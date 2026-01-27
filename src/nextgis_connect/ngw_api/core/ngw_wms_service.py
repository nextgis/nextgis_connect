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

from qgis.core import QgsApplication, QgsProviderRegistry

from nextgis_connect.exceptions import ErrorCode, NgwError
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource, dict_to_object, list_dict_to_list_object


class NGWWmsService(NGWResource):
    type_id = "wmsserver_service"
    type_title = "NGW WMS Service"

    def _construct(self):
        super()._construct()

        self.wms = dict_to_object(self._json[self.type_id])
        if hasattr(self.wms, "layers"):
            self.layers = list_dict_to_list_object(self.wms.layers)
        else:
            self.layers = []

    def params_for_layer(self, layer):
        if len(self.layers) == 0:
            user_message = QgsApplication.translate(
                "Utils",
                "The WMS service does not contain any layers",
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
            "format": "image/png",
            "crs": "EPSG:3857",
            "url": f"{self.get_absolute_api_url()}/wms",
            "layers": layer.keyname,
            "styles": "",
        }

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        connection.update_uri_config(uri_params)

        url = wms_metadata.encodeUri(uri_params)
        return (url, layer.display_name, "wms")

    @classmethod
    def create_in_group(cls, name, ngw_group_resource, ngw_layers_with_style):
        connection = ngw_group_resource.res_factory.connection
        url = ngw_group_resource.get_api_collection_url()

        params_layers = []
        for ngw_layer, ngw_style_id in ngw_layers_with_style:
            params_layer = dict(
                display_name=ngw_layer.display_name,
                keyname=f"ngw_id_{ngw_style_id}",
                resource_id=ngw_style_id,
                min_scale_denom=None,
                max_scale_denom=None,
            )
            params_layers.append(params_layer)

        params = dict(
            resource=dict(
                cls=cls.type_id,
                display_name=name,
                parent=dict(id=ngw_group_resource.resource_id),
            )
        )

        params[cls.type_id] = dict(layers=params_layers)

        result = connection.post(url, params=params)

        ngw_resource = cls(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource
