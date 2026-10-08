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

import pytest
from qgis.core import QgsMapLayerStyle, QgsVectorLayer

from nextgis_connect.features.resource_browser.infrastructure.local_style_transfer import (
    replace_layer_styles,
)


def test_replace_all_styles_preserves_active_name(qgis_app):
    layer = QgsVectorLayer("Point", "Test", "memory")
    snapshot = QgsMapLayerStyle()
    snapshot.readFromLayer(layer)
    manager = layer.styleManager()
    manager.addStyle("old", snapshot)
    manager.addStyle("active", snapshot)
    manager.setCurrentStyle("active")

    replace_layer_styles(
        layer, [("active", snapshot.xmlData()), ("new", snapshot.xmlData())]
    )

    assert set(manager.styles()) == {"active", "new"}
    assert manager.currentStyle() == "active"


def test_empty_transfer_does_not_remove_local_styles(qgis_app):
    layer = QgsVectorLayer("Point", "Test", "memory")
    original = layer.styleManager().styles()
    with pytest.raises(ValueError):
        replace_layer_styles(layer, [])
    assert layer.styleManager().styles() == original


def test_invalid_download_does_not_remove_local_styles(qgis_app):
    layer = QgsVectorLayer("Point", "Test", "memory")
    snapshot = QgsMapLayerStyle()
    snapshot.readFromLayer(layer)
    manager = layer.styleManager()
    manager.addStyle("local", snapshot)
    manager.setCurrentStyle("local")
    with pytest.raises(ValueError):
        replace_layer_styles(
            layer, [("valid", snapshot.xmlData()), ("broken", "<qgis")]
        )
    assert set(manager.styles()) == {"default", "local"}
    assert manager.currentStyle() == "local"
