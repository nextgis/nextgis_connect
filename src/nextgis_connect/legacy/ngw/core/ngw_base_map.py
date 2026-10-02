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

import json
from typing import Dict, Optional, Tuple

from qgis.core import QgsProviderRegistry

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
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
        if isinstance(qms, str):
            decoded_qms = json.loads(qms)
            params["url"] = decoded_qms["url"]
            params["zmin"] = decoded_qms.get("z_min")
            params["zmax"] = decoded_qms.get("z_max")
            if "epsg" in decoded_qms:
                params["crs"] = f"EPSG:{decoded_qms['epsg']}"
        else:
            params["url"] = resource_json["url"]
            params["zmin"] = resource_json.get("z_min")
            params["zmax"] = resource_json.get("z_max")
            if resource_json.get("epsg") is not None:
                params["crs"] = f"EPSG:{resource_json['epsg']}"

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
        cls,
        name,
        ngw_group_resource,
        base_map_url,
        qms_ext_settings=None,
        use_basemap_qms_object=False,
    ):
        connection = ngw_group_resource.res_factory.connection
        params = dict(
            resource=dict(
                cls=cls.type_id,
                display_name=name,
                parent=dict(id=ngw_group_resource.resource_id),
            )
        )

        basemap_params = dict(url=base_map_url)
        if use_basemap_qms_object:
            basemap_params["type"] = "tms"
            if qms_ext_settings is not None:
                basemap_params["url"] = (
                    qms_ext_settings.encode_y_origin_in_url(base_map_url)
                )
                basemap_params.update(qms_ext_settings.to_ngw_basemap_params())
        else:
            qms_parameters = None
            if qms_ext_settings is not None:
                qms_parameters = qms_ext_settings.toJSON()
            basemap_params["qms"] = qms_parameters

        params[cls.type_id] = basemap_params
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
        self.z_min = int(z_min) if z_min is not None else None
        self.z_max = int(z_max) if z_max is not None else None
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

    def to_ngw_basemap_params(self) -> Dict[str, Optional[int]]:
        """Return fields for the NextGIS Web basemap API."""
        return {
            "epsg": self.epsg,
            "z_min": self.z_min,
            "z_max": self.z_max,
        }

    def encode_y_origin_in_url(self, url: str) -> str:
        """Encode bottom-origin tile numbering in an NGW URL template.

        Convert only an explicit ``False`` value from legacy PyTiledLayer;
        native QGIS URLs already encode their Y-origin convention.

        :param url: Tile URL template from QGIS or QuickMapServices.
        :return: Template with the QGIS ``{-y}`` placeholder when needed.
        """
        if self.y_origin_top is False:
            return url.replace("{y}", "{-y}")
        return url
