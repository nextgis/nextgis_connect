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

import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Set,
    Union,
)

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsMemoryProviderUtils,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.legacy.detached_editing.change_journal import (
    DetachedChangeJournal,
)
from nextgis_connect.legacy.detached_editing.change_tracker import (
    DetachedChangeTracker,
    ExtensionChanges,
)
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
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import (
    QgsAttributeList,
    QgsFeatureId,
)
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    DetachedEditingError,
    ErrorCode,
)
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
        self.__journal_failed = False

        self.__fix_source_if_needed()
        self.__apply_required_constraints()

        self.__tracker = DetachedChangeTracker(container.metadata, self)

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
        self.__tracker.metadata = metadata

        self.__qgs_layer.committedFeaturesAdded.connect(
            self.__tracker.added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.connect(
            self.__tracker.removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.connect(
            self.__tracker.changed_attributes
        )
        self.__qgs_layer.committedGeometriesChanges.connect(
            self.__tracker.changed_geometries
        )

        self.__qgs_layer.committedAttributesAdded.connect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.connect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.connect(self.__create_backup)
        self.__qgs_layer.beforeRollBack.connect(self.__on_rollback)
        self.__qgs_layer.afterCommitChanges.connect(self.__clear)

        self.__edit_buffer = DetachedLayerEditBuffer(self)

        self.editing_started.emit()

    @pyqtSlot()
    def __stop_listen_changes(self) -> None:
        # rollBack(False) emits editingStopped but retains the edit buffer
        # and undo stack. Keep tracking subsequent edits and redo commands.
        if self.__qgs_layer.isEditable():
            return

        self.__qgs_layer.committedFeaturesAdded.disconnect(
            self.__tracker.added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.disconnect(
            self.__tracker.removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.disconnect(
            self.__tracker.changed_attributes
        )
        self.__qgs_layer.committedGeometriesChanges.disconnect(
            self.__tracker.changed_geometries
        )

        self.__qgs_layer.committedAttributesAdded.disconnect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.disconnect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.disconnect(self.__create_backup)
        self.__qgs_layer.beforeRollBack.disconnect(self.__on_rollback)
        self.__qgs_layer.afterCommitChanges.disconnect(self.__clear)

        self.__emit_errors()
        self.__clear()
        self.__edit_buffer = None

        metadata = self.__container.metadata
        logger.debug(f"Stop listening changes in layer {metadata}")

        self.editing_finished.emit()

    @pyqtSlot()
    def __clear(self) -> None:
        self.__edit_buffer.clear(
            discard_staged_files=not self.__journal_failed
        )
        self.__commands = []
        self.__tracker.clear()

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
        try:
            self.__tracker.capture_attributes(self.__qgs_layer)
            self.__tracker.capture_geometries(self.__qgs_layer)
            self.__tracker.capture_deletions(self.__qgs_layer)
        except Exception as error:
            message = "Can't create backup before changes"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

            self.__errors.append(ng_error)

    def __on_commit_changes(self) -> None:
        self.__write_metadata(include_extensions=True)

    @pyqtSlot()
    def __on_rollback(self) -> None:
        # Only provider-committed updates survive rollback, not extensions
        # still held in the edit buffer. This also covers rollBack(False).
        self.__write_metadata(include_extensions=False)
        self.__tracker.clear()

    def __write_metadata(self, *, include_extensions: bool) -> None:
        self.__journal_failed = False
        try:
            journal = DetachedChangeJournal(
                self.__container.path, self.metadata
            )
            extensions = None
            if include_extensions and self.__edit_buffer is not None:
                extensions = ExtensionChanges(
                    descriptions=self.__edit_buffer.updated_descriptions,
                    added_attachments=self.__edit_buffer.added_attachments,
                    updated_attachments=self.__edit_buffer.updated_attachments,
                    removed_attachments=self.__edit_buffer.removed_attachments,
                )
            self.__is_layer_changed = journal.write(
                self.__tracker,
                extensions,
            )
        except ContainerError as error:
            self.__journal_failed = True
            self.__errors.append(error)
        except Exception as error:
            self.__journal_failed = True
            ng_error = ContainerError(
                "Can't create feature changes records",
                user_message=self.tr(
                    "The changes could not be recorded in the synchronization "
                    "journal. Unrecorded changes may not be synchronized."
                ),
            )
            ng_error.__cause__ = deepcopy(error)
            self.__errors.append(ng_error)
        self.__emit_change_signals()
        self.__emit_errors()

    def __emit_change_signals(self) -> None:
        if self.__is_structure_changed:
            self.structure_changed.emit()
            self.__is_structure_changed = False

        if self.__is_layer_changed:
            self.layer_changed.emit()
            self.__is_layer_changed = False

    def __emit_errors(self) -> None:
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
