import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from qgis.core import (
    QgsEditorWidgetSetup,
    QgsLayerTreeLayer,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from qgis.utils import iface

from nextgis_connect.detached_editing.action_extractor import ActionExtractor
from nextgis_connect.detached_editing.actions import (
    DataChangeAction,
    FeatureCreateAction,
    VersioningAction,
)
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

if TYPE_CHECKING:
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

    __is_project_container: bool

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
        self.__is_edit_allowed = True
        self.__is_project_container = parent is not None

        self.__update_state(is_full_update=True)

        if self.__is_project_container:
            self.__is_edit_allowed = False
            logger.debug(
                f'Detached container "{self.__path.name}" added to project'
            )

    def __del__(self) -> None:
        if self.__is_project_container:
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
    def is_not_initialized(self) -> bool:
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
        detached_layer.structure_changed.connect(
            lambda: self.__update_state(is_full_update=True)
        )
        detached_layer.layer_changed.connect(
            lambda: self.__update_state(is_full_update=True)
        )
        detached_layer.settings_changed.connect(
            self.__on_settings_changed,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore
        )

        layer.setReadOnly(not self.__is_edit_allowed)

        plugin = NgConnectInterface.instance()
        detached_layer.editing_finished.connect(plugin.synchronize_layers)  # type: ignore

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

        self.__update_state(is_full_update=is_manual)
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

        # task_manager = QgsApplication.taskManager()
        task_manager = NgConnectInterface.instance().task_manager
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

        return True

    def reset_container(self) -> None:
        logger.debug(f"Started layer {self.metadata} reset")

        # Get resource
        if self.__metadata is not None:
            connection_id = self.__metadata.connection_id
            resource_id = self.__metadata.resource_id
        else:
            connection_id = self.__property("ngw_connection_id")
            resource_id = self.__property("ngw_resource_id")

        if connection_id is None or resource_id is None:
            logger.error("Can't force synchronization")
            return

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)
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
            for service_file in self.path.parent.glob(f"{self.path.name}-*"):
                service_file.unlink(missing_ok=True)

        except Exception as os_error:
            message = "Can't replace stub file"
            error = ContainerError(
                message, code=ErrorCode.ContainerCreationError
            )
            error.__cause__ = os_error

            NgConnectInterface.instance().show_error(error)

        self.__state = DetachedLayerState.NotInitialized
        self.__versioning_state = VersioningSynchronizationState.NotInitialized
        self.__error = None

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

        self.__check_structure()

        if self.state == DetachedLayerState.Error:
            if is_full_update:
                self.__changes = utils.container_changes(self.path)
            self.__additional_data_fetch_date = None
            self.state_changed.emit(self.__state)
            return

        if self.__metadata.is_not_initialized:
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

    def __init_ordinary_task(self) -> None:
        if self.is_not_initialized:
            self.__sync_task = DownloadGpkgTask(self.path)
            self.__sync_task.download_finished.connect(
                self.__on_synchronization_finished
            )
            return

        if self.metadata.has_changes:
            self.__sync_task = UploadChangesTask(self.path)
            self.__sync_task.taskCompleted.connect(
                lambda: self.__on_synchronization_finished(True)
            )
            self.__sync_task.taskTerminated.connect(
                lambda: self.__on_synchronization_finished(False)
            )
            return

    def __init_versioning_task(self) -> None:
        State = VersioningSynchronizationState

        if self.is_not_initialized:
            self.__sync_task = FillLayerWithVersioning(self.path)
            self.__sync_task.download_finished.connect(
                self.__on_synchronization_finished
            )
            self.__versioning_state = State.FetchingChanges
            return

        self.__sync_task = FetchDeltaTask(self.path)
        self.__sync_task.download_finished.connect(self.__on_fetch_finished)
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
            first_layer.qgs_layer.reload()

        if (
            self.__additional_data_fetch_date is not None
            and datetime.now() - self.__additional_data_fetch_date
            <= timedelta(hours=1)
        ):
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
        if not result:
            self.__on_synchronization_finished(False)
            return

        assert isinstance(self.__sync_task, FetchDeltaTask)

        if len(self.__sync_task.delta) > 0:
            try:
                self.__has_conflicts(self.__sync_task.delta)
            except Exception as error:
                ng_error = NgConnectError()
                ng_error.__cause__ = error
                self.__process_sync_error(ng_error)
                self.__finish_sync()
                return

            self.__versioning_state = (
                VersioningSynchronizationState.ChangesApplying
            )
            sync_task = ApplyDeltaTask(
                self.path,
                self.__sync_task.target,
                self.__sync_task.timestamp,
                self.__sync_task.delta,
            )
            sync_task.apply_finished.connect(self.__on_apply_finished)
            self.__start_sync(sync_task)
            return

        if self.metadata.has_changes:
            self.__versioning_state = (
                VersioningSynchronizationState.UploadingChanges
            )
            task = UploadChangesTask(self.path)
            task.taskCompleted.connect(
                lambda: self.__on_versioned_uploading_finished(True)
            )
            task.taskTerminated.connect(
                lambda: self.__on_versioned_uploading_finished(False)
            )
            self.__start_sync(task)
            return

        self.__on_synchronization_finished(True)

    @pyqtSlot(bool)
    def __on_apply_finished(self, result: bool) -> None:
        if not result:
            self.__on_synchronization_finished(False)
            return

        assert isinstance(self.__sync_task, ApplyDeltaTask)

        self.__update_state()

        if self.metadata.has_changes:
            self.__versioning_state = (
                VersioningSynchronizationState.UploadingChanges
            )
            task = UploadChangesTask(self.path)
            task.taskCompleted.connect(
                lambda: self.__on_versioned_uploading_finished(True)
            )
            task.taskTerminated.connect(
                lambda: self.__on_versioned_uploading_finished(False)
            )
            self.__start_sync(task)
            return

        self.__on_synchronization_finished(True)

    @pyqtSlot(bool)
    def __on_versioned_uploading_finished(self, result: bool) -> None:
        if not result:
            self.__on_synchronization_finished(False)
            return

        task = FetchDeltaTask(self.path)
        task.download_finished.connect(self.__on_fetch_finished)
        self.__versioning_state = (
            VersioningSynchronizationState.FetchingChanges
        )
        self.__start_sync(task)

    def __start_sync(self, task: DetachedEditingTask) -> None:
        self.__sync_task = task

        task_manager = NgConnectInterface.instance().task_manager
        # task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

    def __finish_sync(self) -> None:
        self.__sync_task = None

        self.__update_state(is_full_update=True)
        self.__unlock_layers()

        logger.debug("<b>Synchronization finished</b>")

        # Start next layer update
        NgConnectInterface.instance().synchronize_layers()

    def __lock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.setReadOnly(True)

    def __unlock_layers(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.setReadOnly(not self.__is_edit_allowed)

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
            custom_property = detached_layer.qgs_layer.customProperty(name)
            if custom_property is not None:
                return custom_property
        return None

    def __set_property(self, name: str, value: Any) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.setCustomProperty(name, value)

    def __apply_aliases(self) -> None:
        for detached_layer in self.__detached_layers.values():
            for field in self.metadata.fields:
                detached_layer.qgs_layer.setFieldAlias(
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
                    detached_layer.qgs_layer.setEditorWidgetSetup(
                        attribute_id, setup
                    )

        attributes_with_removed_lookup_table = (
            self.__sync_task.attributes_with_removed_lookup_table
        )
        for detached_layer in self.__detached_layers.values():
            for attribute_id in attributes_with_removed_lookup_table:
                setup = QgsEditorWidgetSetup("TextEdit", {})
                detached_layer.qgs_layer.setEditorWidgetSetup(
                    attribute_id, setup
                )

    def __update_layers_properties(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.update()

    def __process_sync_error(self, error: NgConnectError) -> None:
        self.__state = DetachedLayerState.Error
        self.__versioning_state = VersioningSynchronizationState.Error
        self.__error = error

        NgConnectInterface.instance().show_error(error)

    def __check_structure(self) -> None:
        container_fields_name = set()
        with closing(self.make_connection()) as connection, closing(
            connection.cursor()
        ) as cursor:
            container_fields_name = set(
                row[1]
                for row in cursor.execute(
                    f"PRAGMA table_info('{self.metadata.table_name}')"
                )
                if row[1] not in ("fid", "geom")
            )

        if all(
            ngw_field.keyname in container_fields_name
            for ngw_field in self.metadata.fields
        ):
            return

        self.__state = DetachedLayerState.Error
        self.__versioning_state = VersioningSynchronizationState.Error
        message = "Fields changed in QGIS"
        code = ErrorCode.StructureChanged
        self.__error = ContainerError(message, code=code)
        self.__changes = DetachedContainerChangesInfo()
        self.__additional_data_fetch_date = None
        self.__is_edit_allowed = False

    @pyqtSlot()
    def __on_settings_changed(self) -> None:
        self.__update_state(is_full_update=True)
        self.__update_layers_properties()
        self.synchronize(is_manual=True)

    def __has_conflicts(self, actions: List[VersioningAction]) -> bool:
        delta_fids = set(
            action.fid
            for action in actions
            if isinstance(action, DataChangeAction)
        )

        extractor = ActionExtractor(self.path, self.metadata)
        local_changes_fids = set(
            action.fid
            for action in extractor.extract_all()
            if isinstance(action, DataChangeAction)
            and not isinstance(action, FeatureCreateAction)
        )

        return len(delta_fids.intersection(local_changes_fids)) > 0
