from typing import Optional

from qgis.PyQt.QtCore import pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from nextgis_connect.search.metadata_key_combo_box import MetadataKeyComboBox
from nextgis_connect.search.metadata_search_line_edit import (
    MetadataSearchLineEdit,
)


class MetadataSearchWidget(QWidget):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()

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
        lineedit_size_policy = self.__metadata_value_lineedit.sizePolicy()
        lineedit_size_policy.setHorizontalStretch(3)
        self.__metadata_value_lineedit.setSizePolicy(lineedit_size_policy)
        self.__metadata_key_combobox.focus_value.connect(
            lambda: self.__metadata_value_lineedit.setFocus()
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

    @pyqtSlot()
    def update_suggestions(self) -> None:
        self.__metadata_key_combobox.update_values()
        self.__metadata_value_lineedit.update_history()

    @pyqtSlot()
    def clear(self) -> None:
        self.__metadata_key_combobox.setEditText("")
        self.__metadata_value_lineedit.clear()
