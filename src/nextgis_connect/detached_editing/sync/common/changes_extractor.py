import itertools
import sqlite3
from typing import Any, Dict, Iterable, List, Set, Tuple, Union

from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, QTime

from nextgis_connect.detached_editing.container.editing import (
    ContainerReadOnlySession,
)
from nextgis_connect.detached_editing.serialization import (
    simplify_value,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureChange,
    FeatureCreation,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerContext,
    FeatureMetadata,
    detached_layer_uri,
)
from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    SynchronizationError,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.types import FeatureId, FieldId, Unset, UnsetType


class ChangesExtractor:
    """
    Extracts various types of changes from a detached editing container.
    """

    _context: DetachedContainerContext
    _layer: QgsVectorLayer

    def __init__(self, context: DetachedContainerContext) -> None:
        """Initialize extractor with a detached container context.

        :param context: Detached container context used to access
            metadata and the container database.
        """
        self._context = context
        self._layer = QgsVectorLayer(detached_layer_uri(self._context))

    def extract_features_changes(self) -> List[FeatureChange]:
        """Collect all feature-related changes from the container.

        :return: List of container data change objects representing
            added, updated, deleted and restored features.
        """
        added_features = self.extract_added_features()
        updated_features = self.extract_updated_features()
        deleted_features = self.extract_deleted_features()
        restored_features = self.extract_restored_features()

        result = itertools.chain(
            added_features,
            updated_features,
            deleted_features,
            restored_features,
        )
        return list(result)

    def extract_all_changes(self) -> List[FeatureChange]:
        """Collect all changes from the container, including feature and
        attachment changes as well as description updates.

        :return: List of container data change objects representing all
            types of changes in the container.
        """
        added_features = self.extract_added_features()
        updated_features = self.extract_updated_features()
        deleted_features = self.extract_deleted_features()
        restored_features = self.extract_restored_features()
        descriptions_changes = self.extract_updated_descriptions()
        added_attachments = self.extract_added_attachments()
        updated_attachments = self.extract_updated_attachments()
        deleted_attachments = self.extract_deleted_attachments()
        restored_attachments = self.extract_restored_attachments()

        result = itertools.chain(
            added_features,
            updated_features,
            deleted_features,
            restored_features,
            descriptions_changes,
            added_attachments,
            updated_attachments,
            deleted_attachments,
            restored_attachments,
        )
        return list(result)

    def extract_added_features(self) -> List[FeatureCreation]:
        """Extract features that were added to the detached container.

        :return: List of `FeatureCreation` changes containing local
            feature ids, serialized geometry and field values.
        """
        added_features_id: List[FeatureId] = []
        with ContainerReadOnlySession(self._context) as cursor:
            added_features_id = [
                feature_id
                for (feature_id,) in cursor.execute(
                    "SELECT fid from ngw_added_features"
                )
            ]

        creation_changes: List[FeatureCreation] = []
        request = QgsFeatureRequest(added_features_id)
        for feature in self._layer.getFeatures(request):  # type: ignore
            fid = feature.id()

            fields_values: List[Tuple[FieldId, Any]] = []
            for field in self._context.metadata.fields:
                value = simplify_value(feature.attribute(field.attribute))
                if value is None:
                    continue
                self.__check_value(field, value)
                fields_values.append((field.ngw_id, value))

            geometry = self.__extract_geometry(feature)

            creation_changes.append(
                FeatureCreation(
                    fid=fid,
                    fields=fields_values or Unset,
                    geometry=geometry or Unset,
                )
            )

        if len(added_features_id) != len(creation_changes):
            error = ContainerError("Not all changes were created")
            error.add_note(f"New features count: {len(added_features_id)}")
            error.add_note(f"Changes count: {len(creation_changes)}")
            raise error

        return creation_changes

    def extract_updated_features(self) -> List[FeatureUpdate]:
        """Extract features that were updated in the detached container.

        :return: List of `FeatureUpdate` changes with NGW feature ids,
            updated fields, serialized geometry (if changed) and
            version (for versioning-enabled containers).
        """
        # Collect information about updated features

        attributes_query = "SELECT fid, attribute from ngw_updated_attributes"
        geoms_query = "SELECT fid from ngw_updated_geometries"

        updated_feature_attributes: Dict[FeatureId, Set[FieldId]] = {}
        updated_feature_geoms: Set[FeatureId] = set()

        all_updated_fids: List[FeatureId] = []
        features_metadata: Dict[FeatureId, FeatureMetadata] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            for fid, attribute in cursor.execute(attributes_query):
                if fid not in updated_feature_attributes:
                    updated_feature_attributes[fid] = set()
                updated_feature_attributes[fid].add(attribute)

            updated_feature_geoms = set(
                feature_id for (feature_id,) in cursor.execute(geoms_query)
            )

            all_updated_fids = list(
                set(updated_feature_attributes.keys()) | updated_feature_geoms
            )
            if len(all_updated_fids) == 0:
                return []

            features_metadata = self.__features_metadata(
                cursor, all_updated_fids
            )

        update_changes: List[FeatureUpdate] = []

        request = QgsFeatureRequest(all_updated_fids)
        for feature in self._layer.getFeatures(request):  # type: ignore
            feature_metadata = features_metadata[feature.id()]
            ngw_fid = feature_metadata.ngw_fid
            assert ngw_fid is not None
            version = feature_metadata.version

            # Collect updated geometry
            geometry = (
                self.__extract_geometry(feature)
                if feature_metadata.fid in updated_feature_geoms
                else Unset
            )

            # Collect updated fields
            fields = self._context.metadata.fields
            fields_values = []
            for attribute_id in updated_feature_attributes.get(
                feature.id(), set()
            ):
                field = fields.get_with(attribute=attribute_id)
                value = simplify_value(feature.attribute(attribute_id))
                self.__check_value(field, value)
                fields_values.append((field.ngw_id, value))
            if not fields_values:
                fields_values = Unset

            # Create update change
            update_changes.append(
                FeatureUpdate(
                    fid=feature_metadata.fid,
                    ngw_fid=ngw_fid,
                    fields=fields_values,
                    geometry=geometry,
                    version=version or Unset,
                )
            )

        return update_changes

    def extract_deleted_features(self) -> List[FeatureDeletion]:
        """Extract features that were deleted locally in the container.

        :return: List of `FeatureDeletion` changes containing NGW
            feature ids to be deleted on the server.
        """
        query = """
            SELECT
                feature_metadata.fid,
                feature_metadata.ngw_fid,
                feature_metadata.version
            FROM ngw_removed_features removed
            LEFT JOIN ngw_features_metadata feature_metadata
                ON feature_metadata.fid = removed.fid
        """

        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            result = [
                FeatureDeletion(
                    fid=fid,
                    ngw_fid=ngw_fid,
                    version=version,
                )
                for (fid, ngw_fid, version) in cursor.execute(query)
            ]

        return result

    def extract_restored_features(self) -> List[FeatureRestoration]:
        """Extract features deleted on the server and restored locally in the
        container.

        :return: List of `FeatureRestoration` changes including NGW fid,
            fields, geometry and version.
        """
        if not self._context.metadata.is_versioning_enabled:
            return []

        restored_features_id: List[FeatureId] = []
        features_metadata: Dict[FeatureId, FeatureMetadata] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            restored_features_id = [
                ngw_feature_id
                for (ngw_feature_id,) in cursor.execute(
                    "SELECT fid from ngw_restored_features"
                )
            ]
            features_metadata = self.__features_metadata(
                cursor, restored_features_id
            )

        restoration_changes = []
        request = QgsFeatureRequest(restored_features_id)
        for feature in self._layer.getFeatures(request):  # type: ignore
            fid = feature.id()

            geometry = self.__extract_geometry(feature)

            fields_values = []
            for field in self._context.metadata.fields:
                value = simplify_value(feature.attribute(field.attribute))
                if value is None:
                    continue
                self.__check_value(field, value)
                fields_values.append((field.ngw_id, value))

            ngw_fid = features_metadata[fid].ngw_fid
            version = features_metadata[fid].version
            assert ngw_fid is not None

            restoration_changes.append(
                FeatureRestoration(
                    fid=fid,
                    ngw_fid=ngw_fid,
                    fields=fields_values,
                    geometry=geometry,
                    version=version or Unset,
                )
            )

        if len(restored_features_id) != len(restoration_changes):
            error = ContainerError("Not all changes were created")
            error.add_note(
                f"Restored features count: {len(restored_features_id)}"
            )
            error.add_note(f"Changes count: {len(restoration_changes)}")
            raise error

        return restoration_changes

    def extract_updated_descriptions(self) -> List[DescriptionPut]:
        """Extract description updates for features.

        :return: List of `DescriptionPut` changes including either the NGW
            feature id (when available) or the local fid, the
            description text, description version (for versioning-enabled
            containers) and a flag indicating whether the feature is new.
        """
        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            query = """
                SELECT
                    metadata.fid,
                    metadata.ngw_fid,
                    descriptions.version,
                    descriptions.description
                FROM ngw_updated_descriptions AS updated
                LEFT JOIN ngw_features_descriptions AS descriptions
                    ON updated.fid = descriptions.fid
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = descriptions.fid
            """
            result = [
                DescriptionPut(
                    fid=fid,
                    ngw_fid=ngw_fid,
                    description=description,
                    version=version or Unset,
                )
                for fid, ngw_fid, version, description in cursor.execute(query)
            ]

        return result

    def extract_added_attachments(self) -> List[AttachmentCreation]:
        """Extract attachments that were added in the container.

        :return: List of `AttachmentCreation` changes containing either
            the NGW feature id (when available) or the local fid, local
            attachment id, name, description and keyname.
        """
        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            query = """
                SELECT
                    metadata.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.name,
                    attachments.description,
                    attachments.keyname,
                    attachments.mime_type
                FROM ngw_added_attachments
                LEFT JOIN ngw_features_attachments as attachments
                    ON attachments.aid = ngw_added_attachments.aid
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
            """
            result = [
                AttachmentCreation(
                    fid=fid,
                    aid=aid,
                    ngw_fid=ngw_fid,
                    name=name,
                    description=description,
                    keyname=keyname,
                    mime_type=mime_type,
                )
                for (
                    fid,
                    ngw_fid,
                    aid,
                    name,
                    description,
                    keyname,
                    mime_type,
                ) in cursor.execute(query)
            ]

        return result

    def extract_deleted_attachments(self) -> List[AttachmentDeletion]:
        """Extract attachments that were removed from the container.

        :return: List of `AttachmentDeletion` changes with NGW feature
            id, attachment id and version.
        """
        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            query = """
                SELECT
                    metadata.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.ngw_aid,
                    attachments.fileobj,
                    attachments.version
                FROM ngw_removed_attachments
                LEFT JOIN ngw_features_attachments AS attachments
                    ON attachments.aid = ngw_removed_attachments.aid
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
            """
            result = [
                AttachmentDeletion(
                    fid=fid,
                    aid=aid,
                    ngw_fid=ngw_fid,
                    ngw_aid=ngw_aid,
                    fileobj=fileobj,
                    version=version or Unset,
                )
                for (
                    fid,
                    ngw_fid,
                    aid,
                    ngw_aid,
                    fileobj,
                    version,
                ) in cursor.execute(query)
            ]

        return result

    def extract_updated_attachments(self) -> List[AttachmentUpdate]:
        """Extract attachments that were modified in the container.

        :return: List of `AttachmentUpdate` changes including NGW
            feature id, NGW attachment id, version (for versioning-enabled
            containers) and updated metadata fields.
        """
        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            query = """
                SELECT
                    metadata.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.ngw_aid,
                    attachments.version,
                    attachments.name,
                    attachments.description,
                    attachments.keyname,
                    attachments.mime_type,
                    attachments.fileobj
                FROM ngw_updated_attachments
                LEFT JOIN ngw_features_attachments AS attachments
                    ON attachments.aid = ngw_updated_attachments.aid
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
            """
            result = [
                AttachmentUpdate(
                    fid=fid,
                    aid=aid,
                    ngw_fid=ngw_fid,
                    ngw_aid=ngw_aid,
                    version=version,
                    name=name,
                    description=description,
                    fileobj=fileobj,
                    mime_type=mime_type if fileobj is None else Unset,
                    keyname=keyname or Unset,
                )
                for (
                    fid,
                    ngw_fid,
                    aid,
                    ngw_aid,
                    version,
                    name,
                    description,
                    keyname,
                    mime_type,
                    fileobj,
                ) in cursor.execute(query)
            ]

        return result

    def extract_restored_attachments(self) -> List[AttachmentRestoration]:
        """Extract attachments that were deleted on the server and restored
        locally.

        :return: List of `AttachmentRestoration` changes including NGW feature
        id, NGW attachment id, version and metadata fields.
        """
        if not self._context.metadata.is_versioning_enabled:
            return []

        result = []
        with ContainerReadOnlySession(self._context) as cursor:
            query = """
                SELECT
                    metadata.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.ngw_aid,
                    attachments.name,
                    attachments.description,
                    attachments.keyname,
                    attachments.fileobj,
                    attachments.mime_type,
                    attachments.version
                FROM ngw_restored_attachments
                LEFT JOIN ngw_features_attachments as attachments
                    ON attachments.aid = ngw_restored_attachments.aid
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
            """
            result = [
                AttachmentRestoration(
                    fid=fid,
                    aid=aid,
                    ngw_fid=ngw_fid,
                    ngw_aid=ngw_aid,
                    name=name,
                    description=description,
                    keyname=keyname,
                    fileobj=fileobj,
                    mime_type=mime_type if fileobj is None else Unset,
                    version=version,
                )
                for (
                    fid,
                    ngw_fid,
                    aid,
                    ngw_aid,
                    name,
                    description,
                    keyname,
                    fileobj,
                    mime_type,
                    version,
                ) in cursor.execute(query)
            ]

        return result

    def __features_metadata(
        self, cursor: sqlite3.Cursor, fids: Iterable[FeatureId]
    ) -> Dict[FeatureId, FeatureMetadata]:
        fids_list = list(fids)
        if not fids_list:
            return {}

        all_fids_joined = ",".join(str(fid) for fid in fids_list)

        features_metadata = {
            row[0]: FeatureMetadata(fid=row[0], ngw_fid=row[1], version=row[2])
            for row in cursor.execute(
                f"""
                    SELECT fid, ngw_fid, version
                    FROM ngw_features_metadata
                    WHERE fid IN ({all_fids_joined})
                """
            )
        }
        return features_metadata

    def __extract_geometry(
        self, feature: QgsFeature
    ) -> Union[QgsGeometry, UnsetType]:
        geometry = feature.geometry()
        return geometry if geometry is not None else Unset

    def __check_value(self, field: NgwField, value: Any) -> None:
        if field.datatype != NgwDataType.TIME or value is None:
            return

        time = QTime.fromString(value, Qt.DateFormat.ISODate)
        if time.isValid():
            return

        error = SynchronizationError(
            "Invalid time format", code=ErrorCode.ValueFormatError
        )
        error.add_note(f"Field: {field.keyname}")
        error.add_note(f"Value: {value}")
        raise error
