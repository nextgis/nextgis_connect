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

import json
from typing import Tuple

from qgis.core import QgsProviderRegistry

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource


class NGWBaseMap(NGWResource):
    type_id = "basemap_layer"
    type_title = "NGW Base Map layer"

    @property
    def layer_params(self) -> Tuple[str, str, str]:
        resource_json = self._json[self.type_id]

        params = {"type": "xyz"}
        qms = resource_json.get("qms")
        if qms is None:
            params["url"] = resource_json["url"]
        else:
            decoded_qms = json.loads(qms)
            params["url"] = decoded_qms["url"]
            params["zmin"] = decoded_qms.get("z_min")
            params["zmax"] = decoded_qms.get("z_max")
            if "epsg" in decoded_qms:
                params["crs"] = f"EPSG:{decoded_qms['epsg']}"

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        assert connection is not None
        if (
            params["url"].startswith(connection.url)
            and connection.auth_config_id is not None
        ):
            params["authcfg"] = connection.auth_config_id

        params = {
            key: value for key, value in params.items() if value is not None
        }

        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            "wms"
        )

        return provider_metadata.encodeUri(params), self.display_name, "wms"

    @classmethod
    def create_in_group(
        cls, name, ngw_group_resource, base_map_url, qms_ext_settings=None
    ):
        connection = ngw_group_resource.res_factory.connection
        params = dict(
            resource=dict(
                cls=cls.type_id,
                display_name=name,
                parent=dict(id=ngw_group_resource.resource_id),
            )
        )

        qms_parameters = None
        if qms_ext_settings is not None:
            qms_parameters = qms_ext_settings.toJSON()

        params[cls.type_id] = dict(url=base_map_url, qms=qms_parameters)
        result = connection.post(
            ngw_group_resource.get_api_collection_url(), params=params
        )

        ngw_resource = cls(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource


class NGWBaseMapExtSettings:
    def __init__(self, url, epsg, z_min, z_max, y_origin_top):
        self.url = url
        self.epsg = int(epsg)
        self.z_min = z_min
        self.z_max = z_max
        self.y_origin_top = y_origin_top

    def toJSON(self):
        d = {}
        if self.url is None:
            return None
        d["url"] = self.url
        if self.epsg is None:
            return None
        d["epsg"] = self.epsg
        if self.z_min is not None:
            d["z_min"] = self.z_min
        if self.z_max is not None:
            d["z_max"] = self.z_max
        if self.y_origin_top is not None:
            d["y_origin_top"] = self.y_origin_top

        return json.dumps(d)
