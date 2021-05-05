# -*- coding: utf-8 -*-

# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SettingsDialog
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
__author__ = 'NextGIS'
__date__ = 'January 2015'
__copyright__ = '(C) 2015, NextGIS'

# This will get replaced with a git SHA1 when you do a git archive
__revision__ = '$Format:%H$'

import os
from qgis.PyQt import uic
from qgis.PyQt import QtCore
#from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtWidgets import *

from .ngw_api.qgis.ngw_connection_edit_dialog import NGWConnectionEditDialog
from .ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings as NgwApiSettings  # !!! Shared connection settings !!!

from .plugin_settings import PluginSettings

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'settings_dialog_base.ui'))


class SettingsDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        self.setupUi(self)
        # self.setFixedSize(self.size())

        self.btnNew.clicked.connect(self.new_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)

        self.populate_connection_list()

        self.chSanitizeRenameFields.setCheckState(
            QtCore.Qt.Checked if NgwApiSettings.get_sanitize_rename_fields() else QtCore.Qt.Unchecked
        )
        self.chSanitizeRenameFields.stateChanged.connect(self.sanitizeOptionsChanged)

        self.chSanitizeFixGeometry.setCheckState(
            QtCore.Qt.Checked if NgwApiSettings.get_sanitize_fix_geometry() else QtCore.Qt.Unchecked
        )
        self.chSanitizeFixGeometry.stateChanged.connect(self.sanitizeOptionsChanged)

        self.cbForceImport.setCheckState(
            QtCore.Qt.Unchecked if NgwApiSettings.get_force_qgis_project_import() else QtCore.Qt.Checked
        )
        self.cbForceImport.stateChanged.connect(self.forceImportChanged)

        self.cbAutoOpenWebMap.setCheckState(
            QtCore.Qt.Checked if PluginSettings.auto_open_web_map_option() else QtCore.Qt.Unchecked
        )
        self.cbAutoOpenWebMap.stateChanged.connect(self.autoOpenWebMapChanged)

        self.cbAutoAddWFS.setCheckState(
            QtCore.Qt.Checked if PluginSettings.auto_add_wfs_option() else QtCore.Qt.Unchecked
        )
        self.cbAutoAddWFS.stateChanged.connect(self.autoAddWFSChanged)

    def new_connection(self):
        dlg = NGWConnectionEditDialog()
        if dlg.exec_():
            conn_sett = dlg.ngw_connection_settings
            NgwApiSettings.save_ngw_connection(conn_sett)
            NgwApiSettings.set_selected_ngw_connection_name(conn_sett.connection_name)
            self.populate_connection_list()
        del dlg

    def edit_connection(self):
        conn_name = self.cmbConnections.currentText()
        conn_sett = None

        if conn_name is not None:
            conn_sett = NgwApiSettings.get_ngw_connection(conn_name)

        dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett)
        dlg.setWindowTitle(self.tr("Edit connection"))
        if dlg.exec_():
            new_conn_sett = dlg.ngw_connection_settings
            # if conn was renamed - remove old
            if conn_name is not None and conn_name != new_conn_sett.connection_name:
                NgwApiSettings.remove_ngw_connection(conn_name)
            # save new
            NgwApiSettings.save_ngw_connection(new_conn_sett)
            NgwApiSettings.set_selected_ngw_connection_name(new_conn_sett.connection_name)

            self.populate_connection_list()
        del dlg

    def delete_connection(self):
        NgwApiSettings.remove_ngw_connection(self.cmbConnections.currentText())
        self.populate_connection_list()

    def populate_connection_list(self):
        self.cmbConnections.clear()
        self.cmbConnections.addItems(NgwApiSettings.get_ngw_connection_names())

        last_connection = NgwApiSettings.get_selected_ngw_connection_name()

        idx = self.cmbConnections.findText(last_connection)
        if idx == -1 and self.cmbConnections.count() > 0:
            self.cmbConnections.setCurrentIndex(0)
        else:
            self.cmbConnections.setCurrentIndex(idx)

        if self.cmbConnections.count() == 0:
            self.btnEdit.setEnabled(False)
            self.btnDelete.setEnabled(False)
        else:
            self.btnEdit.setEnabled(True)
            self.btnDelete.setEnabled(True)

    def reject(self):
        NgwApiSettings.set_selected_ngw_connection_name(self.cmbConnections.currentText())
        QDialog.reject(self)

    def sanitizeOptionsChanged(self, state):
        optionWidget = self.sender()

        option = (state == QtCore.Qt.Checked)

        if optionWidget is self.chSanitizeRenameFields:
            NgwApiSettings.set_sanitize_rename_fields(option)

        if optionWidget is self.chSanitizeFixGeometry:
            NgwApiSettings.set_sanitize_fix_geometry(option)

    def forceImportChanged(self, state):
        option = (state != QtCore.Qt.Checked)
        NgwApiSettings.set_force_qgis_project_import(option)

    def autoOpenWebMapChanged(self, state):
        option = (state == QtCore.Qt.Checked)
        PluginSettings.set_auto_open_web_map_option(option)

    def autoAddWFSChanged(self, state):
        option = (state == QtCore.Qt.Checked)
        PluginSettings.set_auto_add_wfs_option(option)
