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
import json
import os
import tempfile
import urllib.parse
from dataclasses import dataclass
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
    QModelIndex,
    QPoint,
    QSize,
    Qt,
    QTemporaryFile,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QToolButton,
)
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect import utils
from nextgis_connect.action_style_import_or_update import (
    ActionStyleImportUpdate,
)
from nextgis_connect.detached_editing.utils import detached_layer_uri
from nextgis_connect.dialog_choose_style import NGWLayerStyleChooserDialog
from nextgis_connect.dialog_metadata import MetadataDialog
from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgConnectError,
    NgwError,
)
from nextgis_connect.exceptions_list_dialog import ExceptionsListDialog
from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api.core import (
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
    NGWVectorLayer,
    NGWWfsService,
    NGWWmsConnection,
    NGWWmsLayer,
    NGWWmsService,
)
from nextgis_connect.ngw_api.core.ngw_base_map import NGWBaseMap
from nextgis_connect.ngw_api.core.ngw_postgis_layer import NGWPostgisConnection
from nextgis_connect.ngw_api.core.ngw_tms_resources import (
    NGWTmsLayer,
)
from nextgis_connect.ngw_api.core.ngw_webmap import (
    NGWWebMap,
    NGWWebMapGroup,
    NGWWebMapLayer,
)
from nextgis_connect.ngw_api.qgis.ngw_resource_model_4qgis import (
    QGISResourceJob,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_api.qgis.resource_to_map import (
    UnsupportedRasterTypeException,
    _add_aliases,
    _add_all_styles_to_layer,
    _add_lookup_tables,
    add_ogcf_resource,
    add_resource_as_cog_raster,
    add_resource_as_wfs_layers,
)
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
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from nextgis_connect.tree_widget import (
    QNGWResourceItem,
    QNGWResourceTreeModel,
    QNGWResourceTreeView,
)

HAS_NGSTD = True
try:
    from ngstd.core import NGRequest  # type: ignore
    from ngstd.framework import NGAccess  # type: ignore
except ImportError:
    HAS_NGSTD = False

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
        self.actionExport.triggered.connect(self.__export_to_qgis)

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

        self.actionUploadProjectResources = QAction(
            self.tr("Upload all"), self.menuUpload
        )
        self.actionUploadProjectResources.triggered.connect(
            self.upload_project_resources
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

        self.actionUpdateNGWVectorLayer = QAction(
            self.tr("Overwrite selected layer"), self.menuUpload
        )
        self.actionUpdateNGWVectorLayer.triggered.connect(
            self.overwrite_ngw_layer
        )
        self.actionUpdateNGWVectorLayer.setEnabled(False)

        self.actionCreateNewGroup = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionNewFolder.svg")),
            self.tr("Create resource group"),
            self,
        )
        self.actionCreateNewGroup.triggered.connect(self.create_group)

        self.actionCreateWebMap4Layer = QAction(
            self.tr("Create web map"), self
        )
        self.actionCreateWebMap4Layer.triggered.connect(
            self.create_web_map_for_layer
        )

        self.actionCreateWebMap4Style = QAction(
            self.tr("Create web map"), self
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

        self.actionOpenMapInBrowser = QAction(
            QIcon(os.path.join(ICONS_PATH, "mActionOpenMap.svg")),
            self.tr("Open web map in browser"),
            self,
        )
        self.actionOpenMapInBrowser.triggered.connect(self.__action_open_map)

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

        # Add toolbar
        self.main_tool_bar = NGWPanelToolBar()
        self.content.layout().addWidget(self.main_tool_bar)

        self.toolbuttonDownload = QToolButton()
        self.toolbuttonDownload.setIcon(
            QIcon(os.path.join(ICONS_PATH, "mActionExport.svg"))
        )
        self.toolbuttonDownload.setToolTip(self.tr("Add to QGIS"))
        self.toolbuttonDownload.clicked.connect(self.__export_to_qgis)
        self.main_tool_bar.addWidget(self.toolbuttonDownload)

        self.toolbuttonUpload = QToolButton()
        self.toolbuttonUpload.setPopupMode(QToolButton.InstantPopup)
        self.toolbuttonUpload.setMenu(self.menuUpload)
        self.toolbuttonUpload.setIcon(self.menuUpload.icon())
        self.toolbuttonUpload.setText(self.menuUpload.title())
        self.toolbuttonUpload.setToolTip(self.menuUpload.title())
        self.main_tool_bar.addWidget(self.toolbuttonUpload)

        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionCreateNewGroup)
        self.main_tool_bar.addAction(self.actionRefresh)

        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionOpenMapInBrowser)

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

        self._queue_to_add: List[AddLayersCommand] = []

        self.blocked_jobs = {
            "NGWGroupCreater": self.tr("Resource is being created"),
            "NGWResourceDelete": self.tr("Resource is being deleted"),
            "QGISResourcesUploader": self.tr("Layer is being imported"),
            "QGISProjectUploader": self.tr("Project is being imported"),
            "NGWCreateWfsService": self.tr("WFS service is being created"),
            "NGWCreateOgcfService": self.tr(
                "OGC API - Features service is being created"
            ),
            "NGWCreateWMSForVector": self.tr("WMS service is being created"),
            "NGWCreateMapForStyle": self.tr("Web map is being created"),
            "MapForLayerCreater": self.tr("Web map is being created"),
            "QGISStyleUpdater": self.tr("Style for layer is being updated"),
            "QGISStyleAdder": self.tr("Style for layer is being created"),
            "NGWRenameResource": self.tr("Resource is being renamed"),
            "NGWUpdateVectorLayer": self.tr("Resource is being updated"),
            "NgwCreateVectorLayersStubs": self.tr(
                "Vector layers is being downloaded"
            ),
            "ResourcesDownloader": self.tr(
                "Linked resources is being downloaded"
            ),
        }

        # ngw resources view
        self.resources_tree_view = QNGWResourceTreeView(self)
        self.resources_tree_view.setModel(self.resource_model)

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

        self.jobs_count = 0
        self.try_check_https = False

        # update state
        QTimer.singleShot(0, lambda: self.reinit_tree(force=True))

        self.main_tool_bar.setIconSize(QSize(24, 24))

        if HAS_NGSTD:
            NGAccess.instance().userInfoUpdated.connect(
                self.__on_ngstd_user_info_updated
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

        self.checkImportActionsAvailability()

    def close(self):
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

        super().close()

    @pyqtSlot()
    def checkImportActionsAvailability(self):
        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

        if not self.resource_model.is_connected:
            return

        # QGIS layers
        layer_tree_view = self.iface.layerTreeView()
        assert layer_tree_view is not None
        qgis_nodes = layer_tree_view.selectedNodes()
        has_no_qgis_selection = len(qgis_nodes) == 0
        is_one_qgis_selected = len(qgis_nodes) == 1
        # is_multiple_qgis_selection = len(qgis_nodes) > 1
        is_layer = is_one_qgis_selected and isinstance(
            qgis_nodes[0], QgsLayerTreeLayer
        )
        # is_group = (
        #     is_one_qgis_selected and QgsLayerTree.isGroup(qgis_nodes[0])
        # )

        # NGW resources
        selected_ngw_indexes = self.resources_tree_view.selectedIndexes()
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

        # Overwrite selected layer
        self.actionUpdateNGWVectorLayer.setEnabled(
            is_layer
            and is_one_ngw_selected
            and isinstance(
                cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(), QgsVectorLayer
            )
        )

        if not is_one_ngw_selected or not is_layer:
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
            self.actionUpdateStyle.setEnabled(False)
            self.actionAddStyle.setEnabledByType(
                cast(QgsLayerTreeLayer, qgis_nodes[0]).layer(),
                ngw_resources[0],
            )

        upload_actions = [
            self.actionUploadSelectedResources,
            self.actionUploadProjectResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
            self.actionUpdateNGWVectorLayer,
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
                        NGWPostgisLayer,
                        NGWWebMap,
                    ),
                )
                for ngw_resource in ngw_resources
            )
        )
        self.actionExport.setEnabled(is_download_enabled)
        self.toolbuttonDownload.setEnabled(is_download_enabled)

        self.actionOpenMapInBrowser.setEnabled(
            not is_multiple_ngw_selection
            and not has_no_ngw_selection
            and isinstance(ngw_resources[0], NGWWebMap)
        )

        self.actionCreateNewGroup.setEnabled(is_one_ngw_selected)

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
            if is_layer
            else None
        )

        open_in_ngw_visible = (
            is_layer
            and layer is not None
            and layer.customProperty("ngw_connection_id") is not None
            and layer.customProperty("ngw_resource_id") is not None
        )
        self.actionOpenInNGWFromLayer.setVisible(open_in_ngw_visible)
        self.layer_menu_separator.setVisible(open_in_ngw_visible)

    def __model_warning_process(self, job_name, job_uuid, exception):
        self.__model_exception_process(
            job_name, job_uuid, exception, Qgis.MessageLevel.Warning
        )

    def __model_error_process(self, job_name, job_uuid, exception):
        self.__model_exception_process(
            job_name, job_uuid, exception, Qgis.MessageLevel.Critical
        )

    def __model_exception_process(self, job_name, job_uuid, exception, level):
        # always unblock in case of any error so to allow to fix it
        self.unblock_gui()

        if not self.resource_model.is_connected:
            self.disable_tools()

        msg, msg_ext, icon = self.__get_model_exception_description(
            job_name, exception
        )

        connections_manager = NgwConnectionsManager()
        current_connection_id = connections_manager.current_connection_id
        assert current_connection_id
        current_connection = connections_manager.current_connection
        assert current_connection

        if job_name == "NgwCreateVectorLayersStubs":
            found_i = -1
            for i in range(len(self._queue_to_add)):
                if self._queue_to_add[i].job_uuid == job_uuid:
                    found_i = i
                    break
            if found_i != -1:
                del self._queue_to_add[found_i]

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
            if exception is JobServerRequestError and exception.need_reconnect:
                server_url = current_connection.url

                # Try to fix http -> https. Useful for fixing old (saved) cloud
                # connections.
                if server_url.startswith("http://") and server_url.endswith(
                    ".nextgis.com"
                ):
                    self.try_check_https = True
                    current_connection.url = server_url.replace(
                        "http://", "https://"
                    )
                    connections_manager.save(current_connection)
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
            server_url = current_connection.url
            current_connection.url = server_url.replace("https://", "http://")
            connections_manager.save(current_connection)
            logger.debug(
                'Failed to reconnect with "https://". Return "http://" back'
            )
            self.reinit_tree(force=True)
            return

        if (
            issubclass(exception.__class__, JobServerRequestError)
            and exception.user_msg is not None
        ):
            self.show_error(exception.user_msg)
            return

        NgConnectInterface.instance().show_error(exception)

    def __get_model_exception_description(self, job, exception):
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
                if msg_ext is None:
                    msg_ext = ""
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
                        msg_ext = json.loads(str(exception.wrapped_exception))[
                            "message"
                        ]

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
        self, message, level=Qgis.MessageLevel.Info, duration=0
    ):
        if message.endswith(".."):
            message = message[:-1]

        widget = self.iface.messageBar().createMessage(
            NgConnectInterface.PLUGIN_NAME, message
        )
        self.iface.messageBar().pushWidget(widget, level, duration)

    def __modelJobStarted(self, job_id):
        if job_id in self.blocked_jobs:
            self.block_gui()
            self.resources_tree_view.addBlockedJob(self.blocked_jobs[job_id])

    def __modelJobStatusChanged(self, job_id, status):
        if job_id in self.blocked_jobs:
            self.resources_tree_view.addJobStatus(
                self.blocked_jobs[job_id], status
            )

    def __modelJobFinished(self, job_id, job_uuid):
        self.jobs_count += 1  # note: __modelJobFinished will be triggered even if error/warning occured during job execution
        # logger.debug(
        #     f"Jobs finished for current connection: {self.jobs_count}"
        # )

        if job_id == "NGWRootResourcesLoader":
            self.unblock_gui()

        if job_id in self.blocked_jobs:
            self.unblock_gui()
            self.resources_tree_view.removeBlockedJob(
                self.blocked_jobs[job_id]
            )

        self.__add_layers_after_finish(job_uuid)

    def __onModelBlockIndexes(self):
        self.block_gui()

    def __onModelReleaseIndexes(self):
        if self._first_gui_block_on_refresh:
            self._first_gui_block_on_refresh = False
        else:
            self.unblock_gui()

    def block_gui(self):
        self.main_tool_bar.setEnabled(False)
        # TODO (ivanbarsukov): Disable parent action
        for action in (
            self.actionUploadSelectedResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
        ):
            action.setEnabled(False)

    def unblock_gui(self):
        self.main_tool_bar.setEnabled(True)
        self.checkImportActionsAvailability()

    def reinit_tree(self, force=False):
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

    def __action_refresh_tree(self):
        self.reinit_tree(force=True)

    def __add_resource_to_tree(self, ngw_resource):
        # TODO: fix duplicate with model.processJobResult
        if ngw_resource.common.parent is None:
            index = QModelIndex()
            self.resource_model.addNGWResourceToTree(index, ngw_resource)
        else:
            index = self.resource_model.getIndexByNGWResourceId(
                ngw_resource.common.parent.id,
            )

            item = index.internalPointer()
            current_ids = [
                item.child(i).data(QNGWResourceItem.NGWResourceRole).common.id
                for i in range(item.childCount())
                if isinstance(item.child(i), QNGWResourceItem)
            ]
            if ngw_resource.common.id not in current_ids:
                self.resource_model.addNGWResourceToTree(index, ngw_resource)

    def disable_tools(self):
        for action in (
            self.toolbuttonDownload,
            self.toolbuttonUpload,
            self.actionCreateNewGroup,
            self.actionOpenMapInBrowser,
            self.actionUploadSelectedResources,
            self.actionUpdateStyle,
            self.actionAddStyle,
        ):
            action.setEnabled(False)

        self.actionRefresh.setEnabled(
            self.resource_model.connection_id is not None
        )

    def action_settings(self):
        self.iface.showOptionsDialog(
            self.iface.mainWindow(), "NextGIS Connect"
        )

    def str_to_link(self, text: str, url: str):
        return f'<a href="{url}"><span style=" text-decoration: underline; color:#0000ff;">{text}</span></a>'

    def _show_unsupported_raster_err(self):
        msg = "{}. {}".format(
            self.tr("This type of raster is not supported yet"),
            self.str_to_link(
                self.tr("Please add COG support"),
                "https://docs.nextgis.com/docs_ngcom/source/data_upload.html#ngcom-raster-layer",
            ),
        )
        self.show_info(msg)

    def slotCustomContextMenu(self, qpoint: QPoint):
        index = self.resources_tree_view.indexAt(qpoint)
        if not index.isValid() or index.internalPointer().locked:
            return

        selected_indexes = self.resources_tree_view.selectedIndexes()
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

        if any(
            isinstance(
                ngw_resource,
                (
                    NGWGroupResource,
                    NGWVectorLayer,
                    NGWRasterLayer,
                    NGWWmsLayer,
                    NGWWfsService,
                    NGWOgcfService,
                    NGWWmsService,
                    NGWWmsConnection,
                    NGWQGISVectorStyle,
                    NGWQGISRasterStyle,
                    NGWBaseMap,
                    NGWTmsLayer,
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

        if not is_multiple_selection and isinstance(
            ngw_resource, NGWVectorLayer
        ):
            setting_actions.append(self.actionUpdateNGWVectorLayer)

        if not is_multiple_selection and isinstance(
            ngw_resource, NGWGroupResource
        ):
            creating_actions.append(self.actionCreateNewGroup)

        if not is_multiple_selection and isinstance(
            ngw_resource, (NGWVectorLayer, NGWPostgisLayer)
        ):
            creating_actions.extend(
                [
                    self.actionCreateWFSService,
                    self.actionCreateOgcService,
                    self.actionCreateWMSService,
                ]
            )

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

        if not is_multiple_selection and isinstance(ngw_resource, NGWWebMap):
            services_actions.append(self.actionOpenMapInBrowser)

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

    def trvDoubleClickProcess(self, index):
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        if isinstance(ngw_resource, NGWWebMap):
            self.__action_open_map()

    def open_ngw_resource_page(self):
        sel_index = self.resources_tree_view.selectionModel().currentIndex()

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
        selected_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        if not selected_index.isValid():
            return

        self.resources_tree_view.rename_resource(selected_index)

    def __action_open_map(self):
        sel_index = self.resources_tree_view.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            url = ngw_resource.get_display_url()
            QDesktopServices.openUrl(QUrl(url))

    def _add_with_style(self, resource):
        default_style = None
        children = resource.get_children()
        style_resources = [
            child for child in children if isinstance(child, NGWQGISStyle)
        ]

        current_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        current_resource = current_index.data(QNGWResourceItem.NGWResourceRole)
        group_add = isinstance(current_resource, NGWGroupResource)

        if len(style_resources) == 1 or group_add:
            default_style = None
        elif len(style_resources) > 1:
            if self.resource_model.canFetchMore(current_index):
                for child in children:
                    self.resource_model.addNGWResourceToTree(
                        current_index, child
                    )

            dialog = NGWLayerStyleChooserDialog(
                self.tr("Select style"),
                current_index,
                self.resource_model,
                self,
            )
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                sel_index = dialog.selectedStyleIndex()
                if sel_index is not None and sel_index.isValid():
                    default_style = sel_index.data(
                        QNGWResourceItem.NGWResourceRole
                    )

        if resource.type_id == NGWVectorLayer.type_id:
            self.__add_gpkg_layer(resource, style_resources, default_style)
        elif resource.type_id == NGWRasterLayer.type_id:
            add_resource_as_cog_raster(
                resource, style_resources, default_style
            )
        elif resource.type_id == NGWPostgisLayer.type_id:
            self.__add_postgis_layer(resource, style_resources, default_style)

    def __export_to_qgis(self):
        def is_folder(index: QModelIndex) -> bool:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            return isinstance(ngw_resource, NGWGroupResource)

        def is_webmap(index: QModelIndex) -> bool:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            return isinstance(ngw_resource, NGWWebMap)

        selection_model = self.resources_tree_view.selectionModel()
        assert selection_model is not None
        selected_indexes = selection_model.selectedIndexes()
        self.__preprocess_indexes_list(selected_indexes)

        def save_command(job) -> None:
            insertion_point = self.iface.layerTreeInsertionPoint()
            self._queue_to_add.append(
                AddLayersCommand(
                    job.job_uuid, insertion_point, selected_indexes
                )
            )

        # Fetch group tree if group resource is selected
        group_indexes = list(filter(is_folder, selected_indexes))
        job = self.resource_model.fetch_group(group_indexes)
        if job is not None:
            save_command(job)
            return

        # Fetch group tree if group resource is selected
        webmap_indexes = list(filter(is_webmap, selected_indexes))
        job = self.resource_model.fetch_webmap_resources(webmap_indexes)
        if job is not None:
            save_command(job)
            return

        job = self.resource_model.fetch_services_if_needed(selected_indexes)
        if job is not None:
            save_command(job)
            return

        # Make stubs for vector layers
        model = self.resource_model
        download_job = model.download_vector_layers_if_needed(selected_indexes)
        if download_job is not None:
            save_command(download_job)
            return

        plugin = NgConnectInterface.instance()
        plugin.disable_synchronization()

        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        insertion_point = self.iface.layerTreeInsertionPoint()
        backup_point = InsertionPoint(insertion_point)

        for selected_index in selected_indexes:
            tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)
            added = self.__add_resource_to_qgis(
                selected_index, InsertionPoint(insertion_point)
            )
            if added:
                insertion_point.position += 1

        tree_rigistry_bridge.setLayerInsertionPoint(backup_point)

        plugin.enable_synchronization()

    def __preprocess_indexes_list(
        self, ngw_indexes: List[QModelIndex]
    ) -> None:
        def has_parent_in_list(index: QModelIndex) -> bool:
            index = index.parent()
            while index.isValid():
                if index in ngw_indexes:
                    return True
                index = index.parent()
            return False

        # auto_checked_types = (
        #     NGWGroupResource, NGWVectorLayer, NGWQGISVectorStyle
        # )

        i = 0
        for ngw_index in ngw_indexes:
            # ngw_resource = ngw_index.data(QNGWResourceItem.NGWResourceRole)
            # if not isinstance(ngw_resource, auto_checked_types):
            #     i += 1
            #     continue

            if not ngw_index.isValid() or has_parent_in_list(ngw_index):
                del ngw_indexes[i]
            else:
                i += 1

    def __add_resource_to_qgis(
        self,
        index: QModelIndex,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> bool:
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(ngw_resource.connection_id)
        assert connection is not None
        try:
            if isinstance(ngw_resource, NGWVectorLayer):
                self._add_with_style(ngw_resource)
            elif isinstance(ngw_resource, NGWQGISVectorStyle):
                parent_resource = index.parent().data(
                    QNGWResourceItem.NGWResourceRole
                )
                siblings = cast(
                    List[NGWQGISStyle], parent_resource.get_children()
                )
                if isinstance(parent_resource, NGWPostgisLayer):
                    self.__add_postgis_layer(
                        parent_resource, siblings, ngw_resource
                    )
                elif isinstance(parent_resource, NGWVectorLayer):
                    self.__add_gpkg_layer(
                        parent_resource, siblings, ngw_resource
                    )
                else:
                    logger.error("Unsupported type")

            elif isinstance(ngw_resource, NGWRasterLayer):
                try:
                    self._add_with_style(ngw_resource)
                except UnsupportedRasterTypeException:
                    self._show_unsupported_raster_err()

            elif isinstance(ngw_resource, NGWQGISRasterStyle):
                try:
                    parent_resource: NGWResource = index.parent().data(
                        QNGWResourceItem.NGWResourceRole
                    )
                    siblings = parent_resource.get_children()
                    add_resource_as_cog_raster(
                        parent_resource, siblings, ngw_resource
                    )
                except UnsupportedRasterTypeException:
                    self._show_unsupported_raster_err()
            elif isinstance(ngw_resource, NGWWfsService):
                ignore_z_in_wfs = False
                for layer in ngw_resource.get_layers():
                    if ignore_z_in_wfs:
                        break
                    source_layer = ngw_resource.get_source_layer(
                        layer["resource_id"]
                    )
                    if isinstance(source_layer, NGWVectorLayer):
                        if source_layer.is_geom_with_z():
                            res = self.show_msg_box(
                                self.tr(
                                    "You are trying to add a WFS service containing a layer with Z dimension. "
                                    "WFS in QGIS doesn't fully support editing such geometries. "
                                    "You won't be able to edit and create new features. "
                                    "You will only be able to delete features. "
                                    "To fix this, change geometry type of your layer(s) "
                                    "and recreate WFS service."
                                ),
                                self.tr("Warning"),
                                QMessageBox.Warning,
                                QMessageBox.Ignore | QMessageBox.Cancel,
                            )
                            if res == QMessageBox.Ignore:
                                ignore_z_in_wfs = True
                            else:
                                return False
                add_resource_as_wfs_layers(ngw_resource)
            elif isinstance(ngw_resource, NGWOgcfService):
                add_ogcf_resource(ngw_resource)
            elif isinstance(ngw_resource, NGWWmsService):
                utils.add_wms_layer(
                    ngw_resource.common.display_name,
                    ngw_resource.get_url(),
                    ngw_resource.get_layer_keys(),
                    connection,
                    ask_choose_layers=len(ngw_resource.get_layer_keys()) > 1,
                )
            elif isinstance(ngw_resource, NGWWmsConnection):
                utils.add_wms_layer(
                    ngw_resource.common.display_name,
                    ngw_resource.get_connection_url(),
                    ngw_resource.layers(),
                    connection,
                    ask_choose_layers=len(ngw_resource.layers()) > 1,
                )
            elif isinstance(ngw_resource, NGWWmsLayer):
                utils.add_wms_layer(
                    ngw_resource.common.display_name,
                    ngw_resource.ngw_wms_connection_url,
                    ngw_resource.ngw_wms_layers,
                    connection,
                )
            elif isinstance(ngw_resource, NGWBaseMap):
                self.__add_basemap(ngw_resource)
            elif isinstance(ngw_resource, NGWTmsLayer):
                self.__add_tms_layer(ngw_resource)
            elif isinstance(ngw_resource, NGWPostgisLayer):
                self._add_with_style(ngw_resource)
            elif isinstance(ngw_resource, NGWWebMap):
                self.__add_webmap(ngw_resource, insertion_point)
            elif isinstance(ngw_resource, NGWGroupResource):
                self.__add_group_to_qgis(index, insertion_point)

        except NgConnectError as error:
            NgConnectInterface.instance().show_error(error)

        except Exception as error:
            user_message = self.tr(
                'Resource "{}" can\'t be added to the map'
            ).format(ngw_resource.display_name)
            ng_error = NgConnectError(user_message=user_message)
            ng_error.__cause__ = error

            NgConnectInterface.instance().show_error(ng_error)

            return False

        return True

    def __add_group_to_qgis(
        self,
        group_index: QModelIndex,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> None:
        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint
        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        # Save current insertion point
        insertion_point_backup = InsertionPoint(insertion_point)

        # Create new group and set point to it
        group_resource = group_index.data(QNGWResourceItem.NGWResourceRole)
        qgis_group = insertion_point.group.addGroup(
            group_resource.common.display_name
        )
        assert qgis_group is not None
        insertion_point.group = qgis_group
        insertion_point.position = 0
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)

        # Add content
        model = self.resource_model
        for row in range(model.rowCount(group_index)):
            child_index = model.index(row, 0, group_index)
            child_resource = child_index.data(QNGWResourceItem.NGWResourceRole)
            if not isinstance(
                child_resource, (NGWGroupResource, NGWVectorLayer)
            ):
                continue

            tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)
            added = self.__add_resource_to_qgis(
                child_index, InsertionPoint(insertion_point)
            )
            if added:
                insertion_point.position += 1

        # Restore insertion point
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point_backup)

    def create_group(self):
        sel_index = self.resources_tree_view.selectedIndex()
        # if sel_index is None:
        #     sel_index = self.resource_model.index(0, 0, QModelIndex())
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
            self.resources_tree_view.setCurrentIndex
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

        ngw_current_index = (
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
            self.resources_tree_view.setCurrentIndex
        )
        self.qgis_proj_import_response.done.connect(self.open_create_web_map)
        self.qgis_proj_import_response.done.connect(self.processWarnings)

    def upload_selected_resources(self):
        ngw_current_index = (
            self.resources_tree_view.selectionModel().currentIndex()
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
        self.import_layer_response.done.connect(
            self.resources_tree_view.setCurrentIndex
        )
        self.import_layer_response.done.connect(self.processWarnings)

    def overwrite_ngw_layer(self):
        index = self.resources_tree_view.selectionModel().currentIndex()
        qgs_map_layer = self.iface.mapCanvas().currentLayer()

        result = QMessageBox.question(
            self,
            self.tr("Overwrite resource"),
            self.tr(
                'Resource "{}" will be overwritten with QGIS layer "{}". '
                "Current data will be lost.<br/>Are you sure you want to "
                "overwrite it?"
            ).format(
                index.data(Qt.DisplayRole), html.escape(qgs_map_layer.name())
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        if isinstance(qgs_map_layer, QgsVectorLayer):
            self.resource_model.updateNGWLayer(index, qgs_map_layer)
        else:
            pass

    def edit_metadata(self):
        """Edit metadata table"""
        sel_index = self.resources_tree_view.selectionModel().currentIndex()
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            self.block_gui()

            try:
                self.resources_tree_view.ngw_job_block_overlay.show()
                self.resources_tree_view.ngw_job_block_overlay.text.setText(
                    "<strong>{} {}</strong><br/>".format(
                        self.tr("Get resource metadata"),
                        ngw_resource.common.display_name,
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
        ngw_layer_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        response = self.resource_model.updateQGISStyle(
            qgs_map_layer, ngw_layer_index
        )
        response.done.connect(self.resources_tree_view.setCurrentIndex)

    def add_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        ngw_layer_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        response = self.resource_model.addQGISStyle(
            qgs_map_layer, ngw_layer_index
        )
        response.done.connect(self.resources_tree_view.setCurrentIndex)

    def delete_curent_ngw_resource(self):
        res = QMessageBox.question(
            self,
            self.tr("Delete resource"),
            self.tr("Are you sure you want to remove this resource?"),
            QMessageBox.Yes and QMessageBox.No,
            QMessageBox.Yes,
        )

        if res == QMessageBox.Yes:
            selected_index = (
                self.resources_tree_view.selectionModel().currentIndex()
            )
            self.delete_resource_response = self.resource_model.deleteResource(
                selected_index
            )
            self.delete_resource_response.done.connect(
                self.resources_tree_view.setCurrentIndex
            )

    def _downloadRasterSource(self, ngw_lyr, raster_file=None):
        """Download raster layer source file
        using QNetworkAccessManager.
        Download and write file by chunks
        using readyRead signal

        return QFile object
        """
        if not raster_file:
            raster_file = QTemporaryFile()
        else:
            raster_file = QFile(raster_file)

        url = f"{ngw_lyr.get_absolute_api_url()}/download"

        def write_chuck():
            if reply.error():
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
                    ngw_src.common.display_name, readed_size * 100 / total_size
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
                ngw_src.common.display_name,
                "ogr",
            )
            if not qgs_layer.isValid():
                raise Exception(
                    f'Layer "{ngw_src.common.display_name}" can\'t be added to the map!'
                )
            qgs_layer.dataProvider().setEncoding("UTF-8")

        elif ngw_src.type_id == NGWRasterLayer.type_id:
            raster_file = self._downloadRasterSource(ngw_src)
            qgs_layer = QgsRasterLayer(
                raster_file.fileName(), ngw_src.common.display_name, "gdal"
            )
            if not qgs_layer.isValid():
                logger.error("Failed to add raster layer to QGIS")
                raise Exception(
                    f'Layer "{ngw_src.common.display_name}" can\'t be added to the map!'
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
                style_name=style_resource.common.display_name,
            )
            self.dwn_qml_file.remove()
            ngw_res.update()

        return ngw_res

    def copy_curent_ngw_resource(self):
        """Copying the selected ngw resource.
        Only GUI stuff here, main part
        in _copy_resource function
        """
        sel_index = self.resources_tree_view.selectionModel().currentIndex()
        if sel_index.isValid():
            # ckeckbox
            res = QMessageBox.question(
                self,
                self.tr("Duplicate Resource"),
                self.tr("Are you sure you want to duplicate this resource?"),
                QMessageBox.Yes and QMessageBox.No,
                QMessageBox.Yes,
            )
            if res == QMessageBox.No:
                return

            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            # block gui
            self.resources_tree_view.ngw_job_block_overlay.show()
            self.block_gui()
            self.resources_tree_view.ngw_job_block_overlay.text.setText(
                "<strong>{} {}</strong><br/>".format(
                    self.tr("Duplicating"), ngw_resource.common.display_name
                )
            )
            # main part
            try:
                ngw_result = self._copy_resource(ngw_resource)
                self.__add_resource_to_tree(ngw_result)
            except UnsupportedRasterTypeException:
                self._show_unsupported_raster_err()
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
        selected_index = (
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
        response.done.connect(self.resources_tree_view.setCurrentIndex)
        adder = (
            self.add_created_wfs_service
            if service_type == "WFS"
            else self.add_created_ogc_service
        )
        response.done.connect(adder)

    def add_created_wfs_service(self, index):
        if not NgConnectSettings().add_layer_after_service_creation:
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        add_resource_as_wfs_layers(ngw_resource)

    def add_created_ogc_service(self, index: QModelIndex) -> None:
        if not NgConnectSettings().add_layer_after_service_creation:
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        add_ogcf_resource(ngw_resource)

    def add_created_wms_service(self, index: QModelIndex) -> None:
        if not NgConnectSettings().add_layer_after_service_creation:
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(ngw_resource.connection_id)
        assert connection is not None
        utils.add_wms_layer(
            ngw_resource.common.display_name,
            ngw_resource.get_url(),
            ngw_resource.get_layer_keys(),
            connection,
            ask_choose_layers=len(ngw_resource.get_layer_keys()) > 1,
        )

    def create_wms_service(self):
        selected_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )

        resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        children = resource.get_children()
        style_resources = [
            child for child in children if isinstance(child, NGWQGISStyle)
        ]
        if len(style_resources) > 0 and self.resource_model.canFetchMore(
            selected_index
        ):
            for child in children:
                self.resource_model.addNGWResourceToTree(selected_index, child)

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

        responce = self.resource_model.createWMSForVector(
            selected_index, ngw_resource_style_id
        )
        responce.done.connect(self.resources_tree_view.setCurrentIndex)
        responce.done.connect(self.add_created_wms_service)

    def create_web_map_for_style(self):
        selected_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        self.create_map_response = self.resource_model.createMapForStyle(
            selected_index
        )

        self.create_map_response.done.connect(self.open_create_web_map)

    def create_web_map_for_layer(self):
        selected_index = (
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
                ngw_resource_style_id = ngw_styles[0].common.id
            elif len(ngw_styles) > 1:
                dlg = NGWLayerStyleChooserDialog(
                    self.tr("Create web map for layer"),
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
            self.resources_tree_view.setCurrentIndex
        )
        self.create_map_response.done.connect(self.open_create_web_map)

    def open_create_web_map(self, index: QModelIndex):
        if (
            not index.isValid()
            or not NgConnectSettings().open_web_map_after_creation
        ):
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        url = ngw_resource.get_display_url()
        QDesktopServices.openUrl(QUrl(url))

    def processWarnings(self, index):
        ngw_model_job_resp = self.sender()
        job_id = ngw_model_job_resp.job_id
        if len(ngw_model_job_resp.warnings) > 0:
            dlg = ExceptionsListDialog(
                self.tr("NextGIS Connect operation errors"), self
            )
            for w in ngw_model_job_resp.warnings:
                (
                    w_msg,
                    w_msg_ext,
                    icon,
                ) = self.__get_model_exception_description(job_id, w)
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
        selected_index = (
            self.resources_tree_view.selectionModel().currentIndex()
        )
        ngw_qgis_style = selected_index.data(QNGWResourceItem.NGWResourceRole)

        settings = QgsSettings()
        last_used_dir = settings.value("style/lastStyleDir", QDir.homePath())
        style_name = ngw_qgis_style.common.display_name
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
        selected_index = (
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
            self.dwn_qml_file.close()

            if not is_success:
                error_message = self.tr(
                    f"{error_message} at line {line} column {column}"
                )

        if len(error_message) != 0:
            user_message = self.tr("An error occured when copying the style")
            error = NgConnectError(user_message=user_message)
            error.add_note(error_message)
            NgConnectInterface.instance().show_error(error)
            return

        # Copy style
        QGSCLIPBOARD_STYLE_MIME = "application/qgis.style"
        data = dom_document.toByteArray()
        text = dom_document.toString()
        utils.set_clipboard_data(QGSCLIPBOARD_STYLE_MIME, data, text)

    def show_msg_box(self, text, title, icon, buttons):
        box = QMessageBox()
        box.setText(text)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setStandardButtons(buttons)
        return box.exec()

    def show_info(self, text, title=None):
        if title is None:
            title = self.tr("Information")
        self.show_msg_box(text, title, QMessageBox.Information, QMessageBox.Ok)

    def show_error(self, text, title=None):
        if title is None:
            title = self.tr("Error")
        self.show_msg_box(text, title, QMessageBox.Critical, QMessageBox.Ok)

    def __add_layers_after_finish(self, job_uuid: str):
        found_i = -1
        for i in range(len(self._queue_to_add)):
            if self._queue_to_add[i].job_uuid == job_uuid:
                found_i = i
                break
        if found_i == -1:
            return

        project = QgsProject.instance()
        assert project is not None
        tree_rigistry_bridge = project.layerTreeRegistryBridge()
        assert tree_rigistry_bridge is not None

        model = self.resource_model
        command = self._queue_to_add[found_i]

        del self._queue_to_add[found_i]

        def is_webmap(index: QModelIndex) -> bool:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            return isinstance(ngw_resource, NGWWebMap)

        # Fetch group tree if group resource is selected
        webmap_indexes = list(filter(is_webmap, command.ngw_indexes))
        job = self.resource_model.fetch_webmap_resources(webmap_indexes)
        if job is not None:
            command.job_uuid = job.job_uuid
            self._queue_to_add.append(command)
            return

        job = self.resource_model.fetch_services_if_needed(command.ngw_indexes)
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

        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint

        insertion_point = InsertionPoint(command.insertion_point)
        backup_point = self.iface.layerTreeInsertionPoint()

        for selected_index in command.ngw_indexes:
            tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)
            added = self.__add_resource_to_qgis(
                selected_index, InsertionPoint(insertion_point)
            )
            if added:
                insertion_point.position += 1

        tree_rigistry_bridge.setLayerInsertionPoint(backup_point)

        plugin = NgConnectInterface.instance()
        plugin.synchronize_layers()

    def __on_ngstd_user_info_updated(self):
        connections_manager = NgwConnectionsManager()
        current_connection = connections_manager.current_connection
        if (
            current_connection is None
            or current_connection.method != "NextGIS"
        ):
            return

        self.reinit_tree(force=True)

    def __add_gpkg_layer(
        self,
        vector_layer: NGWVectorLayer,
        styles: List[NGWQGISStyle],
        default_style: Optional[NGWQGISVectorStyle] = None,
    ) -> Optional[QgsVectorLayer]:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(vector_layer.connection_id)
        assert connection is not None

        cache_manager = NgConnectCacheManager()
        connection_path = (
            Path(cache_manager.cache_directory) / connection.domain_uuid
        )

        uri = detached_layer_uri(
            connection_path / f"{vector_layer.common.id}.gpkg"
        )
        qgs_gpkg_layer = QgsVectorLayer(
            uri, vector_layer.common.display_name, "ogr"
        )
        if not qgs_gpkg_layer.isValid():
            error = ContainerError(
                f'Layer "{vector_layer.common.display_name}" can\'t be added to the map!'
            )
            error.add_note(f"Uri: {uri}")
            raise error

        qgs_gpkg_layer.dataProvider().setEncoding("UTF-8")  # type: ignore

        _add_all_styles_to_layer(qgs_gpkg_layer, styles, default_style)

        _add_aliases(qgs_gpkg_layer, vector_layer)

        QgsProject.instance().addMapLayer(qgs_gpkg_layer)

        return qgs_gpkg_layer

    def __add_basemap(
        self, basemap: NGWBaseMap, display_name: Optional[str] = None
    ) -> QgsRasterLayer:
        project = QgsProject.instance()
        assert project is not None

        if display_name is None:
            uri, display_name, provider = basemap.layer_params
        else:
            uri, _, provider = basemap.layer_params

        layer = QgsRasterLayer(uri, display_name, provider)
        layer.setCustomProperty("ngw_connection_id", basemap.connection_id)
        layer.setCustomProperty("ngw_resource_id", basemap.resource_id)
        project.addMapLayer(layer)

        return layer

    def __add_tms_layer(
        self, tms_layer: NGWTmsLayer, display_name: Optional[str] = None
    ) -> QgsRasterLayer:
        project = QgsProject.instance()
        assert project is not None

        layer_params = tms_layer.layer_params()

        if display_name is None:
            uri, display_name, provider = layer_params
        else:
            uri, _, provider = layer_params

        layer = QgsRasterLayer(uri, display_name, provider)
        layer.setCustomProperty("ngw_connection_id", tms_layer.connection_id)
        layer.setCustomProperty("ngw_resource_id", tms_layer.resource_id)
        project.addMapLayer(layer)

        return layer

    def __add_postgis_layer(
        self,
        postgis_layer: NGWPostgisLayer,
        styles: List[NGWQGISStyle],
        default_style: Optional[NGWQGISVectorStyle] = None,
    ) -> QgsVectorLayer:
        project = QgsProject.instance()
        assert project is not None

        postgis_connection = cast(
            NGWPostgisConnection,
            self.resource_model.getResourceByNGWId(
                postgis_layer.service_resource_id
            ),
        )
        uri, display_name, provider = postgis_layer.layer_params(
            postgis_connection
        )

        qgs_layer = QgsVectorLayer(uri, display_name, provider)
        qgs_layer.setCustomProperty(
            "ngw_connection_id", postgis_layer.connection_id
        )
        qgs_layer.setCustomProperty(
            "ngw_resource_id", postgis_layer.resource_id
        )

        _add_all_styles_to_layer(qgs_layer, styles, default_style)
        _add_aliases(qgs_layer, postgis_layer)
        _add_lookup_tables(qgs_layer, postgis_layer)

        QgsProject.instance().addMapLayer(qgs_layer)

        return qgs_layer

    def __add_webmap(
        self,
        webmap: NGWWebMap,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> None:
        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        insertion_point_backup = InsertionPoint(insertion_point)

        webmap_group = insertion_point.group.addGroup(webmap.display_name)
        assert webmap_group is not None
        insertion_point.group = webmap_group
        insertion_point.position = 0
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)

        self.__add_webmap_tree(webmap, insertion_point)
        self.__add_webmap_basemaps(webmap, insertion_point)
        self.__set_webmap_extent(webmap)

        # Restore insertion point
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point_backup)

    def __add_webmap_tree(
        self,
        webmap: NGWWebMap,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> None:
        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        for child in webmap.root.children:
            tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)

            is_added = False

            if isinstance(child, NGWWebMapGroup):
                is_added = self.__add_webmap_group(
                    child, InsertionPoint(insertion_point)
                )
            elif isinstance(child, NGWWebMapLayer):
                is_added = self.__add_webmap_layer(child)

            if is_added:
                insertion_point.position += 1

    def __add_webmap_group(
        self,
        webmap_group: NGWWebMapGroup,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> bool:
        InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint
        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()

        # Save current insertion point
        insertion_point_backup = InsertionPoint(insertion_point)

        # Create group
        group = insertion_point.group.addGroup(webmap_group.display_name)
        group.setExpanded(webmap_group.expanded)
        assert group is not None
        insertion_point.group = group
        insertion_point.position = 0

        for child in webmap_group.children:
            tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)

            is_added = False

            if isinstance(child, NGWWebMapGroup):
                is_added = self.__add_webmap_group(
                    child, InsertionPoint(insertion_point)
                )
            elif isinstance(child, NGWWebMapLayer):
                is_added = self.__add_webmap_layer(child)

            if is_added:
                insertion_point.position += 1

        # Restore insertion point
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point_backup)

        return True

    def __add_webmap_layer(
        self,
        webmap_layer: NGWWebMapLayer,
    ) -> bool:
        layer_resource = self.resource_model.getResourceByNGWId(
            webmap_layer.style_parent_id
        )

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(
            layer_resource.connection_id
        )
        assert connection is not None

        if isinstance(layer_resource, NGWRasterLayer):
            if connection.auth_config_id is not None:
                auth_manager = QgsApplication.instance().authManager()
                auth_method = auth_manager.configAuthMethodKey(
                    connection.auth_config_id
                )
                if auth_method != "Basic":
                    return False

        style_resource = self.resource_model.getResourceByNGWId(
            webmap_layer.layer_style_id
        )
        if style_resource is None:
            return False

        styles = [style_resource]

        if isinstance(layer_resource, NGWVectorLayer):
            qgs_layer = self.__add_gpkg_layer(layer_resource, styles)  # type: ignore

        elif isinstance(layer_resource, NGWPostgisLayer):
            qgs_layer = self.__add_postgis_layer(layer_resource, styles)  # type: ignore

        elif isinstance(layer_resource, NGWRasterLayer):
            qgs_layer = add_resource_as_cog_raster(layer_resource, styles)

        elif isinstance(style_resource, NGWWmsLayer):
            qgs_layer = utils.add_wms_layer(
                style_resource.common.display_name,
                style_resource.ngw_wms_connection_url,
                style_resource.ngw_wms_layers,
                connection,
            )

        elif isinstance(style_resource, NGWTmsLayer):
            qgs_layer = self.__add_tms_layer(style_resource)

        else:
            logger.error("Wrong layer resource")
            return False

        qgs_layer.setName(webmap_layer.display_name)

        if qgs_layer is None:
            logger.error("Layer wasn't created")
            return False

        node = QgsProject.instance().layerTreeRoot().findLayer(qgs_layer.id())
        if node is None:
            return False

        node.setItemVisibilityChecked(webmap_layer.is_visible)

        node.setExpanded(webmap_layer.legend)  # type: ignore

        return True

    def __add_webmap_basemaps(
        self,
        webmap: NGWWebMap,
        insertion_point: QgsLayerTreeRegistryBridge.InsertionPoint,
    ) -> None:
        if len(webmap.basemaps) == 0:
            return

        basemaps_group = insertion_point.group.addGroup(self.tr("Basemaps"))
        assert basemaps_group is not None
        insertion_point.group = basemaps_group
        insertion_point.position = 0

        project = QgsProject.instance()
        tree_rigistry_bridge = project.layerTreeRegistryBridge()
        tree_rigistry_bridge.setLayerInsertionPoint(insertion_point)

        for basemap in webmap.basemaps:
            basemap_resource = self.resource_model.getResourceByNGWId(
                basemap.resource_id
            )
            if basemap_resource is None:
                logger.warning("Can't find basemap")
                continue

            assert isinstance(basemap_resource, NGWBaseMap)
            basemap_layer = self.__add_basemap(
                basemap_resource, basemap.display_name
            )

            if basemap.opacity is not None:
                basemap_layer.setOpacity(basemap.opacity)

    def __set_webmap_extent(self, webmap: NGWWebMap) -> None:
        extent = webmap.extent
        if extent is None:
            return

        self.iface.mapCanvas().setReferencedExtent(extent)
        self.iface.mapCanvas().refresh()


class NGWPanelToolBar(QToolBar):
    def __init__(self):
        super().__init__(None)

        self.setIconSize(QSize(24, 24))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def contextMenuEvent(self, event):
        event.accept()

    def resizeEvent(self, event):
        super().setIconSize(QSize(24, 24))
        event.accept()
