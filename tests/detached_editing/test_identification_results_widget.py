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

from pathlib import Path
from typing import Callable, Optional, Tuple, cast
from unittest.mock import Mock

import qgis.utils
from qgis.core import Qgis, QgsApplication, QgsTask, QgsVectorLayer
from qgis.gui import QgisInterface, QgsAttributeEditorContext
from qgis.PyQt.QtWidgets import QScrollArea, QTabWidget, QWidget

from nextgis_connect.legacy.detached_editing.identification.attachment_download import (
    AttachmentBatchDownloadTask,
    AttachmentDownloadContext,
    AttachmentDownloadTask,
)
from nextgis_connect.legacy.detached_editing.identification.attachments_model import (
    AttachmentLoadingKind,
)
from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.legacy.detached_editing.identification.types import (
    IdentificationTab,
)
from nextgis_connect.legacy.detached_editing.identification.ui import (
    attachments_tab as attachments_tab_module,
)
from nextgis_connect.legacy.detached_editing.identification.ui import (
    identification_results_widget as identification_results_widget_module,
)
from nextgis_connect.legacy.detached_editing.identification.ui.attachments_tab import (
    AttachmentsTab,
)
from nextgis_connect.legacy.detached_editing.identification.ui.identification_results_widget import (
    IdentificationResultsWidget,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    DetachedLayerState,
)
from nextgis_connect.shared.constants import PACKAGE_NAME


