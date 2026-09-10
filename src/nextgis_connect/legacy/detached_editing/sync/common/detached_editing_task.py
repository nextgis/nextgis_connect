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

from contextlib import closing
from pathlib import Path
from typing import Optional, cast

from qgis.core import QgsApplication, QgsTask

from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerContext,
    DetachedContainerMetaData,
    container_changes,
    container_metadata,
    make_connection,
)
from nextgis_connect.legacy.ngw.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.resources.ngw_fields import NgwFields
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import parse_version
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    ErrorCode,
    NgConnectError,
    NgwError,
    SynchronizationError,
    default_user_message,
)
from nextgis_connect.platform.qgis.utils import wrap_sql_value
from nextgis_connect.platform.tasks import NgConnectTask


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
            self._context = DetachedContainerContext(
                container_path, self._metadata
            )
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

    def _prepare_error(self, error: Exception) -> Exception:
        """Add detached layer context to task errors.

        :param error: Original task error.
        :return: Error containing layer diagnostics when available.
        """
        error = super()._prepare_error(error)
        if not isinstance(error, NgConnectError):
            return error

        error.add_diagnostic_context(
            "detached_container_path",
            f"Container path: {self._container_path}",
        )
        if not hasattr(self, "_metadata"):
            return error

        layer_name = self._metadata.layer_name
        if error.is_network_problem:
            user_message = QgsApplication.translate(
                "DetachedEditingTask",
                'Could not synchronize layer "{layer_name}" because of a network problem. Check your internet connection and try again.',
            ).format(layer_name=layer_name)
            error.set_user_message(user_message)
        elif error.is_server_unavailable:
            user_message = QgsApplication.translate(
                "DetachedEditingTask",
                'The server is temporarily unavailable. Layer "{layer_name}" could not be synchronized. Please try again later.',
            ).format(layer_name=layer_name)
            error.set_user_message(user_message)
        elif (
            isinstance(error, SynchronizationError)
            and error.code == ErrorCode.SynchronizationError
        ):
            user_message = QgsApplication.translate(
                "DetachedEditingTask",
                'Could not synchronize layer "{layer_name}".',
            ).format(layer_name=layer_name)
            error.set_user_message(user_message)
        else:
            layer_context = QgsApplication.translate(
                "DetachedEditingTask",
                'Affected layer: "{layer_name}".',
            ).format(layer_name=layer_name)
            error.add_user_context(layer_context, key="detached_layer")

        error.mark_user_context("detached_layer")
        error.add_diagnostic_context(
            "detached_layer",
            f"Layer: {self._metadata}",
        )
        return error

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
        if not self._metadata.is_schema_complete:
            raise ContainerError(code=ErrorCode.ContainerVersionIsOutdated)

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

        if not self._is_fields_compatible(ngw_layer.fields):
            message = "Fields changed in NGW"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.fields}")
            error.add_note(f"Remote: {ngw_layer.fields}")
            raise error

        if self._is_container_fields_changed():
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

    def _is_fields_compatible(self, rhs: NgwFields) -> bool:
        return self._metadata.fields.is_compatible(
            rhs,
            skip_fields=self._metadata.fid_field,
            compare_required=False,
        )

    def _is_container_fields_changed(self) -> bool:
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
