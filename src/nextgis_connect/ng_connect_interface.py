import configparser
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Union

from qgis import utils
from qgis.PyQt.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from qgis.core import QgsTaskManager
    from qgis.PyQt.QtCore import QAbstractItemModel, QItemSelectionModel
    from qgis.PyQt.QtWidgets import QToolBar


class _NgConnectInterfaceMetaClass(ABCMeta, type(QObject)): ...


class NgConnectInterface(QObject, metaclass=_NgConnectInterfaceMetaClass):
    PACKAGE_NAME = "nextgis_connect"
    PLUGIN_NAME = "NextGIS Connect"
    TRANSLATION_CONTEXT = "NgConnectPlugin"

    settings_changed = pyqtSignal()

    @classmethod
    def instance(cls) -> "NgConnectInterface":
        plugin = utils.plugins.get(cls.PACKAGE_NAME)
        assert plugin is not None, "Using a plugin before it was created"
        return plugin

    @property
    def metadata(self) -> configparser.ConfigParser:
        metadata = utils.plugins_metadata_parser.get(self.PACKAGE_NAME)
        assert metadata is not None, "Using a plugin before it was created"
        return metadata

    @property
    def version(self) -> str:
        return self.metadata.get("general", "version")

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

    @abstractmethod
    def initGui(self) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def synchronize_layers(self) -> None: ...

    @abstractmethod
    def enable_synchronization(self) -> None: ...

    @abstractmethod
    def disable_synchronization(self) -> None: ...

    @abstractmethod
    def show_error(self, error: Exception) -> str: ...

    @abstractmethod
    def close_error(self, error: Union[Exception, str]) -> None: ...
