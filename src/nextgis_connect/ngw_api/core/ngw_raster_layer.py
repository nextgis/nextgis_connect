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

from qgis.core import QgsProviderRegistry

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_qgis_style import NGWQGISRasterStyle
from .ngw_resource import API_LAYER_EXTENT, NGWResource


class NGWRasterLayer(NGWResource):
    type_id = "raster_layer"
    type_title = "NGW Raster Layer"

    def __init__(self, resource_factory, resource_json):
        super().__init__(resource_factory, resource_json)
        self.is_cog = resource_json["raster_layer"].get("cog", False)

    @property
    def layer_params(self) -> Tuple[str, str, str]:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)

        uri_config = {
            "path": f"{self.get_absolute_vsicurl_url()}/cog",
        }
        is_fixed = False
        connection.update_uri_config(
            uri_config, workaround_for_email=not is_fixed
        )

        provider_registry = QgsProviderRegistry.instance()
        resource_uri = provider_registry.encodeUri("gdal", uri_config)

        return (resource_uri, self.display_name, "gdal")

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

    def create_style(self):
        """Create default style for this layer"""
        connection = self.res_factory.connection
        style_name = self.generate_unique_child_name(self.display_name + "")

        params = dict(
            resource=dict(
                cls="raster_style",
                parent=dict(id=self.resource_id),
                display_name=style_name,
            ),
        )

        url = self.get_api_collection_url()
        result = connection.post(url, params=params)
        return NGWResource(
            self.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

    def create_qml_style(
        self, qml, callback, style_name=None
    ) -> NGWQGISRasterStyle:
        """Create QML style for this layer

        qml - full path to qml file
        callback - upload file callback
        """
        connection = self.res_factory.connection
        if not style_name:
            style_name = self.display_name
        style_name = self.generate_unique_child_name(style_name)

        style_file_desc = connection.upload_file(qml, callback)

        params = dict(
            resource=dict(
                cls=NGWQGISRasterStyle.type_id,
                parent=dict(id=self.resource_id),
                display_name=style_name,
            ),
        )
        params[NGWQGISRasterStyle.type_id] = dict(file_upload=style_file_desc)

        url = self.get_api_collection_url()
        result = connection.post(url, params=params)
        return NGWQGISRasterStyle(
            self.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )
