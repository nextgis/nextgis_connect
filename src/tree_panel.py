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

from ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings

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

        NgwPluginSettings.get_ngw_connection_names()