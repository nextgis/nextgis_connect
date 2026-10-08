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

from typing import Optional

from qgis.PyQt.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from qgis.PyQt.QtGui import QIcon, QPainter, QPaintEvent, QPen
from qgis.PyQt.QtWidgets import QPushButton, QToolButton, QWidget

from nextgis_connect.ui_kit.graphics import NextgisDecorator, NextgisRadius
from nextgis_connect.ui_kit.graphics.decorator import NextgisBrandColor


class HighlightableToolButton(QToolButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._highlighted = False
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setEndValue(0.0)
        self._pulse.setDuration(2400)
        self._pulse.setLoopCount(-1)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.valueChanged.connect(lambda _: self.update())
        self._pulsating = False
        self._circle_highlighted = False
        self._circular_appearance = False

    def setCircularAppearance(self, circular: bool) -> None:
        self._circular_appearance = circular
        self.update()

    def enterEvent(self, a0) -> None:
        super().enterEvent(a0)
        self.update()

    def leaveEvent(self, a0) -> None:
        super().leaveEvent(a0)
        self.update()

    def setCircleHighlighted(self, highlighted: bool) -> None:
        self._circle_highlighted = highlighted
        self.update()

    def setPulsating(self, pulsating: bool) -> None:
        self._pulsating = pulsating
        if pulsating and self.isVisible():
            self._pulse.start()
        else:
            self._pulse.stop()
        self.update()

    def showEvent(self, a0) -> None:
        super().showEvent(a0)
        if self._pulsating:
            self._pulse.start()

    def hideEvent(self, a0) -> None:
        self._pulse.stop()
        super().hideEvent(a0)

    def setHighlighted(self, highlighted: bool) -> None:
        self._highlighted = highlighted
        self.update()

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        if not self._circular_appearance:
            super().paintEvent(a0)
        else:
            icon_painter = QPainter(self)
            icon_rect = self.rect()
            icon_rect.setSize(self.iconSize())
            icon_rect.moveCenter(self.rect().center())
            self.icon().paint(
                icon_painter,
                icon_rect,
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
                QIcon.State.Off,
            )
            icon_painter.end()
        circle_active = self._circle_highlighted or (
            self._circular_appearance and self.underMouse()
        )
        if not (self._highlighted or self._pulsating or circle_active):
            return
        color = (
            NextgisDecorator.brand_color(NextgisBrandColor.ACTIVE)
            if self.isDown()
            else NextgisDecorator.brand_color()
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pulsating or circle_active:
            color.setAlphaF(
                1.0 if circle_active else float(self._pulse.currentValue())
            )
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Circular Material icons have a 10% transparent inset per side.
            icon_scale = 0.8 if self._circular_appearance else 1.0
            diameter = min(
                self.iconSize().width() * icon_scale + 2,
                self.iconSize().height() * icon_scale + 2,
                self.width() - 2,
                self.height() - 2,
            )
            painter.drawEllipse(
                QRectF(
                    (self.width() - diameter) / 2,
                    (self.height() - diameter) / 2,
                    diameter,
                    diameter,
                )
            )
            if not self._highlighted:
                return
            color.setAlpha(255)
        pen = QPen(color, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = NextgisDecorator.radius(NextgisRadius.BUTTON)
        painter.drawRoundedRect(
            self.rect().adjusted(1, 1, -1, -1), radius, radius
        )


class HighlightablePushButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.__highlighted = False

    def setHighlighted(self, highlighted: bool) -> None:
        if self.__highlighted == highlighted:
            return

        self.__highlighted = highlighted
        self.update()

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        super().paintEvent(a0)

        if not self.__highlighted:
            return

        color = NextgisDecorator.brand_color()
        if self.isDown():
            color = NextgisDecorator.brand_color(NextgisBrandColor.ACTIVE)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
