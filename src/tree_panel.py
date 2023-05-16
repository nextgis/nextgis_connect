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
import html
import os
import traceback

from qgis.core import (
    Qgis, QgsMessageLog, QgsProject, QgsVectorLayer, QgsRasterLayer, QgsPluginLayer, QgsLayerTreeGroup, QgsProject,
    QgsNetworkAccessManager,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QByteArray, QEventLoop, QFile, QIODevice, QModelIndex, QSettings, QSize, Qt,
    QTemporaryFile, QUrl,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QFileDialog, QInputDialog, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QToolBar, QToolButton,
)

from .ngw_api.core import (
    NGWError,
    NGWGroupResource,
    NGWMapServerStyle,
    NGWRasterLayer,
    NGWRasterStyle,
    NGWVectorLayer,
    NGWQGISRasterStyle,
    NGWQGISVectorStyle,
    NGWWebMap,
    NGWWfsService,
    NGWWmsConnection,
    NGWWmsLayer,
    NGWWmsService,
)

from .ngw_api.qt.qt_ngw_resource_model_job_error import (
    JobAuthorizationError, JobError, JobInternalError, JobNGWError, JobServerRequestError,
    JobWarning,
)

from .ngw_api.qgis.ngw_connection_edit_dialog import NGWConnectionEditDialog
from .ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from .ngw_api.qgis.resource_to_map import (
    add_resource_as_cog_raster, add_resource_as_cog_raster_with_style,
    add_resource_as_geojson, add_resource_as_geojson_with_style,
    add_resource_as_wfs_layers, UnsupportedRasterTypeException,
)
from .ngw_api.qgis.ngw_resource_model_4qgis import QGISResourceJob
from .ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection

from .ngw_api.utils import log, setDebugEnabled, setLogger

from . import utils
from .action_style_import_or_update import ActionStyleImportUpdate
from .dialog_choose_style import NGWLayerStyleChooserDialog
from .dialog_qgis_proj_import import UploadQGISProjectDialog
from .dialog_metadata import MetadataDialog
from .exceptions_list_dialog import ExceptionsListDialog
from .plugin_settings import PluginSettings
from .settings_dialog import SettingsDialog
from .tree_widget import QNGWResourceTreeView, QNGWResourceItem, QNGWResourceTreeModel


this_dir = os.path.dirname(__file__)

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    this_dir, 'tree_panel_base.ui'))

ICONS_PATH = os.path.join(this_dir, 'icons/')


def qgisLog(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, PluginSettings._product, level)

def ngwApiLog(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, "NGW API", level)

setLogger(ngwApiLog)


class TreePanel(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)

        self.setWindowTitle('NextGIS Connect')
        self.setObjectName('treePanel')

        self.inner_control = TreeControl(iface, self)
        self.inner_control.setWindowFlags(Qt.Widget)
        self.setWidget(self.inner_control)

    def close(self):
        self.inner_control.close()
        super().close()


