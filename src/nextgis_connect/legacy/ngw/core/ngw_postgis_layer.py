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

from typing import Any, Dict, Tuple

from qgis.core import QgsDataSourceUri, QgsWkbTypes

from nextgis_connect.legacy.ngw.core.ngw_resource import NGWResource
from nextgis_connect.platform.qgis.errors import ErrorCode, NgwError

from .ngw_abstract_vector_resource import NGWAbstractVectorResource

POSTGIS_DRIVER = "postgres"
DEFAULT_POSTGRES_PORT = 5432


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
        layer_info = self._json[self.type_id]
        if len(connection_info) == 0 or len(layer_info) == 0:
            raise NgwError(
                "Can't get connection params", code=ErrorCode.PermissionsError
            )

        port = connection_info.get("port")
        if port is None or len(str(port).strip()) == 0:
            port = DEFAULT_POSTGRES_PORT

        username = connection_info.get("username", "")
        password = connection_info.get("password", "")
        if not username or not password:
            username = password = ""  # nosec B105

        uri = QgsDataSourceUri()
        uri.setConnection(
            connection_info["hostname"],
            str(port),
            connection_info["database"],
            username,
            password,
            QgsDataSourceUri.decodeSslMode(
                connection_info.get("sslmode") or "prefer"
            ),
        )
        uri.setDataSource(
            layer_info["schema"],
            layer_info["table"],
            layer_info.get("column_geom", ""),
            "",
            layer_info["column_id"],
        )
        wkb_type = self.wkb_geom_type
        if QgsWkbTypes.hasZ(wkb_type):
            wkb_type = QgsWkbTypes.addZ(QgsWkbTypes.dropZ(wkb_type))
        uri.setWkbType(wkb_type)

        geometry_srid = layer_info.get("geometry_srid")
        if geometry_srid is not None:
            uri.setSrid(str(geometry_srid))

        return uri.uri(False), self.display_name, POSTGIS_DRIVER
