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

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import mock

import pytest
from qgis.core import (
    QgsDataSourceUri,
    QgsMapLayer,
    QgsProviderRegistry,
    QgsVectorLayer,
)

from nextgis_connect.legacy.detached_editing import utils as detached_utils
from nextgis_connect.legacy.ngw.qgis.layer_source_sanitizer import (
    QgisLayerSourceSanitizer,
)


@pytest.fixture(autouse=True)
def _initialized_qgis(qgis_app) -> None:
    del qgis_app


def _layer(
    source: str,
    provider_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> QgsMapLayer:
    layer = mock.Mock(spec=QgsMapLayer)
    layer.source.return_value = source
    layer.providerType.return_value = provider_type
    configured_properties = properties or {}
    layer.customProperty.side_effect = lambda name: configured_properties.get(
        name
    )
    return layer


def _encoded_source(provider_type: str, parameters: Dict[str, Any]) -> str:
    provider_metadata = QgsProviderRegistry.instance().providerMetadata(
        provider_type
    )
    assert provider_metadata is not None
    return provider_metadata.encodeUri(parameters)


@pytest.mark.parametrize(
    ("provider_type", "source", "expected"),
    (
        ("ogr", "/project/shapes/roads.shp", "roads.shp"),
        (
            "ogr",
            "/project/data/roads.gpkg|layername=places",
            "roads.gpkg|layername=places",
        ),
        (
            "spatialite",
            (
                "dbname='/project/data/roads.sqlite' "
                'table="places" (geometry)'
            ),
            "roads.sqlite|layername=places",
        ),
        ("gdal", "/project/rasters/dem.tif", "dem.tif"),
        (
            "delimitedtext",
            "file:///project/tables/places.csv?type=csv&xField=x&yField=y",
            "places.csv",
        ),
        (
            "mbtilesvectortiles",
            "/project/tiles/basemap.mbtiles",
            "basemap.mbtiles",
        ),
        (
            "wms",
            "type=mbtiles&url=file:///project/tiles/basemap.mbtiles",
            "basemap.mbtiles",
        ),
        (
            "ogr",
            r"C:\projects\vectors\roads.gpkg|layername=roads",
            "roads.gpkg|layername=roads",
        ),
    ),
)
def test_local_source_keeps_only_filename(
    provider_type: str,
    source: str,
    expected: str,
) -> None:
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(source, provider_type))

    assert result == expected


def test_gdal_source_omits_null_layer_name() -> None:
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())
    layer = _layer("/project/rasters/dem.tif", "gdal")

    with mock.patch.object(
        sanitizer,
        "_decode_uri",
        return_value={
            "path": "/project/rasters/dem.tif",
            "layername": "NULL",
        },
    ):
        result = sanitizer.sanitize(layer)

    assert result == "dem.tif"


@pytest.mark.parametrize(
    ("provider_type", "parameters", "expected"),
    (
        (
            "wms",
            {
                "crs": "EPSG:3857",
                "format": "image/png",
                "layers": "roads",
                "styles": "",
                "url": (
                    "https://alice:secret@example.com/wms?"
                    "token=hidden&map=main"
                ),
            },
            "https://example.com/wms?map=main|layername=roads",
        ),
        (
            "WFS",
            {
                "password": "secret",
                "typename": "transport:roads",
                "url": (
                    "https://alice:secret@example.com/wfs?"
                    "api_key=hidden&tenant=main"
                ),
                "username": "alice",
                "version": "2.0.0",
            },
            "https://example.com/wfs?tenant=main|layername=transport:roads",
        ),
        (
            "wcs",
            {
                "identifier": "dem",
                "url": (
                    "https://alice:secret@example.com/wcs?"
                    "signature=hidden&map=main"
                ),
            },
            "https://example.com/wcs?map=main|layername=dem",
        ),
        (
            "wms",
            {
                "type": "xyz",
                "url": (
                    "https://tiles.example.com/{z}/{x}/{y}.png?"
                    "key=hidden&theme=light"
                ),
                "zmax": 18,
                "zmin": 0,
            },
            "https://tiles.example.com/{z}/{x}/{y}.png?theme=light",
        ),
        (
            "arcgisfeatureserver",
            {
                "authcfg": "hidden",
                "url": (
                    "https://alice:secret@example.com/arcgis/rest/services/"
                    "Roads/FeatureServer/0"
                ),
            },
            ("https://example.com/arcgis/rest/services/Roads/FeatureServer/0"),
        ),
        (
            "arcgismapserver",
            {
                "authcfg": "hidden",
                "layer": "2",
                "url": (
                    "https://alice:secret@example.com/arcgis/rest/services/"
                    "Base/MapServer"
                ),
            },
            (
                "https://example.com/arcgis/rest/services/Base/MapServer"
                "|layername=2"
            ),
        ),
    ),
)
def test_external_source_keeps_only_url_and_layer(
    provider_type: str,
    parameters: Dict[str, Any],
    expected: str,
) -> None:
    source = _encoded_source(provider_type, parameters)
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(source, provider_type))

    assert result == expected


def test_external_oapif_source_uses_data_source_uri() -> None:
    uri = QgsDataSourceUri()
    uri.setAuthConfigId("hidden")
    uri.setParam("typename", "roads")
    uri.setParam(
        "url",
        "https://alice:secret@example.com/oapif?token=hidden&tenant=main",
    )
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(uri.uri(False), "OAPIF"))

    assert result == "https://example.com/oapif?tenant=main|layername=roads"