class TreeControl(QMainWindow, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super().__init__(parent)

        self.setupUi(self)
        self.iface = iface

        self._first_gui_block_on_refresh = False

        self.actionOpenInNGW = QAction(self.tr("Open in WebGIS"), self)
        self.actionOpenInNGW.triggered.connect(self.open_ngw_resource_page)

        self.actionRename = QAction(self.tr("Rename"), self)
        self.actionRename.triggered.connect(self.rename_ngw_resource)

        self.actionExport = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionExport.svg')),
            self.tr("Add to QGIS"), self)
        self.actionExport.triggered.connect(self.__export_to_qgis)

        self.menuUpload = QMenu(self.tr("Add to Web GIS"), self)
        self.menuUpload.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionImport.svg')))
        self.menuUpload.menuAction().setIconVisibleInMenu(False)

        self.actionUploadSelectedResources = QAction(
            self.tr("Upload selected"), self.menuUpload)
        self.actionUploadSelectedResources.triggered.connect(self.upload_selected_resources)
        self.actionUploadSelectedResources.setEnabled(False)

        self.actionUploadProjectResources = QAction(
            self.tr("Upload all"), self.menuUpload)
        self.actionUploadProjectResources.triggered.connect(self.upload_project_resources)

        self.actionUpdateStyle = ActionStyleImportUpdate(self.tr('Update layer style'))
        self.actionUpdateStyle.triggered.connect(self.update_style)

        self.actionAddStyle = ActionStyleImportUpdate(self.tr('Add new style to layer'))
        self.actionAddStyle.triggered.connect(self.add_style)

        self.menuUpload.addAction(self.actionUploadSelectedResources)
        self.menuUpload.addAction(self.actionUploadProjectResources)
        self.menuUpload.addAction(self.actionUpdateStyle)
        self.menuUpload.addAction(self.actionAddStyle)

        self.actionUpdateNGWVectorLayer = QAction(
            self.tr("Overwrite selected layer"), self.menuUpload)
        self.actionUpdateNGWVectorLayer.triggered.connect(self.overwrite_ngw_layer)
        self.actionUpdateNGWVectorLayer.setEnabled(False)

        self.actionCreateNewGroup = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.svg')),
            self.tr("Create resource group"), self)
        self.actionCreateNewGroup.triggered.connect(self.create_group)

        self.actionCreateWebMap4Layer = QAction(self.tr("Create web Map"), self)
        self.actionCreateWebMap4Layer.triggered.connect(self.create_web_map_for_layer)

        self.actionCreateWebMap4Style = QAction(self.tr("Create web Map"), self)
        self.actionCreateWebMap4Style.triggered.connect(self.create_web_map_for_style)

        self.actionDownload = QAction(self.tr("Download as QML"), self)
        self.actionDownload.triggered.connect(self.downloadQML)

        self.actionCreateWFSService = QAction(self.tr("Create WFS service"), self)
        self.actionCreateWFSService.triggered.connect(self.create_wfs_service)

        self.actionCreateWMSService = QAction(self.tr("Create WMS service"), self)
        self.actionCreateWMSService.triggered.connect(self.create_wms_service)

        self.actionCopyResource = QAction(self.tr("Copy resource"), self)
        self.actionCopyResource.triggered.connect(self.copy_curent_ngw_resource)

        self.actionEditMetadata = QAction(self.tr("Edit metadata"), self)
        self.actionEditMetadata.triggered.connect(self.edit_metadata)

        self.actionDeleteResource = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionDelete.svg')), self.tr("Delete resource"), self)
        self.actionDeleteResource.triggered.connect(self.delete_curent_ngw_resource)

        self.actionOpenMapInBrowser = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionOpenMap.svg')),
            self.tr("Open web map in browser"), self)
        self.actionOpenMapInBrowser.triggered.connect(self.__action_open_map)

        self.actionRefresh = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionRefresh.svg')),
            self.tr("Refresh"), self)
        self.actionRefresh.triggered.connect(self.__action_refresh_tree)

        self.actionSettings = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionSettings.svg')),
            self.tr("Settings"), self)
        self.actionSettings.triggered.connect(self.action_settings)

        self.actionHelp = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionHelp.svg')),
            self.tr("Help"), self)
        self.actionHelp.triggered.connect(self.action_help)

        # Add toolbar
        self.main_tool_bar = NGWPanelToolBar()
        self.addToolBar(self.main_tool_bar)

        self.main_tool_bar.addAction(self.actionExport)
        self.toolbuttonImport = QToolButton()
        self.toolbuttonImport.setPopupMode(QToolButton.InstantPopup)
        self.toolbuttonImport.setMenu(self.menuUpload)
        self.toolbuttonImport.setIcon(self.menuUpload.icon())
        self.toolbuttonImport.setText(self.menuUpload.title())
        self.toolbuttonImport.setToolTip(self.menuUpload.title())

        self.main_tool_bar.addWidget(self.toolbuttonImport)
        self.main_tool_bar.addSeparator()
        self.main_tool_bar.addAction(self.actionCreateNewGroup)
        self.main_tool_bar.addAction(self.actionRefresh)
        self.main_tool_bar.addSeparator()
        self.main_tool_bar.addAction(self.actionOpenMapInBrowser)
        self.main_tool_bar.addSeparator()
        self.main_tool_bar.addAction(self.actionSettings)
        self.main_tool_bar.addAction(self.actionHelp)

        self._resource_model = QNGWResourceTreeModel(self)
        self._resource_model.errorOccurred.connect(self.__model_error_process)
        self._resource_model.warningOccurred.connect(self.__model_warning_process)
        self._resource_model.jobStarted.connect(self.__modelJobStarted)
        self._resource_model.jobStatusChanged.connect(self.__modelJobStatusChanged)
        self._resource_model.jobFinished.connect(self.__modelJobFinished)
        self._resource_model.indexesLocked.connect(self.__onModelBlockIndexes)
        self._resource_model.indexesUnlocked.connect(self.__onModelReleaseIndexes)

        self.blocked_jobs = {
            "NGWGroupCreater": self.tr("Resource is being created"),
            "NGWResourceDelete": self.tr("Resource is being deleted"),
            "QGISResourcesUploader": self.tr("Layer is being imported"),
            "QGISProjectUploader": self.tr("Project is being imported"),
            "NGWCreateWFSForVector": self.tr("WFS service is being created"),
            "NGWCreateWMSForVector": self.tr("WMS service is being created"),
            "NGWCreateMapForStyle": self.tr("Web map is being created"),
            "MapForLayerCreater": self.tr("Web map is being created"),
            "QGISStyleUpdater": self.tr("Style for layer is being updated"),
            "QGISStyleAdder": self.tr("Style for layer is being created"),
            "NGWRenameResource": self.tr("Resource is being renamed"),
            "NGWUpdateVectorLayer": self.tr("Resource is being updated"),
        }

        # ngw resources view
        self.trvResources = QNGWResourceTreeView(self)
        self.trvResources.setModel(self._resource_model)

        self.trvResources.customContextMenuRequested.connect(self.slotCustomContextMenu)
        self.trvResources.itemDoubleClicked.connect(self.trvDoubleClickProcess)
        self.trvResources.selectionModel().currentChanged.connect(self.checkImportActionsAvailability)

        self.nrw_reorces_tree_container.addWidget(self.trvResources)

        self.jobs_count = 0
        self.try_check_https = False

        self.iface.initializationCompleted.connect(self.reinit_tree)
        # update state
        if QSettings().value("proxy/proxyEnabled", None) is not None:
            self.reinit_tree()

        self.main_tool_bar.setIconSize(QSize(24, 24))

        self.checkImportActionsAvailability()
        self.iface.currentLayerChanged.connect(self.checkImportActionsAvailability)
        project = QgsProject.instance()
        project.layersAdded.connect(self.checkImportActionsAvailability)
        project.layersRemoved.connect(self.checkImportActionsAvailability)

    def close(self):
        self.trvResources.customContextMenuRequested.disconnect(self.slotCustomContextMenu)
        self.trvResources.itemDoubleClicked.disconnect(self.trvDoubleClickProcess)
        self.trvResources.selectionModel().currentChanged.disconnect(self.checkImportActionsAvailability)

        self.trvResources.setParent(None)
        self.trvResources.deleteLater()
        del self.trvResources

        self.iface.currentLayerChanged.disconnect(self.checkImportActionsAvailability)
        project = QgsProject.instance()
        project.layersAdded.disconnect(self.checkImportActionsAvailability)
        project.layersRemoved.disconnect(self.checkImportActionsAvailability)

        self._resource_model.errorOccurred.disconnect(self.__model_error_process)
        self._resource_model.warningOccurred.disconnect(self.__model_warning_process)
        self._resource_model.jobStarted.disconnect(self.__modelJobStarted)
        self._resource_model.jobStatusChanged.disconnect(self.__modelJobStatusChanged)
        self._resource_model.jobFinished.disconnect(self.__modelJobFinished)
        self._resource_model.indexesLocked.disconnect(self.__onModelBlockIndexes)
        self._resource_model.indexesUnlocked.disconnect(self.__onModelReleaseIndexes)

        self._resource_model.setParent(None)
        self._resource_model.deleteLater()
        del self._resource_model

        super().close()

    def checkImportActionsAvailability(self):
        current_qgis_layer = self.iface.mapCanvas().currentLayer()
        current_qgis_node = self.iface.layerTreeView().currentNode()
        index = self.trvResources.selectionModel().currentIndex()
        if index is not None:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        else:
            ngw_resource = None

        layer_types = (QgsVectorLayer, QgsRasterLayer, QgsPluginLayer)
        is_layer = (current_qgis_layer is not None
                        and isinstance(current_qgis_layer, layer_types))
        is_group = (current_qgis_node is not None
                        and current_qgis_node.parent() is not None
                        and isinstance(current_qgis_node, QgsLayerTreeGroup))
        self.actionUploadSelectedResources.setEnabled(is_layer or is_group)

        self.actionUpdateNGWVectorLayer.setEnabled(
            isinstance(current_qgis_layer, QgsVectorLayer)
        )

        if isinstance(ngw_resource, NGWQGISVectorStyle) or isinstance(ngw_resource, NGWQGISRasterStyle):
            ngw_layer = index.parent().data(QNGWResourceItem.NGWResourceRole)
            self.actionUpdateStyle.setEnabledByType(current_qgis_layer, ngw_layer)
            self.actionAddStyle.setEnabled(False)
        else:
            self.actionUpdateStyle.setEnabled(False)
            self.actionAddStyle.setEnabledByType(current_qgis_layer, ngw_resource)

        self.actionUploadProjectResources.setEnabled(QgsProject.instance().count() != 0)

        self.toolbuttonImport.setEnabled(
            (self.actionUploadSelectedResources.isEnabled() or self.actionUploadProjectResources.isEnabled() or
                self.actionAddStyle.isEnabled() or self.actionUpdateStyle.isEnabled() or self.actionUpdateNGWVectorLayer.isEnabled())
        )

        # TODO: NEED REFACTORING! Make isCompatible methods!
        self.actionExport.setEnabled(
            isinstance(
                ngw_resource,
                (
                    NGWWfsService,
                    NGWWmsService,
                    NGWWmsConnection,
                    NGWWmsLayer,
                    NGWVectorLayer,
                    NGWQGISVectorStyle,
                    NGWRasterLayer,
                    NGWQGISRasterStyle
                )
            )
        )
        # enable/dis webmap
        self.actionOpenMapInBrowser.setEnabled(isinstance(ngw_resource, NGWWebMap))

    def __model_warning_process(self, job, exception):
        self.__model_exception_process(job, exception, Qgis.Warning)

    def __model_error_process(self, job, exception):
        self.__model_exception_process(job, exception, Qgis.Critical)

    def __model_exception_process(self, job, exception, level, trace=None):
        self.unblock_gui() # always unblock in case of any error so to allow to fix it

        msg, msg_ext, icon = self.__get_model_exception_description(job, exception)

        name_of_conn = NgwPluginSettings.get_selected_ngw_connection_name()
        conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)

        ngwApiLog('Exception name: ' + exception.__class__.__name__)

        if exception.__class__ == JobAuthorizationError:
            self.try_check_https = False
            dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett, only_password_change=True)
            dlg.setWindowTitle(self.tr("Access denied. Enter your login."))
            res = dlg.exec_()
            if res:
                conn_sett = dlg.ngw_connection_settings
                NgwPluginSettings.save_ngw_connection(conn_sett)
                self.reinit_tree(force=True) # force reconnect in order to correctly show connection dialog each time
            else:
                self.block_tools()
            del dlg
            return

        # Detect very first connection.
        if self.jobs_count == 1:

            if exception.__class__ == JobServerRequestError and exception.need_reconnect:

                # Try to fix http -> https. Useful for fixing old (saved) cloud connections.
                if conn_sett.server_url.startswith('http://') and conn_sett.server_url.endswith('.nextgis.com'):
                    self.try_check_https = True
                    conn_sett.server_url = conn_sett.server_url.replace('http://', 'https://')
                    NgwPluginSettings.save_ngw_connection(conn_sett)
                    ngwApiLog('Meet "http://" ".nextgis.com" connection error at very first time using this web gis connection. Trying to reconnect with "https://"')
                    self.reinit_tree()
                    return

                # Show connect dialog again.
                else:
                    self.jobs_count = 0 # mark that the next connection will also be the first one
                    old_con_name = conn_sett.connection_name
                    dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett, only_password_change=False)
                    dlg.set_alert_msg(self.tr('Failed to connect. Please re-enter Web GIS connection settings.'))
                    res = dlg.exec_()
                    if res:
                        conn_sett = dlg.ngw_connection_settings
                        new_con_name = conn_sett.connection_name
                        NgwPluginSettings.save_ngw_connection(conn_sett)
                        NgwPluginSettings.set_selected_ngw_connection_name(new_con_name)
                        if new_con_name != old_con_name:
                            NgwPluginSettings.remove_ngw_connection(old_con_name) # delete unused old bad connection
                        self.reinit_tree(force=True)
                    del dlg
                    return

        # The second time return back http if there was an error: this might be some
        # other error, not related to http/https changing.
        if self.try_check_https: # this can be only when there are more than 1 connection errors
            self.try_check_https = False
            conn_sett.server_url = conn_sett.server_url.replace('https://', 'http://')
            NgwPluginSettings.save_ngw_connection(conn_sett)
            ngwApiLog('Failed to reconnect with "https://". Return "http://" back')
            self.reinit_tree()
            return

        if issubclass(exception.__class__, JobServerRequestError) and not exception.user_msg is None:
            self.show_error(exception.user_msg)

        elif msg is not None:
            self.__msg_in_qgis_mes_bar(
                msg,
                msg_ext is not None,
                level=level
            )

        if msg_ext is not None:
            qgisLog(msg + "\n" + msg_ext)


    def __get_model_exception_description(self, job, exception):
        msg = None
        msg_ext = None
        icon = os.path.join(ICONS_PATH, 'Error.svg')

        if exception.__class__ == JobServerRequestError:
            msg = self.tr("Error occurred while communicating with Web GIS.")
            msg_ext = "URL: %s" % str(exception)
            msg_ext += "\nMSG: %s" % exception

        elif exception.__class__ == JobNGWError:
            msg = " %s." % str(exception)
            msg_ext = "URL: " + exception.url

        elif exception.__class__ == JobAuthorizationError:
            msg = " %s." % self.tr("Access denied. Enter your login.")

        elif exception.__class__ == JobError:
            msg = str(exception)
            if exception.wrapped_exception is not None:
                msg_ext = "%s" % exception.wrapped_exception

                # If we have message for user - add it instead of system message.
                # TODO: put it somewhere globally.
                user_msg = getattr(exception.wrapped_exception, "user_msg", None)
                if not user_msg is None:
                    msg_ext = user_msg

        elif exception.__class__ == JobWarning:
            msg = str(exception)
            icon = os.path.join(ICONS_PATH, 'Warning.svg')

        elif exception.__class__ == JobInternalError:
            msg = self.tr("Internal plugin error occurred!")
            msg_ext = "".join(exception.trace)

        return msg, msg_ext, icon

    def __msg_in_qgis_mes_bar(self, message, need_show_log, level=Qgis.Info, duration=0):
        if need_show_log:
            message += " " + self.tr("See logs for details.")
        widget = self.iface.messageBar().createMessage(
            'NextGIS Connect',
            message
        )
        # widget.setProperty("Error", message)
        if need_show_log:
            button = QPushButton(self.tr("Open logs."), pressed=self.__show_message_log)
            widget.layout().addWidget(button)

        self.iface.messageBar().pushWidget(widget, level, duration)

    def __show_message_log(self):
        self.iface.messageBar().popWidget()
        self.iface.openMessageLog()

    def __modelJobStarted(self, job_id):
        if job_id in self.blocked_jobs:
            self.block_gui()
            self.trvResources.addBlockedJob(self.blocked_jobs[job_id])

    def __modelJobStatusChanged(self, job_id, status):
        if job_id in self.blocked_jobs:
            self.trvResources.addJobStatus(self.blocked_jobs[job_id], status)

    def __modelJobFinished(self, job_id):
        self.jobs_count += 1 # note: __modelJobFinished will be triggered even if error/warning occured during job execution
        ngwApiLog('Jobs finished for current connection: {}'.format(self.jobs_count))

        if job_id == 'NGWRootResourcesLoader':
            self.unblock_gui()

        if job_id in self.blocked_jobs:
            self.unblock_gui()
            self.trvResources.removeBlockedJob(self.blocked_jobs[job_id])

    def __onModelBlockIndexes(self):
        self.block_gui()

    def __onModelReleaseIndexes(self):
        if self._first_gui_block_on_refresh:
            self._first_gui_block_on_refresh = False
        else:
            self.unblock_gui()


    def block_gui(self):
        self.main_tool_bar.setEnabled(False)

    def unblock_gui(self):
        self.main_tool_bar.setEnabled(True)

    def block_tools(self):
        self.toolbuttonImport.setEnabled(False)


    def reinit_tree(self, force=False):
        # clear tree and states
        self.disable_tools()

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
        proxyEnabled = s.value("proxy/proxyEnabled", "", type=str)
        proxy_type = s.value("proxy/proxyType", "", type=str)
        proxy_host = s.value("proxy/proxyHost", "", type=str)
        proxy_port = s.value("proxy/proxyPort", "", type=str)
        proxy_user = s.value("proxy/proxyUser", "", type=str)
        proxy_password = s.value("proxy/proxyPassword", "", type=str)

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

        if force or not self._resource_model.isCurrentConnectionSame(conn_sett):
            if not self._resource_model.isCurruntConnectionSameWoProtocol(conn_sett):
                self.jobs_count = 0 # start working with connection at very first time

            self._first_gui_block_on_refresh = True
            self.block_gui() # block GUI to prevent extra clicks on toolbuttons
            ngw_connection = QgsNgwConnection(conn_sett)
            self._resource_model.resetModel(ngw_connection)

        # expand root item
        # self.trvResources.setExpanded(self._resource_model.index(0, 0, QModelIndex()), True)

        # save last selected connection
        # NgwPluginSettings.set_selected_ngw_connection_name(name_of_conn)

    def __action_refresh_tree(self):
        self.reinit_tree(True)

    def __add_resource_to_tree(self, ngw_resource):
        # TODO: fix duplicate with model.processJobResult
        if ngw_resource.common.parent is None:
            index = QModelIndex()
            self._resource_model.addNGWResourceToTree(index, ngw_resource)
        else:
            index = self._resource_model.getIndexByNGWResourceId(
                ngw_resource.common.parent.id,
            )

            item = index.internalPointer()
            current_ids = [
                item.child(i).data(QNGWResourceItem.NGWResourceRole).common.id
                for i in range(item.childCount())
                if isinstance(item.child(i), QNGWResourceItem)]
            if ngw_resource.common.id not in current_ids:
                self._resource_model.addNGWResourceToTree(index, ngw_resource)

    def disable_tools(self):
        self.actionExport.setEnabled(False)
        self.actionOpenMapInBrowser.setEnabled(False)

    def action_settings(self):
        old_debug_mode = PluginSettings.debug_mode()

        sett_dialog = SettingsDialog()
        sett_dialog.show()
        sett_dialog.exec_()

        debug_mode = PluginSettings.debug_mode()

        if debug_mode != old_debug_mode:
            setDebugEnabled(debug_mode)
            QgsMessageLog.logMessage(
                'Debug messages are now %s' % ('enabled' if debug_mode else 'disabled'),
                PluginSettings._product, level=Qgis.Info)

        self.reinit_tree()

    def action_help(self):
        QDesktopServices.openUrl(QUrl('https://docs.nextgis.com/docs_ngconnect/source/toc.html'))

    def str_to_link(self, text, url):
        return '<a href="{}"><span style=" text-decoration: underline; color:#0000ff;">{}</span></a>'.format(url, text)

    def _show_unsupported_raster_err(self):
        msg = '{}. {}'.format(
            self.tr('This type of raster is not supported yet'),
                self.str_to_link(self.tr('Please add COG support'), self.tr('https://docs.nextgis.com/docs_ngcom/source/data_upload.html#ngcom-raster-layer')
            )
        )
        self.show_info(msg)

    def slotCustomContextMenu(self, qpoint):
        index = self.trvResources.indexAt(qpoint)

        if not index.isValid():
            index = self._resource_model.index(
                0,
                0,
                QModelIndex()
            )

        if index.internalPointer().locked:
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)

        getting_actions = []
        setting_actions = []
        creating_actions = []
        services_actions = []

        services_actions.extend([self.actionOpenInNGW, self.actionRename, self.actionDeleteResource])
        creating_actions.extend([self.actionEditMetadata])

        if isinstance(ngw_resource, NGWGroupResource):
            creating_actions.append(self.actionCreateNewGroup)
        elif isinstance(ngw_resource, NGWVectorLayer):
            getting_actions.extend([self.actionExport])
            setting_actions.extend([self.actionUpdateNGWVectorLayer])
            creating_actions.extend([
                self.actionCreateWFSService,
                self.actionCreateWMSService,
                self.actionCreateWebMap4Layer,
                self.actionCopyResource
            ])
        elif isinstance(ngw_resource, NGWRasterLayer):
            getting_actions.extend([self.actionExport])
            creating_actions.extend([self.actionCreateWebMap4Layer, self.actionCopyResource])
        elif isinstance(ngw_resource, NGWWmsLayer):
            getting_actions.extend([self.actionExport])
            creating_actions.extend([self.actionCreateWebMap4Layer])
        elif isinstance(ngw_resource, NGWWfsService):
            getting_actions.extend([self.actionExport])
        elif isinstance(ngw_resource, NGWWmsService):
            getting_actions.extend([self.actionExport])
        elif isinstance(ngw_resource, NGWWmsConnection):
            getting_actions.extend([self.actionExport])
        elif isinstance(ngw_resource, NGWWebMap):
            services_actions.extend([self.actionOpenMapInBrowser])
        elif isinstance(ngw_resource, NGWQGISVectorStyle):
            getting_actions.extend([self.actionExport, self.actionDownload])
            creating_actions.extend([self.actionCreateWebMap4Style])
        elif isinstance(ngw_resource, NGWQGISRasterStyle):
            getting_actions.extend([self.actionExport, self.actionDownload])
            creating_actions.extend([self.actionCreateWebMap4Style])
        elif isinstance(ngw_resource, NGWRasterStyle):
            creating_actions.extend([self.actionCreateWebMap4Style])
        elif isinstance(ngw_resource, NGWMapServerStyle):
            creating_actions.extend([self.actionCreateWebMap4Style])

        menu = QMenu()
        for actions in [getting_actions, setting_actions, creating_actions, services_actions]:
            if len(actions) > 0:
                for action in actions:
                    menu.addAction(action)
                menu.addSeparator()

        menu.exec_(self.trvResources.viewport().mapToGlobal(qpoint))

    def trvDoubleClickProcess(self, index):
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        if isinstance(ngw_resource, NGWWebMap):
            self.__action_open_map()

    def open_ngw_resource_page(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            url = ngw_resource.get_absolute_url()
            QDesktopServices.openUrl(QUrl(url))

    def rename_ngw_resource(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        if not sel_index.isValid():
            return

        # Get current resource name. This name can differ from display text of tree item (see style resources).
        item = sel_index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)
        cur_name = ngw_resource.common.display_name

        new_name, res = QInputDialog.getText(
            self,
            self.tr("Change resource name"),
            "",
            text=cur_name
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
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            url = ngw_resource.get_display_url()
            QDesktopServices.openUrl(QUrl(url))


    def _add_with_style(self, resource):
        style_resource = None

        child_resources = resource.get_children()
        style_resources = []
        for child_resource in child_resources: # assume that there can be only a style of appropriate for the layer type
            if child_resource.type_id == NGWQGISVectorStyle.type_id or child_resource.type_id == NGWQGISRasterStyle.type_id:
                style_resources.append(child_resource)

        if len(style_resources) == 1:
            style_resource = style_resources[0]
        elif len(style_resources) > 1:
            dlg = NGWLayerStyleChooserDialog(self.tr("Select style"), self.trvResources.selectionModel().currentIndex(), self._resource_model, self)
            result = dlg.exec_()
            if result:
                sel_index = dlg.selectedStyleIndex()
                if sel_index.isValid():
                    style_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            else:
                return # just do nothing after closing the dialog

        if resource.type_id == NGWVectorLayer.type_id:
            if style_resource is None:
                add_resource_as_geojson(resource)
            else:
                add_resource_as_geojson_with_style(resource, style_resource)
        elif resource.type_id == NGWRasterLayer.type_id:
            if style_resource is None:
                add_resource_as_cog_raster(resource)
            else:
                add_resource_as_cog_raster_with_style(resource, style_resource)


    def __export_to_qgis(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)
            try:
                if isinstance(ngw_resource, NGWVectorLayer):
                    self._add_with_style(ngw_resource)
                elif isinstance(ngw_resource, NGWQGISVectorStyle):
                    parent_resource = sel_index.parent().data(QNGWResourceItem.NGWResourceRole)
                    add_resource_as_geojson_with_style(parent_resource, ngw_resource)
                elif isinstance(ngw_resource, NGWRasterLayer):
                    try:
                        self._add_with_style(ngw_resource)
                    except UnsupportedRasterTypeException:
                        self._show_unsupported_raster_err()
                elif isinstance(ngw_resource, NGWQGISRasterStyle):
                    try:
                        parent_resource = sel_index.parent().data(QNGWResourceItem.NGWResourceRole)
                        add_resource_as_cog_raster_with_style(parent_resource, ngw_resource)
                    except UnsupportedRasterTypeException:
                        self._show_unsupported_raster_err()
                elif isinstance(ngw_resource, NGWWfsService):
                    ignore_z_in_wfs = False
                    for layer in ngw_resource.get_layers():
                        if ignore_z_in_wfs:
                            break
                        source_layer = ngw_resource.get_source_layer(layer['resource_id'])
                        if isinstance(source_layer, NGWVectorLayer):
                            if source_layer.is_geom_with_z():
                                res = self.show_msg_box(
                                    self.tr('You are trying to add a WFS service containing a layer with Z dimension. '
                                            'WFS in QGIS doesn\'t fully support editing such geometries. '
                                            'You won\'t be able to edit and create new features. '
                                            'You will only be able to delete features. '
                                            'To fix this, change geometry type of your layer(s) '
                                            'and recreate WFS service.'),
                                    self.tr('Warning'),
                                    QMessageBox.Warning,
                                    QMessageBox.Ignore | QMessageBox.Cancel
                                )
                                if res == QMessageBox.Ignore:
                                    ignore_z_in_wfs = True
                                else:
                                    return
                    add_resource_as_wfs_layers(ngw_resource)
                elif isinstance(ngw_resource, NGWWmsService):
                    utils.add_wms_layer(
                        ngw_resource.common.display_name,
                        ngw_resource.get_url(),
                        ngw_resource.get_layer_keys(),
                        len(ngw_resource.get_layer_keys()) > 1
                    )
                elif isinstance(ngw_resource, NGWWmsConnection):
                    utils.add_wms_layer(
                        ngw_resource.common.display_name,
                        ngw_resource.get_connection_url(),
                        ngw_resource.layers(),
                        len(ngw_resource.layers()) > 1
                    )
                elif isinstance(ngw_resource, NGWWmsLayer):
                    utils.add_wms_layer(
                        ngw_resource.common.display_name,
                        ngw_resource.ngw_wms_connection_url,
                        ngw_resource.ngw_wms_layers,
                    )

            except Exception as ex:
                error_mes = str(ex)
                self.iface.messageBar().pushMessage(
                    self.tr('Error'),
                    error_mes,
                    level=Qgis.Critical
                )
                qgisLog(error_mes, level=Qgis.Critical)

    def create_group(self):
        sel_index = self.trvResources.selectedIndex()
        # if sel_index is None:
        #     sel_index = self._resource_model.index(0, 0, QModelIndex())
        if sel_index is None or not sel_index.isValid():
            self.show_info(self.tr('Please select parent resource group for a new resource group'))
            return

        new_group_name, ok = QInputDialog.getText(
            self,
            self.tr("Create resource group"),
            self.tr("Resource group name:"),
            QLineEdit.Normal,
            self.tr("New resource group"),
            Qt.Dialog
        )
        if (not ok or new_group_name == ""):
            return

        self.create_group_resp = self._resource_model.tryCreateNGWGroup(new_group_name, sel_index)
        self.create_group_resp.done.connect(
            self.trvResources.setCurrentIndex
        )

    def upload_project_resources(self):
        """
        Upload whole project to NextGIS Web
        """

        def get_project_name():
            current_project_title = ''
            current_project = QgsProject.instance()
            if current_project.title() != '':
                current_project_title = current_project.title()
            elif current_project.fileName() != '':
                current_project_title = current_project.baseName()

            return current_project_title

        ngw_current_index = self.trvResources.selectionModel().currentIndex()

        dlg = UploadQGISProjectDialog(get_project_name(), self)
        result = dlg.exec_()
        if not result:
            return

        project_name = dlg.projectName()

        self.qgis_proj_import_response = self._resource_model.uploadProjectResources(
            project_name,
            ngw_current_index,
            self.iface,
        )
        self.qgis_proj_import_response.done.connect(
            self.trvResources.setCurrentIndex
        )
        self.qgis_proj_import_response.done.connect(
            self.open_create_web_map
        )
        self.qgis_proj_import_response.done.connect(
            self.processWarnings
        )

    def upload_selected_resources(self):
        ngw_current_index = self.trvResources.selectionModel().currentIndex()

        qgs_layer_tree_nodes = self.iface.layerTreeView().selectedNodes(skipInternal=True)
        if len(qgs_layer_tree_nodes) == 0: # could be if user had deleted layer but have not selected one after that
            qgs_layer_tree_nodes = [self.iface.layerTreeView().currentNode()]
            if len(qgs_layer_tree_nodes) == 0: # just in case if checkImportActionsAvailability() works incorrectly
                return

        self.import_layer_response = self._resource_model.uploadResourcesList(qgs_layer_tree_nodes, ngw_current_index, self.iface)
        self.import_layer_response.done.connect(
            self.trvResources.setCurrentIndex
        )
        self.import_layer_response.done.connect(
            self.processWarnings
        )

    def overwrite_ngw_layer(self):
        index = self.trvResources.selectionModel().currentIndex()
        qgs_map_layer = self.iface.mapCanvas().currentLayer()

        result = QMessageBox.question(
            self,
            self.tr("Overwrite resource"),
            self.tr("Resource '%s' will be overwritten with QGIS layer '%s'. Current data will be lost.<br/> Are you sure you want to overwrite it?") % (
                index.data(Qt.DisplayRole),
                html.escape(qgs_map_layer.name())
            ),
            QMessageBox.Yes | QMessageBox.No
        )
        if result != QMessageBox.Yes:
            return

        if isinstance(qgs_map_layer, QgsVectorLayer):
            self._resource_model.updateNGWLayer(index, qgs_map_layer)
        else:
            pass

    def edit_metadata(self):
        ''' Edit metadata table
        '''
        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index.isValid():
            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            self.block_gui()

            try:
                self.trvResources.ngw_job_block_overlay.show()
                self.trvResources.ngw_job_block_overlay.text.setText(
                    "<strong>{} {}</strong><br/>".format(self.tr('Get resource metadata'), ngw_resource.common.display_name)
                )
                ngw_resource.update()
                self.trvResources.ngw_job_block_overlay.hide()

                dlg = MetadataDialog(ngw_resource, self)
                _ = dlg.exec_()

            except NGWError:
                error_mes = str(traceback.format_exc())
                self.iface.messageBar().pushMessage(
                    self.tr('Error'),
                    self.tr("Error occurred while communicating with Web GIS."),
                    level=Qgis.Critical
                )
                self.trvResources.ngw_job_block_overlay.hide()
                ngwApiLog(error_mes, level=Qgis.Critical)

            except Exception as ex:
                error_mes = str(traceback.format_exc())
                self.iface.messageBar().pushMessage(
                    self.tr('Error'),
                    ex,
                    level=Qgis.Critical
                )
                self.trvResources.ngw_job_block_overlay.hide()
                ngwApiLog(error_mes, level=Qgis.Critical)

            self.unblock_gui()

    def update_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        sel_index = self.trvResources.selectionModel().currentIndex()
        response = self._resource_model.updateQGISStyle(qgs_map_layer, sel_index)
        response.done.connect(
            self.trvResources.setCurrentIndex
        )

    def add_style(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        sel_index = self.trvResources.selectionModel().currentIndex()
        response = self._resource_model.addQGISStyle(qgs_map_layer, sel_index)
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

    def _downloadRasterSource(self, ngw_lyr, raster_file=None):
        ''' Download raster layer source file
            using QNetworkAccessManager.
            Download and write file by chunks
            using readyRead signal

            return QFile object
        '''
        if not raster_file:
            raster_file = QTemporaryFile()
        else:
            raster_file = QFile(raster_file)

        url = '{}/download'.format(ngw_lyr.get_absolute_api_url())
        def write_chuck():
            if reply.error():
                raise Exception('{} {}'.format(self.tr('Failed to download raster source:'), reply.errorString()))
            data = reply.readAll()
            log('Write chunk! Size: {}'.format(data.size()))
            raster_file.write(data)

        req = QNetworkRequest(QUrl(url))
        creds = ngw_lyr.get_creds()
        if creds is not None:
            creds_str = creds[0] + ':' + creds[1]
            authstr = creds_str.encode('utf-8')
            authstr = QByteArray(authstr).toBase64()
            authstr = QByteArray(('Basic ').encode('utf-8')).append(authstr)
            req.setRawHeader(("Authorization").encode('utf-8'), authstr)

        if raster_file.open(QIODevice.WriteOnly):

            ev_loop = QEventLoop()
            dwn_qml_manager = QNetworkAccessManager()

            # dwn_qml_manager.finished.connect(ev_loop.quit)
            reply = dwn_qml_manager.get(req)

            reply.readyRead.connect(write_chuck)
            reply.finished.connect(ev_loop.quit)

            ev_loop.exec_()

            write_chuck()
            raster_file.close()
            reply.deleteLater()

            return raster_file
        else:
            raise Exception(self.tr("Can't open file to write raster!"))


    def _copy_resource(self, ngw_src):
        ''' Create a copy of a ngw raster or vector layer
            1) Download ngw layer sources
            2) Create QGIS hidden layer
            3) Export layer to ngw
            4) Add styles to new ngw layer
        '''
        def qml_callback(total_size, readed_size):
            ngwApiLog(
                'Style for "%s" - Upload (%d%%)' % (
                    ngw_src.common.display_name,
                    readed_size * 100 / total_size
                )
            )

        style_resource = None

        ngw_group = ngw_src.get_parent()
        child_resources = ngw_src.get_children()
        style_resources = []
        # assume that there can be only a style of appropriate for the layer type
        for child_resource in child_resources:
            if (child_resource.type_id == NGWQGISVectorStyle.type_id or
                child_resource.type_id == NGWQGISRasterStyle.type_id):
                style_resources.append(child_resource)

        # Download sources and create a QGIS layer
        if ngw_src.type_id == NGWVectorLayer.type_id:
            qgs_layer = QgsVectorLayer(
                ngw_src.get_absolute_geojson_url(),
                ngw_src.common.display_name,
                'ogr'
            )
            if not qgs_layer.isValid():
                raise Exception('Layer "%s" can\'t be added to the map!' % ngw_src.common.display_name)
            qgs_layer.dataProvider().setEncoding('UTF-8')

        elif ngw_src.type_id == NGWRasterLayer.type_id:
            raster_file = self._downloadRasterSource(ngw_src)
            qgs_layer = QgsRasterLayer(raster_file.fileName(), ngw_src.common.display_name, 'gdal')
            if not qgs_layer.isValid():
                log('Failed to add raster layer to QGIS')
                raise Exception('Layer "%s" can\'t be added to the map!' % ngw_src.common.display_name)
        else:
            raise Exception('Wrong layer type! Type id: {}' % ngw_src.type_id)

        # Export QGIS layer to NGW
        resJob = QGISResourceJob()
        ngw_res = resJob.importQGISMapLayer(qgs_layer, ngw_group)[0]

        # Remove temp layer and sources
        del qgs_layer
        if ngw_src.type_id == NGWRasterLayer.type_id:
            raster_file.remove()

        # Export styles to new NGW layer
        for style_resource in style_resources:
            self._downloadStyleAsQML(style_resource, mes_bar=False)

            ngw_style = ngw_res.create_qml_style(
                self.dwn_qml_file.fileName(),
                qml_callback,
                style_name=style_resource.common.display_name
            )
            self.dwn_qml_file.remove()
            ngw_res.update()

        return ngw_res

    def copy_curent_ngw_resource(self):
        ''' Copying the selected ngw resource.
            Only GUI stuff here, main part
            in _copy_resource function
        '''
        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index.isValid():
            # ckeckbox
            res = QMessageBox.question(
                self,
                self.tr("Copy resource"),
                self.tr("Are you sure you want to copy this resource?"),
                QMessageBox.Yes and QMessageBox.No,
                QMessageBox.Yes
            )
            if res == QMessageBox.No:
                return

            ngw_resource = sel_index.data(QNGWResourceItem.NGWResourceRole)

            # block gui
            self.trvResources.ngw_job_block_overlay.show()
            self.block_gui()
            self.trvResources.ngw_job_block_overlay.text.setText(
                "<strong>{} {}</strong><br/>".format(self.tr('Copying'), ngw_resource.common.display_name)
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
                    self.tr('Error'),
                    error_mes,
                    level=Qgis.Critical
                )
                qgisLog(error_mes, level=Qgis.Critical)

            # unblock gui
            self.trvResources.ngw_job_block_overlay.hide()
            self.unblock_gui()

    def create_wfs_service(self):
        selected_index = self.trvResources.selectionModel().currentIndex()

        if not selected_index.isValid():
            selected_index = self.index(0, 0, selected_index)

        item = selected_index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        if isinstance(ngw_resource, NGWVectorLayer) and ngw_resource.is_geom_with_z():
            self.show_error(self.tr(
                'You are trying to create a WFS service '
                'for a layer that contains Z geometries. '
                'WFS in QGIS doesn\'t fully support editing such geometries. '
                'To fix this, change geometry type of your layer to non-Z '
                'and create a WFS service again.'))
            return

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

        response = self._resource_model.createWFSForVector(selected_index, ret_obj_num)
        response.done.connect(
            self.trvResources.setCurrentIndex
        )
        response.done.connect(
            self.add_created_wfs_service
        )

    def add_created_wfs_service(self, index):
        if not PluginSettings.auto_add_wfs_option():
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        add_resource_as_wfs_layers(ngw_resource)

    def create_wms_service(self):
        selected_index = self.trvResources.selectionModel().currentIndex()

        dlg = NGWLayerStyleChooserDialog(self.tr("Create WMS service for layer"), selected_index, self._resource_model, self)
        result = dlg.exec_()
        if result:
            ngw_resource_style_id = None
            if dlg.selectedStyleId():
                ngw_resource_style_id = dlg.selectedStyleId()

            responce = self._resource_model.createWMSForVector(selected_index, ngw_resource_style_id)
            responce.done.connect(
                self.trvResources.setCurrentIndex
            )

    def create_web_map_for_style(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        self.create_map_response = self._resource_model.createMapForStyle(selected_index)

        self.create_map_response.done.connect(
            self.open_create_web_map
        )

    def create_web_map_for_layer(self):
        selected_index = self.trvResources.selectionModel().currentIndex()

        ngw_resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        if ngw_resource.type_id in [NGWVectorLayer.type_id, NGWRasterLayer.type_id]:
            ngw_styles = ngw_resource.get_children()
            ngw_resource_style_id = None

            if len(ngw_styles) == 1:
                ngw_resource_style_id = ngw_styles[0].common.id
            elif len(ngw_styles) > 1:
                dlg = NGWLayerStyleChooserDialog(self.tr("Create web map for layer"), selected_index, self._resource_model, self)
                result = dlg.exec_()
                if result:
                    if dlg.selectedStyleId():
                        ngw_resource_style_id = dlg.selectedStyleId()
                else:
                    return # do nothing after closing the dialog

            self.create_map_response = self._resource_model.createMapForLayer(
                selected_index,
                ngw_resource_style_id
            )

        elif ngw_resource.type_id == NGWWmsLayer.type_id:
            self.create_map_response = self._resource_model.createMapForLayer(
                selected_index,
                None
            )

        self.create_map_response.done.connect(
            self.trvResources.setCurrentIndex
        )
        self.create_map_response.done.connect(
            self.open_create_web_map
        )

    def open_create_web_map(self, index):
        if not PluginSettings.auto_open_web_map_option():
            return

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        url = ngw_resource.get_display_url()
        QDesktopServices.openUrl(QUrl(url))

    def processWarnings(self, index):
        ngw_model_job_resp = self.sender()
        job_id = ngw_model_job_resp.job_id
        if len(ngw_model_job_resp.warnings()) > 0:
            dlg = ExceptionsListDialog(self.tr("NextGIS Connect operation exceptions"), self)
            for w in ngw_model_job_resp.warnings():
                w_msg, w_msg_ext, icon = self.__get_model_exception_description(job_id, w)
                dlg.addException(w_msg, w_msg_ext, icon)
                dlg.show()


    def _downloadStyleAsQML(self, ngw_style, qml_file=None, mes_bar=True):
        if not qml_file:
            self.dwn_qml_file = QTemporaryFile()
        else:
            self.dwn_qml_file = QFile(qml_file)

        url = ngw_style.download_qml_url()

        req = QNetworkRequest(QUrl(url))
        creds = ngw_style.get_creds_for_qml()
        if creds is not None:
            creds_str = creds[0] + ':' + creds[1]
            authstr = creds_str.encode('utf-8')
            authstr = QByteArray(authstr).toBase64()
            authstr = QByteArray(('Basic ').encode('utf-8')).append(authstr)
            req.setRawHeader(("Authorization").encode('utf-8'), authstr)

        ev_loop = QEventLoop()
        dwn_qml_manager = QNetworkAccessManager()
        dwn_qml_manager.finished.connect(ev_loop.quit)
        reply = dwn_qml_manager.get(req)
        ev_loop.exec_()

        if reply.error():
            ngwApiLog('Failed to download QML: {}'.format(reply.errorString()))

        if self.dwn_qml_file.open(QIODevice.WriteOnly):
            ngwApiLog('dwn_qml_file: {}'.format(self.dwn_qml_file.fileName()))
            self.dwn_qml_file.write(reply.readAll())
            self.dwn_qml_file.close()
            if mes_bar:
                self.__msg_in_qgis_mes_bar(self.tr("QML file downloaded"), False, duration=2)
        else:
            if mes_bar:
                self.__msg_in_qgis_mes_bar(
                    self.tr("QML file could not be downloaded"),
                    True,
                    Qgis.Critical
                )

        reply.deleteLater()


    def downloadQML(self):
        selected_index = self.trvResources.selectionModel().currentIndex()
        ngw_qgis_style = selected_index.data(QNGWResourceItem.NGWResourceRole)

        filepath, selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Save QML"),
            "%s.qml" % ngw_qgis_style.common.display_name,
            filter=self.tr("QGIS style (*.qml)")
        )

        if filepath == "":
            return

        self._downloadStyleAsQML(ngw_qgis_style, qml_file=filepath)

    def show_msg_box(self, text, title, icon, buttons):
        box = QMessageBox()
        box.setText(text)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setStandardButtons(buttons)
        return box.exec_()

    def show_info(self, text, title=None):
        if title is None:
            title = self.tr('Information')
        self.show_msg_box(text, title, QMessageBox.Information, QMessageBox.Ok)

    def show_error(self, text, title=None):
        if title is None:
            title = self.tr('Error')
        self.show_msg_box(text, title, QMessageBox.Critical, QMessageBox.Ok)


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
