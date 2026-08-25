# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import json
import shutil
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsMemoryProviderUtils,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.legacy.detached_editing.container.editing.commands.attachment_add import (
    AttachmentAddCommand,
)
from nextgis_connect.legacy.detached_editing.container.editing.commands.attachment_remove import (
    AttachmentRemoveCommand,
)
from nextgis_connect.legacy.detached_editing.container.editing.commands.attachment_update import (
    AttachmentUpdateCommand,
)
from nextgis_connect.legacy.detached_editing.container.editing.commands.description_update import (
    DescriptionUpdateCommand,
)
from nextgis_connect.legacy.detached_editing.detached_layer_edit_buffer import (
    DetachedLayerEditBuffer,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    deserialize_value,
    serialize_geometry,
    serialize_value,
    simplify_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerMetaData,
    detached_layer_uri,
    is_attachment_new,
    is_feature_new,
    make_connection,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.resources.ngw_field import FieldId
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import (
    QgsAttributeList,
    QgsChangedAttributesMap,
    QgsFeatureId,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    DetachedEditingError,
    ErrorCode,
)
from nextgis_connect.platform.qgis.utils import wrap_sql_value
from nextgis_connect.shared.types import (
    AttachmentId,
    FileObjectId,
    NgwAttachmentId,
    NgwFeatureId,
    Unset,
    UnsetType,
)

if TYPE_CHECKING:
    from .container.container import DetachedContainer


class DetachedLayer(QObject):
    """Class for tracking changes and writing them to a container"""

    UPDATE_STATE_PROPERTY = "ngw_need_update_state"

    __container: "DetachedContainer"
    __qgs_layer: QgsVectorLayer
    __is_structure_changed: bool
    __is_layer_changed: bool
    __errors: List[ContainerError]

    __updated_attributes: Dict[Tuple[QgsFeatureId, FieldId], Any]
    __updated_geometries: Dict[QgsFeatureId, str]
    __deleted_features: Dict[QgsFeatureId, QgsFeature]

    editing_started = pyqtSignal(name="editingStarted")
    editing_finished = pyqtSignal(name="editingFinished")
    layer_changed = pyqtSignal(name="layerChanged")
    structure_changed = pyqtSignal(name="structureChanged")
    settings_changed = pyqtSignal(name="settingsChanged")

    description_updated = pyqtSignal(QgsFeatureId, str)
    attachment_added = pyqtSignal(QgsFeatureId, AttachmentId)
    attachment_updated = pyqtSignal(QgsFeatureId, AttachmentId)
    attachment_removed = pyqtSignal(QgsFeatureId, AttachmentId)

    error_occurred = pyqtSignal(ContainerError, name="errorOccurred")

    def __init__(
        self,
        container: "DetachedContainer",
        layer: QgsVectorLayer,
    ) -> None:
        super().__init__(container)
        self.__container = container
        self.__qgs_layer = layer
        self.__is_structure_changed = False
        self.__is_layer_changed = False
        self.__edit_buffer = None
        self.__commands = []  # Keep increased reference count of commands
        self.__errors = []

        self.__fix_source_if_needed()
        self.__apply_required_constraints()

        self.__reset_backup()

        self.__qgs_layer.editingStarted.connect(self.__start_listen_changes)
        self.__qgs_layer.editingStopped.connect(self.__stop_listen_changes)
        self.__qgs_layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )
        self.__qgs_layer.afterCommitChanges.connect(self.__on_commit_changes)

        self.update()

        if layer.isEditable():
            self.__start_listen_changes()

    @property
    def container(self) -> "DetachedContainer":
        return self.__container

    @property
    def metadata(self) -> DetachedContainerMetaData:
        return self.__container.metadata

    @property
    def qgs_layer(self) -> QgsVectorLayer:
        return self.__qgs_layer

    @property
    def edit_buffer(self) -> Optional[DetachedLayerEditBuffer]:
        """
        Get the edit buffer for the detached layer.
        :return: DetachedLayerEditBuffer instance or None if not in edit mode.
        :rtype: Optional[DetachedLayerEditBuffer]
        """
        return self.__edit_buffer

    @property
    def is_edit_mode_enabled(self) -> bool:
        return self.__qgs_layer.isEditable()

    @pyqtSlot()
    def update(self) -> None:
        """Update detached layer properties"""

        if self.__container.metadata is None:
            return

        properties = {
            "ngw_is_detached_layer": True,
            "ngw_connection_id": self.__container.metadata.connection_id,
            "ngw_instance_id": self.__container.metadata.instance_id,
            "ngw_resource_id": self.__container.metadata.resource_id,
        }

        custom_properties = self.__qgs_layer.customProperties()
        for name, value in properties.items():
            custom_properties.setValue(name, value)

        self.__qgs_layer.customPropertyChanged.disconnect(
            self.__on_custom_property_changed
        )
        self.__qgs_layer.setCustomProperties(custom_properties)
        self.__qgs_layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )

    def update_required_constraints(self) -> None:
        self.__apply_required_constraints()

    @pyqtSlot()
    def enable_fake(self) -> None:
        memory_layer = QgsMemoryProviderUtils.createMemoryLayer(
            self.qgs_layer.name(),
            self.qgs_layer.fields(),
            self.qgs_layer.wkbType(),
            self.qgs_layer.crs(),
        )
        self.qgs_layer.setDataSource(
            memory_layer.source(), self.qgs_layer.name(), "memory"
        )
        self.__apply_required_constraints()
        self.qgs_layer.setReadOnly(True)

    @pyqtSlot()
    def disable_fake(self) -> None:
        self.qgs_layer.setDataSource(
            detached_layer_uri(
                self.__container.path, self.__container.metadata
            ),
            self.qgs_layer.name(),
            "ogr",
        )

    def feature_description(
        self, feature: Union[QgsFeatureId, QgsFeature]
    ) -> Optional[str]:
        """Get feature description from detached layer.

        :param feature: Feature ID or QgsFeature.
        :return: Description string or empty string if not found.
        """
        if isinstance(feature, QgsFeature):
            feature_id = feature.id()
        else:
            feature_id = feature
            self.__assert_existed_feature(feature_id)

        value = None

        if self.__edit_buffer:
            value = self.__edit_buffer.updated_descriptions.get(feature_id)
            if is_feature_new(feature_id):
                return value

        if value is None:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    """
                    SELECT description
                    FROM ngw_features_descriptions
                    WHERE fid = ?;
                    """,
                    (feature_id,),
                )
                rows = cursor.fetchall()
                if rows:
                    value = rows[0][0]

        return value

    def set_feature_description(
        self, feature: Union[QgsFeatureId, QgsFeature], description: str
    ) -> None:
        """Set updated description for a feature.

        :param feature: Feature ID or QgsFeature.
        :param description: New description string.
        """
        self.__assert_edit_buffer_initialized()
        if isinstance(feature, QgsFeature):
            feature_id = feature.id()
        else:
            feature_id = feature
            self.__assert_existed_feature(feature_id)

        command = DescriptionUpdateCommand(
            self,
            feature_id,
            self.feature_description(feature_id),
            description,
        )
        command.setText(
            self.tr("Change feature {} description").format(feature_id)
        )
        self.__commands.append(command)
        self.qgs_layer.undoStack().push(command)

    def feature_attachments_count(
        self, feature: Union[QgsFeatureId, QgsFeature]
    ) -> int:
        """Get the number of attachments for a feature.

        :param feature: Feature ID or QgsFeature.
        :return: Number of attachments.
        """
        if isinstance(feature, QgsFeature):
            feature_id = feature.id()
        else:
            feature_id = feature

        count = 0
        if self.__edit_buffer:
            count += len(
                self.__edit_buffer.added_attachments.get(feature_id, [])
            )
            count -= len(
                self.__edit_buffer.removed_attachments.get(feature_id, set())
            )

        if is_feature_new(feature_id):
            return count

        with closing(make_connection(self.__qgs_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM ngw_features_attachments
                LEFT JOIN ngw_removed_attachments AS removed
                ON ngw_features_attachments.aid = removed.aid
                WHERE fid = ? AND removed.aid IS NULL;
                """,
                (feature_id,),
            )
            rows = cursor.fetchall()
            count += rows[0][0]

        return count

    def feature_attachments(
        self, feature: Union[QgsFeatureId, QgsFeature]
    ) -> List[AttachmentMetadata]:
        if isinstance(feature, QgsFeature):
            feature_id = feature.id()
        else:
            feature_id = feature

        attachments = []
        updated_attachments = {}
        removed_aids = set()

        if self.__edit_buffer:
            attachments.extend(
                self.__edit_buffer.added_attachments.get(
                    feature_id, {}
                ).values()
            )
            removed_aids = self.__edit_buffer.removed_attachments.get(
                feature_id, set()
            )
            updated_attachments = self.__edit_buffer.updated_attachments.get(
                feature_id, {}
            )

        if not is_feature_new(feature_id):
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    """
                    SELECT
                        attachments.aid,
                        attachments.ngw_aid,
                        features.ngw_fid,
                        attachments.keyname,
                        attachments.name,
                        attachments.description,
                        attachments.fileobj,
                        attachments.mime_type,
                        attachments.size
                    FROM ngw_features_attachments AS attachments
                    LEFT JOIN ngw_features_metadata AS features
                    ON attachments.fid = features.fid
                    LEFT JOIN ngw_removed_attachments AS removed
                    ON attachments.aid = removed.aid
                    WHERE attachments.fid = ? AND removed.aid IS NULL;
                    """,
                    (feature_id,),
                )
                rows = cursor.fetchall()
                for row in rows:
                    aid = row[0]
                    if aid in removed_aids:
                        continue
                    elif aid in updated_attachments:
                        attachment = updated_attachments[aid]
                    else:
                        attachment = AttachmentMetadata(
                            fid=feature_id,
                            aid=aid,
                            ngw_aid=row[1],
                            ngw_fid=row[2],
                            keyname=row[3],
                            name=row[4],
                            description=row[5],
                            fileobj=row[6],
                            mime_type=row[7],
                            size=row[8],
                        )
                        attachment = replace(
                            attachment,
                            file_path=self.__attachment_path(attachment),
                            thumbnail_path=self.__attachment_thumbnail_path(
                                attachment
                            ),
                        )

                    attachments.append(attachment)

        attachments.sort(key=lambda attachment: attachment.aid)

        return attachments

    def feature_attachments_for_identification(
        self, feature: Union[QgsFeatureId, QgsFeature]
    ) -> List[AttachmentMetadata]:
        """Return attachments for identification UI.

        The attachment collection is also the only endpoint that exposes
        ``file_meta``. Refresh it for both layer types so image viewers can
        use server-side panorama metadata before downloading the file.
        """
        if isinstance(feature, QgsFeature):
            feature_id = feature.id()
        else:
            feature_id = feature

        remote_attachments: List[AttachmentMetadata] = []
        if not is_feature_new(feature_id):
            try:
                remote_attachments = self.__refresh_feature_attachments(
                    feature_id
                )
            except Exception:
                logger.exception(
                    "Failed to refresh feature attachments from NGW"
                )

        metadata_by_ngw_aid = {
            attachment.ngw_aid: attachment.file_meta
            for attachment in remote_attachments
            if attachment.ngw_aid is not None
        }
        return [
            replace(
                attachment,
                file_meta=(
                    metadata_by_ngw_aid.get(attachment.ngw_aid)
                    if attachment.ngw_aid is not None
                    else None
                ),
            )
            for attachment in self.feature_attachments(feature_id)
        ]

    def feature_attachment(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> Optional[AttachmentMetadata]:
        if self.__edit_buffer:
            if (
                feature_id in self.__edit_buffer.added_attachments
                and attachment_id
                in self.__edit_buffer.added_attachments[feature_id]
            ):
                return self.__edit_buffer.added_attachments[feature_id][
                    attachment_id
                ]

            if (
                feature_id in self.__edit_buffer.updated_attachments
                and attachment_id
                in self.__edit_buffer.updated_attachments[feature_id]
            ):
                return self.__edit_buffer.updated_attachments[feature_id][
                    attachment_id
                ]

            if (
                feature_id in self.__edit_buffer.removed_attachments
                and attachment_id
                in self.__edit_buffer.removed_attachments[feature_id]
            ):
                raise DetachedEditingError(
                    f"Attachment {attachment_id} for feature {feature_id} not "
                    "found in detached layer.",
                    code=ErrorCode.AttachmentNotFound,
                )

        if is_feature_new(feature_id):
            raise DetachedEditingError(
                f"Feature {feature_id} is new and has no attachments "
                "in detached layer.",
                code=ErrorCode.AttachmentNotFound,
            )

        with closing(make_connection(self.__qgs_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    attachments.aid,
                    attachments.ngw_aid,
                    features.ngw_fid,
                    attachments.keyname,
                    attachments.name,
                    attachments.description,
                    attachments.fileobj,
                    attachments.mime_type,
                    attachments.size
                FROM ngw_features_attachments AS attachments
                LEFT JOIN ngw_features_metadata AS features
                ON attachments.fid = features.fid
                LEFT JOIN ngw_removed_attachments AS removed
                ON attachments.aid = removed.aid
                WHERE attachments.fid = ?
                    AND attachments.aid = ?
                    AND removed.aid IS NULL;
                """,
                (feature_id, attachment_id),
            )
            row = cursor.fetchone()
            if row:
                attachment = AttachmentMetadata(
                    fid=feature_id,
                    aid=row[0],
                    ngw_aid=row[1],
                    ngw_fid=row[2],
                    keyname=row[3],
                    name=row[4],
                    description=row[5],
                    fileobj=row[6],
                    mime_type=row[7],
                    size=row[8],
                )
                attachment = replace(
                    attachment,
                    file_path=self.__attachment_path(attachment),
                    thumbnail_path=self.__attachment_thumbnail_path(
                        attachment
                    ),
                )
                return attachment

        raise DetachedEditingError(
            f"Attachment {attachment_id} for feature {feature_id} not "
            "found in detached layer.",
            code=ErrorCode.AttachmentNotFound,
        )

    def attachment_path(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> Optional[Path]:
        attachment = self.feature_attachment(feature_id, attachment_id)
        if attachment is None:
            return None

        return self.__attachment_path(attachment)

    @pyqtSlot(QgsFeatureId, Path)
    def add_attachment(
        self, feature_id: QgsFeatureId, attachment_path: Path
    ) -> AttachmentMetadata:
        self.__assert_edit_buffer_initialized()
        self.__assert_existed_feature(feature_id)

        command = AttachmentAddCommand(self, feature_id, attachment_path)
        command.setText(
            self.tr("Add attachment {}").format(attachment_path.name)
        )
        self.__commands.append(command)
        self.qgs_layer.undoStack().push(command)

        return command.attachment

    @pyqtSlot(QgsFeatureId, AttachmentMetadata)
    def update_attachment(self, attachment: AttachmentMetadata) -> None:
        self.__assert_edit_buffer_initialized()

        old_attachment = self.feature_attachment(
            attachment.fid, attachment.aid
        )
        if old_attachment is None:
            raise DetachedEditingError(
                f"Attachment {attachment.aid} for feature {attachment.fid} not "
                "found in detached layer.",
                code=ErrorCode.AttachmentNotFound,
            )

        command = AttachmentUpdateCommand(self, old_attachment, attachment)
        command.setText(
            self.tr("Update attachment {} for feature {}").format(
                attachment.aid, attachment.fid
            )
        )
        self.__commands.append(command)
        self.qgs_layer.undoStack().push(command)

    @pyqtSlot(QgsFeatureId, AttachmentId)
    def remove_attachment(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> None:
        self.__assert_edit_buffer_initialized()

        attachment = self.feature_attachment(feature_id, attachment_id)
        if attachment is None:
            raise DetachedEditingError(
                f"Attachment {attachment_id} for feature {feature_id} not "
                "found in detached layer.",
                code=ErrorCode.AttachmentNotFound,
            )

        command = AttachmentRemoveCommand(self, attachment)
        command.setText(
            self.tr("Remove attachment {} from feature {}").format(
                attachment_id, feature_id
            )
        )
        self.__commands.append(command)
        self.qgs_layer.undoStack().push(command)

    @pyqtSlot()
    def __start_listen_changes(self) -> None:
        metadata = self.__container.metadata
        logger.debug(f"Start listening changes in layer {metadata}")

        self.__qgs_layer.committedFeaturesAdded.connect(
            self.__log_added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.connect(
            self.__log_removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.connect(
            self.__log_attribute_values_changes
        )
        self.__qgs_layer.committedGeometriesChanges.connect(
            self.__log_geometry_changes
        )

        self.__qgs_layer.committedAttributesAdded.connect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.connect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.connect(self.__create_backup)
        self.__qgs_layer.afterCommitChanges.connect(self.__clear)

        self.__edit_buffer = DetachedLayerEditBuffer(self)

        self.editing_started.emit()

    @pyqtSlot()
    def __stop_listen_changes(self) -> None:
        self.__qgs_layer.committedFeaturesAdded.disconnect(
            self.__log_added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.disconnect(
            self.__log_removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.disconnect(
            self.__log_attribute_values_changes
        )
        self.__qgs_layer.committedGeometriesChanges.disconnect(
            self.__log_geometry_changes
        )

        self.__qgs_layer.committedAttributesAdded.disconnect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.disconnect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.disconnect(self.__create_backup)
        self.__qgs_layer.afterCommitChanges.disconnect(self.__clear)

        self.__clear()
        self.__edit_buffer = None

        metadata = self.__container.metadata
        logger.debug(f"Stop listening changes in layer {metadata}")

        self.editing_finished.emit()

    @pyqtSlot()
    def __clear(self) -> None:
        self.__edit_buffer.clear()
        self.__commands = []
        self.__reset_backup()

    @pyqtSlot(str, "QgsFeatureList")
    def __log_added_features(self, _: str, features: QgsFeatureList) -> None:
        ng_error = None
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                added_fids = ",".join(
                    map(lambda feature: f"({feature.id()})", features)
                )
                cursor.executescript(
                    f"""
                    INSERT INTO ngw_features_metadata (fid) VALUES {added_fids};
                    INSERT INTO ngw_added_features (fid) VALUES {added_fids};
                    """
                )

                connection.commit()

        except Exception as error:
            message = "Can't create adding changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(f"Added {len(features)} features in layer {metadata}")

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsFeatureIds")
    def __log_removed_features(
        self, _: str, removed_feature_ids: QgsFeatureIds
    ) -> None:
        ng_error = None

        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                # Delete added feature fids
                removed_not_uploaded_fids = (
                    self.__extract_intersection_with_added_fids(
                        cursor, removed_feature_ids
                    )
                )
                self.__remove_features_metadata(
                    cursor, removed_not_uploaded_fids
                )

                # Synchronized features
                removed_uploaded_fids = set(removed_feature_ids) - set(
                    removed_not_uploaded_fids
                )
                self.__add_remove_records(cursor, removed_uploaded_fids)

                connection.commit()

        except Exception as error:
            message = "Can't create deletion changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Removed {len(removed_feature_ids)} features in layer {metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsChangedAttributesMap")
    def __log_attribute_values_changes(
        self, _: str, changed_attributes: QgsChangedAttributesMap
    ) -> None:
        ng_error = None
        feature_ids = set()

        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                feature_ids = set(changed_attributes.keys())
                added_fids_intersection = (
                    self.__extract_intersection_with_added_fids(
                        cursor, feature_ids
                    )
                )
                changed_fids = set(feature_ids) - set(added_fids_intersection)
                if len(changed_fids) > 0:
                    cursor.executemany(
                        """
                        INSERT INTO ngw_updated_attributes (fid, attribute, backup)
                        VALUES (?, ?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            (
                                fid,
                                attribute,
                                self.__updated_attributes[(fid, attribute)],
                            )
                            for fid in changed_fids
                            for attribute in changed_attributes[fid]
                        ),
                    )
                    connection.commit()

        except Exception as error:
            message = "Can't create values changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated attributes for {len(feature_ids)} features in layer "
            f"{metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsGeometryMap")
    def __log_geometry_changes(
        self, _: str, changed_geometries: QgsGeometryMap
    ) -> None:
        ng_error = None

        feature_ids: QgsFeatureIds = set()
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                feature_ids = set(changed_geometries.keys())
                added_fids_intersection = (
                    self.__extract_intersection_with_added_fids(
                        cursor, feature_ids
                    )
                )
                changed_fids = set(feature_ids) - set(added_fids_intersection)
                if len(changed_fids) > 0:
                    cursor.executemany(
                        """
                        INSERT INTO ngw_updated_geometries (fid, backup)
                        VALUES (?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            (fid, self.__updated_geometries[fid])
                            for fid in changed_fids
                        ),
                    )
                    connection.commit()

        except Exception as error:
            message = "Can't create geometry changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated geometries for {len(feature_ids)} features in layer "
            f"{metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot()
    def __log_extensions(self) -> None:
        self.__log_description_changes()
        self.__log_added_attachments()
        self.__log_removed_attachments()
        self.__log_updated_attachments()

    def __log_description_changes(self) -> None:
        if not self.__edit_buffer.has_updated_descriptions:
            return

        ng_error = None

        feature_ids: QgsFeatureIds = set()
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                feature_ids = set(
                    self.__edit_buffer.updated_descriptions.keys()
                )
                cursor.executemany(
                    """
                    INSERT INTO ngw_features_descriptions (
                        fid, description
                    )
                    VALUES (?, ?)
                    ON CONFLICT(fid) DO UPDATE SET
                        description = ?
                    """,
                    (
                        (
                            fid,
                            self.__edit_buffer.updated_descriptions.get(
                                fid, ""
                            ),
                            self.__edit_buffer.updated_descriptions.get(
                                fid, ""
                            ),
                        )
                        for fid in feature_ids
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO ngw_updated_descriptions (fid, backup)
                    VALUES (?, ?)
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        (fid, self.__description_backups.get(fid))
                        for fid in feature_ids
                    ),
                )
                connection.commit()

        except Exception as error:
            message = "Can't create description changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated descriptions for {len(feature_ids)} features in layer "
            f"{metadata}"
        )

        self.__is_layer_changed = True

    def __log_removed_attachments(self) -> None:
        if not self.__edit_buffer.has_removed_attachments:
            return

        ng_error = None

        total_removed = 0
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                for (
                    removed_aids
                ) in self.__edit_buffer.removed_attachments.values():
                    if len(removed_aids) == 0:
                        continue

                    total_removed += len(removed_aids)
                    joined_removed_aids = ",".join(map(str, removed_aids))
                    attachments_rows = list(
                        cursor.execute(
                            f"""
                            SELECT
                                attachments.fid,
                                metadata.ngw_fid,
                                attachments.aid,
                                attachments.ngw_aid,
                                attachments.version,
                                attachments.keyname,
                                attachments.name,
                                attachments.description,
                                attachments.fileobj,
                                attachments.mime_type,
                                ngw_updated_attachments.backup
                            FROM ngw_features_attachments AS attachments
                            LEFT JOIN ngw_features_metadata AS metadata
                                ON metadata.fid = attachments.fid
                            LEFT JOIN ngw_updated_attachments
                                ON ngw_updated_attachments.aid = attachments.aid
                            WHERE attachments.aid IN ({joined_removed_aids});
                            """
                        )
                    )

                    remove_backups = []
                    for row in attachments_rows:
                        before_deletion = self.__attachment_backup_record(row)
                        updated_backup = row[10]
                        after_sync = before_deletion
                        if updated_backup is not None:
                            after_sync = json.loads(updated_backup)

                        remove_backups.append(
                            (
                                row[2],
                                json.dumps(
                                    {
                                        "after_sync": after_sync,
                                        "before_deletion": before_deletion,
                                    }
                                ),
                            )
                        )

                    cursor.executemany(
                        """
                        INSERT INTO ngw_removed_attachments (aid, backup)
                        VALUES (?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        remove_backups,
                    )
                    cursor.execute(
                        f"""
                        DELETE FROM ngw_updated_attachments
                        WHERE aid IN ({joined_removed_aids});
                        """
                    )

                connection.commit()

        except Exception as error:
            message = "Can't create attachment removal records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Removed {total_removed} attachments in layer {metadata}"
        )

        self.__is_layer_changed = True

    def __log_added_attachments(self) -> None:
        if not self.__edit_buffer.has_added_attachments:
            return

        ng_error = None

        all_added_attachments = self.__edit_buffer.added_attachments.values()

        aid_mapping = {}
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                for added_attachments in all_added_attachments:
                    for attachment in added_attachments.values():
                        cursor.execute(
                            """
                            INSERT INTO ngw_features_attachments (
                                fid,
                                name,
                                description,
                                mime_type
                            )
                            VALUES (?, ?, ?, ?)
                            RETURNING aid;
                            """,
                            (
                                attachment.fid,
                                attachment.name,
                                attachment.description,
                                attachment.mime_type,
                            ),
                        )
                        new_aid = cursor.fetchone()[0]
                        aid_mapping[attachment.aid] = new_aid

                cursor.executemany(
                    """
                    INSERT INTO ngw_added_attachments (aid)
                    VALUES (?);
                    """,
                    ((aid,) for aid in aid_mapping.values()),
                )

                connection.commit()

        except Exception as error:
            message = "Can't create attachment update records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        try:
            for added_attachments in all_added_attachments:
                for attachment in added_attachments.values():
                    new_aid = aid_mapping[attachment.aid]
                    new_path = self.attachment_path(attachment.fid, new_aid)
                    if new_path is None:
                        raise DetachedEditingError(
                            f"Can't get path for new attachment {new_aid} "
                            f"of feature {attachment.fid}.",
                            code=ErrorCode.AttachmentNotFound,
                        )

                    assert attachment.file_path is not None
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(attachment.file_path, new_path)
                    DetachedStorageServiceFactory.create().register_attachment_file(
                        self.__container.metadata.instance_id,
                        self.__container.metadata.resource_id,
                        new_aid,
                        file_name=attachment.name,
                        mime_type=attachment.mime_type,
                        feature_local_id=int(attachment.fid),
                        is_dirty=True,
                    )

        except Exception as error:
            message = "Can't move added attachment files"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(f"Updated {aid_mapping} attachments in layer {metadata}")

        self.__is_layer_changed = True

    def __log_updated_attachments(self) -> None:
        if not self.__edit_buffer.has_updated_attachments:
            return

        ng_error = None

        total_updated = 0
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                for (
                    updated_attachments
                ) in self.__edit_buffer.updated_attachments.values():
                    if len(updated_attachments) == 0:
                        continue

                    total_updated += len(updated_attachments)

                    updated_aids = list(updated_attachments.keys())
                    joined_updated_aids = ",".join(map(str, updated_aids))
                    attachments_rows = list(
                        cursor.execute(
                            f"""
                            SELECT
                                attachments.fid,
                                metadata.ngw_fid,
                                attachments.aid,
                                attachments.ngw_aid,
                                attachments.version,
                                attachments.keyname,
                                attachments.name,
                                attachments.description,
                                attachments.fileobj,
                                attachments.mime_type
                            FROM ngw_features_attachments AS attachments
                            LEFT JOIN ngw_features_metadata AS metadata
                                ON metadata.fid = attachments.fid
                            WHERE attachments.aid IN ({joined_updated_aids});
                            """
                        )
                    )

                    cursor.executemany(
                        """
                        UPDATE ngw_features_attachments
                        SET name = ?, description = ?
                        WHERE aid = ?;
                        """,
                        (
                            (
                                attachment.name,
                                attachment.description,
                                attachment.aid,
                            )
                            for attachment in updated_attachments.values()
                        ),
                    )
                    cursor.executemany(
                        """
                        INSERT INTO ngw_updated_attachments (aid, backup)
                        VALUES (?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            (
                                row[2],
                                json.dumps(
                                    self.__attachment_backup_record(row)
                                ),
                            )
                            for row in attachments_rows
                        ),
                    )

                connection.commit()

        except Exception as error:
            message = "Can't create attachment update records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated {total_updated} attachments in layer {metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QList<QgsField>")
    def __on_attribute_added(
        self, layer_id: str, added_fields: List[QgsField]
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Added {len(added_fields)} attributes in layer {metadata}"
        )

        self.__is_structure_changed = True

        QMessageBox.warning(
            None,
            self.tr("Layer structure changed"),
            self.tr(
                "Added columns in QGIS will not be added to NextGIS Web layer."
                "\n\nIf you want to change the layer structure, please do so"
                " in the NextGIS Web interface and reset the layer in sync"
                " status window."
            ),
        )

    @pyqtSlot(str, "QgsAttributeList")
    def __on_attribute_deleted(
        self, layer_id, deleted_attributes: QgsAttributeList
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Removed {len(deleted_attributes)} attributes in layer {metadata}"
        )

        self.__is_structure_changed = True

        container_fields_name = set(
            field.name() for field in self.__qgs_layer.fields()
        )
        if all(
            ngw_field.keyname in container_fields_name
            for ngw_field in metadata.fields
        ):
            return

        QMessageBox.warning(
            None,
            self.tr("Layer structure changed"),
            self.tr(
                "Deleting a column is only possible from the NextGIS Web interface."
                "\n\nFurther work with the layer is possible only after the"
                " layer reset. You can do this from the sync status window."
            ),
        )

    @pyqtSlot(str)
    def __on_custom_property_changed(self, name: str) -> None:
        need_emit = (
            name == self.UPDATE_STATE_PROPERTY
            and self.qgs_layer.customProperty(
                self.UPDATE_STATE_PROPERTY, defaultValue=False
            )
        )
        self.qgs_layer.removeCustomProperty(self.UPDATE_STATE_PROPERTY)

        if need_emit:
            self.settings_changed.emit()

    @pyqtSlot(bool)
    def __create_backup(self, stop_editing: bool) -> None:
        ng_error = None

        try:
            self.__create_backup_for_updated_fields()
            self.__create_backup_for_updated_geometries()
            self.__create_backup_for_deleted_features()
            self.__create_backup_for_updated_descriptions()
        except Exception as error:
            message = "Can't create backup before changes"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.__errors.append(ng_error)

    def __extract_intersection_with_added_fids(
        self, cursor: sqlite3.Cursor, feature_ids: QgsFeatureIds
    ) -> QgsFeatureIds:
        fetch_added_query = """
            SELECT fid
            FROM ngw_added_features
            WHERE fid in ({placeholders})
        """.format(placeholders=",".join(map(str, feature_ids)))
        cursor.execute(fetch_added_query)
        return set(row[0] for row in cursor.fetchall())

    def __create_backup_for_updated_fields(self) -> None:
        changed_attributes_info: QgsChangedAttributesMap = (
            self.__qgs_layer.editBuffer().changedAttributeValues()
        )
        if len(changed_attributes_info) == 0:
            return

        features_before_change = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(list(changed_attributes_info.keys()))
            ),
        )
        self.__updated_attributes.update(
            (
                (feature.id(), attribute),
                serialize_value(feature.attribute(attribute)),
            )
            for feature in features_before_change
            for attribute in changed_attributes_info[feature.id()].keys()
        )

    def __create_backup_for_updated_geometries(self) -> None:
        changed_geometries_info: QgsGeometryMap = (
            self.__qgs_layer.editBuffer().changedGeometries()
        )
        if len(changed_geometries_info) == 0:
            return

        features_before_change = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(list(changed_geometries_info.keys()))
            ),
        )
        self.__updated_geometries.update(
            (
                feature.id(),
                serialize_geometry(
                    feature.geometry(),
                    self.__container.metadata.is_versioning_enabled,
                ),
            )
            for feature in features_before_change
        )

    def __create_backup_for_deleted_features(self) -> None:
        deleted_features_id: QgsFeatureIds = (
            self.__qgs_layer.editBuffer().deletedFeatureIds()
        )
        if len(deleted_features_id) == 0:
            return

        deleted_features = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(deleted_features_id)
            ),
        )
        self.__deleted_features = {
            feature.id(): feature for feature in deleted_features
        }

    def __create_backup_for_updated_descriptions(self) -> None:
        if (
            self.__edit_buffer is None
            or not self.__edit_buffer.has_updated_descriptions
        ):
            return

        updated_descriptions = self.__edit_buffer.updated_descriptions

        self.__description_backups: Dict[QgsFeatureId, str] = dict()

        updated_fids = list(
            fid
            for fid in updated_descriptions.keys()
            if not is_feature_new(fid)
        )
        joined_updated_fids = ",".join(map(str, updated_fids))
        with closing(make_connection(self.__qgs_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                f"""
                SELECT fid, description, version
                FROM ngw_features_descriptions
                WHERE fid IN ({joined_updated_fids});
                """,
            )
            rows = cursor.fetchall()
            self.__description_backups = {
                row[0]: serialize_value({"value": row[1], "version": row[2]})
                for row in rows
            }

    def __reset_backup(self) -> None:
        self.__updated_attributes = dict()
        self.__updated_geometries = dict()
        self.__deleted_features = dict()

    def __remove_features_metadata(
        self, cursor: sqlite3.Cursor, fids: QgsFeatureIds
    ) -> None:
        if len(fids) == 0:
            return

        joined_fids = ",".join(map(str, fids))
        cursor.executescript(
            f"""
            DELETE FROM ngw_features_metadata
            WHERE fid IN ({joined_fids}) AND ngw_fid IS NULL;
            """
        )

    def __add_remove_records(
        self, cursor: sqlite3.Cursor, removed_fids: QgsFeatureIds
    ) -> None:
        if len(removed_fids) == 0:
            return

        joined_removed_fids = ",".join(map(str, removed_fids))
        fields_backups = self.__extract_fields_backups(
            cursor, joined_removed_fids
        )
        geometries_backups = self.__extract_geometries_backups(
            cursor, joined_removed_fids
        )
        description_backups = self.__extract_description_backups(
            cursor, joined_removed_fids
        )
        attachment_backups = self.__extract_attachment_backups(
            cursor, joined_removed_fids
        )
        features_backup = self.__serialize_deletion_backup(
            removed_fids,
            fields_backups,
            geometries_backups,
            description_backups,
            attachment_backups,
        )

        # Update records
        removed_records = ",".join(
            map(
                lambda fid: "({fid}, {backup})".format(  # noqa: UP032
                    fid=fid,
                    backup=wrap_sql_value(json.dumps(features_backup[fid])),
                ),
                removed_fids,
            )
        )
        script = f"""
            INSERT INTO ngw_removed_features (fid, backup)
                VALUES {removed_records};
        """

        if len(fields_backups) > 0:
            script += f"""
            DELETE FROM ngw_updated_attributes
                WHERE fid in ({joined_removed_fids});
            """
        if len(geometries_backups) > 0:
            script += f"""
            DELETE FROM ngw_updated_geometries
                WHERE fid in ({joined_removed_fids});
            """
        script += f"""
            DELETE FROM ngw_features_attachments
                WHERE fid in ({joined_removed_fids});
        """
        if len(description_backups) > 0:
            script += f"""
            DELETE FROM ngw_updated_descriptions
                WHERE fid in ({joined_removed_fids});
            DELETE FROM ngw_features_descriptions
                WHERE fid in ({joined_removed_fids});
            """

        cursor.executescript(script)

    def __extract_fields_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[Tuple[QgsFeatureId, FieldId], str]:
        return {
            (row[0], row[1]): deserialize_value(row[2])
            for row in cursor.execute(
                f"""
                SELECT fid, attribute, backup
                FROM ngw_updated_attributes
                WHERE fid IN ({joined_fids})
                """
            )
        }

    def __extract_geometries_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[QgsFeatureId, str]:
        return {
            row[0]: row[1]
            for row in cursor.execute(
                f"""
                SELECT fid, backup
                FROM ngw_updated_geometries
                WHERE fid IN ({joined_fids})
                """
            )
        }

    def __extract_description_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[QgsFeatureId, Tuple[Dict[str, Any], Dict[str, Any]]]:
        result: Dict[QgsFeatureId, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
        for row in cursor.execute(
            f"""
            SELECT
                ngw_features_descriptions.fid,
                ngw_updated_descriptions.backup,
                ngw_features_descriptions.description,
                ngw_features_descriptions.version
            FROM ngw_features_descriptions
            LEFT JOIN ngw_updated_descriptions
                ON ngw_updated_descriptions.fid = ngw_features_descriptions.fid
            WHERE ngw_features_descriptions.fid IN ({joined_fids})
            """
        ):
            fid = row[0]
            before_delete = {"value": row[2], "version": row[3]}
            after_sync = before_delete
            if row[1]:
                after_sync = cast(Dict[str, Any], json.loads(row[1]))

            result[fid] = (after_sync, before_delete)

        return result

    def __extract_attachment_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[
        QgsFeatureId,
        Tuple[List[Dict[str, Any]], List[Dict[str, Any]]],
    ]:
        after_sync_by_fid: Dict[QgsFeatureId, List[Dict[str, Any]]] = {}
        before_deletion_by_fid: Dict[QgsFeatureId, List[Dict[str, Any]]] = {}

        for row in cursor.execute(
            f"""
            SELECT
                attachments.fid,
                metadata.ngw_fid,
                attachments.aid,
                attachments.ngw_aid,
                attachments.version,
                attachments.keyname,
                attachments.name,
                attachments.description,
                attachments.fileobj,
                attachments.mime_type,
                ngw_updated_attachments.backup
            FROM ngw_features_attachments AS attachments
            LEFT JOIN ngw_features_metadata AS metadata
                ON metadata.fid = attachments.fid
            LEFT JOIN ngw_updated_attachments
                ON ngw_updated_attachments.aid = attachments.aid
            LEFT JOIN ngw_removed_attachments AS removed
                ON removed.aid = attachments.aid
            WHERE attachments.fid IN ({joined_fids})
                AND removed.aid IS NULL;
            """
        ):
            fid = row[0]
            before_deletion = self.__attachment_backup_record(row[:10])
            after_sync = before_deletion
            if row[10] is not None:
                after_sync = cast(Dict[str, Any], json.loads(row[10]))

            if fid not in after_sync_by_fid:
                after_sync_by_fid[fid] = []
            after_sync_by_fid[fid].append(after_sync)

            if fid not in before_deletion_by_fid:
                before_deletion_by_fid[fid] = []
            before_deletion_by_fid[fid].append(before_deletion)

        for fid, backup in cursor.execute(
            f"""
            SELECT attachments.fid, removed.backup
            FROM ngw_removed_attachments AS removed
            LEFT JOIN ngw_features_attachments AS attachments
                ON attachments.aid = removed.aid
            WHERE attachments.fid IN ({joined_fids});
            """
        ):
            if fid not in after_sync_by_fid:
                after_sync_by_fid[fid] = []
            backup_data = cast(Dict[str, Any], json.loads(backup))
            after_sync_by_fid[fid].append(
                cast(Dict[str, Any], backup_data["after_sync"])
            )

        result: Dict[
            QgsFeatureId,
            Tuple[List[Dict[str, Any]], List[Dict[str, Any]]],
        ] = {}
        all_fids = set(after_sync_by_fid.keys()) | set(
            before_deletion_by_fid.keys()
        )
        for fid in all_fids:
            after_sync_attachments = sorted(
                after_sync_by_fid.get(fid, []),
                key=lambda attachment: attachment["aid"],
            )
            before_deletion_attachments = sorted(
                before_deletion_by_fid.get(fid, []),
                key=lambda attachment: attachment["aid"],
            )
            result[fid] = (
                after_sync_attachments,
                before_deletion_attachments,
            )

        return result

    def __attachment_backup_record(
        self,
        row: Tuple[Any, ...],
    ) -> Dict[str, Any]:
        return {
            "fid": row[0],
            "ngw_fid": row[1],
            "aid": row[2],
            "ngw_aid": row[3],
            "version": serialize_value(row[4]),
            "keyname": row[5],
            "name": row[6],
            "description": row[7],
            "fileobj": serialize_value(row[8]),
            "mime_type": row[9],
        }

    def __serialize_deletion_backup(
        self,
        fids: Iterable[NgwFeatureId],
        fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str],
        geometries_backups: Dict[QgsFeatureId, str],
        descriptions_backups: Dict[
            QgsFeatureId, Tuple[Dict[str, Any], Dict[str, Any]]
        ],
        attachments_backups: Dict[
            QgsFeatureId,
            Tuple[List[Dict[str, Any]], List[Dict[str, Any]]],
        ],
    ) -> Dict[NgwFeatureId, Dict[str, Any]]:
        result = {}

        for fid in fids:
            feature = self.__deleted_features[fid]

            fields_after_sync = []
            fields_before_deletion = []

            for field in self.__container.metadata.fields:
                value_before_deletion = simplify_value(
                    feature.attribute(field.attribute)
                )
                value_after_sync = fields_backups.get(
                    (fid, field.attribute), value_before_deletion
                )
                fields_after_sync.append([field.ngw_id, value_after_sync])
                fields_before_deletion.append(
                    [field.ngw_id, value_before_deletion]
                )
            description_after_sync = {}
            description_before_deletion = {}
            if fid in descriptions_backups:
                description_after_sync = descriptions_backups[fid][0]
                description_before_deletion = descriptions_backups[fid][1]

            attachments_after_sync = []
            attachments_before_deletion = []
            if fid in attachments_backups:
                attachments_after_sync = attachments_backups[fid][0]
                attachments_before_deletion = attachments_backups[fid][1]

            serialized_geometry = serialize_geometry(
                feature.geometry(),
                self.__container.metadata.is_versioning_enabled,
            )
            feature_record = {
                "after_sync": {
                    "fields": fields_after_sync,
                    "geom": geometries_backups.get(fid, serialized_geometry),
                    "description": description_after_sync,
                    "attachments": attachments_after_sync,
                },
                "before_deletion": {
                    "fields": fields_before_deletion,
                    "geom": serialized_geometry,
                    "description": description_before_deletion,
                    "attachments": attachments_before_deletion,
                },
            }
            result[fid] = feature_record

        return result

    def __on_commit_changes(self) -> None:
        self.__log_extensions()

        if self.__is_structure_changed:
            self.structure_changed.emit()
            self.__is_structure_changed = False

        if self.__is_layer_changed:
            self.layer_changed.emit()
            self.__is_layer_changed = False

        if self.__errors:
            for ng_error in self.__errors:
                self.error_occurred.emit(ng_error)
            self.__errors.clear()

    def __attachment_path(
        self, attachment: AttachmentMetadata
    ) -> Optional[Path]:
        if is_attachment_new(attachment.aid):
            return attachment.file_path

        assert self.__container.metadata.instance_id

        storage_service = DetachedStorageServiceFactory.create()
        path = storage_service.cached_attachment_path(
            self.__container.metadata.instance_id,
            self.__container.metadata.resource_id,
            attachment.aid,
            file_name=attachment.name,
            mime_type=attachment.mime_type,
            fileobj=attachment.fileobj,
            feature_local_id=int(attachment.fid),
            feature_ngw_fid=attachment.ngw_fid,
            ngw_aid=attachment.ngw_aid,
        )
        canonical_path = storage_service.attachment_path(
            self.__container.metadata.instance_id,
            self.__container.metadata.resource_id,
            attachment.aid,
            file_name=attachment.name,
            mime_type=attachment.mime_type,
            fileobj=attachment.fileobj,
        )
        if path == canonical_path and path.exists():
            storage_service.register_attachment_file(
                self.__container.metadata.instance_id,
                self.__container.metadata.resource_id,
                attachment.aid,
                file_name=attachment.name,
                mime_type=attachment.mime_type,
                fileobj=attachment.fileobj,
                feature_local_id=int(attachment.fid),
                feature_ngw_fid=attachment.ngw_fid,
                ngw_aid=attachment.ngw_aid,
            )
        return path

    def __refresh_feature_attachments(
        self,
        feature_id: QgsFeatureId,
    ) -> List[AttachmentMetadata]:
        ngw_fid = self.__feature_ngw_fid(feature_id)
        if ngw_fid is None:
            return []

        remote_attachments = self.__fetch_feature_attachments_from_ngw(
            feature_id, ngw_fid
        )
        if not self.__container.metadata.is_versioning_enabled:
            self.__save_feature_attachments_from_ngw(
                feature_id, remote_attachments
            )
        return remote_attachments

    def __feature_ngw_fid(
        self, feature_id: QgsFeatureId
    ) -> Optional[NgwFeatureId]:
        with closing(make_connection(self.__qgs_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                SELECT ngw_fid
                FROM ngw_features_metadata
                WHERE fid = ?;
                """,
                (feature_id,),
            )
            row = cursor.fetchone()

        return row[0] if row else None

    def __fetch_feature_attachments_from_ngw(
        self, feature_id: QgsFeatureId, ngw_fid: NgwFeatureId
    ) -> List[AttachmentMetadata]:
        resource_id = self.__container.metadata.resource_id
        connection_id = self.__container.metadata.connection_id
        url = f"/api/resource/{resource_id}/feature/{ngw_fid}/attachment/"

        response = QgsNgwConnection(connection_id).get(url)
        attachments_data = self.__normalize_attachments_response(response)

        attachments = []
        for item in attachments_data:
            ngw_aid = self.__attachment_response_id(item)
            if ngw_aid is None:
                continue

            fileobj = item.get("fileobj")
            if isinstance(fileobj, dict):
                fileobj = fileobj.get("id")

            attachments.append(
                AttachmentMetadata(
                    fid=feature_id,
                    aid=ngw_aid,
                    ngw_fid=ngw_fid,
                    ngw_aid=ngw_aid,
                    version=item.get("version") or Unset,
                    keyname=item.get("keyname"),
                    name=item.get("name"),
                    description=item.get("description"),
                    fileobj=fileobj,
                    mime_type=item.get("mime_type"),
                    size=item.get("size"),
                    sha256=item.get("sha256"),
                    file_meta=item.get("file_meta")
                    if isinstance(item.get("file_meta"), dict)
                    else None,
                )
            )

        return attachments

    def __normalize_attachments_response(
        self, response: Any
    ) -> List[Dict[str, Any]]:
        if response is None:
            return []

        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]

        if isinstance(response, dict):
            for key in ("items", "attachments", "data", "result"):
                value = response.get(key)
                if not isinstance(value, list):
                    continue
                return [item for item in value if isinstance(item, dict)]

        message = "Unexpected attachments response"
        raise DetachedEditingError(message)

    def __attachment_response_id(
        self, item: Dict[str, Any]
    ) -> Optional[NgwAttachmentId]:
        attachment_id = item.get("id", item.get("aid"))
        if attachment_id is None:
            return None
        return int(attachment_id)

    def __save_feature_attachments_from_ngw(
        self,
        feature_id: QgsFeatureId,
        remote_attachments: List[AttachmentMetadata],
    ) -> None:
        remote_by_ngw_aid = {
            attachment.ngw_aid: attachment
            for attachment in remote_attachments
            if attachment.ngw_aid is not None
        }
        remote_ngw_aids = set(remote_by_ngw_aid)

        with closing(make_connection(self.__qgs_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            local_change_aids = self.__local_attachment_change_aids(cursor)
            rows = list(
                cursor.execute(
                    """
                    SELECT aid, ngw_aid, fileobj
                    FROM ngw_features_attachments
                    WHERE fid = ?;
                    """,
                    (feature_id,),
                )
            )

            existing_by_ngw_aid = {
                row[1]: row for row in rows if row[1] is not None
            }
            stale_rows = [
                row
                for row in rows
                if row[0] not in local_change_aids
                and row[1] is not None
                and row[1] not in remote_ngw_aids
            ]

            for attachment in remote_by_ngw_aid.values():
                row = existing_by_ngw_aid.get(attachment.ngw_aid)
                if row is not None:
                    aid = row[0]
                    if aid in local_change_aids:
                        continue
                    self.__update_base_attachment(cursor, aid, attachment)
                    continue

                self.__insert_base_attachment(cursor, attachment)

            for aid, _ngw_aid, fileobj in stale_rows:
                cursor.execute(
                    "DELETE FROM ngw_features_attachments WHERE aid = ?;",
                    (aid,),
                )
                self.__remove_attachment_cache(aid, fileobj)

            connection.commit()

    def __local_attachment_change_aids(
        self, cursor: sqlite3.Cursor
    ) -> Set[AttachmentId]:
        result: Set[AttachmentId] = set()
        for table_name in (
            "ngw_added_attachments",
            "ngw_removed_attachments",
            "ngw_updated_attachments",
            "ngw_restored_attachments",
        ):
            result.update(
                aid
                for (aid,) in cursor.execute(f"SELECT aid FROM {table_name}")
            )
        return result

    def __insert_base_attachment(
        self,
        cursor: sqlite3.Cursor,
        attachment: AttachmentMetadata,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO ngw_features_attachments (
                fid,
                ngw_aid,
                version,
                keyname,
                name,
                description,
                fileobj,
                mime_type,
                size,
                sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                attachment.fid,
                attachment.ngw_aid,
                None
                if isinstance(attachment.version, UnsetType)
                else attachment.version,
                attachment.keyname,
                attachment.name,
                attachment.description,
                attachment.fileobj,
                attachment.mime_type,
                attachment.size,
                attachment.sha256,
            ),
        )

    def __update_base_attachment(
        self,
        cursor: sqlite3.Cursor,
        aid: AttachmentId,
        attachment: AttachmentMetadata,
    ) -> None:
        cursor.execute(
            """
            UPDATE ngw_features_attachments
            SET version = ?,
                keyname = ?,
                name = ?,
                description = ?,
                fileobj = ?,
                mime_type = ?,
                size = ?,
                sha256 = ?
            WHERE aid = ?;
            """,
            (
                None
                if isinstance(attachment.version, UnsetType)
                else attachment.version,
                attachment.keyname,
                attachment.name,
                attachment.description,
                attachment.fileobj,
                attachment.mime_type,
                attachment.size,
                attachment.sha256,
                aid,
            ),
        )

    def __remove_attachment_cache(
        self,
        attachment_id: AttachmentId,
        fileobj: Optional[FileObjectId],
    ) -> None:
        DetachedStorageServiceFactory.create().remove_attachment_cache(
            self.__container.metadata.instance_id,
            self.__container.metadata.resource_id,
            attachment_id,
            fileobj=fileobj,
        )

    def __attachment_thumbnail_path(
        self, attachment: AttachmentMetadata
    ) -> Optional[Path]:
        if is_attachment_new(attachment.aid):
            return None

        assert self.__container.metadata.instance_id

        storage_service = DetachedStorageServiceFactory.create()
        path = storage_service.cached_attachment_thumbnail_path(
            self.__container.metadata.instance_id,
            self.__container.metadata.resource_id,
            attachment.aid,
            fileobj=attachment.fileobj,
            feature_local_id=int(attachment.fid),
            feature_ngw_fid=attachment.ngw_fid,
            ngw_aid=attachment.ngw_aid,
        )
        canonical_path = storage_service.attachment_thumbnail_path(
            self.__container.metadata.instance_id,
            self.__container.metadata.resource_id,
            attachment.aid,
            fileobj=attachment.fileobj,
        )
        if path == canonical_path and path.exists():
            storage_service.register_attachment_thumbnail(
                self.__container.metadata.instance_id,
                self.__container.metadata.resource_id,
                attachment.aid,
                fileobj=attachment.fileobj,
                feature_local_id=int(attachment.fid),
                feature_ngw_fid=attachment.ngw_fid,
                ngw_aid=attachment.ngw_aid,
            )
        return path

    def __fix_source_if_needed(self) -> None:
        if self.qgs_layer.isValid():
            return

        self.qgs_layer.setDataSource(
            detached_layer_uri(
                self.__container.path, self.__container.metadata
            ),
            self.qgs_layer.name(),
            "ogr",
        )

    def __apply_required_constraints(self) -> None:
        self.metadata.fields.apply_required_constraints(self.qgs_layer)

    def __assert_edit_buffer_initialized(self) -> None:
        if self.__edit_buffer is None:
            raise DetachedEditingError(
                "Cannot modify feature when edit buffer is not initialized.",
                code=ErrorCode.LayerEditError,
            )

    def __assert_existed_feature(self, feature_id: QgsFeatureId) -> None:
        feature = self.qgs_layer.getFeature(feature_id)
        if not feature.isValid():
            message = f"Feature {feature_id} does not exist in detached layer."
            raise DetachedEditingError(
                message,
                code=ErrorCode.FeatureNotFound,
            )
