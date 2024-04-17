import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from qgis.core import (
    QgsApplication,
    QgsEditorWidgetSetup,
    QgsLayerTreeLayer,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from qgis.utils import iface

from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgConnectError,
)
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
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.tasks.detached_editing import (
    ApplyDeltaTask,
    DetachedEditingTask,
    DownloadGpkgTask,
    FetchAdditionalDataTask,
    FetchDeltaTask,
    FillLayerWithVersioning,
    UploadChangesTask,
)

from . import utils
from .detached_layer import DetachedLayer
from .detached_layer_factory import DetachedLayerFactory
from .detached_layer_indicator import DetachedLayerIndicator
from .utils import (
    DetachedContainerChangesInfo,
    DetachedContainerMetaData,
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
    __changes: DetachedContainerChangesInfo

    __error: Optional[NgConnectError]

    __indicator: Optional[DetachedLayerIndicator]
    __sync_task: Optional[DetachedEditingTask]

    __check_date: Optional[datetime]
    __additional_data_fetch_date: Optional[datetime]
    __is_edit_allowed: bool

    editing_started = pyqtSignal(name="editingStarted")
    editing_finished = pyqtSignal(name="editingFinished")

    state_changed = pyqtSignal(DetachedLayerState, name="stateChanged")

    def __init__(
        self, container_path: Path, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)

        self.__path = container_path
        self.__detached_layers = {}

        self.__metadata = None
        self.__state = DetachedLayerState.NotInitialized
        self.__versioning_state = VersioningSynchronizationState.NotInitialized
        self.__changes = DetachedContainerChangesInfo()

        self.__error = None

        self.__indicator = None
        self.__sync_task = None

        self.__check_date = None
        self.__additional_data_fetch_date = None
        self.__is_edit_allowed = False

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
    def error(self) -> Optional[NgConnectError]:
        return self.__error

    @property
    def error_code(self) -> ErrorCode:
        if self.__error is None:
            return ErrorCode.NoError
        return self.__error.code

    @property
    def check_date(self) -> Optional[datetime]:
        return self.__check_date

    @property
    def sync_date(self) -> Optional[datetime]:
        return self.__metadata.sync_date if self.__metadata else None

    @property
    def layers_count(self) -> int:
        return len(self.__detached_layers)

    @property
    def is_empty(self) -> bool:
        return len(self.__detached_layers) == 0

    @property
    def can_be_deleted(self) -> bool:
        if self.state != DetachedLayerState.Synchronization:
            return True

        if not self.metadata.is_versioning_enabled and not isinstance(
            self.__sync_task, UploadChangesTask
        ):
            return True

        State = VersioningSynchronizationState
        if self.metadata.is_versioning_enabled and self.__versioning_state in (
            State.FetchingChanges,
            State.ConflictSolving,
        ):
            return True

        return False

    @property
    def is_edit_mode_enabled(self) -> bool:
        return any(
            layer.is_edit_mode_enabled
            for layer in self.__detached_layers.values()
        )

    @property
    def changes_info(self) -> DetachedContainerChangesInfo:
        return self.__changes

    def add_layer(self, layer: QgsVectorLayer) -> None:
        detached_layer = DetachedLayer(self, layer)
        detached_layer.editing_started.connect(self.editing_started)
        detached_layer.editing_finished.connect(self.editing_finished)
        detached_layer.layer_changed.connect(
            lambda: self.__update_state(is_full_update=True)
        )
        detached_layer.settings_changed.connect(
            self.__on_settings_changed,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore
        )

        layer.setReadOnly(not self.__is_edit_allowed)

        plugin = NgConnectInterface.instance()
        detached_layer.editing_finished.connect(plugin.update_layers)  # type: ignore

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
        return sqlite3.connect(str(self.__path))

    def synchronize(self, *, is_manual: bool = False) -> bool:
        if (
            self.is_edit_mode_enabled
            or self.state == DetachedLayerState.Synchronization
        ):
            return False

        self.__update_state()
        if self.metadata is None:
            return False

        if is_manual:
            self.__additional_data_fetch_date = None
        else:
            if self.state == DetachedLayerState.Error:
                return False

            if self.check_date is not None and not self.metadata.has_changes:
                period = NgConnectSettings().synchronizatin_period
                if datetime.now() - self.check_date < period:
                    return False

        self.__init_sync_task()

        if self.__sync_task is None:
            self.__check_date = datetime.now()
            return False

        self.__lock_layers()

        self.__state = DetachedLayerState.Synchronization
        self.state_changed.emit(self.__state)

        task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

        return True

    def force_synchronize(self) -> None:
        logger.debug(
            f"Started forced synchronization for layer {self.metadata}"
        )

        # Get resource

        connection_id = self.__metadata.connection_id
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)
        resource_id = self.__metadata.resource_id
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        # Create stub

        temp_file_path = tempfile.mktemp(suffix=".gpkg")

        detached_factory = DetachedLayerFactory()
        try:
            detached_factory.create_container(ngw_layer, Path(temp_file_path))
        except ContainerError as error:
            logger.exception("Failed to force synchronization")
            self.__error = error
            self.__state = DetachedLayerState.Error
            self.__versioning_state = VersioningSynchronizationState.Error
            self.__additional_data_fetch_date = None

        # Replace container with stub

        try:
            shutil.move(str(temp_file_path), str(self.path))
        except Exception as os_error:
            message = "Can't replace stub file"
            error = ContainerError(
                message, code=ErrorCode.ContainerCreationError
            )
            error.__cause__ = os_error

            NgConnectInterface.instance().show_error(error)

        # Update state and notify listeners

        self.__update_state(is_full_update=True)

        # Fill data

        self.synchronize(is_manual=True)

    def __update_state(self, is_full_update: bool = False) -> None:
        try:
            self.__metadata = utils.container_metadata(self.path)
            if not self.metadata.is_versioning_enabled:
                self.__versioning_state = (
                    VersioningSynchronizationState.NotVersionedLayer
                )

        except NgConnectError as error:
            self.__state = DetachedLayerState.Error
            self.__versioning_state = VersioningSynchronizationState.Error
            self.__error = error
            self.__changes = DetachedContainerChangesInfo()
            self.__additional_data_fetch_date = None
            self.__is_edit_allowed = False

            self.state_changed.emit(self.__state)
            return

        except Exception:
            self.__state = DetachedLayerState.Error
            self.__versioning_state = VersioningSynchronizationState.Error
            self.__error = ContainerError()
            self.__changes = DetachedContainerChangesInfo()
            self.__additional_data_fetch_date = None
            self.__is_edit_allowed = False

            self.state_changed.emit(self.__state)
            return

        if self.state == DetachedLayerState.Error:
            if is_full_update:
                self.__changes = utils.container_changes(self.path)
            self.__additional_data_fetch_date = None
            self.state_changed.emit(self.__state)
            return

        if self.__metadata.is_stub:
            self.__state = DetachedLayerState.NotInitialized
            if self.metadata.is_versioning_enabled:
                self.__versioning_state = (
                    VersioningSynchronizationState.NotInitialized
                )
            self.__changes = DetachedContainerChangesInfo()
            self.__check_date = None
            self.__additional_data_fetch_date = None
            self.__is_edit_allowed = False
            self.state_changed.emit(self.__state)
            return

        if self.__sync_task is not None and self.__sync_task.status() not in (
            QgsTask.TaskStatus.Complete,
            QgsTask.TaskStatus.Terminated,
        ):
            self.__state = DetachedLayerState.Synchronization
        else:
            is_not_synchronized = (
                self.__metadata.has_changes
                or self.__additional_data_fetch_date is None
            )
            self.__state = (
                DetachedLayerState.NotSynchronized
                if is_not_synchronized
                else DetachedLayerState.Synchronized
            )
            self.__versioning_state = (
                VersioningSynchronizationState.NotSynchronized
                if is_not_synchronized
                else VersioningSynchronizationState.Synchronized
            )

        if is_full_update:
            self.__changes = utils.container_changes(self.path)

        self.__error = None

        self.state_changed.emit(self.__state)

    def __init_sync_task(self) -> None:
        if self.metadata.is_versioning_enabled:
            self.__init_versioning_task()
        else:
            self.__init_ordinary_task()

        if self.__sync_task is None and (
            self.__additional_data_fetch_date is None
            or datetime.now() - self.__additional_data_fetch_date
            > timedelta(hours=1)
        ):
            self.__sync_task = FetchAdditionalDataTask(
                self.path, need_update_structure=True
            )
            self.__sync_task.download_finished.connect(
                self.__on_additional_data_fetched
            )

        if self.__sync_task is None:
            logger.debug(
                f"There are no changes to upload for layer {self.metadata}"
            )

    def __init_ordinary_task(self) -> None:
        if self.is_stub:
            self.__sync_task = DownloadGpkgTask(self.path)
            self.__sync_task.download_finished.connect(
                self.__on_synchronization_finished
            )
            return

        if self.metadata.has_changes:
            self.__sync_task = UploadChangesTask(self.path)
            self.__sync_task.synchronization_finished.connect(
                self.__on_synchronization_finished
            )
            return

    def __init_versioning_task(self) -> None:
        if self.is_stub:
            self.__sync_task = FillLayerWithVersioning(self.path)
            self.__sync_task.download_finished.connect(
                self.__on_synchronization_finished
            )
            return

        State = VersioningSynchronizationState
        if self.__versioning_state == State.Synchronized:
            self.__sync_task = FetchDeltaTask(self.path)
            self.__sync_task.download_finished.connect(
                self.__on_fetch_finished
            )
            self.__versioning_state = State.FetchingChanges

    @pyqtSlot(bool)
    def __on_synchronization_finished(self, result: bool) -> None:
        assert self.__sync_task is not None
        if not result:
            assert self.__sync_task.error is not None
            self.__process_sync_error(self.__sync_task.error)
            self.__finish_sync()
            return

        self.__check_date = datetime.now()
        self.__state = DetachedLayerState.Synchronized
        self.__versioning_state = VersioningSynchronizationState.Synchronized

        if not self.is_empty:
            first_layer = next(iter(self.__detached_layers.values()))
            first_layer.layer.reload()

        if self.__additional_data_fetch_date is not None:
            self.__finish_sync()
            return

        # After first sync
        self.__sync_task = FetchAdditionalDataTask(
            self.path, need_update_structure=False
        )
        self.__sync_task.download_finished.connect(
            self.__on_additional_data_fetched
        )
        self.__start_sync(self.__sync_task)

    @pyqtSlot(bool)
    def __on_additional_data_fetched(self, result: bool) -> None:
        assert isinstance(self.__sync_task, FetchAdditionalDataTask)
        if result:
            self.__additional_data_fetch_date = datetime.now()
            self.__is_edit_allowed = self.__sync_task.is_edit_allowed
            self.__apply_aliases()
            self.__apply_lookup_tables()
            self.__state = DetachedLayerState.Synchronized
            self.__versioning_state = (
                VersioningSynchronizationState.Synchronized
            )
        else:
            assert self.__sync_task.error is not None
            self.__process_sync_error(self.__sync_task.error)

            self.__is_edit_allowed = False
            self.__additional_data_fetch_date = None

        self.__finish_sync()

    @pyqtSlot(bool)
    def __on_fetch_finished(self, result: bool) -> None:
        assert isinstance(self.__sync_task, FetchDeltaTask)
        if not result:
            assert self.__sync_task.error is not None
            self.__process_sync_error(self.__sync_task.error)
            self.__finish_sync()
            return

        self.__versioning_state = (
            VersioningSynchronizationState.ChangesApplying
        )
        self.__sync_task = ApplyDeltaTask(
            self.path,
            self.__sync_task.target,
            self.__sync_task.timestamp,
            self.__sync_task.delta,
        )
        self.__sync_task.apply_finished.connect(self.__on_apply_finished)

        self.__start_sync(self.__sync_task)

    @pyqtSlot(bool)
    def __on_apply_finished(self, result: bool) -> None:
        assert isinstance(self.__sync_task, ApplyDeltaTask)
        if not result:
            assert self.__sync_task.error is not None
            self.__process_sync_error(self.__sync_task.error)
            self.__finish_sync()
            return

        # TODO (ivanbarsukov): Conflicts

        if self.metadata.has_changes:
            task = UploadChangesTask(self.path)
            task.synchronization_finished.connect(
                self.__on_synchronization_finished
            )
            self.__start_sync(task)
            return

        logger.debug(
            f"There are no changes to upload for layer {self.metadata}"
        )

        self.__finish_sync()

    def __start_sync(self, task: DetachedEditingTask) -> None:
        self.__sync_task = task

        task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

    def __finish_sync(self) -> None:
        self.__sync_task = None

        self.__update_state(is_full_update=True)
        self.__unlock_layers()

        logger.debug("<b>Synchronization finished</b>")

        # Start next layer update
        NgConnectInterface.instance().update_layers()

    def __lock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.layer.setReadOnly(True)

    def __unlock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.layer.setReadOnly(not self.__is_edit_allowed)

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

    def __property(self, name: str) -> None:
        for detached_layer in self.__detached_layers.values():
            custom_property = detached_layer.layer.customProperty(name)
            if custom_property is not None:
                return custom_property
        return None

    def __set_property(self, name: str, value: Any) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.layer.setCustomProperty(name, value)

    def __apply_aliases(self) -> None:
        for detached_layer in self.__detached_layers.values():
            for field in self.metadata.fields:
                detached_layer.layer.setFieldAlias(
                    field.attribute, field.display_name
                )

    def __apply_lookup_tables(self) -> None:
        assert isinstance(self.__sync_task, FetchAdditionalDataTask)

        for lookup_table_id, pairs in self.__sync_task.lookup_tables.items():
            attributes_id = [
                field.attribute
                for field in self.metadata.fields
                if field.lookup_table == lookup_table_id
            ]

            for detached_layer in self.__detached_layers.values():
                for attribute_id in attributes_id:
                    setup = QgsEditorWidgetSetup("ValueMap", {"map": pairs})
                    detached_layer.layer.setEditorWidgetSetup(
                        attribute_id, setup
                    )

        attributes_with_removed_lookup_table = (
            self.__sync_task.attributes_with_removed_lookup_table
        )
        for detached_layer in self.__detached_layers.values():
            for attribute_id in attributes_with_removed_lookup_table:
                setup = QgsEditorWidgetSetup("TextEdit", {})
                detached_layer.layer.setEditorWidgetSetup(attribute_id, setup)

    def __update_layers_properties(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.fill_properties(self.__metadata)

    def __process_sync_error(self, error: NgConnectError) -> None:
        self.__state = DetachedLayerState.Error
        self.__versioning_state = VersioningSynchronizationState.Error
        self.__error = error

        NgConnectInterface.instance().show_error(error)

    @pyqtSlot()
    def __on_settings_changed(self) -> None:
        self.__update_state(is_full_update=True)
        self.__update_layers_properties()
        self.synchronize(is_manual=True)
