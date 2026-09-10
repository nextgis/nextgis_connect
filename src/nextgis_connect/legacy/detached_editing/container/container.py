# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import os
import shutil
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

from qgis.core import (
    QgsEditorWidgetSetup,
    QgsLayerTreeLayer,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from qgis.utils import iface

from nextgis_connect.features.synchronization.presentation import (
    DetachedLayerIndicatorPresenter,
    DetachedLayerTreeIndicator,
)
from nextgis_connect.legacy.detached_editing import utils
from nextgis_connect.legacy.detached_editing.conflicts.auto_resolver import (
    ConflictsAutoResolver,
)
from nextgis_connect.legacy.detached_editing.conflicts.detector import (
    ConflictsDetector,
)
from nextgis_connect.legacy.detached_editing.conflicts.resolutions_applier import (
    ConflictsResolutionApplier,
)
from nextgis_connect.legacy.detached_editing.conflicts.ui.resolving_dialog import (
    ResolvingDialog,
)
from nextgis_connect.legacy.detached_editing.container.container_factory import (
    DetachedContainerFactory,
)
from nextgis_connect.legacy.detached_editing.container.layer_update_polling_policy import (
    LayerUpdatePollingPolicy,
)
from nextgis_connect.legacy.detached_editing.container.ui.layer_status_dialog import (
    DetachedLayerStatusDialog,
)
from nextgis_connect.legacy.detached_editing.detached_layer import (
    DetachedLayer,
)
from nextgis_connect.legacy.detached_editing.reset import (
    confirm_reset_container,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.sync.common import (
    DetachedEditingTask,
    FetchAdditionalDataTask,
    UploadChangesTask,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes_extractor import (
    ChangesExtractor,
)
from nextgis_connect.legacy.detached_editing.sync.non_versioned import (
    FillLayerWithoutVersioningTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned import (
    ApplyDeltaTask,
    FetchDeltaTask,
    FillLayerWithVersioningTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions import (
    VersioningAction,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerChangesInfo,
    DetachedContainerContext,
    DetachedContainerMetaData,
    DetachedLayerState,
    VersioningSynchronizationState,
    make_connection,
)
from nextgis_connect.legacy.ngw.core import NGWVectorLayer
from nextgis_connect.legacy.ngw.core.ngw_error import NGWError
from nextgis_connect.legacy.ngw.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    ErrorCode,
    NgConnectError,
    NgConnectWarning,
    NgwError,
    SynchronizationError,
)
from nextgis_connect.platform.qgis.utils import wrap_sql_value
from nextgis_connect.plugin.plugin_interface import NgConnectInterface

if TYPE_CHECKING:
    assert isinstance(iface, QgisInterface)


_RESET_REQUIRED_ERROR_CODES = (
    ErrorCode.ContainerVersionIsOutdated,
    ErrorCode.NotVersionedContentChanged,
    ErrorCode.EpochChanged,
    ErrorCode.StructureChanged,
    ErrorCode.VersioningEnabled,
    ErrorCode.VersioningDisabled,
)


@dataclass(frozen=True)
class _TaskSignalConnection:
    task: DetachedEditingTask
    signal: Any
    slot: Callable[..., None]


class DetachedContainer(QObject):
    __path: Path
    __detached_layers: Dict[str, DetachedLayer]

    __metadata: DetachedContainerMetaData
    __state: DetachedLayerState
    __versioning_state: VersioningSynchronizationState
    __changes: DetachedContainerChangesInfo

    __error: Union[NgConnectWarning, NgConnectError, None]

    __indicator: Optional[DetachedLayerTreeIndicator]
    __indicator_presenter: Optional[DetachedLayerIndicatorPresenter]
    __sync_task: Optional[DetachedEditingTask]
    __sync_task_signal_connections: List[_TaskSignalConnection]
    __is_silent_sync: bool
    __is_destroyed: bool

    __check_date: Optional[datetime]
    __polling_policy: LayerUpdatePollingPolicy
    __network_error_count: int
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
        self.__is_not_initialized = True
        self.__state = DetachedLayerState.NotInitialized
        self.__versioning_state = VersioningSynchronizationState.NotInitialized
        self.__changes = DetachedContainerChangesInfo()

        self.__error = None

        self.__indicator = None
        self.__indicator_presenter = None
        self.__sync_task = None
        self.__sync_task_signal_connections = []
        self.__is_silent_sync = False
        self.__is_destroyed = False

        self.__check_date = None
        self.__polling_policy = LayerUpdatePollingPolicy()
        self.__network_error_count = 0
        self.__additional_data_fetch_date = None
        self.__is_edit_allowed = True
        self.__is_project_container = parent is not None
        self.destroyed.connect(self.__on_destroyed)
        self.state_changed.connect(self.__refresh_indicator_presenter)

        self.__update_state(is_full_update=True)

        if self.__is_project_container:
            if self.metadata.is_auto_sync_enabled:
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
    def context(self) -> DetachedContainerContext:
        return DetachedContainerContext(self.path, self.metadata)

    @property
    def state(self) -> DetachedLayerState:
        return self.__state

    @property
    def is_not_initialized(self) -> bool:
        return self.__is_not_initialized

    @property
    def error(self) -> Union[NgConnectWarning, NgConnectError, None]:
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

    def refresh_additional_data(self) -> bool:
        return self.synchronize(update_additional_only=True)

    def set_edit_allowed(self, is_edit_allowed: bool) -> None:
        if self.__is_qobject_deleted():
            return

        self.__is_edit_allowed = is_edit_allowed
        self.__unlock_layers()

    def update_connection(
        self, connection_id: str, instance_id: Optional[str]
    ) -> bool:
        if self.__is_qobject_deleted():
            return False

        if self.metadata is None:
            return False

        current_connection_id = self.metadata.connection_id
        current_instance_id = self.metadata.instance_id
        next_instance_id = (
            current_instance_id if instance_id is None else instance_id
        )
        if (
            current_connection_id == connection_id
            and current_instance_id == next_instance_id
        ):
            return False

        with closing(make_connection(self.path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                UPDATE ngw_metadata
                SET connection_id=?, instance_id=?
                """,
                (connection_id, next_instance_id),
            )
            connection.commit()

        self.__additional_data_fetch_date = None
        self.__update_state(is_full_update=True)
        self.__update_layers_properties()

        return True

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
        detached_layer.error_occurred.connect(self.__process_error)

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
            self.__indicator_presenter = None

            if self.__error is not None:
                NgConnectInterface.instance().notifier.dismiss_message(
                    self.__error.error_id
                )

        logger.debug(
            f'Layer "{layer_id}" detached from container "{self.__path.name}"'
        )

    def layer(self, layer: QgsVectorLayer) -> Optional[DetachedLayer]:
        """Return detached layer for QGIS layer.

        :param layer: Vector layer.
        :return: Detached layer or ``None`` if layer is not detached.
        """
        return self.__detached_layers.get(layer.id())

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
            self.__indicator_presenter = DetachedLayerIndicatorPresenter(
                self,
                self,
            )
            self.__indicator = DetachedLayerTreeIndicator(
                self,
                self.__indicator_presenter,
            )
            self.__indicator.details_requested.connect(
                self.__open_layer_status_dialog
            )

        if self.__indicator in view.indicators(node):
            return

        view.addIndicator(node, self.__indicator)

    def remove_indicator(self, node: QgsLayerTreeLayer):
        view = iface.layerTreeView()
        assert view is not None

        if self.__indicator not in view.indicators(node):
            return

        view.removeIndicator(node, self.__indicator)

    def __open_layer_status_dialog(self) -> None:
        dialog = DetachedLayerStatusDialog(self)
        dialog.exec()

    def synchronize(
        self,
        *,
        is_manual: bool = False,
        update_additional_only: bool = False,
    ) -> bool:
        if self.__is_qobject_deleted():
            return False

        if self.is_edit_mode_enabled:
            if update_additional_only:
                self.__additional_data_fetch_date = None
            return False

        if self.state == DetachedLayerState.Synchronization:
            if update_additional_only:
                self.__additional_data_fetch_date = None
            return False

        if (
            not update_additional_only
            and not is_manual
            and not self.metadata.is_auto_sync_enabled
        ):
            return False

        self.__update_state(is_full_update=is_manual)
        if self.metadata is None:
            return False

        current_date = datetime.now()
        is_network_error_retry = False
        self.__is_silent_sync = False

        if update_additional_only:
            self.__additional_data_fetch_date = None
            sync_task = FetchAdditionalDataTask(
                self.path, need_update_structure=True
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskCompleted,
                self.__on_additional_data_fetched,
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskTerminated,
                self.__on_additional_data_fetched,
            )
        elif is_manual:
            self.__additional_data_fetch_date = None
            sync_task = self.__init_sync_task()
        else:
            if self.state == DetachedLayerState.Error:
                if (
                    self.__is_network_error(self.error)
                    and not self.metadata.has_changes
                ):
                    self.__is_silent_sync = True
                    is_network_error_retry = True
                else:
                    return False

            if not self.metadata.has_changes:
                if is_network_error_retry:
                    if not (
                        self.__polling_policy.should_retry_after_network_error(
                            last_attempt_date=self.check_date,
                            consecutive_error_count=(
                                self.__network_error_count
                            ),
                            current_date=current_date,
                        )
                    ):
                        return False
                elif not (
                    self.__polling_policy.should_poll(
                        last_check_date=self.check_date,
                        last_change_date=self.sync_date,
                        current_date=current_date,
                    )
                ):
                    return False

            sync_task = self.__init_sync_task()

        if sync_task is None:
            self.__check_date = current_date
            return False

        self.__lock_layers()

        self.__state = DetachedLayerState.Synchronization
        self.__emit_state_changed()

        self.__start_sync(sync_task)

        return True

    def reset_container(self) -> None:
        if self.__is_qobject_deleted():
            return

        logger.debug(f"Start layer {self.metadata} reset")

        self.__reset_error()

        # Get resource
        if self.__metadata is not None:
            connection_id = self.__metadata.connection_id
            resource_id = self.__metadata.resource_id
        else:
            connection_id = self.__property("ngw_connection_id")
            resource_id = self.__property("ngw_resource_id")

        if connection_id is None or resource_id is None:
            error = ContainerError(
                "An error occurred while resetting layer. Empty ids"
            )
            self.__process_error(error)
            return

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)
        try:
            ngw_layer = resources_factory.get_resource(resource_id)
        except NgwError as error:
            error.try_again = self.reset_container
            self.__process_error(error)
            return
        except Exception as error:
            ng_error = NgConnectError(
                "An error occurred while resetting layer",
            )
            ng_error.__cause__ = error
            ng_error.try_again = self.reset_container
            self.__process_error(ng_error)
            return

        assert isinstance(ngw_layer, NGWVectorLayer)

        # Create stub

        temp_file_fd, temp_file_path = tempfile.mkstemp(suffix=".gpkg")
        os.close(temp_file_fd)
        Path(temp_file_path).unlink(missing_ok=True)

        detached_factory = DetachedContainerFactory()
        try:
            detached_factory.create_initial_container(
                ngw_layer, Path(temp_file_path)
            )
        except ContainerError as error:
            error.try_again = self.reset_container
            self.__process_error(error)
            return

        # Replace container with dummy
        for layer in self.__detached_layers.values():
            layer.enable_fake()

        try:
            for service_file in self.path.parent.glob(f"{self.path.name}-*"):
                service_file.unlink(missing_ok=True)
            shutil.move(str(temp_file_path), str(self.path))
            DetachedStorageServiceFactory.create().register_detached_container(
                connection.domain_uuid,
                resource_id,
                connection_id=connection.id,
                container_path=self.path,
            )

        except Exception as os_error:
            message = "Can't replace container"
            error = ContainerError(
                message, code=ErrorCode.ContainerCreationError
            )
            error.__cause__ = os_error
            error.try_again = self.reset_container

            self.__process_error(error)

            return

        self.__metadata = utils.container_metadata(self.path)

        for layer in self.__detached_layers.values():
            layer.disable_fake()

        self.__is_not_initialized = True
        self.__state = DetachedLayerState.NotInitialized
        self.__versioning_state = VersioningSynchronizationState.NotInitialized

        logger.debug(f"End layer {self.metadata} reset")

        # Update state and notify listeners

        self.__update_state(is_full_update=True)

        # Fill data

        self.synchronize(is_manual=True)

    def __update_state(self, is_full_update: bool = False) -> None:
        if self.__is_qobject_deleted():
            return

        try:
            self.__metadata = utils.container_metadata(self.path)
            self.__update_storage_index_state()
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
            self.__lock_layers()

            self.__emit_state_changed()
            return

        except Exception:
            self.__state = DetachedLayerState.Error
            self.__versioning_state = VersioningSynchronizationState.Error
            self.__error = ContainerError()
            self.__changes = DetachedContainerChangesInfo()
            self.__additional_data_fetch_date = None
            self.__is_edit_allowed = False
            self.__lock_layers()

            self.__emit_state_changed()
            return

        self.__is_not_initialized = self.__metadata.is_not_initialized

        self.__check_structure()

        if self.state == DetachedLayerState.Error:
            if is_full_update:
                self.__changes = utils.container_changes(self.path)
            self.__additional_data_fetch_date = None
            self.__emit_state_changed()
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
            self.__lock_layers()
            self.__emit_state_changed()
            return

        if self.__sync_task is not None:
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

        self.__reset_error()

        self.__emit_state_changed()

    def __update_storage_index_state(self) -> None:
        try:
            DetachedStorageServiceFactory.create().register_detached_container(
                self.__metadata.instance_id,
                self.__metadata.resource_id,
                connection_id=self.__metadata.connection_id,
                container_path=self.path,
                is_used_by_project=self.__is_project_container,
            )
        except Exception:
            logger.debug(
                "Could not update detached container storage index state",
                exc_info=True,
            )

    def __init_sync_task(self) -> Optional[DetachedEditingTask]:
        sync_task = None

        if self.metadata.is_versioning_enabled:
            sync_task = self.__init_versioning_task()
        else:
            sync_task = self.__init_ordinary_task()

        if sync_task is None and (
            self.__additional_data_fetch_date is None
            or datetime.now() - self.__additional_data_fetch_date
            > timedelta(hours=1)
        ):
            sync_task = FetchAdditionalDataTask(
                self.path, need_update_structure=True
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskCompleted,
                self.__on_additional_data_fetched,
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskTerminated,
                self.__on_additional_data_fetched,
            )

        return sync_task

    def __init_ordinary_task(self) -> Optional[DetachedEditingTask]:
        sync_task = None
        if self.is_not_initialized:
            sync_task = FillLayerWithoutVersioningTask(self.path)
        elif self.metadata.has_changes:
            sync_task = UploadChangesTask(self.path)

        if sync_task is not None:
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskCompleted,
                self.__on_synchronization_finished,
                True,
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskTerminated,
                self.__on_synchronization_finished,
                False,
            )

        return sync_task

    def __init_versioning_task(self) -> Optional[DetachedEditingTask]:
        State = VersioningSynchronizationState
        self.__versioning_state = State.FetchingChanges

        if self.is_not_initialized:
            sync_task = FillLayerWithVersioningTask(self.path)
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskCompleted,
                self.__on_fill_finished,
                True,
            )
            self.__connect_sync_task_signal(
                sync_task,
                sync_task.taskTerminated,
                self.__on_fill_finished,
                False,
            )
            return sync_task

        sync_task = FetchDeltaTask(self.path)
        self.__connect_sync_task_signal(
            sync_task,
            sync_task.taskCompleted,
            self.__on_fetch_finished,
        )
        self.__connect_sync_task_signal(
            sync_task,
            sync_task.taskTerminated,
            self.__on_fetch_finished,
        )
        return sync_task

    @pyqtSlot(bool)
    def __on_synchronization_finished(self, result: bool) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        self.__check_date = datetime.now()

        assert self.__sync_task is not None
        if not result:
            assert self.__sync_task.error is not None

            error = self.__sync_task.error
            self.__record_sync_error(error)
            if self.__is_network_error(error):
                self.__sync_task.error.try_again = lambda: self.synchronize(
                    is_manual=True
                )

            will_be_updated = (
                error.code
                in (
                    ErrorCode.ContainerVersionIsOutdated,
                    ErrorCode.VersioningEnabled,
                    ErrorCode.VersioningDisabled,
                    ErrorCode.EpochChanged,
                )
                and not self.metadata.has_changes
            )

            self.__process_error(
                self.__sync_task.error, show_error=not will_be_updated
            )
            self.__finish_sync()

            if will_be_updated:
                self.reset_container()

            return

        self.__reset_network_error_count()

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
        task = FetchAdditionalDataTask(self.path, need_update_structure=True)
        self.__connect_sync_task_signal(
            task,
            task.taskCompleted,
            self.__on_additional_data_fetched,
        )
        self.__connect_sync_task_signal(
            task,
            task.taskTerminated,
            self.__on_additional_data_fetched,
        )
        self.__start_sync(task)

    @pyqtSlot()
    def __on_additional_data_fetched(self) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        result = self.__sync_task.status() == QgsTask.TaskStatus.Complete
        assert isinstance(self.__sync_task, FetchAdditionalDataTask)
        if result:
            self.__reset_network_error_count()
            self.__additional_data_fetch_date = datetime.now()
            self.__is_edit_allowed = self.__sync_task.is_edit_allowed
            self.__update_state()
            self.__apply_label_attribute()
            self.__apply_aliases()
            self.__apply_required_constraints()
            self.__apply_lookup_tables()
            self.__fix_fid_widget()
            self.__state = DetachedLayerState.Synchronized
            self.__versioning_state = (
                VersioningSynchronizationState.Synchronized
            )
            self.__finish_sync()
        else:
            assert self.__sync_task.error is not None
            self.__check_date = datetime.now()

            error = self.__sync_task.error
            self.__record_sync_error(error)
            if self.__is_network_error(error):
                self.__sync_task.error.try_again = lambda: self.synchronize(
                    is_manual=True
                )

            will_be_updated = (
                error.code
                in (
                    ErrorCode.ContainerVersionIsOutdated,
                    ErrorCode.VersioningEnabled,
                    ErrorCode.VersioningDisabled,
                    ErrorCode.EpochChanged,
                )
                and not self.metadata.has_changes
            )

            self.__process_error(
                self.__sync_task.error, show_error=not will_be_updated
            )
            self.__finish_sync()

            if will_be_updated:
                self.reset_container()

    @pyqtSlot()
    def __on_fetch_finished(self) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        assert isinstance(self.__sync_task, FetchDeltaTask)
        result = self.__sync_task.status() == QgsTask.TaskStatus.Complete
        if not result:
            self.__on_synchronization_finished(False)
            return

        self.__reset_network_error_count()
        self.__update_state()

        if len(self.__sync_task.delta) > 0:
            try:
                delta = self.__process_delta_and_resolve_conflicts(
                    self.__sync_task
                )
            except SynchronizationError as error:
                error.try_again = lambda: self.synchronize(is_manual=True)
                self.__process_error(error)
                self.__finish_sync()
                return
            except Exception as error:
                ng_error = NgConnectError()
                ng_error.__cause__ = error
                self.__process_error(ng_error)
                self.__finish_sync()
                return

            # Even if delta is empty after conflicts resolution we should
            # update layer metadata

            fetch_delta_task = self.__sync_task

            self.__versioning_state = (
                VersioningSynchronizationState.ChangesApplying
            )
            task = ApplyDeltaTask(
                self.path,
                fetch_delta_task.target,
                fetch_delta_task.timestamp,
                delta,
            )
            self.__connect_sync_task_signal(
                task,
                task.taskCompleted,
                self.__on_apply_finished,
            )
            self.__connect_sync_task_signal(
                task,
                task.taskTerminated,
                self.__on_apply_finished,
            )
            self.__start_sync(task)
            return

        if self.metadata.has_changes:
            self.__versioning_state = (
                VersioningSynchronizationState.UploadingChanges
            )
            task = UploadChangesTask(self.path)
            self.__connect_sync_task_signal(
                task,
                task.taskCompleted,
                self.__on_versioned_uploading_finished,
            )
            self.__connect_sync_task_signal(
                task,
                task.taskTerminated,
                self.__on_versioned_uploading_finished,
            )
            self.__start_sync(task)
            return

        self.__on_synchronization_finished(True)

    @pyqtSlot()
    def __on_apply_finished(self) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        result = self.__sync_task.status() == QgsTask.TaskStatus.Complete
        if not result:
            self.__on_synchronization_finished(False)
            return

        self.__reset_network_error_count()
        self.__update_state()

        if not self.metadata.has_changes:
            self.__on_synchronization_finished(True)
            return

        self.__versioning_state = (
            VersioningSynchronizationState.UploadingChanges
        )
        task = UploadChangesTask(self.path)
        self.__connect_sync_task_signal(
            task,
            task.taskCompleted,
            self.__on_versioned_uploading_finished,
        )
        self.__connect_sync_task_signal(
            task,
            task.taskTerminated,
            self.__on_versioned_uploading_finished,
        )
        self.__start_sync(task)

    @pyqtSlot(bool)
    def __on_fill_finished(self, result: bool) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        if not result:
            self.__on_synchronization_finished(False)
            return

        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.triggerRepaint()

        self.__on_synchronization_finished(True)

    @pyqtSlot()
    def __on_versioned_uploading_finished(self) -> None:
        if self.__is_qobject_deleted() or self.__sync_task is None:
            return

        result = self.__sync_task.status() == QgsTask.TaskStatus.Complete
        if not result:
            self.__on_synchronization_finished(False)
            return

        self.__reset_network_error_count()
        self.__update_state()

        task = FetchDeltaTask(self.path)
        self.__connect_sync_task_signal(
            task,
            task.taskCompleted,
            self.__on_fetch_finished,
        )
        self.__connect_sync_task_signal(
            task,
            task.taskTerminated,
            self.__on_fetch_finished,
        )
        self.__versioning_state = (
            VersioningSynchronizationState.FetchingChanges
        )
        self.__start_sync(task)

    def __connect_sync_task_signal(
        self,
        task: DetachedEditingTask,
        signal: Any,
        slot: Callable[..., None],
        *slot_arguments: Any,
    ) -> None:
        if self.__is_qobject_deleted():
            return

        def guarded_slot() -> None:
            if not self.__can_handle_sync_task_result(task):
                return

            slot(*slot_arguments)

        signal.connect(guarded_slot)
        self.__sync_task_signal_connections.append(
            _TaskSignalConnection(task, signal, guarded_slot)
        )

    def __can_handle_sync_task_result(self, task: DetachedEditingTask) -> bool:
        return not self.__is_qobject_deleted() and self.__sync_task is task

    def __start_sync(self, task: DetachedEditingTask) -> None:
        if self.__is_qobject_deleted():
            self.__disconnect_sync_task_signals(task)
            return

        if self.__sync_task is not None and self.__sync_task is not task:
            self.__disconnect_sync_task_signals(self.__sync_task)

        if self.__is_silent_sync:
            logger.debug("Resync attempt started")
        self.__sync_task = task
        self.__reset_error()

        task_manager = NgConnectInterface.instance().task_manager
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

    def __finish_sync(self) -> None:
        self.__disconnect_sync_task_signals(self.__sync_task)
        self.__sync_task = None
        self.__is_silent_sync = False

        if self.__is_qobject_deleted():
            return

        self.__update_state(is_full_update=True)
        self.__unlock_layers()

        logger.debug("✓ Synchronization finished")

        # Start next layer update
        NgConnectInterface.instance().synchronize_layers()

    def __disconnect_sync_task_signals(
        self, task: Optional[DetachedEditingTask] = None
    ) -> None:
        remaining_connections: List[_TaskSignalConnection] = []
        for connection in self.__sync_task_signal_connections:
            if task is not None and connection.task is not task:
                remaining_connections.append(connection)
                continue

            self.__safe_disconnect(connection.signal, connection.slot)

        self.__sync_task_signal_connections = remaining_connections

    def __safe_disconnect(
        self, signal: Any, slot: Callable[..., None]
    ) -> None:
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def __on_destroyed(self, *_: object) -> None:
        self.__is_destroyed = True
        self.__disconnect_sync_task_signals()
        self.__sync_task = None

    def __is_qobject_deleted(self) -> bool:
        if self.__is_destroyed:
            return True

        try:
            return sip.isdeleted(self)
        except RuntimeError:
            return True

    def __emit_state_changed(self) -> None:
        if self.__is_qobject_deleted():
            return

        self.state_changed.emit(self.__state)

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

    def __refresh_indicator_presenter(self, *_: object) -> None:
        if self.__indicator_presenter is None:
            return

        self.__indicator_presenter.refresh()

    def __property(self, name: str) -> None:
        for detached_layer in self.__detached_layers.values():
            custom_property = detached_layer.qgs_layer.customProperty(name)
            if custom_property is not None:
                return custom_property
        return None

    def __set_property(self, name: str, value: Any) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.setCustomProperty(name, value)

    def __apply_label_attribute(self) -> None:
        metadata = utils.container_metadata(self.path)
        label_field = metadata.fields.label_field
        if label_field is None:
            return
        for detached_layer in self.__detached_layers.values():
            detached_layer.qgs_layer.setDisplayExpression(
                f'"{label_field.keyname}"'
            )

    def __apply_aliases(self) -> None:
        for detached_layer in self.__detached_layers.values():
            for field in self.metadata.fields:
                detached_layer.qgs_layer.setFieldAlias(
                    field.attribute, field.display_name
                )

    def __apply_required_constraints(self) -> None:
        for detached_layer in self.__detached_layers.values():
            detached_layer.update_required_constraints()

    def __fix_fid_widget(self) -> None:
        for detached_layer in self.__detached_layers.values():
            # Fix for old QGIS versions. If widget is range data could be
            # corrupted
            setup = QgsEditorWidgetSetup("", {})
            fid_field = detached_layer.qgs_layer.primaryKeyAttributes()[0]
            detached_layer.qgs_layer.setEditorWidgetSetup(fid_field, setup)

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

    def __process_error(
        self,
        error: Union[NgConnectWarning, NgConnectError],
        *,
        show_error: bool = True,
    ) -> None:
        self.__state = DetachedLayerState.Error
        self.__versioning_state = VersioningSynchronizationState.Error
        self.__additional_data_fetch_date = None

        error.add_diagnostic_context(
            "detached_container_path",
            f"Container path: {self.path}",
        )
        if self.metadata is not None:
            if not error.has_user_context("detached_layer"):
                layer_name = self.metadata.layer_name
                layer_context = self.tr(
                    'Affected layer: "{layer_name}".'
                ).format(layer_name=layer_name)
                error.add_user_context(layer_context, key="detached_layer")

            error.add_diagnostic_context(
                "detached_layer",
                f"Layer: {self.metadata}",
            )

        if self.__is_network_error(error):
            if self.__additional_data_fetch_date is None:
                self.__is_edit_allowed = True
                self.__unlock_layers()

            if self.__is_silent_sync:
                logger.debug("Resync attempt failed")
                return
        elif error.code == ErrorCode.ValueFormatError or (
            isinstance(error.__cause__, (NgConnectError, NgConnectWarning))
            and error.__cause__.code == ErrorCode.ValueFormatError
        ):
            self.__is_edit_allowed = True
            self.__unlock_layers()
        else:
            self.__is_edit_allowed = False
            self.__lock_layers()

        self.__error = error

        if error.code in _RESET_REQUIRED_ERROR_CODES:
            error.add_action(self.tr("Reset layer"), self.__request_reset)

        if show_error:
            NgConnectInterface.instance().notifier.display_exception(error)

    def __request_reset(self) -> None:
        confirm_reset_container(self, iface.mainWindow())

    def __check_structure(self) -> None:
        container_fields_name = set()
        with closing(make_connection(self.__path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            container_fields_name = set(
                row[0]
                for row in cursor.execute(
                    f"""
                    SELECT name
                    FROM pragma_table_info({wrap_sql_value(self.metadata.table_name)})
                    """
                )
                if row[0]
                not in (self.metadata.fid_field, self.metadata.geom_field)
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
        self.__lock_layers()

    @pyqtSlot()
    def __on_settings_changed(self) -> None:
        old_connection_id = self.__metadata.connection_id
        self.__update_state(is_full_update=True)
        is_connection_changed = (
            old_connection_id != self.__metadata.connection_id
        )
        self.__update_layers_properties()
        if is_connection_changed or self.__metadata.is_auto_sync_enabled:
            self.synchronize(is_manual=True)

    def __process_delta_and_resolve_conflicts(
        self, fetch_delta_task: FetchDeltaTask
    ) -> Sequence[VersioningAction]:
        if len(fetch_delta_task.delta) == 0:
            return []

        self.__versioning_state = (
            VersioningSynchronizationState.ConflictDetection
        )

        # Check conflicts
        context = DetachedContainerContext(self.path, self.metadata)
        local_changes = ChangesExtractor(context).extract_all_changes()

        conflict_detector = ConflictsDetector()
        conflicts = conflict_detector.detect(
            local_changes,
            fetch_delta_task.delta,
        )
        if len(conflicts) == 0:
            return fetch_delta_task.delta

        self.__versioning_state = (
            VersioningSynchronizationState.ConflictSolving
        )

        auto_resolution = ConflictsAutoResolver().resolve(conflicts)
        manual_resolutions = []
        if len(auto_resolution.remaining_conflicts) > 0:
            dialog = ResolvingDialog(
                context, auto_resolution.remaining_conflicts
            )
            result = dialog.exec()

            if result != ResolvingDialog.DialogCode.Accepted:
                raise SynchronizationError(
                    "Resolving cancelled", code=ErrorCode.ConflictsNotResolved
                )

            manual_resolutions = dialog.resolutions

        all_resolutions = (
            auto_resolution.resolved_conflicts + manual_resolutions
        )

        applier = ConflictsResolutionApplier(context)
        status, updated_delta = applier.apply(
            all_resolutions, fetch_delta_task.delta
        )

        if status != ConflictsResolutionApplier.Status.Resolved:
            raise SynchronizationError("Not all conflicts were solved")

        self.__update_state(is_full_update=True)

        return updated_delta

    def __reset_error(self) -> None:
        if self.__error is None or self.__is_silent_sync:
            return

        NgConnectInterface.instance().notifier.dismiss_message(
            self.__error.error_id
        )
        self.__error = None

    def __record_sync_error(self, error: Exception) -> None:
        if self.__is_network_error(error):
            self.__network_error_count += 1
            return

        self.__reset_network_error_count()

    def __reset_network_error_count(self) -> None:
        self.__network_error_count = 0

    def __is_network_error(self, error: Optional[Exception]) -> bool:
        if error is None:
            return False

        if isinstance(error, NgwError):
            return error.is_network_problem

        if isinstance(error.__cause__, NGWError):
            return True

        return (
            isinstance(error.__cause__, NgwError)
            and error.__cause__.is_network_problem
        )
