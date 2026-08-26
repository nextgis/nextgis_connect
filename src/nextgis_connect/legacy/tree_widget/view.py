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

from typing import TYPE_CHECKING, Dict, Optional, cast

from qgis.gui import QgsNewNameDialog
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QKeyEvent, QWheelEvent
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHeaderView,
    QSizePolicy,
    QTreeView,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem
from nextgis_connect.legacy.tree_widget.model import QNGWResourceTreeModel
from nextgis_connect.legacy.tree_widget.overlay import (
    OverlayAction,
    OverlayButtonState,
    OverlayHostWidget,
    OverlayKind,
    PluginOverlayController,
    PluginOverlayStateModel,
)
from nextgis_connect.platform.qgis.utils import SupportStatus

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    assert isinstance(iface, QgisInterface)

__all__ = ["QNGWResourceTreeView"]


class QNGWResourceTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(QModelIndex)
    overlay_action_requested = pyqtSignal(object)
    overlay_visibility_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent)

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.setIndentation(14)

        header = self.header()
        assert header is not None
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self._jobs: Dict[str, str] = {}
        self._job_actions: Dict[str, OverlayButtonState] = {}
        self._job_compact_titles: Dict[str, str] = {}
        self._manual_loading_title = ""
        self._manual_loading_compact_title = ""
        self._manual_loading_message = ""
        self._manual_loading_details: Optional[str] = None
        self._manual_loading_action = OverlayButtonState()
        self._manual_loading_draw_background = False
        self._loading_cancel_pending = False
        self._loading_cancel_message = ""
        self._is_loading = False
        self._is_overlay_visible = False

        self._overlay_host = OverlayHostWidget(self)
        self._sync_overlay_geometry()
        self.setMinimumHeight(self._overlay_host.minimum_overlay_height())
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().installEventFilter(self)
        self.horizontalScrollBar().installEventFilter(self)

        self._overlay_state_model = PluginOverlayStateModel(self)
        self._overlay_controller = PluginOverlayController(
            self._overlay_state_model,
            self._overlay_host,
            self,
        )
        self._overlay_controller.action_requested.connect(
            self.overlay_action_requested.emit
        )
        self._overlay_controller.state_changed.connect(
            self._handle_overlay_state_changed
        )
        self._overlay_state_model.update(has_connections=True)
        self.expanded.connect(self.__retry_failed_fetch)

    def setModel(self, model: Optional[QAbstractItemModel]) -> None:
        model = cast(QSortFilterProxyModel, model)
        self._source_model = cast(QNGWResourceTreeModel, model.sourceModel())
        self._proxy_model = model
        self._proxy_model.rowsInserted.connect(self.__insertRowsProcess)
        self._proxy_model.layoutChanged.connect(self.__expand_filtered)
        self._source_model.fetchErrorReadyForRetry.connect(
            self.__collapse_failed_fetch
        )

        super().setModel(self._proxy_model)

    def __insertRowsProcess(self, parent: QModelIndex):
        if not parent.isValid():
            self.expandToDepth(0)
            return

    def __expand_filtered(self) -> None:
        for resource_id in self._proxy_model.expanded_resources:  # type: ignore
            index = self._source_model.index_from_id(resource_id)
            self.expand(self._proxy_model.mapFromSource(index))

    def __retry_failed_fetch(self, index: QModelIndex) -> None:
        source_index = self._proxy_model.mapToSource(index)
        had_fetch_error = self._source_model.clear_fetch_error(source_index)
        if not had_fetch_error and not self._source_model.canFetchMore(
            source_index
        ):
            return

        if self._source_model.canFetchMore(source_index):
            self._source_model.fetchMore(source_index)

    def __collapse_failed_fetch(self, source_index: QModelIndex) -> None:
        proxy_index = self._proxy_model.mapFromSource(source_index)
        if proxy_index.isValid():
            self.collapse(proxy_index)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_overlay_geometry()

    def eventFilter(self, watched, event):
        if watched in (
            self.viewport(),
            self.verticalScrollBar(),
            self.horizontalScrollBar(),
        ) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            self._sync_overlay_geometry()
            QTimer.singleShot(0, self._sync_overlay_geometry)

        return super().eventFilter(watched, event)

    def mouseDoubleClickEvent(self, e):
        index = self.indexAt(e.pos())
        if index.isValid():
            self.itemDoubleClicked.emit(index)

        super().mouseDoubleClickEvent(e)

    def create_web_gis_url(self) -> str:
        return self._overlay_controller.resolver.create_web_gis_url()

    def is_overlay_visible(self) -> bool:
        return self._is_overlay_visible

    def _sync_overlay_geometry(self) -> None:
        viewport_geometry = self.viewport().geometry()
        if self._overlay_host.geometry() != viewport_geometry:
            self._overlay_host.setGeometry(viewport_geometry)

        self._overlay_host.raise_()

    def set_has_connections(self, value: bool) -> None:
        self._overlay_state_model.update(has_connections=value)

    def set_migration_required(self, value: bool) -> None:
        self._overlay_state_model.update(has_pending_migration=value)

    def set_auth_required(self, value: bool) -> None:
        self._overlay_state_model.update(has_auth_error=value)

    def set_search_empty(self, value: bool) -> None:
        self._overlay_state_model.update(search_empty=value)

    def set_search_connection_target(
        self,
        *,
        exists: bool,
        url: str,
        name: str = "",
    ) -> None:
        self._overlay_state_model.update(
            has_search_connection_target=True,
            search_connection_url=url,
            search_connection_name=name,
            search_connection_exists=exists,
            search_empty=False,
        )

    def clear_search_connection_target(self) -> None:
        self._overlay_state_model.update(
            has_search_connection_target=False,
            search_connection_url="",
            search_connection_name="",
            search_connection_exists=False,
        )

    def clear_availability_state(self) -> None:
        self._overlay_state_model.update(
            is_available=True,
            unavailable_title="",
            unavailable_compact_title="",
            unavailable_message="",
            unavailable_details=None,
            unavailable_icon="",
            unavailable_action=OverlayButtonState(),
        )

    def clear_plugin_update_state(self) -> None:
        self._overlay_state_model.update(
            has_plugin_update=False,
            plugin_update_title="",
            plugin_update_message="",
            plugin_update_details=None,
            plugin_update_icon="",
            plugin_update_action=OverlayButtonState(),
            plugin_update_footer_action=OverlayButtonState(),
        )

    def set_plugin_update_state(
        self,
        installed_version: str,
        available_version: str,
    ) -> None:
        self._overlay_state_model.update(
            has_plugin_update=True,
            plugin_update_title=self.tr("Update is available"),
            plugin_update_message=self.tr(
                "A newer version of NextGIS Connect is available."
            ),
            plugin_update_details=self.tr(
                "Current version: {installed_version}\nAvailable version: {available_version}"
            ).format(
                installed_version=installed_version,
                available_version=available_version,
            ),
            plugin_update_icon="update",
            plugin_update_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text=self.tr("Update plugin"),
            ),
            plugin_update_footer_action=OverlayButtonState(
                action=OverlayAction.SKIP_PLUGIN_UPDATE,
                text=self.tr("Skip this time"),
                text_opacity=0.5,
            ),
        )

    def set_unavailable_state(
        self,
        status: SupportStatus,
        ngc_version: str,
        ngw_version: str,
    ) -> None:
        if status == SupportStatus.OLD_CONNECT:
            message = self.tr(
                "This version of NextGIS Web requires a newer version of NextGIS Connect."
            )
            action = OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text=self.tr("Update plugin"),
            )
            icon_name = "update"
            title = self.tr("Plugin update required")
            compact_title = self.tr("Update required")
        else:
            message = self.tr("Ask the administrator to update NextGIS Web.")
            action = OverlayButtonState()
            icon_name = "update"
            title = self.tr("Server update required")
            compact_title = self.tr("Update required")

        details = self.tr(
            "NextGIS Connect: {ngc_version}\nNextGIS Web: {ngw_version}"
        ).format(
            ngc_version=ngc_version,
            ngw_version=ngw_version,
        )
        self._overlay_state_model.update(
            is_available=False,
            unavailable_title=title,
            unavailable_compact_title=compact_title,
            unavailable_message=message,
            unavailable_details=details,
            unavailable_icon=icon_name,
            unavailable_action=action,
        )

    def clear_error_state(self) -> None:
        self._overlay_state_model.update(
            has_error=False,
            error_title="",
            error_message="",
            error_details=None,
            error_icon="",
            error_action=OverlayButtonState(),
            error_secondary_action=OverlayButtonState(),
        )

    def set_error_state(
        self,
        message: str,
        *,
        title: Optional[str] = None,
        details: Optional[str] = None,
        retry_enabled: bool = True,
        icon_name: str = "",
        action: Optional[OverlayButtonState] = None,
        secondary_action: Optional[OverlayButtonState] = None,
    ) -> None:
        overlay_action = OverlayButtonState()
        if action is not None:
            overlay_action = action
        elif retry_enabled:
            overlay_action = OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text=self.tr("Retry"),
            )

        self._overlay_state_model.update(
            has_error=True,
            error_title=title or self.tr("Unable to load resources"),
            error_message=message,
            error_details=details,
            error_icon=icon_name,
            error_action=overlay_action,
            error_secondary_action=secondary_action or OverlayButtonState(),
        )

    def addBlockedJob(
        self,
        job_name,
        cancel_action: Optional[OverlayButtonState] = None,
        compact_title: str = "",
    ):
        self._jobs[job_name] = ""
        self._job_compact_titles[job_name] = compact_title or job_name
        self._job_actions[job_name] = (
            OverlayButtonState() if cancel_action is None else cancel_action
        )
        self._clear_loading_cancel_pending()
        self._sync_loading_state()

    def addJobStatus(self, job_name, status):
        if job_name in self._jobs:
            self._jobs[job_name] = status
            self._sync_loading_state()

    def removeBlockedJob(self, job_name, check_overlay=True):
        if job_name in self._jobs:
            self._jobs.pop(job_name)
            self._job_actions.pop(job_name, None)
            self._job_compact_titles.pop(job_name, None)
            self._clear_loading_cancel_pending()

        if check_overlay:
            self._sync_loading_state()

    def check_overlay(self):
        self._sync_loading_state()

    def begin_loading(
        self,
        title: str,
        *,
        compact_title: str = "",
        message: str = "",
        details: Optional[str] = None,
        cancel_action: Optional[OverlayButtonState] = None,
        draw_background: bool = False,
    ) -> None:
        self._manual_loading_title = title
        self._manual_loading_compact_title = compact_title
        self._manual_loading_message = message
        self._manual_loading_details = details
        self._manual_loading_draw_background = draw_background
        self._manual_loading_action = (
            OverlayButtonState() if cancel_action is None else cancel_action
        )
        self._clear_loading_cancel_pending()
        self._sync_loading_state()

    def end_loading(self) -> None:
        self._manual_loading_title = ""
        self._manual_loading_compact_title = ""
        self._manual_loading_message = ""
        self._manual_loading_details = None
        self._manual_loading_action = OverlayButtonState()
        self._manual_loading_draw_background = False
        self._clear_loading_cancel_pending()
        self._sync_loading_state()

    def set_loading_cancel_pending(
        self,
        message: str,
        *,
        pending: bool = True,
    ) -> None:
        self._loading_cancel_pending = pending
        self._loading_cancel_message = message if pending else ""
        self._sync_loading_state()

    def _sync_loading_state(self) -> None:
        if self._manual_loading_title != "":
            loading_message = self._manual_loading_message
            if self._loading_cancel_pending:
                loading_message = self._loading_cancel_message

            self._overlay_state_model.update(
                is_loading=True,
                loading_title=self._manual_loading_title,
                loading_compact_title=self._manual_loading_compact_title,
                loading_message=loading_message,
                loading_details=self._manual_loading_details,
                loading_action=self._manual_loading_action,
                loading_draw_background=self._manual_loading_draw_background,
                loading_cancel_pending=self._loading_cancel_pending,
            )
            return

        if len(self._jobs) > 0:
            job_name, job_status = list(self._jobs.items())[-1]
            details = job_status.strip() or None
            loading_message = self.tr(
                "Please wait while the current operation finishes."
            )
            if self._loading_cancel_pending:
                loading_message = self._loading_cancel_message

            self._overlay_state_model.update(
                is_loading=True,
                loading_title=job_name,
                loading_compact_title=self._job_compact_titles.get(
                    job_name,
                    job_name,
                ),
                loading_message=loading_message,
                loading_details=details,
                loading_action=self._job_actions.get(
                    job_name,
                    OverlayButtonState(),
                ),
                loading_draw_background=False,
                loading_cancel_pending=self._loading_cancel_pending,
            )
            return

        self._overlay_state_model.update(
            is_loading=False,
            loading_title="",
            loading_compact_title="",
            loading_message="",
            loading_details=None,
            loading_action=OverlayButtonState(),
            loading_draw_background=True,
            loading_cancel_pending=False,
        )

    def _clear_loading_cancel_pending(self) -> None:
        self._loading_cancel_pending = False
        self._loading_cancel_message = ""

    def _handle_overlay_state_changed(self, state) -> None:
        is_loading = state.kind == OverlayKind.LOADING
        if is_loading != self._is_loading:
            self._is_loading = is_loading
            self.verticalScrollBar().setEnabled(not is_loading)
            self.horizontalScrollBar().setEnabled(not is_loading)

        is_visible = state.kind != OverlayKind.NONE
        if is_visible == self._is_overlay_visible:
            return

        self._is_overlay_visible = is_visible
        self.overlay_visibility_changed.emit(is_visible)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._is_loading:
            event.accept()
            return

        super().wheelEvent(event)

    def keyPressEvent(self, event: Optional[QKeyEvent]) -> None:
        is_f2 = event.key() == Qt.Key.Key_F2
        index = self.currentIndex()
        if is_f2 and index.isValid():
            self.rename_resource(index)
        else:
            super().keyPressEvent(event)

    def rename_resource(self, index: QModelIndex):
        # Get current resource name. This name can differ from display
        # text of tree item (see style resources).

        index = self._proxy_model.mapToSource(index)

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        current_name = ngw_resource.display_name

        # Get existing names
        existing_names = []
        parent = index.parent()
        if parent.isValid():
            model = self._source_model
            assert model is not None
            for i in range(model.rowCount(parent)):
                if i == index.row():
                    continue

                sibling_index = model.index(i, 0, parent)
                sibling_resource = sibling_index.data(
                    QNGWResourceItem.NGWResourceRole
                )
                existing_names.append(sibling_resource.display_name)

        dialog = QgsNewNameDialog(
            initial=current_name,
            existing=existing_names,
            cs=Qt.CaseSensitivity.CaseSensitive,
            parent=iface.mainWindow(),
        )
        dialog.setWindowTitle(self.tr("Change resource name"))
        dialog.setOverwriteEnabled(False)
        dialog.setAllowEmptyName(False)
        dialog.setHintString(self.tr("Enter new name for selected resource"))
        dialog.setConflictingNameWarning(self.tr("Resource already exists"))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = dialog.name()

        if new_name == current_name:
            return

        self.__rename_resource_resp = self._source_model.renameResource(
            index, new_name
        )
        self.__rename_resource_resp.done.connect(  # type: ignore
            lambda index: self.setCurrentIndex(
                self._proxy_model.mapFromSource(index)
            )
        )
