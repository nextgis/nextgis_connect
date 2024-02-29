"""
/***************************************************************************
 NgConnectPlugin
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

from qgis import utils as qgis_utils
from qgis.core import Qgis, QgsApplication, QgsMapLayerType
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar

from . import utils
from .detached_editing.detached_edititng import DetachedEditing
from .ng_connect_cache_manager import PurgeNgConnectCacheTask
from .ng_connect_dock import NgConnectDock
from .ng_connect_settings import NgConnectSettings
from .ng_connect_settings_page import NgConnectOptionsWidgetFactory
from .ngw_api import qgis
from .ngw_api.utils import setDebugEnabled


class NgConnectPlugin:
    """NextGIS Connect Plugin"""

    TITLE: str = "NextGIS Connect"

    iface: QgisInterface
    plugin_dir: str

    def __init__(self, iface: QgisInterface) -> None:
        self.iface = iface
        self.plugin_dir = path.dirname(__file__)

        self.__init_debug()
        self.__init_translator()

    def initGui(self) -> None:  # noqa: N802
        self.__init_detached_editing()
        self.__init_ng_connect_dock()
        self.__init_ng_connect_menus()
        self.__init_ng_layer_actions()
        self.__init_ng_connect_settings_page()
        self.__init_cache_purging()

    def unload(self) -> None:
        self.__unload_ng_connect_settings_page()
        self.__unload_ng_layer_actions()
        self.__unload_ng_connect_menus()
        self.__unload_ng_connect_dock()
        self.__unload_detached_editing()

    @property
    def toolbar(self) -> QToolBar:
        assert self.__ng_connect_toolbar is not None
        return self.__ng_connect_toolbar

    @staticmethod
    def tr(message: str) -> str:
        return QCoreApplication.translate("NgConnectPlugin", message)

    @staticmethod
    def instance() -> "NgConnectPlugin":
        return qgis_utils.plugins["nextgis_connect"]

    def __init_debug(self) -> None:
        # Enable debug mode.
        debug_mode = NgConnectSettings().is_debug_enabled
        setDebugEnabled(debug_mode)
        utils.log_to_qgis(
            f'Debug messages are {"enabled" if debug_mode else "disabled"}'
        )

    def __init_translator(self) -> None:
        # initialize locale
        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self._translators = list()

        def add_translator(locale_path: str) -> None:
            if not path.exists(locale_path):
                return
            translator = QTranslator()
            translator.load(locale_path)
            QCoreApplication.installTranslator(translator)
            self._translators.append(translator)  # Should be kept in memory

        add_translator(
            path.join(self.plugin_dir, "i18n", f"nextgis_connect_{locale}.qm")
        )
        add_translator(
            path.join(
                path.dirname(qgis.__file__),
                "i18n",
                f"qgis_ngw_api_{locale}.qm",
            )
        )

    def __init_detached_editing(self) -> None:
        self.__detached_editing = DetachedEditing()

    def __unload_detached_editing(self) -> None:
        assert self.__detached_editing is not None
        self.__detached_editing.unload()
        self.__detached_editing = None

    def __init_ng_connect_dock(self) -> None:
        # Dock tree panel
        self.__ng_resources_tree_dock = NgConnectDock(self.TITLE, self.iface)
        self.iface.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self.__ng_resources_tree_dock,
        )

        if self.__detached_editing is None:
            raise RuntimeError("Detached layers mechanism isn't created")

    def __unload_ng_connect_dock(self) -> None:
        self.__ng_resources_tree_dock.setVisible(False)
        self.iface.removeDockWidget(self.__ng_resources_tree_dock)
        self.__ng_resources_tree_dock.deleteLater()

    def __init_ng_connect_menus(self) -> None:
        # Show panel action
        self.__ng_connect_toolbar = self.iface.addToolBar(self.TITLE)
        assert self.__ng_connect_toolbar is not None
        self.__ng_connect_toolbar.setObjectName("NgConnectToolBar")
        self.__ng_connect_toolbar.setToolTip(
            self.tr("NextGIS Connect Toolbar")
        )

        self.__show_ngw_resources_tree_action = QAction(
            QIcon(self.plugin_dir + "/icon.png"),
            self.tr("Show/Hide NextGIS Connect panel"),
            self.iface.mainWindow(),
        )
        self.__show_ngw_resources_tree_action.setObjectName(
            "NGConnectShowDock"
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
            self.TITLE, self.__show_ngw_resources_tree_action
        )

        # Add adction to Help > Plugins
        self.__show_help_action = QAction(
            QIcon(self.plugin_dir + "/icon.png"),
            self.TITLE,
            self.iface.mainWindow(),
        )
        self.__show_help_action.triggered.connect(utils.open_plugin_help)
        plugin_help_menu = self.iface.pluginHelpMenu()
        assert plugin_help_menu is not None
        plugin_help_menu.addAction(self.__show_help_action)

    def __unload_ng_connect_menus(self) -> None:
        self.iface.removePluginMenu(
            self.TITLE, self.__show_ngw_resources_tree_action
        )

        assert self.__ng_connect_toolbar is not None
        self.__ng_connect_toolbar.hide()
        self.__ng_connect_toolbar.deleteLater()
        self.__show_ngw_resources_tree_action.deleteLater()

        plugin_help_menu = self.iface.pluginHelpMenu()
        assert plugin_help_menu is not None
        plugin_help_menu.removeAction(self.__show_help_action)
        self.__show_help_action.deleteLater()

    def __init_ng_layer_actions(self) -> None:
        # Tools for NGW communicate
        layer_actions = [
            self.__ng_resources_tree_dock.actionUploadSelectedResources,
            self.__ng_resources_tree_dock.actionUpdateStyle,
            self.__ng_resources_tree_dock.actionAddStyle,
        ]
        if Qgis.versionInt() < 33000:
            layer_types = (
                QgsMapLayerType.VectorLayer,  # type: ignore
                QgsMapLayerType.RasterLayer,  # type: ignore
            )
        else:
            layer_types = (
                Qgis.LayerType.Vector,  # type: ignore
                Qgis.LayerType.Raster,  # type: ignore
            )
        for action in layer_actions:
            for layer_type in layer_types:
                self.iface.addCustomActionForLayerType(
                    action, self.TITLE, layer_type, True
                )

    def __unload_ng_layer_actions(self) -> None:
        layer_actions = [
            self.__ng_resources_tree_dock.actionUploadSelectedResources,
            self.__ng_resources_tree_dock.actionUpdateStyle,
            self.__ng_resources_tree_dock.actionAddStyle,
        ]
        for action in layer_actions:
            # For vector and raster types
            self.iface.removeCustomActionForLayerType(action)
            self.iface.removeCustomActionForLayerType(action)

    def __init_ng_connect_settings_page(self) -> None:
        self.__options_factory = NgConnectOptionsWidgetFactory()
        self.iface.registerOptionsWidgetFactory(self.__options_factory)

    def __unload_ng_connect_settings_page(self) -> None:
        if self.__options_factory is None:
            return

        self.iface.unregisterOptionsWidgetFactory(self.__options_factory)
        self.__options_factory.deleteLater()
        self.__options_factory = None

    def __init_cache_purging(self) -> None:
        self.__purge_cache_task = PurgeNgConnectCacheTask()
        task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__purge_cache_task)
