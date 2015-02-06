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
from PyQt4 import uic
from PyQt4.QtGui import QDockWidget, QMainWindow, QIcon
from PyQt4.QtCore import Qt, QModelIndex
from qgis.core import QgsMessageLog
from qgis.gui import QgsMessageBar
from ngw_api.core.ngw_error import NGWError
from ngw_api.core.ngw_group_resource import NGWGroupResource
from ngw_api.core.ngw_resource_creator import ResourceCreator
from ngw_api.core.ngw_vector_layer import NGWVectorLayer
from ngw_api.core.ngw_wfs_service import NGWWfsService

from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from ngw_api.qgis.resource_to_map import add_resource_as_geojson, add_resource_as_wfs_layers
from ngw_api.qt.qt_ngw_fake_root_item import QNGWFakeRootItem
from ngw_api.qt.qt_ngw_resource_model import QNGWResourcesModel
from ngw_api.core.ngw_resource_factory import NGWResourceFactory
from settings_dialog import SettingsDialog


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
        self.actionCreateNewGroup.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionNewFolder.png')))
        self.actionCreateNewGroup.triggered.connect(self.create_group)
        self.actionSettings.setIcon(QIcon(os.path.join(ICONS_PATH, 'mActionSettings')))
        self.actionSettings.triggered.connect(self.action_settings)

        #update state
        self.update_conn_list()
        self.reinit_tree(self.cmbConnection.currentText())

        #signals
        self.cmbConnection.currentIndexChanged[str].connect(self.reinit_tree)

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
        self.trvResources.setModel(None)
        self.disable_tools()

        if not name_of_conn:
            return
        conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)

        # setup ngw api
        rsc_factory = NGWResourceFactory(conn_sett)

        try:
            root_rsc = rsc_factory.get_root_resource()
        except Exception, e:
            error_message = self.tr('Error on fetch resources: ') + e.message
            self.iface.messageBar().pushMessage(self.tr('ERROR'),
                                                error_message,
                                                level=QgsMessageBar.CRITICAL)
            QgsMessageLog.logMessage(error_message, level=QgsMessageLog.CRITICAL)
            return

        # setup new qt model
        self._root_item = QNGWFakeRootItem(root_rsc, None)
        self._resource_model = QNGWResourcesModel(self._root_item)
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

    def disable_tools(self):
        self.actionAddAsGeoJSON.setEnabled(False)
        self.actionAddWFS.setEnabled(False)
        self.actionCreateNewGroup.setEnabled(False)

    def add_json_layer(self):
        sel_index = self.trvResources.selectionModel().currentIndex()
        print sel_index.isValid()
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
        sel_index = self.trvResources.selectionModel().currentIndex()

        if sel_index.isValid():
            ngw_resource = sel_index.data(Qt.UserRole)

            new_group_name = 'New group'
            existing_chd_names = [ch.common.display_name for ch in ngw_resource.get_children()]
            if new_group_name in existing_chd_names:
                id = 1
                while(new_group_name+str(id) in existing_chd_names):
                    id += 1
                new_group_name += str(id)

            try:
                ResourceCreator.create_group(ngw_resource, new_group_name)
            except NGWError as ex:
                error_mes = ex.message or ''
                self.iface.messageBar().pushMessage(self.tr('Error'),
                                                error_mes,
                                                level=QgsMessageBar.CRITICAL)
                QgsMessageLog.logMessage(error_mes, level=QgsMessageLog.CRITICAL)

            self.reinit_tree(self.cmbConnection.currentText())
            # TODO: need more flex update

    def action_settings(self):
        sett_dialog = SettingsDialog()
        sett_dialog.show()
        sett_dialog.exec_()

        self.update_conn_list()




