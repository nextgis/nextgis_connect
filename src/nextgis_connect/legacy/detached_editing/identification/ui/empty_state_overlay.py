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

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from nextgis_connect.ui_kit.icons import draw_icon


class EmptyStateOverlay(QWidget):
    """Render a centered icon and message over an empty view."""

    ICON_SIZE = 32

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the overlay.

        :param parent: Parent widget owning the overlay.
        """
        super().__init__(parent)
        self.setObjectName("emptyStateOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("emptyStateIcon")
        self._icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._text_label = QLabel(self)
        self._text_label.setObjectName("emptyStateText")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            self._text_label.sizePolicy().verticalPolicy(),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(
            self._text_label, alignment=Qt.AlignmentFlag.AlignCenter
        )

    @property
    def text_label(self) -> QLabel:
        """Return the label displaying the overlay message."""
        return self._text_label

    def set_appearance(self, text_color: str, background_color: str) -> None:
        """Set the text and background colors of the overlay."""
        self.setStyleSheet(
            f"""
            QWidget#emptyStateOverlay {{
                background-color: {background_color};
            }}
            QLabel#emptyStateText {{
                color: {text_color};
                font-size: 14px;
                padding: 0 8px 4px 8px;
            }}
            """
        )

    def set_icon(self, icon: QIcon) -> None:
        """Set the icon displayed above the message."""
        draw_icon(self._icon_label, icon, size=self.ICON_SIZE)

    def set_message(self, message: str) -> None:
        """Set the text displayed by the overlay."""
        self._text_label.setText(message)
