# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from osgeo import gdal
from qgis.core import Qgis, QgsApplication, QgsTaskManager
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import (
    QT_VERSION_STR,
    QAbstractItemModel,
    QItemSelectionModel,
    QSysInfo,
)
from qgis.PyQt.QtWidgets import QToolBar
from qgis.utils import iface

from nextgis_connect.legacy.notifier.message_bar_notifier import (
    MessageBarNotifier,
)
from nextgis_connect.legacy.notifier.notifier_interface import (
    NotifierInterface,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.plugin.plugin_interface import NgConnectInterface

if TYPE_CHECKING:
    from nextgis_connect.legacy.detached_editing.detached_editing import (
        DetachedEditing,
    )

    assert isinstance(iface, QgisInterface)


class NgConnectPluginStub(NgConnectInterface):
    """Handle plugin startup failures.

    Provide a minimal plugin interface that can show startup exceptions
    without loading the full plugin UI.
    """

    def __init__(self, startup_error: Optional[Exception] = None) -> None:
        """Initialize the startup failure handler.

        :param startup_error: Startup exception to display after loading.
        """
        super().__init__()
        plugin_dir = Path(__file__).parents[1]
        self.__startup_error = startup_error

        logger.debug("✓ Plugin stub object created")
        logger.debug(f"ⓘ OS: {QSysInfo().prettyProductName()}")
        logger.debug(f"ⓘ Qt version: {QT_VERSION_STR}")
        logger.debug(f"ⓘ QGIS version: {Qgis.version()}")
        logger.debug(f"ⓘ Python version: {sys.version}")
        logger.debug(f"ⓘ GDAL version: {gdal.__version__}")
        logger.debug(f"ⓘ Plugin version: {self.version}")
        logger.debug(
            f"ⓘ Plugin path: {plugin_dir}"
            + (
                f" -> {plugin_dir.resolve()}"
                if plugin_dir.is_symlink()
                else ""
            )
        )
        self.__notifier = None

    @property
    def notifier(self) -> "NotifierInterface":
        """Return the plugin notifier.

        :return: Notifier interface instance.
        :raises AssertionError: If the notifier is not initialized.
        """
        assert self.__notifier is not None, "Notifier is not initialized"
        return self.__notifier

    def _load(self) -> None:
        logger.debug("Start stub initialization")

        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self._add_translator(
            self.path / "i18n" / f"nextgis_connect_{locale}.qm",
        )

        self.__notifier = MessageBarNotifier(self)

        if self.__startup_error is not None:
            from qgis.PyQt.QtCore import QTimer

            QTimer.singleShot(
                0,
                lambda: self.notifier.display_exception(self.__startup_error),
            )

        logger.debug("End stub initialization")

    def _unload(self) -> None:
        logger.debug("Start stub unloading")

        self.__notifier.deleteLater()
        self.__notifier = None

        logger.debug("End stub unloading")

    @property
    def toolbar(self) -> QToolBar:
        """Return the plugin toolbar.

        :return: Plugin toolbar.
        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    @property
    def resource_model(self) -> QAbstractItemModel:
        """Return the resource tree model.

        :return: Resource tree model.
        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    @property
    def resource_selection_model(self) -> QItemSelectionModel:
        """Return the resource selection model.

        :return: Resource selection model.
        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    @property
    def task_manager(self) -> QgsTaskManager:
        """Return the plugin task manager.

        :return: Plugin task manager.
        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    def synchronize_layers(self) -> None:
        """Schedule detached layer synchronization.

        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    @property
    def detached_editing(self) -> "DetachedEditing":
        """Return the detached editing service.

        :return: Detached editing service.
        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    def enable_synchronization(self) -> None:
        """Enable detached layer synchronization.

        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError

    def disable_synchronization(self) -> None:
        """Disable detached layer synchronization.

        :raises NotImplementedError: Always raised because the full UI is unavailable.
        """
        raise NotImplementedError
