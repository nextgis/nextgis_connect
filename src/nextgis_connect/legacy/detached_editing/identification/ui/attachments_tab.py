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

import shutil
from contextlib import closing, suppress
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast
from zipfile import ZIP_DEFLATED, ZipFile

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeedback,
    QgsTask,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QMimeDatabase,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices, QImageReader, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QFileDialog,
    QHBoxLayout,
    QListView,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.detached_editing.detached_layer import (
    DetachedLayer,
)
from nextgis_connect.legacy.detached_editing.identification.attachment_download import (
    AttachmentBatchDownloadTask,
    AttachmentDownloadContext,
    AttachmentDownloadTask,
)
from nextgis_connect.legacy.detached_editing.identification.attachments_model import (
    AttachmentLoadingKind,
    AttachmentsModel,
)
from nextgis_connect.legacy.detached_editing.identification.attachments_sort_proxy_model import (
    AttachmentsSortMode,
    AttachmentsSortProxyModel,
)
from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.legacy.detached_editing.identification.ui.attachments_view_wrapper import (
    AttachmentsViewWrapper,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    make_connection,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw_connection import (
    NgwConnection,
    NgwConnectionsManager,
)
from nextgis_connect.platform.clipboard import Clipboard
from nextgis_connect.platform.filesystem import reveal_in_file_manager
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import QgsFeatureId
from nextgis_connect.platform.tasks import NgConnectTask
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.constants import PLUGIN_NAME
from nextgis_connect.shared.types import AttachmentId
from nextgis_connect.ui_kit.icons import material_icon, qgis_icon
from nextgis_connect.ui_kit.widgets.image_preview import (
    ImagePreviewDialog,
    ImagePreviewItem,
)

AttachmentThumbnailKey = Tuple[
    str,
    int,
    Union[str, int],
    Union[str, int],
    Optional[Union[str, int]],
    Optional[str],
]


def _is_image_attachment(attachment: AttachmentMetadata) -> bool:
    mime_type = attachment.mime_type or ""
    settings = IdentificationSettings()
    return (
        mime_type in settings.attachment_thumbnail_mime_types
        or mime_type.startswith("image/")
    )


def _needs_attachment_thumbnail_download(
    attachment: AttachmentMetadata,
) -> bool:
    return (
        _is_image_attachment(attachment)
        and attachment.thumbnail_path is not None
        and not attachment.thumbnail_path.exists()
        and attachment.ngw_fid is not None
        and attachment.ngw_aid is not None
    )


def _download_attachment_thumbnail(
    connection_id: str,
    resource_id: int,
    feature_ngw_fid: Union[str, int],
    ngw_aid: Union[str, int],
    thumbnail_path: Path,
) -> None:
    url = (
        f"/api/resource/{resource_id}"
        f"/feature/{feature_ngw_fid}"
        f"/attachment/{ngw_aid}"
        "/image?size=64x64&crop=true"
    )

    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    data = QgsNgwConnection(connection_id).get(url)
    if isinstance(data, QByteArray):
        thumbnail_path.write_bytes(bytes(data))
    elif isinstance(data, (bytes, bytearray)):
        thumbnail_path.write_bytes(bytes(data))
    else:
        message = "Unexpected attachment thumbnail response"
        raise RuntimeError(message)

    image_reader = QImageReader(str(thumbnail_path))
    if image_reader.canRead():
        return

    error = image_reader.errorString()
    if thumbnail_path.exists():
        thumbnail_path.unlink()

    message = f"Attachment thumbnail response is not an image: {error}"
    raise RuntimeError(message)


def _attachment_thumbnail_key(
    connection_id: str,
    resource_id: int,
    attachment: AttachmentMetadata,
) -> AttachmentThumbnailKey:
    assert attachment.ngw_fid is not None
    assert attachment.ngw_aid is not None
    return (
        connection_id,
        resource_id,
        attachment.ngw_fid,
        attachment.ngw_aid,
        attachment.fileobj,
        attachment.sha256,
    )


class IdentificationAttachmentsTask(NgConnectTask):
    def __init__(
        self,
        detached_layer: DetachedLayer,
        feature_id: QgsFeatureId,
        generation: int,
        keep_existing: bool = False,
    ) -> None:
        super().__init__(flags=QgsTask.Flags())
        self.setDescription(
            QgsApplication.translate(
                "AttachmentsTab", "Loading feature attachments"
            )
        )
        self.detached_layer = detached_layer
        self.feature_id = feature_id
        self.generation = generation
        self.keep_existing = keep_existing
        self._attachments: List[AttachmentMetadata] = []

    @property
    def attachments(self) -> List[AttachmentMetadata]:
        return self._attachments

    def run(self) -> bool:
        if not super().run():
            return False

        try:
            self._attachments = (
                self.detached_layer.feature_attachments_for_identification(
                    self.feature_id
                )
            )
        except Exception as error:
            logger.exception("Failed to load feature attachments")
            self._error = error
            return False

        return True


class AttachmentThumbnailsTask(NgConnectTask):
    attachment_progress_changed = pyqtSignal(int, float)
    attachment_finished = pyqtSignal(int)

    def __init__(
        self,
        attachments: List[AttachmentMetadata],
        instance_uuid: str,
        connection_id: str,
        resource_id: int,
        generation: int,
    ) -> None:
        super().__init__(flags=QgsTask.Flags())
        self.setDescription(
            QgsApplication.translate(
                "AttachmentsTab", "Loading attachment previews"
            )
        )
        self.attachments = list(attachments)
        self.instance_uuid = instance_uuid
        self.connection_id = connection_id
        self.resource_id = resource_id
        self.generation = generation
        self._changed_attachment_ids: List[AttachmentId] = []
        self._failed_thumbnail_keys: Set[AttachmentThumbnailKey] = set()

    @property
    def changed_attachment_ids(self) -> List[AttachmentId]:
        return self._changed_attachment_ids

    @property
    def failed_thumbnail_keys(self) -> Set[AttachmentThumbnailKey]:
        return self._failed_thumbnail_keys

    def run(self) -> bool:
        if not super().run():
            return False

        total = len(self.attachments)
        for index, attachment in enumerate(self.attachments, start=1):
            if self.isCanceled():
                return False

            try:
                self.attachment_progress_changed.emit(attachment.aid, 0.0)
                self._download_thumbnail(attachment)
                self.attachment_progress_changed.emit(attachment.aid, 100.0)
                if total:
                    self.setProgress(index / total * 100)
            finally:
                self.attachment_finished.emit(attachment.aid)

        return True

    def _download_thumbnail(self, attachment: AttachmentMetadata) -> None:
        if not self._needs_thumbnail_download(attachment):
            return

        assert attachment.thumbnail_path is not None
        assert attachment.ngw_fid is not None
        assert attachment.ngw_aid is not None

        try:
            _download_attachment_thumbnail(
                self.connection_id,
                self.resource_id,
                attachment.ngw_fid,
                attachment.ngw_aid,
                attachment.thumbnail_path,
            )
        except Exception:
            if attachment.thumbnail_path.exists():
                attachment.thumbnail_path.unlink()
            self._failed_thumbnail_keys.add(
                _attachment_thumbnail_key(
                    self.connection_id,
                    self.resource_id,
                    attachment,
                )
            )
            logger.warning(
                "Failed to download attachment thumbnail: %s",
                attachment,
                exc_info=True,
            )
            return

        DetachedStorageServiceFactory.create().register_attachment_thumbnail(
            self.instance_uuid,
            self.resource_id,
            attachment.aid,
            fileobj=attachment.fileobj,
            feature_local_id=int(attachment.fid),
            feature_ngw_fid=attachment.ngw_fid,
            ngw_aid=attachment.ngw_aid,
        )
        self._changed_attachment_ids.append(attachment.aid)

    def _needs_thumbnail_download(
        self, attachment: AttachmentMetadata
    ) -> bool:
        return _needs_attachment_thumbnail_download(attachment)


class AttachmentsTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._detached_layer: Optional[DetachedLayer] = None
        self._feature_id: Optional[QgsFeatureId] = None
        self._loading_generation = 0
        self._attachments_task: Optional[IdentificationAttachmentsTask] = None
        self._thumbnails_task: Optional[AttachmentThumbnailsTask] = None
        self._attachment_batch_download_task: Optional[
            AttachmentBatchDownloadTask
        ] = None
        self._attachment_download_tasks: Dict[
            AttachmentId, AttachmentDownloadTask
        ] = {}
        self._pending_open_attachment_ids: Set[AttachmentId] = set()
        self._failed_thumbnail_keys: Set[AttachmentThumbnailKey] = set()
        self._is_read_only = True
        self._clipboard = Clipboard()

        self._attachment_added_connection: Optional[Any] = None
        self._attachment_updated_connection: Optional[Any] = None
        self._attachment_removed_connection: Optional[Any] = None

        self._load_ui()

    @property
    def view(self) -> QListView:
        return self._view_wrapper.view

    def set_feature(
        self, layer: QgsVectorLayer, feature_id: QgsFeatureId
    ) -> None:
        self.close_editor()

        detached_layer = NgConnectInterface.instance().detached_editing.layer(
            layer
        )
        keep_existing = (
            self._detached_layer is detached_layer
            and self._feature_id == feature_id
            and self._attachments_model.is_initialized
        )
        if not keep_existing:
            self._attachment_download_tasks.clear()
            self._pending_open_attachment_ids.clear()

        self._disconnect_attachment_signals()
        self._loading_generation += 1

        self._detached_layer = detached_layer
        self._feature_id = feature_id

        if not keep_existing:
            self._attachments_model.clear_attachments()
            self._view_wrapper.begin_loading(
                self.tr("Loading attachments"),
                self.tr("Fetching the attachment list."),
            )
        self._add_button.setDisabled(True)
        self._extra_button.setDisabled(True)

        task = IdentificationAttachmentsTask(
            detached_layer,
            feature_id,
            self._loading_generation,
            keep_existing=keep_existing,
        )
        task.taskCompleted.connect(self._on_attachments_task_finished)
        task.taskTerminated.connect(self._on_attachments_task_finished)
        self._attachments_task = task

        NgConnectInterface.instance().task_manager.addTask(task)

    def _connect_attachment_signals(
        self, detached_layer: DetachedLayer
    ) -> None:
        self._disconnect_attachment_signals()

        self._attachment_added_connection = (
            detached_layer.attachment_added.connect(self._on_attachment_added)
        )
        self._attachment_removed_connection = (
            detached_layer.attachment_removed.connect(
                self._on_attachment_removed_from_layer
            )
        )
        self._attachment_updated_connection = (
            detached_layer.attachment_updated.connect(
                self._on_attachment_updated_in_layer
            )
        )

    def clear_feature(self) -> None:
        self.close_editor()
        self._disconnect_attachment_signals()
        self._loading_generation += 1
        self._attachments_task = None
        self._thumbnails_task = None
        self._attachment_batch_download_task = None
        self._attachment_download_tasks.clear()
        self._pending_open_attachment_ids.clear()
        self._view_wrapper.end_loading()

        self._detached_layer = None
        self._feature_id = None

        self._attachments_model.clear_attachments()
        self._add_button.setDisabled(True)
        self._extra_button.setDisabled(True)

    def set_read_only(self, read_only: bool) -> None:
        self._is_read_only = read_only
        self._attachments_model.set_editable(not read_only)
        self._update_action_buttons_availability()
        self._view_wrapper.set_read_only(read_only)

    def _update_action_buttons_availability(self, *arguments: Any) -> None:
        del arguments

        has_feature = self._feature_id is not None
        is_ready = self._attachments_task is None
        has_attachments = self._attachments_model.rowCount() > 0

        self._add_button.setEnabled(
            not self._is_read_only and has_feature and is_ready
        )
        self._extra_button.setEnabled(
            has_feature and is_ready and has_attachments
        )

    def close_editor(self) -> None:
        self._view_wrapper.view.close_current_editor()

    def _load_ui(self) -> None:
        layout = QVBoxLayout(self)

        # View wrapper
        self._view_wrapper = AttachmentsViewWrapper(self)
        self._view_wrapper.view.open_attachment.connect(self._open_attachment)
        self._view_wrapper.view.cache_attachment.connect(
            self._start_attachment_download
        )
        self._view_wrapper.view.save_as.connect(self._save_attachment_as)
        self._view_wrapper.view.show_in_folder.connect(self._show_in_folder)
        self._view_wrapper.view.copy_attachment.connect(self._copy_attachment)
        self._view_wrapper.view.delete_attachment.connect(
            self._remove_attachment
        )
        self._view_wrapper.files_dropped.connect(self._add_files)
        layout.addWidget(self._view_wrapper)

        # Buttons row
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(3)

        self._add_button = QPushButton(self.tr("Add attachment"), self)
        self._add_button.clicked.connect(self._add_attachments)

        icon_color = QgsApplication.palette().text().color().name()
        self._add_button.setIcon(
            material_icon("attach_file_add", color=icon_color)
        )

        self._extra_button = QToolButton(self)
        self._extra_button.setFixedSize(
            self._add_button.sizeHint().height(),
            self._add_button.sizeHint().height(),
        )
        self._extra_button.setStyleSheet(
            """
            QToolButton::menu-indicator {
                image: none;
            }
            """
        )
        self._extra_button.setIcon(
            material_icon("more_horiz", color=icon_color)
        )

        buttons_layout.addWidget(self._add_button)
        buttons_layout.addWidget(self._extra_button)
        layout.addLayout(buttons_layout)

        # Extra menu
        extra_menu = QMenu(self)
        cache_all_action = extra_menu.addAction(
            material_icon("download_for_offline"),
            self.tr("Cache all attachments"),
        )
        cache_all_action.triggered.connect(self._start_cache_all_attachments)
        extra_menu.addAction(
            qgis_icon("mActionFileSaveAs.svg"),
            self.tr("Save all attachments as..."),
            self._save_all_attachments_as,
        )
        extra_menu.addSeparator()
        sort_menu = extra_menu.addMenu(
            material_icon("sort"), self.tr("Sort By")
        )
        sort_by_name_action = sort_menu.addAction(self.tr("Name"))
        sort_by_name_action.setCheckable(True)
        sort_by_name_action.setChecked(True)
        sort_by_name_action.setData(AttachmentsSortMode.BY_NAME)
        sort_by_type_action = sort_menu.addAction(self.tr("Type"))
        sort_by_type_action.setCheckable(True)
        sort_by_type_action.setData(AttachmentsSortMode.BY_TYPE)
        # sort_by_size_action = sort_menu.addAction(self.tr("Size"))
        # sort_by_size_action.setCheckable(True)
        # sort_by_size_action.setData(AttachmentsSortMode.BY_SIZE)

        sort_menu.addSeparator()

        sort_ascending_action = sort_menu.addAction(self.tr("A-Z"))
        sort_ascending_action.setCheckable(True)
        sort_ascending_action.setChecked(True)
        sort_ascending_action.setData(Qt.SortOrder.AscendingOrder)
        sort_descending_action = sort_menu.addAction(self.tr("Z-A"))
        sort_descending_action.setCheckable(True)
        sort_descending_action.setData(Qt.SortOrder.DescendingOrder)

        sort_by_group = QActionGroup(sort_menu)
        sort_by_group.addAction(sort_by_name_action)
        sort_by_group.addAction(sort_by_type_action)
        # sort_by_group.addAction(sort_by_size_action)
        sort_by_group.setExclusive(True)
        sort_by_group.triggered.connect(self._on_sort_by_changed)

        sort_order_group = QActionGroup(sort_menu)
        sort_order_group.addAction(sort_ascending_action)
        sort_order_group.addAction(sort_descending_action)
        sort_order_group.setExclusive(True)
        sort_order_group.triggered.connect(self._on_sort_order_changed)

        self._extra_button.setMenu(extra_menu)
        self._extra_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )

        # Model
        self._attachments_model = AttachmentsModel([], self)
        self._attachments_model.modelReset.connect(
            self._update_action_buttons_availability
        )
        self._attachments_model.rowsInserted.connect(
            self._update_action_buttons_availability
        )
        self._attachments_model.rowsRemoved.connect(
            self._update_action_buttons_availability
        )
        self._attachments_model.attachment_removed.connect(
            self._on_attachment_removed_from_model
        )
        self._attachments_model.attachment_updated.connect(
            self._on_attachment_updated_in_model
        )
        self._attachments_proxy = AttachmentsSortProxyModel(self)
        self._attachments_proxy.setSourceModel(self._attachments_model)
        self._attachments_proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self._view_wrapper.view.setModel(self._attachments_proxy)
        self._update_action_buttons_availability()

    def _disconnect_attachment_signals(self) -> None:
        with suppress(RuntimeError, TypeError):
            if self._attachment_added_connection is not None:
                self.disconnect(cast(Any, self._attachment_added_connection))
        self._attachment_added_connection = None

        with suppress(RuntimeError, TypeError):
            if self._attachment_updated_connection is not None:
                self.disconnect(cast(Any, self._attachment_updated_connection))
        self._attachment_updated_connection = None

        with suppress(RuntimeError, TypeError):
            if self._attachment_removed_connection is not None:
                self.disconnect(cast(Any, self._attachment_removed_connection))
        self._attachment_removed_connection = None

    @pyqtSlot()
    def _on_attachments_task_finished(self) -> None:
        task = self.sender()
        if not isinstance(task, IdentificationAttachmentsTask):
            return

        if (
            task is not self._attachments_task
            or task.generation != self._loading_generation
        ):
            return

        self._attachments_task = None

        if task.status() != QgsTask.TaskStatus.Complete:
            if task.keep_existing:
                self._connect_attachment_signals(task.detached_layer)
            else:
                self._attachments_model.set_attachments([])
            self._update_action_buttons_availability()
            self._view_wrapper.end_loading()
            return

        if task.keep_existing:
            self._attachments_model.refresh_attachments(task.attachments)
        else:
            self._attachments_model.set_attachments(task.attachments)
        self._connect_attachment_signals(task.detached_layer)
        self._update_action_buttons_availability()
        self._view_wrapper.end_loading()
        self._start_thumbnail_loading(task.attachments)

    def _start_thumbnail_loading(
        self, attachments: List[AttachmentMetadata]
    ) -> None:
        detached_layer = self._detached_layer
        if detached_layer is None:
            return

        connection_id = detached_layer.container.metadata.connection_id
        instance_uuid = detached_layer.container.metadata.instance_id
        resource_id = detached_layer.container.metadata.resource_id
        attachments_to_load = [
            attachment
            for attachment in attachments
            if self._should_download_attachment_thumbnail(
                connection_id,
                resource_id,
                attachment,
            )
        ]
        if not attachments_to_load:
            return

        for attachment in attachments_to_load:
            self._attachments_model.set_attachment_loading_progress(
                attachment.aid,
                0.0,
                AttachmentLoadingKind.PREVIEW,
            )

        task = AttachmentThumbnailsTask(
            attachments_to_load,
            instance_uuid,
            connection_id,
            resource_id,
            self._loading_generation,
        )
        task.attachment_progress_changed.connect(
            self._on_attachment_thumbnail_progress_changed
        )
        task.attachment_finished.connect(
            self._on_attachment_thumbnail_finished
        )
        task.taskCompleted.connect(self._on_thumbnails_task_finished)
        task.taskTerminated.connect(self._on_thumbnails_task_finished)
        self._thumbnails_task = task

        NgConnectInterface.instance().task_manager.addTask(task)

    def _should_download_attachment_thumbnail(
        self,
        connection_id: str,
        resource_id: int,
        attachment: AttachmentMetadata,
    ) -> bool:
        return (
            _needs_attachment_thumbnail_download(attachment)
            and _attachment_thumbnail_key(
                connection_id,
                resource_id,
                attachment,
            )
            not in self._failed_thumbnail_keys
        )

    @pyqtSlot()
    def _on_thumbnails_task_finished(self) -> None:
        task = self.sender()
        if not isinstance(task, AttachmentThumbnailsTask):
            return

        if (
            task is not self._thumbnails_task
            or task.generation != self._loading_generation
        ):
            return

        self._thumbnails_task = None
        self._failed_thumbnail_keys.update(task.failed_thumbnail_keys)
        self._clear_loading_progress_for_attachments(task.attachments)

        if (
            task.status() == QgsTask.TaskStatus.Complete
            and task.changed_attachment_ids
        ):
            self._attachments_model.update_cached_states()
            self._view_wrapper.view.viewport().update()

    @pyqtSlot(int, float)
    def _on_attachment_loading_progress_changed(
        self,
        attachment_id: AttachmentId,
        progress: float,
    ) -> None:
        self._attachments_model.set_attachment_loading_progress(
            attachment_id,
            progress,
        )

    @pyqtSlot(int, float)
    def _on_attachment_thumbnail_progress_changed(
        self,
        attachment_id: AttachmentId,
        progress: float,
    ) -> None:
        self._attachments_model.set_attachment_loading_progress(
            attachment_id,
            progress,
            AttachmentLoadingKind.PREVIEW,
        )

    @pyqtSlot(int)
    def _on_attachment_thumbnail_finished(
        self,
        attachment_id: AttachmentId,
    ) -> None:
        self._attachments_model.set_attachment_loading_progress(
            attachment_id,
            None,
        )
        self._attachments_model.update_cached_states()
        self._view_wrapper.view.viewport().update()

    def _clear_loading_progress_for_attachments(
        self,
        attachments: List[AttachmentMetadata],
    ) -> None:
        for attachment in attachments:
            self._attachments_model.set_attachment_loading_progress(
                attachment.aid,
                None,
            )

    @pyqtSlot(QgsFeatureId, AttachmentId)
    def _on_attachment_added(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> None:
        detached_layer = self._detached_layer
        if self._feature_id != feature_id or detached_layer is None:
            return

        new_attachment = detached_layer.feature_attachment(
            feature_id, attachment_id
        )
        assert new_attachment is not None
        self._attachments_model.add_attachment(new_attachment)
        self._start_thumbnail_loading([new_attachment])

    @pyqtSlot(QgsFeatureId, AttachmentId)
    def _on_attachment_updated_in_layer(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> None:
        detached_layer = self._detached_layer
        if self._feature_id != feature_id or detached_layer is None:
            return

        self._attachments_model.attachment_updated.disconnect(
            self._on_attachment_updated_in_model
        )
        attachment = detached_layer.feature_attachment(
            feature_id, attachment_id
        )
        assert attachment is not None
        self._attachments_model.update_attachment(attachment)
        self._start_thumbnail_loading([attachment])
        self._attachments_model.attachment_updated.connect(
            self._on_attachment_updated_in_model
        )

    @pyqtSlot(QgsFeatureId, AttachmentId)
    def _on_attachment_removed_from_layer(
        self, feature_id: QgsFeatureId, attachment_id: AttachmentId
    ) -> None:
        if self._feature_id != feature_id:
            return

        self._attachments_model.attachment_removed.disconnect(
            self._on_attachment_removed_from_model
        )
        self._attachments_model.remove_attachment(attachment_id)
        self._attachments_model.attachment_removed.connect(
            self._on_attachment_removed_from_model
        )

    @pyqtSlot(AttachmentId)
    def _on_attachment_updated_in_model(
        self, attachment_id: AttachmentId
    ) -> None:
        detached_layer = self._detached_layer
        if detached_layer is None:
            return

        attachment = self._attachments_model.attachment_by_id(attachment_id)
        if attachment is None:
            return

        if not self._ensure_edit_mode_for_attachment_changes():
            self._restore_attachment_from_layer(attachment_id)
            return

        detached_layer.update_attachment(attachment)

    @pyqtSlot(AttachmentId)
    def _on_attachment_removed_from_model(
        self, attachment_id: AttachmentId
    ) -> None:
        detached_layer = self._detached_layer
        if detached_layer is None or self._feature_id is None:
            return

        detached_layer.remove_attachment(self._feature_id, attachment_id)

    def _add_attachments(self) -> None:
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter(self.tr("All Files (*)"))
        file_dialog.setWindowTitle(self.tr("Select Attachments"))

        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            self._add_files(selected_files)

    def _add_files(self, paths: List[str]) -> None:
        detached_layer = self._detached_layer
        if (
            detached_layer is None
            or self._feature_id is None
            or not paths
            or not self._ensure_edit_mode_for_attachment_changes()
        ):
            return

        for file_path in paths:
            path = Path(file_path)
            logger.info(f"Added file: {path}")
            try:
                detached_layer.add_attachment(self._feature_id, path)
            except OSError:
                message = self.tr(
                    'Cannot add attachment "{}" because its file is unavailable.'
                ).format(path.name)
                logger.exception(message)
                NgConnectInterface.instance().notifier.display_message(
                    message,
                    level=Qgis.MessageLevel.Critical,
                )

    def _remove_attachment(self, index: QModelIndex) -> None:
        if not index.isValid():
            return

        if not self._ensure_edit_mode_for_attachment_changes():
            return

        model = index.model()
        source_index = index
        source_model = model

        if isinstance(model, QSortFilterProxyModel):
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()

        if source_model is None or not source_index.isValid():
            return

        source_model.removeRow(source_index.row(), source_index.parent())

    def _ensure_edit_mode_for_attachment_changes(self) -> bool:
        detached_layer = self._detached_layer
        if detached_layer is None:
            return False

        layer = detached_layer.qgs_layer
        if layer.isEditable():
            return True

        if layer.readOnly():
            return False

        if not layer.startEditing():
            return False

        NgConnectInterface.instance().notifier.display_message(
            self.tr('Edit mode enabled automatically for layer "{}".').format(
                layer.name()
            ),
            level=Qgis.MessageLevel.Info,
            duration=5,
        )
        return True

    def _restore_attachment_from_layer(
        self, attachment_id: AttachmentId
    ) -> None:
        detached_layer = self._detached_layer
        if detached_layer is None or self._feature_id is None:
            return

        try:
            attachment = detached_layer.feature_attachment(
                self._feature_id, attachment_id
            )
        except Exception:
            logger.exception("Failed to restore attachment from layer")
            return

        self._attachments_model.attachment_updated.disconnect(
            self._on_attachment_updated_in_model
        )
        self._attachments_model.update_attachment(attachment)
        self._attachments_model.attachment_updated.connect(
            self._on_attachment_updated_in_model
        )

    @pyqtSlot(QAction)
    def _on_sort_by_changed(self, action: QAction) -> None:  # type: ignore[reportInvalidTypeForm]
        if not action.isChecked():
            return

        sort_key_value = action.data()
        if sort_key_value is None:
            return

        try:
            sort_key = AttachmentsSortMode(sort_key_value)
        except ValueError:
            return

        self._attachments_proxy.sort_key = sort_key

    @pyqtSlot(QAction)
    def _on_sort_order_changed(self, action: QAction) -> None:  # type: ignore[reportInvalidTypeForm]
        if not action.isChecked():
            return

        sort_order = action.data()
        if sort_order not in (
            Qt.SortOrder.AscendingOrder,
            Qt.SortOrder.DescendingOrder,
        ):
            return

        self._attachments_proxy.sort(0, sort_order)

    def _cache_all_attachments(self) -> None:
        detached_layer = self._detached_layer
        if detached_layer is None or self._feature_id is None:
            return

        layer = detached_layer.qgs_layer
        feature = layer.getFeature(self._feature_id)

        context = QgsExpressionContext(
            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
        )
        expression = QgsExpression("ngw_feature_id()")
        expression.prepare(context)
        context.setFeature(feature)
        feature_ngw_fid = expression.evaluate(context)

        resource_id = detached_layer.container.metadata.resource_id
        connection_id = detached_layer.container.metadata.connection_id
        connection = NgwConnectionsManager().connection(connection_id)
        assert connection is not None

        attachments = detached_layer.feature_attachments(self._feature_id)
        attachments_to_download = []

        for attachment in attachments:
            if attachment.ngw_aid is None:
                continue

            attachment_path = detached_layer.attachment_path(
                self._feature_id, attachment.aid
            )
            assert attachment_path is not None
            attachments_to_download.append((attachment, attachment_path))

        if not attachments_to_download:
            return

        for attachment, attachment_path in attachments_to_download:
            self._attachments_model.set_attachment_loading_progress(
                attachment.aid,
                0.0,
            )
            try:
                self._download_attachment(
                    connection,
                    resource_id,
                    feature_ngw_fid,
                    attachment,
                    attachment_path,
                )
            finally:
                self._attachments_model.set_attachment_loading_progress(
                    attachment.aid,
                    None,
                )

        self._attachments_model.update_cached_states()

        logger.debug("Downloaded")

    def _start_cache_all_attachments(self) -> None:
        if self._attachment_batch_download_task is not None:
            return

        contexts = []
        for row in range(self._attachments_proxy.rowCount()):
            index = self._attachments_proxy.index(row, 0)
            context = self._attachment_download_context(index)
            if context is None:
                continue

            attachment_id = context.attachment.aid
            if self._is_attachment_download_in_progress(attachment_id):
                continue

            contexts.append(context)

        if not contexts:
            return

        for context in contexts:
            self._attachments_model.set_attachment_loading_progress(
                context.attachment.aid,
                0.0,
            )

        task = AttachmentBatchDownloadTask(contexts)
        task.attachment_progress_changed.connect(
            self._on_attachment_loading_progress_changed
        )
        task.attachment_finished.connect(
            self._on_attachment_batch_item_finished
        )
        task.taskCompleted.connect(self._on_attachment_batch_task_finished)
        task.taskTerminated.connect(self._on_attachment_batch_task_finished)
        self._attachment_batch_download_task = task

        NgConnectInterface.instance().task_manager.addTask(task)
        logger.debug("Downloading attachments")

    def _open_attachment(self, index: QModelIndex) -> None:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )

        if attachment is None:
            return

        if _is_image_attachment(attachment):
            self._open_image_preview(index)
            return

        if attachment.file_path is None:
            return

        if not attachment.file_path.exists():
            if self._start_attachment_download(index):
                self._pending_open_attachment_ids.add(attachment.aid)
            return

        self._open_attachment_path(attachment.file_path)

    def _open_image_preview(self, index: QModelIndex) -> None:
        items = self._image_preview_items()
        image_row = self._image_preview_row(index)
        if not items or image_row is None:
            return

        dialog = ImagePreviewDialog(
            items,
            image_row,
            self,
            ensure_item_ready=self._cache_image_preview_item,
            window_title_suffix=PLUGIN_NAME,
        )
        dialog.exec()

    def _image_preview_items(self) -> List[ImagePreviewItem]:
        items = []
        for row in range(self._attachments_proxy.rowCount()):
            index = self._attachments_proxy.index(row, 0)
            attachment: Optional[AttachmentMetadata] = index.data(
                AttachmentsModel.Roles.ATTACHMENT
            )
            if attachment is None or not _is_image_attachment(attachment):
                continue

            items.append(
                ImagePreviewItem(
                    file_path=attachment.file_path,
                    file_name=attachment.name or "",
                    description=attachment.description,
                )
            )

        return items

    def _image_preview_row(self, index: QModelIndex) -> Optional[int]:
        image_row = 0
        for row in range(self._attachments_proxy.rowCount()):
            current_index = self._attachments_proxy.index(row, 0)
            attachment: Optional[AttachmentMetadata] = current_index.data(
                AttachmentsModel.Roles.ATTACHMENT
            )
            if attachment is None or not _is_image_attachment(attachment):
                continue

            if current_index == index:
                return image_row

            image_row += 1

        return None

    def _cache_image_preview_item(self, image_row: int) -> bool:
        current_image_row = 0
        for row in range(self._attachments_proxy.rowCount()):
            index = self._attachments_proxy.index(row, 0)
            attachment: Optional[AttachmentMetadata] = index.data(
                AttachmentsModel.Roles.ATTACHMENT
            )
            if attachment is None or not _is_image_attachment(attachment):
                continue

            if current_image_row == image_row:
                if (
                    attachment.file_path is not None
                    and attachment.file_path.exists()
                ):
                    return True

                is_started = self._start_attachment_download(index)
                self._view_wrapper.view.viewport().update()
                return is_started

            current_image_row += 1

        return False

    def _start_attachment_download(self, index: QModelIndex) -> bool:
        context = self._attachment_download_context(index)
        if context is None:
            return False

        attachment_id = context.attachment.aid
        if self._is_attachment_download_in_progress(attachment_id):
            return True

        task = AttachmentDownloadTask(context)
        task.progressChanged.connect(
            lambda progress, aid=attachment_id: (
                self._on_attachment_loading_progress_changed(aid, progress)
            )
        )
        task.taskCompleted.connect(self._on_attachment_download_task_finished)
        task.taskTerminated.connect(self._on_attachment_download_task_finished)
        self._attachment_download_tasks[attachment_id] = task
        self._attachments_model.set_attachment_loading_progress(
            attachment_id,
            0.0,
        )

        NgConnectInterface.instance().task_manager.addTask(task)
        return True

    def _is_attachment_download_in_progress(
        self,
        attachment_id: AttachmentId,
    ) -> bool:
        if attachment_id in self._attachment_download_tasks:
            return True

        batch_task = self._attachment_batch_download_task
        return (
            batch_task is not None
            and attachment_id in batch_task.attachment_ids
        )

    def _attachment_download_context(
        self, index: QModelIndex
    ) -> Optional[AttachmentDownloadContext]:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )
        detached_layer = self._detached_layer
        if detached_layer is None or self._feature_id is None:
            return None

        if (
            attachment is None
            or attachment.file_path is None
            or attachment.file_path.exists()
            or attachment.ngw_aid is None
        ):
            return None

        connection_id = detached_layer.container.metadata.connection_id
        ngw_connection = NgwConnectionsManager().connection(connection_id)
        assert ngw_connection is not None

        with closing(
            make_connection(detached_layer.container.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                """
                SELECT features.ngw_fid
                FROM ngw_features_attachments AS attachments
                JOIN ngw_features_metadata AS features
                ON attachments.fid = features.fid
                WHERE attachments.fid = ? AND attachments.aid = ?;
                """,
                (self._feature_id, attachment.aid),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            feature_ngw_fid = row[0]
            if feature_ngw_fid is None:
                return None

        return AttachmentDownloadContext(
            connection_id=ngw_connection.id,
            connection_url=ngw_connection.url,
            connection_domain_uuid=ngw_connection.domain_uuid,
            resource_id=detached_layer.container.metadata.resource_id,
            feature_ngw_fid=feature_ngw_fid,
            attachment=attachment,
            attachment_path=attachment.file_path,
        )

    @pyqtSlot()
    def _on_attachment_download_task_finished(self) -> None:
        task = self.sender()
        if not isinstance(task, AttachmentDownloadTask):
            return

        if self._attachment_download_tasks.get(task.attachment_id) is not task:
            return

        self._attachment_download_tasks.pop(task.attachment_id, None)
        self._attachments_model.set_attachment_loading_progress(
            task.attachment_id,
            None,
        )

        if task.status() != QgsTask.TaskStatus.Complete:
            self._pending_open_attachment_ids.discard(task.attachment_id)
            return

        self._attachments_model.update_cached_states()
        self._view_wrapper.view.viewport().update()
        self._open_pending_attachment(task.attachment_id)

    def _open_pending_attachment(self, attachment_id: AttachmentId) -> None:
        if attachment_id not in self._pending_open_attachment_ids:
            return

        self._pending_open_attachment_ids.remove(attachment_id)
        attachment = self._attachments_model.attachment_by_id(attachment_id)
        if attachment is None or attachment.file_path is None:
            return

        if not attachment.file_path.exists():
            return

        self._open_attachment_path(attachment.file_path)

    def _open_attachment_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @pyqtSlot(int)
    def _on_attachment_batch_item_finished(
        self,
        attachment_id: AttachmentId,
    ) -> None:
        self._attachments_model.set_attachment_loading_progress(
            attachment_id,
            None,
        )
        self._attachments_model.update_cached_states()
        self._view_wrapper.view.viewport().update()

    @pyqtSlot()
    def _on_attachment_batch_task_finished(self) -> None:
        task = self.sender()
        if not isinstance(task, AttachmentBatchDownloadTask):
            return

        if task is not self._attachment_batch_download_task:
            return

        self._attachment_batch_download_task = None
        for attachment_id in task.attachment_ids:
            self._attachments_model.set_attachment_loading_progress(
                attachment_id,
                None,
            )

        self._attachments_model.update_cached_states()
        self._view_wrapper.view.viewport().update()

    def _show_in_folder(self, index: QModelIndex) -> None:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )

        if attachment is None:
            return

        assert attachment.file_path is not None
        reveal_in_file_manager(attachment.file_path)

    def _copy_attachment(self, index: QModelIndex) -> None:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )

        if attachment is None or not _is_image_attachment(attachment):
            return

        self._cache_attachment(index)
        if attachment.file_path is None or not attachment.file_path.exists():
            return

        pixmap = QPixmap(str(attachment.file_path))
        self._clipboard.copy_image(pixmap)

    def _save_attachment_as(self, index: QModelIndex) -> None:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )

        if attachment is None:
            return

        mime_type_database = QMimeDatabase()
        mime_type = mime_type_database.mimeTypeForName(attachment.mime_type)

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setWindowTitle(self.tr("Save Attachment As"))
        file_dialog.setDefaultSuffix(mime_type.preferredSuffix())
        attachment_name = attachment.name.replace("/", "_").replace("\\", "_")
        attachment_name = attachment_name[:255]
        file_dialog.selectFile(attachment_name)
        file_dialog.setNameFilter(mime_type.filterString())

        if not file_dialog.exec():
            return

        self._cache_attachment(index)

        target_path = Path(file_dialog.selectedFiles()[0])

        assert attachment.file_path is not None
        shutil.copy2(attachment.file_path, target_path)

    def _save_all_attachments_as(self) -> None:
        mime_type_database = QMimeDatabase()
        mime_type = mime_type_database.mimeTypeForName("application/zip")

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setWindowTitle(self.tr("Save Feature Attachments As"))
        file_dialog.setDefaultSuffix(mime_type.preferredSuffix())
        file_dialog.setNameFilter(mime_type.filterString())

        if not file_dialog.exec():
            return

        self._cache_all_attachments()

        target_path = Path(file_dialog.selectedFiles()[0])
        with ZipFile(target_path, "w", ZIP_DEFLATED) as zipf:
            for row in range(self._attachments_proxy.rowCount()):
                index = self._attachments_proxy.index(row, 0)
                attachment: Optional[AttachmentMetadata] = index.data(
                    AttachmentsModel.Roles.ATTACHMENT
                )
                if attachment is None or not attachment.file_path.exists():
                    continue
                zipf.write(
                    str(attachment.file_path),
                    arcname=(attachment.name or "")[:255],
                )

    def _cache_attachment(self, index: QModelIndex) -> None:
        attachment: Optional[AttachmentMetadata] = index.data(
            AttachmentsModel.Roles.ATTACHMENT
        )

        detached_layer = self._detached_layer
        if detached_layer is None or self._feature_id is None:
            return

        if (
            not attachment
            or attachment.file_path is None
            or attachment.file_path.exists()
        ):
            return

        connection_id = detached_layer.container.metadata.connection_id
        ngw_connection = NgwConnectionsManager().connection(connection_id)
        assert ngw_connection is not None

        with closing(
            make_connection(detached_layer.container.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                """
                SELECT features.ngw_fid, attachments.ngw_aid
                FROM ngw_features_attachments AS attachments
                JOIN ngw_features_metadata AS features
                ON attachments.fid = features.fid
                WHERE attachments.fid = ? AND attachments.aid = ?;
                """,
                (self._feature_id, attachment.aid),
            )
            rows = cursor.fetchall()
            ngw_fid, _ngw_aid = rows[0]

        assert attachment.file_path is not None
        self._attachments_model.set_attachment_loading_progress(
            attachment.aid,
            0.0,
        )
        try:
            self._download_attachment(
                ngw_connection,
                detached_layer.container.metadata.resource_id,
                ngw_fid,
                attachment,
                attachment.file_path,
            )
        finally:
            self._attachments_model.set_attachment_loading_progress(
                attachment.aid,
                None,
            )
        self._attachments_model.update_cached_states()

    def _download_attachment(
        self,
        connection: NgwConnection,
        resource_id: int,
        feature_ngw_fid: Union[str, int],
        attachment: AttachmentMetadata,
        attachment_path: Path,
    ) -> None:
        feedback = QgsFeedback()
        feedback.progressChanged.connect(
            lambda progress, aid=attachment.aid: (
                self._on_attachment_loading_progress_changed(aid, progress)
            )
        )
        AttachmentDownloadTask.download(
            AttachmentDownloadContext(
                connection_id=connection.id,
                connection_url=connection.url,
                connection_domain_uuid=connection.domain_uuid,
                resource_id=resource_id,
                feature_ngw_fid=feature_ngw_fid,
                attachment=attachment,
                attachment_path=attachment_path,
            ),
            feedback=feedback,
        )
