from qgis.core import QgsDataSourceUri

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource, dict_to_object, list_dict_to_list_object


class NGWOgcfService(NGWResource):
    type_id = "ogcfserver_service"

    def _construct(self):
        super()._construct()
        # wfsserver_service
        self.ogcf = dict_to_object(self._json[self.type_id])
        if hasattr(self.ogcf, "collections"):
            self.layers = list_dict_to_list_object(self.ogcf.collections)
        else:
            self.layers = []

    def params_for_layer(self, layer):
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)

        uri = QgsDataSourceUri()
        uri.setParam("typename", layer.keyname)
        uri.setParam("srsname", "OGC:CRS84")
        uri.setParam("preferCoordinatesForWfsT11", "false")
        uri.setParam("pagingEnabled", "false")
        uri.setParam("maxNumFeatures", str(layer.maxfeatures))
        uri.setParam("restrictToRequestBBOX", "1")
        uri.setParam("authcfg", connection.auth_config_id)
        uri.setParam("url", self.get_absolute_api_url() + "/ogcf")

        return (uri.uri(True), layer.display_name, "OAPIF")

    def get_layers(self):
        return self.ogcf.layers
