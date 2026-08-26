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

import html
import importlib.util
import json
import os
import tempfile
import urllib.parse
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, cast

from qgis import utils as qgis_utils
from qgis.core import (
    Qgis,
    QgsFileUtils,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsLayerTreeRegistryBridge,
    QgsMapLayer,
    QgsNetworkAccessManager,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsDockWidget, QgsNewNameDialog
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QDir,
    QEventLoop,
    QFile,
    QFileInfo,
    QIODevice,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QTemporaryFile,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QAction,
    QActionGroup,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
)
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect.features.resource_browser.domain import (
    LayerKind,
    ResourceImportExtent,
    ResourceImportMode,
    ResourceImportRequest,
    ResourceImportSource,
    ResourceImportStyle,
    ResourceKind,
    ResourceMenuAction,
    ResourceMenuContext,
    ResourceMenuItem,
    ResourceMenuItemAdapter,
    ResourceTypeBinding,
)
from nextgis_connect.features.resource_browser.infrastructure import (
    DemoProjectSelectionResolver,
    QgisLayerImportTarget,
    QgisMapCanvasExtentApplicator,
    QgisResourceBatchImporter,
    QgisResourceLayerImporter,
)
from nextgis_connect.features.resource_browser.presentation import (
    QgisResourceImportInteraction,
    ResourceContextMenuController,
    ResourceTreeBranchController,
)
from nextgis_connect.legacy.detached_editing.container.cache_lifecycle import (
    CachedDetachedContainerLifecycle,
)
from nextgis_connect.legacy.detached_editing.container.container_factory import (
    DetachedContainerFactory,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    detached_layer_uri,
)
from nextgis_connect.legacy.detached_editing.utils import (
    is_ngw_container as is_detached_ngw_container,
)
from nextgis_connect.legacy.dialog_choose_style import (
    NGWLayerStyleChooserDialog,
)
from nextgis_connect.legacy.dialog_metadata import MetadataDialog
from nextgis_connect.legacy.exceptions_list_dialog import (
    ExceptionsListDialog,
)
from nextgis_connect.legacy.ngw.core import (
    NGWBaseMap,
    NGWError,
    NGWGroupResource,
    NGWMapServerStyle,
    NGWOgcfService,
    NGWPostgisLayer,
    NGWQGISRasterStyle,
    NGWQGISStyle,
    NGWQGISVectorStyle,
    NGWRasterLayer,
    NGWRasterStyle,
    NGWResource,
    NGWTileset,
    NGWTmsConnection,
    NGWTmsLayer,
    NGWVectorLayer,
    NGWWebMap,
    NGWWfsLayer,
    NGWWfsService,
    NGWWmsConnection,
    NGWWmsLayer,
    NGWWmsService,
)
from nextgis_connect.legacy.ngw.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from nextgis_connect.legacy.ngw.core.ngw_webmap import (
    NGWWebMapGroup,
    NGWWebMapLayer,
)
from nextgis_connect.legacy.ngw.qgis.ngw_resource_model_4qgis import (
    QGISResourceJob,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    NgwServerFeature,
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job import (
    UploadedLayerResource,
)
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job_error import (
    JobError,
    JobNGWError,
    JobServerRequestError,
    JobWarning,
)
from nextgis_connect.legacy.ngw.resources.creation.vector_layer_creation_dialog import (
    VectorLayerCreationDialog,
)
from nextgis_connect.legacy.ngw_connection.application.connection_switcher import (
    NgwConnectionSwitcher,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_edit_dialog import (
    NgwConnectionEditDialog,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_switch_menu import (
    ConnectionSwitchMenu,
)
from nextgis_connect.legacy.ngw_connection.presentation.diagnostics.dialog import (
    NgwConnectionDiagnosticsDialog,
)
from nextgis_connect.legacy.plugin_update import (
    PluginUpdate,
    PluginUpdateCheckResult,
    PluginUpdateCheckTask,
)
from nextgis_connect.legacy.resource_properties.resource_properties_dialog import (
    ResourcePropertiesDialog,
)
from nextgis_connect.legacy.search.connection_url import (
    SearchConnectionTarget,
    SearchConnectionTargetResolver,
)
from nextgis_connect.legacy.search.resource_url import SearchResourceUrlParser
from nextgis_connect.legacy.search.search_panel import SearchPanel
from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.legacy.search.utils import SearchType
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.legacy.shell.presentation.dock.resource_delete_confirmation_dialog import (
    ResourceDeleteConfirmationDialog,
)
from nextgis_connect.legacy.tree_widget import (
    QNGWResourceItem,
    QNGWResourceTreeModel,
    QNGWResourceTreeView,
)
from nextgis_connect.legacy.tree_widget.model import NGWResourceModelResponse
from nextgis_connect.legacy.tree_widget.overlay import (
    OverlayAction,
    OverlayButtonState,
)
from nextgis_connect.legacy.tree_widget.proxy_model import NgConnectProxyModel
from nextgis_connect.platform.clipboard import Clipboard
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis import utils
from nextgis_connect.platform.qgis.compat import (
    QGIS_3_30,
    GeometryType,
    is_mvt_supported,
    parse_version,
)
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgwError,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.constants import PACKAGE_NAME, PLUGIN_NAME
from nextgis_connect.shell.presentation.plugin_panel import (
    PluginPanelToolBar,
    PluginPanelToolBarActions,
)
from nextgis_connect.ui_kit.buttons.shining import ShiningButton
from nextgis_connect.ui_kit.icons import (
    icon_to_base64,
    material_icon,
    plugin_icon,
    plugin_icon_file_path,
    qgis_icon,
)

HAS_NGSTD = importlib.util.find_spec("ngstd") is not None
if HAS_NGSTD:
    from ngstd.core import NGRequest  # type: ignore
    from ngstd.framework import NGAccess  # type: ignore


this_dir = os.path.dirname(__file__)
FORM_CLASS, _ = uic.loadUiType(
    os.path.join(this_dir, "ng_connect_dock_base.ui")
)

ROOT_RESOURCES_LOADER_JOB_ID = "NGWRootResourcesLoader"


@dataclass
class AddLayersCommand:
    job_uuid: str
    insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint
    ngw_indexes: List[QModelIndex]
    allow_demo_project_resolve: bool = True


@dataclass(frozen=True)
class PendingResourceImport:
    job_uuid: str
    resource_id: int
    action_id: ResourceMenuAction
    target: QgisLayerImportTarget


@dataclass(frozen=True)
class DirectResourceImportConfiguration:
    linked_resource: NGWResource
    render_resource_id: Optional[int] = None
    render_resource_ids: Tuple[int, ...] = ()
    styles: Tuple[ResourceImportStyle, ...] = ()
    default_style_name: Optional[str] = None
    source_extent: Optional[ResourceImportExtent] = None


class NgConnectDock(QgsDockWidget, FORM_CLASS):
    iface: QgisInterface
    resource_model: QNGWResourceTreeModel
    resources_tree_view: QNGWResourceTreeView

    def __init__(self, iface: QgisInterface):
        super().__init__(parent=None)

        self.setupUi(self)
        self.setObjectName("NGConnectDock")
        self.setWindowIcon(plugin_icon("branding/connect_logo.svg"))

        self.__init_title()

        self.iface = iface

        self._first_gui_block_on_refresh = False
        self.__cancelable_job_ids: List[str] = []
        self.__active_resource_importer: Optional[
            QgisResourceBatchImporter
        ] = None
        self.__cancel_pending_job_id: Optional[str] = None
        self.__canceled_job_ids: Set[str] = set()
        self.__root_loading_cancel_requested = False
        self.__root_children_loading_parent_id: Optional[int] = None
        self.__is_tree_overlay_visible = False
        self.__promo_banner_container: Optional[QFrame] = None
        self.__search_menu = None
        self.__connection_switch_menu: Optional[ConnectionSwitchMenu] = None
        self.__is_closed = False
        self.__is_project_export_action_registered = False
        self.__plugin_update_task: Optional[PluginUpdateCheckTask] = None
        self.__active_plugin_update: Optional[PluginUpdate] = None
        self.__skipped_plugin_update_ids: Set[str] = set()
        self.__search_connection_target_resolver = (
            SearchConnectionTargetResolver()
        )
        self.__search_resource_url_parser = SearchResourceUrlParser()
        self.__search_connection_target: Optional[SearchConnectionTarget] = (
            None
        )
        self.__pending_search_string = ""
        self.__resource_menu_controller = ResourceContextMenuController(self)
        self.__resource_menu_controller.action_requested.connect(
            self.__handle_resource_menu_action
        )
        self.__resource_layer_importer = QgisResourceLayerImporter(
            self,
            canvas_extent_applicator=QgisMapCanvasExtentApplicator(
                self.iface.mapCanvas()
            ),
        )
        self.__resource_layer_importer.layer_imported.connect(
            self.__on_resource_layer_imported
        )
        self.__resource_layer_importer.import_failed.connect(
            self.__on_resource_layer_import_failed
        )

        self.actionOpenInNGWFromLayer = QAction(
            self.tr("Open resource page"), self
        )
        self.actionOpenInNGWFromLayer.setIcon(
            plugin_icon("branding/ngw_logo.svg")
        )
        self.actionOpenInNGWFromLayer.triggered.connect(
            self.open_ngw_resource_page_from_layer
        )

        self.actionOpenLayerHistoryFromLayer = QAction(
            self.tr("Open layer history"), self
        )
        self.actionOpenLayerHistoryFromLayer.setIcon(
            qgis_icon("mIconHistory.svg")
        )
        self.actionOpenLayerHistoryFromLayer.triggered.connect(
            self.open_layer_history_from_layer
        )

        self.layer_menu_separator = QAction(self)
        self.layer_menu_separator.setSeparator(True)

        self.menuUpload = (
            self.__resource_menu_controller.create_add_to_web_gis_menu()
        )
        self.menuUpload.setTitle(self.tr("Add to Web GIS"))
        self.menuUpload.setIcon(plugin_icon("actions/cloud_upload.svg"))
        self.menuUpload.menuAction().setIconVisibleInMenu(False)

        self.actionUploadProjectViaImportExportMenu = QAction(
            plugin_icon("branding/nextgis_logo.svg"),
            self.tr("Upload project to NextGIS Web"),
            self,
        )
        self.actionUploadProjectViaImportExportMenu.triggered.connect(
            self.upload_project_resources
        )
        self.actionUploadProjectViaImportExportMenu.setEnabled(False)

        utils.add_project_export_action(
            self.actionUploadProjectViaImportExportMenu
        )
        self.__is_project_export_action_registered = True

        self.actionOpenInBrowser = QAction(
            plugin_icon("actions/open_map.svg"),
            self.tr("View in browser"),
            self,
        )
        self.actionOpenInBrowser.triggered.connect(self.__open_in_web)

        self.actionRefresh = QAction(
            plugin_icon("actions/refresh.svg"),
            self.tr("Refresh"),
            self,
        )
        self.actionRefresh.triggered.connect(self.__action_refresh_tree)

        self.actionSettings = QAction(
            plugin_icon("actions/settings.svg"),
            self.tr("Settings"),
            self,
        )
        self.actionSettings.triggered.connect(self.action_settings)

        self.actionHelp = QAction(
            plugin_icon("actions/help.svg"),
            self.tr("Help"),
            self,
        )
        self.actionHelp.triggered.connect(utils.open_plugin_help)

        connections_manager = NgwConnectionsManager()
        current_connection_id = connections_manager.current_connection_id

        self.search_panel = SearchPanel(current_connection_id, self)
        NgConnectInterface.instance().settings_changed.connect(
            self.search_panel.on_settings_changed
        )
        NgConnectInterface.instance().settings_changed.connect(
            self.checkImportActionsAvailability
        )
        self.content.layout().addWidget(self.search_panel)
        self.search_panel.search_requested.connect(self.__on_search_requested)
        self.search_panel.reset_requested.connect(self.__on_search_reset)
        self.search_panel.hide()

        self.menuDownload = (
            self.__resource_menu_controller.create_resource_import_menu()
        )
        self.menuDownload.setTitle(self.tr("Add to QGIS"))
        self.menuDownload.setIcon(plugin_icon("actions/cloud_download.svg"))

        self.download_action = QAction(
            self.menuDownload.icon(),
            self.menuDownload.title(),
            self,
        )
        self.download_action.setToolTip(self.menuDownload.title())
        self.download_action.triggered.connect(self.__trigger_default_import)
        self.__set_resource_import_menu_visible(False)

        self.upload_action = QAction(
            self.menuUpload.icon(),
            self.menuUpload.title(),
            self,
        )
        self.upload_action.setToolTip(self.menuUpload.title())
        self.upload_action.setMenu(self.menuUpload)

        self.actionIdentify = NgConnectInterface.instance().detached_editing.identification_action

        self.__create_resource_creation_action()
        self.__create_search_action()

        toolbar_actions = PluginPanelToolBarActions(
            add_to_qgis=self.download_action,
            add_to_web_gis=self.upload_action,
            identify=self.actionIdentify,
            create_resource=self.creation_action,
            search=self.search_action,
            refresh=self.actionRefresh,
            open_in_browser=self.actionOpenInBrowser,
            settings=self.actionSettings,
            help=self.actionHelp,
        )
        self.main_tool_bar = PluginPanelToolBar(
            toolbar_actions,
            self.content,
        )
        self.main_tool_bar.settings_middle_clicked.connect(
            self.__show_connection_switch_menu
        )
        self.content.layout().insertWidget(0, self.main_tool_bar)

        self.resource_model = QNGWResourceTreeModel(self)
        self.resource_model.errorOccurred.connect(self.__model_error_process)
        self.resource_model.warningOccurred.connect(
            self.__model_warning_process
        )
        self.resource_model.jobStarted.connect(self.__modelJobStarted)
        self.resource_model.jobStatusChanged.connect(
            self.__modelJobStatusChanged
        )
        self.resource_model.jobFinished.connect(self.__modelJobFinished)
        self.resource_model.indexesLocked.connect(self.__onModelBlockIndexes)
        self.resource_model.indexesUnlocked.connect(
            self.__onModelReleaseIndexes
        )
        self.resource_model.connection_id_changed.connect(
            self.search_panel.set_connection_id
        )

        self._queue_to_add: List[AddLayersCommand] = []
        self.__pending_resource_imports: List[PendingResourceImport] = []

        self.blocked_jobs = {
            "NGWGroupCreater": self.tr("Creating resource..."),
            "NGWResourceDelete": self.tr("Deleting resource..."),
            "NGWResourceBatchDelete": self.tr("Deleting resources..."),
            "QGISResourcesUploader": self.tr("Uploading layer..."),
            "QGISProjectUploader": self.tr("Uploading project..."),
            "NGWCreateWfsService": self.tr("Creating WFS service..."),
            "NGWCreateOgcfService": self.tr(
                "Creating OGC API Features service..."
            ),
            "NGWCreateWMSForVector": self.tr("Creating WMS service..."),
            "NGWCreateMapForStyle": self.tr("Creating Web map..."),
            "MapForLayerCreater": self.tr("Creating Web map..."),
            "QGISStyleUpdater": self.tr("Creating style for a layer..."),
            "QGISStyleAdder": self.tr("Creating style for a layer..."),
            "NGWRenameResource": self.tr("Renaming resource..."),
            "NGWUpdateVectorLayer": self.tr("Updating resource..."),
            "NGWUpdateRasterLayer": self.tr("Updating resource..."),
            "NGWMissingResourceUpdater": self.tr("Downloading resources..."),
            "NgwCreateVectorLayersStubs": self.tr(
                "Processing vector layers..."
            ),
            "ResourcesDownloader": self.tr("Downloading linked resources..."),
            "NgwStylesDownloader": self.tr("Downloading styles..."),
            "AddLayersStub": self.tr("Adding resources to QGIS..."),
            "NgwSearch": self.tr("Searching resources..."),
        }
        self.blocked_job_compact_titles = {
            "NGWGroupCreater": self.tr("Creating..."),
            "NGWResourceDelete": self.tr("Deleting..."),
            "NGWResourceBatchDelete": self.tr("Deleting..."),
            "QGISResourcesUploader": self.tr("Uploading..."),
            "QGISProjectUploader": self.tr("Uploading..."),
            "NGWCreateWfsService": self.tr("Creating..."),
            "NGWCreateOgcfService": self.tr("Creating..."),
            "NGWCreateWMSForVector": self.tr("Creating..."),
            "NGWCreateMapForStyle": self.tr("Creating..."),
            "MapForLayerCreater": self.tr("Creating..."),
            "QGISStyleUpdater": self.tr("Creating..."),
            "QGISStyleAdder": self.tr("Creating..."),
            "NGWRenameResource": self.tr("Renaming..."),
            "NGWUpdateVectorLayer": self.tr("Updating..."),
            "NGWUpdateRasterLayer": self.tr("Updating..."),
            "NGWMissingResourceUpdater": self.tr("Downloading..."),
            "NgwCreateVectorLayersStubs": self.tr("Processing..."),
            "ResourcesDownloader": self.tr("Downloading..."),
            "NgwStylesDownloader": self.tr("Downloading..."),
            "AddLayersStub": self.tr("Adding..."),
            "NgwSearch": self.tr("Searching..."),
        }
        self._cancelable_blocked_jobs = {
            "QGISResourcesUploader",
            "QGISProjectUploader",
            "NGWUpdateVectorLayer",
            "NGWUpdateRasterLayer",
            "NGWMissingResourceUpdater",
            "ResourcesDownloader",
            "NgwCreateVectorLayersStubs",
            "NgwStylesDownloader",
            "NgwSearch",
        }

        # proxy model
        self.proxy_model = NgConnectProxyModel(self)
        self.proxy_model.setSourceModel(self.resource_model)
        self.resource_model.found_resources_changed.connect(
            self.proxy_model.set_resources_id
        )

        # ngw resources view
        self.resources_tree_view = QNGWResourceTreeView(self)
        self.resources_tree_view.setModel(self.proxy_model)
        self.__resource_tree_branch_controller = ResourceTreeBranchController(
            self.resources_tree_view
        )
        self.resource_model.found_resources_changed.connect(
            self.__set_search_empty
        )

        self.__resource_menu_item_adapter = (
            self.__create_resource_menu_item_adapter()
        )
        self.resources_tree_view.customContextMenuRequested.connect(
            self.__show_resource_context_menu
        )
        self.resources_tree_view.itemDoubleClicked.connect(
            self.trvDoubleClickProcess
        )
        self.resources_tree_view.overlay_action_requested.connect(
            self.__handle_tree_overlay_action
        )
        self.resources_tree_view.overlay_visibility_changed.connect(
            self.__handle_tree_overlay_visibility_changed
        )

        size_policy = self.resources_tree_view.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        self.resources_tree_view.setSizePolicy(size_policy)

        self.content.layout().addWidget(self.resources_tree_view)

        self.__create_web_gis_button = ShiningButton(
            self.tr("Create you own Web GIS!"),
            self.content,
        )
        self.__create_web_gis_button.clicked.connect(
            self.__open_create_web_gis_url
        )
        self.__create_web_gis_button.hide()
        self.content.layout().addWidget(self.__create_web_gis_button)

        self.__add_banner()

        self.jobs_count = 0
        self.try_check_https = False

        self.__initialization_timer = QTimer(self)
        self.__initialization_timer.setSingleShot(True)
        self.__initialization_timer.timeout.connect(
            self.__initialize_deferred_state
        )
        self.__initialization_timer.start(0)

        if HAS_NGSTD:
            self.__ngstd_connection = (
                NGAccess.instance().userInfoUpdated.connect(
                    self.__on_ngstd_user_info_updated
                )
            )

        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        layer_tree_view.selectionModel().selectionChanged.connect(
            self.checkImportActionsAvailability
        )

        selection_model = self.resources_tree_view.selectionModel()
        assert selection_model is not None
        selection_model.selectionChanged.connect(
            self.checkImportActionsAvailability
        )

        project = QgsProject.instance()
        assert project is not None
        project.layersRemoved.connect(self.checkImportActionsAvailability)

        self.__is_reinit_tree = False
        self.__reinit_tree_error = None

        self.checkImportActionsAvailability()

    def __initialize_deferred_state(self) -> None:
        if self.__is_closed:
            return

        self.reinit_tree(force=True)
        self.__start_plugin_update_check()

    def close(self) -> bool:
        if self.__is_closed:
            return super().close()

        self.__is_closed = True
        self.__unregister_project_export_action()
        self.__close_connection_switch_menu()
        self.__safe_disconnect(
            self.main_tool_bar.settings_middle_clicked,
            self.__show_connection_switch_menu,
        )
        self.__initialization_timer.stop()
        self.__safe_disconnect(
            self.__initialization_timer.timeout,
            self.__initialize_deferred_state,
        )

        self.__safe_disconnect(
            NgConnectInterface.instance().settings_changed,
            self.search_panel.on_settings_changed,
        )
        self.__safe_disconnect(
            NgConnectInterface.instance().settings_changed,
            self.checkImportActionsAvailability,
        )
        self.__safe_disconnect(
            self.search_panel.search_requested,
            self.__on_search_requested,
        )
        self.__safe_disconnect(
            self.search_panel.reset_requested,
            self.__on_search_reset,
        )

        self.__safe_disconnect(
            self.resources_tree_view.customContextMenuRequested,
            self.__show_resource_context_menu,
        )
        self.__safe_disconnect(
            self.__resource_menu_controller.action_requested,
            self.__handle_resource_menu_action,
        )
        self.__safe_disconnect(
            self.resources_tree_view.itemDoubleClicked,
            self.trvDoubleClickProcess,
        )
        self.__safe_disconnect(
            self.resources_tree_view.overlay_action_requested,
            self.__handle_tree_overlay_action,
        )
        self.__safe_disconnect(
            self.resources_tree_view.overlay_visibility_changed,
            self.__handle_tree_overlay_visibility_changed,
        )

        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        self.__safe_disconnect(
            layer_tree_view.selectionModel().selectionChanged,
            self.checkImportActionsAvailability,
        )

        selection_model = self.resources_tree_view.selectionModel()
        assert selection_model is not None
        self.__safe_disconnect(
            selection_model.selectionChanged,
            self.checkImportActionsAvailability,
        )

        project = QgsProject.instance()
        assert project is not None
        self.__safe_disconnect(
            project.layersRemoved,
            self.checkImportActionsAvailability,
        )

        if HAS_NGSTD and self.__ngstd_connection is not None:
            self.__safe_disconnect(
                NGAccess.instance().userInfoUpdated,
                self.__on_ngstd_user_info_updated,
            )
            self.__ngstd_connection = None

        if self.__plugin_update_task is not None:
            self.__safe_disconnect(
                self.__plugin_update_task.signals.finished,
                self.__on_plugin_update_check_finished,
            )
            self.__plugin_update_task.cancel()
            self.__plugin_update_task = None

        self.__safe_disconnect(
            self.resource_model.errorOccurred,
            self.__model_error_process,
        )
        self.__safe_disconnect(
            self.resource_model.warningOccurred,
            self.__model_warning_process,
        )
        self.__safe_disconnect(
            self.resource_model.jobStarted,
            self.__modelJobStarted,
        )
        self.__safe_disconnect(
            self.resource_model.jobStatusChanged,
            self.__modelJobStatusChanged,
        )
        self.__safe_disconnect(
            self.resource_model.jobFinished,
            self.__modelJobFinished,
        )
        self.__safe_disconnect(
            self.resource_model.indexesLocked,
            self.__onModelBlockIndexes,
        )
        self.__safe_disconnect(
            self.resource_model.indexesUnlocked,
            self.__onModelReleaseIndexes,
        )
        self.__safe_disconnect(
            self.resource_model.connection_id_changed,
            self.search_panel.set_connection_id,
        )
        self.__safe_disconnect(
            self.resource_model.found_resources_changed,
            self.proxy_model.set_resources_id,
        )
        self.__safe_disconnect(
            self.resource_model.found_resources_changed,
            self.__set_search_empty,
        )

        self.resource_model.shutdown_jobs()
        self.resources_tree_view.deleteLater()
        self.resource_model.deleteLater()

        return super().close()

    def __unregister_project_export_action(self) -> None:
        if not self.__is_project_export_action_registered:
            return

        if Qgis.versionInt() >= QGIS_3_30:
            self.iface.removeProjectExportAction(
                self.actionUploadProjectViaImportExportMenu
            )
        else:
            import_export_menu = utils.get_project_import_export_menu()
            if import_export_menu is not None:
                import_export_menu.removeAction(
                    self.actionUploadProjectViaImportExportMenu
                )

        self.__is_project_export_action_registered = False

    def __safe_disconnect(self, signal, slot) -> None:
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def __start_plugin_update_check(self) -> None:
        if self.__is_closed or self.__plugin_update_task is not None:
            return

        self.__plugin_update_task = PluginUpdateCheckTask()
        self.__plugin_update_task.signals.finished.connect(
            self.__on_plugin_update_check_finished
        )
        NgConnectInterface.instance().task_manager.addTask(
            self.__plugin_update_task
        )

    @pyqtSlot(object)
    def __on_plugin_update_check_finished(
        self, result: PluginUpdateCheckResult
    ) -> None:
        self.__plugin_update_task = None
        if self.__is_closed:
            return

        update = result.update
        if update is None:
            return

        if update.skip_id in self.__skipped_plugin_update_ids:
            return

        self.__active_plugin_update = update
        self.resources_tree_view.set_plugin_update_state(
            update.installed_version,
            update.available_version,
        )

    def __set_search_empty(self, resources) -> None:
        self.resources_tree_view.set_search_empty(-1 in resources)

    @pyqtSlot()
    def checkImportActionsAvailability(self):
        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

        # Search
        self.search_action.setEnabled(self.resource_model.is_connected)
        self.search_panel.setEnabled(self.resource_model.is_connected)

        if not self.resource_model.is_connected:
            self.__resource_menu_controller.set_resource_import_actions_enabled(
                False
            )
            self.__resource_menu_controller.set_add_to_web_gis_actions_enabled(
                False
            )
            self.__resource_menu_controller.set_resource_creation_actions_enabled(
                False
            )
            self.upload_action.setEnabled(False)
            self.creation_action.setEnabled(False)
            self.__set_resource_import_menu_visible(False)
            self.actionUploadProjectViaImportExportMenu.setEnabled(False)
            return

        # QGIS layers
        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        is_one_qgis_selected = len(qgis_nodes) == 1
        # is_multiple_qgis_selection = len(qgis_nodes) > 1
        is_one_qgis_layer_selected = is_one_qgis_selected and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )
        # is_group = (
        #     is_one_qgis_selected and QgsLayerTree.isGroup(qgis_nodes[0])
        # )

        # NGW resources
        selected_ngw_indexes = []
        ngw_resources: List[NGWResource] = []
        for proxy_index in self.resources_tree_view.selectedIndexes():
            source_index = self.proxy_model.mapToSource(proxy_index)
            if not source_index.isValid():
                continue

            ngw_resource = source_index.data(QNGWResourceItem.NGWResourceRole)
            if not isinstance(ngw_resource, NGWResource):
                continue

            selected_ngw_indexes.append(source_index)
            ngw_resources.append(ngw_resource)
        has_no_ngw_selection = len(selected_ngw_indexes) == 0
        is_multiple_ngw_selection = len(selected_ngw_indexes) > 1

        selected_qgis_layer = (
            cast(QgsLayerTreeLayer, qgis_nodes[0]).layer()
            if is_one_qgis_layer_selected
            else None
        )

        resource_menu_context = self.__create_resource_menu_context(
            selected_ngw_indexes
        )
        self.__resource_menu_controller.update_resource_import_actions(
            resource_menu_context
        )
        self.__resource_menu_controller.update_add_to_web_gis_actions(
            resource_menu_context
        )
        self.__resource_menu_controller.update_resource_creation_actions(
            resource_menu_context
        )
        self.upload_action.setEnabled(
            self.__resource_menu_controller.has_available_add_to_web_gis_actions()
        )
        self.actionUploadProjectViaImportExportMenu.setEnabled(
            self.__resource_menu_controller.is_add_to_web_gis_action_enabled(
                ResourceMenuAction.UPLOAD_PROJECT
            )
        )
        self.__set_resource_import_menu_visible(
            self.__resource_menu_controller.has_available_alternative_resource_import_actions()
        )
        self.download_action.setEnabled(
            self.__resource_menu_controller.has_available_resource_import_actions()
        )

        self.actionOpenInBrowser.setText(self.tr("View in browser"))
        self.actionOpenInBrowser.setEnabled(
            not is_multiple_ngw_selection
            and not has_no_ngw_selection
            and ngw_resources[0].is_preview_supported
        )

        self.creation_action.setEnabled(
            self.__resource_menu_controller.has_available_resource_creation_actions()
        )

        open_in_ngw_visible = (
            is_one_qgis_layer_selected
            and selected_qgis_layer is not None
            and selected_qgis_layer.customProperty("ngw_connection_id")
            is not None
            and selected_qgis_layer.customProperty("ngw_resource_id")
            is not None
        )
        self.actionOpenInNGWFromLayer.setVisible(open_in_ngw_visible)
        self.layer_menu_separator.setVisible(open_in_ngw_visible)

        self.actionOpenLayerHistoryFromLayer.setVisible(False)

        if open_in_ngw_visible:
            assert selected_qgis_layer is not None

            plugin = NgConnectInterface.instance()
            detached_layer = plugin.detached_editing.layer(selected_qgis_layer)

            if detached_layer is not None:
                self.actionOpenLayerHistoryFromLayer.setVisible(True)
                is_versioning_enabled = (
                    detached_layer.metadata.is_versioning_enabled
                )
                self.actionOpenLayerHistoryFromLayer.setEnabled(
                    is_versioning_enabled
                )

    @pyqtSlot()
    def __trigger_default_import(self) -> None:
        if self.download_action.menu() is not None:
            return

        action = self.__resource_menu_controller.resource_import_action(
            ResourceMenuAction.ADD_TO_QGIS
        )
        if not action.isVisible() or not action.isEnabled():
            return

        action.trigger()

    def __set_resource_import_menu_visible(self, visible: bool) -> None:
        if visible:
            self.download_action.setMenu(self.menuDownload)
            return

        self.download_action.setMenu(None)

    def __is_style_transfer_compatible(
        self,
        qgis_layer: Optional[QgsMapLayer],
        ngw_layer: object,
    ) -> bool:
        if isinstance(qgis_layer, QgsRasterLayer):
            return isinstance(ngw_layer, NGWRasterLayer)

        if not isinstance(qgis_layer, QgsVectorLayer):
            return False

        if not isinstance(ngw_layer, NGWAbstractVectorResource):
            return False

        return qgis_layer.geometryType() == ngw_layer.geometry_type

    @pyqtSlot(str, str, Exception)
    def __model_warning_process(
        self, job_name: str, job_uuid: str, exception: Exception
    ):
        self.__model_exception_process(
            job_name, job_uuid, exception, Qgis.MessageLevel.Warning
        )

    @pyqtSlot(str, str, Exception)
    def __model_error_process(
        self, job_name: str, job_uuid: str, exception: Exception
    ):
        self.__model_exception_process(
            job_name, job_uuid, exception, Qgis.MessageLevel.Critical
        )

    def __model_exception_process(
        self,
        job_name: str,
        job_uuid: str,
        exception: Exception,
        level: Qgis.MessageLevel,
    ):
        if job_name == "NGWResourceDeletePreviewLoader":
            return

        # always unblock in case of any error so to allow to fix it
        self.unblock_gui()

        if (
            self.__root_children_loading_parent_id is not None
            and job_name == "NGWResourceUpdater"
        ):
            self.__stop_root_children_loading()

        if not job_name and self.__root_loading_cancel_requested:
            self.__show_root_loading_error(exception)
            return

        if not job_name:
            self.__show_root_loading_error(exception)
            return

        if not self.resource_model.is_connected:
            self.disable_tools()

        _msg, _msg_ext, _icon = self.__get_model_exception_description(
            exception
        )

        connections_manager = NgwConnectionsManager()
        current_connection_id = connections_manager.current_connection_id
        assert current_connection_id
        current_connection = connections_manager.current_connection
        assert current_connection

        for i, command in enumerate(self._queue_to_add):
            if command.job_uuid == job_uuid:
                del self._queue_to_add[i]
                break

        self.__pending_resource_imports = [
            command
            for command in self.__pending_resource_imports
            if command.job_uuid != job_uuid
        ]

        if (
            isinstance(exception, NgwError)
            and exception.code == ErrorCode.AuthorizationError
        ):
            self.try_check_https = False
            dialog = NgwConnectionEditDialog(
                self.iface.mainWindow(), current_connection_id
            )
            message = self.tr(
                "Failed to connect. Please check your connection details"
            )
            dialog.set_message(
                message,
                Qgis.MessageLevel.Critical,
                duration=0,
            )
            logger.error(message)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                self.reinit_tree(force=True)
            else:
                self.__show_connection_parameters_error()
            del dialog
            return

        # Detect very first connection.
        if self.jobs_count == 1:
            if (
                isinstance(exception, JobServerRequestError)
                and exception.need_reconnect
            ):
                updated_url = current_connection.url

                # Try to fix http -> https. Useful for fixing old (saved) cloud
                # connections.
                if updated_url.startswith("http://") and updated_url.endswith(
                    ".nextgis.com"
                ):
                    self.try_check_https = True
                    updated_url = updated_url.replace("http://", "https://")
                    updated_connection = replace(
                        current_connection, url=updated_url
                    )
                    connections_manager.upsert(updated_connection)
                    connections_manager.save()
                    logger.debug(
                        'Meet "http://", ".nextgis.com" connection error at '
                        "very first time using this web gis connection. Trying"
                        ' to reconnect with "https://"'
                    )
                    self.reinit_tree(force=True)
                    return

                # Show connect dialog again.
                self.try_check_https = False
                dialog = NgwConnectionEditDialog(
                    self.iface.mainWindow(), current_connection_id
                )
                message = self.tr(
                    "Failed to connect. Please check your connection details"
                )
                dialog.set_message(
                    message,
                    Qgis.MessageLevel.Critical,
                    duration=0,
                )
                logger.error(message)
                result = dialog.exec()
                if result == QDialog.DialogCode.Accepted:
                    self.reinit_tree(force=True)
                else:
                    self.__show_connection_parameters_error()
                del dialog
                return

        # The second time return back http if there was an error: this might be some
        # other error, not related to http/https changing.
        if self.try_check_https:
            # this can be only when there are more than 1 connection errors
            self.try_check_https = False
            updated_url = current_connection.url.replace("https://", "http://")
            updated_connection = replace(current_connection, url=updated_url)
            connections_manager.upsert(updated_connection)
            connections_manager.save()
            logger.debug(
                'Failed to reconnect with "https://". Return "http://" back'
            )
            self.reinit_tree(force=True)
            return

        if (
            isinstance(exception, JobServerRequestError)
            and exception.user_msg is not None
            and exception.try_again is None
        ):
            if job_name == ROOT_RESOURCES_LOADER_JOB_ID:
                self.__show_root_loading_error(exception)
                return

            if job_name in self.__canceled_job_ids:
                return

            self.show_error(exception.user_msg)
            return

        if job_name == ROOT_RESOURCES_LOADER_JOB_ID:
            self.__show_root_loading_error(exception)
            return

        if job_name in self.__canceled_job_ids:
            return

        if (
            isinstance(exception, NgConnectError)
            and exception.try_again is None
        ):
            if self.__is_reinit_tree:
                exception.try_again = lambda: self.reinit_tree(force=True)

        error_id = NgConnectInterface.instance().notifier.display_exception(
            exception
        )
        if self.__is_reinit_tree:
            self.__reinit_tree_error = error_id

    def __start_root_loading_overlay(self) -> None:
        self.__root_loading_cancel_requested = False
        self.__root_children_loading_parent_id = None
        self.__cancel_pending_job_id = None
        self.resources_tree_view.begin_loading(
            self.tr("Loading Web GIS resources..."),
            compact_title=self.tr("Loading resources..."),
            message=self.tr("Loading the root resource."),
            draw_background=True,
        )

    def __start_root_children_loading(self) -> bool:
        root_index = self.resource_model.index(0, 0, QModelIndex())
        if not root_index.isValid():
            return False

        parent_id = root_index.data(QNGWResourceItem.NGWResourceIdRole)
        if parent_id is None:
            return False

        has_active_updater = any(
            job.getJobId() == "NGWResourceUpdater"
            for job in self.resource_model.jobs
        )
        if (
            not self.resource_model.canFetchMore(root_index)
            and not has_active_updater
        ):
            return False

        self.__root_children_loading_parent_id = int(parent_id)
        self.__cancel_pending_job_id = None
        self.resources_tree_view.begin_loading(
            self.tr("Loading Web GIS resources..."),
            compact_title=self.tr("Loading resources..."),
            message=self.tr("Loading the root resource contents."),
            draw_background=True,
        )

        if (
            self.resource_model.canFetchMore(root_index)
            and not has_active_updater
        ):
            self.resource_model.fetchMore(root_index)

        return True

    def __has_pending_root_children_loading(
        self,
        *,
        finishing_updater: bool = False,
    ) -> bool:
        if self.__root_children_loading_parent_id is None:
            return False

        root_index = self.resource_model.index_from_id(
            self.__root_children_loading_parent_id
        )
        if root_index is None or not root_index.isValid():
            return False

        updater_count = sum(
            1
            for job in self.resource_model.jobs
            if job.getJobId() == "NGWResourceUpdater"
        )
        if finishing_updater and updater_count > 0:
            updater_count -= 1

        return (
            self.resource_model.canFetchMore(root_index) or updater_count > 0
        )

    def __stop_root_children_loading(self) -> None:
        self.__root_children_loading_parent_id = None
        self.resources_tree_view.end_loading()

    def __show_root_loading_error(self, exception: Exception) -> None:
        self.__root_children_loading_parent_id = None
        self.resources_tree_view.end_loading()
        self.disable_tools()

        if self.__root_loading_cancel_requested:
            self.resources_tree_view.set_error_state(
                self.tr("The root resource loading was canceled."),
                title=self.tr("Loading canceled"),
                details=self.tr(
                    "Try loading the resource tree again when the connection becomes available."
                ),
                retry_enabled=False,
                icon_name="cloud_off",
                action=OverlayButtonState(
                    action=OverlayAction.RELOAD_TREE,
                    text=self.tr("Try again"),
                ),
            )
            return

        if self.__is_nextgis_cloud_http_500_error(exception):
            self.resources_tree_view.set_error_state(
                self.tr(
                    "The server returned an internal error while loading the root resource."
                ),
                title=self.tr("Unable to load resources"),
                details=self.tr(
                    "Contact support for the current Web GIS instance."
                ),
                retry_enabled=False,
                icon_name="cloud_alert",
                action=OverlayButtonState(
                    action=OverlayAction.RELOAD_TREE,
                    text=self.tr("Try again"),
                ),
                secondary_action=OverlayButtonState(
                    action=OverlayAction.CONTACT_SUPPORT,
                    text=self.tr("Contact support"),
                ),
            )
            return

        if self.__is_connection_error(exception):
            self.resources_tree_view.set_error_state(
                "",
                title=self.tr("Unable to connect"),
                details=self.__connection_error_details(),
                retry_enabled=False,
                icon_name="globe_2_cancel",
                action=OverlayButtonState(
                    action=OverlayAction.RUN_DIAGNOSTICS,
                    text=self.tr("Run diagnostics"),
                ),
                secondary_action=OverlayButtonState(
                    action=OverlayAction.RELOAD_TREE,
                    text=self.tr("Try again"),
                ),
            )
            return

        details = self.tr(
            "Run diagnostics to check the connection and server availability."
        )
        user_message = getattr(exception, "user_msg", None)
        if user_message:
            details = f"{details}\n\n{user_message}"

        self.resources_tree_view.set_error_state(
            self.tr("The root resource could not be loaded."),
            title=self.tr("Unable to load resources"),
            details=details,
            retry_enabled=False,
            icon_name="globe_2_cancel",
            action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text=self.tr("Try again"),
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text=self.tr("Run diagnostics"),
            ),
        )

    def __show_connection_parameters_error(self) -> None:
        self.__root_children_loading_parent_id = None
        self.resources_tree_view.end_loading()
        self.disable_tools()
        self.resources_tree_view.set_error_state(
            "",
            title=self.tr("Unable to connect"),
            details=self.__connection_error_details(),
            retry_enabled=False,
            icon_name="globe_2_cancel",
            action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text=self.tr("Run diagnostics"),
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text=self.tr("Try again"),
            ),
        )

    def __connection_error_details(self) -> str:
        return self.tr(
            "The selected connection is invalid or unavailable.\n\n"
            "Run diagnostics to check the connection settings and server availability."
        )

    def __is_nextgis_cloud_http_500_error(
        self,
        exception: Exception,
    ) -> bool:
        has_http_500 = any(
            getattr(candidate, "status_code", None) == 500
            for candidate in self.__error_candidates(exception)
        )
        if not has_http_500:
            return False

        connection = NgwConnectionsManager().current_connection
        return connection is not None and self.__is_nextgis_cloud_url(
            connection.url
        )

    def __is_connection_error(self, exception: Exception) -> bool:
        connection_error_codes = (
            ErrorCode.NgwConnectionError,
            ErrorCode.InvalidConnection,
        )
        return any(
            getattr(candidate, "is_network_problem", False)
            or getattr(candidate, "code", None) in connection_error_codes
            for candidate in self.__error_candidates(exception)
        )

    @staticmethod
    def __error_candidates(exception: Exception) -> Tuple[Exception, ...]:
        candidates = (
            exception,
            getattr(exception, "wrapped_exception", None),
            getattr(exception, "__cause__", None),
        )
        return tuple(
            candidate
            for candidate in candidates
            if isinstance(candidate, Exception)
        )

    @staticmethod
    def __is_nextgis_cloud_url(url: str) -> bool:
        try:
            hostname = urllib.parse.urlparse(
                NgwConnection.normalize_url(url)
            ).hostname
        except ValueError:
            return False

        if hostname is None:
            return False

        hostname = hostname.rstrip(".").lower()
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in ("nextgis.com", "nextgis.ru")
        )

    def __open_current_connection_diagnostics(
        self,
        *,
        start_immediately: bool = False,
    ) -> None:
        connection = NgwConnectionsManager().current_connection
        if connection is None:
            return

        dialog = NgwConnectionDiagnosticsDialog(
            connection,
            self,
            start_immediately=start_immediately,
        )
        dialog.exec()

    @pyqtSlot()
    def __open_create_web_gis_url(self) -> None:
        QDesktopServices.openUrl(
            QUrl(self.resources_tree_view.create_web_gis_url())
        )

    def __update_create_web_gis_button_visibility(self) -> None:
        connection = NgwConnectionsManager().current_connection
        is_visible = (
            not self.__is_tree_overlay_visible
            and connection is not None
            and self.__is_demo_or_sandbox_connection(connection)
        )
        self.__create_web_gis_button.setVisible(is_visible)

    def __update_promo_banner_visibility(self) -> None:
        if self.__promo_banner_container is None:
            return

        self.__promo_banner_container.setVisible(
            not self.__is_tree_overlay_visible
        )

    def __is_demo_or_sandbox_connection(
        self,
        connection: NgwConnection,
    ) -> bool:
        connection_host = urllib.parse.urlparse(
            NgwConnection.normalize_url(connection.url)
        ).netloc
        demo_host = urllib.parse.urlparse(utils.nextgis_domain("demo")).netloc
        sandbox_host = urllib.parse.urlparse(
            utils.nextgis_domain("sandbox")
        ).netloc

        return connection_host in (demo_host, sandbox_host)

    def __try_sandbox_web_gis(self) -> None:
        sandbox_url = utils.nextgis_domain("sandbox")
        connection = NgwConnection(
            str(uuid.uuid4()),
            self.tr("Sandbox"),
            sandbox_url,
            None,
        )

        connections_manager = NgwConnectionsManager()
        connections_manager.upsert(connection)
        connections_manager.current_connection_id = connection.id
        connections_manager.save()
        self.reinit_tree(force=True)

    def __get_model_exception_description(self, exception: Exception):
        msg = None
        msg_ext = None
        icon = plugin_icon("synchronization/field_error.svg")

        if isinstance(exception, JobServerRequestError):
            msg = self.tr("Error occurred while communicating with Web GIS")
            msg_ext = f"URL: {exception.url}"
            msg_ext += f"\nMSG: {exception}"

        elif isinstance(exception, JobNGWError):
            msg = str(exception)
            msg_ext = "URL: " + exception.url

        if (
            isinstance(exception, NgwError)
            and exception.code == ErrorCode.AuthorizationError
        ):
            msg = " " + self.tr("Access denied. Enter your login.")

        elif isinstance(exception, JobError):
            if isinstance(exception.wrapped_exception, NgConnectError):
                msg = exception.wrapped_exception.user_message
                msg_ext = exception.wrapped_exception.detail
            else:
                msg = str(exception)
                # If we have message for user - add it instead of system message.
                if exception.wrapped_exception is not None:
                    user_msg = getattr(
                        exception.wrapped_exception, "user_msg", None
                    )
                    if user_msg is not None:
                        msg_ext = user_msg
                    else:
                        try:
                            msg_ext = json.loads(
                                str(exception.wrapped_exception)
                            )["message"]
                        except Exception:
                            msg_ext = str(exception.wrapped_exception)

        elif isinstance(exception, JobWarning):
            msg = str(exception)
            icon = plugin_icon("synchronization/field_warning.svg")

        elif isinstance(exception, NgConnectError):
            msg = exception.user_message
            msg_ext = exception.detail

        else:
            msg = self.tr("Internal plugin error occurred.")
            msg_ext = ""

        return msg, msg_ext, icon

    def __msg_in_qgis_mes_bar(
        self, message: str, level=Qgis.MessageLevel.Info, duration: int = 0
    ):
        if message.endswith(".."):
            message = message[:-1]

        widget = self.iface.messageBar().createMessage(PLUGIN_NAME, message)
        self.iface.messageBar().pushWidget(widget, level, duration)

    @pyqtSlot(str)
    def __modelJobStarted(self, job_id: str):
        if (
            self.__cancel_pending_job_id is not None
            and self.__cancel_pending_job_id != job_id
        ):
            self.__cancel_pending_job_id = None
            self.resources_tree_view.set_loading_cancel_pending(
                "",
                pending=False,
            )

        if job_id == ROOT_RESOURCES_LOADER_JOB_ID:
            self.__start_root_loading_overlay()

        if job_id in self.blocked_jobs:
            self.setUserVisible(True)
            self.block_gui()
            cancel_action = None
            if job_id in self._cancelable_blocked_jobs:
                self.__cancelable_job_ids.append(job_id)
                cancel_action = OverlayButtonState(
                    action=OverlayAction.CANCEL,
                    text=self.tr("Cancel"),
                )

            self.resources_tree_view.addBlockedJob(
                self.blocked_jobs[job_id],
                cancel_action=cancel_action,
                compact_title=self.blocked_job_compact_titles[job_id],
            )

    @pyqtSlot(str, str)
    def __modelJobStatusChanged(self, job_id: str, status: str):
        if job_id in self.blocked_jobs:
            self.resources_tree_view.addJobStatus(
                self.blocked_jobs[job_id], status
            )

    @pyqtSlot(str, str)
    def __modelJobFinished(self, job_id: str, job_uuid: str):
        # note: __modelJobFinished will be triggered even if error/warning
        # occurred during job execution
        self.jobs_count += 1

        if job_id == ROOT_RESOURCES_LOADER_JOB_ID:
            if not self.__start_root_children_loading():
                self.resources_tree_view.end_loading()
                self.unblock_gui()
            self.__root_loading_cancel_requested = False

        if (
            job_id == "NGWResourceUpdater"
            and self.__root_children_loading_parent_id is not None
            and not self.__has_pending_root_children_loading(
                finishing_updater=True,
            )
        ):
            self.__stop_root_children_loading()
            self.unblock_gui()

        if job_id in self.blocked_jobs:
            self.unblock_gui()
            self.resources_tree_view.removeBlockedJob(
                self.blocked_jobs[job_id], check_overlay=False
            )
            self.__canceled_job_ids.discard(job_id)
            self.__remove_cancelable_job(job_id)

        if self.__cancel_pending_job_id == job_id:
            self.__cancel_pending_job_id = None
            self.resources_tree_view.set_loading_cancel_pending(
                "",
                pending=False,
            )

        self.__add_layers_after_finish(job_uuid)
        self.__resume_pending_resource_imports(job_uuid)

        if len(self.resource_model.jobs) == 1 or all(
            job.getJobId() not in self.blocked_jobs
            for job in self.resource_model.jobs
        ):
            self.resources_tree_view.check_overlay()

        self.__update_create_web_gis_button_visibility()

    @pyqtSlot()
    def __onModelBlockIndexes(self):
        self.block_gui()

    @pyqtSlot()
    def __onModelReleaseIndexes(self):
        if self._first_gui_block_on_refresh:
            self._first_gui_block_on_refresh = False
        else:
            self.unblock_gui()

    def block_gui(self):
        self.main_tool_bar.setEnabled(False)
        self.search_panel.setEnabled(False)
        self.__resource_menu_controller.set_add_to_web_gis_actions_enabled(
            False
        )
        self.__resource_menu_controller.set_resource_import_actions_enabled(
            False
        )
        self.__resource_menu_controller.set_resource_creation_actions_enabled(
            False
        )

        if HAS_NGSTD and self.__ngstd_connection is not None:
            NGAccess.instance().userInfoUpdated.disconnect(
                self.__on_ngstd_user_info_updated
            )
            self.__ngstd_connection = None

    def unblock_gui(self):
        self.main_tool_bar.setEnabled(True)
        self.search_panel.setEnabled(True)
        self.checkImportActionsAvailability()

        if HAS_NGSTD and self.__ngstd_connection is None:
            self.__ngstd_connection = (
                NGAccess.instance().userInfoUpdated.connect(
                    self.__on_ngstd_user_info_updated
                )
            )

    @pyqtSlot(bool)
    def __handle_tree_overlay_visibility_changed(
        self, is_visible: bool
    ) -> None:
        self.__is_tree_overlay_visible = is_visible
        self.__update_create_web_gis_button_visibility()
        self.__update_promo_banner_visibility()

    @pyqtSlot(object)
    def __handle_tree_overlay_action(self, action: OverlayAction) -> None:
        if action == OverlayAction.CREATE_CONNECTION:
            dialog = NgwConnectionEditDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            self.reinit_tree(force=True)
            return

        if action == OverlayAction.CREATE_WEB_GIS:
            QDesktopServices.openUrl(
                QUrl(self.resources_tree_view.create_web_gis_url())
            )
            return

        if action == OverlayAction.CREATE_SANDBOX_CONNECTION:
            self.__try_sandbox_web_gis()
            return

        if action == OverlayAction.SWITCH_SEARCH_CONNECTION:
            self.__switch_to_search_connection_target()
            return

        if action == OverlayAction.CREATE_SEARCH_CONNECTION:
            self.__create_search_connection_target()
            return

        if action == OverlayAction.OPEN_PLUGIN_SETTINGS:
            self.iface.showOptionsDialog(
                self.iface.mainWindow(), "NextGIS Connect"
            )
            return

        if action == OverlayAction.OPEN_NEXTGIS_SETTINGS:
            self.iface.showOptionsDialog(self.iface.mainWindow(), "NextGIS")
            return

        if action == OverlayAction.OPEN_PLUGIN_MANAGER:
            self.__open_plugin_manager_updates()
            return

        if action == OverlayAction.SKIP_PLUGIN_UPDATE:
            self.__skip_active_plugin_update()
            return

        if action == OverlayAction.CONVERT_CONNECTIONS:
            NgwConnectionsManager().convert_old_connections(convert_auth=True)
            self.reinit_tree(force=True)
            return

        if action == OverlayAction.CANCEL:
            self.__cancel_active_loading()
            return

        if action == OverlayAction.RELOAD_TREE:
            self.reinit_tree(force=True)
            return

        if action == OverlayAction.RUN_DIAGNOSTICS:
            self.__open_current_connection_diagnostics(start_immediately=True)
            return

        if action == OverlayAction.CONTACT_SUPPORT:
            utm = utils.utm_tags("error")
            QDesktopServices.openUrl(
                QUrl(f"{utils.nextgis_domain()}/contact/?{utm}")
            )
            return

        if action == OverlayAction.OPEN_NEXTGIS_SITE:
            QDesktopServices.openUrl(QUrl(utils.nextgis_domain()))

    def __open_plugin_manager_updates(self) -> None:
        try:
            import pyplugin_installer

            pyplugin_installer.instance().showPluginManagerWhenReady(3)
        except Exception:
            self.iface.pluginManagerInterface().showPluginManager(3)

    def __skip_active_plugin_update(self) -> None:
        if self.__active_plugin_update is None:
            self.resources_tree_view.clear_plugin_update_state()
            return

        self.__skipped_plugin_update_ids.add(
            self.__active_plugin_update.skip_id
        )
        self.__active_plugin_update = None
        self.resources_tree_view.clear_plugin_update_state()

    def reinit_tree(self, force=False):
        self.__is_reinit_tree = True
        self.__root_loading_cancel_requested = False
        self.__root_children_loading_parent_id = None
        self.__cancel_pending_job_id = None
        if self.__reinit_tree_error is not None:
            NgConnectInterface.instance().notifier.dismiss_message(
                self.__reinit_tree_error
            )
            self.__reinit_tree_error = None

        self.resources_tree_view.clear_error_state()
        self.resources_tree_view.clear_availability_state()
        self.resources_tree_view.set_auth_required(False)
        self.resources_tree_view.set_migration_required(False)
        self.resources_tree_view.set_search_empty(False)
        self.resources_tree_view.clear_search_connection_target()
        self.resources_tree_view.end_loading()

        # clear tree and states
        self.block_gui()

        try:
            connections_manager = NgwConnectionsManager()
            if connections_manager.has_not_converted_connections():
                connections_manager.convert_old_connections(convert_auth=True)

            current_connection = connections_manager.current_connection
            if current_connection is None:
                self.__init_title()
                self.jobs_count = 0
                self.resource_model.resetModel(None)
                self.unblock_gui()
                self.disable_tools()
                self.resources_tree_view.set_has_connections(False)
                self.__update_create_web_gis_button_visibility()
                return

            self.__init_title()
            self.resources_tree_view.set_has_connections(True)
            self.__update_create_web_gis_button_visibility()

            if (
                HAS_NGSTD
                and current_connection.method == "NextGIS"
                and not NGAccess.instance().isUserAuthorized()
            ):
                self.jobs_count = 0
                self.resource_model.resetModel(None)
                self.resources_tree_view.set_auth_required(True)
                self.unblock_gui()
                self.disable_tools()
                return

            if force:
                if HAS_NGSTD and current_connection.method == "NextGIS":
                    NGRequest.addAuthURL(
                        NGAccess.instance().endPoint(), current_connection.url
                    )

                # start working with connection at very first time
                self.jobs_count = 0

                self._first_gui_block_on_refresh = True
                ngw_connection = QgsNgwConnection(current_connection.id)
                self.__start_root_loading_overlay()

                self.resource_model.resetModel(ngw_connection)

                if (
                    self.resource_model.ngw_version is not None
                    and not self.resource_model.is_ngw_version_supported
                ):
                    self.resources_tree_view.end_loading()
                    self.unblock_gui()
                    self.disable_tools()

                    self.resources_tree_view.set_unavailable_state(
                        self.resource_model.support_status,
                        qgis_utils.pluginMetadata(
                            "nextgis_connect", "version"
                        ),
                        self.resource_model.ngw_version,
                    )

                    logger.error("NGW version is outdated")

            # expand root item
            # self.resources_tree_view.setExpanded(self.resource_model.index(0, 0, QModelIndex()), True)

        except Exception as error:
            self.jobs_count = 0
            self.resources_tree_view.end_loading()
            self.resource_model.resetModel(None)

            self.unblock_gui()
            self.disable_tools()

            logger.exception("Model update error")
            self.resources_tree_view.set_error_state(
                self.tr("The resource tree could not be refreshed."),
                details=str(error),
            )
            NgConnectInterface.instance().notifier.display_exception(error)

        self.__update_search_action()
        self.__is_reinit_tree = False

    def __cancel_active_loading(self) -> None:
        if self.__cancel_pending_job_id is not None:
            return

        if len(self.__cancelable_job_ids) == 0:
            return

        active_job_id = self.__cancelable_job_ids[-1]
        if (
            active_job_id == "AddLayersStub"
            and self.__active_resource_importer is not None
        ):
            self.__active_resource_importer.cancel()
            self.__mark_loading_cancel_requested("AddLayersStub")
            return

        if not self.resource_model.cancel_job(active_job_id):
            return

        self.__canceled_job_ids.add(active_job_id)
        self.__mark_loading_cancel_requested(active_job_id)

    def __remove_cancelable_job(self, job_id: str) -> None:
        for position in range(len(self.__cancelable_job_ids) - 1, -1, -1):
            if self.__cancelable_job_ids[position] == job_id:
                self.__cancelable_job_ids.pop(position)
                return

    def __mark_loading_cancel_requested(self, job_id: str) -> None:
        self.__cancel_pending_job_id = job_id
        self.resources_tree_view.set_loading_cancel_pending(
            self.tr("Canceling..."),
        )

    @pyqtSlot()
    def __action_refresh_tree(self):
        self.reinit_tree(force=True)

    @pyqtSlot(bool)
    def __toggle_filter(self, state: bool) -> None:
        if not state:
            self.resource_model.reset_search()
            self.__clear_search_connection_target()
        else:
            self.search_panel.clear()
            self.search_panel.focus()

        self.search_panel.setVisible(state)

    def __add_resource_to_tree(self, ngw_resource):
        # TODO: fix duplicate with model.processJobResult
        if ngw_resource.common.parent is None:
            index = QModelIndex()
            self.resource_model.addNGWResourceToTree(index, ngw_resource)
        else:
            index = self.resource_model.index_from_id(
                ngw_resource.parent_id,
            )

            item = index.internalPointer()
            current_ids = [
                item.child(i)
                .data(QNGWResourceItem.NGWResourceRole)
                .resource_id
                for i in range(item.childCount())
                if isinstance(item.child(i), QNGWResourceItem)
            ]
            if ngw_resource.resource_id not in current_ids:
                self.resource_model.addNGWResourceToTree(index, ngw_resource)

    def disable_tools(self):
        for widget in (
            self.download_action,
            self.upload_action,
            self.creation_action,
            self.search_action,
            self.search_panel,
            self.actionOpenInBrowser,
        ):
            widget.setEnabled(False)
        self.__resource_menu_controller.set_add_to_web_gis_actions_enabled(
            False
        )
        self.__resource_menu_controller.set_resource_import_actions_enabled(
            False
        )
        self.__resource_menu_controller.set_resource_creation_actions_enabled(
            False
        )

        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

    @pyqtSlot()
    def action_settings(self):
        self.iface.showOptionsDialog(
            self.iface.mainWindow(), "NextGIS Connect"
        )

    @pyqtSlot(QPoint)
    def __show_connection_switch_menu(
        self,
        popup_position: QPoint,
    ) -> None:
        self.__close_connection_switch_menu()

        connections_manager = NgwConnectionsManager()
        menu = ConnectionSwitchMenu(
            connections_manager.connections,
            connections_manager.current_connection_id,
            self.main_tool_bar,
        )
        menu.switch_requested.connect(self.__switch_connection)
        self.__connection_switch_menu = menu
        menu.popup(popup_position)

    def __close_connection_switch_menu(self) -> None:
        menu = self.__connection_switch_menu
        if menu is None:
            return

        self.__connection_switch_menu = None
        menu.close()
        menu.deleteLater()

    @pyqtSlot(str, object)
    def __switch_connection(
        self,
        connection_id: str,
        auth_config_id: Optional[str],
    ) -> None:
        connections_manager = NgwConnectionsManager()
        plugin = NgConnectInterface.instance()
        connections_manager.connection_updated.connect(
            plugin.connection_updated.emit
        )
        switcher = NgwConnectionSwitcher(connections_manager)
        if not switcher.switch(connection_id, auth_config_id):
            return

        plugin.settings_changed.emit()
        self.search_panel.set_connection_id(connection_id)
        self.reinit_tree(force=True)

    def add_to_web_gis_action(
        self,
        action_id: ResourceMenuAction,
    ) -> QAction:
        return self.__resource_menu_controller.add_to_web_gis_action(action_id)

    def resource_creation_action(
        self,
        action_id: ResourceMenuAction,
    ) -> QAction:
        return self.__resource_menu_controller.resource_creation_action(
            action_id
        )

    def str_to_link(self, text: str, url: str) -> str:
        return f'<a href="{url}"><span style=" text-decoration: underline; color:#0000ff;">{text}</span></a>'

    def __create_resource_menu_item_adapter(
        self,
    ) -> ResourceMenuItemAdapter:
        bindings = (
            ResourceTypeBinding(
                ResourceKind.QGIS_VECTOR_STYLE,
                (NGWQGISVectorStyle,),
            ),
            ResourceTypeBinding(
                ResourceKind.QGIS_RASTER_STYLE,
                (NGWQGISRasterStyle,),
            ),
            ResourceTypeBinding(
                ResourceKind.RASTER_STYLE,
                (NGWRasterStyle,),
            ),
            ResourceTypeBinding(
                ResourceKind.MAPSERVER_STYLE,
                (NGWMapServerStyle,),
            ),
            ResourceTypeBinding(ResourceKind.GROUP, (NGWGroupResource,)),
            ResourceTypeBinding(
                ResourceKind.VECTOR_LAYER,
                (NGWVectorLayer,),
            ),
            ResourceTypeBinding(
                ResourceKind.RASTER_LAYER,
                (NGWRasterLayer,),
            ),
            ResourceTypeBinding(
                ResourceKind.POSTGIS_LAYER,
                (NGWPostgisLayer,),
            ),
            ResourceTypeBinding(ResourceKind.WFS_LAYER, (NGWWfsLayer,)),
            ResourceTypeBinding(
                ResourceKind.WFS_SERVICE,
                (NGWWfsService,),
            ),
            ResourceTypeBinding(
                ResourceKind.OGCF_SERVICE,
                (NGWOgcfService,),
            ),
            ResourceTypeBinding(ResourceKind.WMS_LAYER, (NGWWmsLayer,)),
            ResourceTypeBinding(
                ResourceKind.WMS_SERVICE,
                (NGWWmsService,),
            ),
            ResourceTypeBinding(
                ResourceKind.WMS_CONNECTION,
                (NGWWmsConnection,),
            ),
            ResourceTypeBinding(ResourceKind.BASEMAP, (NGWBaseMap,)),
            ResourceTypeBinding(ResourceKind.TMS_LAYER, (NGWTmsLayer,)),
            ResourceTypeBinding(
                ResourceKind.TMS_CONNECTION,
                (NGWTmsConnection,),
            ),
            ResourceTypeBinding(ResourceKind.TILESET, (NGWTileset,)),
            ResourceTypeBinding(ResourceKind.WEB_MAP, (NGWWebMap,)),
            ResourceTypeBinding(
                ResourceKind.FORM,
                (),
                ("formbuilder_form",),
            ),
        )
        return ResourceMenuItemAdapter(bindings)

    def __create_resource_menu_context(
        self,
        selected_indexes: List[QModelIndex],
    ) -> ResourceMenuContext:
        menu_items: List[ResourceMenuItem] = []
        resource_indexes: List[QModelIndex] = []
        resources: List[NGWResource] = []
        has_inactive_resource_selection = False
        for index in selected_indexes:
            if not index.isValid():
                has_inactive_resource_selection = True
                continue

            item = index.internalPointer()
            if getattr(item, "locked", False):
                has_inactive_resource_selection = True
                continue

            resource = index.data(QNGWResourceItem.NGWResourceRole)
            if not isinstance(resource, NGWResource):
                has_inactive_resource_selection = True
                continue

            resource_indexes.append(index)
            resources.append(resource)
            menu_items.append(
                self.__resource_menu_item_adapter.adapt(
                    resource,
                    is_root=not index.parent().isValid(),
                    is_preview_supported=resource.is_preview_supported,
                    is_versioning_enabled=(
                        isinstance(resource, NGWVectorLayer)
                        and resource.is_versioning_enabled
                    ),
                    has_geometry=self.__resource_has_geometry(resource, index),
                )
            )

        if has_inactive_resource_selection:
            menu_items = []
            resource_indexes = []
            resources = []

        current_layer = self.iface.mapCanvas().currentLayer()
        current_layer_kind = LayerKind.NONE
        if isinstance(current_layer, QgsVectorLayer):
            current_layer_kind = LayerKind.VECTOR
        elif isinstance(current_layer, QgsRasterLayer):
            current_layer_kind = LayerKind.RASTER

        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        is_one_qgis_layer_selected = len(qgis_nodes) == 1 and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )
        selected_qgis_layer = (
            cast(QgsLayerTreeLayer, qgis_nodes[0]).layer()
            if is_one_qgis_layer_selected
            else None
        )

        can_update_style = False
        can_add_style = False
        if len(resources) == 1 and selected_qgis_layer is not None:
            style_target: object = resources[0]
            is_style_resource = isinstance(
                resources[0],
                (NGWQGISVectorStyle, NGWQGISRasterStyle),
            )
            if is_style_resource:
                style_target = (
                    resource_indexes[0]
                    .parent()
                    .data(QNGWResourceItem.NGWResourceRole)
                )

            can_update_style = self.__is_style_transfer_compatible(
                selected_qgis_layer,
                style_target,
            )
            can_add_style = can_update_style and not is_style_resource

        project = QgsProject.instance()
        assert project is not None

        return ResourceMenuContext(
            resources=tuple(menu_items),
            current_layer_kind=current_layer_kind,
            is_developer_mode=NgConnectSettings().is_developer_mode,
            has_qgis_selection=self.__has_uploadable_qgis_nodes(qgis_nodes),
            has_project_layers=self.__has_uploadable_project_layers(project),
            can_update_style=can_update_style,
            can_add_style=can_add_style,
        )

    def __resource_has_geometry(
        self,
        resource: NGWResource,
        resource_index: QModelIndex,
    ) -> bool:
        geometry_resource: object = resource
        if isinstance(resource, NGWQGISVectorStyle):
            geometry_resource = resource_index.parent().data(
                QNGWResourceItem.NGWResourceRole
            )

        return (
            not isinstance(geometry_resource, NGWAbstractVectorResource)
            or geometry_resource.geometry_type != GeometryType.Null
        )

    def __has_uploadable_project_layers(self, project: QgsProject) -> bool:
        root = project.layerTreeRoot()
        if root is None:
            return False

        return self.__has_uploadable_qgis_nodes(root.children())

    def __has_uploadable_qgis_nodes(
        self,
        qgis_nodes: List[QgsLayerTreeNode],
    ) -> bool:
        for qgis_node in qgis_nodes:
            if isinstance(qgis_node, QgsLayerTreeLayer):
                qgis_layer = qgis_node.layer()
                if self.__is_uploadable_qgis_layer(qgis_layer):
                    return True
                continue

            children = getattr(qgis_node, "children", None)
            if not callable(children):
                continue

            if self.__has_uploadable_qgis_nodes(children()):
                return True

        return False

    def __is_uploadable_qgis_layer(
        self,
        qgis_layer: Optional[QgsMapLayer],
    ) -> bool:
        if qgis_layer is None:
            return False

        resource_job = QGISResourceJob()
        return (
            resource_job.isSuitableLayer(qgis_layer)
            == resource_job.SUITABLE_LAYER
        )

    @pyqtSlot(QPoint)
    def __show_resource_context_menu(self, qpoint: QPoint) -> None:
        proxy_index = self.resources_tree_view.indexAt(qpoint)
        index = self.proxy_model.mapToSource(proxy_index)

        if not index.isValid() or index.internalPointer().locked:
            return

        selection_model = self.resources_tree_view.selectionModel()
        assert selection_model is not None
        proxy_selected_indexes = self.resources_tree_view.selectedIndexes()
        if proxy_index not in proxy_selected_indexes:
            selection_model.setCurrentIndex(
                proxy_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
            proxy_selected_indexes = [proxy_index]

        selected_indexes = [
            self.proxy_model.mapToSource(selected_index)
            for selected_index in proxy_selected_indexes
        ]
        context = self.__create_resource_menu_context(selected_indexes)
        global_position = self.resources_tree_view.viewport().mapToGlobal(
            qpoint
        )
        self.__resource_menu_controller.show(context, global_position)

    @pyqtSlot(object)
    def __handle_resource_menu_action(
        self,
        action_id: ResourceMenuAction,
    ) -> None:
        handlers: Dict[ResourceMenuAction, Callable[[], None]] = {
            ResourceMenuAction.ADD_TO_QGIS: self.__download_selected,
            ResourceMenuAction.ADD_MVT_LAYER: partial(
                self.__add_selected_resource_directly,
                ResourceMenuAction.ADD_MVT_LAYER,
            ),
            ResourceMenuAction.ADD_TMS_LAYER: partial(
                self.__add_selected_resource_directly,
                ResourceMenuAction.ADD_TMS_LAYER,
            ),
            ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER: partial(
                self.__add_selected_resource_directly,
                ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER,
            ),
            ResourceMenuAction.UPLOAD_SELECTED: self.upload_selected_resources,
            ResourceMenuAction.UPLOAD_PROJECT: self.upload_project_resources,
            ResourceMenuAction.UPDATE_STYLE: self.update_style,
            ResourceMenuAction.ADD_STYLE: self.add_style,
            ResourceMenuAction.OPEN_IN_WEB_GIS: self.open_ngw_resource_page,
            ResourceMenuAction.VIEW_IN_BROWSER: self.__open_in_web,
            ResourceMenuAction.OPEN_LAYER_HISTORY: self.open_layer_history,
            ResourceMenuAction.EXPAND_ALL: (
                self.__resource_tree_branch_controller.expand_selected
            ),
            ResourceMenuAction.COLLAPSE_ALL: (
                self.__resource_tree_branch_controller.collapse_selected
            ),
            ResourceMenuAction.DOWNLOAD_QML: self.download_qml,
            ResourceMenuAction.DOWNLOAD_NGFP: self.download_ngfp,
            ResourceMenuAction.COPY_STYLE: self.copy_style,
            ResourceMenuAction.OVERWRITE_LAYER: self.overwrite_ngw_layer,
            ResourceMenuAction.DUPLICATE_RESOURCE: (
                self.duplicate_current_ngw_resource
            ),
            ResourceMenuAction.CREATE_GROUP: self.create_group,
            ResourceMenuAction.CREATE_VECTOR_LAYER: self.create_vector_layer,
            ResourceMenuAction.CREATE_FORM: (
                self.__create_form_for_selected_vector_layer
            ),
            ResourceMenuAction.CREATE_WEB_MAP: (
                self.__create_web_map_for_selected_resource
            ),
            ResourceMenuAction.CREATE_WFS_SERVICE: partial(
                self.create_wfs_or_ogcf_service,
                "WFS",
            ),
            ResourceMenuAction.CREATE_OGCF_SERVICE: partial(
                self.create_wfs_or_ogcf_service,
                "OGC API - Features",
            ),
            ResourceMenuAction.CREATE_WMS_SERVICE: self.create_wms_service,
            ResourceMenuAction.RENAME_RESOURCE: self.rename_ngw_resource,
            ResourceMenuAction.SHOW_PROPERTIES: self.show_properties_dialog,
            ResourceMenuAction.DELETE_RESOURCE: self.delete_current_ngw_resource,
        }

        try:
            handler = handlers[action_id]
        except KeyError as error:
            raise ValueError(
                f"Unsupported resource menu action: {action_id}"
            ) from error

        handler()

    def __create_web_map_for_selected_resource(self) -> None:
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        if isinstance(
            resource,
            (
                NGWQGISVectorStyle,
                NGWQGISRasterStyle,
                NGWRasterStyle,
                NGWMapServerStyle,
            ),
        ):
            self.create_web_map_for_style()
            return

        self.create_web_map_for_layer()

    def __create_form_for_selected_vector_layer(self) -> None:
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if not selected_index.isValid():
            return

        resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(resource, NGWVectorLayer):
            return

        url = (
            f"{resource.get_absolute_url().rstrip('/')}"
            "/create?" + urllib.parse.urlencode({"cls": "formbuilder_form"})
        )
        QDesktopServices.openUrl(QUrl(url))

    def trvDoubleClickProcess(self, index: QModelIndex) -> None:
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        if isinstance(ngw_resource, NGWWebMap):
            self.__open_in_web()

    def open_ngw_resource_page(self):
        sel_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            url = ngw_resource.get_absolute_url()
            QDesktopServices.openUrl(QUrl(url))

    def open_ngw_resource_page_from_layer(self):
        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        is_one_qgis_selected = len(qgis_nodes) == 1
        is_layer = is_one_qgis_selected and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )

        layer = (
            cast(QgsLayerTreeLayer, qgis_nodes[0]).layer()
            if is_layer
            else None
        )
        assert layer is not None

        connection_id = layer.customProperty("ngw_connection_id")
        resource_id = layer.customProperty("ngw_resource_id")

        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(connection_id)
        assert connection is not None

        url = QUrl(connection.url)
        url.setPath(f"/resource/{resource_id}")

        QDesktopServices.openUrl(url)

    def open_layer_history(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        if not selected_index.isValid():
            return

        ngw_resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        url = ngw_resource.get_absolute_url() + "/history"
        QDesktopServices.openUrl(QUrl(url))

    def open_layer_history_from_layer(self):
        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        is_one_qgis_selected = len(qgis_nodes) == 1
        is_layer = is_one_qgis_selected and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )

        layer = (
            cast(QgsLayerTreeLayer, qgis_nodes[0]).layer()
            if is_layer
            else None
        )
        assert layer is not None

        connection_id = layer.customProperty("ngw_connection_id")
        resource_id = layer.customProperty("ngw_resource_id")

        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(connection_id)
        assert connection is not None

        url = QUrl(connection.url)
        url.setPath(f"/resource/{resource_id}/history")

        QDesktopServices.openUrl(url)

    def rename_ngw_resource(self):
        # rename resources takes proxy index
        selected_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if not selected_index.isValid():
            return

        self.resources_tree_view.rename_resource(selected_index)

    def __open_in_web(self):
        selected_indexes = (
            self.resources_tree_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) != 1:
            return

        selected_index = self.proxy_model.mapToSource(selected_indexes[0])
        if not selected_index.isValid():
            return

        ngw_resource: NGWResource = selected_index.data(
            QNGWResourceItem.NGWResourceRole
        )
        url = ngw_resource.preview_url
        QDesktopServices.openUrl(QUrl(url))

    def __add_selected_resource_directly(
        self,
        action_id: ResourceMenuAction,
    ) -> None:
        selected_indexes = self.resources_tree_view.selectedIndexes()
        if len(selected_indexes) != 1:
            return

        source_index = self.proxy_model.mapToSource(selected_indexes[0])
        if not source_index.isValid():
            return

        resource = source_index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(resource, NGWResource):
            return

        self.__continue_direct_resource_import(
            resource.resource_id,
            action_id,
            self.__current_resource_import_target(),
        )

    def __continue_direct_resource_import(
        self,
        resource_id: int,
        action_id: ResourceMenuAction,
        target: QgisLayerImportTarget,
    ) -> None:
        source_index = self.resource_model.index_from_id(resource_id)
        if source_index is None or not source_index.isValid():
            return

        resource = source_index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(resource, NGWResource):
            return

        mode = self.__direct_resource_import_mode(action_id)
        if mode is None or not self.__is_direct_resource_import_supported(
            resource,
            source_index,
            mode,
        ):
            return

        if self.__schedule_direct_import_dependencies(
            resource,
            source_index,
            mode,
            action_id,
            target,
        ):
            return

        configuration = DirectResourceImportConfiguration(resource)
        if mode == ResourceImportMode.TMS:
            tms_configuration = self.__create_tms_import_configuration(
                resource,
                source_index,
            )
            if tms_configuration is None:
                return
            configuration = tms_configuration
        elif mode == ResourceImportMode.EXPERIMENTAL_NGW:
            experimental_configuration = (
                self.__create_experimental_import_configuration(
                    resource,
                    source_index,
                    action_id,
                    target,
                )
            )
            if experimental_configuration is None:
                return
            configuration = experimental_configuration

        request = ResourceImportRequest(
            mode=mode,
            source=self.__create_resource_import_source(
                configuration.linked_resource,
                with_provider_credentials=(
                    mode == ResourceImportMode.EXPERIMENTAL_NGW
                ),
            ),
            render_resource_id=configuration.render_resource_id,
            render_resource_ids=configuration.render_resource_ids,
            styles=configuration.styles,
            default_style_name=configuration.default_style_name,
            source_extent=configuration.source_extent,
        )
        self.__resource_layer_importer.import_resource(request, target)

    def __is_direct_resource_import_supported(
        self,
        resource: NGWResource,
        source_index: QModelIndex,
        mode: ResourceImportMode,
    ) -> bool:
        if not self.__resource_has_geometry(resource, source_index):
            return False

        if (
            mode == ResourceImportMode.EXPERIMENTAL_NGW
            and not NgConnectSettings().is_developer_mode
        ):
            return False

        if mode == ResourceImportMode.MVT:
            if not is_mvt_supported():
                return False

            return isinstance(
                resource,
                (
                    NGWVectorLayer,
                    NGWPostgisLayer,
                    NGWWfsLayer,
                ),
            )

        if mode == ResourceImportMode.EXPERIMENTAL_NGW:
            return isinstance(resource, NGWVectorLayer)

        if mode == ResourceImportMode.TMS:
            return isinstance(
                resource,
                (
                    NGWVectorLayer,
                    NGWPostgisLayer,
                    NGWQGISStyle,
                    NGWWebMap,
                    NGWRasterLayer,
                    NGWWmsLayer,
                    NGWTileset,
                ),
            )

        return False

    def __schedule_direct_import_dependencies(
        self,
        resource: NGWResource,
        source_index: QModelIndex,
        mode: ResourceImportMode,
        action_id: ResourceMenuAction,
        target: QgisLayerImportTarget,
    ) -> bool:
        needs_vector_children = mode in (
            ResourceImportMode.TMS,
            ResourceImportMode.EXPERIMENTAL_NGW,
        ) and isinstance(resource, (NGWVectorLayer, NGWPostgisLayer))
        if not needs_vector_children or not self.resource_model.canFetchMore(
            source_index
        ):
            return False

        job = self.resource_model.fetch_not_expanded([resource.resource_id])
        if job is None:
            return False

        self.__schedule_pending_resource_import(
            job.job_uuid,
            resource.resource_id,
            action_id,
            target,
        )
        return True

    def __create_tms_import_configuration(
        self,
        resource: NGWResource,
        source_index: QModelIndex,
    ) -> Optional[DirectResourceImportConfiguration]:
        if isinstance(resource, (NGWVectorLayer, NGWPostgisLayer)):
            style_resource = self.__select_vector_layer_style(source_index)
            if style_resource is None:
                return None
            return DirectResourceImportConfiguration(
                resource,
                render_resource_id=style_resource.resource_id,
            )

        if isinstance(resource, NGWQGISStyle):
            linked_resource = source_index.parent().data(
                QNGWResourceItem.NGWResourceRole
            )
            if not isinstance(linked_resource, NGWResource):
                return None
            return DirectResourceImportConfiguration(
                linked_resource,
                render_resource_id=resource.resource_id,
            )

        if isinstance(resource, NGWWebMap):
            render_resource_ids = self.__webmap_tms_render_resource_ids(
                resource
            )
            if len(render_resource_ids) == 0:
                self.show_info(self.tr("The Web map has no layers"))
                return None
            return DirectResourceImportConfiguration(
                resource,
                render_resource_ids=render_resource_ids,
                source_extent=self.__webmap_import_extent(resource),
            )

        if isinstance(resource, (NGWRasterLayer, NGWWmsLayer, NGWTileset)):
            return DirectResourceImportConfiguration(resource)

        return None

    def __create_experimental_import_configuration(
        self,
        resource: NGWResource,
        source_index: QModelIndex,
        action_id: ResourceMenuAction,
        target: QgisLayerImportTarget,
    ) -> Optional[DirectResourceImportConfiguration]:
        style_resources = tuple(
            child_resource
            for child_resource in self.resource_model.children_resources(
                source_index
            )
            if isinstance(child_resource, NGWQGISVectorStyle)
        )
        missing_style_ids = [
            style.resource_id
            for style in style_resources
            if not style.is_qml_populated
        ]
        if len(missing_style_ids) > 0:
            job = self.resource_model.fetch_missing_styles(missing_style_ids)
            if job is not None:
                self.__schedule_pending_resource_import(
                    job.job_uuid,
                    resource.resource_id,
                    action_id,
                    target,
                )
            return None

        default_style_name: Optional[str] = None
        if len(style_resources) > 1:
            default_style = self.__select_vector_layer_style(source_index)
            if default_style is None:
                return None
            default_style_name = default_style.display_name

        styles = tuple(
            ResourceImportStyle(
                name=style.display_name,
                qml=style.qml or "",
            )
            for style in style_resources
        )
        return DirectResourceImportConfiguration(
            resource,
            styles=styles,
            default_style_name=default_style_name,
        )

    def __webmap_tms_render_resource_ids(
        self,
        webmap: NGWWebMap,
    ) -> Tuple[int, ...]:
        layers = self.__webmap_tms_layers(webmap)
        if webmap.draw_order_enabled:
            layers.sort(key=self.__webmap_draw_order_sort_key)

        layers.reverse()
        return tuple(
            layer.layer_style_id
            for layer in layers
            if layer.layer_style_id != 0
        )

    def __webmap_tms_layers(
        self,
        webmap: NGWWebMap,
    ) -> List[NGWWebMapLayer]:
        layers: List[NGWWebMapLayer] = []
        for child in webmap.root.children:
            layers.extend(self.__webmap_item_tms_layers(child))

        return layers

    def __webmap_item_tms_layers(
        self,
        item: object,
    ) -> List[NGWWebMapLayer]:
        if isinstance(item, NGWWebMapLayer):
            return [item]

        if isinstance(item, NGWWebMapGroup):
            layers: List[NGWWebMapLayer] = []
            for child in item.children:
                layers.extend(self.__webmap_item_tms_layers(child))
            return layers

        return []

    def __webmap_draw_order_sort_key(
        self,
        layer: NGWWebMapLayer,
    ) -> Tuple[int, int]:
        draw_order_position = layer.draw_order_position
        if draw_order_position is None:
            return (1, 0)

        return (0, draw_order_position)

    def __webmap_import_extent(
        self,
        webmap: NGWWebMap,
    ) -> Optional[ResourceImportExtent]:
        extent = webmap.extent
        if extent is None:
            return None

        return ResourceImportExtent(
            x_min=extent.xMinimum(),
            y_min=extent.yMinimum(),
            x_max=extent.xMaximum(),
            y_max=extent.yMaximum(),
            coordinate_reference_system_auth_id=extent.crs().authid(),
        )

    def __schedule_pending_resource_import(
        self,
        job_uuid: str,
        resource_id: int,
        action_id: ResourceMenuAction,
        target: QgisLayerImportTarget,
    ) -> None:
        self.__pending_resource_imports.append(
            PendingResourceImport(
                job_uuid=job_uuid,
                resource_id=resource_id,
                action_id=action_id,
                target=target,
            )
        )

    def __current_resource_import_target(self) -> QgisLayerImportTarget:
        insertion_point = self.iface.layerTreeInsertionPoint()
        return QgisLayerImportTarget(
            group=insertion_point.group,
            position=insertion_point.position,
        )

    def __select_vector_layer_style(
        self,
        vector_layer_index: QModelIndex,
    ) -> Optional[NGWQGISVectorStyle]:
        styles = [
            resource
            for resource in self.resource_model.children_resources(
                vector_layer_index
            )
            if isinstance(resource, NGWQGISVectorStyle)
        ]
        if len(styles) == 0:
            self.show_info(
                self.tr(
                    "A QGIS vector style is required to add this layer as TMS"
                )
            )
            return None
        if len(styles) == 1:
            return styles[0]

        dialog = NGWLayerStyleChooserDialog(
            self.tr("Select style"),
            vector_layer_index,
            self.resource_model,
            self,
        )
        result = dialog.exec()
        selected_index = dialog.selectedStyleIndex()
        dialog.deleteLater()
        if (
            result != NGWLayerStyleChooserDialog.DialogCode.Accepted
            or selected_index is None
            or not selected_index.isValid()
        ):
            return None

        selected_resource = selected_index.data(
            QNGWResourceItem.NGWResourceRole
        )
        if not isinstance(selected_resource, NGWQGISVectorStyle):
            return None
        return selected_resource

    def __create_resource_import_source(
        self,
        resource: NGWResource,
        *,
        with_provider_credentials: bool = False,
    ) -> ResourceImportSource:
        connection = resource.connection.connection
        return ResourceImportSource(
            connection_url=connection.url,
            connection_id=connection.id,
            connection_instance_id=connection.domain_uuid,
            resource_id=resource.resource_id,
            display_name=resource.display_name,
            auth_config_id=connection.auth_config_id,
            provider_connection_url=(
                connection.url_with_credentials()
                if with_provider_credentials
                else None
            ),
        )

    def __direct_resource_import_mode(
        self,
        action_id: ResourceMenuAction,
    ) -> Optional[ResourceImportMode]:
        if action_id == ResourceMenuAction.ADD_MVT_LAYER:
            return ResourceImportMode.MVT
        if action_id == ResourceMenuAction.ADD_TMS_LAYER:
            return ResourceImportMode.TMS
        if action_id == ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER:
            return ResourceImportMode.EXPERIMENTAL_NGW
        return None

    @pyqtSlot(str)
    def __on_resource_layer_import_failed(self, message: str) -> None:
        self.show_error(
            self.tr("The resource could not be added to QGIS")
            + f"\n\n{message}"
        )

    @pyqtSlot(str)
    def __on_resource_layer_imported(
        self,
        layer_id: str,
    ) -> None:
        imported_layer = QgsProject.instance().mapLayer(layer_id)
        if imported_layer is None:
            return

        imported_layer.triggerRepaint()
        self.__select_qgis_layers((layer_id,))
        self.checkImportActionsAvailability()

    def __select_qgis_layers(self, layer_ids: Tuple[str, ...]) -> None:
        if len(layer_ids) == 0:
            return

        layer_tree_view = self.iface.layerTreeView()
        selection_model = layer_tree_view.selectionModel()
        layer_tree_model = layer_tree_view.layerTreeModel()
        view_model = layer_tree_view.model()
        if (
            selection_model is None
            or layer_tree_model is None
            or view_model is None
        ):
            return

        selection_model.clearSelection()
        current_index = QModelIndex()
        project = QgsProject.instance()
        selection_flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )

        for layer_id in layer_ids:
            layer = project.mapLayer(layer_id)
            if layer is None:
                continue

            layer_node = project.layerTreeRoot().findLayer(layer.id())
            if layer_node is None:
                continue

            source_index = layer_tree_model.node2index(layer_node)
            layer_index = view_model.mapFromSource(source_index)
            if not layer_index.isValid():
                continue

            selection_model.select(layer_index, selection_flags)
            current_index = layer_index

        if current_index.isValid():
            selection_model.setCurrentIndex(
                current_index,
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def __create_resource_batch_importer(
        self,
        indices: List[QModelIndex],
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> QgisResourceBatchImporter:
        return QgisResourceBatchImporter(
            self.resource_model,
            indices,
            insertion_point,
            QgisResourceImportInteraction(),
        )

    def __download_selected(self):
        selection_model = self.resources_tree_view.selectionModel()
        selected_indexes = [
            self.proxy_model.mapToSource(index)
            for index in selection_model.selectedIndexes()
        ]
        self.__download_indices(selected_indexes)

    def __download_indices(self, indices: List[QModelIndex]) -> None:
        allow_demo_project_resolve = True

        def save_command(job) -> None:
            insertion_point = self.iface.layerTreeInsertionPoint()
            self._queue_to_add.append(
                AddLayersCommand(
                    job.job_uuid,
                    insertion_point,
                    indices,
                    allow_demo_project_resolve,
                )
            )

        importer = self.__create_resource_batch_importer(
            indices,
            self.iface.layerTreeInsertionPoint(),
        )

        is_success, missing_ids = importer.missing_resources()
        if not is_success:
            return

        # Fetch group tree if group resource is selected
        job = self.resource_model.fetch_not_expanded(missing_ids)
        if job is not None:
            save_command(job)
            return

        # Fetch group tree if group resource is selected
        job = self.resource_model.fetch_missing(missing_ids)
        if job is not None:
            save_command(job)
            return

        resolution = DemoProjectSelectionResolver(self.resource_model).resolve(
            indices,
            allow_demo_project_resolve,
        )
        indices = list(resolution.indices)
        allow_demo_project_resolve = resolution.allow_demo_project_resolution
        importer = self.__create_resource_batch_importer(
            indices,
            self.iface.layerTreeInsertionPoint(),
        )

        is_success, missing_ids = importer.missing_resources()
        if not is_success:
            return

        job = self.resource_model.fetch_missing(missing_ids)
        if job is not None:
            save_command(job)
            return

        # Make stubs for vector layers
        model = self.resource_model
        download_job = model.download_vector_layers_if_needed(indices)
        if download_job is not None:
            save_command(download_job)
            return

        # Fetch styles
        is_success, styles_id = importer.missing_styles()
        if not is_success:
            return

        job = self.resource_model.fetch_missing_styles(styles_id)
        if job is not None:
            save_command(job)
            return

        plugin = NgConnectInterface.instance()
        plugin.disable_synchronization()

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        backup_point = self.iface.layerTreeInsertionPoint()

        job_id = "AddLayersStub"
        self.block_gui()
        self.__cancelable_job_ids.append(job_id)
        self.__active_resource_importer = importer
        self.resources_tree_view.addBlockedJob(
            self.blocked_jobs[job_id],
            cancel_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text=self.tr("Cancel"),
            ),
            compact_title=self.blocked_job_compact_titles[job_id],
        )
        QApplication.processEvents()

        try:
            result = importer.execute()
            if result.is_success:
                self.__select_qgis_layers(result.added_layer_ids)
        finally:
            self.unblock_gui()
            self.resources_tree_view.removeBlockedJob(
                self.blocked_jobs[job_id]
            )
            self.__remove_cancelable_job(job_id)
            if self.__active_resource_importer is importer:
                self.__active_resource_importer = None
            if self.__cancel_pending_job_id == job_id:
                self.__cancel_pending_job_id = None

            tree_rigistry_bridge.setLayerInsertionPoint(backup_point)
            plugin.enable_synchronization()

    @pyqtSlot()
    def create_group(self) -> None:
        proxy_index = self.resources_tree_view.selectionModel().currentIndex()
        sel_index = self.proxy_model.mapToSource(proxy_index)
        if sel_index is None or not sel_index.isValid():
            self.show_info(
                self.tr(
                    "Please select parent resource group for a new resource group"
                )
            )
            return

        new_group_name, ok = QInputDialog.getText(
            self,
            self.tr("Create resource group"),
            self.tr("Resource group name"),
            echo=QLineEdit.EchoMode.Normal,
            text=self.tr("New resource group"),
            flags=Qt.WindowType.Dialog,
        )
        if not ok or new_group_name == "":
            self.resource_model.refresh_lazy_children_state(sel_index)
            if proxy_index.isValid():
                self.resources_tree_view.setCurrentIndex(proxy_index)
            return

        self.create_group_resp = self.resource_model.tryCreateNGWGroup(
            new_group_name, sel_index
        )
        self.create_group_resp.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )

    @pyqtSlot()
    def create_vector_layer(self) -> None:
        parent_resource_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        parent_resource = parent_resource_index.data(
            QNGWResourceItem.NGWResourceRole
        )
        if not isinstance(parent_resource, NGWGroupResource):
            parent_resource_index = parent_resource_index.parent()
            parent_resource = parent_resource_index.data(
                QNGWResourceItem.NGWResourceRole
            )

        connection = parent_resource.connection

        self.__fetch_children_if_needed(parent_resource_index)
        dialog = VectorLayerCreationDialog(
            self.resource_model, parent_resource_index, self
        )
        if connection.has_support_for_feature(NgwServerFeature.BOOLEAN_TYPE):
            dialog.enable_boolean_field_type()
        if connection.has_support_for_feature(NgwServerFeature.JSON_TYPE):
            dialog.enable_json_field_type()
        if connection.has_support_for_feature(
            NgwServerFeature.NO_GEOMETRY_LAYERS
        ):
            dialog.enable_no_geometry_layer_type()

        def create_resource(resource):
            response = self.resource_model.createVectorLayer(
                parent_resource_index, resource
            )
            if response is None:
                return None

            self.create_vector_layer_responce = response

            response.done.connect(
                lambda index: self.resources_tree_view.setCurrentIndex(
                    self.proxy_model.mapFromSource(index)
                )
            )
            if dialog.add_to_project:
                response.done.connect(
                    lambda index: self.__download_indices([index])
                )

            return response

        dialog.set_create_resource_callback(create_resource)
        result = dialog.exec()
        if result != VectorLayerCreationDialog.DialogCode.Accepted:
            return

        if dialog.resource is None:
            return

    def upload_project_resources(self):
        """
        Upload whole project to NextGIS Web
        """

        def get_project_name():
            current_project = QgsProject.instance()
            if current_project.title() != "":
                return current_project.title()
            if current_project.fileName() != "":
                return current_project.baseName()
            return ""

        ngw_current_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        dialog = QgsNewNameDialog(
            initial=get_project_name(),
            # existing=existing_names,
            cs=Qt.CaseSensitivity.CaseSensitive,
            parent=self.iface.mainWindow(),
        )
        dialog.setWindowTitle(self.tr("Uploading parameters"))
        dialog.setOverwriteEnabled(False)
        dialog.setAllowEmptyName(False)
        dialog.setHintString(self.tr("Enter name for resource group"))
        # dialog.setConflictingNameWarning(self.tr('Resource already exists'))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        project_name = dialog.name()

        self.qgis_proj_import_response = (
            self.resource_model.uploadProjectResources(
                project_name,
                ngw_current_index,
                self.iface,
            )
        )
        self.qgis_proj_import_response.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )
        self.qgis_proj_import_response.done.connect(self.processWarnings)
        self.qgis_proj_import_response.done.connect(
            self.__replace_uploaded_layers_if_requested
        )
        self.qgis_proj_import_response.done.connect(self.open_create_web_map)

    def upload_selected_resources(self):
        ngw_current_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectedIndexes()[0]
        )

        qgs_layer_tree_nodes = self.iface.layerTreeView().selectedNodes(
            skipInternal=True
        )
        if (
            len(qgs_layer_tree_nodes) == 0
        ):  # could be if user had deleted layer but have not selected one after that
            current_node = self.iface.layerTreeView().currentNode()
            if current_node is None:
                self.show_error(self.tr("No layer selected"))
                return
            qgs_layer_tree_nodes = [current_node]

        qgs_layer_tree_nodes = [node.clone() for node in qgs_layer_tree_nodes]

        self.import_layer_response = self.resource_model.uploadResourcesList(
            qgs_layer_tree_nodes, ngw_current_index, self.iface
        )
        self.import_layer_response.select.connect(self.__select_list)
        self.import_layer_response.done.connect(self.processWarnings)
        self.import_layer_response.done.connect(
            self.__replace_uploaded_layers_if_requested
        )

    @pyqtSlot(QModelIndex)
    def __replace_uploaded_layers_if_requested(self, _index: QModelIndex):
        response = cast(NGWResourceModelResponse, self.sender())
        uploaded_layers = self.__replaceable_uploaded_layers(
            response.uploaded_layers
        )
        if len(uploaded_layers) == 0:
            return

        if not self.__confirm_uploaded_layers_replacement(uploaded_layers):
            return

        replaced_layers = []
        skipped_layers = []
        for uploaded_layer in uploaded_layers:
            qgs_layer = uploaded_layer.qgs_map_layer
            try:
                self.__replace_uploaded_layer_source(uploaded_layer)
            except Exception as error:
                logger.exception(
                    'Could not replace source for layer "%s"',
                    qgs_layer.name(),
                )
                if isinstance(error, NgConnectError):
                    message = error.user_message
                else:
                    message = self.tr("Source was not replaced")
                skipped_layers.append(f"{qgs_layer.name()}: {message}")
            else:
                replaced_layers.append(qgs_layer.name())

        if len(replaced_layers) > 0:
            self.__msg_in_qgis_mes_bar(
                self.tr(
                    "Local layer sources were replaced with Web GIS layers"
                ),
                duration=3,
            )

        if len(skipped_layers) > 0:
            self.show_info(
                self.tr("Some uploaded layers were not replaced:\n{}").format(
                    "\n".join(skipped_layers)
                ),
                self.tr("Replace local layers"),
            )

    def __replaceable_uploaded_layers(
        self, uploaded_layers: List[UploadedLayerResource]
    ) -> List[UploadedLayerResource]:
        project = QgsProject.instance()
        replaceable_layers = []
        for uploaded_layer in uploaded_layers:
            qgs_layer = uploaded_layer.qgs_map_layer
            ngw_resource = uploaded_layer.ngw_resource
            is_project_layer = project.mapLayer(qgs_layer.id()) is qgs_layer
            is_vector_layer = isinstance(
                qgs_layer, QgsVectorLayer
            ) and isinstance(ngw_resource, NGWVectorLayer)
            is_raster_layer = isinstance(
                qgs_layer, QgsRasterLayer
            ) and isinstance(ngw_resource, NGWRasterLayer)

            if not is_project_layer or (
                not is_vector_layer and not is_raster_layer
            ):
                continue

            replaceable_layers.append(uploaded_layer)

        return replaceable_layers

    def __confirm_uploaded_layers_replacement(
        self, uploaded_layers: List[UploadedLayerResource]
    ) -> bool:
        layer_names = [
            uploaded_layer.qgs_map_layer.name()
            for uploaded_layer in uploaded_layers[:5]
        ]
        if len(uploaded_layers) > len(layer_names):
            layer_names.append(
                self.tr("... and {} more").format(
                    len(uploaded_layers) - len(layer_names)
                )
            )

        message = self.tr(
            "Replace local layer sources with the uploaded Web GIS layers?"
        )
        if len(layer_names) > 0:
            message += "\n\n" + "\n".join(layer_names)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Replace local layers"))
        box.setText(message)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)

        return box.exec() == QMessageBox.StandardButton.Yes

    def __replace_uploaded_layer_source(
        self, uploaded_layer: UploadedLayerResource
    ) -> None:
        qgs_layer = uploaded_layer.qgs_map_layer
        ngw_resource = uploaded_layer.ngw_resource

        if isinstance(qgs_layer, QgsVectorLayer) and isinstance(
            ngw_resource, NGWVectorLayer
        ):
            self.__replace_uploaded_vector_layer_source(
                qgs_layer, ngw_resource
            )
            return

        if isinstance(qgs_layer, QgsRasterLayer) and isinstance(
            ngw_resource, NGWRasterLayer
        ):
            self.__replace_uploaded_raster_layer_source(
                qgs_layer, ngw_resource
            )
            return

        raise NgConnectError(
            "Layer and resource types are incompatible",
            user_message=self.tr("Layer and resource types are incompatible"),
            code=ErrorCode.InvalidResource,
        )

    def __replace_uploaded_vector_layer_source(
        self, qgs_layer: QgsVectorLayer, ngw_layer: NGWVectorLayer
    ) -> None:
        if qgs_layer.isEditable():
            raise NgConnectError(
                f'Layer "{qgs_layer.name()}" is in edit mode',
                user_message=self.tr(
                    "Layer is in edit mode. Save or discard edits first."
                ),
                code=ErrorCode.LayerEditError,
            )

        container_path = self.__detached_container_path(ngw_layer)
        connection = self.__ngw_connection(ngw_layer)
        if container_path.exists():
            if not is_detached_ngw_container(container_path):
                raise NgConnectError(
                    f"Detached container is invalid: {container_path}",
                    user_message=self.tr(
                        "Detached layer container is invalid"
                    ),
                    code=ErrorCode.ContainerIsInvalid,
                )
            if not CachedDetachedContainerLifecycle().reconcile(
                container_path,
                ngw_layer,
                connection,
            ):
                raise NgConnectError(
                    f"Detached container is incompatible: {container_path}",
                    user_message=self.tr(
                        "Detached layer container is invalid"
                    ),
                    code=ErrorCode.ContainerIsInvalid,
                )
        else:
            DetachedContainerFactory().create_initial_container(
                ngw_layer, container_path
            )
            DetachedStorageServiceFactory.create().register_detached_container(
                connection.domain_uuid,
                ngw_layer.resource_id,
                connection_id=connection.id,
                container_path=container_path,
            )

        source = detached_layer_uri(container_path)
        old_source, old_name, old_provider = self.__layer_source_info(
            qgs_layer
        )
        detached_editing = NgConnectInterface.instance().detached_editing
        was_detached = detached_editing.container(qgs_layer) is not None
        detached_editing.unregister_layer(qgs_layer)

        try:
            self.__set_layer_source(
                qgs_layer, source, ngw_layer.display_name, "ogr"
            )
            is_attached = detached_editing.setup_existing_layer(qgs_layer)
            if not is_attached:
                raise NgConnectError(
                    "Could not attach layer to detached editing",
                    user_message=self.tr(
                        "Layer was not attached to detached editing"
                    ),
                    code=ErrorCode.DetachedEditingError,
                )
        except Exception:
            self.__set_layer_source(
                qgs_layer, old_source, old_name, old_provider
            )
            if was_detached or is_detached_ngw_container(qgs_layer):
                detached_editing.setup_existing_layer(qgs_layer)
            raise

    def __replace_uploaded_raster_layer_source(
        self, qgs_layer: QgsRasterLayer, ngw_layer: NGWRasterLayer
    ) -> None:
        if not ngw_layer.is_cog:
            raise NgwError(code=ErrorCode.UnsupportedRasterType)

        connection = self.__ngw_connection(ngw_layer)
        if connection.method not in ("", "Basic"):
            raise NgConnectError(
                f"Raster layer {ngw_layer.resource_id} uses OAuth connection",
                user_message=self.tr(
                    "Currently adding raster layers is not available for OAuth "
                    "connections. Please use Basic authentication."
                ),
                code=ErrorCode.AddingError,
            )

        source, name, provider = ngw_layer.layer_params
        self.__set_layer_source(qgs_layer, source, name, provider)
        self.__set_ngw_layer_properties(qgs_layer, ngw_layer)

    def __detached_container_path(self, ngw_layer: NGWVectorLayer) -> Path:
        connection = self.__ngw_connection(ngw_layer)
        return DetachedStorageServiceFactory.create().container_path(
            connection.domain_uuid, ngw_layer.resource_id
        )

    def __ngw_connection(self, ngw_resource: NGWResource) -> NgwConnection:
        connection = NgwConnectionsManager().connection(
            ngw_resource.connection_id
        )
        if connection is None:
            raise NgConnectError(
                f"Connection {ngw_resource.connection_id} is not accessible",
                user_message=self.tr("Web GIS connection is not accessible"),
                code=ErrorCode.InvalidConnection,
            )
        return connection

    def __set_ngw_layer_properties(
        self, qgs_layer: QgsMapLayer, ngw_resource: NGWResource
    ) -> None:
        connection = self.__ngw_connection(ngw_resource)
        qgs_layer.setCustomProperty(
            "ngw_connection_id", ngw_resource.connection_id
        )
        qgs_layer.setCustomProperty("ngw_instance_id", connection.domain_uuid)
        qgs_layer.setCustomProperty(
            "ngw_resource_id", ngw_resource.resource_id
        )

    def __layer_source_info(self, qgs_layer: QgsMapLayer):
        return (qgs_layer.source(), qgs_layer.name(), qgs_layer.providerType())

    def __set_layer_source(
        self, qgs_layer: QgsMapLayer, source: str, name: str, provider: str
    ) -> None:
        old_source, old_name, old_provider = self.__layer_source_info(
            qgs_layer
        )
        qgs_layer.setDataSource(source, name, provider)
        qgs_layer.setName(name)
        if qgs_layer.isValid():
            return

        qgs_layer.setDataSource(old_source, old_name, old_provider)
        qgs_layer.setName(old_name)
        raise NgConnectError(
            "QGIS layer is invalid after source replacement",
            user_message=self.tr("Layer source was not replaced"),
            code=ErrorCode.AddingError,
        )

    def overwrite_ngw_layer(self):
        index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)

        if not self.__confirm_resource_overwrite(
            str(index.data(Qt.ItemDataRole.DisplayRole)),
            qgs_map_layer.name(),
            isinstance(ngw_resource, NGWVectorLayer)
            and ngw_resource.is_versioning_enabled,
        ):
            return

        if isinstance(qgs_map_layer, QgsVectorLayer):
            self.resource_model.updateNGWVectorLayer(index, qgs_map_layer)

        if isinstance(qgs_map_layer, QgsRasterLayer):
            self.resource_model.updateNGWRasterLayer(index, qgs_map_layer)

    def __confirm_resource_overwrite(
        self,
        resource_name: str,
        qgis_layer_name: str,
        is_versioning_enabled: bool,
    ) -> bool:
        message = self.tr(
            'Resource "{}" will be overwritten with QGIS layer "{}". '
            "Current data will be lost.<br/>Are you sure you want to "
            "overwrite it?"
        )
        if is_versioning_enabled:
            message = self.tr(
                'Resource "{}" will be overwritten with QGIS layer "{}". '
                "Current data and layer history will be lost.<br/><br/>"
                "Are you ready to lose the layer history and overwrite it?"
            )

        box = QMessageBox(self)
        box.setIcon(
            QMessageBox.Icon.Warning
            if is_versioning_enabled
            else QMessageBox.Icon.Question
        )
        box.setWindowTitle(self.tr("Overwrite resource"))
        box.setText(
            message.format(
                html.escape(resource_name),
                html.escape(qgis_layer_name),
            )
        )
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)

        confirm_button = box.button(QMessageBox.StandardButton.Yes)
        assert confirm_button is not None
        confirm_button.setText(self.tr("Overwrite"))

        if is_versioning_enabled:
            self.__start_overwrite_confirmation_countdown(confirm_button, box)

        return box.exec() == QMessageBox.StandardButton.Yes

    def __start_overwrite_confirmation_countdown(
        self,
        confirm_button: QAbstractButton,
        box: QMessageBox,
    ) -> None:
        seconds_left = 5
        confirm_text = self.tr("Overwrite")

        def update_button_text() -> None:
            confirm_button.setText(f"{confirm_text} {seconds_left}")

        def tick() -> None:
            nonlocal seconds_left
            seconds_left -= 1
            if seconds_left <= 0:
                timer.stop()
                confirm_button.setText(confirm_text)
                confirm_button.setEnabled(True)
                return

            update_button_text()

        confirm_button.setEnabled(False)
        update_button_text()

        timer = QTimer(box)
        timer.setInterval(1000)
        timer.timeout.connect(tick)
        timer.start()

    def edit_metadata(self):
        """Edit metadata table"""
        sel_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            self.block_gui()
            self.resources_tree_view.begin_loading(
                self.tr("Loading metadata"),
                message=ngw_resource.display_name,
            )

            try:
                ngw_resource.update()

                dlg = MetadataDialog(ngw_resource, self)
                dlg.exec()

            except NGWError as error:
                ng_error = NgwError()
                ng_error.__cause__ = error
                NgConnectInterface.instance().notifier.display_exception(
                    ng_error
                )

            except NgConnectError as error:
                NgConnectInterface.instance().notifier.display_exception(error)

            except Exception as error:
                ng_error = NgConnectError()
                ng_error.__cause__ = error
                NgConnectInterface.instance().notifier.display_exception(
                    ng_error
                )

            finally:
                self.resources_tree_view.end_loading()

            self.unblock_gui()

    def update_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()

        def update_style_for_index(style_index: QModelIndex) -> None:
            response = self.resource_model.updateQGISStyle(
                qgs_map_layer, style_index
            )
            response.done.connect(
                lambda index: self.resources_tree_view.setCurrentIndex(
                    self.proxy_model.mapFromSource(index)
                )
            )

        ngw_resource_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        resource = ngw_resource_index.data(QNGWResourceItem.NGWResourceRole)
        if isinstance(resource, (NGWQGISVectorStyle, NGWQGISRasterStyle)):
            update_style_for_index(ngw_resource_index)
            return

        self.__fetch_children_if_needed(ngw_resource_index)

        style_indices = []
        for row in range(self.resource_model.rowCount(ngw_resource_index)):
            child_index = self.resource_model.index(row, 0, ngw_resource_index)
            child = child_index.data(QNGWResourceItem.NGWResourceRole)
            if isinstance(child, NGWQGISStyle):
                style_indices.append(child_index)

        styles_count = len(style_indices)

        if styles_count == 0:
            self.add_style()

        elif styles_count == 1:
            update_style_for_index(style_indices[0])

        else:
            dlg = NGWLayerStyleChooserDialog(
                self.tr("Choose style"),
                ngw_resource_index,
                self.resource_model,
                self,
            )
            result = dlg.exec()
            if result != QDialog.DialogCode.Accepted:
                return

            style_index = dlg.selectedStyleIndex()
            assert style_index is not None
            update_style_for_index(style_index)

    def add_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        ngw_layer_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        response = self.resource_model.addQGISStyle(
            qgs_map_layer, ngw_layer_index
        )
        response.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )

    def delete_current_ngw_resource(self):
        selection_model = self.resources_tree_view.selectionModel()
        selected_indexes = [
            self.proxy_model.mapToSource(index)
            for index in selection_model.selectedIndexes()
        ]
        selected_indexes = [
            index for index in selected_indexes if index.isValid()
        ]
        if len(selected_indexes) == 0:
            return

        confirmation_dialog = ResourceDeleteConfirmationDialog(
            self.resource_model,
            selected_indexes,
            self,
        )
        if confirmation_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if len(selected_indexes) == 1:
            delete_resource_response = self.resource_model.deleteResource(
                selected_indexes[0]
            )
        else:
            delete_resource_response = self.resource_model.deleteResources(
                selected_indexes
            )

        if delete_resource_response is None:
            return

        self.delete_resource_response = delete_resource_response
        self.delete_resource_response.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )

    def _downloadRasterSource(
        self, ngw_lyr: NGWRasterLayer, raster_file: Optional[QFile] = None
    ) -> QFile:
        """
        Download raster layer source file from NextGIS Web using QNetworkAccessManager.

        The file is downloaded and written in chunks using the readyRead signal.
        If raster_file is not provided, a temporary file will be created.

        :param ngw_lyr: NGWRasterLayer instance to download.
        :param raster_file: Optional QFile or QTemporaryFile to write data to.

        :return: QFile object containing the downloaded raster data.
        """
        if not raster_file:
            raster_file = QTemporaryFile()
        else:
            raster_file = QFile(raster_file)

        url = f"{ngw_lyr.get_absolute_api_url()}/download"

        def write_chuck():
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(
                    "{} {}".format(
                        self.tr("Failed to download raster source:"),
                        reply.errorString(),
                    )
                )
            data = reply.readAll()
            logger.debug(f"Write chunk! Size: {data.size()}")
            raster_file.write(data)

        req = QNetworkRequest(QUrl(url))

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(ngw_lyr.connection_id)
        assert connection is not None
        connection.update_network_request(req)

        if raster_file.open(QIODevice.OpenModeFlag.WriteOnly):
            ev_loop = QEventLoop()
            dwn_qml_manager = QgsNetworkAccessManager()

            # dwn_qml_manager.finished.connect(ev_loop.quit)
            reply = dwn_qml_manager.get(req)

            reply.readyRead.connect(write_chuck)
            reply.finished.connect(ev_loop.quit)

            ev_loop.exec()

            write_chuck()
            raster_file.close()
            reply.deleteLater()

            return raster_file

        raise Exception(self.tr("Can't open file to write raster!"))

    def _copy_resource(self, ngw_src):
        """Create a copy of a ngw raster or vector layer
        1) Download ngw layer sources
        2) Create QGIS hidden layer
        3) Export layer to ngw
        4) Add styles to new ngw layer
        """

        def qml_callback(total_size, readed_size):
            logger.debug(
                self.tr('Style for "{}" - Upload ({}%)').format(
                    ngw_src.display_name, readed_size * 100 / total_size
                )
            )

        style_resource = None

        ngw_group = ngw_src.get_parent()
        child_resources = ngw_src.get_children()
        style_resources = []
        # assume that there can be only a style of appropriate for the layer type
        for child_resource in child_resources:
            if (
                child_resource.type_id == NGWQGISVectorStyle.type_id
                or child_resource.type_id == NGWQGISRasterStyle.type_id
            ):
                style_resources.append(child_resource)

        # Download sources and create a QGIS layer
        if ngw_src.type_id == NGWVectorLayer.type_id:
            resource_id = ngw_src.resource_id
            export_params = {
                "format": "GPKG",
                "fid": "",
                "zipped": "false",
            }
            export_url = (
                f"/api/resource/{resource_id}/export?"
                + urllib.parse.urlencode(export_params)
            )

            temp_fd, temp_path_str = tempfile.mkstemp(suffix=".gpkg")
            os.close(temp_fd)
            temp_path = Path(temp_path_str)

            ngw_connection = QgsNgwConnection(ngw_src.connection_id)
            ngw_connection.download(export_url, str(temp_path))

            qgs_layer = QgsVectorLayer(
                str(temp_path),
                ngw_src.display_name,
                "ogr",
            )
            if not qgs_layer.isValid():
                raise Exception(
                    f'Layer "{ngw_src.display_name}" can\'t be added to the map!'
                )
            qgs_layer.dataProvider().setEncoding("UTF-8")

        elif ngw_src.type_id == NGWRasterLayer.type_id:
            raster_file = self._downloadRasterSource(ngw_src)
            qgs_layer = QgsRasterLayer(
                raster_file.fileName(), ngw_src.display_name, "gdal"
            )
            if not qgs_layer.isValid():
                logger.error("Failed to add raster layer to QGIS")
                raise Exception(
                    f'Layer "{ngw_src.display_name}" can\'t be added to the map!'
                )
        else:
            raise Exception(f"Wrong layer type! Type id: {ngw_src.type_id}")

        # Export QGIS layer to NGW
        resJob = QGISResourceJob()
        ngw_res = resJob.importQGISMapLayer(qgs_layer, ngw_group)[0]

        # Remove temp layer and sources

        del qgs_layer
        if ngw_src.type_id == NGWVectorLayer.type_id:
            try:
                temp_path.unlink()
            except Exception as error:
                logger.exception(
                    "Failed to remove temporary GPKG %s: %s",
                    temp_path,
                    error,
                )
        if ngw_src.type_id == NGWRasterLayer.type_id:
            raster_file.remove()

        # Export styles to new NGW layer
        for style_resource in style_resources:
            self._downloadStyleAsQML(style_resource, mes_bar=False)

            ngw_res.create_qml_style(
                self.dwn_qml_file.fileName(),
                qml_callback,
                style_name=style_resource.display_name,
            )
            self.dwn_qml_file.remove()
            ngw_res.update()

        return ngw_res

    def duplicate_current_ngw_resource(self):
        """Copying the selected ngw resource.
        Only GUI stuff here, main part
        in _copy_resource function
        """
        sel_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if sel_index.isValid():
            # ckeckbox
            res = QMessageBox.question(
                self,
                self.tr("Duplicate Resource"),
                self.tr("Are you sure you want to duplicate this resource?"),
                QMessageBox.StandardButton.Yes
                and QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if res == QMessageBox.StandardButton.No:
                return

            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            # block gui
            self.block_gui()
            self.resources_tree_view.begin_loading(
                self.tr("Duplicating resource"),
                message=ngw_resource.display_name,
            )
            # main part
            try:
                ngw_result = self._copy_resource(ngw_resource)
                self.__add_resource_to_tree(ngw_result)
            except NgConnectError as error:
                NgConnectInterface.instance().notifier.display_exception(error)
            except Exception as ex:
                error_mes = str(ex)
                self.iface.messageBar().pushMessage(
                    self.tr("Error"),
                    error_mes,
                    level=Qgis.MessageLevel.Critical,
                )
                logger.exception(error_mes)

            finally:
                self.resources_tree_view.end_loading()
                self.unblock_gui()

    def create_wfs_or_ogcf_service(self, service_type: str):
        assert service_type in ("WFS", "OGC API - Features")
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        if not selected_index.isValid():
            selected_index = self.index(0, 0, selected_index)

        item = selected_index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        if service_type == "WFS" and ngw_resource.is_geom_with_z():
            self.show_error(
                self.tr(
                    "You are trying to create a WFS service "
                    "for a layer that contains Z geometries. "
                    "WFS in QGIS doesn't fully support editing such geometries. "
                    "To fix this, change geometry type of your layer to non-Z "
                    "and create a WFS service again."
                )
            )
            return

        max_features, res = QInputDialog.getInt(
            self,
            self.tr("Create ") + service_type,
            self.tr("The number of objects returned by default"),
            1000,
            0,
            2147483647,
        )
        if res is False:
            return

        response = self.resource_model.createWfsOrOgcfForVector(
            service_type, selected_index, max_features
        )
        response.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )
        response.done.connect(self.__add_created_service)

    @pyqtSlot(QModelIndex)
    def __add_created_service(self, index: QModelIndex):
        if not NgConnectSettings().add_layer_after_service_creation:
            return

        self.__download_indices([index])

    def __fetch_children_if_needed(self, index: QModelIndex):
        if not self.resource_model.canFetchMore(index):
            return

        resource = index.data(QNGWResourceItem.NGWResourceRole)
        children = resource.get_children()
        for child in children:
            self.resource_model.addNGWResourceToTree(index, child)

    def create_wms_service(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        self.__fetch_children_if_needed(selected_index)

        style_resources = []

        selected_resource = selected_index.data(
            QNGWResourceItem.NGWResourceRole
        )
        if isinstance(selected_resource, NGWQGISStyle):
            selected_index = selected_index.parent()
            style_resources = [selected_resource]
        else:
            for row in range(self.resource_model.rowCount(selected_index)):
                child_index = self.resource_model.index(row, 0, selected_index)
                child = child_index.data(QNGWResourceItem.NGWResourceRole)
                if isinstance(child, NGWQGISStyle):
                    style_resources.append(child)

        if len(style_resources) == 1:
            ngw_resource_style_id = style_resources[0].resource_id
        else:
            dlg = NGWLayerStyleChooserDialog(
                self.tr("Create WMS service for layer"),
                selected_index,
                self.resource_model,
                self,
            )
            result = dlg.exec()
            if result != QDialog.DialogCode.Accepted:
                return
            ngw_resource_style_id = dlg.selectedStyleId()

        responce = self.resource_model.createWMSService(
            selected_index, ngw_resource_style_id
        )
        responce.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )
        responce.done.connect(self.__add_created_service)

    def create_web_map_for_style(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        self.create_map_response = self.resource_model.createMapForStyle(
            selected_index
        )

        self.create_map_response.done.connect(self.open_create_web_map)

    def create_web_map_for_layer(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )

        ngw_resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        if ngw_resource.type_id in [
            NGWVectorLayer.type_id,
            NGWRasterLayer.type_id,
        ]:
            ngw_styles = self.__layer_style_children(ngw_resource)
            ngw_resource_style_id = None

            if len(ngw_styles) == 0:
                if not self.__confirm_create_default_style_for_web_map(
                    ngw_resource.display_name
                ):
                    return
            elif len(ngw_styles) == 1:
                ngw_resource_style_id = ngw_styles[0].resource_id
            elif len(ngw_styles) > 1:
                dlg = NGWLayerStyleChooserDialog(
                    self.tr("Create Web map for layer"),
                    selected_index,
                    self.resource_model,
                    self,
                )
                result = dlg.exec()
                if result:
                    if dlg.selectedStyleId():
                        ngw_resource_style_id = dlg.selectedStyleId()
                else:
                    return  # do nothing after closing the dialog

            self.create_map_response = self.resource_model.createMapForLayer(
                selected_index, ngw_resource_style_id
            )

        elif ngw_resource.type_id == NGWWmsLayer.type_id:
            self.create_map_response = self.resource_model.createMapForLayer(
                selected_index, None
            )

        self.create_map_response.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )
        self.create_map_response.done.connect(self.open_create_web_map)

    def __layer_style_children(
        self,
        ngw_resource: NGWResource,
    ) -> List[NGWResource]:
        return [
            child
            for child in ngw_resource.get_children()
            if isinstance(
                child,
                (
                    NGWQGISStyle,
                    NGWRasterStyle,
                    NGWMapServerStyle,
                ),
            )
        ]

    def __confirm_create_default_style_for_web_map(
        self,
        layer_name: str,
    ) -> bool:
        message = self.tr(
            'Layer "{layer_name}" has no styles.\n'
            "Create a default style and continue creating the Web map?"
        ).format(layer_name=layer_name)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Create Web map for layer"))
        box.setText(message)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)

        confirm_button = box.button(QMessageBox.StandardButton.Yes)
        assert confirm_button is not None
        confirm_button.setText(self.tr("Create default style"))

        return box.exec() == QMessageBox.StandardButton.Yes

    def open_create_web_map(self, index: QModelIndex):
        if (
            not index.isValid()
            or not NgConnectSettings().open_web_map_after_creation
        ):
            return

        ngw_resource: NGWResource = index.data(
            QNGWResourceItem.NGWResourceRole
        )
        url = ngw_resource.preview_url
        QDesktopServices.openUrl(QUrl(url))

    def processWarnings(self, index):
        ngw_model_job_resp = cast(NGWResourceModelResponse, self.sender())
        if len(ngw_model_job_resp.warnings) == 0:
            return

        dlg = ExceptionsListDialog(
            self.tr("NextGIS Connect operation errors"), self
        )
        for w in ngw_model_job_resp.warnings:
            (
                w_msg,
                w_msg_ext,
                icon,
            ) = self.__get_model_exception_description(w)
            dlg.addException(w_msg, w_msg_ext, icon)
            dlg.show()

    def _downloadStyleAsQML(
        self, ngw_style: NGWQGISStyle, path=None, mes_bar=True
    ):
        if not path:
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".qml", delete=False
            )
            path = temp_file.name
            temp_file.close()

        url = ngw_style.download_qml_url()
        result = False
        try:
            ngw_style.connection.download(url, path)
            logger.debug(f"Downloaded QML file path: {path}")
            result = True
        except Exception:
            logger.exception("Failed to download QML")

        if mes_bar:
            if result:
                self.__msg_in_qgis_mes_bar(
                    self.tr("QML file downloaded"), duration=2
                )
            else:
                error = NgConnectError(
                    user_message=self.tr("QML file could not be downloaded")
                )
                NgConnectInterface.instance().notifier.display_exception(error)

        self.dwn_qml_file = QFile(path)
        return result

    def download_qml(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        ngw_qgis_style = selected_index.data(QNGWResourceItem.NGWResourceRole)

        settings = QgsSettings()
        last_used_dir = settings.value("style/lastStyleDir", QDir.homePath())
        style_name = ngw_qgis_style.display_name
        path_to_qml = os.path.join(last_used_dir, f"{style_name}.qml")
        filepath, _selected_filter = QFileDialog.getSaveFileName(
            self,
            caption=self.tr("Save QML"),
            directory=path_to_qml,
            filter=self.tr("QGIS Layer Style File") + "(*.qml)",
        )

        if filepath == "":
            return

        filepath = QgsFileUtils.ensureFileNameHasExtension(filepath, ["qml"])

        is_success = self._downloadStyleAsQML(ngw_qgis_style, path=filepath)
        if is_success:
            settings.setValue(
                "style/lastStyleDir", QFileInfo(filepath).absolutePath()
            )

    def download_ngfp(self) -> None:
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if not selected_index.isValid():
            return

        ngw_form = selected_index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(ngw_form, NGWResource):
            return

        if getattr(ngw_form.common, "cls", None) != "formbuilder_form":
            return

        settings = QgsSettings()
        last_used_dir = settings.value("form/lastNgfpDir", QDir.homePath())
        form_name = ngw_form.display_name
        path_to_ngfp = os.path.join(last_used_dir, f"{form_name}.ngfp")
        filepath, _selected_filter = QFileDialog.getSaveFileName(
            self,
            caption=self.tr("Save NGFP"),
            directory=path_to_ngfp,
            filter=self.tr("NextGIS Form Package") + "(*.ngfp)",
        )
        if filepath == "":
            return

        filepath = QgsFileUtils.ensureFileNameHasExtension(
            filepath,
            ["ngfp"],
        )
        try:
            ngw_form.connection.download(
                f"{ngw_form.get_relative_api_url()}/ngfp",
                filepath,
            )
        except Exception:
            logger.exception("Failed to download NGFP")
            error = NgConnectError(
                user_message=self.tr("NGFP file could not be downloaded")
            )
            NgConnectInterface.instance().notifier.display_exception(error)
            return

        settings.setValue(
            "form/lastNgfpDir",
            QFileInfo(filepath).absolutePath(),
        )
        self.__msg_in_qgis_mes_bar(
            self.tr("NGFP file downloaded"),
            duration=2,
        )

    def copy_style(self):
        # Download style
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        ngw_qgis_style = selected_index.data(QNGWResourceItem.NGWResourceRole)
        self._downloadStyleAsQML(ngw_qgis_style, mes_bar=False)

        # Set style to dom
        dom_document = QDomDocument()
        error_message = ""
        if self.dwn_qml_file.open(QFile.OpenModeFlag.ReadOnly):
            is_success, error_message, line, column = dom_document.setContent(
                self.dwn_qml_file
            )
            if error_message is None:
                error_message = ""

            self.dwn_qml_file.close()

            if not is_success:
                error_message = self.tr(
                    f"{error_message} at line {line} column {column}"
                )

        if len(error_message) != 0:
            user_message = self.tr("An error occurred when copying the style")
            error = NgConnectError(user_message=user_message)
            error.add_note(error_message)
            NgConnectInterface.instance().notifier.display_exception(error)
            return

        # Copy style
        QGSCLIPBOARD_STYLE_MIME = "application/qgis.style"
        data = dom_document.toByteArray()
        text = dom_document.toString()
        Clipboard().set_data(QGSCLIPBOARD_STYLE_MIME, data, text)

    def show_msg_box(
        self,
        text: str,
        title: str,
        icon: QMessageBox.Icon,
        buttons: QMessageBox.StandardButtons,
    ) -> int:
        box = QMessageBox()
        box.setText(text)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setStandardButtons(buttons)
        return box.exec()

    def show_info(self, text: str, title: Optional[str] = None):
        if title is None:
            title = self.tr("Information")
        self.show_msg_box(
            text,
            title,
            QMessageBox.Icon.Information,
            QMessageBox.StandardButton.Ok,
        )

    def show_error(self, text: str, title: Optional[str] = None):
        if title is None:
            title = self.tr("Error")
        self.show_msg_box(
            text,
            title,
            QMessageBox.Icon.Critical,
            QMessageBox.StandardButton.Ok,
        )

    def __resume_pending_resource_imports(self, job_uuid: str) -> None:
        commands = [
            command
            for command in self.__pending_resource_imports
            if command.job_uuid == job_uuid
        ]
        if len(commands) == 0:
            return

        self.__pending_resource_imports = [
            command
            for command in self.__pending_resource_imports
            if command.job_uuid != job_uuid
        ]
        for command in commands:
            self.__continue_direct_resource_import(
                command.resource_id,
                command.action_id,
                command.target,
            )

    def __add_layers_after_finish(self, job_uuid: str):
        found_i = -1
        for i, command in enumerate(self._queue_to_add):
            if command.job_uuid == job_uuid:
                found_i = i
                break

        if found_i == -1:
            return

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        model = self.resource_model
        command = self._queue_to_add[found_i]

        del self._queue_to_add[found_i]

        importer = self.__create_resource_batch_importer(
            command.ngw_indexes,
            command.insertion_point,
        )

        is_success, missing_ids = importer.missing_resources()
        if not is_success:
            return

        # Fetch group tree if group resource is selected
        job = self.resource_model.fetch_not_expanded(missing_ids)
        if job is not None:
            command.job_uuid = job.job_uuid
            self._queue_to_add.append(command)
            return

        # Fetch group tree if group resource is selected
        job = self.resource_model.fetch_missing(missing_ids)
        if job is not None:
            command.job_uuid = job.job_uuid
            self._queue_to_add.append(command)
            return

        resolution = DemoProjectSelectionResolver(self.resource_model).resolve(
            command.ngw_indexes,
            command.allow_demo_project_resolve,
        )
        command.ngw_indexes = list(resolution.indices)
        command.allow_demo_project_resolve = (
            resolution.allow_demo_project_resolution
        )
        importer = self.__create_resource_batch_importer(
            command.ngw_indexes,
            command.insertion_point,
        )

        is_success, missing_ids = importer.missing_resources()
        if not is_success:
            return

        job = self.resource_model.fetch_missing(missing_ids)
        if job is not None:
            command.job_uuid = job.job_uuid
            self._queue_to_add.append(command)
            return

        download_job = model.download_vector_layers_if_needed(
            command.ngw_indexes
        )
        if download_job is not None:
            command.job_uuid = download_job.job_uuid
            self._queue_to_add.append(command)
            return

        # Fetch styles
        is_success, styles_id = importer.missing_styles()
        if not is_success:
            return
        job = self.resource_model.fetch_missing_styles(styles_id)
        if job is not None:
            command.job_uuid = job.job_uuid
            self._queue_to_add.append(command)
            return

        plugin = NgConnectInterface.instance()
        plugin.disable_synchronization()

        backup_point = self.iface.layerTreeInsertionPoint()

        job_id = "AddLayersStub"
        self.block_gui()
        self.__cancelable_job_ids.append(job_id)
        self.__active_resource_importer = importer
        self.resources_tree_view.addBlockedJob(
            self.blocked_jobs[job_id],
            cancel_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text=self.tr("Cancel"),
            ),
            compact_title=self.blocked_job_compact_titles[job_id],
        )
        QApplication.processEvents()

        try:
            result = importer.execute()
            if result.is_success:
                self.__select_qgis_layers(result.added_layer_ids)
        finally:
            self.unblock_gui()
            self.resources_tree_view.removeBlockedJob(
                self.blocked_jobs[job_id]
            )
            self.__remove_cancelable_job(job_id)
            if self.__active_resource_importer is importer:
                self.__active_resource_importer = None
            if self.__cancel_pending_job_id == job_id:
                self.__cancel_pending_job_id = None

            tree_rigistry_bridge.setLayerInsertionPoint(backup_point)
            plugin.enable_synchronization()

    def __on_ngstd_user_info_updated(self):
        connections_manager = NgwConnectionsManager()
        current_connection = connections_manager.current_connection
        if (
            current_connection is None
            or current_connection.method != "NextGIS"
        ):
            return

        self.reinit_tree(force=True)

    def __create_search_action(self) -> None:
        menu = QMenu()

        search_type_group = QActionGroup(menu)
        search_type_group.setExclusive(True)

        separator = menu.addSeparator()
        separator.setText(self.tr("Search type"))

        settings = SearchSettings()
        last_type = settings.last_used_type

        by_name_action = menu.addAction(self.tr("By name"))
        search_type_group.addAction(by_name_action)
        by_name_action.setData(SearchType.ByDisplayName)
        by_name_action.setCheckable(True)
        by_name_action.setChecked(last_type == SearchType.ByDisplayName)
        by_name_action.triggered.connect(self.__on_search_type_changed)

        by_metadata_action = menu.addAction(self.tr("By metadata"))
        search_type_group.addAction(by_metadata_action)
        by_metadata_action.setData(SearchType.ByMetadata)
        by_metadata_action.setCheckable(True)
        by_metadata_action.setChecked(last_type == SearchType.ByMetadata)
        by_metadata_action.triggered.connect(self.__on_search_type_changed)

        self.search_action = QAction(
            plugin_icon("actions/filter.svg"),
            self.tr("Search"),
            self,
        )
        self.search_action.setToolTip(
            self.tr("Show resource search by name or metadata")
        )
        self.search_action.setCheckable(True)
        self.search_action.triggered.connect(self.__toggle_filter)

        self.__search_menu = menu

    def __update_search_action(self) -> None:
        has_new_search_api = (
            self.resource_model.ngw_version is not None
            and parse_version(self.resource_model.ngw_version)
            >= parse_version("5.0.0.dev13")
        )

        if has_new_search_api:
            self.search_action.setMenu(self.__search_menu)
        else:
            self.__search_menu.actions()[1].setChecked(True)
            self.search_panel.set_type(SearchType.ByDisplayName)
            self.search_action.setMenu(None)

    def __create_resource_creation_action(self) -> None:
        menu = self.__resource_menu_controller.create_resource_creation_menu()
        default_action = self.resource_creation_action(
            ResourceMenuAction.CREATE_GROUP
        )
        self.creation_action = QAction(
            default_action.icon(),
            default_action.text(),
            self,
        )
        self.creation_action.setToolTip(default_action.toolTip())
        self.creation_action.setMenu(menu)
        self.creation_action.triggered.connect(default_action.trigger)

    @pyqtSlot(str)
    def __on_search_requested(self, search_string: str) -> None:
        if len(search_string) == 0:
            self.__on_search_reset()
            return

        connections_manager = NgwConnectionsManager()
        search_connection_target = (
            self.__search_connection_target_resolver.resolve(
                search_string,
                connections_manager.current_connection,
                connections_manager.connections,
            )
        )
        if search_connection_target is not None:
            self.__show_search_connection_target(
                search_string,
                search_connection_target,
            )
            return

        self.__start_search(search_string)

    @pyqtSlot()
    def __on_search_reset(self) -> None:
        self.resource_model.reset_search()
        self.resources_tree_view.set_search_empty(False)
        self.__clear_search_connection_target()

    def __start_search(self, search_string: str) -> None:
        self.__clear_search_connection_target()
        self.resources_tree_view.set_search_empty(False)
        self.resource_model.search(search_string)

    def __show_search_connection_target(
        self,
        search_string: str,
        search_connection_target: SearchConnectionTarget,
    ) -> None:
        self.resource_model.reset_search()
        self.__pending_search_string = search_string
        self.__search_connection_target = search_connection_target

        connection = search_connection_target.connection
        self.resources_tree_view.set_search_connection_target(
            exists=connection is not None,
            url=search_connection_target.url,
            name="" if connection is None else connection.name,
        )

    def __clear_search_connection_target(self) -> None:
        self.__pending_search_string = ""
        self.__search_connection_target = None
        self.resources_tree_view.clear_search_connection_target()

    def __switch_to_search_connection_target(self) -> None:
        search_connection_target = self.__search_connection_target
        if (
            search_connection_target is None
            or search_connection_target.connection is None
        ):
            return

        self.__activate_search_connection(search_connection_target.connection)

    def __create_search_connection_target(self) -> None:
        search_connection_target = self.__search_connection_target
        if search_connection_target is None:
            return

        dialog = NgwConnectionEditDialog(self)
        dialog.set_url(search_connection_target.url)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.__activate_search_connection(dialog.connection())

    def __activate_search_connection(self, connection: NgwConnection) -> None:
        search_string = self.__pending_search_string
        connections_manager = NgwConnectionsManager()
        connections_manager.current_connection_id = connection.id
        connections_manager.save()
        self.search_panel.set_connection_id(connection.id)

        self.reinit_tree(force=True)
        if not self.resource_model.is_connected:
            self.__hide_search_after_connection_problem()
            return

        self.__clear_search_connection_target()
        if len(search_string) > 0:
            self.__start_search(
                self.__search_string_for_connection(search_string, connection)
            )

    def __search_string_for_connection(
        self,
        search_string: str,
        connection: NgwConnection,
    ) -> str:
        resource_id = self.__search_resource_url_parser.resource_id(
            search_string,
            connection,
        )
        if resource_id is None:
            return search_string

        return f"@id = {resource_id}"

    def __hide_search_after_connection_problem(self) -> None:
        self.resource_model.reset_search()
        self.resources_tree_view.set_search_empty(False)
        self.__clear_search_connection_target()
        self.search_action.setChecked(False)
        self.search_panel.setVisible(False)

    @pyqtSlot(bool)
    def __on_search_type_changed(self, value: bool) -> None:
        if not value:
            return

        action = cast(QAction, self.sender())
        self.search_panel.set_type(action.data())
        self.search_panel.show()
        self.search_panel.focus()
        self.search_action.setChecked(True)

    @pyqtSlot()
    def show_properties_dialog(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if not selected_index.isValid():
            return

        resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        dialog = ResourcePropertiesDialog(resource)
        dialog.exec()

    @pyqtSlot(list)
    def __select_list(self, indexes: List[QModelIndex]) -> None:
        selection = QItemSelection()
        for index in indexes:
            proxy_index = self.proxy_model.mapFromSource(index)
            self.resources_tree_view.expand(proxy_index.parent())
            selection.select(proxy_index, proxy_index)

        self.resources_tree_view.selectionModel().clear()
        self.resources_tree_view.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.SelectCurrent
        )

    def __add_banner(self) -> None:
        black_friday_start = datetime(
            year=2025, month=12, day=1, hour=6, minute=1, tzinfo=timezone.utc
        ).timestamp()
        black_friday_finish = datetime(
            year=2025, month=12, day=6, hour=5, minute=59, tzinfo=timezone.utc
        ).timestamp()
        black_friday_tag = "black-friday25"
        nextgis_domain = utils.nextgis_domain()
        lang_page = "en" if nextgis_domain.endswith("com") else "ru"
        promo_base_url = f"{nextgis_domain}/black-friday-2025/{lang_page}/"
        promo_campaign = black_friday_tag

        promo_text = self.tr("<b>50% off</b> all subscriptions and data")

        now = datetime.now().timestamp()

        settings = NgConnectSettings()

        is_black_friday = black_friday_start <= now <= black_friday_finish
        if not is_black_friday or settings.is_promo_dismissed(
            black_friday_tag
        ):
            return

        utm_template = "&".join(
            [
                "utm_source=qgis_plugin",
                "utm_medium=banner",
                f"utm_campaign={promo_campaign}",
                f"utm_term={PACKAGE_NAME}",
                f"utm_content={utils.locale()}",
            ]
        )
        promo_url = f"{promo_base_url}?{utm_template}"

        banner_container = QFrame(self.content)
        banner_container.setFrameShape(QFrame.Shape.NoFrame)
        banner_layout = QVBoxLayout(banner_container)
        banner_layout.setContentsMargins(0, 4, 0, 4)

        banner = QFrame(banner_container)
        banner.setObjectName("NgConnectBanner")
        banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner.setFrameShadow(QFrame.Shadow.Raised)

        banner.setLayout(QHBoxLayout())
        banner.layout().setContentsMargins(6, 6, 6, 6)

        banner_label = QLabel(banner)
        banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = plugin_icon_file_path("promo/fire.png")
        close_icon = icon_to_base64(material_icon("close_small", size=16))

        html = f"""
            <html>
            <head>
            </head>
            <body>
                <table width="100%">
                    <tr>
                        <td style="text-align: right">
                            <img src="{icon_path}">
                        </td>
                        <td width="1%" style="text-align: center;">
                            &nbsp;<a href="#open">{promo_text}</a>
                        </td>
                        <td style="text-align: right;" valign="middle">
                            <a href="#close"><img src="{close_icon}"></a>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
        """
        banner_label.setText(html)

        banner.layout().addWidget(banner_label)
        banner_layout.addWidget(banner)

        self.__promo_banner_container = banner_container
        self.content.layout().addWidget(banner_container)
        self.__update_promo_banner_visibility()

        def open_link(url: str) -> None:
            if url == "#close":
                self.__promo_banner_container = None
                banner_container.deleteLater()
                settings.dismiss_promo(promo_campaign)
                logger.debug(f"Dismissed promo {promo_campaign}")
                return

            logger.debug(f"Open promo in browser: {promo_url}")
            QDesktopServices.openUrl(QUrl(promo_url))

        banner_label.linkActivated.connect(open_link)

    def __init_title(self) -> None:
        title = PLUGIN_NAME
        connection = NgwConnectionsManager().current_connection
        if connection is not None:
            title = f"{connection.name} – {title}"

        self.setWindowTitle(title)
