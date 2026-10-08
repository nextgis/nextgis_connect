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

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest

from nextgis_connect.ui_kit.widgets.multi_select_combo_box import (
    MultiSelectComboBox,
)


def test_popup_preserves_rows_and_toggles_checks(qgis_app) -> None:
    combo = MultiSelectComboBox()
    combo.setToolTip("Choose types")
    combo.addItemWithCheckState(
        "Vector <layer>", Qt.CheckState.Unchecked, "vector"
    )
    combo.addItemWithCheckState(
        "Raster layer", Qt.CheckState.Unchecked, "raster"
    )
    combo.resize(300, 30)
    combo.show()
    qgis_app.processEvents()
    QTest.mouseClick(combo.lineEdit(), Qt.MouseButton.LeftButton)
    qgis_app.processEvents()

    view = combo.view()
    assert view.isVisible()
    assert view.model().rowCount() == 2
    assert view.model().index(0, 0).data() == "Vector <layer>"
    first_rect = view.visualRect(view.model().index(0, 0))
    assert not first_rect.isEmpty()
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=first_rect.center()
    )
    assert combo.checkedItemsData() == ["vector"]
    assert combo.lineEdit().text() == "Vector <layer>"
    assert (
        combo.toolTip()
        == 'Choose types:<ul style="-qt-list-indent:0; margin:0; margin-left:14px; padding:0;"><li>Vector &lt;layer&gt;</li></ul>'
    )
    assert view.isVisible()

    second_rect = view.visualRect(view.model().index(1, 0))
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=second_rect.center()
    )
    assert combo.checkedItemsData() == ["vector", "raster"]
    assert view.model().index(0, 0).data() == "Vector <layer>"
    assert view.model().index(1, 0).data() == "Raster layer"
    assert combo.lineEdit().text() == "Vector <layer>, Raster layer"
    returns = []
    combo.returnPressed.connect(lambda: returns.append(True))
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert returns == [True]
    assert not view.isVisible()
    combo.clear_action.trigger()
    assert combo.checkedItemsData() == []
    assert combo.lineEdit().text() == ""
    assert combo.toolTip() == "Choose types"
    combo.hidePopup()
    combo.close()


def test_group_header_cannot_be_selected_in_open_popup(qgis_app) -> None:
    combo = MultiSelectComboBox()
    combo.add_group_header("Layers and styles")
    combo.addItemWithCheckState(
        "Vector layer", Qt.CheckState.Unchecked, "vector"
    )
    combo.show()
    combo.showPopup()
    qgis_app.processEvents()
    view = combo.view()
    index = view.model().index(0, 0)
    assert not view.model().flags(index) & Qt.ItemFlag.ItemIsSelectable
    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=view.visualRect(index).center(),
    )
    assert combo.checkedItemsData() == []
    assert not view.selectionModel().isSelected(index)
    combo.hidePopup()
    combo.close()
