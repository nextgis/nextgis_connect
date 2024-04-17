import configparser
from abc import ABC, abstractmethod

from qgis import utils
from qgis.core import QgsTaskManager
from qgis.PyQt.QtCore import QAbstractItemModel, QItemSelectionModel
from qgis.PyQt.QtWidgets import QToolBar


class NgConnectInterface(ABC):
    PACKAGE_NAME = "nextgis_connect"
    PLUGIN_NAME = "NextGIS Connect"
    TRANSLATE_CONTEXT = "NgConnectPlugin"

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
    def toolbar(self) -> QToolBar: ...

    @property
    @abstractmethod
    def model(self) -> QAbstractItemModel: ...

    @property
    @abstractmethod
    def selection_model(self) -> QItemSelectionModel: ...

    @property
    @abstractmethod
    def task_manager(self) -> QgsTaskManager: ...

    @abstractmethod
    def update_layers(self) -> None: ...

    @abstractmethod
    def show_error(self, error: Exception) -> None: ...

    # TODO(ibarsukov): add import adction
    # TODO(ibarsukov): add export adction
