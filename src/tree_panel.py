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
from PyQt4.QtGui import QDockWidget, QMainWindow
from PyQt4.QtCore import Qt
from qgis.core import QgsMessageLog
from qgis.gui import QgsMessageBar

from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from ngw_api.qt.qt_ngw_resource_item import QNGWResourceItem
from ngw_api.qt.qt_ngw_resource_model import QNGWResourcesModel
from ngw_api.core.ngw_resource_factory import NGWResourceFactory

__author__ = 'NextGIS'
__date__ = 'January 2015'
__copyright__ = '(C) 2015, NextGIS'

# This will get replaced with a git SHA1 when you do a git archive
__revision__ = '$Format:%H$'


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'tree_panel_base.ui'))


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

        self.cmbConnection.currentIndexChanged[str].connect(self.reinit_tree)
        self.update_conn_list()

    def update_conn_list(self):
        self.cmbConnection.clear()
        self.cmbConnection.addItems(NgwPluginSettings.get_ngw_connection_names())

        last_connection = NgwPluginSettings.get_selected_ngw_connection_name()
        idx = self.cmbConnection.findText(last_connection)
        if idx == -1 and self.cmbConnection.count() > 0:
            self.cmbConnection.setCurrentIndex(0)
        else:
            self.cmbConnection.setCurrentIndex(idx)

    def reinit_tree(self, name_of_conn):
        #clear tree
        self.trvResources.setModel(None)

        if not name_of_conn:
            return
        conn_sett = NgwPluginSettings.get_ngw_connection(name_of_conn)

        #setup ngw api
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

        self._root_item = QNGWResourceItem(root_rsc, None)
        self._resource_model = QNGWResourcesModel(self._root_item)
        self.trvResources.setModel(self._resource_model)

        NgwPluginSettings.set_selected_ngw_connection_name(name_of_conn)

