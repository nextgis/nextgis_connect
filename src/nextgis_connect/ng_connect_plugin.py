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

import sys
from pathlib import Path
from typing import cast

from osgeo import gdal
from qgis import utils as qgis_utils
from qgis.core import Qgis, QgsApplication, QgsRuntimeProfiler, QgsTaskManager
from qgis.gui import QgisInterface, QgsMessageBarItem
from qgis.PyQt.QtCore import (
    QT_VERSION_STR,
    QAbstractItemModel,
    QItemSelectionModel,
    QMetaObject,
    QSysInfo,
    Qt,
    QTranslator,
    QUrl,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QPushButton, QToolBar

from nextgis_connect.about_dialog import AboutDialog
from nextgis_connect.compat import LayerType
from nextgis_connect.detached_editing.detached_edititng import DetachedEditing
from nextgis_connect.exceptions import (
    ErrorCode,
    NgConnectError,
    NgConnectWarning,
)
from nextgis_connect.logging import logger, unload_logger
from nextgis_connect.ng_connect_dock import NgConnectDock
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api import qgis as qgis_ngw_api
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from nextgis_connect.settings.ng_connect_settings_page import (
    NgConnectOptionsWidgetFactory,
)
from nextgis_connect.tasks.cache.purge_ng_connect_cache_task import (
    PurgeNgConnectCacheTask,
)
from nextgis_connect.tasks.ng_connect_task_manager import NgConnectTaskManager
from nextgis_connect.utils import nextgis_domain, utm_tags


class NgConnectPlugin(NgConnectInterface):
    """NextGIS Connect Plugin"""

    iface: QgisInterface
    plugin_dir: Path

    def __init__(self) -> None:
        super().__init__()
        self.iface = cast(QgisInterface, qgis_utils.iface)
        self.plugin_dir = Path(__file__).parent

        NgConnectSettings().did_last_launch_fail = False

        logger.debug("<b>Plugin object created</b>")
        logger.debug(f"<b>OS:</b> {QSysInfo().prettyProductName()}")
        logger.debug(f"<b>Qt version:</b> {QT_VERSION_STR}")
        logger.debug(f"<b>QGIS version:</b> {Qgis.version()}")
        logger.debug(f"<b>Python version:</b> {sys.version}")
        logger.debug(f"<b>GDAL version:</b> {gdal.__version__}")
        logger.debug(f"<b>Plugin version:</b> {self.version}")
        logger.debug(
            f"<b>Plugin path:</b> {self.plugin_dir}"
            + (
                f" -> {self.plugin_dir.resolve()}"
                if self.plugin_dir.is_symlink()
                else ""
            )
        )

    def initGui(self) -> None:
        with QgsRuntimeProfiler.profile("Plugin initialization"):  # type: ignore
            logger.debug("<b>Start interface initialization</b>")

            with QgsRuntimeProfiler.profile("Translations initialization"):  # type: ignore
                self.__init_translator()
            with QgsRuntimeProfiler.profile("Connections intialization"):  # type: ignore
                self.__init_connections()
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

            logger.debug("<b>End plugin initialization</b>")

    def unload(self) -> None:
        logger.debug("<b>Start plugin unloading</b>")

        self.__unload_ng_connect_settings_page()
        self.__unload_ng_layer_actions()
        self.__unload_ng_connect_menus()
        self.__unload_ng_connect_dock()
        self.__unload_detached_editing()
        self.__unload_task_manger()
        self.__unload_translations()
        self.__close_notifications()

        logger.debug("<b>End plugin unloading</b>")

        unload_logger()

    @property
    def toolbar(self) -> QToolBar:
        assert self.__ng_connect_toolbar is not None
        return self.__ng_connect_toolbar

    @property
    def resource_model(self) -> QAbstractItemModel:
        return self.__ng_resources_tree_dock.resource_model

    @property
    def resource_selection_model(self) -> QItemSelectionModel:
        return None  # type: ignore

    @property
    def task_manager(self) -> QgsTaskManager:
        assert self.__task_manager is not None
        return self.__task_manager

    def synchronize_layers(self) -> None:
        assert self.__detached_editing is not None
        QMetaObject.invokeMethod(
            self.__detached_editing,
            "synchronizeLayers",
            Qt.ConnectionType.QueuedConnection,
        )

    def enable_synchronization(self) -> None:
        assert self.__detached_editing is not None
        self.__detached_editing.enable_synchronization()
        self.synchronize_layers()

    def disable_synchronization(self) -> None:
        assert self.__detached_editing is not None
        self.__detached_editing.disable_synchronization()

    def show_error(self, error: Exception) -> None:
        if not isinstance(error, NgConnectError):
            old_error = error
            error = NgConnectError()
            error.__cause__ = old_error
            del old_error

        def show_details():
            user_message = error.user_message.rstrip(".")
            QMessageBox.information(
                self.iface.mainWindow(), user_message, error.detail
            )

        def contact_us():
            utm = utm_tags("error")
            QDesktopServices.openUrl(
                QUrl(f"{nextgis_domain()}/contact/?{utm}")
            )

        def upgrade_plan():
            utm = utm_tags("quota")
            QDesktopServices.openUrl(
                QUrl(f"{nextgis_domain()}/pricing-base/?{utm}")
            )

        message = error.user_message
        if not message.endswith("."):
            message += "."
        if message.endswith(".."):
            message = message.rstrip(".") + "."

        message_bar = self.iface.messageBar()
        assert message_bar is not None

        widget = message_bar.createMessage(
            NgConnectInterface.PLUGIN_NAME, message
        )

        if error.try_again is not None:

            def try_again():
                error.try_again()
                message_bar.popWidget(widget)

            button = QPushButton(self.tr("Try again"))
            button.pressed.connect(try_again)
            widget.layout().addWidget(button)

        if error.detail is not None:
            button = QPushButton(self.tr("Details"))
            button.pressed.connect(show_details)
            widget.layout().addWidget(button)
        else:
            button = QPushButton(self.tr("Open logs"))
            button.pressed.connect(self.iface.openMessageLog)
            widget.layout().addWidget(button)

        if error.code == ErrorCode.QuotaExceeded:
            button = QPushButton(self.tr("Upgrade your plan"))
            button.setIcon(
                QIcon(str(self.plugin_dir / "icons" / "upgrade.svg")),
            )
            button.pressed.connect(upgrade_plan)
            widget.layout().addWidget(button)

        elif error.code.is_connection_error:
            button = QPushButton(self.tr("Open settings"))
            button.pressed.connect(
                lambda: self.iface.showOptionsDialog(
                    self.iface.mainWindow(), "NextGIS Connect"
                )
            )
            widget.layout().addWidget(button)

        if error.code.is_plugin_error:
            button = QPushButton(self.tr("Let us know"))
            button.pressed.connect(contact_us)
            widget.layout().addWidget(button)

        level = (
            Qgis.MessageLevel.Critical
            if not isinstance(error, NgConnectWarning)
            else Qgis.MessageLevel.Warning
        )

        item = message_bar.pushWidget(widget, level)
        item.setObjectName("NgConnectMessageBarItem")

        logger.exception(error.log_message, exc_info=error)

    def __init_connections(self) -> None:
        connections_manager = NgwConnectionsManager()
        connections_manager.clear_old_connections_if_converted()

    def __init_translator(self) -> None:
        # initialize locale
        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self.__translators = list()

        def add_translator(locale_path: Path) -> None:
            translator = QTranslator()

            is_loaded = translator.load(str(locale_path))
            if not is_loaded:
                return

            is_installed = QgsApplication.installTranslator(translator)
            if not is_installed:
                return

            # Should be kept in memory
            self.__translators.append(translator)

        add_translator(
            Path(self.plugin_dir) / "i18n" / f"nextgis_connect_{locale}.qm",
        )
        add_translator(
            Path(qgis_ngw_api.__file__).parent
            / "i18n"
            / f"qgis_ngw_api_{locale}.qm",
        )

    def __unload_translations(self) -> None:
        for translator in self.__translators:
            QgsApplication.removeTranslator(translator)

        self.__translators.clear()

    def __close_notifications(self) -> None:
        notifications = self.iface.mainWindow().findChildren(
            QgsMessageBarItem, "NgConnectMessageBarItem"
        )
        for notification in notifications:
            self.iface.messageBar().popWidget(notification)

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
            raise NgConnectError(message)

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
            QIcon(str(self.plugin_dir / "icons/connect_logo.svg")),
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

        self.__action_about = QAction(
            QgsApplication.getThemeIcon("mActionPropertiesWidget.svg"),
            self.tr("About plugin…"),
            self.iface.mainWindow(),
        )

        self.__action_about.triggered.connect(self.__open_about)

        # Add action to Web
        self.iface.addPluginToWebMenu(
            self.PLUGIN_NAME,
            self.__show_ngw_resources_tree_action,
        )
        self.iface.addPluginToWebMenu(
            self.PLUGIN_NAME,
            self.__action_about,
        )

        # Add adction to Help > Plugins
        self.__show_help_action = QAction(
            QIcon(str(self.plugin_dir / "icons/connect_logo.svg")),
            self.PLUGIN_NAME,
            self.iface.mainWindow(),
        )
        self.__show_help_action.triggered.connect(self.__open_about)
        plugin_help_menu = self.iface.pluginHelpMenu()
        assert plugin_help_menu is not None
        plugin_help_menu.addAction(self.__show_help_action)

    def __unload_ng_connect_menus(self) -> None:
        self.iface.removePluginWebMenu(
            self.PLUGIN_NAME,
            self.__show_ngw_resources_tree_action,
        )
        self.iface.removePluginWebMenu(
            self.PLUGIN_NAME,
            self.__action_about,
        )

        assert self.__ng_connect_toolbar is not None
        self.__ng_connect_toolbar.hide()
        self.__ng_connect_toolbar.deleteLater()
        self.__show_ngw_resources_tree_action.deleteLater()
        self.__action_about.deleteLater()

        plugin_help_menu = self.iface.pluginHelpMenu()
        assert plugin_help_menu is not None
        plugin_help_menu.removeAction(self.__show_help_action)
        self.__show_help_action.deleteLater()

    def __init_ng_layer_actions(self) -> None:
        # Tools for NGW communicate
        layer_actions = [
            self.__ng_resources_tree_dock.actionOpenInNGWFromLayer,
            self.__ng_resources_tree_dock.layer_menu_separator,
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
            self.__ng_resources_tree_dock.actionOpenInNGWFromLayer,
            self.__ng_resources_tree_dock.layer_menu_separator,
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

    def __open_about(self) -> None:
        dialog = AboutDialog(str(Path(__file__).parent.name))
        dialog.exec()
