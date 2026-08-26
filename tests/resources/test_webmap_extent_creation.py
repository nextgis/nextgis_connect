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

from unittest import mock

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRectangle
from qgis.PyQt.QtGui import QColor

from nextgis_connect.legacy.ngw.core import NGWVectorLayer, NGWWebMap
from nextgis_connect.legacy.ngw.core.ngw_resource_creator import (
    ResourceCreator,
)
from nextgis_connect.legacy.ngw.core.ngw_webmap import (
    NGWWebMapGroup,
    NGWWebMapLayer,
    WebMapBaseMap,
)
from nextgis_connect.legacy.ngw.qgis.ngw_resource_model_4qgis import (
    MapForLayerCreater,
    QGISProjectUploader,
)
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job import (
    NGWCreateMapForStyle,
)

QUADRANT_EXTENTS = [
    pytest.param((10, 20, 30, 40), id="north-east"),
    pytest.param((-30, 20, -10, 40), id="north-west"),
    pytest.param((-30, -40, -10, -20), id="south-west"),
    pytest.param((10, -40, 30, -20), id="south-east"),
]
REPORTED_WEB_MERCATOR_BBOX = (
    80.733005159807,
    51.125765297828714,
    82.29183861012281,
    51.655209179236756,
)


def _reported_web_mercator_rectangle():
    return QgsRectangle(
        8987157.0246004443615675,
        6643570.37114027142524719,
        9160685.57052112184464931,
        6738021.34575835801661015,
    )


def _extent_response(coordinates):
    left, bottom, right, top = coordinates

    return {
        "extent": {
            "minLon": left,
            "minLat": bottom,
            "maxLon": right,
            "maxLat": top,
        }
    }


def _webmap_resource_json(resource_id):
    return {
        "resource": {
            "id": resource_id,
            "cls": NGWWebMap.type_id,
            "display_name": "Map",
            "description": None,
            "parent": None,
            "owner_user": None,
            "children": False,
            "interfaces": [],
        },
        "webmap": {
            "root_item": {
                "children": [],
            },
        },
    }


def _assert_bbox(bbox, coordinates) -> None:
    left, bottom, right, top = coordinates

    assert bbox["extent_left"] == pytest.approx(left)
    assert bbox["extent_bottom"] == pytest.approx(bottom)
    assert bbox["extent_right"] == pytest.approx(right)
    assert bbox["extent_top"] == pytest.approx(top)


@pytest.mark.parametrize("coordinates", QUADRANT_EXTENTS)
def test_create_webmap_uses_canvas_extent(
    qgis_app,
    coordinates,
) -> None:
    del qgis_app

    left, bottom, right, top = coordinates
    canvas = mock.Mock()
    canvas.extent.return_value = QgsRectangle(left, bottom, right, top)
    canvas.canvasColor.return_value = QColor("#1a2b3c")
    canvas.mapSettings.return_value.destinationCrs.return_value = (
        QgsCoordinateReferenceSystem.fromEpsgId(4326)
    )
    iface = mock.Mock()
    iface.mapCanvas.return_value = canvas

    uploader = QGISProjectUploader("Group", mock.Mock(), iface, None)
    webmap_layer = NGWWebMapLayer(
        42,
        "Layer",
        is_visible=True,
        transparency=None,
        legend=True,
    )

    with mock.patch.object(
        uploader,
        "_layer_status",
    ), mock.patch.object(
        NGWWebMap,
        "create_in_group",
        return_value=mock.Mock(),
    ) as create_in_group_mock:
        uploader.create_webmap(
            mock.Mock(),
            "Map",
            [webmap_layer],
            [],
        )

    _assert_bbox(create_in_group_mock.call_args.args[4], coordinates)
    assert (
        create_in_group_mock.call_args.kwargs["basemap_background_color"]
        == "1a2b3c"
    )


def test_create_webmap_transforms_canvas_extent_from_web_mercator(
    qgis_app,
) -> None:
    del qgis_app

    canvas = mock.Mock()
    canvas.extent.return_value = _reported_web_mercator_rectangle()
    canvas.canvasColor.return_value = QColor("#1a2b3c")
    canvas.mapSettings.return_value.destinationCrs.return_value = (
        QgsCoordinateReferenceSystem.fromEpsgId(3857)
    )
    iface = mock.Mock()
    iface.mapCanvas.return_value = canvas

    uploader = QGISProjectUploader("Group", mock.Mock(), iface, None)
    webmap_layer = NGWWebMapLayer(
        42,
        "Layer",
        is_visible=True,
        transparency=None,
        legend=True,
    )

    with mock.patch.object(
        uploader,
        "_layer_status",
    ), mock.patch.object(
        NGWWebMap,
        "create_in_group",
        return_value=mock.Mock(),
    ) as create_in_group_mock:
        uploader.create_webmap(
            mock.Mock(),
            "Map",
            [webmap_layer],
            [],
        )

    _assert_bbox(
        create_in_group_mock.call_args.args[4],
        REPORTED_WEB_MERCATOR_BBOX,
    )


