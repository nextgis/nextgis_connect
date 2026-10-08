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

from qgis.PyQt.QtCore import QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QWheelEvent
from qgis.PyQt.QtWidgets import QToolButton

from nextgis_connect.features.search.domain.resource_blueprint import (
    ResourceBlueprintTypeParser,
)
from nextgis_connect.legacy.search.resource_type_search_widget import (
    ResourceTypeSearchWidget,
)
from nextgis_connect.ui_kit.widgets.multi_select_combo_box import (
    MultiSelectComboBox,
)


def test_resource_type_widget_emits_or_query_for_checked_types(
    qgis_app,
) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    combobox = widget.findChild(MultiSelectComboBox)
    assert combobox is not None
    combobox.addItemWithCheckState(
        "Vector layer",
        Qt.CheckState.Checked,
        "vector_layer",
    )
    combobox.addItemWithCheckState(
        "Raster layer",
        Qt.CheckState.Checked,
        "raster_layer",
    )
    queries = []
    widget.search_requested.connect(queries.append)

    widget.search()

    assert queries == ["@type = vector_layer OR @type = raster_layer"]


def test_resource_type_widget_enables_clear_action_for_selection(
    qgis_app,
) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    combobox = widget.findChild(MultiSelectComboBox)
    assert combobox is not None
    line_edit = combobox.lineEdit()
    assert line_edit is not None
    clear_action = next(
        action
        for action in line_edit.actions()
        if action.text() == "Clear selected resource types"
    )
    assert not clear_action.isVisible()
    clear_button = next(
        button
        for button in line_edit.findChildren(QToolButton)
        if button.defaultAction() is clear_action
    )
    assert clear_button.isHidden()
    combobox.addItemWithCheckState(
        "Vector layer",
        Qt.CheckState.Unchecked,
        "vector_layer",
    )
    combobox.toggleItemCheckState(0)

    assert clear_action.isEnabled()
    assert clear_action.isVisible()
    assert not clear_button.isHidden()
    assert (
        combobox.toolTip()
        == 'Selected resource types:<ul style="-qt-list-indent:0; margin:0; margin-left:14px; padding:0;"><li>Vector layer</li></ul>'
    )

    resets = []
    widget.reset_requested.connect(lambda: resets.append(True))
    clear_action.trigger()

    assert resets == [True]
    assert not widget.has_search_data()
    assert not clear_action.isVisible()
    assert clear_button.isHidden()
    assert combobox.toolTip() == "Select one or more resource types"


def test_resource_type_widget_shows_resource_icons(qgis_app) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {
            "resource": {
                "cls": {
                    "enum": ["vector_layer", "raster_layer"],
                }
            }
        }
    )
    combobox = widget.findChild(MultiSelectComboBox)
    assert combobox is not None

    assert combobox.defaultText() == ""
    assert combobox.lineEdit().placeholderText() == "Resource type…"
    assert combobox.currentIndex() == -1
    assert not combobox.itemIcon(0).isNull()
    combobox.toggleItemCheckState(0)
    assert combobox._selection_icon_action.isVisible()
    assert not combobox._selection_icon_button.isHidden()
    combobox.toggleItemCheckState(1)
    assert not combobox._selection_icon_action.isVisible()
    assert combobox._selection_icon_button.isHidden()
    combobox.toggleItemCheckState(1)
    assert combobox._selection_icon_action.isVisible()
    initial_geometry = combobox.lineEdit().geometry()
    combobox.setCurrentIndex(0)
    assert combobox.lineEdit().geometry() == initial_geometry


def test_resource_type_widget_selects_type_with_wheel(qgis_app) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {"resource": {"cls": {"enum": ["vector_layer"]}}}
    )
    combobox = widget.findChild(MultiSelectComboBox)
    assert combobox is not None

    combobox.wheelEvent(
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

    assert widget.has_search_data()


def test_wheel_replaces_single_selection_and_ignores_multiple(
    qgis_app,
) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {"resource": {"cls": {"enum": ["raster_layer", "vector_layer"]}}}
    )
    combobox = widget.findChild(MultiSelectComboBox)
    assert combobox is not None
    combobox.toggleItemCheckState(0)

    def scroll() -> None:
        combobox.wheelEvent(
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

    scroll()
    assert combobox.checkedItemsData() == ["vector_layer"]
    combobox.setEnabled(False)
    scroll()
    assert combobox.checkedItemsData() == ["vector_layer"]
    combobox.showPopup()
    assert not combobox.view().isVisible()
    combobox.setEnabled(True)
    combobox.toggleItemCheckState(0)
    scroll()
    assert combobox.checkedItemsData() == ["raster_layer", "vector_layer"]
    assert combobox.currentIndex() == -1
    assert combobox.toolTip() == (
        "Selected resource types:"
        f'<ul style="-qt-list-indent:0; margin:0; margin-left:14px; padding:0;"><li>{combobox.itemText(0)}</li>'
        f"<li>{combobox.itemText(1)}</li></ul>"
    )
    widget.resize(400, 40)
    widget.grab()


def test_resource_types_are_grouped_and_sorted(qgis_app) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {
            "categories": {
                "layers_and_styles": {
                    "order": 20,
                    "label": "Layers and styles",
                },
                "maps_and_services": {
                    "order": 40,
                    "label": "Maps and services",
                },
            },
            "resources": {
                "webmap": {
                    "identity": "webmap",
                    "label": "Map",
                    "category": "maps_and_services",
                },
                "qgis_vector_style": {
                    "identity": "qgis_vector_style",
                    "label": "Style",
                    "category": "layers_and_styles",
                },
                "vector_layer": {
                    "identity": "vector_layer",
                    "label": "Vector",
                    "category": "layers_and_styles",
                },
                "raster_layer": {
                    "identity": "raster_layer",
                    "label": "Raster",
                    "category": "layers_and_styles",
                },
            },
        }
    )
    combo = widget.findChild(MultiSelectComboBox)
    assert combo is not None
    assert [combo.itemData(index) for index in range(combo.count())] == [
        None,
        "raster_layer",
        "vector_layer",
        "qgis_vector_style",
        None,
        "webmap",
    ]
    combo.toggleItemCheckState(0)
    combo.toggleItemCheckState(4)
    assert combo.checkedItemsData() == []
    assert combo.itemText(0) == "Layers and styles"
    assert combo.itemText(4) == "Maps and services"
    assert (
        not combo.model().flags(combo.model().index(0, 0))
        & Qt.ItemFlag.ItemIsSelectable
    )


