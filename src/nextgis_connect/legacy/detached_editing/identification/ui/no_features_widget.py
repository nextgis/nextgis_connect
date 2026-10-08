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

from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.legacy.detached_editing.identification.ui.empty_state_overlay import (
    EmptyStateOverlay,
)
from nextgis_connect.ui_kit.icons import material_icon


class NoFeaturesWidget(EmptyStateOverlay):
    """Show an informational message over an empty identification tab.

    Render a centered informational icon and text that explains why the tab
    has no content.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the placeholder widget.

        :param parent: Parent widget owning the placeholder.
        """
        super().__init__(parent)
        self._label = self.text_label

        palette = self.palette()
        disabled_text_color = palette.color(
            palette.ColorGroup.Disabled,
            palette.ColorRole.Text,
        ).name()
        self.set_appearance(disabled_text_color, "transparent")
        self.set_icon(
            material_icon(
                "info",
                color=disabled_text_color,
                size=self.ICON_SIZE,
            )
        )
        self.set_message("No features were found at the click location.")

    def set_message(self, message: str) -> None:
        """Set the text shown in the overlay."""
        super().set_message(message)