def test_create_webmap_falls_back_to_project_crs_for_projected_extent(
    qgis_app,
) -> None:
    del qgis_app

    project = QgsProject.instance()
    previous_crs = project.crs()
    project.setCrs(QgsCoordinateReferenceSystem.fromEpsgId(3857))

    canvas = mock.Mock()
    canvas.extent.return_value = _reported_web_mercator_rectangle()
    canvas.canvasColor.return_value = QColor("#1a2b3c")
    canvas.mapSettings.return_value.destinationCrs.return_value = (
        QgsCoordinateReferenceSystem.fromEpsgId(4326)
    )
    iface = mock.Mock()
    iface.mapCanvas.return_value = canvas

    uploader = QGISProjectUploader("Group", mock.Mock(), iface, None)
    webmap_layer = NGWWebMapLayer(
        42,
        "Layer",
        is_visible=True,
        transparency=None,
        legend=True,
    )

    try:
        with mock.patch.object(
            uploader,
            "_layer_status",
        ), mock.patch.object(
            NGWWebMap,
            "create_in_group",
            return_value=mock.Mock(),
        ) as create_in_group_mock:
            uploader.create_webmap(
                mock.Mock(),
                "Map",
                [webmap_layer],
                [],
            )
    finally:
        project.setCrs(previous_crs)

    _assert_bbox(
        create_in_group_mock.call_args.args[4],
        REPORTED_WEB_MERCATOR_BBOX,
    )


@pytest.mark.parametrize("coordinates", QUADRANT_EXTENTS)
def test_create_map_for_layer_uses_ngw_extent_endpoint(
    qgis_app,
    coordinates,
) -> None:
    del qgis_app

    ngw_group = mock.Mock()
    ngw_layer = mock.Mock(spec=NGWVectorLayer)
    ngw_layer.connection.get.return_value = _extent_response(coordinates)
    ngw_layer.display_name = "Layer"
    ngw_layer.get_parent.return_value = ngw_group
    ngw_layer.resource_id = 42
    ngw_layer.type_id = NGWVectorLayer.type_id

    job = MapForLayerCreater(ngw_layer, 100)

    with mock.patch.object(
        job,
        "unique_resource_name",
        return_value="Layer-map",
    ), mock.patch.object(
        NGWWebMap,
        "create_in_group",
        return_value=mock.Mock(),
    ) as create_in_group_mock:
        job.create4VectorRasterLayer()

    ngw_layer.connection.get.assert_called_once_with("/api/resource/42/extent")
    _assert_bbox(create_in_group_mock.call_args.kwargs["bbox"], coordinates)


def test_create_map_for_vector_layer_without_style_creates_default_style(
    qgis_app,
) -> None:
    del qgis_app

    ngw_group = mock.Mock()
    ngw_layer = mock.Mock(spec=NGWVectorLayer)
    ngw_layer.connection.get.return_value = _extent_response((10, 20, 30, 40))
    ngw_layer.display_name = "Layer"
    ngw_layer.get_parent.return_value = ngw_group
    ngw_layer.resource_id = 42
    ngw_layer.type_id = NGWVectorLayer.type_id

    ngw_style = mock.Mock()
    ngw_style.resource_id = 100
    ngw_webmap = mock.Mock()
    job = MapForLayerCreater(ngw_layer, None)

    with mock.patch.object(
        ResourceCreator,
        "create_default_vector_style",
        return_value=ngw_style,
    ) as create_default_style, mock.patch.object(
        job,
        "unique_resource_name",
        return_value="Layer-map",
    ), mock.patch.object(
        NGWWebMap,
        "create_in_group",
        return_value=ngw_webmap,
    ) as create_in_group_mock:
        job.create4VectorRasterLayer()

    create_default_style.assert_called_once_with(
        ngw_layer,
        feedback=job._feedback,
    )
    webmap_layers = create_in_group_mock.call_args.args[2]
    assert webmap_layers[0]["layer_style_id"] == 100
    assert job.result.added_resources == [ngw_style, ngw_webmap]
    assert job.result.main_resource_id == ngw_webmap.resource_id


