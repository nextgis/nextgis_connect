# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

from math import ceil
from typing import Optional

from qgis.gui import QgsProxyStyle
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QPainter, QPalette, QPixmap
from qgis.PyQt.QtWidgets import (
    QMenu,
    QStyle,
    QStyleOption,
    QStyleOptionMenuItem,
    QWidget,
)

from nextgis_connect.ui_kit.graphics import mix_colors


class MenuSectionStyle(QgsProxyStyle):
    """Recolor native section drawing only within a plugin menu."""

    @staticmethod
    def install(menu: QMenu) -> None:
        menu.ensurePolished()
        if isinstance(menu.style(), MenuSectionStyle):
            return
        # QgsProxyStyle clones the QGIS application style, including QgsAppStyle.
        # Never transfer ownership of the shared application style to this menu.
        style = MenuSectionStyle(menu)
        menu.setStyle(style)

    def drawControl(
        self,
        element: QStyle.ControlElement,
        option: Optional[QStyleOption],
        painter: Optional[QPainter],
        widget: Optional[QWidget] = None,
    ) -> None:
        if not (
            element == QStyle.ControlElement.CE_MenuItem
            and isinstance(option, QStyleOptionMenuItem)
            and option.menuItemType
            == QStyleOptionMenuItem.MenuItemType.Separator
            and option.text
        ):
            super().drawControl(element, option, painter, widget)
            return
        assert isinstance(option, QStyleOptionMenuItem)
        assert painter is not None
        if option.rect.isEmpty():
            return
        color = mix_colors(
            option.palette.color(QPalette.ColorRole.WindowText),
            option.palette.color(QPalette.ColorRole.Window),
            0.5,
        )
        ratio = painter.device().devicePixelRatioF()
        drawing = QPixmap(
            QSize(
                ceil(option.rect.width() * ratio),
                ceil(option.rect.height() * ratio),
            )
        )
        drawing.setDevicePixelRatio(ratio)
        drawing.fill(Qt.GlobalColor.transparent)
        native_painter = QPainter(drawing)
        try:
            native_painter.setRenderHints(painter.renderHints())
            native_painter.translate(-option.rect.topLeft())
            super().drawControl(element, option, native_painter, widget)
            # Fusion hard-codes the line color. Tint the native drawing instead
            # of replacing its geometry; retain glyph and line alpha coverage.
            native_painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            native_painter.fillRect(option.rect, color)
        finally:
            native_painter.end()
        painter.drawPixmap(option.rect.topLeft(), drawing)
