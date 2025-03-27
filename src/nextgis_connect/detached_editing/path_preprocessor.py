from pathlib import Path
from typing import List, Optional

from qgis.core import QgsProject

from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
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
    def __call__(self, path: str) -> str:
        try:
            self.__create_container_if_needed(path)
        except Exception:
            logger.exception("An error occurred while path preprocessing")

        return path

    def __create_container_if_needed(self, path: str) -> None:
        path = path.split("|")[0]
        if not path.endswith(".gpkg"):
            return

        cache_directory = Path(NgConnectCacheManager().cache_directory)
        layer_path = self.__absolute_layer_path(path)

        # Currently supported only layers in cache folder
        if layer_path.exists() or cache_directory not in layer_path.parents:
            return

        logger.warning(f"Found deleted container: {layer_path}")

        connections_id = self.__connections(layer_path)
        resource_id = self.__resource_id(layer_path)

        if len(connections_id) == 0 or resource_id is None:
            return

        logger.debug(f"Found {len(connections_id)} suitable connections")

        connection_id = self.__best_connection(connections_id, resource_id)
        if connection_id is None:
            logger.warning("There are no connections with data read rights")
            return

        self.__create_empty_container(connection_id, resource_id, layer_path)

    def __absolute_layer_path(self, path: str) -> Path:
        layer_path = Path(path)

        if layer_path.is_absolute():
            return layer_path

        project = QgsProject.instance()
        return (project.absolutePath() / layer_path).resolve()

    def __connections(self, layer_path: Path) -> List[str]:
        domain_uuid = layer_path.parent.name

        result = []

        connections_manager = NgwConnectionsManager()
        for connection in connections_manager.connections:
            if connection.domain_uuid != domain_uuid:
                continue
            result.append(connection.id)

        return result

    def __resource_id(self, layer_path: Path) -> Optional[int]:
        if not layer_path.stem.isnumeric():
            return None

        return int(layer_path.stem)

    def __best_connection(
        self, connections: List[str], resource_id: int
    ) -> Optional[str]:
        permission_url = f"/api/resource/{resource_id}/permission"

        best_connection = None

        for connection_id in connections:
            logger.debug(f"Check connection {connection_id}")

            ngw_connection = QgsNgwConnection(connection_id)
            permissions = ngw_connection.get(permission_url)

            is_read_allowed = permissions["data"]["read"]
            is_write_allowed = permissions["data"]["write"]

            if is_write_allowed:
                best_connection = connection_id
                break

            if is_read_allowed:
                best_connection = connection_id

        return best_connection

    def __create_empty_container(
        self, connection_id: str, resource_id: int, layer_path: Path
    ) -> None:
        ngw_connection = QgsNgwConnection(connection_id)
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(resource_id)
        assert isinstance(ngw_layer, NGWVectorLayer)

        detached_factory = DetachedLayerFactory()
        layer_path.parent.mkdir(exist_ok=True)
        detached_factory.create_initial_container(ngw_layer, layer_path)
