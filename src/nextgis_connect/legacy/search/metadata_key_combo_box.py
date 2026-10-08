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

from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import QComboBox, QWidget

from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.ui_kit.widgets.search_clear_action import (
    install_search_clear_action,
)


class MetadataKeyComboBox(QComboBox):
    """
    A QComboBox subclass for selecting metadata keys with an editable line edit.
    """

    reset_requested = pyqtSignal()
    focus_value = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the MetadataKeyComboBox.

        :param parent: The parent widget. Defaults to None.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setPlaceholderText(self.tr("Metadata key…"))
        line_edit = self.lineEdit()
        assert line_edit is not None
        install_search_clear_action(line_edit)
        self.lineEdit().textEdited.connect(self.__reset_if_empty)
        self.lineEdit().installEventFilter(self)

        self.update_values()

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if a0 is self.lineEdit() and isinstance(a1, QKeyEvent):
            if a1.type() == QEvent.Type.KeyPress and a1.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                if self.isEnabled():
                    self.focus_value.emit()
                return True
        return super().eventFilter(a0, a1)

    @pyqtSlot()
    def update_values(self) -> None:
        """
        Updates the available metadata keys in the combo box.

        This method clears the current items, retrieves metadata keys
        from SearchSettings, and repopulates the combo box while maintaining
        the user's current text input.
        """
        backup_text = self.lineEdit().text()

        self.clear()
        settings = SearchSettings()
        self.addItems(settings.metadata_keys)

        self.lineEdit().setText(backup_text)

    @pyqtSlot(str)
    def __reset_if_empty(self, search_string: str) -> None:
        if len(search_string) != 0:
            return

        self.reset_requested.emit()
