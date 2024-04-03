import sqlite3
from base64 import b64decode
from typing import Any, Dict, List, Optional, Tuple, Union

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
)
from nextgis_connect.logging import logger
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
    __layer_metadata: DetachedContainerMetaData
    __cursor: sqlite3.Cursor
    __fields: Dict[FieldId, NgwField]

    def __init__(
        self, layer_metadata: DetachedContainerMetaData, cursor: sqlite3.Cursor
    ) -> None:
        self.__layer_metadata = layer_metadata
        self.__cursor = cursor
        self.__fields = {
            field.ngw_id: field for field in layer_metadata.fields
        }

    def apply(self, actions: List[VersioningAction]) -> bool:
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
            applier_for_action[action.action](action)  # type: ignore

        return True

    def __create_feature(self, action: FeatureCreateAction) -> None:
        table_name = self.__layer_metadata.table_name

        fields_placeholder, values_placeholder, values_list = (
            self.__feature_placeholders(action)
        )

        self.__cursor.execute(
            f"""
            INSERT INTO '{table_name}' ({fields_placeholder})
            VALUES ({values_placeholder})
            """,
            (*values_list,),
        )
        fid = self.__cursor.lastrowid
        self.__cursor.execute(
            "INSERT INTO ngw_features_metadata VALUES (?, ?, ?, NULL)",
            (fid, action.fid, action.vid),
        )

    def __update_feature(self, action: FeatureUpdateAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            logger.error(f"Feature with fid={action.fid} is not exist")
            return

        table_name = self.__layer_metadata.table_name
        fields_placeholder, values_placeholder, values_list = (
            self.__feature_placeholders(action)
        )

        placeholder = ", ".join(
            f"{key}={value}"
            for key, value in zip(fields_placeholder, values_placeholder)
        )

        self.__cursor.execute(
            f"UPDATE '{table_name}' SET {placeholder} WHERE fid=?",
            (*values_list, feature_metadata.fid),
        )
        self.__cursor.execute(
            "UPDATE ngw_features_metadata SET version=? WHERE ngw_fid=?",
            (action.vid, feature_metadata.ngw_fid),
        )

    def __delete_feature(self, action: FeatureDeleteAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            logger.error(f"Feature with fid={action.fid} is not exist")
            return

        table_name = self.__layer_metadata.table_name
        self.__cursor.execute(
            f"""
            DELETE FROM '{table_name}' WHERE fid={feature_metadata.fid}
            DELETE FROM ngw_features_metadata WHERE fid={feature_metadata.fid}
            """
        )

    def __put_description(self, action: DescriptionPutAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            logger.error(f"Feature with fid={action.fid} is not exist")
            return

        self.__cursor.execute(
            "UPDATE ngw_features_metadata SET description=? WHERE ngw_fid=?",
            (action.value, feature_metadata.ngw_fid),
        )

    def __create_attachment(self, action: AttachmentCreateAction) -> None:
        pass

    def __update_attachment(self, action: AttachmentUpdateAction) -> None:
        pass

    def __delete_attachment(self, action: AttachmentDeleteAction) -> None:
        pass

    def __continue(self, action: ContinueAction) -> None:
        pass

    def __feature_placeholders(
        self, action: Union[FeatureCreateAction, FeatureUpdateAction]
    ) -> Tuple[str, str, List[Any]]:
        fields_list: List[str] = [
            self.__fields[field[0]].keyname for field in action.fields
        ]
        values_list: List[Any] = [field[1] for field in action.fields]
        if action.geom is not None:
            fields_list.append("geom")
            values_list.append(b64decode(action.geom))

        fields_placeholder = ", ".join(fields_list)
        values_placeholder = ", ".join("?" for _ in values_list)

        if action.geom is not None:
            values_placeholder = values_placeholder[:-1] + "GeomFromWKB(?)"

        return fields_placeholder, values_placeholder, values_list

    def __get_feature_metadata(
        self, *, ngw_fid: FeatureId
    ) -> Optional[FeatureMetaData]:
        self.__cursor.execute(
            "SELECT * FROM ngw_features_metadata WHERE ngw_fid=?", (ngw_fid,)
        )
        result = [FeatureMetaData(*row) for row in self.__cursor.fetchall()]
        assert len(result) <= 1
        return result[0] if len(result) == 1 else None
