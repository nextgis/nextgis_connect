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

from typing import Optional
from unittest import mock

import pytest
from qgis.core import QgsDataSourceUri

from nextgis_connect.legacy.ngw.core.ngw_postgis_layer import (
    DEFAULT_POSTGRES_PORT,
    NGWPostgisConnection,
    NGWPostgisLayer,
)
from nextgis_connect.platform.qgis.compat import WkbType


@pytest.mark.parametrize(
    ("sslmode", "expected_sslmode"),
    ((None, "prefer"), ("verify-full", "verify-full")),
)
def test_layer_params_constructs_postgis_uri(
    sslmode: Optional[str], expected_sslmode: str
) -> None:
    postgis_connection = NGWPostgisConnection(
        mock.Mock(),
        {
            "resource": {
                "id": 1,
                "cls": "postgis_connection",
                "display_name": "connection",
                "parent": None,
                "children": False,
                "owner_user": None,
            },
            "postgis_connection": {
                "hostname": "database.example.com",
                "port": None,
                "database": "gis",
                "username": "alice",
                "password": "secret",
                "sslmode": sslmode,
            },
        },
    )
    postgis_layer = NGWPostgisLayer(
        mock.Mock(),
        {
            "resource": {
                "id": 2,
                "cls": "postgis_layer",
                "display_name": "roads",
                "parent": None,
                "children": False,
                "owner_user": None,
            },
            "postgis_layer": {
                "connection": {"id": 1},
                "schema": "public",
                "table": "roads",
                "column_geom": "geom",
                "column_id": "id",
                "geometry_type": "LINESTRINGZ",
                "geometry_srid": 4326,
            },
        },
    )

    uri_string, layer_name, provider = postgis_layer.layer_params(
        postgis_connection
    )
    expected_uri = QgsDataSourceUri()
    expected_uri.setConnection(
        "database.example.com",
        str(DEFAULT_POSTGRES_PORT),
        "gis",
        "alice",
        "secret",
        QgsDataSourceUri.decodeSslMode(expected_sslmode),
    )
    expected_uri.setDataSource("public", "roads", "geom", "", "id")
    expected_uri.setWkbType(WkbType.LineStringZ)
    expected_uri.setSrid("4326")

    assert QgsDataSourceUri(uri_string) == expected_uri
    assert ("sslmode=" in uri_string) is (sslmode is not None)
    assert layer_name == "roads"
    assert provider == "postgres"
