from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, cast

from qgis.core import (
    QgsLayerTree,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsApplicationExitBlockerInterface
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSlot
from qgis.utils import iface  # type: ignore

from nextgis_connect.logging import logger

from . import utils
from .detached_container import DetachedContainer
from .detached_layer_config_widget import DetachedLayerConfigWidgetFactory

iface: QgisInterface


class ExitBlocker(QgsApplicationExitBlockerInterface):
    def __init__(self, detached_editing: "DetachedEditing") -> None:
        super().__init__()
        self.__detached_editing = detached_editing

    def __del__(self) -> None:
        logger.debug("Delete exit blocker")

    def allowExit(self) -> bool:  # noqa: N802
        self.__detached_editing.stop_next_sync()
        return not self.__detached_editing.is_sychronization_active


class DetachedEditing(QObject):
    __containers: Dict[Path, DetachedContainer]
    __containers_by_layer_id: Dict[str, DetachedContainer]
    __sync_is_stopped: bool

    __timer: QTimer
    __properties_factory: DetachedLayerConfigWidgetFactory
    __exit_blocker: ExitBlocker

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.__containers = {}
        self.__containers_by_layer_id = {}
        self.__sync_is_stopped = False

        layers_check_period = timedelta(seconds=15) / timedelta(milliseconds=1)
        self.__timer = QTimer(self)
        self.__timer.setInterval(int(layers_check_period))
        self.__timer.timeout.connect(self.update_layers)
        self.__timer.start()

        self.__exit_blocker = ExitBlocker(self)
        iface.registerApplicationExitBlocker(self.__exit_blocker)

        self.__properties_factory = DetachedLayerConfigWidgetFactory()
        iface.registerMapLayerConfigWidgetFactory(self.__properties_factory)

        project = QgsProject.instance()
        assert project is not None

        project.layersAdded.connect(self.__on_layers_added)
        project.layersWillBeRemoved.connect(self.__on_layers_will_be_removed)

        root = project.layerTreeRoot()
        assert root is not None

        root.addedChildren.connect(self.__on_added_children)
        root.willRemoveChildren.connect(self.__on_will_remove_children)

        iface.currentLayerChanged.connect(self.__update_actions)

        QTimer.singleShot(0, self.__setup_layers)

    def unload(self) -> None:
        containers = list(self.__containers.values())

        self.__containers.clear()
        self.__containers_by_layer_id.clear()

        for container in containers:
            container.clear()

        iface.unregisterMapLayerConfigWidgetFactory(self.__properties_factory)
        del self.__properties_factory

        iface.unregisterApplicationExitBlocker(self.__exit_blocker)
        del self.__exit_blocker

    @property
    def is_sychronization_active(self) -> bool:
        return any(
            layer.state == utils.DetachedLayerState.Synchronization
            for layer in self.__containers.values()
        )

    def stop_next_sync(self) -> None:
        self.__sync_is_stopped = True

    @pyqtSlot(name="updateLayers")
    def update_layers(self) -> None:
        if self.is_sychronization_active or self.__sync_is_stopped:
            return

        stubs = list(
            filter(
                lambda container: container.is_stub, self.__containers.values()
            )
        )

        containers = stubs if len(stubs) > 0 else self.__containers.values()
        for container in containers:
            is_started = container.synchronize()
            if is_started:
                return

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

            self.__containers_by_layer_id[layer.id()].add_indicator(node)

        # Run after returning to event loop
        QTimer.singleShot(0, self.update_layers)

    def __setup_layer(self, layer: QgsMapLayer) -> bool:
        if (
            layer.id() in self.__containers_by_layer_id
            or not utils.is_ngw_container(layer)
        ):
            return False

        container_path = utils.container_path(layer)
        container = self.__containers.get(container_path)
        if container is None:
            container = DetachedContainer(container_path, self)
            self.__containers[container_path] = container

        self.__containers_by_layer_id[layer.id()] = container

        # Check if layer wasn't added to project earlier
        need_add_names = layer.customProperty("ngw_is_detached_layer") is None

        vector_layer = cast(QgsVectorLayer, layer)
        container.add_layer(vector_layer)

        if need_add_names:
            vector_layer.setName(container.metadata.layer_name)
            for field in container.metadata.fields:
                vector_layer.setFieldAlias(field.attribute, field.display_name)

        return True

    @pyqtSlot("QList<QgsMapLayer *>")
    def __on_layers_added(self, layers: List[QgsMapLayer]) -> None:
        for layer in layers:
            self.__setup_layer(layer)

        self.__update_actions()
        self.update_layers()

    @pyqtSlot("QStringList")
    def __on_layers_will_be_removed(self, layer_ids: List[str]) -> None:
        for layer_id in layer_ids:
            if layer_id not in self.__containers_by_layer_id:
                continue

            container = self.__containers_by_layer_id.pop(layer_id)
            container.delete_layer(layer_id)

            if container.is_empty:
                self.__containers.pop(container.path)
                container.deleteLater()

        self.__update_actions()

    @pyqtSlot(QgsLayerTreeNode, int, int)
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
                if layer.id() not in self.__containers_by_layer_id:
                    continue
                self.__containers_by_layer_id[layer.id()].add_indicator(node)
            else:
                node.layerLoaded.connect(self.__on_layer_loaded)

    @pyqtSlot()
    def __on_layer_loaded(self) -> None:
        node = self.sender()
        if not isinstance(node, QgsLayerTreeLayer):
            return

        layer = node.layer()
        if not isinstance(layer, QgsVectorLayer):
            return

        if layer.id() not in self.__containers_by_layer_id:
            return

        self.__containers_by_layer_id[layer.id()].add_indicator(node)

    @pyqtSlot(QgsLayerTreeNode, int, int)
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
            if layer.id() not in self.__containers_by_layer_id:
                continue

            self.__containers_by_layer_id[layer.id()].remove_indicator(node)

    def __update_actions(self) -> None:
        pass
