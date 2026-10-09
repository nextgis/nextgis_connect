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
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest

from nextgis_connect.legacy.search.text_search_line_edit import (
    SearchTagDelegate,
    TextSearchLineEdit,
)


@pytest.mark.parametrize(
    "key", [Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter]
)
@pytest.mark.parametrize("target", ["popup", "input"])
def test_metadata_completion_consumes_accept_key(
    qgis_app, key, target, monkeypatch
):
    widget = TextSearchLineEdit(None)
    widget.show()
    searches = []
    widget.search_requested.connect(searches.append)
    widget.setText("@met")
    widget._TextSearchLineEdit__completer_model.set_prefix("@met")
    qgis_app.processEvents()
    popup = widget._completer.popup()
    index = popup.model().index(0, 0)
    assert index.data() == "@metadata"
    assert index.data(
        widget._TextSearchLineEdit__completer_model.TAG_DESCRIPTION_ROLE
    )
    popup.setCurrentIndex(index)
    popup_calls = []
    completer_popup = type(widget._completer).popup

    def track_popup_access(completer):
        popup_calls.append(completer)
        return completer_popup(completer)

    monkeypatch.setattr(type(widget._completer), "popup", track_popup_access)
    QTest.keyClick(popup if target == "popup" else widget, key)
    qgis_app.processEvents()
    assert widget.text() == "@metadata["
    assert not searches
    assert not popup.isVisible()
    assert not popup_calls
    widget.close()


def test_tag_delegate_survives_popup_opening(qgis_app):
    widget = TextSearchLineEdit(None)
    widget.resize(330, 30)
    widget.show()
    model = widget._TextSearchLineEdit__completer_model
    model.set_prefix("@")
    qgis_app.processEvents()
    popup = widget._completer.popup()
    assert popup.isVisible()
    assert isinstance(popup.itemDelegate(), SearchTagDelegate)
    assert popup.model().index(0, 0).data() == "@id"
    model.set_prefix("@ty")
    qgis_app.processEvents()
    assert isinstance(popup.itemDelegate(), SearchTagDelegate)
    widget.close()
