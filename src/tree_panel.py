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
        copyright            : (C) 2014 by NextGIS
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
import subprocess
import webbrowser
from PyQt4 import uic
from PyQt4.QtGui import QDockWidget, QMainWindow, QIcon, QInputDialog, QLineEdit, QMenu, QMessageBox, QAction
from PyQt4.QtCore import Qt, QModelIndex
from qgis.core import QgsMessageLog, QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup
from qgis.gui import QgsMessageBar, QgsBusyIndicatorDialog
import sys
from ngw_api.core.ngw_error import NGWError
from ngw_api.core.ngw_group_resource import NGWGroupResource
from ngw_api.core.ngw_resource_creator import ResourceCreator
from ngw_api.core.ngw_vector_layer import NGWVectorLayer
from ngw_api.core.ngw_webmap import NGWWebMap
from ngw_api.core.ngw_wfs_service import NGWWfsService
from ngw_api.core.ngw_resource import NGWResource

from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from ngw_api.qgis.resource_to_map import add_resource_as_geojson, add_resource_as_wfs_layers
from ngw_api.qgis.ngw_resource_model_4qgis import QNGWResourcesModel4QGIS
from ngw_api.qt.qt_ngw_fake_root_item import QNGWFakeRootItem
from ngw_api.qt.qt_ngw_resource_model import QNGWResourcesModel, QNGWResourceModelError
from ngw_api.core.ngw_resource_factory import NGWResourceFactory
from settings_dialog import SettingsDialog

from plugin_settings import PluginSettings

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'tree_panel_base.ui'))

ICONS_PATH = os.path.join(os.path.dirname(__file__), 'icons/')


class TreePanel(QDockWidget):
    def __init__(self, iface, parent=None):
        #init dock
        super(TreePanel, self).__init__(parent)
        self.setWindowTitle(self.tr('NGW Resources'))

        #init internal control
        self.inner_control = TreeControl(iface, self)
        self.inner_control.setWindowFlags(Qt.Widget)
        self.setWidget(self.inner_control)


