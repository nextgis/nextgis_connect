"""
/***************************************************************************
 NGConnectDock
                                 A QGIS plugin
 NGW Connect
                             -------------------
        begin                : 2015-01-30
        git sha              : $Format:%H$
        copyright            : (C) 2014-2016 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import html
import importlib.util
import json
import os
import tempfile
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, cast

from qgis import utils as qgis_utils
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFileUtils,
    QgsLayerTreeLayer,
    QgsLayerTreeRegistryBridge,
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
    QSize,
    Qt,
    QTemporaryFile,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import (
    QContextMenuEvent,
    QDesktopServices,
    QIcon,
    QResizeEvent,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
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
    QToolBar,
    QToolButton,
    QVBoxLayout,
)
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect import utils
from nextgis_connect.action_style_import_or_update import (
    ActionStyleImportUpdate,
)
from nextgis_connect.compat import QGIS_3_32, parse_version
from nextgis_connect.dialog_choose_style import NGWLayerStyleChooserDialog
from nextgis_connect.dialog_metadata import MetadataDialog
from nextgis_connect.exceptions import (
    ErrorCode,
    NgConnectError,
    NgwError,
)
from nextgis_connect.exceptions_list_dialog import ExceptionsListDialog
from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api.core import (
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
    # NGWTileset,
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
from nextgis_connect.ngw_api.qgis.ngw_resource_model_4qgis import (
    QGISResourceJob,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job_error import (
    JobError,
    JobNGWError,
    JobServerRequestError,
    JobWarning,
)
from nextgis_connect.ngw_connection.ngw_connection_edit_dialog import (
    NgwConnectionEditDialog,
)
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.ngw_resources_adder import NgwResourcesAdder
from nextgis_connect.resource_properties.resource_properties_dialog import (
    ResourcePropertiesDialog,
)
from nextgis_connect.resources.creation.vector_layer_creation_dialog import (
    VectorLayerCreationDialog,
)
from nextgis_connect.search.search_panel import SearchPanel
from nextgis_connect.search.search_settings import SearchSettings
from nextgis_connect.search.utils import SearchType
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.tree_widget import (
    QNGWResourceItem,
    QNGWResourceTreeModel,
    QNGWResourceTreeView,
)
from nextgis_connect.tree_widget.model import NGWResourceModelResponse
from nextgis_connect.tree_widget.proxy_model import NgConnectProxyModel

HAS_NGSTD = importlib.util.find_spec("ngstd") is not None
if HAS_NGSTD:
    from ngstd.core import NGRequest  # type: ignore
    from ngstd.framework import NGAccess  # type: ignore


this_dir = os.path.dirname(__file__)

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(this_dir, "ng_connect_dock_base.ui")
)

ICONS_PATH = os.path.join(this_dir, "icons/")


@dataclass
class AddLayersCommand:
    job_uuid: str
    insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint
    ngw_indexes: List[QModelIndex]


class NgConnectDock(QgsDockWidget, FORM_CLASS):
    iface: QgisInterface
    resource_model: QNGWResourceTreeModel
    resources_tree_view: QNGWResourceTreeView

    def __init__(self, title: str, iface: QgisInterface):
        super().__init__(title, parent=None)

        self.setupUi(self)
        self.setObjectName("NGConnectDock")

        self.iface = iface

        self._first_gui_block_on_refresh = False
        self.__search_menu = None

        self.actionOpenInNGW = QAction(self.tr("Open in Web GIS"), self)
        self.actionOpenInNGW.triggered.connect(self.open_ngw_resource_page)

        self.actionOpenInNGWFromLayer = QAction(
            self.tr("Open in Web GIS"), self
        )
        self.actionOpenInNGWFromLayer.triggered.connect(
            self.open_ngw_resource_page_from_layer
        )
        self.layer_menu_separator = QAction()
        self.layer_menu_separator.setSeparator(True)

        self.actionRename = QAction(self.tr("Rename"), self)
        self.actionRename.triggered.connect(self.rename_ngw_resource)

        self.actionExport = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionExport.svg")),
            self.tr("Add to QGIS"),
            self,
        )
        self.actionExport.triggered.connect(self.__download_selected)

        self.actionResourceProperties = QAction(
            self.tr("Resource Properties…"), self
        )
        self.actionResourceProperties.setIcon(
            QIcon(":images/themes/default/propertyicons/attributes.svg")
        )
        self.actionResourceProperties.triggered.connect(
            self.show_properties_dialog
        )

        self.menuUpload = QMenu(self.tr("Add to Web GIS"), self)
        self.menuUpload.setIcon(
            QIcon(os.path.join(ICONS_PATH, "mActionImport.svg"))
        )
        self.menuUpload.menuAction().setIconVisibleInMenu(False)

        self.actionUploadSelectedResources = QAction(
            self.tr("Upload selected"), self.menuUpload
        )
        self.actionUploadSelectedResources.triggered.connect(
            self.upload_selected_resources
        )
        self.actionUploadSelectedResources.setEnabled(False)

        if Qgis.versionInt() >= QGIS_3_32:
            self.iface.layerTreeView().contextMenuAboutToShow.connect(
                self.__add_upload_selected_action_to_export_menu
            )

        self.actionUploadProjectResources = QAction(
            self.tr("Upload all"), self.menuUpload
        )
        self.actionUploadProjectResources.triggered.connect(
            self.upload_project_resources
        )

        self.actionUploadProjectViaImportExportMenu = QAction(
            QIcon(str(Path(__file__).parent / "icons" / "logo.svg")),
            self.tr("Upload project to NextGIS Web"),
        )
        self.actionUploadProjectViaImportExportMenu.triggered.connect(
            self.upload_project_resources
        )
        self.actionUploadProjectViaImportExportMenu.setEnabled(False)

        utils.add_project_export_action(
            self.actionUploadProjectViaImportExportMenu
        )

        self.actionUpdateStyle = ActionStyleImportUpdate(
            self.tr("Update layer style")
        )
        self.actionUpdateStyle.triggered.connect(self.update_style)

        self.actionAddStyle = ActionStyleImportUpdate(
            self.tr("Add new style to layer")
        )
        self.actionAddStyle.triggered.connect(self.add_style)

        self.menuUpload.addAction(self.actionUploadSelectedResources)
        self.menuUpload.addAction(self.actionUploadProjectResources)
        self.menuUpload.addAction(self.actionUpdateStyle)
        self.menuUpload.addAction(self.actionAddStyle)

        self.actionUpdateNGWLayer = QAction(
            self.tr("Overwrite selected layer"), self.menuUpload
        )
        self.actionUpdateNGWLayer.triggered.connect(self.overwrite_ngw_layer)
        self.actionUpdateNGWLayer.setEnabled(False)

        self.actionCreateWebMap4Layer = QAction(
            self.tr("Create Web map"), self
        )
        self.actionCreateWebMap4Layer.triggered.connect(
            self.create_web_map_for_layer
        )

        self.actionCreateWebMap4Style = QAction(
            self.tr("Create Web map"), self
        )
        self.actionCreateWebMap4Style.triggered.connect(
            self.create_web_map_for_style
        )

        self.actionDownload = QAction(self.tr("Download as QML"), self)
        self.actionDownload.triggered.connect(self.downloadQML)

        self.actionCopyStyle = QAction(self.tr("Copy Style"), self)
        self.actionCopyStyle.triggered.connect(self.copy_style)

        self.actionCreateWFSService = QAction(
            self.tr("Create WFS service"), self
        )
        self.actionCreateWFSService.triggered.connect(
            lambda: self.create_wfs_or_ogcf_service("WFS")
        )

        self.actionCreateOgcService = QAction(
            self.tr("Create OGC API - Features service"), self
        )
        self.actionCreateOgcService.triggered.connect(
            lambda: self.create_wfs_or_ogcf_service("OGC API - Features")
        )

        self.actionCreateWMSService = QAction(
            self.tr("Create WMS service"), self
        )
        self.actionCreateWMSService.triggered.connect(self.create_wms_service)

        self.actionCopyResource = QAction(self.tr("Duplicate Resource"), self)
        self.actionCopyResource.triggered.connect(
            self.copy_curent_ngw_resource
        )

        self.actionEditMetadata = QAction(self.tr("Edit metadata"), self)
        self.actionEditMetadata.triggered.connect(self.edit_metadata)

        self.actionDeleteResource = QAction(
            QgsApplication.getThemeIcon("mActionDeleteSelected.svg"),
            self.tr("Delete resource"),
            self,
        )
        self.actionDeleteResource.triggered.connect(
            self.delete_curent_ngw_resource
        )

        self.actionOpenInBrowser = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionOpenMap.svg")),
            self.tr("Display in browser"),
            self,
        )
        self.actionOpenInBrowser.triggered.connect(self.__open_in_web)

        self.actionRefresh = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionRefresh.svg")),
            self.tr("Refresh"),
            self,
        )
        self.actionRefresh.triggered.connect(self.__action_refresh_tree)

        self.actionSettings = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionSettings.svg")),
            self.tr("Settings"),
            self,
        )
        self.actionSettings.triggered.connect(self.action_settings)

        self.actionHelp = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionHelp.svg")),
            self.tr("Help"),
            self,
        )
        self.actionHelp.triggered.connect(utils.open_plugin_help)

        connections_manager = NgwConnectionsManager()
        current_connection_id = connections_manager.current_connection_id

        # Add toolbar
        self.main_tool_bar = NGWPanelToolBar()
        self.content.layout().addWidget(self.main_tool_bar)

        self.search_panel = SearchPanel(current_connection_id, self)
        NgConnectInterface.instance().settings_changed.connect(
            self.search_panel.on_settings_changed
        )
        self.content.layout().addWidget(self.search_panel)
        self.search_panel.search_requested.connect(self.__on_search_requested)
        self.search_panel.reset_requested.connect(self.__on_search_reset)
        self.search_panel.hide()

        self.toolbuttonDownload = QToolButton()
        self.toolbuttonDownload.setIcon(
            QIcon(os.path.join(ICONS_PATH, "mActionExport.svg"))
        )
        self.toolbuttonDownload.setToolTip(self.tr("Add to QGIS"))
        self.toolbuttonDownload.clicked.connect(self.__download_selected)
        self.main_tool_bar.addWidget(self.toolbuttonDownload)

        self.toolbuttonUpload = QToolButton()
        self.toolbuttonUpload.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.toolbuttonUpload.setMenu(self.menuUpload)
        self.toolbuttonUpload.setIcon(self.menuUpload.icon())
        self.toolbuttonUpload.setText(self.menuUpload.title())
        self.toolbuttonUpload.setToolTip(self.menuUpload.title())
        self.main_tool_bar.addWidget(self.toolbuttonUpload)

        self.main_tool_bar.addSeparator()

        self.__create_resource_creation_button()
        self.main_tool_bar.addWidget(self.creation_button)

        self.__create_search_button()
        self.main_tool_bar.addWidget(self.search_button)

        self.main_tool_bar.addAction(self.actionRefresh)

        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionOpenInBrowser)

        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionSettings)
        self.main_tool_bar.addAction(self.actionHelp)

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

        self.blocked_jobs = {
            "NGWGroupCreater": self.tr("Creating resource..."),
            "NGWResourceDelete": self.tr("Deleting resource..."),
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
            "NGWMissingResourceUpdater": self.tr("Downloading resources..."),
            "NgwCreateVectorLayersStubs": self.tr(
                "Processing vector layers..."
            ),
            "ResourcesDownloader": self.tr("Downloading linked resources..."),
            "NgwStylesDownloader": self.tr("Downloading styles..."),
            "AddLayersStub": self.tr("Adding resources to QGIS..."),
            "NgwSearch": self.tr("Searching resources..."),
        }

        # proxy model
        self.proxy_model = NgConnectProxyModel(self)
        self.proxy_model.setSourceModel(self.resource_model)
        self.resource_model.found_resources_changed.connect(
            self.proxy_model.set_resources_id
        )
        self.resource_model.found_resources_changed.connect(
            lambda resources: self.resources_tree_view.not_found_overlay.setVisible(
                -1 in resources
            )
        )

        # ngw resources view
        self.resources_tree_view = QNGWResourceTreeView(self)
        self.resources_tree_view.setModel(self.proxy_model)

        self.resources_tree_view.customContextMenuRequested.connect(
            self.slotCustomContextMenu
        )
        self.resources_tree_view.itemDoubleClicked.connect(
            self.trvDoubleClickProcess
        )

        size_policy = self.resources_tree_view.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        self.resources_tree_view.setSizePolicy(size_policy)

        self.content.layout().addWidget(self.resources_tree_view)

        self.__add_banner()

        self.jobs_count = 0
        self.try_check_https = False

        # update state
        QTimer.singleShot(0, lambda: self.reinit_tree(force=True))

        self.main_tool_bar.setIconSize(QSize(24, 24))

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

    def close(self) -> bool:
        self.resources_tree_view.customContextMenuRequested.disconnect(
            self.slotCustomContextMenu
        )
        self.resources_tree_view.itemDoubleClicked.disconnect(
            self.trvDoubleClickProcess
        )

        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        layer_tree_view.selectionModel().selectionChanged.disconnect(
            self.checkImportActionsAvailability
        )

        selection_model = self.resources_tree_view.selectionModel()
        assert selection_model is not None
        selection_model.currentChanged.disconnect(
            self.checkImportActionsAvailability
        )

        self.resources_tree_view.deleteLater()

        self.resource_model.errorOccurred.disconnect(
            self.__model_error_process
        )
        self.resource_model.warningOccurred.disconnect(
            self.__model_warning_process
        )
        self.resource_model.jobStarted.disconnect(self.__modelJobStarted)
        self.resource_model.jobStatusChanged.disconnect(
            self.__modelJobStatusChanged
        )
        self.resource_model.jobFinished.disconnect(self.__modelJobFinished)
        self.resource_model.indexesLocked.disconnect(
            self.__onModelBlockIndexes
        )
        self.resource_model.indexesUnlocked.disconnect(
            self.__onModelReleaseIndexes
        )

        self.resource_model.deleteLater()

        return super().close()

    @pyqtSlot()
    def checkImportActionsAvailability(self):
        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

        # Search
        self.search_button.setEnabled(self.resource_model.is_connected)
        self.search_panel.setEnabled(self.resource_model.is_connected)

        if not self.resource_model.is_connected:
            return

        # QGIS layers
        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        has_no_qgis_selection = len(qgis_nodes) == 0
        is_one_qgis_selected = len(qgis_nodes) == 1
        # is_multiple_qgis_selection = len(qgis_nodes) > 1
        is_one_qgis_layer_selected = is_one_qgis_selected and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )
        # is_group = (
        #     is_one_qgis_selected and QgsLayerTree.isGroup(qgis_nodes[0])
        # )

        # NGW resources
        selected_ngw_indexes = [
            self.proxy_model.mapToSource(index)
            for index in self.resources_tree_view.selectedIndexes()
        ]
        ngw_resources: List[NGWResource] = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in selected_ngw_indexes
        ]
        has_no_ngw_selection = len(selected_ngw_indexes) == 0
        is_one_ngw_selected = len(selected_ngw_indexes) == 1
        is_multiple_ngw_selection = len(selected_ngw_indexes) > 1

        project = QgsProject.instance()
        assert project is not None

        # Upload current layer(s)
        self.actionUploadSelectedResources.setEnabled(
            not has_no_qgis_selection and is_one_ngw_selected
        )

        # Upload project
        self.actionUploadProjectResources.setEnabled(
            not is_multiple_ngw_selection and project.count() != 0
        )
        self.actionUploadProjectViaImportExportMenu.setEnabled(
            self.actionUploadProjectResources.isEnabled()
        )

        # Overwrite selected layer
        self.actionUpdateNGWLayer.setEnabled(
            is_one_qgis_layer_selected
            and is_one_ngw_selected
            and (
                isinstance(
                    cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(),
                    QgsVectorLayer,
                )
                or isinstance(
                    cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(),
                    QgsRasterLayer,
                )
            )
        )

        if not is_one_ngw_selected or not is_one_qgis_layer_selected:
            self.actionUpdateStyle.setEnabled(False)
            self.actionAddStyle.setEnabled(False)

        elif isinstance(
            ngw_resources[0], (NGWQGISVectorStyle, NGWQGISRasterStyle)
        ):
            ngw_layer = (
                selected_ngw_indexes[0]
                .parent()
                .data(QNGWResourceItem.NGWResourceRole)
            )
            self.actionUpdateStyle.setEnabledByType(
                cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(), ngw_layer
            )
            self.actionAddStyle.setEnabled(False)

        else:
            self.actionUpdateStyle.setEnabledByType(
                cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(),
                ngw_resources[0],
            )
            self.actionAddStyle.setEnabledByType(
                cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(),
                ngw_resources[0],
            )

        upload_actions = [
            self.actionUploadSelectedResources,
            self.actionUploadProjectResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
            self.actionUpdateNGWLayer,
        ]
        self.toolbuttonUpload.setEnabled(
            any(action.isEnabled() for action in upload_actions)
        )

        # TODO: NEED REFACTORING! Make isCompatible methods!
        is_download_enabled = (
            not has_no_ngw_selection
            and all(
                ngw_index.parent().isValid()
                for ngw_index in selected_ngw_indexes
            )
            and all(
                isinstance(
                    ngw_resource,
                    (
                        NGWGroupResource,
                        NGWWfsService,
                        NGWWfsLayer,
                        NGWOgcfService,
                        NGWWmsService,
                        NGWWmsConnection,
                        NGWWmsLayer,
                        NGWVectorLayer,
                        NGWRasterLayer,
                        NGWQGISVectorStyle,
                        NGWQGISRasterStyle,
                        NGWBaseMap,
                        NGWTmsLayer,
                        # NGWTileset,
                        NGWTmsConnection,
                        NGWPostgisLayer,
                        NGWWebMap,
                    ),
                )
                for ngw_resource in ngw_resources
            )
        )
        self.actionExport.setEnabled(is_download_enabled)
        self.toolbuttonDownload.setEnabled(is_download_enabled)

        self.actionOpenInBrowser.setText(
            self.tr("Open Web map in browser")
            if is_one_ngw_selected and isinstance(ngw_resources[0], NGWWebMap)
            else self.tr("Display in browser")
        )
        self.actionOpenInBrowser.setEnabled(
            not is_multiple_ngw_selection
            and not has_no_ngw_selection
            and ngw_resources[0].is_preview_supported
        )

        self.creation_button.setEnabled(is_one_ngw_selected)
        self.actionCreateNgwVectorLayer.setEnabled(is_one_ngw_selected)

        self.actionDeleteResource.setEnabled(
            not is_multiple_ngw_selection
            and not has_no_ngw_selection
            and selected_ngw_indexes[0].parent().isValid()
        )

        self.actionOpenInNGW.setEnabled(is_one_ngw_selected)
        self.actionRename.setEnabled(is_one_ngw_selected)
        self.actionEditMetadata.setEnabled(is_one_ngw_selected)

        layer = (
            cast(QgsLayerTreeLayer, qgis_nodes[0]).layer()
            if is_one_qgis_layer_selected
            else None
        )

        open_in_ngw_visible = (
            is_one_qgis_layer_selected
            and layer is not None
            and layer.customProperty("ngw_connection_id") is not None
            and layer.customProperty("ngw_resource_id") is not None
        )
        self.actionOpenInNGWFromLayer.setVisible(open_in_ngw_visible)
        self.layer_menu_separator.setVisible(open_in_ngw_visible)

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
        # always unblock in case of any error so to allow to fix it
        self.unblock_gui()

        if not self.resource_model.is_connected:
            self.disable_tools()

        msg, msg_ext, icon = self.__get_model_exception_description(exception)

        connections_manager = NgwConnectionsManager()
        current_connection_id = connections_manager.current_connection_id
        assert current_connection_id
        current_connection = connections_manager.current_connection
        assert current_connection

        for i, command in enumerate(self._queue_to_add):
            if command.job_uuid == job_uuid:
                del self._queue_to_add[i]
                break

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
                self.disable_tools()
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
                    connections_manager.save(updated_connection)
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
                    self.disable_tools()
                del dialog

        # The second time return back http if there was an error: this might be some
        # other error, not related to http/https changing.
        if self.try_check_https:
            # this can be only when there are more than 1 connection errors
            self.try_check_https = False
            updated_url = current_connection.url.replace("https://", "http://")
            updated_connection = replace(current_connection, url=updated_url)
            connections_manager.save(updated_connection)
            logger.debug(
                'Failed to reconnect with "https://". Return "http://" back'
            )
            self.reinit_tree(force=True)
            return

        if (
            isinstance(exception, JobServerRequestError)
            and exception.user_msg is not None
        ):
            self.show_error(exception.user_msg)
            return

        if (
            isinstance(exception, NgConnectError)
            and exception.try_again is None
        ):
            if self.__is_reinit_tree:
                exception.try_again = lambda: self.reinit_tree(force=True)

        error_id = NgConnectInterface.instance().show_error(exception)
        if self.__is_reinit_tree:
            self.__reinit_tree_error = error_id

    def __get_model_exception_description(self, exception: Exception):
        msg = None
        msg_ext = None
        icon = os.path.join(ICONS_PATH, "Error.svg")

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
            icon = os.path.join(ICONS_PATH, "Warning.svg")

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

        widget = self.iface.messageBar().createMessage(
            NgConnectInterface.PLUGIN_NAME, message
        )
        self.iface.messageBar().pushWidget(widget, level, duration)

    @pyqtSlot(str)
    def __modelJobStarted(self, job_id: str):
        if job_id in self.blocked_jobs:
            self.block_gui()
            self.resources_tree_view.addBlockedJob(self.blocked_jobs[job_id])

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

        if job_id == "NGWRootResourcesLoader":
            self.unblock_gui()

        if job_id in self.blocked_jobs:
            self.unblock_gui()
            self.resources_tree_view.removeBlockedJob(
                self.blocked_jobs[job_id], check_overlay=False
            )

        self.__add_layers_after_finish(job_uuid)

        if len(self.resource_model.jobs) == 1 or all(
            job.getJobId() not in self.blocked_jobs
            for job in self.resource_model.jobs
        ):
            self.resources_tree_view.check_overlay()

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
        self.actionCreateNgwVectorLayer.setEnabled(False)
        self.search_panel.setEnabled(False)
        # TODO (ivanbarsukov): Disable parent action
        for action in (
            self.actionUploadSelectedResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
        ):
            action.setEnabled(False)

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

    def reinit_tree(self, force=False):
        self.__is_reinit_tree = True
        if self.__reinit_tree_error is not None:
            NgConnectInterface.instance().close_error(self.__reinit_tree_error)
            self.__reinit_tree_error = None

        # clear tree and states
        self.block_gui()

        try:
            connections_manager = NgwConnectionsManager()
            current_connection = connections_manager.current_connection
            if current_connection is None:
                self.jobs_count = 0
                self.resource_model.resetModel(None)
                self.unblock_gui()
                self.disable_tools()
                if connections_manager.has_not_converted_connections():
                    self.resources_tree_view.migration_overlay.show()
                else:
                    self.resources_tree_view.showWelcomeMessage()
                return

            if (
                HAS_NGSTD
                and current_connection.method == "NextGIS"
                and not NGAccess.instance().isUserAuthorized()
            ):
                self.jobs_count = 0
                self.resource_model.resetModel(None)
                self.resources_tree_view.no_oauth_auth_overlay.show()
                self.unblock_gui()
                self.disable_tools()
                return

            self.resources_tree_view.hideWelcomeMessage()
            self.resources_tree_view.migration_overlay.hide()
            self.resources_tree_view.unsupported_version_overlay.hide()
            self.resources_tree_view.no_oauth_auth_overlay.hide()

            if force:
                if HAS_NGSTD and current_connection.method == "NextGIS":
                    NGRequest.addAuthURL(
                        NGAccess.instance().endPoint(), current_connection.url
                    )

                # start working with connection at very first time
                self.jobs_count = 0

                self._first_gui_block_on_refresh = True
                ngw_connection = QgsNgwConnection(current_connection.id)

                self.resource_model.resetModel(ngw_connection)

                if (
                    self.resource_model.ngw_version is not None
                    and not self.resource_model.is_ngw_version_supported
                ):
                    self.unblock_gui()
                    self.disable_tools()

                    self.resources_tree_view.unsupported_version_overlay.set_status(
                        self.resource_model.support_status,
                        qgis_utils.pluginMetadata(
                            "nextgis_connect", "version"
                        ),
                        self.resource_model.ngw_version,
                    )
                    self.resources_tree_view.unsupported_version_overlay.show()

                    logger.error("NGW version is outdated")

            # expand root item
            # self.resources_tree_view.setExpanded(self.resource_model.index(0, 0, QModelIndex()), True)

        except Exception as error:
            self.jobs_count = 0
            self.resource_model.resetModel(None)

            self.unblock_gui()
            self.disable_tools()

            logger.exception("Model update error")

            NgConnectInterface.instance().show_error(error)

        self.__update_search_button()
        self.__is_reinit_tree = False

    @pyqtSlot()
    def __action_refresh_tree(self):
        self.reinit_tree(force=True)

    @pyqtSlot(bool)
    def __toggle_filter(self, state: bool) -> None:
        if not state:
            self.resource_model.reset_search()
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
            self.toolbuttonDownload,
            self.toolbuttonUpload,
            self.actionCreateNgwVectorLayer,
            self.creation_button,
            self.search_button,
            self.search_panel,
            self.actionOpenInBrowser,
            self.actionUploadSelectedResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
        ):
            widget.setEnabled(False)

        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

    @pyqtSlot()
    def action_settings(self):
        self.iface.showOptionsDialog(
            self.iface.mainWindow(), "NextGIS Connect"
        )

    def str_to_link(self, text: str, url: str) -> str:
        return f'<a href="{url}"><span style=" text-decoration: underline; color:#0000ff;">{text}</span></a>'

    def slotCustomContextMenu(self, qpoint: QPoint):
        proxy_index = self.resources_tree_view.indexAt(qpoint)
        index = self.proxy_model.mapToSource(proxy_index)

        if not index.isValid() or index.internalPointer().locked:
            return

        proxy_selected_indexes = self.resources_tree_view.selectedIndexes()
        selected_indexes = [
            self.proxy_model.mapToSource(index)
            for index in proxy_selected_indexes
        ]
        ngw_resources: List[NGWResource] = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in selected_indexes
        ]

        getting_actions: List[QAction] = []
        setting_actions: List[QAction] = []
        creating_actions: List[QAction] = [self.actionEditMetadata]
        services_actions: List[QAction] = [
            self.actionOpenInNGW,
            self.actionRename,
            self.actionDeleteResource,
        ]
        if NgConnectSettings().is_developer_mode:
            services_actions.append(self.actionResourceProperties)

        if any(
            isinstance(
                ngw_resource,
                (
                    NGWGroupResource,
                    NGWVectorLayer,
                    NGWRasterLayer,
                    NGWWmsLayer,
                    NGWWfsService,
                    NGWWfsLayer,
                    NGWOgcfService,
                    NGWWmsService,
                    NGWWmsConnection,
                    NGWQGISVectorStyle,
                    NGWQGISRasterStyle,
                    # NGWTileset,
                    NGWBaseMap,
                    NGWTmsLayer,
                    NGWTmsConnection,
                    NGWPostgisLayer,
                    NGWWebMap,
                ),
            )
            for ngw_resource in ngw_resources
        ):
            getting_actions.append(self.actionExport)

        ngw_resource = ngw_resources[0]
        is_multiple_selection = len(ngw_resources) > 1

        if not is_multiple_selection and isinstance(
            ngw_resource, (NGWQGISVectorStyle, NGWQGISRasterStyle)
        ):
            getting_actions.extend([self.actionDownload, self.actionCopyStyle])

        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        is_same_type = (
            isinstance(ngw_resource, NGWVectorLayer)
            and isinstance(qgs_map_layer, QgsVectorLayer)
        ) or (
            isinstance(ngw_resource, NGWRasterLayer)
            and isinstance(qgs_map_layer, QgsRasterLayer)
        )

        if (
            not is_multiple_selection
            and isinstance(ngw_resource, (NGWVectorLayer, NGWRasterLayer))
            and is_same_type
        ):
            setting_actions.append(self.actionUpdateNGWLayer)

        if not is_multiple_selection and isinstance(
            ngw_resource, NGWGroupResource
        ):
            creating_actions.append(self.actionCreateNewGroup)
            creating_actions.append(self.actionCreateNewVectorLayer)

        if not is_multiple_selection:
            if isinstance(
                ngw_resource, (NGWVectorLayer, NGWPostgisLayer, NGWWfsLayer)
            ):
                creating_actions.extend(
                    [
                        self.actionCreateWFSService,
                        self.actionCreateOgcService,
                        self.actionCreateWMSService,
                    ]
                )
            elif isinstance(ngw_resource, (NGWRasterLayer, NGWQGISStyle)):
                creating_actions.append(self.actionCreateWMSService)

        if not is_multiple_selection and isinstance(
            ngw_resource, (NGWVectorLayer, NGWRasterLayer, NGWWmsLayer)
        ):
            creating_actions.append(self.actionCreateWebMap4Layer)

        if not is_multiple_selection and isinstance(
            ngw_resource, (NGWVectorLayer, NGWRasterLayer)
        ):
            creating_actions.append(self.actionCopyResource)

        if not is_multiple_selection and isinstance(
            ngw_resource,
            (
                NGWQGISVectorStyle,
                NGWQGISRasterStyle,
                NGWRasterStyle,
                NGWMapServerStyle,
            ),
        ):
            creating_actions.append(self.actionCreateWebMap4Style)

        if not is_multiple_selection and ngw_resource.is_preview_supported:
            services_actions.append(self.actionOpenInBrowser)

        menu = QMenu()
        for actions in [
            getting_actions,
            setting_actions,
            creating_actions,
            services_actions,
        ]:
            if len(actions) == 0:
                continue
            for action in actions:
                menu.addAction(action)
            menu.addSeparator()

        menu.exec(self.resources_tree_view.viewport().mapToGlobal(qpoint))

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

    def __download_selected(self):
        selection_model = self.resources_tree_view.selectionModel()
        selected_indexes = [
            self.proxy_model.mapToSource(index)
            for index in selection_model.selectedIndexes()
        ]
        self.__download_indices(selected_indexes)

    def __download_indices(self, indices: List[QModelIndex]) -> None:
        def save_command(job) -> None:
            insertion_point = self.iface.layerTreeInsertionPoint()
            self._queue_to_add.append(
                AddLayersCommand(job.job_uuid, insertion_point, indices)
            )

        adder = NgwResourcesAdder(
            self.resource_model,
            indices,
            self.iface.layerTreeInsertionPoint(),
        )

        is_success, missing_ids = adder.missing_resources()
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

        # Make stubs for vector layers
        model = self.resource_model
        download_job = model.download_vector_layers_if_needed(indices)
        if download_job is not None:
            save_command(download_job)
            return

        # Fetch styles
        is_success, styles_id = adder.missing_styles()
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
        self.resources_tree_view.addBlockedJob(self.blocked_jobs[job_id])

        adder.run()

        self.unblock_gui()
        self.resources_tree_view.removeBlockedJob(self.blocked_jobs[job_id])

        tree_rigistry_bridge.setLayerInsertionPoint(backup_point)

        plugin.enable_synchronization()

    @pyqtSlot()
    def create_group(self) -> None:
        sel_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
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

        self.__fetch_children_if_needed(parent_resource_index)
        dialog = VectorLayerCreationDialog(
            self.resource_model, parent_resource_index, self
        )
        result = dialog.exec()
        if result != VectorLayerCreationDialog.DialogCode.Accepted:
            return

        resource = dialog.resource
        add_to_project = dialog.add_to_project
        self.create_vector_layer_responce = (
            self.resource_model.createVectorLayer(
                parent_resource_index, resource
            )
        )

        self.create_vector_layer_responce.done.connect(
            lambda index: self.resources_tree_view.setCurrentIndex(
                self.proxy_model.mapFromSource(index)
            )
        )
        if add_to_project:
            self.create_vector_layer_responce.done.connect(
                lambda index: self.__download_indices([index])
            )

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
        self.qgis_proj_import_response.done.connect(self.open_create_web_map)
        self.qgis_proj_import_response.done.connect(self.processWarnings)

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
            qgs_layer_tree_nodes = [self.iface.layerTreeView().currentNode()]
            if (
                len(qgs_layer_tree_nodes) == 0
            ):  # just in case if checkImportActionsAvailability() works incorrectly
                return

        self.import_layer_response = self.resource_model.uploadResourcesList(
            qgs_layer_tree_nodes, ngw_current_index, self.iface
        )
        self.import_layer_response.select.connect(self.__select_list)
        self.import_layer_response.done.connect(self.processWarnings)

    def overwrite_ngw_layer(self):
        index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        qgs_map_layer = self.iface.mapCanvas().currentLayer()

        result = QMessageBox.question(
            self,
            self.tr("Overwrite resource"),
            self.tr(
                'Resource "{}" will be overwritten with QGIS layer "{}". '
                "Current data will be lost.<br/>Are you sure you want to "
                "overwrite it?"
            ).format(
                index.data(Qt.ItemDataRole.DisplayRole),
                html.escape(qgs_map_layer.name()),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        if isinstance(qgs_map_layer, QgsVectorLayer):
            self.resource_model.updateNGWVectorLayer(index, qgs_map_layer)

        if isinstance(qgs_map_layer, QgsRasterLayer):
            self.resource_model.updateNGWRasterLayer(index, qgs_map_layer)

    def edit_metadata(self):
        """Edit metadata table"""
        sel_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            self.block_gui()

            try:
                self.resources_tree_view.ngw_job_block_overlay.show()
                self.resources_tree_view.ngw_job_block_overlay.text.setText(
                    "<strong>{} {}</strong><br/>".format(
                        self.tr("Get resource metadata"),
                        ngw_resource.display_name,
                    )
                )
                ngw_resource.update()
                self.resources_tree_view.ngw_job_block_overlay.hide()

                dlg = MetadataDialog(ngw_resource, self)
                dlg.exec()

            except NGWError as error:
                ng_error = NgwError()
                ng_error.__cause__ = error
                NgConnectInterface.instance().show_error(ng_error)
                self.resources_tree_view.ngw_job_block_overlay.hide()

            except NgConnectError as error:
                NgConnectInterface.instance().show_error(error)
                self.resources_tree_view.ngw_job_block_overlay.hide()

            except Exception as error:
                ng_error = NgConnectError()
                ng_error.__cause__ = error
                NgConnectInterface.instance().show_error(ng_error)
                self.resources_tree_view.ngw_job_block_overlay.hide()

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

    def delete_curent_ngw_resource(self):
        res = QMessageBox.question(
            self,
            self.tr("Delete resource"),
            self.tr("Are you sure you want to remove this resource?"),
            QMessageBox.StandardButton.Yes and QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if res == QMessageBox.StandardButton.Yes:
            selected_index = self.proxy_model.mapToSource(
                self.resources_tree_view.selectionModel().currentIndex()
            )
            self.delete_resource_response = self.resource_model.deleteResource(
                selected_index
            )
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

            temp_path = Path(tempfile.mktemp(suffix=".gpkg"))

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
            except Exception:
                pass
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

    def copy_curent_ngw_resource(self):
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
            self.resources_tree_view.ngw_job_block_overlay.show()
            self.block_gui()
            self.resources_tree_view.ngw_job_block_overlay.text.setText(
                "<strong>{} {}</strong><br/>".format(
                    self.tr("Duplicating"), ngw_resource.display_name
                )
            )
            # main part
            try:
                ngw_result = self._copy_resource(ngw_resource)
                self.__add_resource_to_tree(ngw_result)
            except NgConnectError as error:
                NgConnectInterface.instance().show_error(error)
            except Exception as ex:
                error_mes = str(ex)
                self.iface.messageBar().pushMessage(
                    self.tr("Error"),
                    error_mes,
                    level=Qgis.MessageLevel.Critical,
                )
                logger.exception(error_mes)

            # unblock gui
            self.resources_tree_view.ngw_job_block_overlay.hide()
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
            ngw_styles = ngw_resource.get_children()
            ngw_resource_style_id = None

            if len(ngw_styles) == 1:
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
            path = tempfile.mktemp(suffix=".qml")

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
                NgConnectInterface.instance().show_error(error)

        self.dwn_qml_file = QFile(path)
        return result

    def downloadQML(self):
        selected_index = self.proxy_model.mapToSource(
            self.resources_tree_view.selectionModel().currentIndex()
        )
        ngw_qgis_style = selected_index.data(QNGWResourceItem.NGWResourceRole)

        settings = QgsSettings()
        last_used_dir = settings.value("style/lastStyleDir", QDir.homePath())
        style_name = ngw_qgis_style.display_name
        path_to_qml = os.path.join(last_used_dir, f"{style_name}.qml")
        filepath, selected_filter = QFileDialog.getSaveFileName(
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
            NgConnectInterface.instance().show_error(error)
            return

        # Copy style
        QGSCLIPBOARD_STYLE_MIME = "application/qgis.style"
        data = dom_document.toByteArray()
        text = dom_document.toString()
        utils.set_clipboard_data(QGSCLIPBOARD_STYLE_MIME, data, text)

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

        adder = NgwResourcesAdder(
            self.resource_model, command.ngw_indexes, command.insertion_point
        )

        is_success, missing_ids = adder.missing_resources()
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

        download_job = model.download_vector_layers_if_needed(
            command.ngw_indexes
        )
        if download_job is not None:
            command.job_uuid = download_job.job_uuid
            self._queue_to_add.append(command)
            return

        # Fetch styles
        is_success, styles_id = adder.missing_styles()
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
        self.resources_tree_view.addBlockedJob(self.blocked_jobs[job_id])

        adder.run()

        self.unblock_gui()
        self.resources_tree_view.removeBlockedJob(self.blocked_jobs[job_id])

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

    def __add_upload_selected_action_to_export_menu(self, menu: QMenu) -> None:
        """
        Triggered when the layer tree menu is about to show
        Add action 'Upload to NextGIS Web' to the Export menu of selected layers
        """
        menus = [
            action
            for action in menu.children()
            if isinstance(action, QMenu)
            and action.objectName() == "exportMenu"
        ]

        if not menus:
            return

        export_menu = menus[0]

        actionUploadSelectedViaExportMenu = QAction(
            QIcon(str(Path(__file__).parent / "icons" / "logo.svg")),
            self.tr("Upload to NextGIS Web"),
            export_menu,
        )
        actionUploadSelectedViaExportMenu.triggered.connect(
            self.upload_selected_resources
        )
        actionUploadSelectedViaExportMenu.setEnabled(
            self.actionUploadSelectedResources.isEnabled()
        )

        export_menu.addAction(actionUploadSelectedViaExportMenu)

    def __create_search_button(self) -> None:
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

        self.search_button = QToolButton()
        self.search_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.search_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.DelayedPopup
        )
        self.search_button.setIcon(
            QIcon(os.path.join(ICONS_PATH, "mActionFilter.svg"))
        )
        self.search_button.setText(self.tr("Search"))
        self.search_button.setToolTip(self.tr("Search"))
        self.search_button.setCheckable(True)
        self.search_button.clicked.connect(self.__toggle_filter)

        self.__search_menu = menu

    def __update_search_button(self) -> None:
        has_new_search_api = (
            self.resource_model.ngw_version is not None
            and parse_version(self.resource_model.ngw_version)
            >= parse_version("5.0.0.dev13")
        )

        if has_new_search_api:
            self.search_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.MenuButtonPopup
            )
            self.search_button.setMenu(self.__search_menu)
        else:
            self.search_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.DelayedPopup
            )
            self.__search_menu.actions()[1].setChecked(True)
            self.search_panel.set_type(SearchType.ByDisplayName)
            self.search_button.setMenu(None)

        self.main_tool_bar.fix_icons_size()

    def __create_resource_creation_button(self) -> None:
        menu = QMenu()

        self.actionCreateNewGroup = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionNewFolder.svg")),
            self.tr("Create resource group"),
            self,
        )
        self.actionCreateNewGroup.triggered.connect(self.create_group)
        menu.addAction(self.actionCreateNewGroup)

        self.actionCreateNewVectorLayer = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionNewVectorLayer.svg")),
            self.tr("Create vector layer"),
            self,
        )
        self.actionCreateNewVectorLayer.triggered.connect(
            self.create_vector_layer
        )
        menu.addAction(self.actionCreateNewVectorLayer)

        text = self.tr("New NextGIS Web Vector Layer")
        self.actionCreateNgwVectorLayer = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionNewVectorLayerNative.svg")),
            text,
            self,
        )
        self.actionCreateNgwVectorLayer.setToolTip(f"<b>{text}</b>")
        self.actionCreateNgwVectorLayer.triggered.connect(
            self.create_vector_layer
        )

        self.creation_button = QToolButton()
        self.creation_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.creation_button.setMenu(menu)
        self.creation_button.setDefaultAction(self.actionCreateNewGroup)

    @pyqtSlot(str)
    def __on_search_requested(self, search_string: str) -> None:
        if len(search_string) == 0:
            self.__on_search_reset()
        else:
            self.resources_tree_view.not_found_overlay.hide()
            self.resource_model.search(search_string)

    @pyqtSlot()
    def __on_search_reset(self) -> None:
        self.resource_model.reset_search()
        self.resources_tree_view.not_found_overlay.hide()

    @pyqtSlot(bool)
    def __on_search_type_changed(self, value: bool) -> None:
        if not value:
            return

        action = cast(QAction, self.sender())
        self.search_panel.set_type(action.data())
        self.search_panel.show()
        self.search_panel.focus()
        self.search_button.setChecked(True)

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
                f"utm_term={NgConnectInterface.PACKAGE_NAME}",
                f"utm_content={utils.locale()}",
            ]
        )
        promo_url = f"{promo_base_url}?{utm_template}"

        banner_layout = QVBoxLayout()
        banner_layout.setContentsMargins(0, 4, 0, 4)

        banner = QFrame(self.content)
        banner.setObjectName("NgConnectBanner")
        banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner.setFrameShadow(QFrame.Shadow.Raised)

        banner.setLayout(QHBoxLayout())
        banner.layout().setContentsMargins(6, 6, 6, 6)

        banner_label = QLabel(banner)
        banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = Path(ICONS_PATH) / "fire.png"
        close_icon = utils.icon_to_base64(
            utils.material_icon("close", size=16)
        )

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

        self.content.layout().addLayout(banner_layout)

        def open_link(url: str) -> None:
            if url == "#close":
                banner_layout.deleteLater()
                banner.deleteLater()
                settings.dismiss_promo(promo_campaign)
                logger.debug(f"Dismissed promo {promo_campaign}")
                return

            logger.debug(f"Open promo in browser: {promo_url}")
            QDesktopServices.openUrl(QUrl(promo_url))

        banner_label.linkActivated.connect(open_link)


class NGWPanelToolBar(QToolBar):
    def __init__(self):
        super().__init__(None)

        self.setIconSize(QSize(24, 24))
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

    def contextMenuEvent(self, a0: Optional[QContextMenuEvent]) -> None:
        a0.accept()

    def resizeEvent(self, a0: Optional[QResizeEvent]) -> None:
        self.fix_icons_size()
        a0.accept()

    def fix_icons_size(self) -> None:
        self.setIconSize(QSize(24, 24))

        for button in self.findChildren(QToolButton):
            button.setIconSize(QSize(24, 24))
            button.setFixedSize(button.sizeHint())
