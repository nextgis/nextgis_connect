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

from qgis.PyQt.QtCore import Qt, QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import Qgis, QgsMessageLog, QgsMapLayerType
from qgis.gui import QgisInterface

from .plugin_settings import PluginSettings
from .tree_panel import TreePanel

from .ngw_api import qgis, utils
from .ngw_api.utils import setDebugEnabled


class NGConnectPlugin:
    """QGIS Plugin Implementation.

        Utils:

from qgis.utils import plugins
plugins['nextgis_connect'].info()
plugins['nextgis_connect'].enableDebug(True)
plugins['nextgis_connect'].enableDebug(False)
    """

    iface: QgisInterface
    title: str
    plugin_dir: str

    def __init__(self, iface):
        self.iface = iface
        self.title = 'NextGIS Connect'
        self.plugin_dir = path.dirname(__file__)

        self.__init_debug()
        self.__init_translator()

    def tr(self, message):
        return QCoreApplication.translate('NGConnectPlugin', message)

    def initGui(self):
        self.__init_ng_resources_tree()
        self.__init_ng_connect_menus()
        self.__init_ng_layer_actions()

    def unload(self):
        self.__unload_ng_layer_actions()
        self.__unload_ng_connect_menus()
        self.__unload_ng_resources_tree()

    def __init_debug(self):
        # Enable debug mode.
        debug_mode = PluginSettings.debug_mode()
        setDebugEnabled(debug_mode)
        QgsMessageLog.logMessage(
            'Debug messages are %s' % ('enabled' if debug_mode else 'disabled'),
            PluginSettings._product, level=Qgis.MessageLevel.Info)

    def __init_translator(self):
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        self._translators = list()

        def add_translator(locale_path):
            if not path.exists(locale_path):
                return
            translator = QTranslator()
            translator.load(locale_path)
            QCoreApplication.installTranslator(translator)
            self._translators.append(translator)  # Should be kept in memory

        add_translator(path.join(
            self.plugin_dir, 'i18n',
            'nextgis_connect_{}.qm'.format(locale)))
        add_translator(path.join(
            path.dirname(qgis.__file__), "i18n",
            "qgis_ngw_api_{}.qm".format(locale)
        ))

    def __init_ng_resources_tree(self):
        # Dock tree panel
        self.__ng_resources_tree_dock = TreePanel(
            self.title, self.iface, self.iface.mainWindow()
        )
        self.iface.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.__ng_resources_tree_dock
        )

    def __unload_ng_resources_tree(self):
        self.__ng_resources_tree_dock.setVisible(False)
        self.iface.removeDockWidget(self.__ng_resources_tree_dock)
        self.__ng_resources_tree_dock.deleteLater()

    def __init_ng_connect_menus(self):
        # Show panel action
        self.__ng_connect_toolbar = self.iface.addToolBar(self.title)
        self.__ng_connect_toolbar.setObjectName('NGConnectToolbar')

        self.__show_ngw_resources_tree_action = QAction(
            QIcon(self.plugin_dir + '/icon.png'),
            self.tr('Show/Hide NextGIS Connect panel'),
            self.iface.mainWindow()
        )
        self.__show_ngw_resources_tree_action.setObjectName(
            'ShowNGWResourcesTreeAction'
        )
        self.__show_ngw_resources_tree_action.setEnabled(True)
        self.__show_ngw_resources_tree_action.setCheckable(True)

        self.__show_ngw_resources_tree_action.triggered.connect(
            self.__ng_resources_tree_dock.setUserVisible
        )
        self.__ng_resources_tree_dock.visibilityChanged.connect(
            self.__show_ngw_resources_tree_action.setChecked
        )

        self.__ng_connect_toolbar.addAction(
            self.__show_ngw_resources_tree_action
        )

        self.iface.addPluginToMenu(
            self.title, self.__show_ngw_resources_tree_action
        )

    def __unload_ng_connect_menus(self):
        self.iface.removePluginMenu(
            self.title, self.__show_ngw_resources_tree_action
        )

        self.__ng_connect_toolbar.deleteLater()
        self.__show_ngw_resources_tree_action.deleteLater()

    def __init_ng_layer_actions(self):
        # Tools for NGW communicate
        ic = self.__ng_resources_tree_dock.inner_control
        layer_actions = [
            ic.actionUploadSelectedResources,
            ic.actionUpdateStyle,
            ic.actionAddStyle
        ]
        if Qgis.versionInt() < 33000:
            layer_types = (
                QgsMapLayerType.Vector, QgsMapLayerType.Raster
            )
        else:
            layer_types = (
                Qgis.LayerType.Vector, Qgis.LayerType.Raster
            )
        for action in layer_actions:
            for layer_type in layer_types:
                self.iface.addCustomActionForLayerType(
                    action, self.title, layer_type, True
                )

    def __unload_ng_layer_actions(self):
        ic = self.__ng_resources_tree_dock.inner_control
        layer_actions = [
            ic.actionUploadSelectedResources,
            ic.actionUpdateStyle,
            ic.actionAddStyle
        ]
        for action in layer_actions:
            self.iface.removeCustomActionForLayerType(action)

    @staticmethod
    def info():
        print("Plugin NextGIS Connect.")

        from . import ngw_api
        print(("NGW API v. %s" % (ngw_api.__version__) ))

        print(("NGW API log %s" % ("ON" if utils.debug else "OFF") ))

    @staticmethod
    def enableDebug(flag):
        utils.debug = flag

        print(("NGW API log %s" % ("ON" if utils.debug else "OFF") ))