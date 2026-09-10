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

from qgis.PyQt.QtWidgets import QHBoxLayout, QPushButton, QWidget

from nextgis_connect.legacy.notifier.message_bar_notifier import (
    MessageBarNotifier,
)
from nextgis_connect.platform.qgis.errors import ContainerError, NgwError


def test_network_error_has_diagnostics_button(qgis_app) -> None:
    del qgis_app

    error = NgwError("Connection error", is_network_problem=True)
    widget = QWidget()
    widget.setLayout(QHBoxLayout())

    notifier = MessageBarNotifier(None)
    notifier._add_error_buttons(error, widget)

    button_texts = [
        button.text() for button in widget.findChildren(QPushButton)
    ]

    assert "Run diagnostics" in button_texts
    assert "Open settings" not in button_texts

    widget.deleteLater()
    notifier.deleteLater()


def test_error_action_is_rendered_as_button(qgis_app) -> None:
    del qgis_app

    action_calls = []
    error = ContainerError()
    error.add_action("Reset layer", lambda: action_calls.append("reset"))
    widget = QWidget()
    widget.setLayout(QHBoxLayout())

    notifier = MessageBarNotifier(None)
    notifier._add_error_buttons(error, widget)

    reset_button = next(
        button
        for button in widget.findChildren(QPushButton)
        if button.text() == "Reset layer"
    )
    reset_button.click()

    assert action_calls == ["reset"]

    widget.deleteLater()
    notifier.deleteLater()
