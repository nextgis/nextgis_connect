import os.path
import warnings
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSize, pyqtSignal
from qgis.PyQt.QtWidgets import QWidget

from .ngw_connection_edit_dialog import NgwConnectionEditDialog
from .ngw_connections_manager import NgwConnectionsManager

pluginPath = os.path.dirname(__file__)
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    WIDGET, BASE = uic.loadUiType(
        os.path.join(pluginPath, "ngw_connections_widget_base.ui")
    )


class NgwConnectionsWidget(BASE, WIDGET):
    selected_connection_changed = pyqtSignal(str)
    __connection_id: Optional[str]

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self.setupUi(self)

        warning_icon = QgsApplication.getThemeIcon("mIconWarning.svg")
        size = int(max(24.0, self.connectionComboBox.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.warningLabel.setPixmap(pixmap)
        self.warningLabel.hide()

        self.__connection_id = None

        self.blockSignals(True)
        self.refresh()
        current_index = self.connectionComboBox.currentIndex()
        self.editPushButton.setEnabled(current_index != -1)
        self.removePushButton.setEnabled(current_index != -1)
        self.blockSignals(False)

        self.newPushButton.clicked.connect(self.__new_connection)
        self.editPushButton.clicked.connect(self.__edit_connection)
        self.removePushButton.clicked.connect(self.__remove_connection)
        self.connectionComboBox.currentIndexChanged.connect(
            self.__on_current_index_changed
        )

    def connection_id(self) -> Optional[str]:
        return self.__connection_id

    def connection_name(self) -> str:
        return self.connectionComboBox.currentText()

    def set_connection_id(self, connection_id: Optional[str]) -> None:
        found_index = -1
        for connection_index in range(self.connectionComboBox.count()):
            iterated_connection_id = self.connectionComboBox.itemData(
                connection_index
            )
            if iterated_connection_id == connection_id:
                found_index = connection_index
                break

        self.__connection_id = connection_id if found_index != -1 else None
        self.connectionComboBox.setCurrentIndex(found_index)

        self.__on_current_index_changed(found_index)

    def refresh(self):
        connections_manager = NgwConnectionsManager()

        self.connectionComboBox.blockSignals(True)

        # Clear combobox
        self.connectionComboBox.clear()

        # Fill combobox
        connections = connections_manager.connections
        for connection in connections:
            self.connectionComboBox.addItem(connection.name, connection.id)

        self.connectionComboBox.blockSignals(False)

        # Set current connection if not set
        if self.__connection_id is None:
            current_connection_id = connections_manager.current_connection_id
            if current_connection_id is None and len(connections) > 0:
                self.__connection_id = next(iter(connections)).id
            else:
                self.__connection_id = current_connection_id

        self.set_connection_id(self.__connection_id)

    def __new_connection(self):
        dialog = NgwConnectionEditDialog(self)
        result = dialog.exec()

        if result != NgwConnectionEditDialog.DialogCode.Accepted:
            return

        self.__connection_id = dialog.connection_id()

        self.refresh()

    def __edit_connection(self):
        current_index = self.connectionComboBox.currentIndex()
        connection_id = self.connectionComboBox.itemData(current_index)
        dialog = NgwConnectionEditDialog(self, connection_id)
        dialog.exec()

        # TODO emit if changed

        self.refresh()

    def __remove_connection(self):
        connection_id = self.connectionComboBox.currentData()
        connections_manager = NgwConnectionsManager()
        connections_manager.remove(connection_id)

        self.__connection_id = None

        self.refresh()

    def __on_current_index_changed(self, index: int):
        if index != -1:
            self.__connection_id = self.connectionComboBox.currentData()
            connections_manager = NgwConnectionsManager()
            is_valid = connections_manager.is_valid(self.connection_id())
            self.warningLabel.setVisible(not is_valid)
        else:
            self.__connection_id = None

        self.editPushButton.setEnabled(index != -1)
        self.removePushButton.setEnabled(index != -1)

        self.selected_connection_changed.emit(self.__connection_id)
