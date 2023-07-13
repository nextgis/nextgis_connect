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

from qgis.PyQt.QtCore import Qt, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsMapLayerType
from qgis.gui import QgisInterface

from .plugin_settings import NgConnectSettings
from .ng_connect_dock import NgConnectDock
from .ng_connect_settings import NgConnectOptionsWidgetFactory
from . import utils

from .ngw_api import qgis
from .ngw_api import utils as ngwapi_utils
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
        self.__init_ng_connect_dock()
        self.__init_ng_connect_menus()
        self.__init_ng_layer_actions()
        self.__init_ng_connect_settings()

    def unload(self):
        self.__unload_ng_connect_settings()
        self.__unload_ng_layer_actions()
        self.__unload_ng_connect_menus()
        self.__unload_ng_connect_dock()

    def __init_debug(self):
        # Enable debug mode.
        debug_mode = NgConnectSettings().is_debug_enabled()
        setDebugEnabled(debug_mode)
        QgsMessageLog.logMessage(
            'Debug messages are {}'.format(
                'enabled' if debug_mode else 'disabled'
            ),
            'NextGIS Connect', level=Qgis.MessageLevel.Info
        )

    def __init_translator(self):
        # initialize locale
        locale = QgsApplication.instance().locale()
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
            'nextgis_connect_{}.qm'.format(locale)
        ))
        add_translator(path.join(
            path.dirname(qgis.__file__), "i18n",
            "qgis_ngw_api_{}.qm".format(locale)
        ))

    def __init_ng_connect_dock(self):
        # Dock tree panel
        self.__ng_resources_tree_dock = NgConnectDock(
            self.title, self.iface
        )
        self.iface.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self.__ng_resources_tree_dock
        )

    def __unload_ng_connect_dock(self):
        self.__ng_resources_tree_dock.setVisible(False)
        self.iface.removeDockWidget(self.__ng_resources_tree_dock)
        self.__ng_resources_tree_dock.deleteLater()

    def __init_ng_connect_menus(self):
        # Show panel action
        self.__ng_connect_toolbar = self.iface.addToolBar(self.title)
        self.__ng_connect_toolbar.setObjectName('NGConnectToolBar')
        self.__ng_connect_toolbar.setToolTip(
            self.tr('NextGIS Connect Toolbar')
        )

        self.__show_ngw_resources_tree_action = QAction(
            QIcon(self.plugin_dir + '/icon.png'),
            self.tr('Show/Hide NextGIS Connect panel'),
            self.iface.mainWindow()
        )
        self.__show_ngw_resources_tree_action.setObjectName(
            'NGConnectShowDock'
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

        # Add action to Plugins
        self.iface.addPluginToMenu(
            self.title, self.__show_ngw_resources_tree_action
        )

        # Add adction to Help > Plugins
        self.__show_help_action = QAction(
            QIcon(self.plugin_dir + '/icon.png'),
            self.title,
            self.iface.mainWindow()
        )
        self.__show_help_action.triggered.connect(utils.open_plugin_help)
        self.iface.pluginHelpMenu().addAction(self.__show_help_action)

    def __unload_ng_connect_menus(self):
        self.iface.removePluginMenu(
            self.title, self.__show_ngw_resources_tree_action
        )

        self.__ng_connect_toolbar.hide()
        self.__ng_connect_toolbar.deleteLater()
        self.__show_ngw_resources_tree_action.deleteLater()

        self.iface.pluginHelpMenu().removeAction(self.__show_help_action)
        self.__show_help_action.deleteLater()

    def __init_ng_layer_actions(self):
        # Tools for NGW communicate
        layer_actions = [
            self.__ng_resources_tree_dock.actionUploadSelectedResources,
            self.__ng_resources_tree_dock.actionUpdateStyle,
            self.__ng_resources_tree_dock.actionAddStyle
        ]
        if Qgis.versionInt() < 33000:
            layer_types = (
                QgsMapLayerType.VectorLayer,  # type: ignore
                QgsMapLayerType.RasterLayer  # type: ignore
            )
        else:
            layer_types = (
                Qgis.LayerType.Vector,  # type: ignore
                Qgis.LayerType.Raster  # type: ignore
            )
        for action in layer_actions:
            for layer_type in layer_types:
                self.iface.addCustomActionForLayerType(
                    action, self.title, layer_type, True
                )

    def __unload_ng_layer_actions(self):
        layer_actions = [
            self.__ng_resources_tree_dock.actionUploadSelectedResources,
            self.__ng_resources_tree_dock.actionUpdateStyle,
            self.__ng_resources_tree_dock.actionAddStyle
        ]
        for action in layer_actions:
            # For vector and raster types
            self.iface.removeCustomActionForLayerType(action)
            self.iface.removeCustomActionForLayerType(action)

    def __init_ng_connect_settings(self):
        self.__options_factory = NgConnectOptionsWidgetFactory()
        self.iface.registerOptionsWidgetFactory(self.__options_factory)

    def __unload_ng_connect_settings(self):
        if self.__options_factory is None:
            return

        self.iface.unregisterOptionsWidgetFactory(self.__options_factory)
        self.__options_factory.deleteLater()
        self.__options_factory = None

    @staticmethod
    def info():
        print("Plugin NextGIS Connect.")

        from . import ngw_api
        print(f"NGW API v. {ngw_api.__version__}")

        print("NGW API log {}".format("ON" if ngwapi_utils.debug else "OFF"))

    @staticmethod
    def enableDebug(flag):
        ngwapi_utils.debug = flag

        print("NGW API log {}".format("ON" if ngwapi_utils.debug else "OFF"))