def test_external_source_removes_all_supported_credentials() -> None:
    source = _encoded_source(
        "WFS",
        {
            "authcfg": "hidden",
            "password": "secret",
            "typename": "roads",
            "url": (
                "https://alice:secret@example.com/wfs?"
                "user=alice&password=secret&access_token=hidden&"
                "X-Amz-Credential=hidden&X-Amz-Signature=hidden&safe=1"
            ),
            "username": "alice",
        },
    )
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(source, "WFS"))

    assert result == "https://example.com/wfs?safe=1|layername=roads"


@pytest.mark.parametrize(
    ("provider_type", "source", "expected"),
    (
        (
            "gdal",
            (
                "/vsicurl/https://alice:secret@example.nextgis.com/"
                "api/resource/42/cog"
            ),
            "https://example.nextgis.com/resource/42 (cog)",
        ),
        (
            "ogr",
            (
                "/vsicurl/https://alice:secret@example.nextgis.com/"
                "api/resource/42/geojson"
            ),
            "https://example.nextgis.com/resource/42 (geojson)",
        ),
        (
            "WFS",
            (
                "url='https://alice:secret@example.nextgis.com/"
                "api/resource/42/wfs' typename='roads'"
            ),
            "https://example.nextgis.com/resource/42 (wfs)",
        ),
        (
            "wms",
            (
                "layers=roads&url=https%3A%2F%2Falice%3Asecret%40"
                "example.nextgis.com%2Fapi%2Fresource%2F42%2Fwms"
            ),
            "https://example.nextgis.com/resource/42 (wms)",
        ),
        (
            "wms",
            (
                "type=xyz&url=https%3A%2F%2Falice%3Asecret%40"
                "example.nextgis.com%2Fapi%2Fcomponent%2Frender%2Ftile%3F"
                "resource%3D42%26z%3D%7Bz%7D%26x%3D%7Bx%7D%26y%3D%7By%7D"
            ),
            "https://example.nextgis.com/resource/42 (tms)",
        ),
        (
            "OAPIF",
            (
                "url='https://alice:secret@example.nextgis.com/"
                "api/resource/42/ogcf' typename='roads'"
            ),
            "https://example.nextgis.com/resource/42 (ogcf)",
        ),
    ),
)
def test_ngw_url_is_replaced_with_resource_url(
    provider_type: str,
    source: str,
    expected: str,
) -> None:
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(source, provider_type))

    assert result == expected


def test_ngw_custom_properties_have_priority_over_source_url() -> None:
    connections_manager = mock.Mock()
    connections_manager.connection.return_value = SimpleNamespace(
        url="https://user:password@primary.nextgis.com"
    )
    layer = _layer(
        "/vsicurl/https://fallback.nextgis.com/api/resource/99/cog",
        "gdal",
        {
            "ngw_connection_id": "primary",
            "ngw_resource_id": 42,
        },
    )

    result = QgisLayerSourceSanitizer(connections_manager).sanitize(layer)

    assert result == "https://primary.nextgis.com/resource/42 (cog)"


def test_ngw_properties_use_source_url_when_connection_is_missing() -> None:
    connections_manager = mock.Mock()
    connections_manager.connection.return_value = None
    layer = _layer(
        "/vsicurl/https://fallback.nextgis.com/api/resource/99/geojson",
        "ogr",
        {
            "ngw_connection_id": "missing",
            "ngw_resource_id": 42,
        },
    )

    result = QgisLayerSourceSanitizer(connections_manager).sanitize(layer)

    assert result == "https://fallback.nextgis.com/resource/42 (geojson)"


@pytest.mark.parametrize(
    ("has_changes", "suffix"),
    ((False, ""), (True, " (modified)")),
)
def test_detached_source_reports_local_changes(
    has_changes: bool,
    suffix: str,
) -> None:
    connections_manager = mock.Mock()
    connections_manager.connection.return_value = SimpleNamespace(
        url="https://example.nextgis.com"
    )
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
    layer.setCustomProperty("ngw_connection_id", "connection")
    layer.setCustomProperty("ngw_resource_id", 42)
    metadata = SimpleNamespace(
        connection_id="connection",
        has_changes=has_changes,
        resource_id=42,
    )

    with mock.patch.object(
        detached_utils,
        "is_ngw_container",
        return_value=True,
    ), mock.patch.object(
        detached_utils,
        "container_path",
        return_value=Path("/cache/42.gpkg"),
    ), mock.patch.object(
        detached_utils,
        "container_metadata",
        return_value=metadata,
    ):
        result = QgisLayerSourceSanitizer(connections_manager).sanitize(layer)

    assert result == f"https://example.nextgis.com/resource/42{suffix}"


@pytest.mark.parametrize(
    ("provider_type", "source", "expected"),
    (
        (
            "postgres",
            (
                "dbname='gis' host=database.example.com port=5432 "
                "user='alice' password='secret' "
                'table="public"."roads" (geom)'
            ),
            (
                "postgresql://database.example.com:5432/gis"
                "|layername=public.roads"
            ),
        ),
        (
            "postgres",
            (
                "service='main_service' dbname='gis' user='alice' "
                'password=\'secret\' table="public"."roads" (geom)'
            ),
            "postgresql://main_service/gis|layername=public.roads",
        ),
        (
            "mssql",
            (
                "dbname='gis' host=database.example.com port=1433 "
                "user='alice' password='secret' "
                'table="dbo"."roads" (geom)'
            ),
            "mssql://database.example.com:1433/gis|layername=dbo.roads",
        ),
    ),
)
def test_database_source_omits_credentials(
    provider_type: str,
    source: str,
    expected: str,
) -> None:
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer(source, provider_type))

    assert result == expected


def test_unknown_source_is_omitted() -> None:
    sanitizer = QgisLayerSourceSanitizer(mock.Mock())

    result = sanitizer.sanitize(_layer("Point?crs=EPSG:4326", "memory"))

    assert result is None
