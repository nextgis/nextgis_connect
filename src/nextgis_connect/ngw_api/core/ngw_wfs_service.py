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

from qgis.core import QgsDataSourceUri

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource, dict_to_object, list_dict_to_list_object


class NGWWfsService(NGWResource):
    type_id = "wfsserver_service"

    def _construct(self):
        super()._construct()
        # wfsserver_service
        self.wfs = dict_to_object(self._json[self.type_id])
        if hasattr(self.wfs, "layers"):
            self.layers = list_dict_to_list_object(self.wfs.layers)
        else:
            self.layers = []

    def params_for_layer(self, layer):
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)

        uri = QgsDataSourceUri()
        uri.setAuthConfigId(connection.auth_config_id)
        uri.setParam("typename", layer.keyname)
        uri.setParam("srsname", "EPSG:3857")
        uri.setParam("version", "auto")
        uri.setParam("url", self.get_absolute_api_url() + "/wfs")
        uri.setParam("restrictToRequestBBOX", "1")

        return (uri.uri(False), layer.display_name, "WFS")

    def get_layers(self):
        return self._json["wfsserver_service"]["layers"]

    def get_source_layer(self, layer_id):
        return self.res_factory.get_resource(layer_id)
