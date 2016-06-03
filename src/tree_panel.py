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
import json
import subprocess
import webbrowser
import functools
from urlparse import urlparse

from PyQt4 import uic
from PyQt4.QtGui import *
from PyQt4.QtCore import *
from qgis.core import QgsMessageLog, QgsProject, QgsMapLayer
from qgis.gui import QgsMessageBar
import sys
from ngw_api.core.ngw_error import NGWError
from ngw_api.core.ngw_group_resource import NGWGroupResource
# from ngw_api.core.ngw_resource_creator import ResourceCreator
from ngw_api.core.ngw_vector_layer import NGWVectorLayer
from ngw_api.core.ngw_webmap import NGWWebMap
from ngw_api.core.ngw_wfs_service import NGWWfsService
# from ngw_api.core.ngw_resource import NGWResource

from ngw_api.qgis.ngw_connection_edit_dialog import NGWConnectionEditDialog
from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from ngw_api.qgis.resource_to_map import add_resource_as_geojson, add_resource_as_wfs_layers
from ngw_api.qgis.ngw_resource_model_4qgis import QNGWResourcesModel4QGIS
from ngw_api.qt.qt_ngw_resource_item import QNGWResourceItemExt
# from ngw_api.qt.qt_ngw_fake_root_item import QNGWFakeRootItem
# from ngw_api.qt.qt_ngw_resource_model import QNGWResourcesModel
# from ngw_api.core.ngw_resource_factory import NGWResourceFactory
from settings_dialog import SettingsDialog

from plugin_settings import PluginSettings

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'tree_panel_base.ui'))