def test_resource_group_order_is_taken_from_blueprint(qgis_app) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {
            "categories": {
                "custom": {"order": 1},
                "layers_and_styles": {"order": 99},
            },
            "resources": {
                "vector_layer": {
                    "identity": "vector_layer",
                    "category": "layers_and_styles",
                },
                "custom_resource": {
                    "identity": "custom_resource",
                    "category": "custom",
                },
            },
        }
    )
    combo = widget.findChild(MultiSelectComboBox)
    assert [combo.itemData(index) for index in range(combo.count())] == [
        None,
        "custom_resource",
        None,
        "vector_layer",
    ]


def test_types_without_suffix_are_last_and_tracker_keeps_category(
    qgis_app,
) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {
            "categories": {
                "layers": {"label": "Layers", "order": 20},
                "field": {"label": "Field", "order": 60},
            },
            "resources": {
                "vector_layer": {"label": "Vector", "category": "layers"},
                "basemap": {"label": "Basemap", "category": "layers"},
                "raster_layer": {"label": "Raster", "category": "layers"},
                "tracker": {"label": "Tracker", "category": "field"},
                "unknown": {"label": "Unknown"},
            },
        }
    )
    combo = widget.findChild(MultiSelectComboBox)
    assert [combo.itemText(index) for index in range(combo.count())] == [
        "Layers",
        "Raster",
        "Vector",
        "Basemap",
        "Field",
        "Tracker",
        "Other resources",
        "Unknown",
    ]


def test_sorting_compares_category_then_kind_then_label(qgis_app) -> None:
    del qgis_app
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(
        {
            "categories": {
                "first": {"label": "Z group", "order": 10},
                "second": {"label": "A group", "order": 20},
            },
            "resources": {
                "tracker": {"label": "A tracker", "category": "second"},
                "vector_layer": {"label": "B vector", "category": "first"},
                "raster_layer": {"label": "A raster", "category": "first"},
                "wms_connection": {
                    "label": "Z connection",
                    "category": "first",
                },
                "basemap": {"label": "A basemap", "category": "first"},
                "wms_service": {"label": "A service", "category": "first"},
            },
        }
    )
    combo = widget.findChild(MultiSelectComboBox)
    assert [combo.itemText(index) for index in range(combo.count())] == [
        "Z group",
        "Z connection",
        "A raster",
        "B vector",
        "A service",
        "A basemap",
        "A group",
        "A tracker",
    ]


def test_type_list_matches_completion_and_sort_uses_labels(
    qgis_app,
) -> None:
    del qgis_app
    blueprint = {
        "categories": {"layers": {"order": 20, "label": "Layers"}},
        "resources": {
            "resource": {
                "identity": "resource",
                "label": "Abstract resource",
                "category": "layers",
            },
            "vector_layer": {
                "identity": "vector_layer",
                "label": "A vector",
                "category": "layers",
            },
            "basemap_layer": {
                "identity": "basemap_layer",
                "label": "B basemap",
                "category": "layers",
            },
            "raster_layer": {
                "identity": "raster_layer",
                "label": "Z raster",
                "category": "layers",
            },
        },
    }
    widget = ResourceTypeSearchWidget(None)
    widget._ResourceTypeSearchWidget__set_resource_types(blueprint)
    combo = widget.findChild(MultiSelectComboBox)
    identities = [
        combo.itemData(index)
        for index in range(combo.count())
        if combo.itemData(index) is not None
    ]
    assert identities == ["vector_layer", "basemap_layer", "raster_layer"]
    assert sorted(identities) == ResourceBlueprintTypeParser().parse(blueprint)