class _IdentificationWidgetHarness:
    def __init__(self, current_tab: IdentificationTab) -> None:
        self.tab_widget = QTabWidget()
        self._is_changing_tab_availability = False
        self.overlay_update_count = 0

        self.tab_widget.addTab(QWidget(self.tab_widget), "Attributes")
        self.tab_widget.addTab(QWidget(self.tab_widget), "Attachments")
        self.tab_widget.addTab(QWidget(self.tab_widget), "Description")
        self.tab_widget.setCurrentIndex(current_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def set_feature_data_tabs_enabled(self, enabled: bool) -> None:
        method_name = (
            "_IdentificationResultsWidget__set_feature_data_tabs_enabled"
        )
        method = cast(
            Callable[["_IdentificationWidgetHarness", bool], None],
            getattr(IdentificationResultsWidget, method_name),
        )
        method(self, enabled)

    def close(self) -> None:
        self.tab_widget.close()
        self.tab_widget.deleteLater()

    def _update_overlay_geometry(self) -> None:
        self.overlay_update_count += 1

    def _on_tab_changed(self, selected_tab: int) -> None:
        method_name = "_IdentificationResultsWidget__on_tab_changed"
        method = cast(
            Callable[["_IdentificationWidgetHarness", int], None],
            getattr(IdentificationResultsWidget, method_name),
        )
        method(self, selected_tab)


class _FeatureRefreshHarness:
    def __init__(self, current_index: int = 0) -> None:
        self.features_combobox = Mock()
        self.features_combobox.currentIndex.return_value = current_index
        self.selected_result = Mock()
        self.selected_result.mFeature.id.return_value = 7

        refreshed_feature = Mock()
        refreshed_feature.isValid.return_value = True
        self.selected_result.mLayer.getFeature.return_value = refreshed_feature

        self._IdentificationResultsWidget__current_feature_result = Mock(
            return_value=self.selected_result
        )
        self._IdentificationResultsWidget__on_feature_changed = Mock()
        self._IdentificationResultsWidget__current_feature_key = Mock(
            return_value=("layer-id", 7)
        )
        self._IdentificationResultsWidget__remove_feature_keys = Mock()


def _install_plugin_mock() -> Tuple[Mock, Optional[object]]:
    plugin = Mock()
    plugin.path = Path(__file__).resolve().parents[2] / ("src/nextgis_connect")
    previous_plugin = qgis.utils.plugins.get(PACKAGE_NAME)
    qgis.utils.plugins[PACKAGE_NAME] = plugin
    return plugin, previous_plugin


def _restore_plugin_mock(previous_plugin: Optional[object]) -> None:
    if previous_plugin is None:
        qgis.utils.plugins.pop(PACKAGE_NAME, None)
    else:
        qgis.utils.plugins[PACKAGE_NAME] = previous_plugin


def _edit_mode_widget_mock() -> Mock:
    widget = Mock()
    widget.edit_button = Mock()
    widget._attachments_tab = Mock()
    widget._description_tab = Mock()
    widget._form = Mock()

    update_attachments_method = (
        "_IdentificationResultsWidget__update_attachments_editing_availability"
    )
    set_form_mode_method = (
        "_IdentificationResultsWidget__set_attribute_form_edit_mode"
    )
    setattr(widget, update_attachments_method, Mock())
    setattr(
        widget,
        set_form_mode_method,
        getattr(IdentificationResultsWidget, set_form_mode_method).__get__(
            widget
        ),
    )
    return widget


def _update_edit_mode(widget: Mock, is_enabled: bool) -> None:
    method_name = "_IdentificationResultsWidget__update_edit_mode"
    getattr(IdentificationResultsWidget, method_name)(widget, is_enabled)


class TestIdentificationResultsWidget:
    def test_unload_is_idempotent_for_open_dock(
        self, qgis_iface: QgisInterface
    ) -> None:
        previous_plugin = _install_plugin_mock()[1]

        widget = IdentificationResultsWidget(qgis_iface.mapCanvas())
        try:
            assert isinstance(widget.attributes_scroll_area, QScrollArea)
            assert widget.attributes_scroll_area.widgetResizable()
            assert (
                widget.attributes_tab.layout().indexOf(
                    widget.attributes_scroll_area
                )
                >= 0
            )

            widget.unload()
            widget.unload()
        finally:
            widget.close()
            widget.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_auto_start_edit_mode_enables_editing_and_notifies(
        self, qgis_iface: QgisInterface
    ) -> None:
        plugin, previous_plugin = _install_plugin_mock()
        layer = QgsVectorLayer(
            "Point?field=id:integer", "Editable layer", "memory"
        )
        tab = AttachmentsTab()
        tab._detached_layer = Mock(qgs_layer=layer)

        try:
            is_editing_started = tab._ensure_edit_mode_for_attachment_changes()

            assert is_editing_started
            assert layer.isEditable()
            plugin.notifier.display_message.assert_called_once()

            call_args = plugin.notifier.display_message.call_args
            assert "Edit mode enabled automatically" in call_args.args[0]
            assert call_args.kwargs["level"] == Qgis.MessageLevel.Info
            assert call_args.kwargs["duration"] == 5
        finally:
            if layer.isEditable():
                layer.rollBack()
            layer.deleteLater()
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_auto_start_edit_mode_ignores_read_only_layer(
        self, qgis_iface: QgisInterface
    ) -> None:
        plugin, previous_plugin = _install_plugin_mock()
        layer = QgsVectorLayer(
            "Point?field=id:integer", "Read-only layer", "memory"
        )
        layer.setReadOnly(True)
        tab = AttachmentsTab()
        tab._detached_layer = Mock(qgs_layer=layer)

        try:
            is_editing_started = tab._ensure_edit_mode_for_attachment_changes()

            assert not is_editing_started
            assert not layer.isEditable()
            plugin.notifier.display_message.assert_not_called()
        finally:
            layer.deleteLater()
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_add_files_notifies_when_attachment_file_is_unavailable(
        self,
    ) -> None:
        plugin, previous_plugin = _install_plugin_mock()
        detached_layer = Mock()
        detached_layer.add_attachment.side_effect = FileNotFoundError()
        tab = AttachmentsTab()
        tab._detached_layer = detached_layer
        tab._feature_id = 1
        tab._ensure_edit_mode_for_attachment_changes = Mock(return_value=True)

        try:
            tab._add_files(["/unavailable/photo.jpg"])

            detached_layer.add_attachment.assert_called_once_with(
                1, Path("/unavailable/photo.jpg")
            )
            plugin.notifier.display_message.assert_called_once()
            call_args = plugin.notifier.display_message.call_args
            assert "photo.jpg" in call_args.args[0]
            assert call_args.kwargs["level"] == Qgis.MessageLevel.Critical
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_thumbnail_loading_uses_item_progress_without_overlay(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        plugin, previous_plugin = _install_plugin_mock()
        attachment = AttachmentMetadata(
            fid=1,
            aid=2,
            name="photo.jpg",
            mime_type="image/jpeg",
        )
        tab = AttachmentsTab()
        tab._detached_layer = Mock(
            container=Mock(
                metadata=Mock(
                    connection_id="connection",
                    instance_id="instance",
                    resource_id=1,
                )
            )
        )
        tab._attachments_model.set_attachments([attachment])
        tab._view_wrapper.begin_loading = Mock()
        tab._view_wrapper.end_loading = Mock()
        tab._should_download_attachment_thumbnail = Mock(return_value=True)

        try:
            tab._start_thumbnail_loading([attachment])

            tab._view_wrapper.begin_loading.assert_not_called()
            tab._view_wrapper.end_loading.assert_not_called()
            assert tab._attachments_model.index_for_attachment_id(2).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert (
                tab._attachments_model.index_for_attachment_id(2).data(
                    tab._attachments_model.Roles.LOADING_KIND
                )
                == AttachmentLoadingKind.PREVIEW.value
            )
            plugin.task_manager.addTask.assert_called_once()
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_image_preview_requests_only_current_item(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        del qgis_app

        dialog = Mock()
        dialog_class = Mock(return_value=dialog)
        _plugin, previous_plugin = _install_plugin_mock()
        monkeypatch.setattr(
            attachments_tab_module,
            "ImagePreviewDialog",
            dialog_class,
        )
        tab = AttachmentsTab()
        tab._attachments_model.set_attachments(
            [
                AttachmentMetadata(
                    fid=1,
                    aid=1,
                    name="first.jpg",
                    mime_type="image/jpeg",
                    file_path=tmp_path / "first.jpg",
                ),
                AttachmentMetadata(
                    fid=1,
                    aid=2,
                    name="second.jpg",
                    mime_type="image/jpeg",
                    file_path=tmp_path / "second.jpg",
                ),
            ]
        )

        try:
            tab._open_image_preview(tab._attachments_proxy.index(0, 0))

            dialog_class.assert_called_once()
            assert len(dialog_class.call_args.args) == 2
            call_kwargs = dialog_class.call_args.kwargs
            assert call_kwargs.get("prefetch_radius", 0) == 0
            dialog.exec.assert_called_once()
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_cache_all_starts_batch_download_task(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        tab._attachments_model.set_attachments(
            [
                AttachmentMetadata(
                    fid=1,
                    aid=1,
                    name="first.pdf",
                    mime_type="application/pdf",
                    file_path=tmp_path / "first.pdf",
                ),
                AttachmentMetadata(
                    fid=1,
                    aid=2,
                    name="second.pdf",
                    mime_type="application/pdf",
                    file_path=tmp_path / "second.pdf",
                ),
            ]
        )

        def attachment_download_context(index):
            attachment = index.data(tab._attachments_model.Roles.ATTACHMENT)
            return AttachmentDownloadContext(
                connection_id="connection",
                connection_url="https://example.test",
                connection_domain_uuid="domain",
                resource_id=1,
                feature_ngw_fid=1,
                attachment=attachment,
                attachment_path=attachment.file_path,
            )

        tab._attachment_download_context = Mock(
            side_effect=attachment_download_context
        )

        try:
            tab._start_cache_all_attachments()

            _plugin.task_manager.addTask.assert_called_once()
            task = _plugin.task_manager.addTask.call_args.args[0]

            assert isinstance(task, AttachmentBatchDownloadTask)
            assert task.attachment_ids == [1, 2]
            assert tab._attachments_model.index_for_attachment_id(1).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert tab._attachments_model.index_for_attachment_id(2).data(
                tab._attachments_model.Roles.IS_LOADING
            )
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_thumbnail_finish_clears_only_finished_item(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        tab._attachments_model.set_attachments(
            [
                AttachmentMetadata(
                    fid=1,
                    aid=1,
                    name="first.jpg",
                    mime_type="image/jpeg",
                ),
                AttachmentMetadata(
                    fid=1,
                    aid=2,
                    name="second.jpg",
                    mime_type="image/jpeg",
                ),
            ]
        )
        tab._attachments_model.set_attachment_loading_progress(
            1,
            50.0,
            AttachmentLoadingKind.PREVIEW,
        )
        tab._attachments_model.set_attachment_loading_progress(
            2,
            50.0,
            AttachmentLoadingKind.PREVIEW,
        )

        try:
            tab._on_attachment_thumbnail_finished(1)

            assert not tab._attachments_model.index_for_attachment_id(1).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert tab._attachments_model.index_for_attachment_id(2).data(
                tab._attachments_model.Roles.IS_LOADING
            )
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_batch_download_finish_clears_only_finished_item(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        tab._attachments_model.set_attachments(
            [
                AttachmentMetadata(
                    fid=1,
                    aid=1,
                    name="first.pdf",
                    mime_type="application/pdf",
                ),
                AttachmentMetadata(
                    fid=1,
                    aid=2,
                    name="second.pdf",
                    mime_type="application/pdf",
                ),
            ]
        )
        tab._attachments_model.set_attachment_loading_progress(1, 50.0)
        tab._attachments_model.set_attachment_loading_progress(2, 50.0)

        try:
            tab._on_attachment_batch_item_finished(1)

            assert not tab._attachments_model.index_for_attachment_id(1).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert tab._attachments_model.index_for_attachment_id(2).data(
                tab._attachments_model.Roles.IS_LOADING
            )
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_download_task_finish_clears_only_finished_item(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        first_attachment = AttachmentMetadata(
            fid=1,
            aid=1,
            name="first.pdf",
            mime_type="application/pdf",
            file_path=tmp_path / "first.pdf",
        )
        second_attachment = AttachmentMetadata(
            fid=1,
            aid=2,
            name="second.pdf",
            mime_type="application/pdf",
            file_path=tmp_path / "second.pdf",
        )
        tab._attachments_model.set_attachments(
            [first_attachment, second_attachment]
        )
        tab._attachments_model.set_attachment_loading_progress(1, 50.0)
        tab._attachments_model.set_attachment_loading_progress(2, 50.0)
        first_task = AttachmentDownloadTask(
            AttachmentDownloadContext(
                connection_id="connection",
                connection_url="https://example.test",
                connection_domain_uuid="domain",
                resource_id=1,
                feature_ngw_fid=1,
                attachment=first_attachment,
                attachment_path=tmp_path / "first.pdf",
            )
        )
        second_task = AttachmentDownloadTask(
            AttachmentDownloadContext(
                connection_id="connection",
                connection_url="https://example.test",
                connection_domain_uuid="domain",
                resource_id=1,
                feature_ngw_fid=1,
                attachment=second_attachment,
                attachment_path=tmp_path / "second.pdf",
            )
        )
        tab._attachment_download_tasks = {
            1: first_task,
            2: second_task,
        }
        monkeypatch.setattr(AttachmentsTab, "sender", lambda self: first_task)

        try:
            tab._on_attachment_download_task_finished()

            assert not tab._attachments_model.index_for_attachment_id(1).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert tab._attachments_model.index_for_attachment_id(2).data(
                tab._attachments_model.Roles.IS_LOADING
            )
            assert tab._attachment_download_tasks == {2: second_task}
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_open_attachment_starts_download_when_file_is_missing(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        attachment = AttachmentMetadata(
            fid=1,
            aid=1,
            name="report.pdf",
            mime_type="application/pdf",
            file_path=tmp_path / "report.pdf",
        )
        tab._attachments_model.set_attachments([attachment])
        tab._start_attachment_download = Mock(return_value=True)
        tab._open_attachment_path = Mock()

        try:
            tab._open_attachment(tab._attachments_proxy.index(0, 0))

            tab._start_attachment_download.assert_called_once()
            tab._open_attachment_path.assert_not_called()
            assert tab._pending_open_attachment_ids == {1}
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_open_attachment_opens_local_new_file_when_it_exists(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        attachment_path = tmp_path / "report.pdf"
        attachment_path.write_bytes(b"PDF")
        attachment = AttachmentMetadata(
            fid=1,
            aid=-1,
            name="report.pdf",
            mime_type="application/pdf",
            file_path=attachment_path,
        )
        tab._attachments_model.set_attachments([attachment])
        tab._start_attachment_download = Mock(return_value=True)
        tab._open_attachment_path = Mock()

        try:
            tab._open_attachment(tab._attachments_proxy.index(0, 0))

            tab._open_attachment_path.assert_called_once_with(attachment_path)
            tab._start_attachment_download.assert_not_called()
            assert tab._pending_open_attachment_ids == set()
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_extra_actions_button_follows_attachment_count(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        tab._feature_id = 1

        try:
            tab.set_read_only(False)

            assert tab._add_button.isEnabled()
            assert not tab._extra_button.isEnabled()

            tab._attachments_model.set_attachments(
                [
                    AttachmentMetadata(
                        fid=1,
                        aid=1,
                        name="report.pdf",
                        mime_type="application/pdf",
                    )
                ]
            )

            assert tab._add_button.isEnabled()
            assert tab._extra_button.isEnabled()

            tab._attachments_model.clear_attachments()

            assert tab._add_button.isEnabled()
            assert not tab._extra_button.isEnabled()
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_refresh_existing_attachments_preserves_selection(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        tab = AttachmentsTab()
        first_attachment = AttachmentMetadata(
            fid=1,
            aid=1,
            name="a.pdf",
        )
        second_attachment = AttachmentMetadata(
            fid=1,
            aid=2,
            name="b.pdf",
            description="old",
        )
        updated_second_attachment = AttachmentMetadata(
            fid=1,
            aid=2,
            name="z.pdf",
            description="new",
        )
        tab._attachments_model.set_attachments(
            [first_attachment, second_attachment]
        )
        source_index = tab._attachments_model.index_for_attachment_id(2)
        proxy_index = tab._attachments_proxy.mapFromSource(source_index)
        selection_model = tab.view.selectionModel()
        selection_model.select(
            proxy_index,
            selection_model.SelectionFlag.ClearAndSelect,
        )
        tab.view.setCurrentIndex(proxy_index)

        try:
            tab._attachments_model.refresh_attachments(
                [first_attachment, updated_second_attachment]
            )

            selected_indexes = selection_model.selectedIndexes()
            selected_attachments = [
                index.data(tab._attachments_model.Roles.ATTACHMENT)
                for index in selected_indexes
            ]

            assert len(selected_attachments) == 1
            assert selected_attachments[0].aid == 2
            assert selected_attachments[0].description == "new"
            assert (
                tab.view.currentIndex()
                .data(tab._attachments_model.Roles.ATTACHMENT)
                .aid
                == 2
            )
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_download_task_finish_opens_pending_attachment(
        self,
        qgis_app: QgsApplication,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        del qgis_app

        _plugin, previous_plugin = _install_plugin_mock()
        attachment_path = tmp_path / "report.pdf"
        attachment = AttachmentMetadata(
            fid=1,
            aid=1,
            name="report.pdf",
            mime_type="application/pdf",
            file_path=attachment_path,
        )
        task = AttachmentDownloadTask(
            AttachmentDownloadContext(
                connection_id="connection",
                connection_url="https://example.test",
                connection_domain_uuid="domain",
                resource_id=1,
                feature_ngw_fid=1,
                attachment=attachment,
                attachment_path=attachment_path,
            )
        )
        tab = AttachmentsTab()
        tab._attachments_model.set_attachments([attachment])
        tab._attachments_model.set_attachment_loading_progress(1, 50.0)
        tab._attachment_download_tasks = {1: task}
        tab._pending_open_attachment_ids = {1}
        tab._open_attachment_path = Mock()
        attachment_path.write_bytes(b"PDF")
        monkeypatch.setattr(AttachmentsTab, "sender", lambda self: task)
        monkeypatch.setattr(
            task,
            "status",
            lambda: QgsTask.TaskStatus.Complete,
        )

        try:
            tab._on_attachment_download_task_finished()

            tab._open_attachment_path.assert_called_once_with(attachment_path)
            assert tab._pending_open_attachment_ids == set()
        finally:
            tab.close()
            tab.deleteLater()
            _restore_plugin_mock(previous_plugin)

    def test_edit_mode_update_enables_attribute_form_editing(
        self, qgis_app: QgsApplication
    ) -> None:
        del qgis_app

        widget = _edit_mode_widget_mock()

        _update_edit_mode(widget, True)

        widget.edit_button.setChecked.assert_called_once_with(True)
        widget._attachments_tab.close_editor.assert_not_called()
        widget._description_tab.set_read_only.assert_called_once_with(False)
        widget._form.setMode.assert_called_once_with(
            QgsAttributeEditorContext.Mode.SingleEditMode
        )

    def test_edit_mode_update_closes_attachment_editor_on_stop(
        self, qgis_app: QgsApplication
    ) -> None:
        del qgis_app

        widget = _edit_mode_widget_mock()

        _update_edit_mode(widget, False)

        widget.edit_button.setChecked.assert_called_once_with(False)
        widget._attachments_tab.close_editor.assert_called_once_with()
        widget._description_tab.set_read_only.assert_called_once_with(True)
        widget._form.setMode.assert_called_once_with(
            QgsAttributeEditorContext.Mode.IdentifyMode
        )

    def test_refresh_current_feature_after_sync_reloads_tabs(
        self,
        qgis_app: QgsApplication,
    ) -> None:
        del qgis_app

        widget = _FeatureRefreshHarness(current_index=3)

        method_name = (
            "_IdentificationResultsWidget__refresh_current_feature_after_sync"
        )
        getattr(IdentificationResultsWidget, method_name)(widget)

        refresh_callback = (
            widget._IdentificationResultsWidget__on_feature_changed
        )
        refresh_callback.assert_called_once_with(3)

    def test_state_change_refreshes_feature_for_local_and_synced_states(
        self,
        qgis_app: QgsApplication,
        monkeypatch,
    ) -> None:
        del qgis_app

        widget = Mock()
        refresh_callback = Mock()
        refresh_method_name = (
            "_IdentificationResultsWidget__refresh_current_feature_after_sync"
        )
        setattr(widget, refresh_method_name, refresh_callback)
        monkeypatch.setattr(
            identification_results_widget_module.QTimer,
            "singleShot",
            lambda _delay, callback: callback(),
        )

        method_name = "_IdentificationResultsWidget__on_state_changed"
        on_state_changed = getattr(IdentificationResultsWidget, method_name)

        on_state_changed(widget, DetachedLayerState.NotSynchronized)
        on_state_changed(widget, DetachedLayerState.Synchronized)
        on_state_changed(widget, DetachedLayerState.Synchronization)

        assert refresh_callback.call_count == 2

    def test_feature_data_tabs_can_be_disabled_temporarily(
        self, qgis_app: QgsApplication
    ) -> None:
        del qgis_app

        settings = IdentificationSettings()
        settings.last_used_tab = IdentificationTab.ATTACHMENTS

        widget = _IdentificationWidgetHarness(settings.last_used_tab)
        try:
            widget.set_feature_data_tabs_enabled(False)

            assert widget.tab_widget.currentIndex() == (
                IdentificationTab.ATTRIBUTES
            )
            assert not widget.tab_widget.isTabEnabled(
                IdentificationTab.ATTACHMENTS
            )
            assert not widget.tab_widget.isTabEnabled(
                IdentificationTab.DESCRIPTION
            )
            assert settings.last_used_tab == IdentificationTab.ATTACHMENTS
            assert widget.overlay_update_count == 1

            widget.set_feature_data_tabs_enabled(True)

            assert widget.tab_widget.currentIndex() == (
                IdentificationTab.ATTACHMENTS
            )
            assert widget.tab_widget.isTabEnabled(
                IdentificationTab.ATTACHMENTS
            )
            assert widget.tab_widget.isTabEnabled(
                IdentificationTab.DESCRIPTION
            )
        finally:
            widget.close()
