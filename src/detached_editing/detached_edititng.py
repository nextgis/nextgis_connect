from typing import Dict, List, Optional, cast

from qgis.PyQt.QtCore import QObject

from qgis.core import (
    QgsProject, QgsMapLayer, QgsVectorLayer, QgsLayerTree, QgsLayerTreeNode,
    QgsLayerTreeLayer
)
from qgis.gui import QgisInterface, QgsApplicationExitBlockerInterface
from qgis.utils import iface

from . import utils

from .detached_layer import DetachedLayer
from .detached_layer_config_widget import DetachedLayerConfigWidgetFactory

iface: QgisInterface


class ExitBlocker(QgsApplicationExitBlockerInterface):
    def __init__(self, detached_editing: "DetachedEditing") -> None:
        super().__init__()
        self.__detached_editing = detached_editing

    def allowExit(self) -> bool:
        # TODO: ask about sync if not started
        # TODO: ask about aborting sync if started
        return not self.__detached_editing.is_sychronization_active


class DetachedEditing(QObject):
    __layers: Dict[str, DetachedLayer]
    __exit_blocker: ExitBlocker

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.__layers = {}

        self.__exit_blocker = ExitBlocker(self)
        iface.registerApplicationExitBlocker(self.__exit_blocker)

        self.__properties_factory = DetachedLayerConfigWidgetFactory()
        iface.registerMapLayerConfigWidgetFactory(self.__properties_factory)

        iface.currentLayerChanged.connect(self.__update_actions)

        project = QgsProject.instance()
        assert project is not None

        project.layersAdded.connect(self.__on_layers_added)
        project.layersWillBeRemoved.connect(self.__on_layers_will_be_removed)

        root = project.layerTreeRoot()
        assert root is not None

        root.addedChildren.connect(self.__on_added_children)
        root.willRemoveChildren.connect(self.__on_will_remove_children)

        self.__setup_layers()

    def unload(self) -> None:
        for layer in self.__layers.values():
            layer.remove_indicator()

        iface.unregisterMapLayerConfigWidgetFactory(self.__properties_factory)
        del self.__properties_factory

        iface.unregisterApplicationExitBlocker(self.__exit_blocker)
        del self.__exit_blocker

    @property
    def is_sychronization_active(self) -> bool:
        return any(
            layer.state == utils.DetachedLayerState.Synchronization
            for layer in self.__layers.values()
        )

    def __setup_layers(self) -> None:
        project = QgsProject.instance()
        assert project is not None
        root = project.layerTreeRoot()
        assert root is not None

        for layer in project.mapLayers().values():
            is_added = self.__setup_layer(layer)
            if not is_added:
                continue

            node = root.findLayer(layer)
            if node is None:
                continue

            self.__layers[layer.id()].add_indicator(node)

    def __setup_layer(self, layer: QgsMapLayer) -> bool:
        if layer.id() in self.__layers or not utils.is_ngw_container(layer):
            return False

        self.__layers[layer.id()] = DetachedLayer(cast(QgsVectorLayer, layer))
        return True

    def __on_layers_added(self, layers: List[QgsMapLayer]) -> None:
        for layer in layers:
            self.__setup_layer(layer)

        self.__update_actions()

    def __on_layers_will_be_removed(self, layer_ids: List[str]) -> None:
        for layer_id in layer_ids:
            if layer_id not in self.__layers:
                continue
            del self.__layers[layer_id]

        self.__update_actions()

    def __on_added_children(
        self, parent_node: QgsLayerTreeNode, index_from: int, index_to: int
    ) -> None:
        children = parent_node.children()
        for index in range(index_from, index_to + 1):
            node = children[index]
            if not QgsLayerTree.isLayer(node):
                continue
            node = cast(QgsLayerTreeLayer, node)
            if (layer := node.layer()) is not None:
                if layer.id() not in self.__layers:
                    continue
                self.__layers[layer.id()].add_indicator(node)
            else:
                node.layerLoaded.connect(self.__on_layer_loaded)

    def __on_layer_loaded(self) -> None:
        node = self.sender()
        if not isinstance(node, QgsLayerTreeLayer):
            return

        layer = node.layer()
        if not isinstance(layer, QgsVectorLayer):
            return

        if layer.id() not in self.__layers:
            return

        self.__layers[layer.id()].add_indicator(node)

    def __on_will_remove_children(
        self, parent_node: QgsLayerTreeNode, index_from: int, index_to: int
    ) -> None:
        children = parent_node.children()
        for index in range(index_from, index_to + 1):
            node = children[index]
            if not QgsLayerTree.isLayer(node):
                continue
            node = cast(QgsLayerTreeLayer, node)
            if (layer := node.layer()) is None:
                continue
            if layer.id() not in self.__layers:
                continue

            self.__layers[layer.id()].remove_indicator(node)

    def __update_actions(self) -> None:
        # TODO: implement
        pass
