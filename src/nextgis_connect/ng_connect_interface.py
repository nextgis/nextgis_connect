from abc import ABC, abstractproperty

from qgis import utils
from qgis.PyQt.QtCore import QAbstractItemModel
from qgis.PyQt.QtWidgets import QToolBar


class NgConnectInterface(ABC):
    @staticmethod
    def instance() -> "NgConnectInterface":
        return utils.plugins["nextgis_connect"]

    @abstractproperty
    def toolbar(self) -> QToolBar:
        ...

    @abstractproperty
    def model(self) -> QAbstractItemModel:
        ...

    # TODO(ibarsukov): add import adction
    # TODO(ibarsukov): add export adction
    # TODO(ibarsukov): add selection_model
    # TODO(ibarsukov): add task_manager
