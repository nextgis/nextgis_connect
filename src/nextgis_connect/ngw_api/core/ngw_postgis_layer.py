from typing import Any, Dict, Tuple

from qgis.core import QgsDataSourceUri

from nextgis_connect.exceptions import ErrorCode, NgwError
from nextgis_connect.ngw_api.core.ngw_resource import NGWResource

from .ngw_abstract_vector_resource import NGWAbstractVectorResource


class NGWPostgisConnection(NGWResource):
    type_id = "postgis_connection"
    type_title = "NGW PostGIS Connection"

    @property
    def connection_info(self) -> Dict[str, Any]:
        return self._json[self.type_id]


class NGWPostgisLayer(NGWAbstractVectorResource):
    type_id = "postgis_layer"

    @property
    def service_resource_id(self) -> int:
        return self._json[self.type_id]["connection"]["id"]

    def layer_params(
        self, postgis_connection: NGWPostgisConnection
    ) -> Tuple[str, str, str]:
        connection_info = postgis_connection.connection_info
        if len(connection_info) == 0:
            raise NgwError(
                "Can't get connection params", code=ErrorCode.PermissionsError
            )

        uri = QgsDataSourceUri()
        uri.setConnection(
            connection_info["hostname"],
            str(connection_info["port"]),
            connection_info["database"],
            connection_info["username"],
            connection_info["password"],
        )

        layer_info = self._json[self.type_id]
        uri.setDataSource(
            layer_info["schema"],
            layer_info["table"],
            layer_info["column_geom"],
            None,
            layer_info["column_id"],
        )

        return uri.uri(False), self.display_name, "postgres"
