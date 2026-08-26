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

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeedback,
    QgsRectangle,
    QgsReferencedRectangle,
)

from nextgis_connect.legacy.ngw.core.ngw_group_resource import NGWGroupResource
from nextgis_connect.platform.qgis.extent_calculator import ExtentCalculator

from .ngw_resource import NGWResource


class NGWWebMap(NGWResource):
    type_id = "webmap"
    type_title = "NGW Web Map"

    __root: Optional["NGWWebMapRoot"]
    __used_tree_resources: List[int]
    __basemaps: List["WebMapBaseMap"]

    def __init__(self, resource_factory, resource_json):
        super().__init__(resource_factory, resource_json)
        self.__root = None
        self.__used_tree_resources = []
        self.__basemaps = []

    @property
    def all_resources_id(self) -> List[int]:
        if self.__root is None:
            self.__create_structure()

        return self.__used_tree_resources

    @property
    def root(self) -> "NGWWebMapRoot":
        if self.__root is None:
            self.__create_structure()
        assert self.__root is not None
        return self.__root

    @property
    def basemaps(self) -> List["WebMapBaseMap"]:
        if self.__root is None:
            self.__create_structure()

        return self.__basemaps

    @property
    def basemap_background_color(self) -> Optional[str]:
        background_color = self._json.get("basemap_webmap", {}).get(
            "background_color"
        )
        return background_color if isinstance(background_color, str) else None

    @property
    def basemap_disabled(self) -> Optional[bool]:
        disabled = self._json.get("basemap_webmap", {}).get("disable")
        return disabled if isinstance(disabled, bool) else None

    @property
    def draw_order_enabled(self) -> bool:
        return bool(self._json[self.type_id].get("draw_order_enabled"))

    @staticmethod
    def to_webmap_extent(
        rectangle: QgsReferencedRectangle,
    ) -> Dict[str, float]:
        return ExtentCalculator.to_webmap_extent(rectangle)

    @property
    def extent(self) -> Optional[QgsReferencedRectangle]:
        webmap = self._json[self.type_id]
        left, bottom, right, top = (
            webmap.get(f"extent_{side}")
            for side in ["left", "bottom", "right", "top"]
        )
        extent = [
            min(left, right),
            min(bottom, top),
            max(left, right),
            max(bottom, top),
        ]

        if any(side is None for side in extent):
            return None

        rectangle = QgsRectangle(*extent)
        crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)

        return QgsReferencedRectangle(rectangle, crs)

    @property
    def preview_url(self):
        return f"{self.get_absolute_url()}/display"

    def __create_structure(self) -> None:
        basemap_webmap = self._json.get("basemap_webmap", {})

        self.__root = NGWWebMapRoot()
        for item in self._json[self.type_id]["root_item"].get("children", []):
            if item["item_type"] == "layer":
                webmap_layer = self.__extract_layer(item)
                assert webmap_layer.style_parent_id is not None
                self.__used_tree_resources.append(webmap_layer.style_parent_id)
                self.__used_tree_resources.append(webmap_layer.layer_style_id)
                self.__root.appendChild(webmap_layer)
            else:
                webmap_group = self.__extract_group(item)
                if len(webmap_group.children) > 0:
                    self.__root.appendChild(webmap_group)

        self.__basemaps = [
            WebMapBaseMap(**basemap)
            for basemap in basemap_webmap.get("basemaps", [])
        ]
        self.__basemaps.sort(reverse=True)

        self.__used_tree_resources.extend(
            basemap.resource_id for basemap in self.__basemaps
        )

    def __extract_layer(self, layer_item: Dict[str, Any]) -> "NGWWebMapLayer":
        layer_id = layer_item["style_parent_id"]
        style_id = layer_item["layer_style_id"]

        legend_value = layer_item.get("legend_symbols")
        if legend_value is None:
            legend_value = self._json[self.type_id].get("legend_symbols")

        if legend_value is not None:
            legend_value = legend_value == "expand"
        else:
            legend_value = False

        return NGWWebMapLayer(
            style_id,
            layer_item["display_name"],
            is_visible=layer_item["layer_enabled"],
            transparency=layer_item.get("layer_transparency"),
            legend=legend_value,
            style_parent_id=layer_id,
            draw_order_position=layer_item.get("draw_order_position"),
        )

    def __extract_group(self, group_item: Dict[str, Any]) -> "NGWWebMapGroup":
        group = NGWWebMapGroup(
            group_item["display_name"],
            expanded=group_item.get("group_expanded", False),
            exclusive=group_item.get("group_exclusive", False),
            is_visible=group_item.get("group_enabled", True),
        )
        if group.expanded is None:
            group.expanded = False

        for item in group_item.get("children", []):
            if item["item_type"] == "layer":
                webmap_layer = self.__extract_layer(item)
                assert webmap_layer.style_parent_id is not None
                self.__used_tree_resources.append(webmap_layer.style_parent_id)
                self.__used_tree_resources.append(webmap_layer.layer_style_id)
                group.appendChild(webmap_layer)
            else:
                webmap_group = self.__extract_group(item)
                group.appendChild(webmap_group)

        return group

    @classmethod
    def create_in_group(
        cls,
        name,
        ngw_group_resource: NGWGroupResource,
        ngw_webmap_items: List[Dict[str, Any]],
        ngw_base_maps: Optional[List["WebMapBaseMap"]] = None,
        bbox: Union[
            Mapping[str, Any],
            QgsReferencedRectangle,
            Tuple[float, float, float, float],
            None,
        ] = None,
        feedback: Optional[QgsFeedback] = None,
        basemap_background_color: Optional[str] = None,
    ):
        if ngw_base_maps is None:
            ngw_base_maps = []

        bbox = cls.__webmap_bbox(bbox)

        connection = ngw_group_resource.res_factory.connection
        url = ngw_group_resource.get_api_collection_url()

        base_maps = [
            {
                "display_name": basemap.display_name,
                "resource_id": basemap.resource_id,
                "enabled": basemap.enabled,
                "opacity": basemap.opacity,
            }
            for basemap in ngw_base_maps
        ]
        web_map_base_maps = dict(
            basemaps=base_maps,
            background_color=basemap_background_color,
        )

        web_map: Dict[str, Any] = dict(
            root_item=dict(item_type="root", children=ngw_webmap_items),
        )
        web_map.update(bbox)

        params = dict(
            resource=dict(
                cls=NGWWebMap.type_id,
                display_name=name,
                parent=dict(id=ngw_group_resource.resource_id),
            ),
            webmap=web_map,
            basemap_webmap=web_map_base_maps,
        )

        result = connection.post(url, params=params, feedback=feedback)

        ngw_resource = NGWWebMap(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(
                connection,
                result["id"],
                feedback=feedback,
            ),
        )

        return ngw_resource

    @classmethod
    def __webmap_bbox(
        cls,
        bbox: Union[
            Mapping[str, Any],
            QgsReferencedRectangle,
            Tuple[float, float, float, float],
            None,
        ],
    ) -> Dict[str, float]:
        if isinstance(bbox, QgsReferencedRectangle):
            return ExtentCalculator.to_webmap_extent(bbox)

        if bbox is None:
            return ExtentCalculator.default_webmap_extent()

        if isinstance(bbox, tuple):
            extent = ExtentCalculator.from_ngw_extent_tuple(bbox)
        elif isinstance(bbox, Mapping):
            extent = ExtentCalculator.from_webmap_extent_dict(bbox)
        else:
            extent = None

        if extent is None:
            return ExtentCalculator.default_webmap_extent()

        return ExtentCalculator.to_webmap_extent(extent)


