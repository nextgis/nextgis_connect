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

import base64
from pathlib import Path
from typing import Optional

from qgis.core import QgsPathResolver, QgsSymbolLayerUtils
from qgis.PyQt.QtXml import QDomDocument, QDomElement

_SVG_PATH_PROPERTIES = {
    "SvgMarker": "name",
    "SVGFill": "svgFile",
}


class SvgEmbeddingQmlHandler:
    """Embed local SVG marker files using QGIS' ``base64:`` format."""

    def __init__(self, path_resolver: QgsPathResolver) -> None:
        self._path_resolver = path_resolver

    def process(self, document: QDomDocument) -> bool:
        """Embed SVG references that can be resolved to local files."""
        has_changes = False
        symbol_layers = document.elementsByTagName("layer")
        for index in range(symbol_layers.count()):
            symbol_layer = symbol_layers.at(index).toElement()
            svg_path_property = _SVG_PATH_PROPERTIES.get(
                symbol_layer.attribute("class")
            )
            if svg_path_property is None:
                continue

            has_changes = (
                self._embed_symbol_layer_svg(
                    symbol_layer,
                    svg_path_property,
                )
                or has_changes
            )

        background_nodes = document.elementsByTagName("background")
        for index in range(background_nodes.count()):
            background_node = background_nodes.at(index).toElement()
            has_changes = (
                self._embed_attribute(
                    background_node,
                    "shapeSVGFile",
                )
                or has_changes
            )

        property_nodes = document.elementsByTagName("property")
        for index in range(property_nodes.count()):
            property_node = property_nodes.at(index).toElement()
            if property_node.attribute("key") != "labeling/shapeSVGFile":
                continue

            has_changes = (
                self._embed_attribute(property_node, "value") or has_changes
            )

        return has_changes

    def _embed_symbol_layer_svg(
        self,
        symbol_layer: QDomElement,
        svg_path_property: str,
    ) -> bool:
        properties = symbol_layer.elementsByTagName("prop")
        for property_index in range(properties.count()):
            property_node = properties.at(property_index).toElement()
            if property_node.attribute("k") == svg_path_property:
                return self._embed_attribute(property_node, "v")

        properties_map = symbol_layer.firstChildElement("Option")
        if properties_map.attribute("type") != "Map":
            return False

        property_node = properties_map.firstChildElement("Option")
        while not property_node.isNull():
            if property_node.attribute("name") == svg_path_property:
                return self._embed_attribute(property_node, "value")
            property_node = property_node.nextSiblingElement("Option")

        return False

    def _embed_attribute(
        self,
        node: QDomElement,
        attribute_name: str,
    ) -> bool:
        svg_reference = node.attribute(attribute_name)
        embedded_svg = self._embedded_svg(svg_reference)
        if embedded_svg is None:
            return False

        node.setAttribute(attribute_name, embedded_svg)
        return True

    def _embedded_svg(self, svg_reference: str) -> Optional[str]:
        if svg_reference.startswith("base64:"):
            return None

        svg_path = QgsSymbolLayerUtils.svgSymbolNameToPath(
            svg_reference,
            self._path_resolver,
        )
        try:
            svg_data = Path(svg_path).read_bytes()
        except OSError:
            return None

        encoded_svg = base64.b64encode(svg_data).decode("ascii")
        return f"base64:{encoded_svg}"
