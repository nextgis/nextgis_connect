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

from html import escape
from typing import Optional

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.features.synchronization.infrastructure.storage.cache_maintenance_service import (
    CacheMaintenanceService,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_edit_dialog import (
    NgwConnectionEditDialog,
)
from nextgis_connect.ui_kit.graphics.decorator import (
    NextgisBrandColor,
    NextgisDecorator,
)
from nextgis_connect.ui_kit.icons import qgis_icon


class HighlightablePushButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.__highlighted = False

    def setHighlighted(self, highlighted: bool) -> None:
        if self.__highlighted == highlighted:
            return

        self.__highlighted = highlighted
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

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


class NgwConnectionsWidget(QWidget):
    selected_connection_changed = pyqtSignal(str)
    __connection_id: Optional[str]
    __connections_manager: NgwConnectionsManager

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        connections_manager: Optional[NgwConnectionsManager] = None,
    ) -> None:
        super().__init__(parent)
        self.__setup_ui()
        self.__rebuild_layout()

        warning_icon = qgis_icon("mIconWarning.svg")
        size = int(max(24.0, self.connectionComboBox.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.warningLabel.setPixmap(pixmap)
        self.warningLabel.setFixedWidth(pixmap.width())
        self.warningLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warningLabel.hide()

        self.__connection_id = None
        self.__connections_manager = (
            NgwConnectionsManager()
            if connections_manager is None
            else connections_manager
        )

        self.blockSignals(True)
        self.load_connections()
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

    def load_connections(self) -> None:
        self.__connection_id = self.__connections_manager.current_connection_id
        self.refresh()

    def refresh(self):
        self.connectionComboBox.blockSignals(True)

        # Clear combobox
        self.connectionComboBox.clear()

        # Fill combobox
        connections = self.__connections_manager.connections
        for connection in connections:
            self.connectionComboBox.addItem(connection.name, connection.id)

        self.connectionComboBox.blockSignals(False)

        if self.__find_connection(self.__connection_id) is None:
            self.__connection_id = None

        if self.__connection_id is None:
            current_connection_id = (
                self.__connections_manager.current_connection_id
            )
            current_connection = self.__find_connection(current_connection_id)
            if current_connection is not None:
                self.__connection_id = current_connection.id
            elif len(connections) > 0:
                self.__connection_id = connections[0].id

        self.__update_new_button_highlight()
        self.set_connection_id(self.__connection_id)

    def apply_connections(self) -> None:
        self.__connections_manager.save()
        self.load_connections()

    def __new_connection(self):
        dialog = NgwConnectionEditDialog(
            self,
            connections_manager=self.__connections_manager,
            save_on_accept=False,
        )
        result = dialog.exec()

        if result != NgwConnectionEditDialog.DialogCode.Accepted:
            return

        connection = dialog.connection()
        self.__connections_manager.upsert(connection)
        self.__connection_id = connection.id

        self.refresh()

    def __edit_connection(self):
        current_index = self.connectionComboBox.currentIndex()
        connection_id = self.connectionComboBox.itemData(current_index)
        connection = self.__find_connection(connection_id)
        if connection is None:
            return

        dialog = NgwConnectionEditDialog(
            self,
            connection=connection,
            connections_manager=self.__connections_manager,
            save_on_accept=False,
        )
        result = dialog.exec()
        if result != NgwConnectionEditDialog.DialogCode.Accepted:
            return

        updated_connection = dialog.connection()
        self.__connections_manager.upsert(updated_connection)
        self.__connection_id = updated_connection.id

        self.refresh()

    def __remove_connection(self):
        connection_id = self.connectionComboBox.currentData()
        connection = self.__find_connection(connection_id)
        if connection is None:
            return

        auth_config_ids = (
            self.__connections_manager.auth_config_ids_for_connection(
                connection_id
            )
        )
        cache_service = CacheMaintenanceService()
        project_containers = cache_service.containers_used_by_project(
            connection
        )
        if len(project_containers) > 0:
            self.__show_connection_used_by_project_warning(
                connection,
                project_containers,
            )
            return

        changed_containers = cache_service.containers_with_changes(connection)
        if not self.__confirm_remove_connection(
            connection,
            len(auth_config_ids),
            changed_containers,
        ):
            return

        self.__connections_manager.remove(connection_id)
        if not cache_service.clear_connection_cache(connection):
            QMessageBox.warning(
                self,
                self.tr("Cache was not fully deleted"),
                self.tr(
                    "Some cache files for the connection were not deleted."
                ),
            )

        self.__connection_id = None

        self.refresh()

    def __show_connection_used_by_project_warning(
        self,
        connection: NgwConnection,
        project_containers,
    ) -> None:
        containers_list = self.__project_containers_html(project_containers)
        QMessageBox.warning(
            self,
            self.tr("Connection is used in project"),
            self.tr(
                "It is not possible to delete connection <b>{}</b> while "
                "layers from it are being used in the project."
            ).format(escape(connection.name))
            + "<br><br>"
            + self.tr("Remove these layers from the project first:")
            + containers_list,
        )

    @staticmethod
    def __project_containers_html(project_containers) -> str:
        items = "".join(
            f"<li>{escape(label)}</li>" for _, label in project_containers
        )
        return f"<ul>{items}</ul>"

    def __confirm_remove_connection(
        self,
        connection: NgwConnection,
        auth_config_count: int,
        changed_containers,
    ) -> bool:
        if auth_config_count == 0:
            message = self.tr(
                "Do you want to delete connection <b>{}</b>?"
            ).format(connection.name)
        else:
            message = self.tr(
                "Do you want to delete connection <b>{}</b> and "
                "{} sign-in parameter(s) attached to it?"
            ).format(connection.name, auth_config_count)

        if len(changed_containers) > 0:
            containers_list = "\n".join(
                f"- {label}\n  {path}" for path, label in changed_containers
            )
            message += "\n\n" + self.tr(
                "The connection cache contains layers with unsynchronized "
                "changes. If you continue, you will lose them forever:"
            )
            message += f"\n{containers_list}"

        message_box = QMessageBox(
            QMessageBox.Icon.Warning,
            self.tr("Delete connection?"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            self,
        )
        delete_button = message_box.button(QMessageBox.StandardButton.Yes)
        delete_button.setText(self.tr("Delete"))
        message_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        message_box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return message_box.exec() == QMessageBox.StandardButton.Yes

    def __find_connection(
        self, connection_id: Optional[str]
    ) -> Optional[NgwConnection]:
        if connection_id is None:
            return None

        return self.__connections_manager.connection(connection_id)

    def __is_connection_valid(self, connection_id: Optional[str]) -> bool:
        reason = self.__connections_manager.invalid_reason(connection_id)
        if reason is not None:
            self.warningLabel.setToolTip(reason)
            return False

        self.warningLabel.setToolTip("")
        return True

    def __on_current_index_changed(self, index: int):
        if index != -1:
            self.__connection_id = self.connectionComboBox.currentData()
            self.__connections_manager.current_connection_id = (
                self.__connection_id
            )
            is_valid = self.__is_connection_valid(self.connection_id())
            self.warningLabel.setVisible(not is_valid)
        else:
            self.__connection_id = None
            self.__connections_manager.current_connection_id = None

        self.editPushButton.setEnabled(index != -1)
        self.removePushButton.setEnabled(index != -1)

        self.selected_connection_changed.emit(self.__connection_id)

    def __update_new_button_highlight(self) -> None:
        if self.connectionComboBox.count() != 0:
            self.newPushButton.setHighlighted(False)
            self.newPushButton.setToolTip("")
            return

        self.newPushButton.setHighlighted(True)
        self.newPushButton.setToolTip(self.tr("Create your first connection"))

    def __setup_ui(self) -> None:
        self.connectionComboBox = QComboBox(self)
        self.warningLabel = QLabel(self)
        self.warningLabel.setToolTip(self.tr("Connection is invalid!"))
        self.newPushButton = HighlightablePushButton(self)
        self.newPushButton.setText(self.tr("New"))
        self.editPushButton = QPushButton(self.tr("Edit"), self)
        self.removePushButton = QPushButton(self.tr("Remove"), self)

    def __rebuild_layout(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(9, 9, 9, 9)
        root_layout.setSpacing(6)

        connection_layout = QHBoxLayout()
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.setSpacing(4)
        connection_layout.addWidget(self.connectionComboBox)
        connection_layout.addWidget(self.warningLabel)
        root_layout.addLayout(connection_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)
        for button in (
            self.newPushButton,
            self.editPushButton,
            self.removePushButton,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Fixed,
            )
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        root_layout.addLayout(buttons_layout)
