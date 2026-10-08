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

from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import (
    QMenu,
    QProxyStyle,
    QStyle,
    QToolBar,
    QToolButton,
)

from nextgis_connect.ui_kit.icons import material_icon
from nextgis_connect.ui_kit.widgets.tool_button_preview import (
    render_menu_button_preview,
)


def test_preview_accepts_native_toolbar_button(qgis_app):
    toolbar = QToolBar()
    action = toolbar.addAction(material_icon("help"), "Search")
    action.setCheckable(True)
    action.setChecked(True)
    action.setMenu(QMenu(toolbar))
    button = toolbar.widgetForAction(action)
    assert isinstance(button, QToolButton)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    toolbar.show()
    qgis_app.processEvents()
    preview = render_menu_button_preview(button)
    assert not preview.isNull()
    assert preview.width() / preview.devicePixelRatioF() == button.width()
    assert action.isChecked()
    toolbar.close()


def test_preview_uses_native_style_and_does_not_enable_source(
    qgis_app, monkeypatch
):
    captured_states = []

    class RecordingStyle(QProxyStyle):
        def drawComplexControl(self, control, option, painter, widget=None):
            if control == QStyle.ComplexControl.CC_ToolButton:
                captured_states.append(
                    (option.state, option.activeSubControls)
                )
            super().drawComplexControl(control, option, painter, widget)

    button = QToolButton()
    style = RecordingStyle("Fusion")
    style.setParent(button)
    button.setStyle(style)
    button.setIcon(material_icon("help"))
    button.setMenu(QMenu(button))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    button.resize(42, 28)
    button.setEnabled(False)
    monkeypatch.setattr(button, "devicePixelRatioF", lambda: 2.0)
    preview = render_menu_button_preview(button)
    assert not preview.isNull()
    assert preview.width() == 84
    assert preview.height() == 56
    assert preview.devicePixelRatioF() == 2.0
    assert captured_states[0][0] & QStyle.StateFlag.State_Enabled
    assert captured_states[0][1] == QStyle.SubControl.SC_ToolButtonMenu
    assert not button.isEnabled()
    button.close()


def test_preview_tracks_source_palette(qgis_app):
    button = QToolButton()
    style = QProxyStyle("Fusion")
    style.setParent(button)
    button.setStyle(style)
    button.setIcon(material_icon("help"))
    button.setMenu(QMenu(button))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    button.resize(42, 28)
    light = render_menu_button_preview(button).toImage()
    palette = QPalette(button.palette())
    from qgis.PyQt.QtGui import QColor

    palette.setColor(QPalette.ColorRole.Button, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
    button.setPalette(palette)
    dark = render_menu_button_preview(button).toImage()
    assert light != dark
    button.close()
