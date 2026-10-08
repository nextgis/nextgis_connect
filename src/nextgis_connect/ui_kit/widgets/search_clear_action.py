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

from qgis.PyQt.QtWidgets import QLineEdit, QToolButton

from nextgis_connect.ui_kit.icons import material_icon


def install_search_clear_action(line_edit: QLineEdit) -> None:
    line_edit.setClearButtonEnabled(False)
    action = line_edit.addAction(
        material_icon("backspace"),
        QLineEdit.ActionPosition.TrailingPosition,
    )
    button = next(
        button
        for button in line_edit.findChildren(QToolButton)
        if button.defaultAction() is action
    )

    def update_visibility(text: str) -> None:
        action.setVisible(bool(text))
        button.setVisible(bool(text))

    def clear() -> None:
        line_edit.clear()
        line_edit.textEdited.emit("")

    action.triggered.connect(clear)
    line_edit.textChanged.connect(update_visibility)
    update_visibility(line_edit.text())
