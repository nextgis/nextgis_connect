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

from pathlib import Path
from typing import Optional

from qgis.core import (
    QgsApplication,
    QgsRuntimeProfiler,
    QgsTaskManager,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
    QItemSelectionModel,
    Qt,
    QTranslator,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar

from nextgis_connect import utils
from nextgis_connect.compat import LayerType
from nextgis_connect.detached_editing import DetachedEditing
from nextgis_connect.logging import logger, unload_logger
from nextgis_connect.ng_connect_dock import NgConnectDock
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api import qgis as qgis_ngw_api
from nextgis_connect.settings.ng_connect_settings_page import (
    NgConnectOptionsWidgetFactory,
)
from nextgis_connect.tasks.ng_connect_task_manager import NgConnectTaskManager
from nextgis_connect.tasks.purge_ng_connect_cache_task import (
    PurgeNgConnectCacheTask,
)


class NgConnectPlugin(NgConnectInterface):
    """NextGIS Connect Plugin"""

    iface: QgisInterface
    plugin_dir: Path

    def __init__(self, iface: QgisInterface) -> None:
        self.iface = iface
        self.plugin_dir = Path(__file__).parent

        self.__init_translator()

        logger.debug("<b>Plugin object created</b>")

    def initGui(self) -> None:  # noqa: N802
        with QgsRuntimeProfiler.profile("Interface initialization"):  # type: ignore
            logger.debug("<b>Start interface initialization</b>")

            with QgsRuntimeProfiler.profile("Task manager initialization"):  # type: ignore
                self.__init_task_manager()
            with QgsRuntimeProfiler.profile("Detached layers initialization"):  # type: ignore
                self.__init_detached_editing()
            with QgsRuntimeProfiler.profile("Dock widget initialization"):  # type: ignore
                self.__init_ng_connect_dock()
            with QgsRuntimeProfiler.profile("Menus initialization"):  # type: ignore
                self.__init_ng_connect_menus()
            with QgsRuntimeProfiler.profile("Actions initialization"):  # type: ignore
                self.__init_ng_layer_actions()
            with QgsRuntimeProfiler.profile("Settings initialization"):  # type: ignore
                self.__init_ng_connect_settings_page()
            with QgsRuntimeProfiler.profile("Cache initialization"):  # type: ignore
                self.__init_cache_purging()

            logger.debug("<b>End interface initialization</b>")

    def unload(self) -> None:
        logger.debug("<b>Start plugin unload</b>")

        self.__unload_ng_connect_settings_page()
        self.__unload_ng_layer_actions()
        self.__unload_ng_connect_menus()
        self.__unload_ng_connect_dock()
        self.__unload_detached_editing()
        self.__unload_task_manger()

        logger.debug("<b>End plugin unload</b>")

        unload_logger()

    @property
    def toolbar(self) -> QToolBar:
        assert self.__ng_connect_toolbar is not None
        return self.__ng_connect_toolbar

    @property
    def model(self) -> QAbstractItemModel:
        return self.__ng_resources_tree_dock.resource_model

    @property
    def selection_model(self) -> QItemSelectionModel:
        return None  # type: ignore

    @property
    def task_manager(self) -> QgsTaskManager:
        assert self.__task_manager is not None
        return self.__task_manager

    def update_layers(self) -> None:
        assert self.__detached_editing is not None
        self.__detached_editing.update_layers()

    def tr(
        self,
        source_text: str,
        disambiguation: Optional[str] = None,
        n: int = -1,
    ) -> str:
        return QgsApplication.translate(
            self.TRANSLATE_CONTEXT, source_text, disambiguation, n
        )

    def __init_translator(self) -> None:
        # initialize locale
        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self._translators = list()

        def add_translator(locale_path: Path) -> None:
            if not locale_path.exists():
                return
            translator = QTranslator()
            translator.load(str(locale_path))
            QCoreApplication.installTranslator(translator)
            self._translators.append(translator)  # Should be kept in memory

        add_translator(
            Path(self.plugin_dir) / "i18n" / f"nextgis_connect_{locale}.qm",
        )
        add_translator(
            Path(qgis_ngw_api.__file__).parent
            / "i18n"
            / f"qgis_ngw_api_{locale}.qm",
        )

    def __init_task_manager(self) -> None:
        self.__task_manager = NgConnectTaskManager()
        logger.debug("Task manager initialized")

    def __unload_task_manger(self) -> None:
        assert self.__task_manager is not None
        self.__task_manager = None

        logger.debug("Task manager unloaded")

    def __init_detached_editing(self) -> None:
        self.__detached_editing = DetachedEditing()
        logger.debug("Detached editing initialized")

    def __unload_detached_editing(self) -> None:
        assert self.__detached_editing is not None
        self.__detached_editing.unload()
        self.__detached_editing.deleteLater()
        self.__detached_editing = None

        logger.debug("Detached editing unloaded")

    def __init_ng_connect_dock(self) -> None:
        # Dock tree panel
        self.__ng_resources_tree_dock = NgConnectDock(
            self.PLUGIN_NAME, self.iface
        )
        self.iface.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self.__ng_resources_tree_dock,
        )

        if self.__detached_editing is None:
            message = "Detached layers mechanism isn't created"
            raise RuntimeError(message)

    def __unload_ng_connect_dock(self) -> None:
        self.__ng_resources_tree_dock.setVisible(False)
        self.iface.removeDockWidget(self.__ng_resources_tree_dock)
        self.__ng_resources_tree_dock.deleteLater()

    def __init_ng_connect_menus(self) -> None:
        # Show panel action
        self.__ng_connect_toolbar = self.iface.addToolBar(self.PLUGIN_NAME)
        assert self.__ng_connect_toolbar is not None
        self.__ng_connect_toolbar.setObjectName("NgConnectToolBar")
        self.__ng_connect_toolbar.setToolTip(
            self.tr("NextGIS Connect Toolbar"),
        )

        self.__show_ngw_resources_tree_action = QAction(
            QIcon(str(self.plugin_dir / "icon.png")),
            self.tr("Show/Hide NextGIS Connect panel"),
            self.iface.mainWindow(),
        )
        self.__show_ngw_resources_tree_action.setObjectName(
            "NGConnectShowDock",
        )
        self.__show_ngw_resources_tree_action.setEnabled(True)
        self.__show_ngw_resources_tree_action.setCheckable(True)

        self.__show_ngw_resources_tree_action.triggered.connect(
            self.__ng_resources_tree_dock.setUserVisible,
        )
        self.__ng_resources_tree_dock.visibilityChanged.connect(
            self.__show_ngw_resources_tree_action.setChecked,
        )

        self.__ng_connect_toolbar.addAction(
            self.__show_ngw_resources_tree_action,
        )

        # Add action to Plugins
        self.iface.addPluginToMenu(
            self.PLUGIN_NAME,
            self.__show_ngw_resources_tree_action,
        )

        # Add adction to Help > Plugins
        self.__show_help_action = QAction(
            QIcon(str(self.plugin_dir / "icon.png")),
            self.PLUGIN_NAME,
            self.iface.mainWindow(),
        )
        self.__show_help_action.triggered.connect(utils.open_plugin_help)
        plugin_help_menu = self.iface.pluginHelpMenu()
        assert plugin_help_menu is not None
        plugin_help_menu.addAction(self.__show_help_action)

    def __unload_ng_connect_menus(self) -> None:
        self.iface.removePluginMenu(
            self.PLUGIN_NAME,
            self.__show_ngw_resources_tree_action,
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

        for action in layer_actions:
            for layer_type in (LayerType.Vector, LayerType.Raster):
                self.iface.addCustomActionForLayerType(
                    action,
                    self.PLUGIN_NAME,
                    layer_type,
                    allLayers=True,
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
