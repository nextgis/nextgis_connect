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

from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from nextgis_connect.ui_kit.graphics import NextgisDecorator, NextgisRadius
from nextgis_connect.ui_kit.icons import material_icon


class InformationNotice(QFrame):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("NgConnectInformationNotice")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self._icon = QLabel(self)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._icon)
        label = QLabel(text, self)
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        self._update_colors()

    def changeEvent(self, a0: Optional[QEvent]) -> None:
        super().changeEvent(a0)
        if (
            a0 is not None
            and a0.type() == QEvent.Type.PaletteChange
            and hasattr(self, "_icon")
        ):
            self._update_colors()

    def _update_colors(self) -> None:
        color = QColor(
            "#2A3A49" if NextgisDecorator.is_dark_theme() else "#D7DEE5"
        )
        self.setStyleSheet(
            "QFrame#NgConnectInformationNotice {"
            f"border: 1px solid {color.name()};"
            f"border-radius: {NextgisDecorator.radius(NextgisRadius.BUTTON)}px;"
            "}"
        )
        self._icon.setPixmap(
            material_icon(
                "info", color=NextgisDecorator.brand_color().name(), size=20
            ).pixmap(20, 20)
        )
