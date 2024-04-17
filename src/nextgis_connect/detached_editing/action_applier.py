import sqlite3
from base64 import b64decode
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
)
from nextgis_connect.exceptions import ContainerError, SynchronizationError
from nextgis_connect.resources.ngw_field import FieldId, NgwField

from .actions import (
    ActionType,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    ContinueAction,
    DescriptionPutAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureId,
    FeatureUpdateAction,
    VersioningAction,
)


class ActionApplier:
    __container_path: Path
    __layer: QgsVectorLayer
    __metadata: DetachedContainerMetaData
    __fields: Dict[FieldId, NgwField]

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata
        layer_path = f"{container_path}|layername={metadata.table_name}"
        self.__layer = QgsVectorLayer(layer_path)

        self.__fields = {field.ngw_id: field for field in metadata.fields}

    def apply(self, actions: List[VersioningAction]) -> None:
        applier_for_action = {
            ActionType.FEATURE_CREATE: self.__create_feature,
            ActionType.FEATURE_UPDATE: self.__update_feature,
            ActionType.FEATURE_DELETE: self.__delete_feature,
            ActionType.DESCRIPTION_PUT: self.__put_description,
            ActionType.ATTACHMENT_CREATE: self.__create_attachment,
            ActionType.ATTACHMENT_UPDATE: self.__update_attachment,
            ActionType.ATTACHMENT_DELETE: self.__delete_attachment,
            ActionType.CONTINUE: self.__continue,
        }

        for action in actions:
            applier_for_action[action.action](action)

    def __create_feature(self, action: FeatureCreateAction) -> None:
        new_feature = QgsFeature(self.__layer.fields())

        for field_id, value in action.fields:
            attribute = self.__fields[field_id].attribute
            new_feature.setAttribute(attribute, value)

        new_feature.setGeometry(self.__deserialize_geometry(action.geom))

        is_success, result = self.__layer.dataProvider().addFeatures(
            [new_feature]
        )
        if not is_success:
            raise SynchronizationError("Can't add feature")

        fid = result[0].id()

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    "INSERT INTO ngw_features_metadata VALUES (?, ?, ?, NULL)",
                    (fid, action.fid, action.vid),
                )
                connection.commit()

        except Exception as error:
            raise ContainerError from error

    def __update_feature(self, action: FeatureUpdateAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        fields = {
            self.__fields[field_id].attribute: value
            for field_id, value in action.fields
        }
        if len(fields) > 0:
            is_success = self.__layer.dataProvider().changeAttributeValues(
                {feature_metadata.fid: fields}
            )
            if not is_success:
                raise SynchronizationError("Can't update fields")

        if action.geom is not None:
            geom = self.__deserialize_geometry(action.geom)
            is_success = self.__layer.dataProvider().changeGeometryValues(
                {feature_metadata.fid: geom}
            )
            if not is_success:
                raise SynchronizationError("Can't update geometry")

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    "UPDATE ngw_features_metadata SET version=? WHERE ngw_fid=?",
                    (action.vid, feature_metadata.ngw_fid),
                )
                connection.commit()

        except Exception as error:
            raise ContainerError from error

    def __delete_feature(self, action: FeatureDeleteAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        self.__layer.dataProvider().deleteFeatures([feature_metadata.fid])

        query = f"""
            DELETE FROM ngw_features_metadata
            WHERE fid={feature_metadata.fid}
        """

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(query)
                connection.commit()

        except Exception as error:
            raise ContainerError from error

    def __put_description(self, action: DescriptionPutAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        query = (
            "UPDATE ngw_features_metadata SET description=? WHERE ngw_fid=?"
        )
        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(query, (action.value, action.fid))
                connection.commit()

        except Exception as error:
            raise ContainerError from error

    def __create_attachment(self, action: AttachmentCreateAction) -> None:
        pass

    def __update_attachment(self, action: AttachmentUpdateAction) -> None:
        pass

    def __delete_attachment(self, action: AttachmentDeleteAction) -> None:
        pass

    def __continue(self, action: ContinueAction) -> None:
        pass

    def __deserialize_geometry(
        self, geom: Optional[str]
    ) -> Optional[QgsGeometry]:
        if geom is None:
            return None

        geometry = None
        if self.__metadata.is_versioning_enabled:
            geometry = QgsGeometry()
            geometry.fromWkb(b64decode(geom))
        else:
            geometry = QgsGeometry.fromWkt(geom)

        return geometry

    def __get_feature_metadata(
        self, *, ngw_fid: FeatureId
    ) -> Optional[FeatureMetaData]:
        query = f"SELECT * FROM ngw_features_metadata WHERE ngw_fid={ngw_fid}"
        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                result = [
                    FeatureMetaData(*row) for row in cursor.execute(query)
                ]

        except Exception as error:
            raise ContainerError from error

        assert len(result) <= 1, "More than one feature with one ngw_fid"

        return result[0] if len(result) == 1 else None
