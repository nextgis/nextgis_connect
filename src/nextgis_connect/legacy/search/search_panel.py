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

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QWidget,
)

from nextgis_connect.legacy.search.metadata_search_widget import (
    MetadataSearchWidget,
)
from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.legacy.search.text_search_line_edit import (
    TextSearchLineEdit,
)
from nextgis_connect.legacy.search.utils import SearchType
from nextgis_connect.platform.logging import logger
from nextgis_connect.ui_kit.icons import qgis_icon


class SearchPanel(QWidget):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QWidget]
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout()
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        self.setLayout(layout)

        # Add search widgets
        self.__stacked_layout = QStackedLayout()
        self.__stacked_layout.addWidget(
            self.__init_text_search_widget(connection_id)
        )
        self.__stacked_layout.addWidget(
            self.__init_metadata_search_widget(connection_id)
        )
        layout.addLayout(self.__stacked_layout)

        # Add search button
        self.__search_button = QToolButton()
        self.__search_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.__search_button.setIcon(qgis_icon("search.svg"))
        search_field_height = self.__text_search_widget.sizeHint().height()
        search_icon_size = QSize(search_field_height, search_field_height)
        self.__search_button.setFixedSize(search_icon_size)
        self.__search_button.setToolTip(self.tr("Run resource search"))
        self.__search_button.clicked.connect(self.__request_search)
        layout.addWidget(self.__search_button)

        # Set size policy
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)

        # Restore last view
        settings = SearchSettings()
        self.set_type(settings.last_used_type)

    @pyqtSlot()
    def focus(self) -> None:
        if self.__search_type == SearchType.ByDisplayName:
            self.__text_search_widget.setFocus()
        elif self.__search_type == SearchType.ByMetadata:
            self.__metadata_search_widget.focus()
        else:
            raise NotImplementedError

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: str) -> None:
        self.__text_search_widget.set_connection_id(connection_id)

    @pyqtSlot()
    def on_settings_changed(self) -> None:
        self.__text_search_widget.update_history()
        self.__metadata_search_widget.update_suggestions()

    @pyqtSlot()
    def clear(self) -> None:
        self.__text_search_widget.clear()
        self.__metadata_search_widget.clear()
        self.reset_requested.emit()

    @pyqtSlot(SearchType)
    def set_type(self, search_type: SearchType) -> None:
        if not self.isVisible() or self.__search_type != search_type:
            self.clear()

        if search_type == SearchType.ByDisplayName:
            self.__stacked_layout.setCurrentIndex(0)
        elif search_type == SearchType.ByMetadata:
            self.__stacked_layout.setCurrentIndex(1)
        else:
            raise NotImplementedError

        self.__search_type = search_type
        settings = SearchSettings()
        settings.last_used_type = search_type

    @pyqtSlot()
    def __request_search(self) -> None:
        if self.__search_type == SearchType.ByDisplayName:
            self.__text_search_widget.search()
        elif self.__search_type == SearchType.ByMetadata:
            self.__metadata_search_widget.search()
        else:
            raise NotImplementedError

    @pyqtSlot(str)
    def __search_by_text(self, search_string: str) -> None:
        if not self.isEnabled():
            return

        if len(search_string) == 0:
            self.__reset()
            return

        logger.debug(f"◴ Search resources: {search_string}")
        self.search_requested.emit(search_string)

    @pyqtSlot()
    def __reset(self) -> None:
        logger.debug("Reset search requested")
        self.reset_requested.emit()

    def __init_text_search_widget(
        self, connection_id: Optional[str]
    ) -> QWidget:
        self.__text_search_widget = TextSearchLineEdit(connection_id)
        self.__text_search_widget.search_requested.connect(
            self.__search_by_text
        )
        self.__text_search_widget.reset_requested.connect(self.__reset)
        return self.__text_search_widget

    def __init_metadata_search_widget(
        self, connection_id: Optional[str]
    ) -> QWidget:
        self.__metadata_search_widget = MetadataSearchWidget()
        self.__metadata_search_widget.search_requested.connect(
            self.__search_by_text
        )
        self.__metadata_search_widget.reset_requested.connect(self.__reset)
        return self.__metadata_search_widget
