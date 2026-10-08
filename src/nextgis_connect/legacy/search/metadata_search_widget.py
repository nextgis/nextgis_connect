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

from qgis.PyQt.QtCore import pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from nextgis_connect.legacy.search.metadata_key_combo_box import (
    MetadataKeyComboBox,
)
from nextgis_connect.legacy.search.metadata_search_line_edit import (
    MetadataSearchLineEdit,
)


class MetadataSearchWidget(QWidget):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()
    search_data_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # Combobox
        self.__metadata_key_combobox = MetadataKeyComboBox()
        combobox_size_policy = self.__metadata_key_combobox.sizePolicy()
        combobox_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        combobox_size_policy.setHorizontalStretch(2)
        self.__metadata_key_combobox.setSizePolicy(combobox_size_policy)
        self.__metadata_key_combobox.reset_requested.connect(
            self.reset_requested
        )
        self.__metadata_key_combobox.editTextChanged.connect(
            self.__on_search_data_changed
        )
        layout.addWidget(self.__metadata_key_combobox)

        # Label
        equal_label = QLabel("=")
        layout.addWidget(equal_label)

        # Lineedit
        self.__metadata_value_lineedit = MetadataSearchLineEdit()
        self.__metadata_value_lineedit.search_requested.connect(self.search)
        self.__metadata_value_lineedit.reset_requested.connect(
            self.reset_requested
        )
        self.__metadata_value_lineedit.textChanged.connect(
            self.__on_search_data_changed
        )
        lineedit_size_policy = self.__metadata_value_lineedit.sizePolicy()
        lineedit_size_policy.setHorizontalStretch(3)
        self.__metadata_value_lineedit.setSizePolicy(lineedit_size_policy)
        self.__metadata_key_combobox.focus_value.connect(
            lambda: self.__metadata_value_lineedit.setFocus()
        )
        self.__metadata_key_combobox.focus_value.connect(
            self.__search_if_ready
        )
        layout.addWidget(self.__metadata_value_lineedit)

        self.setLayout(layout)

    @pyqtSlot()
    def focus(self) -> None:
        self.__metadata_key_combobox.setFocus()

    @pyqtSlot()
    def search(self) -> None:
        key = self.__metadata_key_combobox.currentText().strip()
        value = self.__metadata_value_lineedit.text().strip()
        if len(key) == 0 or len(value) == 0:
            self.reset_requested.emit()
            return

        query = f'@metadata["{key}"] = "{value}"'
        self.search_requested.emit(query)

    def has_search_data(self) -> bool:
        key = self.__metadata_key_combobox.currentText().strip()
        value = self.__metadata_value_lineedit.text().strip()
        return len(key) > 0 and len(value) > 0

    def search_query(self) -> str:
        key = self.__metadata_key_combobox.currentText().strip()
        value = self.__metadata_value_lineedit.text().strip()
        return f'@metadata["{key}"] = "{value}"' if key or value else ""

    @pyqtSlot()
    def update_suggestions(self) -> None:
        self.__metadata_key_combobox.update_values()
        self.__metadata_value_lineedit.update_history()

    @pyqtSlot()
    def clear(self) -> None:
        self.__metadata_key_combobox.setEditText("")
        self.__metadata_value_lineedit.clear()
        self.search_data_changed.emit()

    @pyqtSlot()
    def __on_search_data_changed(self) -> None:
        self.search_data_changed.emit()

    @pyqtSlot()
    def __search_if_ready(self) -> None:
        if self.has_search_data() and self.isEnabled():
            self.search()
