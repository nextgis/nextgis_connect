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

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import List, Optional, Tuple

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QDir, QObject, QTimer, pyqtSignal

from nextgis_connect.legacy.detached_editing.container.cache_lifecycle import (
    CachedDetachedContainerLifecycle,
)
from nextgis_connect.legacy.detached_editing.container.container_factory import (
    DetachedContainerFactory,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
    is_ngw_container,
)
from nextgis_connect.legacy.ngw.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.storage.path_resolver import StoragePathResolver


class DetachedEditingPathPreprocessor(QObject):
    error_occurred = pyqtSignal(Exception)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        container_lifecycle: Optional[CachedDetachedContainerLifecycle] = None,
    ) -> None:
        super().__init__(parent)
        self._container_lifecycle = (
            container_lifecycle or CachedDetachedContainerLifecycle()
        )

    def __call__(self, old_source: str) -> str:
        new_source = old_source

        try:
            new_source = self._fix_path_or_create_container(old_source)
        except Exception:
            logger.exception("An error occurred while path preprocessing")
            self._emit_error(
                Exception("An error occurred while path preprocessing")
            )

        if old_source != new_source:
            logger.debug(f"Fixed source: {old_source} -> {new_source}")

        return new_source

    def _fix_path_or_create_container(self, old_source: str) -> str:
        source_parts = old_source.split("|")
        source_path_str = source_parts[0]
        source_layer_name = source_parts[1] if len(source_parts) > 1 else None

        if not source_path_str.endswith(".gpkg"):
            return old_source

        source_path = (
            PureWindowsPath(source_path_str)
            if "\\" in source_path_str or ":" in source_path_str
            else PurePosixPath(source_path_str)
        )
        domain_uuid, resource_id = self._extract_domain_uuid_and_resource_id(
            source_path
        )
        if domain_uuid is None or resource_id is None:
            # Currently supported only layers in cache folder
            return old_source

        cached_layer_path = self._cached_layer_path(domain_uuid, resource_id)

        if not cached_layer_path.exists():
            logger.warning(f"Found deleted container: {cached_layer_path}")
            is_created = self._find_connection_and_create_container(
                domain_uuid, resource_id, cached_layer_path
            )
            if not is_created:
                return old_source
        elif not is_ngw_container(cached_layer_path):
            return old_source
        elif self._needs_reconciliation(
            domain_uuid, resource_id, cached_layer_path
        ):
            is_reconciled = self._find_connection_and_reconcile_container(
                domain_uuid, resource_id, cached_layer_path
            )
            if not is_reconciled:
                return old_source

        layer_path = (
            str(cached_layer_path)
            if source_path.is_absolute()
            else QDir(QgsProject.instance().absolutePath()).relativeFilePath(
                str(cached_layer_path)
            )
        )
        layer_name = (
            "|" + detached_layer_uri(cached_layer_path).split("|")[1]
            if source_layer_name is not None
            else ""
        )
        return f"{layer_path}{layer_name}"

    def _emit_error(self, error: Exception) -> None:
        QTimer.singleShot(0, lambda: self.error_occurred.emit(error))

    def _extract_domain_uuid_and_resource_id(
        self, source_path: PurePath
    ) -> Tuple[Optional[str], Optional[int]]:
        if len(source_path.parts) < 2:
            return None, None

        file_candidate = source_path.parts[-1]
        uuid_pattern = re.compile(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
            re.IGNORECASE,
        )
        file_pattern = re.compile(r"^\d+\.gpkg$")

        if not file_pattern.match(file_candidate):
            return None, None

        legacy_uuid = source_path.parts[-2]
        if uuid_pattern.match(legacy_uuid):
            return legacy_uuid, int(source_path.stem)

        if not self._is_indexed_storage_path(source_path):
            return None, None

        if len(source_path.parts) >= 4:
            indexed_uuid = source_path.parts[-4]
            if uuid_pattern.match(indexed_uuid):
                return indexed_uuid, int(source_path.stem)

        layer_key = DetachedStorageServiceFactory.create().layer_key_for_path(
            source_path
        )
        if layer_key is None:
            return None, None
        return layer_key.instance_uuid, layer_key.resource_id

    def _is_indexed_storage_path(self, source_path: PurePath) -> bool:
        return StoragePathResolver.is_indexed_storage_path(source_path)

    def _cached_layer_path(self, domain_uuid: str, resource_id: int) -> Path:
        return DetachedStorageServiceFactory.create().container_path(
            domain_uuid, resource_id
        )

    def _find_connection_and_create_container(
        self, domain_uuid: str, resource_id: int, cached_layer_path: Path
    ) -> bool:
        connection_id = self._best_connection(domain_uuid, resource_id)
        if connection_id is None:
            logger.warning("There are no suitable connections")
            return False

        self._create_empty_container(
            domain_uuid,
            connection_id,
            resource_id,
            cached_layer_path,
        )

        return True

    def _needs_reconciliation(
        self,
        domain_uuid: str,
        resource_id: int,
        cached_layer_path: Path,
    ) -> bool:
        try:
            metadata = container_metadata(cached_layer_path)
        except Exception:
            logger.exception("Could not read detached container metadata")
            return False

        if metadata.resource_id != resource_id:
            return not metadata.has_changes

        if metadata.instance_id != domain_uuid:
            return not metadata.has_changes

        connections_manager = NgwConnectionsManager()
        connection_is_missing = (
            connections_manager.connection(metadata.connection_id) is None
        )
        if self._container_lifecycle.is_outdated(metadata):
            return not metadata.has_changes or connection_is_missing

        return connection_is_missing

    def _find_connection_and_reconcile_container(
        self, domain_uuid: str, resource_id: int, cached_layer_path: Path
    ) -> bool:
        connection_id = self._best_connection(domain_uuid, resource_id)
        if connection_id is None:
            logger.warning("There are no suitable connections")
            return False

        connection = NgwConnectionsManager().connection(connection_id)
        if connection is None:
            return False

        ngw_connection = QgsNgwConnection(connection_id)
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        return self._container_lifecycle.reconcile(
            cached_layer_path,
            ngw_layer,
            connection,
        )

    def _best_connection(
        self, domain_uuid: str, resource_id: int
    ) -> Optional[str]:
        connections_id = self._connections(domain_uuid)
        if len(connections_id) == 0:
            return None

        logger.debug(f"Found {len(connections_id)} suitable connections")
        permission_url = f"/api/resource/{resource_id}/permission"

        best_connection = None

        for connection_id in connections_id:
            logger.debug(f"Check connection {connection_id}")

            ngw_connection = QgsNgwConnection(connection_id)
            permissions = ngw_connection.get(permission_url)

            is_read_allowed = permissions["data"]["read"]
            is_write_allowed = permissions["data"]["write"]

            if is_write_allowed:
                best_connection = connection_id
                break

            if is_read_allowed and best_connection is None:
                best_connection = connection_id

        return best_connection

    def _connections(self, domain_uuid: str) -> List[str]:
        connections_manager = NgwConnectionsManager()
        return [
            connection.id
            for connection in connections_manager.connections
            if connection.domain_uuid == domain_uuid
            or domain_uuid in connection.old_connection_ids
        ]

    def _create_empty_container(
        self,
        domain_uuid: str,
        connection_id: str,
        resource_id: int,
        cached_layer_path: Path,
    ) -> None:
        ngw_connection = QgsNgwConnection(connection_id)
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        detached_factory = DetachedContainerFactory()
        storage_service = DetachedStorageServiceFactory.create()
        cached_layer_path.parent.mkdir(exist_ok=True, parents=True)
        try:
            detached_factory.create_initial_container(
                ngw_layer,
                cached_layer_path,
            )
            metadata = container_metadata(cached_layer_path)
            storage_service.register_detached_container(
                metadata.instance_id,
                metadata.resource_id,
                connection_id=metadata.connection_id,
                container_path=cached_layer_path,
            )
        except Exception:
            storage_service.remove_layer_container_cache(
                domain_uuid,
                resource_id,
            )
            raise
