import itertools
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsVectorLayer,
)

from nextgis_connect.detached_editing.serialization import (
    serialize_geometry,
    simplify_value,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
    detached_layer_uri,
)
from nextgis_connect.exceptions import ContainerError

from .actions import (
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureId,
    FeatureRestoreAction,
    FeatureUpdateAction,
    VersioningAction,
)


class ActionExtractor:
    """
    Extracts various types of actions from a detached editing container.
    """

    __container_path: Path
    __metadata: DetachedContainerMetaData
    __layer: QgsVectorLayer

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata
        self.__layer = QgsVectorLayer(
            detached_layer_uri(container_path, metadata)
        )

    def extract_all(self) -> List[VersioningAction]:
        added_features = self.extract_added_features()
        deleted_features = self.extract_deleted_features()
        restored_features = self.extract_restored_features()
        restored_features = self.extract_restored_features()
        updated_features = self.extract_updated_features()

        actions = itertools.chain(
            added_features,
            deleted_features,
            restored_features,
            updated_features,
        )
        return list(actions)

    def extract_added_features(self) -> List[FeatureCreateAction]:
        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                added_features_id = [
                    row[0]
                    for row in cursor.execute(
                        "SELECT fid from ngw_added_features"
                    )
                ]
        except Exception as error:
            raise ContainerError from error

        create_actions = []
        request = QgsFeatureRequest(added_features_id)
        for feature in self.__layer.getFeatures(request):  # type: ignore
            fid = feature.id()
            geom = self.__serialize_geometry(feature.geometry())
            fields_values = []
            for field in self.__metadata.fields:
                value = simplify_value(feature.attribute(field.attribute))
                if value is None:
                    continue
                fields_values.append([field.ngw_id, value])

            create_actions.append(
                FeatureCreateAction(fid, None, geom, fields_values)
            )

        return create_actions

    def extract_updated_features(self) -> List[FeatureUpdateAction]:
        # Collect information about updated features

        attributes_query = "SELECT fid, attribute from ngw_updated_attributes"
        geoms_query = "SELECT fid from ngw_updated_geometries"

        updated_feature_attributes: Dict[FeatureId, Set[int]] = {}
        updated_feature_geoms: Set[FeatureId] = set()

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                for fid, attribute in cursor.execute(attributes_query):
                    if fid not in updated_feature_attributes:
                        updated_feature_attributes[fid] = set()
                    updated_feature_attributes[fid].add(attribute)

                updated_feature_geoms = set(
                    row[0] for row in cursor.execute(geoms_query)
                )

                all_updated_fids = list(
                    set(updated_feature_attributes.keys())
                    | updated_feature_geoms
                )
                if len(all_updated_fids) == 0:
                    return []

                features_metadata = self.__features_metadata(
                    cursor, all_updated_fids
                )

        except Exception as error:
            raise ContainerError from error

        updated_actions: List[FeatureUpdateAction] = []

        request = QgsFeatureRequest(all_updated_fids)
        for feature in self.__layer.getFeatures(request):  # type: ignore
            feature_metadata = features_metadata[feature.id()]
            ngw_fid = feature_metadata.ngw_fid
            assert ngw_fid is not None
            vid = feature_metadata.version

            geom = (
                self.__serialize_geometry(feature.geometry())
                if feature_metadata.fid in updated_feature_geoms
                else None
            )

            fields = self.__metadata.fields

            fields_values = []
            for attribute_id in updated_feature_attributes.get(
                feature.id(), set()
            ):
                fields_values.append(
                    [
                        fields.get_with(attribute=attribute_id).ngw_id,
                        simplify_value(feature.attribute(attribute_id)),
                    ]
                )

            updated_actions.append(
                FeatureUpdateAction(ngw_fid, vid, geom, fields_values)
            )

        return updated_actions

    def extract_deleted_features(self) -> List[FeatureDeleteAction]:
        query = """
            SELECT feature_metadata.ngw_fid
            FROM ngw_removed_features removed
            LEFT JOIN ngw_features_metadata feature_metadata
                ON feature_metadata.fid = removed.fid
            """

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                return [
                    FeatureDeleteAction(row[0])
                    for row in cursor.execute(query)
                ]

        except Exception as error:
            raise ContainerError from error

    def extract_restored_features(self) -> List[FeatureRestoreAction]:
        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                restored_features_id = [
                    row[0]
                    for row in cursor.execute(
                        "SELECT fid from ngw_restored_features"
                    )
                ]
                features_metadata = self.__features_metadata(
                    cursor, restored_features_id
                )
        except Exception as error:
            raise ContainerError from error

        restore_actions = []
        request = QgsFeatureRequest(restored_features_id)
        for feature in self.__layer.getFeatures(request):  # type: ignore
            fid = feature.id()
            geom = self.__serialize_geometry(feature.geometry())
            fields_values = []
            for field in self.__metadata.fields:
                value = simplify_value(feature.attribute(field.attribute))
                if value is None:
                    continue
                fields_values.append([field.ngw_id, value])

            ngw_fid = features_metadata[fid].ngw_fid
            version = features_metadata[fid].version
            assert ngw_fid is not None

            restore_actions.append(
                FeatureRestoreAction(ngw_fid, version, geom, fields_values)
            )

        return restore_actions

    def __features_metadata(
        self, cursor: sqlite3.Cursor, fids: Iterable[FeatureId]
    ) -> Dict[FeatureId, FeatureMetaData]:
        all_fids_joined = ",".join(str(fid) for fid in fids)

        features_metadata = {
            row[0]: FeatureMetaData(fid=row[0], ngw_fid=row[1], version=row[2])
            for row in cursor.execute(
                f"""
                    SELECT fid, ngw_fid, version
                    FROM ngw_features_metadata
                    WHERE fid IN ({all_fids_joined})
                """
            )
        }
        return features_metadata

    def __serialize_geometry(self, geometry: Optional[QgsGeometry]) -> str:
        return serialize_geometry(
            geometry, self.__metadata.is_versioning_enabled
        )
