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

from qgis.PyQt.QtCore import QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QWheelEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QToolButton, QWidget

from nextgis_connect.legacy.search.search_panel import SearchPanel
from nextgis_connect.legacy.search.text_search_line_edit import (
    TextSearchLineEdit,
)
from nextgis_connect.legacy.search.utils import SearchType
from nextgis_connect.ui_kit.widgets.multi_select_combo_box import (
    MultiSelectComboBox,
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


def test_search_button_requires_data_from_active_filter(
    qgis_app,
    reset_qgis_settings,
) -> None:
    del qgis_app, reset_qgis_settings
    parent = QWidget()
    panel = SearchPanel(None, parent)
    search_button = next(
        button
        for button in panel.findChildren(QToolButton)
        if button.toolTip() == "Run resource search"
    )
    text_widget = panel._SearchPanel__text_search_widget
    metadata_widget = panel._SearchPanel__metadata_search_widget
    resource_type_widget = panel._SearchPanel__resource_type_search_widget
    resource_type_combobox = resource_type_widget.findChild(
        MultiSelectComboBox
    )
    assert resource_type_combobox is not None

    assert not search_button.isEnabled()
    text_widget.setText("Roads")
    assert search_button.isEnabled()
    panel.set_type(SearchType.ByMetadata)
    assert not search_button.isEnabled()
    metadata_widget._MetadataSearchWidget__metadata_key_combobox.setEditText(
        "priority"
    )
    assert not search_button.isEnabled()
    metadata_widget._MetadataSearchWidget__metadata_value_lineedit.setText(
        "high"
    )
    assert search_button.isEnabled()

    panel.set_type(SearchType.ByResourceType)
    assert not search_button.isEnabled()
    resource_type_widget._ResourceTypeSearchWidget__set_resource_types(
        {"resource": {"cls": {"enum": ["vector_layer"]}}}
    )
    resource_type_combobox.wheelEvent(
        QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
    assert search_button.isEnabled()


def test_pending_criteria_follow_applied_query(
    qgis_app, reset_qgis_settings
) -> None:
    del qgis_app, reset_qgis_settings
    parent = QWidget()
    panel = SearchPanel(None, parent)
    panel.set_type(SearchType.ByDisplayName)
    pending = []
    panel.criteria_pending.connect(pending.append)
    text_widget = panel.findChild(TextSearchLineEdit)
    text_widget.setText("Roads")
    assert pending[-1] is False
    assert panel._SearchPanel__search_button._highlighted
    panel.mark_search_applied()
    assert pending[-1] is False
    text_widget.setText("Buildings")
    assert pending[-1] is True
    assert panel._SearchPanel__search_button._highlighted
    text_widget.setText("Roads")
    assert pending[-1] is False
    text_widget.clear()
    panel.mark_search_reset()
    assert pending[-1] is False


def test_metadata_combo_enter_requests_search(
    qgis_app, reset_qgis_settings
) -> None:
    del qgis_app, reset_qgis_settings
    parent = QWidget()
    panel = SearchPanel(None, parent)
    panel.set_type(SearchType.ByMetadata)
    widget = panel._SearchPanel__metadata_search_widget
    combo = widget._MetadataSearchWidget__metadata_key_combobox
    combo.setEditText("priority")
    widget._MetadataSearchWidget__metadata_value_lineedit.setText("high")
    searches = []
    panel.search_requested.connect(searches.append)
    QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Return)
    assert searches == ['@metadata["priority"] = "high"']
