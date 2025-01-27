import sqlite3
from base64 import b64decode
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Set, Tuple

from qgis.core import (
    QgsEditError,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
    edit,
)
from qgis.PyQt.QtCore import QObject, pyqtSlot

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
)
from nextgis_connect.exceptions import (
    ContainerError,
    LayerEditError,
    NgConnectError,
    SynchronizationError,
)

from .actions import (
    ActionType,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    ContinueAction,
    DescriptionPutAction,
    FeatureAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureId,
    FeatureUpdateAction,
)


class ActionApplier(QObject):
    __container_path: Path
    __layer: QgsVectorLayer
    __metadata: DetachedContainerMetaData

    __commands: List[Tuple[str, Tuple]]
    __create_command_ids: List

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        super().__init__()

        self.__container_path = container_path
        self.__metadata = metadata
        layer_path = f"{container_path}|layername={metadata.table_name}"
        self.__layer = QgsVectorLayer(layer_path)

        self.__commands = []
        self.__create_command_ids = []

    def apply(self, actions: List[FeatureAction]) -> None:
        if len(actions) == 0:
            return

        try:
            self.__layer.committedFeaturesAdded.connect(
                self.__update_create_commands
            )
            self.__apply_actions(actions)

        except NgConnectError:
            raise

        except sqlite3.Error as error:
            raise ContainerError from error

        except QgsEditError as error:
            raise SynchronizationError from LayerEditError.from_qgis_error(
                error
            )

        except Exception as error:
            raise SynchronizationError from error

        finally:
            self.__commands = []
            self.__create_command_ids = []

            self.__layer.committedFeaturesAdded.disconnect(
                self.__update_create_commands
            )

    def __apply_actions(self, actions: List[FeatureAction]) -> None:
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

        previously_added, previously_deleted = (
            self.__extract_previously_uploaded(actions)
        )

        with edit(self.__layer):
            for action in actions:
                params = (action,)

                if action.action == ActionType.FEATURE_CREATE:
                    params = (action, previously_added)
                elif action.action == ActionType.FEATURE_DELETE:
                    params = (action, previously_deleted)

                applier_for_action[action.action](*params)

        with closing(
            sqlite3.connect(str(self.__container_path))
        ) as connection, closing(connection.cursor()) as cursor:
            for command in self.__commands:
                cursor.execute(*command)

            connection.commit()

    def __extract_previously_uploaded(
        self, actions: List[FeatureAction]
    ) -> Tuple[Set[FeatureId], Set[FeatureId]]:
        if not self.__metadata.is_versioning_enabled:
            return (set(), set())

        added_ngw_fids = set()
        deleted_ngw_fids = set()

        for action in actions:
            if isinstance(action, FeatureCreateAction):
                added_ngw_fids.add(action.fid)
            if isinstance(action, FeatureDeleteAction):
                deleted_ngw_fids.add(action.fid)

        if len(added_ngw_fids) == 0 and len(deleted_ngw_fids) == 0:
            return (set(), set())

        already_added = set()
        already_deleted = set()

        with closing(
            sqlite3.connect(str(self.__container_path))
        ) as connection, closing(connection.cursor()) as cursor:
            if len(added_ngw_fids) > 0:
                added_fids = ",".join(str(fid) for fid in added_ngw_fids)
                already_added = set(
                    row[0]
                    for row in cursor.execute(
                        f"""
                        SELECT ngw_fid FROM ngw_features_metadata
                            WHERE ngw_fid IN ({added_fids})
                        """
                    )
                )

            if len(deleted_ngw_fids) > 0:
                deleted_fids = ",".join(str(fid) for fid in deleted_ngw_fids)
                still_existed = set(
                    row[0]
                    for row in cursor.execute(
                        f"""
                        SELECT ngw_fid FROM ngw_features_metadata
                            WHERE ngw_fid IN ({deleted_fids})
                        """
                    )
                )
                already_deleted = deleted_ngw_fids - still_existed

        return (already_added, already_deleted)

    def __create_feature(
        self,
        action: FeatureCreateAction,
        previously_added: Set[FeatureId],
    ) -> None:
        # Update version if feature were added in previous sync
        if action.fid in previously_added:
            self.__commands.append(
                (
                    "UPDATE ngw_features_metadata SET version=? WHERE ngw_fid=?",
                    (action.vid, action.fid),
                )
            )
            return

        fields = self.__metadata.fields

        # Create new feature
        new_feature = QgsFeature(self.__layer.fields())
        for field_ngw_id, value in action.fields:
            attribute = fields.get_with(ngw_id=field_ngw_id).attribute
            new_feature.setAttribute(attribute, value)
        new_feature.setGeometry(self.__deserialize_geometry(action.geom))

        is_success = self.__layer.addFeature(new_feature)
        if not is_success:
            raise SynchronizationError("Can't add feature")

        # Create metadata for feature
        self.__create_command_ids.append(len(self.__commands))
        self.__commands.append(
            (
                "INSERT INTO ngw_features_metadata VALUES (?, ?, ?, NULL)",
                (action.fid, action.vid),
            )
        )

    def __update_feature(self, action: FeatureUpdateAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        assert feature_metadata.fid is not None

        fields = self.__metadata.fields

        # Update fields
        fields_values = {
            fields.get_with(ngw_id=ngw_field_id).attribute: value
            for ngw_field_id, value in action.fields
        }
        if len(fields_values) > 0:
            is_success = self.__layer.changeAttributeValues(
                feature_metadata.fid, fields_values
            )
            if not is_success:
                raise SynchronizationError("Can't update fields")

        # Update geometry
        if action.geom is not None:
            geom = self.__deserialize_geometry(action.geom)
            is_success = self.__layer.changeGeometry(
                feature_metadata.fid, geom
            )
            if not is_success:
                raise SynchronizationError("Can't update geometry")

        # Update feature metadata
        self.__commands.append(
            (
                "UPDATE ngw_features_metadata SET version=? WHERE ngw_fid=?",
                (action.vid, feature_metadata.ngw_fid),
            )
        )

    def __delete_feature(
        self, action: FeatureDeleteAction, previously_deleted: Set[FeatureId]
    ) -> None:
        if action.fid in previously_deleted:
            return

        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        assert feature_metadata.fid is not None

        # Delete feature
        is_success = self.__layer.deleteFeature(feature_metadata.fid)
        if not is_success:
            raise SynchronizationError(
                f"Can't delete feature with fid={feature_metadata.fid}"
            )

        # Delete feature metadata
        self.__commands.append(
            (
                "DELETE FROM ngw_features_metadata WHERE fid=?",
                (feature_metadata.fid,),
            )
        )

    def __put_description(self, action: DescriptionPutAction) -> None:
        feature_metadata = self.__get_feature_metadata(ngw_fid=action.fid)
        if feature_metadata is None:
            message = f"Feature with fid={action.fid} is not exist"
            raise SynchronizationError(message)

        self.__commands.append(
            (
                "UPDATE ngw_features_metadata SET description=? WHERE ngw_fid=?",
                (action.value, action.fid),
            )
        )

    def __create_attachment(self, action: AttachmentCreateAction) -> None:
        pass

    def __update_attachment(self, action: AttachmentUpdateAction) -> None:
        pass

    def __delete_attachment(self, action: AttachmentDeleteAction) -> None:
        pass

    def __continue(self, action: ContinueAction) -> None:
        pass

    def __deserialize_geometry(self, geom: Optional[str]) -> QgsGeometry:
        if geom is None or geom == "":
            return QgsGeometry()

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

    @pyqtSlot(str, "QgsFeatureList")
    def __update_create_commands(
        self, _: str, features: List[QgsFeature]
    ) -> None:
        for command_id, feature in zip(self.__create_command_ids, features):
            command = self.__commands[command_id]
            self.__commands[command_id] = (
                command[0],
                (feature.id(), *command[1]),
            )
