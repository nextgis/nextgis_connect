import configparser
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from qgis import utils
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QObject, QTranslator, pyqtSignal

from nextgis_connect.core.base.qobject_metaclass import QObjectMetaClass
from nextgis_connect.core.constants import PACKAGE_NAME
from nextgis_connect.logging import logger, unload_logger

if TYPE_CHECKING:
    from qgis.core import QgsTaskManager
    from qgis.PyQt.QtCore import QAbstractItemModel, QItemSelectionModel
    from qgis.PyQt.QtWidgets import QToolBar

    from nextgis_connect.detached_editing.detached_editing import (
        DetachedEditing,
    )
    from nextgis_connect.notifier.notifier_interface import NotifierInterface


class NgConnectInterface(QObject, metaclass=QObjectMetaClass):
    """
    Interface for the NextGIS Connect plugin.

    This abstract base class provides singleton access to the plugin
    instance, exposes plugin metadata, version, and path, and defines
    abstract properties and methods that must be implemented by concrete
    subclasses.
    """

    settings_changed = pyqtSignal()

    @classmethod
    def instance(cls) -> "NgConnectInterface":
        """
        Get the singleton instance of the NextGIS Connect plugin.

        :returns: The singleton instance of the plugin.
        :rtype: NgConnectInterface
        :raises AssertionError: If the plugin instance is not yet created.
        """
        plugin = utils.plugins.get(PACKAGE_NAME)
        assert plugin is not None, "Using a plugin before it was created"
        return plugin

    @property
    def metadata(self) -> configparser.ConfigParser:
        """
        Get the metadata for the NextGIS Connect plugin.

        :returns: Metadata of the plugin as a ConfigParser object.
        :rtype: configparser.ConfigParser
        :raises AssertionError: If the plugin metadata is not available.
        """
        metadata = utils.plugins_metadata_parser.get(PACKAGE_NAME)
        assert metadata is not None, "Using a plugin before it was created"
        return metadata

    @property
    def version(self) -> str:
        """
        Return the plugin version.

        :returns: Plugin version string.
        :rtype: str
        """
        return self.metadata.get("general", "version")

    @property
    def path(self) -> "Path":
        """
        Return the plugin path.

        :returns: Path to the plugin directory.
        :rtype: Path
        """
        return Path(__file__).parent

    @property
    @abstractmethod
    def toolbar(self) -> "QToolBar": ...

    @property
    @abstractmethod
    def resource_model(self) -> "QAbstractItemModel": ...

    @property
    @abstractmethod
    def resource_selection_model(self) -> "QItemSelectionModel": ...

    @property
    @abstractmethod
    def task_manager(self) -> "QgsTaskManager": ...

    @property
    @abstractmethod
    def detached_editing(self) -> "DetachedEditing": ...

    @abstractmethod
    def synchronize_layers(self) -> None: ...

    @abstractmethod
    def enable_synchronization(self) -> None: ...

    @abstractmethod
    def disable_synchronization(self) -> None: ...

    @property
    @abstractmethod
    def notifier(self) -> "NotifierInterface":
        """Return the notifier for displaying messages to the user.

        :returns: Notifier interface instance.
        :rtype: NotifierInterface
        """
        ...

    def initGui(self) -> None:
        """Initialize the GUI components and load necessary resources."""
        self.__translators = list()

        try:
            self._load()
        except Exception:
            logger.exception("An error occurred while plugin loading")

    def unload(self) -> None:
        """Unload the plugin and perform cleanup operations."""
        try:
            self._unload()
        except Exception:
            logger.exception("An error occurred while plugin unloading")

        self.__unload_translations()
        unload_logger()

    @abstractmethod
    def _load(self) -> None:
        """Load the plugin resources and initialize components.

        This method must be implemented by subclasses.
        """
        ...

    @abstractmethod
    def _unload(self) -> None:
        """Unload the plugin resources and clean up components.

        This method must be implemented by subclasses.
        """
        ...

    def _add_translator(self, translator_path: Path) -> None:
        """Add a translator for the plugin.

        :param translator_path: Path to the translation file.
        :type translator_path: Path
        """
        translator = QTranslator()
        is_loaded = translator.load(str(translator_path))
        if not is_loaded:
            logger.debug(f"Translator {translator_path} wasn't loaded")
            return

        is_installed = QgsApplication.installTranslator(translator)
        if not is_installed:
            logger.error(f"Translator {translator_path} wasn't installed")
            return

        # Should be kept in memory
        self.__translators.append(translator)

    def __unload_translations(self) -> None:
        """Remove all translators added by the plugin."""
        for translator in self.__translators:
            QgsApplication.removeTranslator(translator)
        self.__translators.clear()
