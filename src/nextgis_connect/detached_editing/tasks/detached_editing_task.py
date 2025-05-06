from contextlib import closing
from pathlib import Path
from typing import Optional, cast

from qgis.core import QgsApplication, QgsTask

from nextgis_connect.compat import parse_version
from nextgis_connect.core.tasks.ng_connect_task import NgConnectTask
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_changes,
    container_metadata,
    make_connection,
)
from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgwError,
    SynchronizationError,
    default_user_message,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.resources.ngw_fields import NgwFields
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.utils import wrap_sql_value


class DetachedEditingTask(NgConnectTask):
    _container_path: Path
    _metadata: DetachedContainerMetaData

    def __init__(
        self, container_path: Path, flags: Optional[QgsTask.Flags] = None
    ) -> None:
        if flags is None:
            flags = QgsTask.Flags()
        super().__init__(flags=flags)

        self._container_path = container_path

        try:
            self._metadata = container_metadata(container_path)
            self.__check_container()

        except ContainerError as error:
            self._error = error
            return

        except Exception as error:
            message = "An error occurred during layer metadata extracting"
            logger.exception(message)
            self._error = ContainerError(message)
            self._error.__cause__ = error
            return

        description = QgsApplication.translate(
            "DetachedEditingTask", '"{layer_name}" layer synchronization'
        ).format(layer_name=self._metadata.layer_name)
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        self.__check_connection()

        if self._error is not None:
            self._error.add_note(
                f"Connection id: {self._metadata.connection_id}"
            )
            self._error.add_note(f"Resource id: {self._metadata.resource_id}")
            return False

        return True

    def _get_layer(self, ngw_connection: QgsNgwConnection) -> NGWVectorLayer:
        resource_id = self._metadata.resource_id
        resources_factory = NGWResourceFactory(ngw_connection)

        try:
            ngw_layer = cast(
                NGWVectorLayer, resources_factory.get_resource(resource_id)
            )

        except NgwError as error:
            if error.code not in (
                ErrorCode.AuthorizationError,
                ErrorCode.PermissionsError,
            ):
                raise

            user_message = (
                default_user_message(ErrorCode.SynchronizationError)
                + " "
                + error.user_message
                + "."
            )
            raise SynchronizationError(user_message=user_message) from error

        self.__check_compatibility(ngw_layer)

        return ngw_layer

    def __check_container(self) -> None:
        container_version = parse_version(self._metadata.container_version)
        supported_version = parse_version(
            NgConnectSettings().supported_container_version
        )
        if container_version < supported_version:
            raise ContainerError(code=ErrorCode.ContainerVersionIsOutdated)

    def __check_compatibility(self, ngw_layer: NGWVectorLayer) -> None:
        if self._metadata.geometry_name != ngw_layer.geom_name:
            message = "Geometry is not compatible"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.geometry_name}")
            error.add_note(f"Remote: {ngw_layer.geom_name}")
            raise error

        if not self.__is_fields_compatible(ngw_layer.fields):
            message = "Fields changed in NGW"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.fields}")
            error.add_note(f"Remote: {ngw_layer.fields}")
            raise error

        if self.__is_container_fields_changed():
            message = "Fields changed in QGIS"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            raise error

        if (
            self._metadata.is_versioning_enabled
            != ngw_layer.is_versioning_enabled
        ):
            message = "Versioning state changed"
            code = (
                ErrorCode.VersioningDisabled
                if self._metadata.is_versioning_enabled
                else ErrorCode.VersioningEnabled
            )
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.is_versioning_enabled}")
            error.add_note(f"Remote: {ngw_layer.is_versioning_enabled}")
            raise error

        if self._metadata.is_versioning_enabled:
            if self._metadata.epoch != ngw_layer.epoch:
                message = "Epoch changed"
                code = ErrorCode.EpochChanged
                error = SynchronizationError(message, code=code)
                error.add_note(f"Local: {self._metadata.epoch}")
                error.add_note(f"Remote: {ngw_layer.epoch}")
                raise error
        else:
            remote_features_count = ngw_layer.features_count

            changes = container_changes(self._container_path)
            last_sync_features_count = (
                self._metadata.features_count
                - changes.added_features_count
                + changes.removed_features_count
            )

            if last_sync_features_count != remote_features_count:
                message = "Not versioned layer content changed in NGW"
                code = ErrorCode.NotVersionedContentChanged
                error = SynchronizationError(message, code=code)
                error.add_note(f"Last sync count: {last_sync_features_count}")
                error.add_note(f"Remote count: {remote_features_count}")
                raise error

    def __is_fields_compatible(self, rhs: NgwFields) -> bool:
        return self._metadata.fields.is_compatible(
            rhs, skip_fields=self._metadata.fid_field
        )

    def __is_container_fields_changed(self) -> bool:
        container_fields_name = set()
        with closing(
            make_connection(self._container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            container_fields_name = set(
                row[1]
                for row in cursor.execute(
                    f"PRAGMA table_info({wrap_sql_value(self._metadata.table_name)})"
                )
                if row[1]
                not in (self._metadata.fid_field, self._metadata.geom_field)
            )

        return any(
            ngw_field.keyname not in container_fields_name
            for ngw_field in self._metadata.fields
        )

    def __check_connection(self) -> None:
        connection_id = self._metadata.connection_id
        connection_manager = NgwConnectionsManager()
        if not connection_manager.is_valid(connection_id):
            user_message = (
                default_user_message(ErrorCode.SynchronizationError)
                + " "
                + default_user_message(ErrorCode.InvalidConnection)
                + " "
                + QgsApplication.translate(
                    "DetachedEditingTask",
                    "Please check layer connection settings.",
                )
            )
            self._error = SynchronizationError(user_message=user_message)
            return

        connection = connection_manager.connection(connection_id)
        if self._metadata.instance_id != connection.domain_uuid:
            user_message = (
                default_user_message(ErrorCode.SynchronizationError)
                + " "
                + default_user_message(ErrorCode.DomainChanged)
                + " "
                + QgsApplication.translate(
                    "DetachedEditingTask",
                    "Please check layer connection settings.",
                )
            )
            self._error = SynchronizationError(
                code=ErrorCode.DomainChanged, user_message=user_message
            )
            return
