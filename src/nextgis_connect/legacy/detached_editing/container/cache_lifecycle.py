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
import tempfile
from pathlib import Path
from typing import Optional

from nextgis_connect.legacy.detached_editing.container.container_factory import (
    DetachedContainerFactory,
)
from nextgis_connect.legacy.detached_editing.container.migrations import (
    ContainerMigrator,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    make_connection,
)
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import parse_version


class CachedDetachedContainerLifecycle:
    def __init__(
        self,
        container_factory: Optional[DetachedContainerFactory] = None,
        settings: Optional[NgConnectSettings] = None,
    ) -> None:
        self._container_factory = (
            container_factory or DetachedContainerFactory()
        )
        self._settings = settings or NgConnectSettings()

    def reconcile(
        self,
        container_path: Path,
        ngw_layer: NGWVectorLayer,
        connection: NgwConnection,
    ) -> bool:
        try:
            metadata = container_metadata(container_path)
        except Exception:
            logger.exception("Could not read detached container metadata")
            return self.replace_with_empty_container(
                container_path,
                ngw_layer,
            )

        if not self._is_same_remote_layer(metadata, ngw_layer, connection):
            if metadata.has_changes:
                logger.warning(
                    "Detached container points to another remote layer and "
                    f"has local changes: {container_path}"
                )
                return False

            return self.replace_with_empty_container(
                container_path,
                ngw_layer,
            )

        try:
            ContainerMigrator().migrate(container_path)
            metadata = container_metadata(container_path)
        except Exception:
            logger.exception("Could not migrate detached container")
            return False

        if self.is_outdated(metadata):
            if metadata.has_changes:
                logger.warning(
                    "Found outdated detached container with local changes: "
                    f"{container_path}"
                )
            else:
                logger.warning(
                    "Found outdated detached container without local changes: "
                    f"{container_path}"
                )
                return self.replace_with_empty_container(
                    container_path,
                    ngw_layer,
                )

        self._update_connection_id_if_needed(
            container_path,
            metadata,
            connection,
        )
        DetachedStorageServiceFactory.create().register_detached_container(
            connection.domain_uuid,
            ngw_layer.resource_id,
            connection_id=connection.id,
            container_path=container_path,
        )
        return True

    def replace_with_empty_container(
        self,
        container_path: Path,
        ngw_layer: NGWVectorLayer,
    ) -> bool:
        temp_path = None
        container_path.parent.mkdir(exist_ok=True, parents=True)

        try:
            temp_file_fd, temp_file_path = tempfile.mkstemp(
                suffix=".gpkg",
                dir=container_path.parent,
            )
            os.close(temp_file_fd)
            temp_path = Path(temp_file_path)
            temp_path.unlink(missing_ok=True)

            self._container_factory.create_initial_container(
                ngw_layer,
                temp_path,
            )

            for service_file in container_path.parent.glob(
                f"{container_path.name}-*"
            ):
                service_file.unlink(missing_ok=True)

            temp_path.replace(container_path)
            metadata = container_metadata(container_path)
            DetachedStorageServiceFactory.create().register_detached_container(
                metadata.instance_id,
                metadata.resource_id,
                connection_id=metadata.connection_id,
                container_path=container_path,
            )

        except Exception:
            logger.exception("Could not replace detached container")
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return False

        return True

    def is_outdated(
        self,
        metadata: DetachedContainerMetaData,
    ) -> bool:
        if not metadata.is_schema_complete:
            return True

        container_version = parse_version(metadata.container_version)
        supported_version = parse_version(
            self._settings.supported_container_version
        )
        return container_version < supported_version

    def _is_same_remote_layer(
        self,
        metadata: DetachedContainerMetaData,
        ngw_layer: NGWVectorLayer,
        connection: NgwConnection,
    ) -> bool:
        return (
            metadata.instance_id == connection.domain_uuid
            and metadata.resource_id == ngw_layer.resource_id
        )

    def _update_connection_id_if_needed(
        self,
        container_path: Path,
        metadata: DetachedContainerMetaData,
        connection: NgwConnection,
    ) -> None:
        if (
            metadata.connection_id == connection.id
            and metadata.instance_id == connection.domain_uuid
        ):
            return

        logger.warning(
            "Update detached container connection metadata: "
            f"{metadata.connection_id} -> {connection.id}"
        )
        with make_connection(container_path) as db_connection:
            cursor = db_connection.cursor()
            cursor.execute(
                """
                UPDATE ngw_metadata
                SET connection_id = ?, instance_id = ?
                """,
                (connection.id, connection.domain_uuid),
            )
            db_connection.commit()