@pytest.mark.parametrize("coordinates", QUADRANT_EXTENTS)
def test_create_map_for_style_uses_ngw_extent_endpoint(
    qgis_app,
    coordinates,
) -> None:
    del qgis_app

    ngw_group = mock.Mock()
    ngw_layer = mock.Mock(spec=NGWVectorLayer)
    ngw_layer.connection.get.return_value = _extent_response(coordinates)
    ngw_layer.display_name = "Layer"
    ngw_layer.get_parent.return_value = ngw_group
    ngw_layer.resource_id = 42
    ngw_style = mock.Mock()
    ngw_style.display_name = "Style"
    ngw_style.get_parent.return_value = ngw_layer
    ngw_style.resource_id = 100

    job = NGWCreateMapForStyle(ngw_style)

    with mock.patch.object(
        job,
        "unique_resource_name",
        return_value="Style-map",
    ), mock.patch.object(
        NGWWebMap,
        "create_in_group",
        return_value=mock.Mock(),
    ) as create_in_group_mock:
        job._do()

    ngw_layer.connection.get.assert_called_once_with("/api/resource/42/extent")
    _assert_bbox(create_in_group_mock.call_args.kwargs["bbox"], coordinates)


def test_create_in_group_preserves_world_extent(qgis_app) -> None:
    del qgis_app

    connection = mock.Mock()
    connection.post.return_value = {"id": 100}
    connection.get.return_value = _webmap_resource_json(100)
    resource_factory = mock.Mock()
    resource_factory.connection = connection
    ngw_group = mock.Mock()
    ngw_group.get_api_collection_url.return_value = "/api/resource/"
    ngw_group.res_factory = resource_factory
    ngw_group.resource_id = 1

    NGWWebMap.create_in_group(
        "Map",
        ngw_group,
        [NGWWebMapGroup("Hidden group", is_visible=False).toDict()],
        [],
        bbox=None,
    )

    params = connection.post.call_args.kwargs["params"]
    bbox = params["webmap"]

    _assert_bbox(bbox, (-180.0, -90.0, 180.0, 90.0))
    assert bbox["root_item"]["children"][0]["group_enabled"] is False


def test_create_in_group_preserves_basemap_settings(qgis_app) -> None:
    del qgis_app
    connection = mock.Mock()
    connection.post.return_value = {"id": 100}
    connection.get.return_value = _webmap_resource_json(100)
    resource_factory = mock.Mock()
    resource_factory.connection = connection
    ngw_group = mock.Mock()
    ngw_group.get_api_collection_url.return_value = "/api/resource/"
    ngw_group.res_factory = resource_factory
    ngw_group.resource_id = 1

    NGWWebMap.create_in_group(
        "Map",
        ngw_group,
        [],
        [
            WebMapBaseMap(
                resource_id=42,
                display_name="Hidden basemap",
                enabled=False,
                opacity=0.4,
            )
        ],
        basemap_background_color="1a2b3c",
    )

    basemap_webmap = connection.post.call_args.kwargs["params"][
        "basemap_webmap"
    ]
    assert basemap_webmap == {
        "basemaps": [
            {
                "display_name": "Hidden basemap",
                "resource_id": 42,
                "enabled": False,
                "opacity": 0.4,
            }
        ],
        "background_color": "1a2b3c",
    }


def test_create_in_group_does_not_normalize_projected_values(qgis_app) -> None:
    del qgis_app

    rectangle = _reported_web_mercator_rectangle()
    connection = mock.Mock()
    connection.post.return_value = {"id": 100}
    connection.get.return_value = _webmap_resource_json(100)
    resource_factory = mock.Mock()
    resource_factory.connection = connection
    ngw_group = mock.Mock()
    ngw_group.get_api_collection_url.return_value = "/api/resource/"
    ngw_group.res_factory = resource_factory
    ngw_group.resource_id = 1

    NGWWebMap.create_in_group(
        "Map",
        ngw_group,
        [],
        [],
        bbox={
            "extent_left": rectangle.xMinimum(),
            "extent_bottom": rectangle.yMinimum(),
            "extent_right": rectangle.xMaximum(),
            "extent_top": rectangle.yMaximum(),
        },
    )

    params = connection.post.call_args.kwargs["params"]
    bbox = params["webmap"]

    _assert_bbox(bbox, (-180.0, -90.0, 180.0, 90.0))
