# -*- coding: utf-8 -*-

# -*- coding: utf-8 -*-
"""
/***************************************************************************
 TreePanel
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
import os
import sys
import json
import functools

from PyQt4 import uic
from PyQt4.QtGui import *
from PyQt4.QtCore import *
from PyQt4.QtNetwork import *

from qgis.core import QgsMessageLog, QgsProject, QgsVectorLayer, QgsRasterLayer, QgsNetworkAccessManager
from qgis.gui import QgsMessageBar

from ngw_api.core.ngw_error import NGWError
from ngw_api.core.ngw_group_resource import NGWGroupResource
from ngw_api.core.ngw_vector_layer import NGWVectorLayer
from ngw_api.core.ngw_raster_layer import NGWRasterLayer
from ngw_api.core.ngw_webmap import NGWWebMap
from ngw_api.core.ngw_wfs_service import NGWWfsService
from ngw_api.core.ngw_mapserver_style import NGWMapServerStyle
from ngw_api.core.ngw_qgis_vector_style import NGWQGISVectorStyle
from ngw_api.core.ngw_raster_style import NGWRasterStyle

from ngw_api.qt.qt_ngw_resource_item import QNGWResourceItemExt

from ngw_api.qgis.ngw_connection_edit_dialog import NGWConnectionEditDialog
from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from ngw_api.qgis.resource_to_map import *

from ngw_api.qt.qt_ngw_resource_base_model import QNGWResourcesModelExeption
from ngw_api.qgis.ngw_resource_model_4qgis import QNGWResourcesModel4QGIS

from ngw_api.utils import setLogger

from settings_dialog import SettingsDialog
from plugin_settings import PluginSettings

from dialog_choose_style import NGWLayerStyleChooserDialog
from dialog_qgis_proj_import import DialogImportQGISProj

from action_style_import_or_update import ActionStyleImportUpdate

this_dir = os.path.dirname(__file__).decode(sys.getfilesystemencoding())

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    this_dir, 'tree_panel_base.ui'))

ICONS_PATH = os.path.join(this_dir, 'icons/')


def qgisLog(msg, level=QgsMessageLog.INFO):
    QgsMessageLog.logMessage(msg, PluginSettings._product, level)

def ngwApiLog(msg, level=QgsMessageLog.INFO):
    QgsMessageLog.logMessage(msg, "NGW API", level)

setLogger(ngwApiLog)

class TreePanel(QDockWidget):
    def __init__(self, iface, parent=None):
        # init dock
        super(TreePanel, self).__init__(parent)

        self.setWindowTitle(self.tr('NextGIS Resources'))

        # init internal control
        self.inner_control = TreeControl(iface, self)
        self.inner_control.setWindowFlags(Qt.Widget)
        self.setWidget(self.inner_control)


class TreeControl(QMainWindow, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super(TreeControl, self).__init__(parent)

        # parent.destroyed.connect(self.__stop)

        self.setupUi(self)
        self.iface = iface

        # Do not use ui toolbar
        # self.removeToolBar(self.mainToolBar)

        # Open ngw resource in browser ----------------------------------------
        self.actionOpenInNGW = QAction(
            QIcon(),
            self.tr("Open in WebGIS"),
            self
        )
        self.actionOpenInNGW.triggered.connect(self.open_ngw_resource_page)

        # Rename ngw resource --------------------------------------------------
        self.actionRename = QAction(
            QIcon(),
            self.tr("Rename"),
            self
        )
        self.actionRename.triggered.connect(self.rename_ngw_resource)

        # Export to QGIS ------------------------------------------------------
        self.actionExport = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionExport.svg')),
            self.tr("Add to QGIS"),
            self
        )
        self.actionExport.triggered.connect(self.__export_to_qgis)

        # Import to NGW -------------------------------------------------------
        self.actionImportQGISResource = QAction(
            self.tr("Import selected layer(s)"),
            self.iface.legendInterface()
        )
        self.actionImportQGISResource.triggered.connect(self.import_layers)
        self.actionImportQGISResource.setEnabled(False)

        self.actionImportUpdateStyle = ActionStyleImportUpdate()
        self.actionImportUpdateStyle.triggered.connect(self.import_update_style)

        self.actionImportQGISProject = QAction(
            self.tr("Import current project"),
            self.iface.legendInterface()
        )
        self.actionImportQGISProject.triggered.connect(self.import_qgis_project)

        self.menuImport = QMenu(
            self.tr("Add to Web GIS"),
            self
        )
        self.menuImport.setIcon(
            QIcon(os.path.join(ICONS_PATH, 'mActionImport.svg'))
        )
        self.menuImport.menuAction().setIconVisibleInMenu(False)
        self.menuImport.addAction(self.actionImportQGISResource)
        self.menuImport.addAction(self.actionImportUpdateStyle)
        self.menuImport.addAction(self.actionImportQGISProject)

        # Create new group ----------------------------------------------------
        self.actionCreateNewGroup = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.svg')),
            self.tr("Create new group"),
            self
        )
        self.actionCreateNewGroup.setToolTip(self.tr("Create new resource group"))
        self.actionCreateNewGroup.triggered.connect(self.create_group)

        # Create style --------------------------------------------------------
        # self.actionCreateStyle = QAction(
        #     QIcon(),
        #     self.tr("Create style"),
        #     self
        # )
        # self.actionCreateStyle.setToolTip(self.tr("Create style"))
        # self.actionCreateStyle.triggered.connect(self.create_style)

        # Create web map ------------------------------------------------------
        self.actionCreateWebMap4Layer = QAction(
            QIcon(),
            self.tr("Create Web Map"),
            self
        )
        self.actionCreateWebMap4Layer.setToolTip(self.tr("Create Web Map"))
        self.actionCreateWebMap4Layer.triggered.connect(self.create_web_map_for_layer)

        self.actionCreateWebMap4Style = QAction(
            QIcon(),
            self.tr("Create Web Map"),
            self
        )
        self.actionCreateWebMap4Style.setToolTip(self.tr("Create Web Map"))
        self.actionCreateWebMap4Style.triggered.connect(self.create_web_map_for_style)

        # Download QGIS style as QML file -------------------------------------
        self.actionDownload = QAction(
            QIcon(),
            self.tr("Download as QML"),
            self
        )
        self.actionDownload.setToolTip(self.tr("Download style as QML file"))
        self.actionDownload.triggered.connect(self.downloadQML)

        # Create WFS service --------------------------------------------------
        self.actionCreateWFSService = QAction(
            QIcon(),
            self.tr("Create WFS service"),
            self
        )
        self.actionCreateWFSService.setToolTip(self.tr("Create WFS service"))
        self.actionCreateWFSService.triggered.connect(self.create_wfs_service)

        # Create WMS service --------------------------------------------------
        self.actionCreateWMSService = QAction(
            QIcon(),
            self.tr("Create WMS service"),
            self
        )
        self.actionCreateWMSService.setToolTip(self.tr("Create WMS service"))
        self.actionCreateWMSService.triggered.connect(self.create_wms_service)


        # Delete resource -----------------------------------------------------
        self.actionDeleteResource = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionDelete.svg')),
            self.tr("Delete"),
            self
        )
        self.actionDeleteResource.setToolTip(self.tr("Delete resource"))
        self.actionDeleteResource.triggered.connect(self.delete_curent_ngw_resource)

        # Open map ------------------------------------------------------------
        self.actionOpenMapInBrowser = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionOpenMap.svg')),
            self.tr("Open map in browser"),
            self
        )
        self.actionOpenMapInBrowser.setToolTip(self.tr("Open map in browser"))
        self.actionOpenMapInBrowser.triggered.connect(self.__action_open_map)

        self.actionRefresh = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionRefresh.svg')),
            self.tr("Refresh"),
            self
        )
        self.actionRefresh.setToolTip(self.tr("Refresh"))
        self.actionRefresh.triggered.connect(self.__action_refresh_tree)

        self.actionSettings = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionSettings.svg')),
            self.tr("Settings"),
            self
        )
        self.actionSettings.setToolTip(self.tr("Settings"))
        self.actionSettings.triggered.connect(self.action_settings)

        # Add toolbar
        self.main_tool_bar = NGWPanelToolBar()
        self.addToolBar(self.main_tool_bar)

        self.main_tool_bar.addAction(self.actionExport)
        self.toolbuttonImport = QToolButton()
        self.toolbuttonImport.setPopupMode(QToolButton.InstantPopup)
        self.toolbuttonImport.setMenu(self.menuImport)
        self.toolbuttonImport.setIcon(self.menuImport.icon())
        self.toolbuttonImport.setText(self.menuImport.title())
        self.toolbuttonImport.setToolTip(self.menuImport.title())

        self.main_tool_bar.addWidget(self.toolbuttonImport)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionCreateNewGroup)
        self.main_tool_bar.addAction(self.actionRefresh)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionOpenMapInBrowser)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionSettings)

        # ngw resources model
        self._resource_model = QNGWResourcesModel4QGIS(self)

        self._resource_model.errorOccurred.connect(self.__model_error_process)
        self._resource_model.warningOccurred.connect(self.__model_warning_process)
        self._resource_model.jobStarted.connect(self.__modelJobStarted)
        self._resource_model.jobStatusChanged.connect(self.__modelJobStatusChanged)
        self._resource_model.jobFinished.connect(self.__modelJobFinished)
        self.blocked_jobs = {
            self._resource_model.JOB_CREATE_NGW_GROUP_RESOURCE: self.tr("Resource is being created"),
            self._resource_model.JOB_DELETE_NGW_RESOURCE: self.tr("Resource is being deleted"),
            self._resource_model.JOB_IMPORT_QGIS_RESOURCE: self.tr("Layer is being imported"),
            self._resource_model.JOB_IMPORT_QGIS_PROJECT: self.tr("Project is being imported"),
            self._resource_model.JOB_CREATE_NGW_WFS_SERVICE: self.tr("WFS service is being created"),
            self._resource_model.JOB_CREATE_NGW_WMS_SERVICE: self.tr("WMS service is being created"),
            self._resource_model.JOB_CREATE_NGW_WEB_MAP: self.tr("Web map is being created"),
            self._resource_model.JOB_CREATE_NGW_STYLE: self.tr("Style for layer is being created"),
            self._resource_model.JOB_RENAME_RESOURCE: self.tr("Resource is being renamed"),
        }

        # ngw resources view
        self.trvResources = NGWResourcesTreeView(self)
        self.trvResources.setModel(self._resource_model)
        self.trvResources.customContextMenuRequested.connect(self.slotCustomContextMenu)
        self.trvResources.itemDoubleClicked.connect(self.trvDoubleClickProcess)
        self.trvResources.selectionModel().currentChanged.connect(self.ngwResourcesSelectionChanged)

        self.nrw_reorces_tree_container.addWidget(self.trvResources)

        self.iface.initializationCompleted.connect(self.reinit_tree)
        # update state
        if QSettings().value("proxy/proxyEnabled", None) is not None:
            self.reinit_tree()

        # Help message label
        url = "http://%s/docs_ngcom/source/ngqgis_connect.html" % self.tr("docs.nextgis.com")
        self.helpMessageLabel.setText(
            ' <span style="font-weight:bold;font-size:12px;color:blue;">?    </span><a href="%s">%s</a>' % (
                url,
                self.tr("Help")
            )
        )

        # ----------------------------------------------
        # Configurate new WebGIS InfoWidget
        # This widget may be useful in the future
        self.webGISCreationMessageWidget.setVisible(False)
        # self.webGISCreationMessageCloseLable.linkActivated.connect(self.__closeNewWebGISInfoWidget)
        # if PluginSettings.webgis_creation_message_closed_by_user():
        #     self.webGISCreationMessageWidget.setVisible(False)
        # ----------------------------------------------

        self.main_tool_bar.setIconSize(QSize(24, 24))

        self.qgisResourcesSelectionChanged()
        self.iface.currentLayerChanged.connect(
            self.qgisResourcesSelectionChanged
        )
        QgsMapLayerRegistry.instance().layersAdded.connect(
            self.qgisResourcesSelectionChanged
        )
        QgsMapLayerRegistry.instance().layersRemoved.connect(
            self.qgisResourcesSelectionChanged
        )

    # def __closeNewWebGISInfoWidget(self, link):
    #     self.webGISCreationMessageWidget.setVisible(False)
    #     PluginSettings.set_webgis_creation_message_closed_by_user(True)

    def checkImportActionsAvailability(self):
        current_qgis_layer = self.iface.mapCanvas().currentLayer()
        index = self.trvResources.selectionModel().currentIndex()
        ngw_resource = None
        if index is not None:
            ngw_resource = index.data(QNGWResourceItemExt.NGWResourceRole)

        if current_qgis_layer is None:
            self.actionImportQGISResource.setEnabled(False)
        elif isinstance(current_qgis_layer, (QgsVectorLayer, QgsRasterLayer)):
            self.actionImportQGISResource.setEnabled(True)

        if isinstance(ngw_resource, NGWQGISVectorStyle):
            ngw_vector_layer = index.parent().data(QNGWResourceItemExt.NGWResourceRole)
            self.actionImportUpdateStyle.setEnabled(current_qgis_layer, ngw_vector_layer)
        else:
            self.actionImportUpdateStyle.setEnabled(current_qgis_layer, ngw_resource)

        self.actionImportQGISProject.setEnabled(
            QgsMapLayerRegistry.instance().count() != 0
        )

        self.toolbuttonImport.setEnabled(
            self.actionImportQGISResource.isEnabled() or self.actionImportQGISProject.isEnabled() or self.actionImportUpdateStyle.isEnabled()
        )

        # TODO: NEED REFACTORING! Make isCompatible methods!
        self.actionExport.setEnabled(
            isinstance(
                ngw_resource,
                (
                    NGWWfsService,
                    NGWVectorLayer,
                    NGWQGISVectorStyle
                )
            )
        )
        # enable/dis webmap
        self.actionOpenMapInBrowser.setEnabled(isinstance(ngw_resource, NGWWebMap))

    def qgisResourcesSelectionChanged(self):
        self.checkImportActionsAvailability()

    def ngwResourcesSelectionChanged(self, selected, deselected):
        self.checkImportActionsAvailability()
    
    def __msg_in_qgis_mes_bar(self, message, level=QgsMessageBar.INFO, duration=0):
        self.iface.messageBar().pushMessage(
            self.tr('NextGIS Connect'),
            message,
            level,
            duration,
        )

    def __model_warning_process(self, job, exception):
        self.__model_exception_process(job, exception, QgsMessageBar.WARNING)

    def __model_error_process(self, job, exception):
        self.__model_exception_process(job, exception, QgsMessageBar.CRITICAL)

    def __model_exception_process(self, job, exception, level):
        if isinstance(exception, NGWError):
            self.__ngw_error_process(exception, level)

        elif isinstance(exception, QNGWResourcesModelExeption):
            if exception.ngw_error is None:
                self.__msg_in_qgis_mes_bar(
                    "%s" % exception,
                    level=level
                )
            else:
                self.__ngw_error_process(
                    exception.ngw_error,
                    level,
                    "[%s] " % str(exception)
                )
        else:
            self.__msg_in_qgis_mes_bar(
                "%s: %s" % (type(exception), exception),
                level=level
            )

    def __ngw_error_process(self, exception, level, prefix=""):
        try:
            exeption_dict = json.loads(exception.message)
            exeption_type = exeption_dict.get("exception")

            name_of_conn = NgwPluginSettings.get_selected_ngw_connection_name()

            if exeption_type in ["HTTPForbidden", "ForbiddenError"]:

                self.__msg_in_qgis_mes_bar(
                    "WebGIS access denied",
                    level=level
                )

                conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)
                dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett, only_password_change=True)
                dlg.setWindowTitle(
                    self.tr("Access denied. Enter your login.")
                )
                res = dlg.exec_()
                if res:
                    conn_sett = dlg.ngw_connection_settings
                    NgwPluginSettings.save_ngw_connection(conn_sett)
                    self.reinit_tree()
                del dlg

            elif exeption_type == "ConnectionError":
                self.__msg_in_qgis_mes_bar(
                    prefix + "Webgis connection failed. See logs for detail.",
                    level=level
                )
                qgisLog(
                    prefix + "Webgis connection failed: %s" % exeption_dict.get("message", ""),
                )

            else:
                self.__msg_in_qgis_mes_bar(
                    prefix + "WebGIS answered - " + exeption_dict.get("message", ""),
                    level=level
                )

        except Exception:
            self.__msg_in_qgis_mes_bar(
                prefix + "Received unknown error. See logs.",
                level=level
            )
            qgisLog(
                prefix + "Received unknown error. See logs.",
            )
            qgisLog(
                exception.message,
            )

    def __modelJobStarted(self, job_id):
        if job_id in self.blocked_jobs:
            self.trvResources.addBlockedJob(self.blocked_jobs[job_id])

    def __modelJobStatusChanged(self, job_id, status):
        if job_id in self.blocked_jobs:
            self.trvResources.addJobStatus(self.blocked_jobs[job_id], status)

    def __modelJobFinished(self, job_id):
        if job_id in self.blocked_jobs:
            self.trvResources.removeBlockedJob(self.blocked_jobs[job_id])

    def reinit_tree(self, force=False):
        # clear tree and states
        self.disable_tools()

        # ----------------------------------------------
        # Configurate new WebGIS InfoWidget
        # This widget may be useful in the future
        # Check show message for creation new web gis
        # if not PluginSettings.webgis_creation_message_closed_by_user():
        #     for conn_name in NgwPluginSettings.get_ngw_connection_names():
        #         conn_settings = NgwPluginSettings.get_ngw_connection(conn_name)
        #         o = urlparse(conn_settings.server_url)
        #         if o.hostname.find("nextgis.com") != -1:
        #             self.webGISCreationMessageWidget.setVisible(False)
        #             break
        # ----------------------------------------------

        name_of_conn = NgwPluginSettings.get_selected_ngw_connection_name()
        if not name_of_conn:
            self.trvResources.showWelcomeMessage()
            self._resource_model.cleanModel()
            return

        self.trvResources.hideWelcomeMessage()

        conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)

        if not conn_sett:
            return

        s = QSettings()
        proxyEnabled = s.value("proxy/proxyEnabled", u"", type=unicode)
        proxy_type = s.value("proxy/proxyType", u"", type=unicode)
        proxy_host = s.value("proxy/proxyHost", u"", type=unicode)
        proxy_port = s.value("proxy/proxyPort", u"", type=unicode)
        proxy_user = s.value("proxy/proxyUser", u"", type=unicode)
        proxy_password = s.value("proxy/proxyPassword", u"", type=unicode)

        if proxyEnabled == "true":
            if proxy_type == "DefaultProxy":
                qgsNetMan = QgsNetworkAccessManager.instance()
                proxy = qgsNetMan.proxy().applicationProxy()
                proxy_host = proxy.hostName()
                proxy_port = str(proxy.port())
                proxy_user = proxy.user()
                proxy_password = proxy.password()

            if proxy_type in ["DefaultProxy", "Socks5Proxy", "HttpProxy", "HttpCachingProxy"]:
                # QgsMessageLog.logMessage("%s  %s  %s  %s" % (
                #     proxy_host,
                #     proxy_port,
                #     proxy_user,
                #     proxy_password,
                # ))
                conn_sett.set_proxy(
                    proxy_host,
                    proxy_port,
                    proxy_user,
                    proxy_password
                )

        if not self._resource_model.isCurrentConnectionSame(conn_sett) or force:
            self._resource_model.resetModel(conn_sett)

        # expand root item
        # self.trvResources.setExpanded(self._resource_model.index(0, 0, QModelIndex()), True)

        # save last selected connection
        # NgwPluginSettings.set_selected_ngw_connection_name(name_of_conn)

    def __action_refresh_tree(self):
        self.reinit_tree(True)

    def disable_tools(self):
        self.actionExport.setEnabled(False)
        self.actionOpenMapInBrowser.setEnabled(False)

    def action_settings(self):
        sett_dialog = SettingsDialog()
        sett_dialog.show()
        sett_dialog.exec_()

        self.reinit_tree()

    def slotCustomContextMenu(self, qpoint):
        index = self.trvResources.indexAt(qpoint)

        if not index.isValid():
            index = self._resource_model.index(
                0,
                0,
                QModelIndex()
            )

        ngw_resource = index.data(QNGWResourceItemExt.NGWResourceRole)

        menu = QMenu()
        menu.addAction(self.actionOpenInNGW)
        menu.addAction(self.actionRename)

        if isinstance(ngw_resource, NGWGroupResource):
            menu.addAction(self.actionCreateNewGroup)
        elif isinstance(ngw_resource, NGWVectorLayer):
            menu.addAction(self.actionExport)
            menu.addAction(self.actionCreateWFSService)
            menu.addAction(self.actionCreateWMSService)
            menu.addAction(self.actionCreateWebMap4Layer)
        elif isinstance(ngw_resource, NGWRasterLayer):
            menu.addAction(self.actionCreateWebMap4Layer)
        elif isinstance(ngw_resource, NGWWfsService):
            menu.addAction(self.actionExport)
        elif isinstance(ngw_resource, NGWWebMap):
            menu.addAction(self.actionOpenMapInBrowser)
        elif isinstance(ngw_resource, NGWQGISVectorStyle):
            menu.addAction(self.actionExport)
            menu.addAction(self.actionCreateWebMap4Style)
            menu.addAction(self.actionDownload)
        elif isinstance(ngw_resource, NGWRasterStyle):
            menu.addAction(self.actionCreateWebMap4Style)
        elif isinstance(ngw_resource, NGWMapServerStyle):
            menu.addAction(self.actionCreateWebMap4Style)

        menu.addSeparator()
        menu.addAction(self.actionDeleteResource)

        menu.exec_(self.trvResources.viewport().mapToGlobal(qpoint))

    def trvDoubleClickProcess(self, index):
        ngw_resource = index.data(QNGWResourceItemExt.NGWResourceRole)
        if isinstance(ngw_resource, NGWWebMap):
            self.__action_open_map()

    def open_ngw_resource_page(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)
            url = ngw_resource.get_absolute_url()
            QDesktopServices.openUrl(QUrl(url))

    def rename_ngw_resource(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            new_name, res = QInputDialog.getText(
                self,
                self.tr("Change resource name"),
                "",
                text=sel_index.data(Qt.DisplayRole)
            )

            if res is False or new_name == "":
                return

            self.rename_resource_resp = self._resource_model.renameResource(sel_index, new_name)
            self.rename_resource_resp.done.connect(
                self.trvResources.setCurrentIndex
            )

    def __action_open_map(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)
            url = ngw_resource.get_display_url()
            QDesktopServices.openUrl(QUrl(url))

    def __export_to_qgis(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItemExt.NGWResourceRole)
            try:
                if isinstance(ngw_resource, NGWVectorLayer):
                    add_resource_as_geojson(ngw_resource)
                if isinstance(ngw_resource, NGWQGISVectorStyle):
                    ngw_layer = sel_index.parent().data(QNGWResourceItemExt.NGWResourceRole)
                    add_resource_as_geojson_with_style(ngw_layer, ngw_resource)
                elif isinstance(ngw_resource, NGWWfsService):
                    add_resource_as_wfs_layers(ngw_resource)

            except NGWError as ex:
                error_mes = ex.message or ''
                self.iface.messageBar().pushMessage(
                    self.tr('Error'),
                    error_mes,
                    level=QgsMessageBar.CRITICAL
                )
                qgisLog(error_mes, level=QgsMessageLog.CRITICAL)

    def create_group(self):
        new_group_name, res = QInputDialog.getText(
            self,
            self.tr("Set new group name"),
            self.tr("New group name:"),
            QLineEdit.Normal,
            self.tr("New group"),
            Qt.Dialog
        )

        if (res is False or new_group_name == ""):
            return

        sel_index = self.trvResources.selectedIndex()

        if sel_index is None:
            sel_index = self._resource_model.index(0, 0, QModelIndex())

        self.create_group_resp = self._resource_model.tryCreateNGWGroup(new_group_name, sel_index)
        self.create_group_resp.done.connect(
            self.trvResources.setCurrentIndex
        )

    def import_qgis_project(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        current_project = QgsProject.instance()
        current_project_title = current_project.title()

        dlg = DialogImportQGISProj(current_project_title, self)
        result = dlg.exec_()
        if result:
            self.qgis_proj_import_response = self._resource_model.tryImportCurentQGISProject(
                dlg.getProjName(),
                sel_index,
                self.iface
            )
            self.qgis_proj_import_response.done.connect(
                self.trvResources.setCurrentIndex
            )
            self.qgis_proj_import_response.done.connect(
                self.open_create_web_map
            )

    def import_layers(self):
        # qgs_map_layer = self.iface.mapCanvas().currentLayer()
        qgs_map_layers = self.iface.legendInterface().selectedLayers()
        
        sel_index = self.trvResources.selectionModel().currentIndex()
        self.import_layer_response = self._resource_model.createNGWLayer(qgs_map_layers, sel_index)
        self.import_layer_response.done.connect(
            self.trvResources.setCurrentIndex
        )

    def import_update_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        sel_index = self.trvResources.selectionModel().currentIndex()
        response = self._resource_model.createOrUpdateQGISStyle(qgs_map_layer, sel_index)
        response.done.connect(
            self.trvResources.setCurrentIndex
        )        

    def delete_curent_ngw_resource(self):
        res = QMessageBox.question(
            self,
            self.tr("Delete resource"),
            self.tr("Are you sure you want to remove this resource?"),
            QMessageBox.Yes and QMessageBox.No,
            QMessageBox.Yes
        )

        if res == QMessageBox.Yes:
            selected_index = self.trvResources.selectionModel().currentIndex()
            self.delete_resource_response = self._resource_model.deleteResource(selected_index)
            self.delete_resource_response.done.connect(
                self.trvResources.setCurrentIndex
            )

    def create_wfs_service(self):
        ret_obj_num, res = QInputDialog.getInt(
            self,
            self.tr("Create WFS service"),
            self.tr("The number of objects returned by default"),
            1000,
            0,
            2147483647
        )
        if res is False:
            return

        selected_index = self.trvResources.selectionModel().currentIndex()
        responce = self._resource_model.createWFSForVector(selected_index, ret_obj_num)
        responce.done.connect(
            self.trvResources.setCurrentIndex
        )
        responce.done.connect(
            self.add_created_wfs_service
        )

    def add_created_wfs_service(self, index):
        if PluginSettings.auto_add_wfs_option() is False:
            return

        ngw_resource = index.data(Qt.UserRole)
        add_resource_as_wfs_layers(ngw_resource)

    def create_wms_service(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        
        dlg = NGWLayerStyleChooserDialog(self.tr("Create WMS for layer"), selected_index, self._resource_model, self)
        result = dlg.exec_()
        if result:
            ngw_resource_style_id = None
            if not dlg.needCreateNewStyle() and dlg.selectedStyle():
                ngw_resource_style_id = dlg.selectedStyle()

            responce = self._resource_model.createWMSForVector(selected_index, ngw_resource_style_id)
            responce.done.connect(
                self.trvResources.setCurrentIndex
            )
            # responce.done.connect(
            #     self.add_created_wms_service
            # )

    def create_web_map_for_style(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        self.create_map_response = self._resource_model.createMapForStyle(selected_index)

        self.create_map_response.done.connect(
            self.open_create_web_map
        )

    def create_web_map_for_layer(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        self._resource_model.updateResourceWithLoadChildren(selected_index)

        dlg = NGWLayerStyleChooserDialog(self.tr("Create Web Map for layer"), selected_index, self._resource_model, self)
        result = dlg.exec_()
        if result:
            ngw_resource_style_id = None
            if not dlg.needCreateNewStyle() and dlg.selectedStyle():
                ngw_resource_style_id = dlg.selectedStyle()

            self.create_map_response = self._resource_model.createMapForLayer(
                selected_index,
                ngw_resource_style_id
            )

            self.create_map_response.done.connect(
                self.trvResources.setCurrentIndex
            )
            self.create_map_response.done.connect(
                self.open_create_web_map
            )

    def open_create_web_map(self, index):
        if PluginSettings.auto_open_web_map_option() is False:
            return

        ngw_resource = index.data(Qt.UserRole)
        url = ngw_resource.get_display_url()
        QDesktopServices.openUrl(QUrl(url))

    def downloadQML(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        ngw_qgis_style = selected_index.data(QNGWResourceItemExt.NGWResourceRole)
        url = ngw_qgis_style.download_qml_url()

        filepath = QFileDialog.getSaveFileName(
            self,
            self.tr("Save QML"),
            "%s.qml" % ngw_qgis_style.common.display_name,
            filter=self.tr("QGIS Layer style file (*.qml)")
        )
        # QDesktopServices.openUrl(QUrl(url))

        if filepath == "":
            return

        self.dwn_qml_filepath = filepath
        self.dwn_qml_manager = QNetworkAccessManager(self)
        self.dwn_qml_manager.finished.connect(self.saveQML)
        self.dwn_qml_manager.get(QNetworkRequest(QUrl(url)))

    def saveQML(self, reply):
        file = QFile(self.dwn_qml_filepath)
        if file.open(QIODevice.WriteOnly):
            file.write(reply.readAll())
            file.close()
            self.__msg_in_qgis_mes_bar(self.tr("QML file downloaded"), duration=2)
        else:
            self.__msg_in_qgis_mes_bar(self.tr("QML file could not be downloaded"), QgsMessageBar.CRITICAL)

        reply.deleteLater()

    # def create_style(self):
    #     dlg = DialogChooseQGISLayer(self.tr("Get style from layer"), self.iface, self)
    #     result = dlg.exec_()
    #     if result:
    #         selected_index = self.trvResources.selectionModel().currentIndex()
    #         selected_layer = dlg.layers.currentLayer()

    #         if selected_layer is None:
    #             return

    #         self._resource_model.createStyleForLayer(
    #             selected_index,
    #             selected_layer
    #         )


class NGWPanelToolBar(QToolBar):
    def __init__(self):
        QToolBar.__init__(self, None)

        self.setIconSize(QSize(24, 24))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def contextMenuEvent(self, event):
        event.accept()

    def resizeEvent(self, event):
        QToolBar.setIconSize(self, QSize(24, 24))
        event.accept()


class Overlay(QWidget):
    def __init__(self, parent):
        QWidget.__init__(self, parent)
        # self.resize(parent.size())
        palette = QPalette(self.palette())
        palette.setColor(palette.Background, Qt.transparent)
        self.setPalette(palette)

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QBrush(QColor(255, 255, 255, 200)))
        painter.setPen(QPen(Qt.NoPen))


class MessageOverlay(Overlay):
    def __init__(self, parent, text):
        Overlay.__init__(self, parent)
        self.layout = QHBoxLayout(self)
        self.setLayout(self.layout)

        self.text = QLabel(text, self)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.layout.addWidget(self.text)


class ProcessOverlay(Overlay):
    def __init__(self, parent):
        Overlay.__init__(self, parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        spacer_before = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        spacer_after = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.layout.addItem(spacer_before)

        self.central_widget = QWidget(self)
        # self.central_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.central_widget_layout = QVBoxLayout(self.central_widget)
        self.central_widget.setLayout(self.central_widget_layout)
        self.layout.addWidget(self.central_widget)

        self.layout.addItem(spacer_after)

        self.progress = QProgressBar(self)
        self.progress.setMinimum(0)
        self.progress.setMaximum(0)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.central_widget_layout.addWidget(self.progress)
        self.setStyleSheet(
            """
                QProgressBar {
                    border: 1px solid grey;
                    border-radius: 5px;
                }
            """
        )

        self.text = QLabel(self)
        self.text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.central_widget_layout.addWidget(self.text)

    def write(self, jobs):
        text = ""
        for job_name, job_status in jobs.items():
            text += "<strong>%s</strong><br/>" % job_name
            if job_status != "":
                text += "%s<br/>" % job_status

        self.text.setText(text)


class NGWResourcesTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        QTreeView.__init__(self, parent)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.header().setStretchLastSection(False)
        self.header().setResizeMode(QHeaderView.ResizeToContents)

        # no ngw connectiond message
        self.no_ngw_connections_overlay = MessageOverlay(
            self,
            self.tr(
                "No active connections to nextgis.com. Please create a connection. You can get your free Web GIS at <a href='http://my.nextgis.com/'>nextgis.com</a>!"
            )
        )
        self.no_ngw_connections_overlay.hide()

        self.ngw_job_block_overlay = ProcessOverlay(
            self,
        )
        self.ngw_job_block_overlay.hide()

        self.jobs = {}

    def setModel(self, model):
        self._source_model = model
        self._source_model.rowsInserted.connect(self.__insertRowsProcess)
        # self._source_model.focusedResource.connect(self.__focuseResource)

        super(NGWResourcesTreeView, self).setModel(self._source_model)

    def selectedIndex(self):
        return self.selectionModel().currentIndex()

    def __insertRowsProcess(self, parent, start, end):
        if not parent.isValid():
            self.expandAll()
        # else:
        #     self.expand(
        #         parent
        #     )

    # def __focuseResource(self, index):
    #     self.setCurrentIndex(
    #         index
    #     )

    def resizeEvent(self, event):
        self.no_ngw_connections_overlay.resize(event.size())
        self.ngw_job_block_overlay.resize(event.size())

        QTreeView.resizeEvent(self, event)

    def mouseDoubleClickEvent(self, e):
        index = self.indexAt(e.pos())
        if index.isValid():
            self.itemDoubleClicked.emit(index)

        super(NGWResourcesTreeView, self).mouseDoubleClickEvent(e)

    def showWelcomeMessage(self):
        self.no_ngw_connections_overlay.show()

    def hideWelcomeMessage(self):
        self.no_ngw_connections_overlay.hide()

    def addBlockedJob(self, job_name):
        self.jobs.update(
            {job_name: ""}
        )
        self.ngw_job_block_overlay.write(self.jobs)

        self.ngw_job_block_overlay.show()

    def addJobStatus(self, job_name, status):
        if job_name in self.jobs:
            self.jobs[job_name] = status
            self.ngw_job_block_overlay.write(self.jobs)

    def removeBlockedJob(self, job_name):
        if job_name in self.jobs:
            self.jobs.pop(job_name)
            self.ngw_job_block_overlay.write(self.jobs)

        if len(self.jobs) == 0:
            self.ngw_job_block_overlay.hide()
