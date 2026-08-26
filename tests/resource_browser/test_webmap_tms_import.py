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

from nextgis_connect.features.resource_browser.domain import (
    ResourceImportExtent,
)
from nextgis_connect.legacy.ngw.core import NGWWebMap
from nextgis_connect.legacy.ngw.core.ngw_webmap import NGWWebMapGroup
from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
    NgConnectDock,
)


def _webmap_resource_json() -> dict:
    return {
        "resource": {
            "id": 265,
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
                "children": [
                    {
                        "item_type": "layer",
                        "style_parent_id": 164,
                        "layer_style_id": 264,
                        "display_name": "Visible layer",
                        "layer_enabled": True,
                    },
                    {
                        "item_type": "layer",
                        "style_parent_id": 199,
                        "layer_style_id": 299,
                        "display_name": "Hidden layer",
                        "layer_enabled": False,
                    },
                    {
                        "item_type": "group",
                        "display_name": "Group",
                        "group_expanded": True,
                        "group_enabled": False,
                        "group_exclusive": False,
                        "children": [
                            {
                                "item_type": "layer",
                                "style_parent_id": 163,
                                "layer_style_id": 263,
                                "display_name": "Nested visible layer",
                                "layer_enabled": True,
                            },
                        ],
                    },
                ],
            },
            "extent_left": 10.0,
            "extent_bottom": 20.0,
            "extent_right": 30.0,
            "extent_top": 40.0,
        },
        "basemap_webmap": {
            "basemaps": [
                {
                    "resource_id": 100,
                    "display_name": "Enabled basemap",
                    "enabled": True,
                    "opacity": None,
                },
                {
                    "resource_id": 101,
                    "display_name": "Disabled basemap",
                    "enabled": False,
                    "opacity": None,
                },
            ],
        },
    }


def _webmap_resource_json_with_draw_order() -> dict:
    resource_json = _webmap_resource_json()
    resource_json["webmap"]["draw_order_enabled"] = True
    resource_json["webmap"]["root_item"]["children"] = [
        {
            "item_type": "layer",
            "style_parent_id": 110,
            "layer_style_id": 10,
            "display_name": "Second by draw order",
            "layer_enabled": True,
            "draw_order_position": 2,
        },
        {
            "item_type": "layer",
            "style_parent_id": 111,
            "layer_style_id": 11,
            "display_name": "No draw order",
            "layer_enabled": True,
            "draw_order_position": None,
        },
        {
            "item_type": "layer",
            "style_parent_id": 112,
            "layer_style_id": 12,
            "display_name": "First by draw order",
            "layer_enabled": True,
            "draw_order_position": 1,
        },
    ]
    return resource_json


def _webmap_resource_json_like_map_18() -> dict:
    resource_json = _webmap_resource_json()
    resource_json["webmap"]["root_item"]["children"] = [
        {
            "item_type": "layer",
            "style_parent_id": 120,
            "layer_style_id": 20,
            "display_name": "Layer 20",
            "layer_enabled": True,
        },
        {
            "item_type": "layer",
            "style_parent_id": 119,
            "layer_style_id": 19,
            "display_name": "Layer 19",
            "layer_enabled": True,
        },
        {
            "item_type": "layer",
            "style_parent_id": 121,
            "layer_style_id": 21,
            "display_name": "Layer 21",
            "layer_enabled": True,
        },
        {
            "item_type": "layer",
            "style_parent_id": 122,
            "layer_style_id": 22,
            "display_name": "Layer 22",
            "layer_enabled": True,
        },
    ]
    resource_json["basemap_webmap"]["basemaps"] = [
        {
            "resource_id": 17,
            "display_name": "Basemap 17",
            "enabled": True,
            "opacity": None,
        }
    ]
    return resource_json


class TestWebMapTmsImport:
    def test_reads_group_enabled(self, qgis_app) -> None:
        del qgis_app
        webmap = NGWWebMap(mock.Mock(), _webmap_resource_json())

        group = webmap.root.children[2]

        assert isinstance(group, NGWWebMapGroup)
        assert group.is_visible is False
        assert group.toDict()["group_enabled"] is False

    def test_collects_webmap_tms_layers_like_ngw(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        dock = NgConnectDock.__new__(NgConnectDock)
        webmap = NGWWebMap(mock.Mock(), _webmap_resource_json())

        resource_ids = dock._NgConnectDock__webmap_tms_render_resource_ids(
            webmap
        )

        assert resource_ids == (
            263,
            299,
            264,
        )

    def test_collects_map_18_tms_layers_like_ngw(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        dock = NgConnectDock.__new__(NgConnectDock)
        webmap = NGWWebMap(mock.Mock(), _webmap_resource_json_like_map_18())

        resource_ids = dock._NgConnectDock__webmap_tms_render_resource_ids(
            webmap
        )

        assert resource_ids == (
            22,
            21,
            19,
            20,
        )

    def test_collects_draw_ordered_webmap_tms_layers_like_ngw(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        dock = NgConnectDock.__new__(NgConnectDock)
        webmap = NGWWebMap(
            mock.Mock(),
            _webmap_resource_json_with_draw_order(),
        )

        resource_ids = dock._NgConnectDock__webmap_tms_render_resource_ids(
            webmap
        )

        assert resource_ids == (
            11,
            10,
            12,
        )

    def test_uses_webmap_extent_as_tms_source_extent(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        dock = NgConnectDock.__new__(NgConnectDock)
        webmap = NGWWebMap(mock.Mock(), _webmap_resource_json())

        source_extent = dock._NgConnectDock__webmap_import_extent(webmap)

        assert source_extent == ResourceImportExtent(
            x_min=10.0,
            y_min=20.0,
            x_max=30.0,
            y_max=40.0,
            coordinate_reference_system_auth_id="EPSG:4326",
        )
