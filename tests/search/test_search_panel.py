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
# with this program.  If not, see <https://www.gnu.org/licenses/>.

from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.legacy.search.search_panel import SearchPanel
from nextgis_connect.legacy.search.text_search_line_edit import (
    TextSearchLineEdit,
)


def test_search_panel_parents_text_search_widget_during_construction(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    parents = []
    initialize_text_search_widget = TextSearchLineEdit.__init__

    def record_parent(widget, connection_id, parent=None) -> None:
        parents.append(parent)
        initialize_text_search_widget(widget, connection_id, parent)

    monkeypatch.setattr(TextSearchLineEdit, "__init__", record_parent)

    panel = SearchPanel(None, QWidget())

    assert parents == [panel]
