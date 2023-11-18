
import warnings
import os.path
from typing import Optional

from qgis.PyQt import uic
from qgis.PyQt.QtCore import pyqtSignal, QSize
from qgis.PyQt.QtWidgets import QWidget

from qgis.core import  QgsApplication

from .ngw_connection_edit_dialog import NgwConnectionEditDialog
from .ngw_connections_manager import NgwConnectionsManager


pluginPath = os.path.dirname(__file__)
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    WIDGET, BASE = uic.loadUiType(
        os.path.join(pluginPath, 'ngw_connections_widget_base.ui'))


class NgwConnectionsWidget(BASE, WIDGET):
    selectedConnectionChanged = pyqtSignal(str)
    __connection_id: Optional[str]

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self.setupUi(self)

        warning_icon = QgsApplication.getThemeIcon("mIconWarning.svg")
        size = int(max(24.0, self.connectionComboBox.minimumSize().height()))
        pixmap = warning_icon.pixmap(warning_icon.actualSize(QSize(size, size)))
        self.warningLabel.setPixmap(pixmap)
        self.warningLabel.hide()

        self.__connection_id = None

        self.blockSignals(True)
        self.refresh()
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

        # TODO fix this workaround
        self.selectedConnectionChanged.emit(self.__connection_id)

    def refresh(self):
        connections_manager = NgwConnectionsManager()

        self.connectionComboBox.blockSignals(True)
        self.connectionComboBox.clear()

        connections = connections_manager.connections()
        for connection in connections:
            self.connectionComboBox.addItem(connection.name, connection.id)

        self.connectionComboBox.blockSignals(False)

        if self.__connection_id is None:
            self.__connection_id = connections_manager.current_connection_id

        has_connections = self.connectionComboBox.count() > 0
        self.editPushButton.setEnabled(has_connections)
        self.removePushButton.setEnabled(has_connections)

        connection_ids = [connection.id for connection in connections]
        if has_connections and self.__connection_id not in connection_ids:
            self.__connection_id = connection_ids[0]

        self.set_connection_id(
            self.__connection_id if has_connections else None
        )

    def __new_connection(self):
        dialog = NgwConnectionEditDialog(self)
        result = dialog.exec_()

        if result != NgwConnectionEditDialog.DialogCode.Accepted:
            return

        self.__connection_id = dialog.connection_id()

        self.refresh()

    def __edit_connection(self):
        current_index = self.connectionComboBox.currentIndex()
        connection_id = self.connectionComboBox.itemData(current_index)
        dialog = NgwConnectionEditDialog(self, connection_id)
        dialog.exec_()

        # TODO emit if changed

        self.refresh()

    def __remove_connection(self):
        connection_id = self.connectionComboBox.currentData()
        connections_manager = NgwConnectionsManager()
        connections_manager.remove(connection_id)

        self.__connection_id = None
        if connection_id == connections_manager.current_connection_id:
            connections_manager.current_connection_id = None

        self.refresh()

    def __on_current_index_changed(self, index: int):
        if index != -1:
            self.__connection_id = self.connectionComboBox.currentData()
            connections_manager = NgwConnectionsManager()
            is_valid = connections_manager.is_valid(self.connection_id())
            self.warningLabel.setVisible(not is_valid)
        else:
            self.__connection_id = None

        self.selectedConnectionChanged.emit(self.__connection_id)
