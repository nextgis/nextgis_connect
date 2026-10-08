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

from typing import TYPE_CHECKING, Optional

from qgis.PyQt import sip
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
from nextgis_connect.legacy.search.resource_type_search_widget import (
    ResourceTypeSearchWidget,
)
from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.legacy.search.text_search_line_edit import (
    TextSearchLineEdit,
)
from nextgis_connect.legacy.search.utils import SearchType
from nextgis_connect.platform.logging import logger
from nextgis_connect.ui_kit.buttons.highlightable import (
    HighlightableToolButton,
)
from nextgis_connect.ui_kit.icons import qgis_icon

if TYPE_CHECKING:
    from nextgis_connect.legacy.tree_widget.model import (
        NGWResourceModelResponse,
    )


class SearchPanel(QWidget):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()
    criteria_pending = pyqtSignal(bool)

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QWidget]
    ) -> None:
        super().__init__(parent)
        self.__applied_query = ""
        self.__search_generation = 0

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
        self.__stacked_layout.addWidget(
            self.__init_resource_type_search_widget(connection_id)
        )
        layout.addLayout(self.__stacked_layout)

        # Add search button
        self.__search_button = HighlightableToolButton(self)
        self.__search_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.__search_button.setIcon(qgis_icon("search.svg"))
        search_field_height = self.__text_search_widget.sizeHint().height()
        search_icon_size = QSize(search_field_height, search_field_height)
        self.__search_button.setFixedSize(search_icon_size)
        self.__search_button.setToolTip(self.tr("Run resource search"))
        self.__search_button.clicked.connect(self.__request_search)
        self.__text_search_widget.textChanged.connect(
            self.__update_search_button
        )
        self.__metadata_search_widget.search_data_changed.connect(
            self.__update_search_button
        )
        self.__resource_type_search_widget.search_data_changed.connect(
            self.__update_search_button
        )
        layout.addWidget(self.__search_button)

        # Set size policy
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)

        # Restore last view
        self.__search_type = SearchType.ByDisplayName
        settings = SearchSettings()
        self.set_type(settings.last_used_type)

    @pyqtSlot()
    def focus(self) -> None:
        if self.__search_type == SearchType.ByDisplayName:
            self.__text_search_widget.setFocus()
        elif self.__search_type == SearchType.ByMetadata:
            self.__metadata_search_widget.focus()
        elif self.__search_type == SearchType.ByResourceType:
            self.__resource_type_search_widget.setFocus()
        else:
            raise NotImplementedError

    def set_help_host(self, host: QWidget) -> None:
        self.__text_search_widget.set_help_host(host)

    def set_search_mode_button(self, button: QToolButton) -> None:
        self.__text_search_widget.set_search_mode_button(button)

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: str) -> None:
        self.mark_search_reset()
        self.__text_search_widget.set_connection_id(connection_id)
        self.__resource_type_search_widget.set_connection_id(connection_id)
        if self.__search_type == SearchType.ByResourceType:
            self.__resource_type_search_widget.load_resource_types()

    @pyqtSlot()
    def on_settings_changed(self) -> None:
        self.__text_search_widget.update_history()
        self.__metadata_search_widget.update_suggestions()

    @pyqtSlot()
    def clear(self) -> None:
        self.__text_search_widget.clear()
        self.__metadata_search_widget.clear()
        self.__resource_type_search_widget.clear()
        self.reset_requested.emit()
        self.__update_search_button()

    @pyqtSlot(SearchType)
    def set_type(self, search_type: SearchType) -> None:
        if not self.isVisible() or self.__search_type != search_type:
            self.clear()

        if search_type == SearchType.ByDisplayName:
            self.__stacked_layout.setCurrentIndex(0)
        elif search_type == SearchType.ByMetadata:
            self.__stacked_layout.setCurrentIndex(1)
        elif search_type == SearchType.ByResourceType:
            self.__stacked_layout.setCurrentIndex(2)
            self.__resource_type_search_widget.load_resource_types()
        else:
            raise NotImplementedError

        self.__search_type = search_type
        self.__update_search_button()
        settings = SearchSettings()
        settings.last_used_type = search_type

    @pyqtSlot()
    def __request_search(self) -> None:
        if self.__search_type == SearchType.ByDisplayName:
            self.__text_search_widget.search()
        elif self.__search_type == SearchType.ByMetadata:
            self.__metadata_search_widget.search()
        elif self.__search_type == SearchType.ByResourceType:
            self.__resource_type_search_widget.search()
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

    def current_query(self) -> str:
        return self.__current_query()

    def track_search(
        self, response: "NGWResourceModelResponse", query: str
    ) -> None:
        self.__search_generation += 1
        generation = self.__search_generation

        def completed() -> None:
            if sip.isdeleted(self):
                return
            if generation == self.__search_generation:
                self.mark_search_applied(query)

        def finished() -> None:
            response.search_completed.disconnect(completed)
            response.finished.disconnect(finished)

        response.search_completed.connect(completed)
        response.finished.connect(finished)

    def mark_search_applied(self, query: Optional[str] = None) -> None:
        self.__applied_query = (
            self.__current_query() if query is None else query
        )
        self.__update_search_button()

    def mark_search_reset(self) -> None:
        self.__search_generation += 1
        self.__applied_query = ""
        self.__update_search_button()

    def __current_query(self) -> str:
        if self.__search_type == SearchType.ByDisplayName:
            return self.__text_search_widget.text().strip()
        if self.__search_type == SearchType.ByMetadata:
            return self.__metadata_search_widget.search_query()
        return self.__resource_type_search_widget.search_query()

    @pyqtSlot()
    def __update_search_button(self) -> None:
        if self.__search_type == SearchType.ByDisplayName:
            has_search_data = len(self.__text_search_widget.text().strip()) > 0
        elif self.__search_type == SearchType.ByMetadata:
            has_search_data = self.__metadata_search_widget.has_search_data()
        elif self.__search_type == SearchType.ByResourceType:
            has_search_data = (
                self.__resource_type_search_widget.has_search_data()
            )
        else:
            raise NotImplementedError

        help_visible = self.__text_search_widget.is_help_visible
        self.__search_button.setEnabled(has_search_data and not help_visible)
        pending = (
            bool(self.__applied_query)
            and self.__current_query() != self.__applied_query
        )
        self.__search_button.setHighlighted(
            has_search_data
            and not help_visible
            and (pending or not self.__applied_query)
        )
        self.criteria_pending.emit(pending)

    def __init_text_search_widget(
        self, connection_id: Optional[str]
    ) -> QWidget:
        self.__text_search_widget = TextSearchLineEdit(connection_id, self)
        self.__text_search_widget.search_requested.connect(
            self.__search_by_text
        )
        self.__text_search_widget.reset_requested.connect(self.__reset)
        self.__text_search_widget.help_visibility_changed.connect(
            self.__update_search_button
        )
        return self.__text_search_widget

    def __init_metadata_search_widget(
        self, connection_id: Optional[str]
    ) -> QWidget:
        self.__metadata_search_widget = MetadataSearchWidget(self)
        self.__metadata_search_widget.search_requested.connect(
            self.__search_by_text
        )
        self.__metadata_search_widget.reset_requested.connect(self.__reset)
        return self.__metadata_search_widget

    def __init_resource_type_search_widget(
        self, connection_id: Optional[str]
    ) -> QWidget:
        self.__resource_type_search_widget = ResourceTypeSearchWidget(
            connection_id,
            self,
        )
        self.__resource_type_search_widget.search_requested.connect(
            self.__search_by_text
        )
        self.__resource_type_search_widget.reset_requested.connect(
            self.__reset_resource_types
        )
        return self.__resource_type_search_widget

    def __reset_resource_types(self) -> None:
        if self.__search_type == SearchType.ByResourceType:
            self.__reset()