ICONS_PATH = os.path.join(os.path.dirname(__file__), 'icons/')


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
        self.setupUi(self)
        self.iface = iface

        # Do not use ui toolbar
        self.removeToolBar(self.mainToolBar)

        # actions
        self.actionExport = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionExport.svg')),
            self.tr("Add to QGIS"),
            self
        )
        self.actionExport.triggered.connect(self.__export_to_qgis)

        self.actionImportQGISResource = QAction(
            self.tr("Import selected layer"),
            self.iface.legendInterface()
        )
        self.actionImportQGISResource.triggered.connect(self.action_import_layer)
        self.actionImportQGISResource.setEnabled(False)

        self.actionImportQGISProject = QAction(
            self.tr("Import current project"),
            self.iface.legendInterface()
        )
        self.actionImportQGISProject.triggered.connect(self.action_import_qgis_project)

        self.menuImport = QMenu(
            self.tr("Add to Web GIS"),
            self
        )
        self.menuImport.setIcon(
            QIcon(os.path.join(ICONS_PATH, 'mActionImport.svg'))
        )
        self.menuImport.menuAction().setIconVisibleInMenu(False)
        self.menuImport.addAction(self.actionImportQGISResource)
        self.menuImport.addAction(self.actionImportQGISProject)

        # self.actionAddAsGeoJSON.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionAddOgrLayer.svg')))
        # self.actionAddAsGeoJSON.triggered.connect(self.add_json_layer)
        # self.actionAddWFS.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionAddWfsLayer.svg')))
        # self.actionAddWFS.triggered.connect(self.add_wfs_layer)
        # self.actionOpenMapInBrowser.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionOpenMap.svg')))
        # self.actionOpenMapInBrowser.triggered.connect(self.__action_open_map)
        # self.actionCreateNewGroup.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.png')))
        # self.actionCreateNewGroup.triggered.connect(self.create_group)
        # self.actionImportQGISProject.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionQGISImport.svg')))
        # self.actionImportQGISProject.triggered.connect(self.action_import_qgis_project)
        # self.actionRefresh.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionRefresh.svg')))
        # self.actionRefresh.triggered.connect(self.reinit_tree)
        # self.actionSettings.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionSettings.svg')))
        # self.actionSettings.triggered.connect(self.action_settings)

        self.actionCreateNewGroup = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.svg')),
            self.tr("Create new group"),
            self
        )
        self.actionCreateNewGroup.setToolTip(self.tr("Create new resource group"))
        self.actionCreateNewGroup.triggered.connect(self.create_group)

        self.actionCreateWFSService = QAction(
            QIcon(),
            self.tr("Create WFS service"),
            self
        )
        self.actionCreateWFSService.setToolTip(self.tr("Create WFS service"))
        self.actionCreateWFSService.triggered.connect(self.create_wfs_service)

        self.actionDeleteResource = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionDelete.svg')),
            self.tr("Delete"),
            self
        )
        self.actionDeleteResource.setToolTip(self.tr("Delete resource"))
        self.actionDeleteResource.triggered.connect(self.delete_curent_ngw_resource)

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
        self.actionRefresh.triggered.connect(self.reinit_tree)

        self.actionSettings = QAction(
            QIcon(os.path.join(ICONS_PATH, 'mActionSettings.svg')),
            self.tr("Settings"),
            self
        )
        self.actionSettings.setToolTip(self.tr("Settings"))
        self.actionSettings.triggered.connect(self.action_settings)

        # Add new toolbar
        self.main_tool_bar = self.addToolBar("main")
        self.main_tool_bar.setFloatable(False)
        self.main_tool_bar.addAction(self.actionExport)
        toolbutton = QToolButton()
        toolbutton.setPopupMode(QToolButton.InstantPopup)
        toolbutton.setMenu(self.menuImport)
        toolbutton.setIcon(self.menuImport.icon())
        toolbutton.setText(self.menuImport.title())
        toolbutton.setToolTip(self.menuImport.title())
        self.main_tool_bar.addWidget(toolbutton)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionCreateNewGroup)
        self.main_tool_bar.addAction(self.actionRefresh)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionOpenMapInBrowser)
        self.main_tool_bar.addSeparator()

        self.main_tool_bar.addAction(self.actionSettings)

        # ngw resources model
        self._resource_model = QNGWResourcesModel4QGIS()
        self._resource_model.errorOccurred.connect(self.__model_error_process)
        self._resource_model.jobStarted.connect(self.__modelJobStarted)
        self._resource_model.jobStatusChanged.connect(self.__modelJobStatusChanged)
        self._resource_model.jobFinished.connect(self.__modelJobFinished)
        self.blocked_jobs = {
            self._resource_model.JOB_CREATE_NGW_GROUP_RESOURCE: self.tr("Resource is being created"),
            self._resource_model.JOB_DELETE_NGW_RESOURCE: self.tr("Resource is being deleted"),
            self._resource_model.JOB_IMPORT_QGIS_RESOURCE: self.tr("Layer is being imported"),
            self._resource_model.JOB_IMPORT_QGIS_PROJECT: self.tr("Project is being imported"),
            self._resource_model.JOB_CREATE_NGW_WFS_SERVICE: self.tr("WFS service is being created"),
        }

        # ngw resources view
        self.trvResources = NGWResourcesTreeView(self)
        self.trvResources.setModel(self._resource_model)
        self.trvResources.customContextMenuRequested.connect(self.slotCustomContextMenu)
        self.trvResources.itemDoubleClicked.connect(self.trvDoubleClickProcess)

        self.nrw_reorces_tree_container.addWidget(self.trvResources)

        # update state
        self.reinit_tree()

        # Help message label
        url = "http://%s/docs_ngcom/source/ngqgis_connect.html" % self.tr("docs.nextgis.com")
        self.helpMessageLabel.setText(
            ' <span style="font-weight:bold;font-size:12px;color:blue;">?    </span><a href="%s">%s</a>' % (
                url,
                self.tr("Help")
            )
        )

        self.iface.currentLayerChanged.connect(self.__checkImportActions)

        # ----------------------------------------------
        # Configurate new WebGIS InfoWidget
        # This widget may be useful in the future
        self.webGISCreationMessageWidget.setVisible(False)
        # self.webGISCreationMessageCloseLable.linkActivated.connect(self.__closeNewWebGISInfoWidget)
        # if PluginSettings.webgis_creation_message_closed_by_user():
        #     self.webGISCreationMessageWidget.setVisible(False)
        # ----------------------------------------------

    # def __closeNewWebGISInfoWidget(self, link):
    #     self.webGISCreationMessageWidget.setVisible(False)
    #     PluginSettings.set_webgis_creation_message_closed_by_user(True)

    def __checkImportActions(self, current_qgis_layer):
        if current_qgis_layer is None:
            self.actionImportQGISResource.setEnabled(False)
        elif isinstance(current_qgis_layer, QgsMapLayer):
            self.actionImportQGISResource.setEnabled(True)
        print "current_qgis_layer: ", current_qgis_layer

    def __model_error_process(self, job, exception):
        QgsMessageLog.logMessage("model error process job: %d" % job)
        QgsMessageLog.logMessage("JOB_CREATE_NGW_WFS_SERVICE: %d" % self._resource_model.JOB_CREATE_NGW_WFS_SERVICE)

        error_mes = "Error in unknown operation"
        if job == self._resource_model.JOB_LOAD_NGW_RESOURCE_CHILDREN:
            error_mes = self.tr("Loading resource error. Check your connection settings. See log for details.")
        elif job == self._resource_model.JOB_CREATE_NGW_GROUP_RESOURCE:
            error_mes = self.tr("Creating group resource error.")
        elif job == self._resource_model.JOB_IMPORT_QGIS_RESOURCE:
            error_mes = self.tr("Creating layer resource error.")
        elif job == self._resource_model.JOB_CREATE_NGW_WFS_SERVICE:
            error_mes = self.tr("Creating WFS service error. See log for details.")

        self.iface.messageBar().pushMessage(
            self.tr('Error'),
            error_mes,
            level=QgsMessageBar.CRITICAL
        )

        if isinstance(exception, NGWError):
            try:
                exeption_dict = json.loads(exception.message)
                exeption_type = exeption_dict.get("exception", "")

                name_of_conn = NgwPluginSettings.get_selected_ngw_connection_name()

                if exeption_type in ["HTTPForbidden", "ForbiddenError"]:
                    conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)
                    print "conn_sett: ", conn_sett
                    dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett)
                    dlg.leName.setDisabled(True)
                    dlg.leUrl.setDisabled(True)
                    dlg.setWindowTitle(
                        self.tr("Access denied. Enter your login.")
                    )
                    res = dlg.exec_()
                    QgsMessageLog.logMessage("res: %d" % res)
                    if res:
                        conn_sett = dlg.ngw_connection_settings
                        NgwPluginSettings.save_ngw_connection(conn_sett)
                        self.reinit_tree()
                    del dlg

                ngw_err_msg = exeption_dict.get("message", "")

                QgsMessageLog.logMessage(
                    "%s\n\t %s" % (error_mes, ngw_err_msg),
                    PluginSettings._product,
                    level=QgsMessageLog.CRITICAL
                )

            except Exception as e:
                QgsMessageLog.logMessage(
                    "Error when proccess NGW Error: %s" % (e),
                    PluginSettings._product,
                    level=QgsMessageLog.CRITICAL
                )
        else:

            QgsMessageLog.logMessage(
                "%s\n\t %s" % (error_mes, exception),
                PluginSettings._product,
                level=QgsMessageLog.CRITICAL
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

    def reinit_tree(self):
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

        self._resource_model.resetModel(conn_sett)

        # expand root item
        self.trvResources.setExpanded(self._resource_model.index(0, 0, QModelIndex()), True)
        # reconnect signals
        self.trvResources.selectionModel().currentChanged.connect(self.active_item_chg)

        # save last selected connection
        # NgwPluginSettings.set_selected_ngw_connection_name(name_of_conn)

    def active_item_chg(self, selected, deselected):
        ngw_resource = selected.data(Qt.UserRole)
        # TODO: NEED REFACTORING! Make isCompatible methods!
        # enable/dis geojson button
        # self.actionAddAsGeoJSON.setEnabled(isinstance(ngw_resource, NGWVectorLayer))
        # enable/dis wfs button
        # self.actionAddWFS.setEnabled(isinstance(ngw_resource, NGWWfsService))
        self.actionExport.setEnabled(
            isinstance(
                ngw_resource,
                (
                    NGWWfsService,
                    NGWVectorLayer
                )
            )
        )
        # enable/dis new group button
        # self.actionCreateNewGroup.setEnabled(isinstance(ngw_resource, NGWGroupResource))
        # enable/dis webmap
        self.actionOpenMapInBrowser.setEnabled(isinstance(ngw_resource, NGWWebMap))

    def disable_tools(self):
        # self.actionAddAsGeoJSON.setEnabled(False)
        # self.actionAddWFS.setEnabled(False)
        self.actionExport.setEnabled(False)
        # self.actionCreateNewGroup.setEnabled(False)
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
        if isinstance(ngw_resource, NGWGroupResource):
            menu.addAction(self.actionCreateNewGroup)
        elif isinstance(ngw_resource, NGWVectorLayer):
            menu.addAction(self.actionExport)
            menu.addAction(self.actionCreateWFSService)
        elif isinstance(ngw_resource, NGWWfsService):
            menu.addAction(self.actionExport)
        elif isinstance(ngw_resource, NGWWebMap):
            menu.addAction(self.actionOpenMapInBrowser)

        menu.addSeparator()
        menu.addAction(self.actionDeleteResource)

        menu.exec_(self.trvResources.viewport().mapToGlobal(qpoint))

    def trvDoubleClickProcess(self, index):
        ngw_resource = index.data(QNGWResourceItemExt.NGWResourceRole)
        if isinstance(ngw_resource, NGWWebMap):
            self.__action_open_map()

    def __action_open_map(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)
            url = ngw_resource.get_display_url()
            if sys.platform == 'darwin':    # in case of OS X
                subprocess.Popen(['open', url])
            else:
                webbrowser.open_new_tab(url)

    def __export_to_qgis(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)
            try:
                if isinstance(ngw_resource, NGWVectorLayer):
                    add_resource_as_geojson(ngw_resource)
                elif isinstance(ngw_resource, NGWWfsService):
                    add_resource_as_wfs_layers(ngw_resource)

            except NGWError as ex:
                error_mes = ex.message or ''
                self.iface.messageBar().pushMessage(
                    self.tr('Error'),
                    error_mes,
                    level=QgsMessageBar.CRITICAL
                )
                QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

    # def add_json_layer(self):
    #     sel_index = self.trvResources.selectionModel().currentIndex()
    #     # print sel_index.isValid()
    #     if sel_index.isValid():
    #         ngw_resource = sel_index.data(Qt.UserRole)

    #         try:
    #             add_resource_as_geojson(ngw_resource)
    #         except NGWError as ex:
    #             error_mes = ex.message or ''
    #             self.iface.messageBar().pushMessage(
    #                 self.tr('Error'),
    #                 error_mes,
    #                 level=QgsMessageBar.CRITICAL
    #             )
    #             QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

    # def add_wfs_layer(self):
    #     sel_index = self.trvResources.selectionModel().currentIndex()

    #     if sel_index.isValid():
    #         ngw_resource = sel_index.data(Qt.UserRole)

    #         try:
    #             add_resource_as_wfs_layers(ngw_resource)
    #         except NGWError as ex:
    #             error_mes = ex.message or ''
    #             self.iface.messageBar().pushMessage(
    #                 self.tr('Error'),
    #                 error_mes,
    #                 level=QgsMessageBar.CRITICAL
    #             )
    #             QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

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

        sel_index = self.trvResources.selectionModel().currentIndex()
        if sel_index is None:
            sel_index = self._resource_model.index(0, 0, QModelIndex())
        self._resource_model.tryCreateNGWGroup(new_group_name, sel_index)

    def action_import_qgis_project(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        current_project = QgsProject.instance()
        current_project_title = current_project.title()

        new_group_name, res = QInputDialog.getText(
            self,
            self.tr("Set import project name"),
            self.tr("Import project name:"),
            QLineEdit.Normal,
            current_project_title,
            Qt.Dialog
        )

        if new_group_name == u'':
            QMessageBox.critical(
                self,
                self.tr("Project import error"),
                self.tr("Empty project name")
            )
            return

        self._resource_model.tryImportCurentQGISProject(new_group_name, sel_index, self.iface)

    def action_import_layer(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        sel_index = self.trvResources.selectionModel().currentIndex()
        self._resource_model.createNGWLayer(qgs_map_layer, sel_index)

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
            self._resource_model.deleteResource(selected_index)

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
        self._resource_model.createWFSForVector(selected_index, ret_obj_num)


# from PyQt4.QtCore import 
from PyQt4 import QtGui


class Overlay(QtGui.QWidget):
    def __init__(self, parent):
        QtGui.QWidget.__init__(self, parent)
        # self.resize(parent.size())
        palette = QtGui.QPalette(self.palette())
        palette.setColor(palette.Background, Qt.transparent)
        self.setPalette(palette)

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(event.rect(), QtGui.QBrush(QtGui.QColor(255, 255, 255, 200)))
        painter.setPen(QtGui.QPen(Qt.NoPen))


class MessageOverlay(Overlay):
    def __init__(self, parent, text):
        Overlay.__init__(self, parent)
        self.layout = QtGui.QHBoxLayout(self)
        self.setLayout(self.layout)

        self.text = QtGui.QLabel(text, self)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.layout.addWidget(self.text)


class ProcessOverlay(Overlay):
    def __init__(self, parent):
        Overlay.__init__(self, parent)
        self.layout = QtGui.QVBoxLayout(self)
        self.setLayout(self.layout)

        spacer_before = QtGui.QSpacerItem(20, 40, QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding)
        spacer_after = QtGui.QSpacerItem(20, 40, QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding)
        self.layout.addItem(spacer_before)

        self.central_widget = QtGui.QWidget(self)
        # self.central_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.central_widget_layout = QtGui.QVBoxLayout(self.central_widget)
        self.central_widget.setLayout(self.central_widget_layout)
        self.layout.addWidget(self.central_widget)

        self.layout.addItem(spacer_after)

        self.progress = QtGui.QProgressBar(self)
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

        self.text = QtGui.QLabel(self)
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


class NGWResourcesTreeView(QtGui.QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        QtGui.QTreeView.__init__(self, parent)

        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

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
        model.rowsInserted.connect(self.__insertRowsProcess)
        super(NGWResourcesTreeView, self).setModel(model)

    def __insertRowsProcess(self, parent, start, end):
        self.setExpanded(parent, True)

    def resizeEvent(self, event):
        self.no_ngw_connections_overlay.resize(event.size())
        self.ngw_job_block_overlay.resize(event.size())

        event.accept()

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