class TreeControl(QMainWindow, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super(TreeControl, self).__init__(parent)
        self.setupUi(self)

        self.iface = iface

        # actions
        self.actionAddAsGeoJSON.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionAddOgrLayer.svg')))
        self.actionAddAsGeoJSON.triggered.connect(self.add_json_layer)
        self.actionAddWFS.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionAddWfsLayer.svg')))
        self.actionAddWFS.triggered.connect(self.add_wfs_layer)
        self.actionOpenMapInBrowser.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionOpenMap.svg')))
        self.actionOpenMapInBrowser.triggered.connect(self.action_open_map)
        self.actionCreateNewGroup.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.png')))
        self.actionCreateNewGroup.triggered.connect(self.create_group)
        self.actionImportQGISProject.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionQGISImport.svg')))
        self.actionImportQGISProject.triggered.connect(self.action_import_qgis_project)
        self.actionRefresh.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionRefresh.svg')))
        self.actionRefresh.triggered.connect(self.action_refresh)
        self.actionSettings.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionSettings.svg')))
        self.actionSettings.triggered.connect(self.action_settings)

        # actions on qgis resources
        # self.actionImportQGISProject = QAction(
        #     QIcon(os.path.join(ICONS_PATH, 'mActionQGISImport.svg')),
        #     self.tr("Import current project"),
        #     self.iface.legendInterface()
        # )
        # self.actionImportQGISProject.triggered.connect(self.action_import_qgis_project)

        self.actionImportQGISResource = QAction(
            self.tr("Import selected"),
            self.iface.legendInterface()
        )
        self.actionImportQGISResource.triggered.connect(self.action_import_layer)

        # ngw resources model
        self._resource_model = QNGWResourcesModel4QGIS()
        self._resource_model.errorOccurred.connect(self.model_error_process)
        # self._resource_model.qgisProjectImportStarted.connect(self.__importStarted)
        # self._resource_model.qgisProjectImportFinished.connect(self.__importFinished)
        self._resource_model.jobStarted.connect(self.__modelJobStarted)
        self._resource_model.jobStatusChanged.connect(self.__modelJobStatusChanged)
        self._resource_model.jobFinished.connect(self.__modelJobFinished)
        self.blocked_jobs = {
            self._resource_model.JOB_CREATE_NGW_GROUP_RESOURCE: self.tr("NGW Resource is being created"),
            self._resource_model.JOB_DELETE_NGW_RESOURCE: self.tr("NGW Resource is being deleted"),
            self._resource_model.JOB_IMPORT_QGIS_RESOURCE: self.tr("Layer is being imported"),
            self._resource_model.JOB_IMPORT_QGIS_PROJECT: self.tr("Project is being imported"),
        }

        # update state
        self.update_conn_list()
        self.reinit_tree(self.cmbConnection.currentText())

        # signals
        self.cmbConnection.currentIndexChanged[str].connect(self.reinit_tree)
        self.trvResources.customContextMenuRequested.connect(self.slotCustomContextMenu)

    def model_error_process(self, code, msg):
        QgsMessageLog.logMessage("model_error_process code: %d" % code)

        error_mes = "Error in unknown operation"
        if code == QNGWResourceModelError.LoadResourceError:
            error_mes = self.tr("Loading resource error. Check your connection settings. See logs for details.")
        if code == QNGWResourceModelError.CreateGroupError:
            error_mes = self.tr("Creating ngw group resource error.")
        if code == QNGWResourceModelError.CreateLayerError:
            error_mes = self.tr("Creating ngw layer resource error.")

        self.iface.messageBar().pushMessage(
            self.tr('Error'),
            error_mes,
            level=QgsMessageBar.CRITICAL)

        QgsMessageLog.logMessage(
            "%s\n\t %s" % (error_mes, msg),
            PluginSettings._product,
            level=QgsMessageLog.CRITICAL
        )

    def __modelJobStarted(self, job_id):
        if job_id in self.blocked_jobs:
            self.progressDlg = QgsBusyIndicatorDialog()
            self.progressDlg.setWindowTitle(self.blocked_jobs[job_id])
            self.progressDlg.show()

    def __modelJobStatusChanged(self, job_id, status):
        if job_id in self.blocked_jobs:
            self.progressDlg.setMessage(status)

    def __modelJobFinished(self, job_id):
        if job_id in self.blocked_jobs:
            self.progressDlg.close()

    def update_conn_list(self):
        self.cmbConnection.clear()
        self.cmbConnection.addItems(NgwPluginSettings.get_ngw_connection_names())
        self.set_active_conn_from_sett()

    def set_active_conn_from_sett(self):
        last_connection = NgwPluginSettings.get_selected_ngw_connection_name()
        idx = self.cmbConnection.findText(last_connection)
        if idx == -1 and self.cmbConnection.count() > 0:
            self.cmbConnection.setCurrentIndex(0)
        else:
            self.cmbConnection.setCurrentIndex(idx)

    def reinit_tree(self, name_of_conn):
        # clear tree and states
        QgsMessageLog.logMessage("reinit_tree")

        # self.trvResources.setModel(None)
        self.disable_tools()

        if not name_of_conn:
            return

        conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)

        if not conn_sett:
            return

        # setup ngw api
        # rsc_factory = NGWResourceFactory(conn_sett)

        # try:
        #     root_rsc = rsc_factory.get_root_resource()
        # except Exception, e:
        #     error_message = self.tr('Error on fetch resources: ') + e.message
        #     self.iface.messageBar().pushMessage(self.tr('ERROR'),
        #                                         error_message,
        #                                         level=QgsMessageBar.CRITICAL)
        #     QgsMessageLog.logMessage(error_message, level=QgsMessageLog.CRITICAL)
        #     return

        # setup new qt model
        # self._root_item = QNGWFakeRootItem(root_rsc, None)
        # self._resource_model = QNGWResourcesModel(self._root_item)
        # self.trvResources.setModel(self._resource_model)
        self._resource_model.resetModel(conn_sett)

        self.trvResources.setModel(self._resource_model)

        # expand root item
        self.trvResources.setExpanded(self._resource_model.index(0, 0, QModelIndex()), True)

        # reconnect signals
        self.trvResources.selectionModel().currentChanged.connect(self.active_item_chg)

        # save last selected connection
        NgwPluginSettings.set_selected_ngw_connection_name(name_of_conn)

    def active_item_chg(self, selected, deselected):
        ngw_resource = selected.data(Qt.UserRole)
        # TODO: NEED REFACTORING! Make isCompatible methods!
        # enable/dis geojson button
        self.actionAddAsGeoJSON.setEnabled(isinstance(ngw_resource, NGWVectorLayer))
        # enable/dis wfs button
        self.actionAddWFS.setEnabled(isinstance(ngw_resource, NGWWfsService))
        # enable/dis new group button
        self.actionCreateNewGroup.setEnabled(isinstance(ngw_resource, NGWGroupResource))
        # enable/dis webmap
        self.actionOpenMapInBrowser.setEnabled(isinstance(ngw_resource, NGWWebMap))

    def disable_tools(self):
        self.actionAddAsGeoJSON.setEnabled(False)
        self.actionAddWFS.setEnabled(False)
        self.actionCreateNewGroup.setEnabled(False)
        self.actionOpenMapInBrowser.setEnabled(False)

    def add_json_layer(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        # print sel_index.isValid()
        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)

            try:
                add_resource_as_geojson(ngw_resource)
            except NGWError as ex:
                error_mes = ex.message or ''
                self.iface.messageBar().pushMessage(self.tr('Error'),
                                                error_mes,
                                                level=QgsMessageBar.CRITICAL)
                QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

    def add_wfs_layer(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)

            try:
                add_resource_as_wfs_layers(ngw_resource)
            except NGWError as ex:
                error_mes = ex.message or ''
                self.iface.messageBar().pushMessage(self.tr('Error'),
                                                error_mes,
                                                level=QgsMessageBar.CRITICAL)
                QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

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
        self._resource_model.tryCreateNGWGroup(new_group_name, sel_index)

    def action_refresh(self):
        self.reinit_tree(self.cmbConnection.currentText())  # TODO: more smart update (selected and childs)

    def action_settings(self):
        sett_dialog = SettingsDialog()
        sett_dialog.show()
        sett_dialog.exec_()

        self.update_conn_list()

    def action_open_map(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)
            url = ngw_resource.get_display_url()
            if sys.platform == 'darwin':    # in case of OS X
                subprocess.Popen(['open', url])
            else:
                webbrowser.open_new_tab(url)

    def action_import_qgis_project(self):
        sel_index = self.trvResources.selectionModel().currentIndex()

        current_project = QgsProject.instance()
        current_project_title = current_project.title()

        if current_project_title == u'':
            new_group_name, res = QInputDialog.getText(
                self,
                self.tr("Set import project name"),
                self.tr("Import project name:"),
                QLineEdit.Normal,
                current_project_title,
                Qt.Dialog
            )

            if res is False:
                return

            if new_group_name == "":
                QMessageBox.critical(
                    self,
                    self.tr("Import QGIS project error"),
                    self.tr("Empty import project name")
                )
                return

        self._resource_model.tryImportCurentQGISProject(new_group_name, sel_index, self.iface)

    def action_import_layer(self):
        qgs_map_layer = self.iface.mapCanvas().currentLayer()
        sel_index = self.trvResources.selectionModel().currentIndex()
        self._resource_model.createNGWLayer(qgs_map_layer, sel_index)

    def slotCustomContextMenu(self, qpoint):
        menu = QMenu()
        actionDelete = menu.addAction(self.tr("Delete"))
        actionDelete.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionDelete.svg')))
        actionDelete.triggered.connect(self.delete_curent_ngw_resource)

        actionNewGroup = menu.addAction(self.tr("New group"))
        actionNewGroup.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.png')))
        actionNewGroup.triggered.connect(self.create_group)

        menu.exec_(self.trvResources.viewport().mapToGlobal(qpoint))

    def delete_curent_ngw_resource(self):
        res = QMessageBox.question(
            self,
            self.tr("Delete ngw resource"),
            self.tr("Are you sure you want to remove the ngw resource?"),
            QMessageBox.Yes and QMessageBox.No,
            QMessageBox.Yes
        )

        if res == QMessageBox.Yes:
            selected_index = self.trvResources.selectionModel().currentIndex()
            self._resource_model.deleteResource(selected_index)
