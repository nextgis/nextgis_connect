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

import datetime
from typing import Any, Dict, List, Optional

from qgis.core import QgsProviderRegistry

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_abstract_vector_resource import NGWAbstractVectorResource
from .ngw_feature import NGWFeature
from .ngw_mapserver_style import NGWMapServerStyle
from .ngw_resource import API_LAYER_EXTENT, NGWResource

ADD_FEATURE_URL = "/api/resource/%s/feature/"
DEL_ALL_FEATURES_URL = "/api/resource/%s/feature/"


class NGWVectorLayer(NGWAbstractVectorResource):
    """Define ngw vector layer resource

    Geometry types: point, multipoint, linestring, multilinestring, polygon, multipolygon

    """

    type_id = "vector_layer"

    def get_absolute_geojson_url(self):
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        assert connection is not None

        uri_config = {
            "path": f"{self.get_absolute_vsicurl_url()}/geojson",
            "authcfg": connection.auth_config_id,
        }
        uri_config = {
            key: value
            for key, value in uri_config.items()
            if value is not None
        }

        provider_registry = QgsProviderRegistry.instance()
        assert provider_registry is not None
        metadata_provider = provider_registry.providerMetadata("ogr")
        assert metadata_provider is not None

        return metadata_provider.encodeUri(uri_config)

    def get_feature_adding_url(self):
        return ADD_FEATURE_URL % self.resource_id

    def get_feature_deleting_url(self):
        return DEL_ALL_FEATURES_URL % self.resource_id

    # TODO Need refactoring
    def patch_features(self, ngw_feature_list):
        features_dict_list = [
            ngw_feature.asDict() for ngw_feature in ngw_feature_list
        ]

        connection = self.res_factory.connection

        url = self.get_feature_adding_url()
        connection.patch(url, params=features_dict_list)

    def construct_ngw_feature_as_json(self, attributes):
        json_feature = {}

        for field_name, pyvalue in list(attributes.items()):
            field_type = self.field(field_name).datatype.name
            field_value = None
            if field_type == NGWVectorLayer.FieldTypeDate:
                if isinstance(pyvalue, datetime.date):
                    field_value = {
                        "year": pyvalue.year,
                        "month": pyvalue.month,
                        "day": pyvalue.day,
                    }
            elif field_type == NGWVectorLayer.FieldTypeTime:
                if isinstance(pyvalue, datetime.time):
                    field_value = {
                        "hour": pyvalue.hour,
                        "minute": pyvalue.minute,
                        "second": pyvalue.second,
                    }
            elif field_type == NGWVectorLayer.FieldTypeDatetime:
                if isinstance(pyvalue, datetime.datetime):
                    field_value = {
                        "year": pyvalue.year,
                        "month": pyvalue.month,
                        "day": pyvalue.day,
                        "hour": pyvalue.hour,
                        "minute": pyvalue.minute,
                        "second": pyvalue.second,
                    }
            elif field_type is None:
                field_value = None
            else:
                field_value = pyvalue

            json_feature[field_name] = field_value

        return json_feature

    def delete_all_features(self):
        connection = self.res_factory.connection
        connection.delete(self.get_feature_deleting_url())

    # TODO Need refactoring. Paging loading with process
    def get_features(self) -> List[NGWFeature]:
        connection = self.res_factory.connection

        url = self.get_feature_adding_url()
        result = connection.get(url)

        ngw_features = []
        for feature in result:
            ngw_features.append(NGWFeature(feature, self))

        return ngw_features

    def extent(self):
        result = self.res_factory.connection.get(
            API_LAYER_EXTENT(self.resource_id)
        )
        extent = result.get("extent")
        if extent is None:
            return (-180, 180, -90, 90)

        return (
            extent.get("minLon", -180),
            extent.get("maxLon", 180),
            extent.get("minLat", -90),
            extent.get("maxLat", 90),
        )

    def create_map_server_style(self):
        """Create default Map Srver style for this layer"""
        connection = self.res_factory.connection

        style_name = self.generate_unique_child_name(self.display_name + "")

        params = dict(
            resource=dict(
                cls=NGWMapServerStyle.type_id,
                parent=dict(id=self.resource_id),
                display_name=style_name,
            ),
        )

        url = self.get_api_collection_url()
        result = connection.post(url, params=params)
        ngw_resource = NGWMapServerStyle(
            self.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource

    def update_fields_params(
        self, params_for_update: Dict[str, Dict[str, Any]]
    ):
        layer_dict = self._json.get("feature_layer")
        ngw_fields_list = layer_dict.get("fields")

        fields_for_update = []

        for ngw_field in ngw_fields_list:
            field_for_update = dict(id=ngw_field["id"])

            field_keyname = ngw_field["keyname"]
            if field_keyname in params_for_update:
                field_for_update.update(params_for_update[field_keyname])

            fields_for_update.append(field_for_update)

        connection = self.res_factory.connection
        url = self.get_relative_api_url()

        params = dict(feature_layer=dict(fields=fields_for_update))

        connection.put(url, params=params)

        self.update()

    def export(self, path: str, format: str = "GPKG", srs: int = 3857) -> None:
        url = self.get_relative_api_url()
        export_url = (
            f"{url}/export?format={format}&srs={srs}&fid=&zipped=false"
        )

        connection = self.res_factory.connection
        connection.download(export_url, path)

    @property
    def is_versioning_enabled(self) -> bool:
        feature_layer = self._json.get("feature_layer", {})
        if "versioning" not in feature_layer:
            return False
        return feature_layer["versioning"].get("enabled", False)

    @property
    def epoch(self) -> Optional[int]:
        feature_layer = self._json.get("feature_layer", {})
        if "versioning" not in feature_layer:
            return None
        return feature_layer["versioning"].get("epoch")

    @property
    def version(self) -> Optional[int]:
        feature_layer = self._json.get("feature_layer", {})
        if "versioning" not in feature_layer:
            return None
        return feature_layer["versioning"].get("latest")
