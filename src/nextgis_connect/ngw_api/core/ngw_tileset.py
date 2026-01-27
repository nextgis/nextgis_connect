from typing import Tuple

from qgis.core import QgsProviderRegistry

from nextgis_connect.ngw_api.core.ngw_resource import NGWResource
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import dict_to_object


class NGWTileset(NGWResource):
    type_id = "tileset"
    type_title = "NGW Tileset"

    def _construct(self):
        super()._construct()
        self.wfs = dict_to_object(self._json[self.type_id])

    @property
    def layer_params(self) -> Tuple[str, str, str]:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        assert connection is not None

        # layer_info = self._json[self.type_id]

        url = (
            f"{connection.url}/api/component/render/tile?"
            f"resource={self.resource_id}&nd=204&z={{z}}&x={{x}}&y={{y}}"
        )

        params = {"type": "xyz", "url": url}

        connection.update_uri_config(params)

        params = {
            key: value for key, value in params.items() if value is not None
        }

        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            "wms"
        )
        return provider_metadata.encodeUri(params), self.display_name, "wms"
