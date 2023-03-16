"""
/***************************************************************************
 NGConnectPlugin
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
from os import path

from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import Qgis, QgsMapLayer, QgsMessageLog

from .plugin_settings import PluginSettings
from .tree_panel import TreePanel

from .ngw_api import qgis
from .ngw_api.utils import setDebugEnabled


class NGConnectPlugin:
    """QGIS Plugin Implementation.

        Utils:

from qgis.utils import plugins
plugins['nextgis_connect'].info()
plugins['nextgis_connect'].enableDebug(True)
plugins['nextgis_connect'].enableDebug(False)
    """

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = path.dirname(__file__)

        # Enable debug mode.
        debug_mode = PluginSettings.debug_mode()
        setDebugEnabled(debug_mode)
        QgsMessageLog.logMessage(
            'Debug messages are %s' % ('enabled' if debug_mode else 'disabled'),
            PluginSettings._product, level=Qgis.Info)

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        self._translators = list()

        def add_translator(locale_path):
            if not path.exists(locale_path):
                return
            translator = QTranslator()
            translator.load(locale_path)
            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(translator)
            self._translators.append(translator)  # Should be kept in memory

        add_translator(path.join(
            self.plugin_dir, 'i18n',
            'nextgis_connect_{}.qm'.format(locale)))
        add_translator(path.join(
            path.dirname(qgis.__file__), "i18n",
            "qgis_ngw_api_{}.qm".format(locale)
        ))

        self.title = self.tr('NextGIS Connect')

    def tr(self, message):
        return QCoreApplication.translate('NGConnectPlugin', message)

    def initGui(self):
        main_window = self.iface.mainWindow()
        dock_visibility = PluginSettings.dock_visibility()

        # Dock tree panel
        self.dockWidget = TreePanel(self.iface, main_window)
        self.dockWidget.setFloating(PluginSettings.dock_floating())
        self.dockWidget.resize(PluginSettings.dock_size())
        self.dockWidget.move(PluginSettings.dock_pos())
        self.dockWidget.setVisible(dock_visibility)
        self.iface.addDockWidget(PluginSettings.dock_area(), self.dockWidget)

        # Show panel action
        self.toolbar = self.iface.addToolBar(self.title)
        self.action_show = QAction(
            QIcon(self.plugin_dir + '/icon.png'),
            self.tr('Show/Hide NextGIS Connect panel'),
            main_window)
        self.action_show.setEnabled(True)
        self.action_show.setCheckable(True)
        self.action_show.setChecked(dock_visibility)
        self.action_show.toggled.connect(self.dockWidget.setVisible)
        self.toolbar.addAction(self.action_show)
        self.iface.addPluginToMenu(self.title, self.action_show)

        # Tools for NGW communicate
        ic = self.dockWidget.inner_control
        for action in (ic.actionImportQGISResource, ic.actionUpdateStyle, ic.actionAddStyle):
            for layer_type in (QgsMapLayer.VectorLayer, QgsMapLayer.RasterLayer):
                self.iface.addCustomActionForLayerType(action, self.title, layer_type, True)

    def unload(self):
        ic = self.dockWidget.inner_control
        for action in (ic.actionImportQGISResource, ic.actionUpdateStyle, ic.actionAddStyle):
            self.iface.removeCustomActionForLayerType(action)

        self.toolbar.deleteLater()
        self.iface.removePluginMenu(self.title, self.action_show)

        main_window = self.iface.mainWindow()
        PluginSettings.set_dock_floating(self.dockWidget.isFloating())
        PluginSettings.set_dock_size(self.dockWidget.size())
        PluginSettings.set_dock_pos(self.dockWidget.pos())
        PluginSettings.set_dock_visibility(self.dockWidget.isVisible())
        PluginSettings.set_dock_area(main_window.dockWidgetArea(self.dockWidget))

        self.iface.removeDockWidget(self.dockWidget)
        self.dockWidget.close()

    @staticmethod
    def info():
        print("Plugin NextGIS Connect.")

        from . import ngw_api
        print(("NGW API v. %s" % (ngw_api.__version__) ))

        print(("NGW API log %s" % ("ON" if ngw_api.utils.debug else "OFF") ))

    @staticmethod
    def enableDebug(flag):
        from . import ngw_api
        ngw_api.utils.debug = flag

        print(("NGW API log %s" % ("ON" if ngw_api.utils.debug else "OFF") ))
