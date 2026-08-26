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

from pathlib import Path
from typing import Optional

from qgis.PyQt.QtCore import QObject, QRect, QRectF
from qgis.PyQt.QtGui import QColor, QLinearGradient, QPainter, QPalette, QPen

from nextgis_connect.ui_kit.graphics.decorator import (
    NextgisDecorator,
    mix_colors,
)
from nextgis_connect.ui_kit.graphics.svg_renderer import (
    CustomSvgRenderer,
)


class NextgisBackgroundPainter(QObject):
    """Paint NextGIS themed backgrounds.

    Draw grid, isoline SVG, and gradient layers for widgets and header
    areas using the active palette.
    """

    _DARK_GRID_ALPHA = 50
    _LIGHT_GRID_ALPHA = 64

    def __init__(
        self,
        isolines_path: Path,
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialize the background painter.

        :param isolines_path: SVG path used for isoline decoration.
        :param parent: Parent object.
        """
        super().__init__(parent)
        self._isolines_renderer = CustomSvgRenderer(
            isolines_path,
            self,
            themed=True,
        )

    def paint_widget_background(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        palette: Optional[QPalette] = None,
    ) -> None:
        """Paint a full widget background.

        :param painter: Painter used for rendering.
        :param rect: Rectangle to paint.
        :param palette: Palette used for colors.
        """
        active_palette = NextgisDecorator.system_palette(palette)

        self._draw_grid(painter, rect, active_palette)
        self._draw_isolines(painter, rect, opacity=0.50)
        self._draw_vertical_gradient(painter, rect, active_palette)

    def paint_header_background(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        palette: Optional[QPalette] = None,
    ) -> None:
        """Paint a header background.

        :param painter: Painter used for rendering.
        :param rect: Rectangle to paint.
        :param palette: Palette used for colors.
        """
        active_palette = NextgisDecorator.system_palette(palette)

        painter.save()
        painter.setClipRect(rect)
        self._draw_grid(painter, rect, active_palette)
        self._draw_isolines(painter, rect, opacity=0.25)
        self._draw_header_gradient(painter, rect, active_palette)
        painter.restore()

    def _draw_grid(
        self,
        painter: QPainter,
        rect: QRect,
        palette: QPalette,
    ) -> None:
        color = self._grid_color(palette)

        pen = QPen(color)
        pen.setWidthF(0.5)
        painter.setPen(pen)

        grid_size = NextgisDecorator.GRID_SIZE
        x_coord = rect.left() - (rect.left() % grid_size)
        y_coord = rect.top() - (rect.top() % grid_size)

        while x_coord < rect.right() + grid_size:
            shifted_x = x_coord + grid_size // 2
            painter.drawLine(shifted_x, rect.top(), shifted_x, rect.bottom())
            x_coord += grid_size

        while y_coord < rect.bottom() + grid_size:
            shifted_y = y_coord + grid_size // 2
            painter.drawLine(rect.left(), shifted_y, rect.right(), shifted_y)
            y_coord += grid_size

    @classmethod
    def _grid_color(cls, palette: QPalette) -> QColor:
        color = NextgisDecorator.system_muted_text_color(palette)
        alpha = (
            cls._DARK_GRID_ALPHA
            if NextgisDecorator.is_dark_theme(palette)
            else cls._LIGHT_GRID_ALPHA
        )
        color.setAlpha(alpha)
        return color

    def _draw_isolines(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        opacity: float,
    ) -> None:
        isolines_size = self._isolines_renderer.default_size()
        isolines_height = isolines_size.height()
        isolines_width = isolines_size.width()

        isolines_rect = QRectF(
            rect.left() + (rect.width() - isolines_width) / 2,
            rect.top() + (rect.height() - isolines_height) / 2,
            isolines_width,
            isolines_height,
        )

        painter.save()
        painter.setOpacity(opacity)
        self._isolines_renderer.render(painter, isolines_rect)
        painter.restore()

    def _draw_vertical_gradient(
        self,
        painter: QPainter,
        rect: QRect,
        palette: QPalette,
    ) -> None:
        background_color = NextgisDecorator.system_window_color(palette)
        surface_color = NextgisDecorator.system_base_color(palette)
        top_color = mix_colors(background_color, surface_color, 0.75)

        transparent_color = QColor(top_color)
        transparent_color.setAlpha(0)
        semi_transparent_color = QColor(top_color)
        semi_transparent_color.setAlpha(128)

        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gradient.setColorAt(0.0, transparent_color)
        gradient.setColorAt(0.2, semi_transparent_color)
        gradient.setColorAt(1.0, top_color)
        painter.fillRect(rect, gradient)

    def _draw_header_gradient(
        self,
        painter: QPainter,
        rect: QRect,
        palette: QPalette,
    ) -> None:
        base_color = NextgisDecorator.system_base_color(palette)
        window_color = NextgisDecorator.system_window_color(palette)
        accent_color = mix_colors(
            base_color,
            NextgisDecorator.brand_color(),
            0.16,
        )
        bottom_color = mix_colors(window_color, base_color, 0.90)

        highlight_color = QColor(accent_color)
        highlight_color.setAlpha(210)
        bottom_color.setAlpha(150)

        gradient = QLinearGradient(
            rect.left(),
            rect.top(),
            rect.right(),
            rect.bottom(),
        )
        gradient.setColorAt(0.0, highlight_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.fillRect(rect, gradient)
