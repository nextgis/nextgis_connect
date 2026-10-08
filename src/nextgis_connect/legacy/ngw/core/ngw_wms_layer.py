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

from typing import Tuple

from qgis.core import QgsApplication

from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgwError,
    ResourcePermissionError,
)
from nextgis_connect.platform.qgis.wms_uri import QgisWmsUriFactory

from .ngw_resource import NGWResource
from .ngw_wms_connection import NGWWmsConnection


class NGWWmsLayer(NGWResource):
    type_id = "wmsclient_layer"
    type_title = "NGW WMS Layer"

    @property
    def service_resource_id(self) -> int:
        return self._json[self.type_id]["connection"]["id"]

    def layer_params(
        self, wms_connection: NGWWmsConnection
    ) -> Tuple[str, str, str]:
        connection_info = wms_connection.connection_info
        if len(connection_info) == 0 or not connection_info.get("url"):
            raise ResourcePermissionError(
                "Can't get connection params",
                resource_url=wms_connection.get_absolute_url(),
            )

        layer_params = self._json.get(self.type_id, {})

        layers = layer_params.get("wmslayers")
        if layers is None or len(layers) == 0:
            # fmt: off
            user_message = QgsApplication.translate(
                "Utils",
                "The WMS layer resource is not connected to any layers"
            )
            # fmt: on
            raise NgwError(
                "WMS layers list is empty",
                user_message=user_message,
                code=ErrorCode.InvalidResource,
            )

        uri_params = {
            "format": layer_params["imgformat"],
            "crs": f"EPSG:{layer_params['srs']['id']}",
            "url": connection_info["url"],
        }
        if "username" in connection_info and "password" in connection_info:
            uri_params.update(
                {
                    "username": connection_info["username"],
                    "password": connection_info["password"],
                }
            )
        url = QgisWmsUriFactory.create(uri_params)
        for layer in layers.split(","):
            url += f"&layers={layer}&styles"

        return (url, self.display_name, "wms")

    @classmethod
    def create_in_group(
        cls,
        name,
        ngw_group_resource,
        ngw_wms_connection_id,
        wms_layers,
        wms_format,
    ):
        connection = ngw_group_resource.res_factory.connection
        url = ngw_group_resource.get_api_collection_url()

        params = dict(
            resource=dict(
                cls=cls.type_id,
                display_name=name,
                parent=dict(id=ngw_group_resource.resource_id),
            )
        )

        params[cls.type_id] = dict(
            connection=dict(id=ngw_wms_connection_id),
            wmslayers=",".join(wms_layers),
            imgformat=wms_format,
            srs=dict(id=3857),
        )

        result = connection.post(url, params=params)

        ngw_resource = cls(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource
