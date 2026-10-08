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

from typing import Any, Dict

from qgis.core import QgsApplication

from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgwError,
    ResourcePermissionError,
)
from nextgis_connect.platform.qgis.wms_uri import QgisWmsUriFactory

from .ngw_resource import NGWResource, dict_to_object, list_dict_to_list_object


class NGWWmsConnection(NGWResource):
    type_id = "wmsclient_connection"
    type_title = "NGW WMS Connection"

    def _construct(self):
        super()._construct()

        self.wms = dict_to_object(self._json[self.type_id])
        self.capcache = None
        self.layers = []
        if hasattr(self.wms, "capcache") and self.wms.capcache is not None:
            self.capcache = dict_to_object(self.wms.capcache)

        if self.capcache is not None and hasattr(self.capcache, "layers"):
            self.layers = list_dict_to_list_object(self.capcache.layers)
            for layer in self.layers:
                layer.keyname = layer.id
                layer.display_name = layer.title

    @property
    def connection_info(self) -> Dict[str, Any]:
        return self._json[self.type_id]

    def params_for_layer(self, layer):
        if len(self.layers) == 0:
            # fmt: off
            user_message = QgsApplication.translate(
                "Utils",
                "The WMS service does not contain any layers"
            )
            # fmt: on
            raise NgwError(
                "WMS layers list is empty",
                user_message=user_message,
                code=ErrorCode.InvalidResource,
            )

        if (
            not hasattr(self, "wms")
            or self.wms is None
            or not hasattr(self.wms, "url")
            or self.wms.url is None
        ):
            raise ResourcePermissionError(
                "Can't get connection params",
                resource_url=self.get_absolute_url(),
            )

        uri_params = {
            "format": "image/png",
            "crs": "EPSG:3857",
            "url": self.wms.url,
            "layers": layer.keyname,
            "styles": "",
        }
        if self.wms.username is not None and self.wms.password is not None:
            uri_params["username"] = self.wms.username
            uri_params["password"] = self.wms.password

        url = QgisWmsUriFactory.create(uri_params)
        return (url, layer.display_name, "wms")

    @classmethod
    def create_in_group(
        cls,
        name,
        ngw_group_resource,
        wms_url,
        version="1.1.1",
        auth=(None, None),
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
            url=wms_url,
            username=auth[0],
            password=auth[1],
            version=version,
            capcache="query",
        )

        result = connection.post(url, params=params)

        ngw_resource = cls(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource
