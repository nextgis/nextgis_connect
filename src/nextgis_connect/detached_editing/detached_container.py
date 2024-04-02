import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from qgis.core import (
    QgsApplication,
    QgsLayerTreeLayer,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.utils import iface, spatialite_connect

from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api.core import NGWVectorLayer
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.settings import NgConnectCacheManager
from nextgis_connect.tasks.detached_editing import (
    DownloadGpkgTask,
    FillLayerWithVersioning,
    UploadChangesTask,
)

from . import utils
from .detached_layer import DetachedLayer
from .detached_layer_factory import DetachedLayerFactory
from .detached_layer_indicator import DetachedLayerIndicator
from .utils import (
    DetachedContainerChanges,
    DetachedContainerMetaData,
    DetachedLayerErrorType,
    DetachedLayerState,
    VersioningSynchronizationState,
)

assert isinstance(iface, QgisInterface)


class DetachedContainer(QObject):
    __path: Path
    __detached_layers: Dict[str, DetachedLayer]

    __metadata: DetachedContainerMetaData
    __state: DetachedLayerState
    __versioning_state: VersioningSynchronizationState
    __changes: DetachedContainerChanges
    __error_type: DetachedLayerErrorType

    __indicator: Optional[DetachedLayerIndicator]
    __sync_task: Optional[QgsTask]

    state_changed = pyqtSignal(DetachedLayerState, name="stateChanged")

    def __init__(
        self, container_path: Path, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)

        self.__path = container_path
        self.__detached_layers = {}

        self.__indicator = None
        self.__sync_task = None

        # self.destroyed.connect(self.__clear_indicators)

        self.__update_state(is_full_update=True)

        logger.debug(
            f'Detached container "{self.__path.name}" added to project'
        )

    def __del__(self) -> None:
        logger.debug(
            f'Detached container "{self.__path.name}" deleted from project'
        )

    @property
    def path(self) -> Path:
        return self.__path

    @property
    def metadata(self):
        return self.__metadata

    @property
    def state(self) -> DetachedLayerState:
        return self.__state

    @property
    def is_stub(self) -> bool:
        return self.__state == DetachedLayerState.NotInitialized

    @property
    def error_type(self) -> DetachedLayerErrorType:
        return self.__error_type

    @property
    def check_date(self) -> Optional[datetime]:
        for detached_layer in self.__detached_layers.values():
            check_date = detached_layer.layer.customProperty("ngw_check_date")
            if check_date is not None:
                return check_date
        return None

    @property
    def sync_date(self) -> Optional[datetime]:
        return self.__metadata.sync_date

    @property
    def is_empty(self) -> bool:
        return len(self.__detached_layers) == 0

    @property
    def changes(self) -> DetachedContainerChanges:
        return self.__changes

    def add_layer(self, layer: QgsVectorLayer) -> None:
        detached_layer = DetachedLayer(self, layer)
        detached_layer.layer_changed.connect(
            lambda: self.__update_state(is_full_update=True)
        )

        plugin = NgConnectInterface.instance()
        detached_layer.editing_finished.connect(plugin.update_layers)

        layer.setCustomProperty("ngw_check_date", self.check_date)

        self.__detached_layers[layer.id()] = detached_layer

        logger.debug(
            f'Layer "{layer.id()}" attached to container "{self.__path.name}"'
        )

    def delete_layer(self, layer_id: str) -> None:
        layer = self.__detached_layers.pop(layer_id)
        layer.deleteLater()
        del layer

        if self.is_empty and self.__indicator is not None:
            self.__indicator.deleteLater()
            self.__indicator = None

        logger.debug(
            f'Layer "{layer_id}" detached from container "{self.__path.name}"'
        )

    def clear(self) -> None:
        self.__clear_indicators()

        layer_ids = list(self.__detached_layers.keys())
        for layer_id in layer_ids:
            self.delete_layer(layer_id)

    def add_indicator(self, node: QgsLayerTreeLayer) -> None:
        assert isinstance(iface, QgisInterface)
        view = iface.layerTreeView()
        assert view is not None

        if self.__indicator is None:
            self.__indicator = DetachedLayerIndicator(self)

        if self.__indicator in view.indicators(node):
            return

        view.addIndicator(node, self.__indicator)

    def remove_indicator(self, node: QgsLayerTreeLayer):
        view = iface.layerTreeView()
        assert view is not None

        if self.__indicator not in view.indicators(node):
            return

        view.removeIndicator(node, self.__indicator)

    def make_connection(self) -> sqlite3.Connection:
        return spatialite_connect(str(self.__path))

    def synchronize(self, *, is_manual: bool = False) -> bool:
        if self.state == DetachedLayerState.Synchronization:
            return False

        if any(
            detached_layer.layer.isEditable()
            for detached_layer in self.__detached_layers.values()
        ):
            return False

        if not is_manual and self.check_date is not None:
            interval = 60
            if (datetime.now() - self.check_date).total_seconds() < interval:
                return False

        self.__lock_layers()

        container_path = self.__path
        metadata = self.metadata
        layer_name = self.__metadata.layer_name
        resource_id = self.__metadata.resource_id

        if self.is_stub:
            if metadata.is_versioning_enabled:
                self.__sync_task = FillLayerWithVersioning(container_path)
            else:
                self.__sync_task = DownloadGpkgTask(container_path)
            self.__sync_task.download_finished.connect(self.__on_task_finished)
        elif self.metadata.has_changes:
            self.__sync_task = UploadChangesTask(container_path)
            self.__sync_task.synchronization_finished.connect(
                self.__on_task_finished
            )
        else:
            logger.debug(
                f'There are no changes to upload for layer "{layer_name}" '
                f"(id={resource_id})"
            )
            self.__unlock_layers()
            return False

        self.__state = DetachedLayerState.Synchronization
        self.state_changed.emit(self.__state)

        task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

        return True

    def force_synchronize(self) -> None:
        layer_name = self.__metadata.layer_name
        resource_id = self.__metadata.resource_id
        logger.debug(
            f'Started forced synchronization for layer "{layer_name}" '
            f"(id={resource_id})"
        )

        connection_id = self.__metadata.connection_id
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        cache_manager = NgConnectCacheManager()
        cache_directory = Path(cache_manager.cache_directory)

        instance_cache_path = cache_directory / ngw_layer.connection_id
        instance_cache_path.mkdir(parents=True, exist_ok=True)
        gpkg_path = instance_cache_path / f"{ngw_layer.common.id}.gpkg"

        gpkg_path.unlink()

        detached_factory = DetachedLayerFactory()
        detached_factory.create_container(ngw_layer, gpkg_path)

        self.__update_state(is_full_update=True)

        self.synchronize(is_manual=True)

    def __update_state(self, is_full_update: bool = False) -> None:  # noqa
        try:
            self.__metadata = utils.container_metadata(self.path)
        except Exception:
            self.__state = DetachedLayerState.Error
            self.__error_type = DetachedLayerErrorType.CreationError
            self.__versioning_state = (
                VersioningSynchronizationState.NotVersionedLayer
            )
            self.__changes = DetachedContainerChanges()
            self.state_changed.emit(self.__state)
            return

        if self.__metadata.is_stub:
            self.__state = DetachedLayerState.NotInitialized
            self.__versioning_state = (
                VersioningSynchronizationState.NotInitialized
                if self.__metadata.is_versioning_enabled
                else VersioningSynchronizationState.NotVersionedLayer
            )
            self.__changes = DetachedContainerChanges()
            self.state_changed.emit(self.__state)
            return

        self.__versioning_state = (
            VersioningSynchronizationState.NotVersionedLayer
        )

        if self.__sync_task is not None and self.__sync_task.status() not in (
            QgsTask.TaskStatus.Complete,
            QgsTask.TaskStatus.Terminated,
        ):
            self.__state = DetachedLayerState.Synchronization
        else:
            self.__state = (
                DetachedLayerState.NotSynchronized
                if self.__metadata.has_changes
                else DetachedLayerState.Synchronized
            )

        if is_full_update:
            self.__changes = utils.container_changes(self.path)
        self.__error_type = DetachedLayerErrorType.NoError

        self.state_changed.emit(self.__state)

    def __on_task_finished(self, result: bool) -> None:  # noqa: FBT001
        if result:
            self.__state = DetachedLayerState.Synchronized
            self.__versioning_state = (
                VersioningSynchronizationState.Synchronized
            )
            now = datetime.now()
            for detached_layer in self.__detached_layers.values():
                detached_layer.layer.setCustomProperty("ngw_check_date", now)

            first_layer = next(iter(self.__detached_layers.values()))
            first_layer.layer.reload()

        else:
            self.__state = DetachedLayerState.Error

        self.__sync_task = None

        self.__unlock_layers()

        self.__update_state()

        # Start next layer update
        NgConnectInterface.instance().update_layers()

    def __lock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.layer.setReadOnly(True)

    def __unlock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.layer.setReadOnly(False)

    def __clear_indicators(self) -> None:
        if self.__indicator is None:
            return

        project = QgsProject.instance()
        assert project is not None

        root = project.layerTreeRoot()
        assert root is not None

        for layer_id in self.__detached_layers:
            node = root.findLayer(layer_id)
            if node is None:
                continue
            self.remove_indicator(node)
