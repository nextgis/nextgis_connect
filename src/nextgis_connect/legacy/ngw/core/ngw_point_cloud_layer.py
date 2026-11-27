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

from typing import Tuple

from qgis.core import QgsProviderRegistry

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource


class NGWPointCloudLayer(NGWResource):
    """Represent an NGW point-cloud layer exposed as a remote COPC source."""

    type_id = "point_cloud_layer"
    type_title = "NGW Point Cloud Layer"

    @property
    def layer_params(self) -> Tuple[str, str, str]:
        """Return source parameters for a QGIS COPC layer.

        :return: Encoded COPC URI, display name, and provider key.
        :raises RuntimeError: If the NGW connection or QGIS COPC provider is unavailable.
        """
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        if connection is None:
            raise RuntimeError("NextGIS Web connection is unavailable")

        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            "copc"
        )
        if provider_metadata is None:
            raise RuntimeError("QGIS COPC provider is unavailable")

        copc_url = f"{self.get_absolute_api_url()}/point_cloud.copc.laz"
        uri_config = {"path": copc_url}
        connection.update_uri_config(uri_config)
        resource_uri = provider_metadata.encodeUri(uri_config)
        return resource_uri, self.display_name, "copc"
