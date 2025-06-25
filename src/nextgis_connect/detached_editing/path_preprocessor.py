import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import List, Optional, Tuple

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QDir

from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    detached_layer_uri,
    is_ngw_container,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)


class DetachedEditingPathPreprocessor:
    def __call__(self, old_source: str) -> str:
        new_source = old_source

        try:
            new_source = self.__fix_path_or_create_container(old_source)
        except Exception:
            logger.exception("An error occurred while path preprocessing")

        if old_source != new_source:
            logger.debug(f"<b>Fixed source</b>: {old_source} -> {new_source}")

        return new_source

    def __fix_path_or_create_container(self, old_source: str) -> str:
        source_parts = old_source.split("|")
        source_path_str = source_parts[0]
        source_layer_name = source_parts[1] if len(source_parts) > 1 else None

        source_path = (
            PureWindowsPath(source_path_str)
            if "\\\\" in source_path_str
            or (len(source_path_str) > 2 and source_path_str[1] == ":")
            else PurePosixPath(source_path_str)
        )
        domain_uuid, resource_id = self.__extract_domain_uuid_and_resource_id(
            source_path
        )
        if domain_uuid is None or resource_id is None:
            # Currently supported only layers in cache folder
            return old_source

        cached_layer_path = self.__cached_layer_path(domain_uuid, resource_id)

        if not cached_layer_path.exists():
            logger.warning(f"Found deleted container: {cached_layer_path}")
            is_created = self.__find_connection_and_create_container(
                cached_layer_path
            )
            if not is_created:
                return old_source
        elif not is_ngw_container(cached_layer_path):
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

    def __extract_domain_uuid_and_resource_id(
        self, source_path: PurePath
    ) -> Tuple[Optional[str], Optional[int]]:
        if len(source_path.parts) < 2:
            return None, None

        uuid_candidate = source_path.parts[-2]
        file_candidate = source_path.parts[-1]

        uuid_pattern = re.compile(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
            re.IGNORECASE,
        )
        file_pattern = re.compile(r"^\d+\.gpkg$")

        if not uuid_pattern.match(uuid_candidate) or not file_pattern.match(
            file_candidate
        ):
            return None, None

        return uuid_candidate, int(source_path.stem)

    def __cached_layer_path(self, domain_uuid: str, resource_id: int) -> Path:
        cache_directory = Path(NgConnectCacheManager().cache_directory)
        return (
            cache_directory / domain_uuid / f"{resource_id}.gpkg"
        ).resolve()

    def __find_connection_and_create_container(
        self, cached_layer_path: Path
    ) -> bool:
        domain_uuid = cached_layer_path.parent.name
        resource_id = int(cached_layer_path.stem)

        connection_id = self.__best_connection(domain_uuid, resource_id)
        if connection_id is None:
            logger.warning("There are no suitable connections")
            return False

        self.__create_empty_container(
            connection_id, resource_id, cached_layer_path
        )

        return True

    def __best_connection(
        self, domain_uuid: str, resource_id: int
    ) -> Optional[str]:
        connections_id = self.__connections(domain_uuid)
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

    def __connections(self, domain_uuid: str) -> List[str]:
        connections_manager = NgwConnectionsManager()
        return [
            connection.id
            for connection in connections_manager.connections
            if connection.domain_uuid == domain_uuid
        ]

    def __create_empty_container(
        self, connection_id: str, resource_id: int, cached_layer_path: Path
    ) -> None:
        ngw_connection = QgsNgwConnection(connection_id)
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        detached_factory = DetachedLayerFactory()
        cached_layer_path.parent.mkdir(exist_ok=True)
        detached_factory.create_initial_container(ngw_layer, cached_layer_path)
