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
from typing import Any, cast
from unittest.mock import Mock

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest

from nextgis_connect.legacy.detached_editing.identification.ui.description_tab import (
    DescriptionTab,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface


def test_description_tab_does_not_reload_unchanged_description(
    qgis_app, monkeypatch
) -> None:
    del qgis_app
    description = "<p>Description</p>"
    detached_layer = Mock()
    detached_layer.feature_description.return_value = description
    plugin = Mock()
    plugin.path = Path(__file__).resolve().parents[2] / "src/nextgis_connect"
    plugin.detached_editing.layer.return_value = detached_layer
    monkeypatch.setattr(
        NgConnectInterface,
        "instance",
        classmethod(lambda _cls: plugin),
    )
    tab = DescriptionTab()
    layer = Mock()
    try:
        tab.set_feature(layer, 1)
        set_content = Mock(wraps=tab._text_editor.set_content)
        monkeypatch.setattr(tab._text_editor, "set_content", set_content)

        tab.set_feature(layer, 1)

        set_content.assert_not_called()
    finally:
        tab.close()
        tab.deleteLater()


def test_double_click_description_enables_edit_mode(qgis_app) -> None:
    tab = DescriptionTab()
    layer = Mock()
    layer.readOnly.return_value = False
    layer.isEditable.return_value = False
    layer.startEditing.return_value = True
    detached_layer = Mock(qgs_layer=layer)
    tab._detached_layer = detached_layer
    try:
        tab.resize(200, 200)
        tab.show()
        qgis_app.processEvents()

        viewport = tab.text_edit.viewport()
        assert viewport is not None
        mouse_double_click = cast(Any, QTest.mouseDClick)
        mouse_double_click(
            viewport,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(),
        )

        layer.startEditing.assert_called_once_with()
        assert not tab.text_edit.isReadOnly()
    finally:
        tab.close()
        tab.deleteLater()


def test_empty_description_overlay_tracks_editor_content(qgis_app) -> None:
    tab = DescriptionTab()
    try:
        tab._feature_id = 1
        tab.resize(200, 200)
        tab.show()
        qgis_app.processEvents()

        tab._refresh_empty_description_overlay()
        assert tab._empty_description_overlay.isVisible()

        tab._text_editor.set_content("<p>Description</p>")
        tab._refresh_empty_description_overlay()
        assert not tab._empty_description_overlay.isVisible()
    finally:
        tab.close()
        tab.deleteLater()
