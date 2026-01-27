"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2014-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from typing import Tuple

from qgis.core import QgsApplication, QgsProviderRegistry

from nextgis_connect.exceptions import ErrorCode, NgwError

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
        if len(connection_info) == 0:
            raise NgwError(
                "Can't get connection params", code=ErrorCode.PermissionsError
            )

        layer_params = self._json.get(self.type_id, {})

        layers = layer_params.get("wmslayers")
        if layers is None or len(layers) == 0:
            user_message = QgsApplication.translate(
                "Utils",
                "The WMS layer resource is not connected to any layers",
            )
            raise NgwError(
                "WMS layers list is empty",
                user_message=user_message,
                code=ErrorCode.InvalidResource,
            )

        provider_regstry = QgsProviderRegistry.instance()
        assert provider_regstry is not None
        wms_metadata = provider_regstry.providerMetadata("wms")
        assert wms_metadata is not None
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
        url = wms_metadata.encodeUri(uri_params)
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