class NGWWebMapItem:
    ITEM_TYPE_ROOT = "root"
    ITEM_TYPE_LAYER = "layer"
    ITEM_TYPE_GROUP = "group"

    item_type: str
    children: List["NGWWebMapItem"]

    def __init__(self, item_type):
        self.item_type = item_type
        self.children = []

    def appendChild(self, ngw_web_map_item: "NGWWebMapItem"):
        self.children.append(ngw_web_map_item)

    def toDict(self):
        struct = dict(item_type=self.item_type, children=[])
        struct.update(self._attributes())

        for child in self.children:
            struct["children"].append(child.toDict())

        return struct

    def _attributes(self):
        raise NotImplementedError


class NGWWebMapRoot(NGWWebMapItem):
    def __init__(self):
        super().__init__(NGWWebMapItem.ITEM_TYPE_ROOT)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}: root>"

    def _attributes(self):
        return dict()


class NGWWebMapLayer(NGWWebMapItem):
    def __init__(
        self,
        layer_style_id: int,
        display_name: str,
        *,
        is_visible: bool,
        transparency: Optional[float],
        legend: Optional[bool],
        style_parent_id: Optional[int] = None,
        draw_order_position: Optional[int] = None,
    ):
        super().__init__(NGWWebMapItem.ITEM_TYPE_LAYER)
        self.layer_style_id = layer_style_id
        self.display_name = display_name
        self.is_visible = is_visible
        self.transparency = transparency
        self.legend = legend
        self.style_parent_id = style_parent_id
        self.draw_order_position = draw_order_position

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}: {self.display_name}>"

    def _attributes(self):
        legend = None
        if self.legend is not None:
            legend = "expand" if self.legend else "collapse"

        return dict(
            layer_style_id=self.layer_style_id,
            display_name=self.display_name,
            layer_adapter="image",
            layer_enabled=self.is_visible,
            layer_max_scale_denom=None,
            layer_min_scale_denom=None,
            layer_transparency=self.transparency,
            legend_symbols=legend,
            draw_order_position=self.draw_order_position,
        )


class NGWWebMapGroup(NGWWebMapItem):
    def __init__(
        self,
        display_name,
        expanded=True,
        exclusive=False,
        is_visible=True,
    ):
        super().__init__(NGWWebMapItem.ITEM_TYPE_GROUP)
        self.display_name = display_name
        self.expanded = expanded
        self.exclusive = exclusive
        self.is_visible = is_visible

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}: {self.display_name}>"

    def _attributes(self):
        return dict(
            display_name=self.display_name,
            group_expanded=self.expanded,
            group_enabled=self.is_visible,
            group_exclusive=self.exclusive,
        )


@dataclass(order=True)
class WebMapBaseMap:
    resource_id: int
    display_name: str
    enabled: bool
    position: Optional[int] = None
    opacity: Optional[float] = None

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}: {self.display_name} (id={self.resource_id})>"
