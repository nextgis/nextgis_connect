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
from qgis.gui import QgsProxyStyle
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QMenu, QProxyStyle

from nextgis_connect.ui_kit.widgets.menu_section_style import MenuSectionStyle


@pytest.fixture
def native_section_app(qgis_app):
    style = qgis_app.style()
    while isinstance(style, QProxyStyle):
        style = style.baseStyle()
    if style is None or style.objectName().lower() not in ("breeze", "fusion"):
        pytest.skip("Run with QT_STYLE_OVERRIDE=Breeze or Fusion")
    return qgis_app


@pytest.mark.parametrize(
    "background,foreground", [("#222222", "#eeeeee"), ("#eeeeee", "#222222")]
)
def test_section_setup_does_not_override_theme_separator_rules(
    qgis_app,
    background,
    foreground,
):
    menu = QMenu()
    menu.setStyleSheet(
        f"QMenu {{ background: {background}; color: {foreground}; }}"
        "QMenu::separator { height: 2px; border: none;"
        "border-bottom: 1px solid #111111; margin-left: 10px; margin-right: 5px; }"
    )
    menu.addAction("Item")
    section = menu.addSection("Section")
    menu.addAction("Other item")
    menu.show()
    qgis_app.processEvents()
    original_rect = menu.actionGeometry(section)
    original_sheet = menu.styleSheet()
    original_image = menu.grab().toImage()
    MenuSectionStyle.install(menu)
    qgis_app.processEvents()
    assert menu.actionGeometry(section) == original_rect
    assert menu.styleSheet() == original_sheet
    assert menu.grab().toImage() == original_image
    menu.close()
    menu.deleteLater()


@pytest.mark.parametrize(
    "background,foreground", [("#232629", "#eff0f1"), ("#eff0f1", "#232629")]
)
def test_native_heading_is_recolored_without_changing_other_widgets(
    native_section_app,
    background,
    foreground,
):
    qgis_app = native_section_app
    menu = QMenu()
    qgis_style = QgsProxyStyle(menu)
    qgis_style.setObjectName("QgisMenuStyle")
    menu.setStyle(qgis_style)
    palette = menu.palette()
    for role in (
        QPalette.ColorRole.Window,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.Button,
    ):
        palette.setColor(role, QColor(background))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(role, QColor(foreground))
    menu.setPalette(palette)
    menu.setMinimumWidth(400)
    ordinary_action = menu.addAction("Add layer")
    section = menu.addSection("Modify QGIS layer")
    menu.addAction("Apply style")
    separator = menu.addSeparator()
    menu.addAction("Replace styles")
    menu.show()
    qgis_app.processEvents()
    original_rects = [menu.actionGeometry(action) for action in menu.actions()]
    original_image = menu.grab().toImage()
    original_sheet = menu.styleSheet()
    application_style = qgis_app.style()
    application_palette = qgis_app.palette()
    menu_palette = menu.palette()
    other_menu = QMenu()
    other_menu.addAction("Other plugin or QGIS")
    other_menu.addSection("Unchanged section")
    other_menu.show()
    qgis_app.processEvents()
    other_style = other_menu.style()
    other_image = other_menu.grab().toImage()

    MenuSectionStyle.install(menu)
    qgis_app.processEvents()
    image = menu.grab().toImage()
    assert isinstance(menu.style(), MenuSectionStyle)
    assert qgis_app.style() is application_style
    assert qgis_app.palette() == application_palette
    assert menu.palette() == menu_palette
    assert other_menu.style() is other_style
    assert other_menu.grab().toImage() == other_image
    assert [
        menu.actionGeometry(action) for action in menu.actions()
    ] == original_rects
    assert menu.styleSheet() == original_sheet
    assert image.copy(
        menu.actionGeometry(ordinary_action)
    ) == original_image.copy(menu.actionGeometry(ordinary_action))
    assert image.copy(menu.actionGeometry(separator)) == original_image.copy(
        menu.actionGeometry(separator)
    )

    rect = menu.actionGeometry(section)
    background_color = QColor(background)
    original_mask = {
        (x, y)
        for x in range(rect.left(), rect.right() + 1)
        for y in range(rect.top(), rect.bottom() + 1)
        if original_image.pixelColor(x, y) != background_color
    }
    mask = {
        (x, y)
        for x in range(rect.left(), rect.right() + 1)
        for y in range(rect.top(), rect.bottom() + 1)
        if image.pixelColor(x, y) != background_color
    }
    # Recoloring can round faint antialiased text pixels to the background.
    # The native text bounds and the line's footprint must not move.
    assert (min(x for x, _ in mask), max(x for x, _ in mask)) == (
        min(x for x, _ in original_mask),
        max(x for x, _ in original_mask),
    )
    assert (min(y for _, y in mask), max(y for _, y in mask)) == (
        min(y for _, y in original_mask),
        max(y for _, y in original_mask),
    )
    assert any(x < rect.center().x() for x, _ in mask)
    line_pixels = [
        (x, y) for x, y in mask if rect.right() - 40 < x < rect.right() - 12
    ]
    assert line_pixels
    assert set(line_pixels) == {
        (x, y)
        for x, y in original_mask
        if rect.right() - 40 < x < rect.right() - 12
    }
    # Native styles can use translucent lines (Fusion) or opaque ones (Breeze).
    # Recolor the line without changing the theme's alpha coverage.
    assert any(
        image.pixelColor(x, y) != original_image.pixelColor(x, y)
        for x, y in line_pixels
    )
    assert image.copy(rect) != original_image.copy(rect)
    menu.close()
    menu.deleteLater()
    other_menu.close()
    other_menu.deleteLater()
