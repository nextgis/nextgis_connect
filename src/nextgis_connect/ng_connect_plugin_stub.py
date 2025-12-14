import sys
from pathlib import Path
from typing import TYPE_CHECKING

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

from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.notifier.message_bar_notifier import MessageBarNotifier
from nextgis_connect.notifier.notifier_interface import NotifierInterface

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_editing import (
        DetachedEditing,
    )

    assert isinstance(iface, QgisInterface)


class NgConnectPluginStub(NgConnectInterface):
    """NextGIS Connect Plugin stub for exceptions processing"""

    def __init__(self) -> None:
        super().__init__()
        plugin_dir = Path(__file__).parent

        logger.debug("<b>✓ Plugin stub object created</b>")
        logger.debug(f"<b>ⓘ OS:</b> {QSysInfo().prettyProductName()}")
        logger.debug(f"<b>ⓘ Qt version:</b> {QT_VERSION_STR}")
        logger.debug(f"<b>ⓘ QGIS version:</b> {Qgis.version()}")
        logger.debug(f"<b>ⓘ Python version:</b> {sys.version}")
        logger.debug(f"<b>ⓘ GDAL version:</b> {gdal.__version__}")
        logger.debug(f"<b>ⓘ Plugin version:</b> {self.version}")
        logger.debug(
            f"<b>ⓘ Plugin path:</b> {plugin_dir}"
            + (
                f" -> {plugin_dir.resolve()}"
                if plugin_dir.is_symlink()
                else ""
            )
        )
        self.__notifier = None

    @property
    def notifier(self) -> "NotifierInterface":
        """Return the notifier for displaying messages to the user.

        :returns: Notifier interface instance.
        :rtype: NotifierInterface
        """
        assert self.__notifier is not None, "Notifier is not initialized"
        return self.__notifier

    def _load(self) -> None:
        logger.debug("<b>Start stub initialization</b>")

        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self._add_translator(
            Path(__file__).parent / "i18n" / f"nextgis_connect_{locale}.qm",
        )

        self.__notifier = MessageBarNotifier(self)

        logger.debug("<b>End stub initialization</b>")

    def _unload(self) -> None:
        logger.debug("<b>Start stub unloading</b>")

        self.__notifier.deleteLater()
        self.__notifier = None

        logger.debug("<b>End stub unloading</b>")

    @property
    def toolbar(self) -> QToolBar:
        raise NotImplementedError

    @property
    def resource_model(self) -> QAbstractItemModel:
        raise NotImplementedError

    @property
    def resource_selection_model(self) -> QItemSelectionModel:
        raise NotImplementedError

    @property
    def task_manager(self) -> QgsTaskManager:
        raise NotImplementedError

    def synchronize_layers(self) -> None:
        raise NotImplementedError

    def enable_synchronization(self) -> None:
        raise NotImplementedError

    def disable_synchronization(self) -> None:
        raise NotImplementedError

    @property
    def detached_editing(self) -> "DetachedEditing":
        raise NotImplementedError
