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

from qgis.PyQt.QtCore import QStringListModel, Qt, pyqtSlot
from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.legacy.search.abstract_search_line_edit import (
    AbstractSearchLineEdit,
)
from nextgis_connect.legacy.search.search_settings import SearchSettings


class MetadataSearchLineEdit(AbstractSearchLineEdit):
    __completer_model: QStringListModel

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(self.tr("Value…"))

        # Completer model
        self.__completer_model = QStringListModel(self)
        self.update_history()
        self._completer.setModel(self.__completer_model)

        # Search
        self.search_requested.connect(
            self.update_history,
            Qt.ConnectionType.QueuedConnection,  # type: ignore
        )

    @pyqtSlot()
    def search(self) -> None:
        if not self.isEnabled():
            return

        metadata_value = self.text().strip()
        if len(metadata_value) == 0:
            self.reset_requested.emit()
            return

        settings = SearchSettings()
        settings.add_metadata_query_to_history(metadata_value)

        self.search_requested.emit(metadata_value)

    @pyqtSlot()
    def update_history(self) -> None:
        settings = SearchSettings()
        self.__completer_model.setStringList(settings.metadata_queries_history)
