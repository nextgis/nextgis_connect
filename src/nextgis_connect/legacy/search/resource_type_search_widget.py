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

import json
from typing import Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import (
    QSignalBlocker,
    QSize,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from nextgis_connect.features.search.domain.resource_type_catalog import (
    ResourceTypeCatalogParser,
    ResourceTypeGroup,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.ui_kit.icons import (
    ngw_resource_type_icon,
)
from nextgis_connect.ui_kit.widgets.multi_select_combo_box import (
    MultiSelectComboBox,
)


class ResourceTypeSearchWidget(QWidget):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()
    search_data_changed = pyqtSignal()

    __connection_id: Optional[str]
    __network_manager: Optional[QgsNetworkAccessManager]
    __resource_types_network_reply: Optional[QNetworkReply]

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.__connection_id = connection_id
        self.__network_manager = None
        self.__resource_types_network_reply = None
        self.__catalog_parser = ResourceTypeCatalogParser()
        self.__resource_types_loaded = False

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.__resource_type_combobox = MultiSelectComboBox(self)
        self.setFocusProxy(self.__resource_type_combobox)
        self.__resource_type_combobox.setDefaultText("")
        self.__resource_type_combobox.setProperty(
            "selectedToolTip", self.tr("Selected resource types")
        )
        self.__resource_type_combobox.setToolTip(
            self.tr("Select one or more resource types")
        )
        self.__resource_type_combobox.setEnabled(False)
        self.__resource_type_combobox.setIconSize(QSize(16, 16))
        line_edit = self.__resource_type_combobox.lineEdit()
        assert line_edit is not None
        line_edit.setPlaceholderText(self.tr("Resource type…"))
        size_policy = self.__resource_type_combobox.sizePolicy()
        size_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        self.__resource_type_combobox.setSizePolicy(size_policy)
        layout.addWidget(self.__resource_type_combobox)

        self.__resource_type_combobox.clear_action.setText(
            self.tr("Clear selected resource types")
        )
        self.__resource_type_combobox.checkedItemsChanged.connect(
            self.__on_checked_items_changed
        )
        self.__resource_type_combobox.returnPressed.connect(self.search)

        self.setLayout(layout)
        self.__show_no_connection_state()

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: str) -> None:
        normalized_connection_id = (
            connection_id if connection_id != "" else None
        )
        if self.__connection_id == normalized_connection_id:
            return

        self.__connection_id = normalized_connection_id
        self.__resource_types_loaded = False
        self.__abort_resource_type_fetching()
        self.clear()
        self.__show_no_connection_state()

    @pyqtSlot()
    def load_resource_types(self) -> None:
        if self.__resource_types_loaded:
            return

        if self.__resource_types_network_reply is not None:
            return

        connection_id = self.__connection_id
        if connection_id is None:
            self.__show_no_connection_state()
            return

        connection = NgwConnectionsManager().connection(connection_id)
        if connection is None:
            self.__show_no_connection_state()
            return

        self.__resource_type_combobox.clear()
        self.__resource_type_combobox.setDefaultText(
            self.tr("Loading resource types…")
        )
        self.__resource_type_combobox.setEnabled(False)

        request = QNetworkRequest(
            QUrl(connection.url + "/api/component/resource/blueprint")
        )
        connection.update_network_request(request)

        if self.__network_manager is None:
            self.__network_manager = QgsNetworkAccessManager(self)
        self.__resource_types_network_reply = self.__network_manager.get(
            request
        )
        self.__resource_types_network_reply.finished.connect(
            self.__update_resource_types
        )
        logger.debug("↓ Fetching resource types for resource type filter")

    @pyqtSlot()
    def search(self) -> None:
        query = self.search_query()
        if not query:
            self.reset_requested.emit()
            return

        self.search_requested.emit(query)

    def has_search_data(self) -> bool:
        return len(self.__resource_type_combobox.checkedItemsData()) > 0

    def search_query(self) -> str:
        return " OR ".join(
            f"@type = {resource_type}"
            for resource_type in self.__resource_type_combobox.checkedItemsData()
        )

    @pyqtSlot()
    def clear(self) -> None:
        self.__resource_type_combobox.clear_selection()
        self.search_data_changed.emit()

    @pyqtSlot()
    def __update_resource_types(self) -> None:
        reply = self.sender()
        if not isinstance(reply, QNetworkReply):
            return

        if reply is not self.__resource_types_network_reply:
            reply.deleteLater()
            return

        self.__resource_types_network_reply = None
        if reply.error() != QNetworkReply.NetworkError.NoError:  # type: ignore
            logger.warning("Can't fetch resource types for resource filter")
            self.__show_loading_error_state()
            reply.deleteLater()
            return

        try:
            blueprint = json.loads(reply.readAll().data().decode())
            self.__set_resource_types(blueprint)
        except (TypeError, UnicodeDecodeError, ValueError):
            logger.exception("Can't parse resource types for resource filter")
            self.__show_loading_error_state()
        finally:
            reply.close()
            reply.deleteLater()

    def __set_resource_types(self, blueprint: object) -> None:
        groups = self.__catalog_parser.parse(blueprint)
        with QSignalBlocker(self.__resource_type_combobox):
            self.__resource_type_combobox.clear()
            for group in groups:
                self.__add_resource_group(group)
            self.__resource_type_combobox.setCurrentIndex(-1)
        self.__resource_types_loaded = True
        self.__resource_type_combobox.setEnabled(True)
        self.__resource_type_combobox.setDefaultText(
            "" if groups else self.tr("No resource types available")
        )
        self.search_data_changed.emit()

    def __add_resource_group(self, group: ResourceTypeGroup) -> None:
        label = (
            self.tr("Other resources") if group.label is None else group.label
        )
        if label:
            self.__resource_type_combobox.add_group_header(label)
        for resource in group.resources:
            self.__resource_type_combobox.addItemWithCheckState(
                resource.label, Qt.CheckState.Unchecked, resource.identity
            )
            self.__resource_type_combobox.setItemIcon(
                self.__resource_type_combobox.count() - 1,
                ngw_resource_type_icon(
                    resource_class=resource.identity, size=16
                ),
            )

    def __abort_resource_type_fetching(self) -> None:
        reply = self.__resource_types_network_reply
        self.__resource_types_network_reply = None
        if reply is not None:
            reply.abort()

    def __show_no_connection_state(self) -> None:
        self.__resource_type_combobox.clear()
        self.__resource_type_combobox.setDefaultText(
            self.tr("No active connection")
        )
        self.__resource_type_combobox.setEnabled(False)

    def __show_loading_error_state(self) -> None:
        self.__resource_type_combobox.clear()
        self.__resource_type_combobox.setDefaultText(
            self.tr("Unable to load resource types")
        )
        self.__resource_type_combobox.setEnabled(False)

    @pyqtSlot()
    def __on_checked_items_changed(self) -> None:
        self.search_data_changed.emit()
        if not self.has_search_data():
            self.reset_requested.emit()
