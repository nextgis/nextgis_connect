from pathlib import Path
from typing import Dict, List, Optional, cast

from qgis.core import (
    Qgis,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsPathResolver,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSlot
from qgis.utils import iface  # type: ignore

from nextgis_connect.compat import QGIS_3_34
from nextgis_connect.detached_editing.path_preprocessor import (
    DetachedEditingPathPreprocessor,
)
from nextgis_connect.logging import logger
from nextgis_connect.settings import NgConnectSettings

from . import utils
from .detached_container import DetachedContainer
from .detached_layer_config_widget import DetachedLayerConfigWidgetFactory

iface: QgisInterface


class DetachedEditing(QObject):
    __containers: Dict[Path, DetachedContainer]
    __containers_by_layer_id: Dict[str, DetachedContainer]
    __is_synchronization_enabled: bool

    __timer: QTimer
    __properties_factory: DetachedLayerConfigWidgetFactory

    __path_preprocessor: Optional[DetachedEditingPathPreprocessor]
    __path_preprocessor_id: Optional[str]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        settings = NgConnectSettings()

        self.__containers = {}
        self.__containers_by_layer_id = {}
        self.__is_synchronization_enabled = True

        self.__timer = QTimer(self)
        self.__timer.setInterval(settings.layer_check_period)
        self.__timer.timeout.connect(self.synchronize_layers)
        self.__timer.start()

        self.__properties_factory = DetachedLayerConfigWidgetFactory()
        iface.registerMapLayerConfigWidgetFactory(self.__properties_factory)

        project = QgsProject.instance()
        project.layersAdded.connect(self.__on_layers_added)
        project.layersWillBeRemoved.connect(self.__on_layers_will_be_removed)

        root = project.layerTreeRoot()
        root.addedChildren.connect(self.__on_added_children)
        root.willRemoveChildren.connect(self.__on_will_remove_children)

        self.__path_preprocessor = None
        self.__path_preprocessor_id = None
        if Qgis.versionInt() // 100 * 100 == QGIS_3_34:
            # BUG in QGIS 3.34: https://github.com/qgis/QGIS/issues/58112
            logger.warning(
                "There is a bug in QGIS 3.34. Restoration of layers will be"
                " disabled"
            )
        else:
            self.__path_preprocessor = DetachedEditingPathPreprocessor()
            self.__path_preprocessor_id = QgsPathResolver.setPathPreprocessor(
                self.__path_preprocessor  # type: ignore
            )

        QTimer.singleShot(0, self.__setup_layers)

    def unload(self) -> None:
        self.__timer.stop()

        containers = list(self.__containers.values())

        self.__containers.clear()
        self.__containers_by_layer_id.clear()

        for container in containers:
            container.clear()

        if self.__path_preprocessor_id is not None:
            QgsPathResolver.removePathPreprocessor(self.__path_preprocessor_id)
            del self.__path_preprocessor

        iface.unregisterMapLayerConfigWidgetFactory(self.__properties_factory)
        del self.__properties_factory

    @property
    def is_sychronization_active(self) -> bool:
        return any(
            layer.state == utils.DetachedLayerState.Synchronization
            for layer in self.__containers.values()
        )

    @pyqtSlot(name="synchronizeLayers")
    def synchronize_layers(self) -> None:
        self.__remove_empty_containers()

        if (
            self.is_sychronization_active
            or not self.__is_synchronization_enabled
        ):
            return

        stubs = list(
            filter(
                lambda container: container.is_not_initialized,
                self.__containers.values(),
            )
        )
        containers = (
            stubs if len(stubs) > 0 else list(self.__containers.values())
        )
        for container in containers:
            is_started = container.synchronize()
            if is_started:
                return

    @pyqtSlot(name="enableSynchronization")
    def enable_synchronization(self) -> None:
        self.__is_synchronization_enabled = True

    @pyqtSlot(name="disableSynchronization")
    def disable_synchronization(self) -> None:
        self.__is_synchronization_enabled = False

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
        QTimer.singleShot(0, self.synchronize_layers)

    def __setup_layer(self, layer: QgsMapLayer) -> bool:
        if (
            layer.id() in self.__containers_by_layer_id
            or not utils.is_ngw_container(layer)
        ):
            return False

        container_path = utils.container_path(layer)
        container = self.__containers.get(container_path)
        if container is None:
            try:
                container = DetachedContainer(container_path, self)
            except Exception:
                logger.exception("Container is corrupted")
                return False

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

        self.synchronize_layers()

    @pyqtSlot("QStringList")
    def __on_layers_will_be_removed(self, layer_ids: List[str]) -> None:
        for layer_id in layer_ids:
            if layer_id not in self.__containers_by_layer_id:
                continue

            container = self.__containers_by_layer_id.pop(layer_id)
            container.delete_layer(layer_id)

            if (
                container.is_empty
                and container.state != utils.DetachedLayerState.Synchronization
            ):
                self.__containers.pop(container.path)
                container.deleteLater()

    @pyqtSlot(QgsLayerTreeNode, int, int)
    def __on_added_children(
        self, parent_node: QgsLayerTreeNode, index_from: int, index_to: int
    ) -> None:
        children = parent_node.children()
        for index in range(index_from, index_to + 1):
            node = children[index]
            if not isinstance(node, QgsLayerTreeLayer):
                continue
            layer = node.layer()
            if layer is not None:
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
            if not isinstance(node, QgsLayerTreeLayer):
                continue

            layer = node.layer()
            if (
                layer is None
                or layer.id() not in self.__containers_by_layer_id
            ):
                continue

            container = self.__containers_by_layer_id[layer.id()]
            container.remove_indicator(node)

    def __remove_empty_containers(self) -> None:
        paths_for_remove = []
        for path, container in self.__containers.items():
            if (
                container.is_empty
                and container.state != utils.DetachedLayerState.Synchronization
            ):
                paths_for_remove.append(path)

        for path in paths_for_remove:
            container = self.__containers.pop(path, None)
            if container is not None:
                container.deleteLater()
