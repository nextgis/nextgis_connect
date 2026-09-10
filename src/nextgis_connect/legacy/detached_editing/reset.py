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

from typing import Optional, Protocol

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from nextgis_connect.platform.qgis.compat import combine_flags


class _ContainerMetadata(Protocol):
    has_changes: bool


class _ResettableContainer(Protocol):
    @property
    def metadata(self) -> Optional[_ContainerMetadata]: ...

    @property
    def is_edit_mode_enabled(self) -> bool: ...

    def reset_container(self) -> None: ...


def confirm_reset_container(
    container: _ResettableContainer, parent: Optional[QWidget]
) -> bool:
    """Ask for confirmation when resetting a detached layer loses changes."""
    translate = QCoreApplication.translate
    if container.is_edit_mode_enabled:
        QMessageBox.warning(
            parent,
            translate("DetachedLayerStatusDialog", "Reset layer"),
            translate(
                "DetachedLayerStatusDialog",
                "Synchronization is not possible while the layer is in edit"
                " mode",
            ),
        )
        return False

    metadata = container.metadata
    if metadata is not None and metadata.has_changes:
        answer = QMessageBox.question(
            parent,
            translate("DetachedLayerStatusDialog", "Possible data loss"),
            translate(
                "DetachedLayerStatusDialog",
                "The layer contains changes. If you continue, you will lose"
                " them forever.\n\nAre you sure you want to continue?",
            ),
            combine_flags(
                QMessageBox,
                "StandardButton",
                (
                    QMessageBox.StandardButton.Yes,
                    QMessageBox.StandardButton.No,
                ),
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

    container.reset_container()
    return True
