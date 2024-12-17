from typing import Optional

from qgis.PyQt.QtCore import QStringListModel, Qt, pyqtSlot
from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.search.abstract_search_line_edit import (
    AbstractSearchLineEdit,
)
from nextgis_connect.search.search_settings import SearchSettings


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

        metadata_value = self.text()
        if len(metadata_value) == 0:
            self.reset_requested.emit()
            return

        metadata_value = metadata_value.strip()

        settings = SearchSettings()
        settings.add_metadata_query_to_history(metadata_value)

        self.search_requested.emit(metadata_value)

    @pyqtSlot()
    def update_history(self) -> None:
        settings = SearchSettings()
        self.__completer_model.setStringList(settings.metadata_queries_history)
