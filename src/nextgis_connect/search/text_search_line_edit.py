from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon, QMovie
from qgis.PyQt.QtWidgets import QAction, QLineEdit, QWidget

from nextgis_connect.search.abstract_search_line_edit import (
    AbstractSearchLineEdit,
)
from nextgis_connect.search.search_settings import SearchSettings
from nextgis_connect.search.text_search_completer_model import (
    TextSearchCompleterModel,
)


class TextSearchLineEdit(AbstractSearchLineEdit):
    __completer_model: TextSearchCompleterModel

    __loading_action: Optional[QAction]
    __loading_icon_movie: QMovie

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(self.tr("Resource name…"))

        # Animation
        self.__loading_action = None
        self.__loading_icon_movie = QMovie(self)
        self.__loading_icon_movie.setFileName(
            ":images/themes/default/mIconLoading.gif"
        )

        # Completer model
        self.__completer_model = TextSearchCompleterModel(connection_id, self)
        self.textEdited.connect(self.__completer_model.set_prefix)
        self.__completer_model.fetching_started.connect(
            self.__show_loading_icon
        )
        self.__completer_model.fetching_finished.connect(
            self.__hide_loading_icon
        )
        self.__completer_model.complete_requested.connect(
            self._completer.complete
        )
        self.search_requested.connect(self.__completer_model.stop_fetching)
        self._completer.setModel(self.__completer_model)

        # Search
        self.search_requested.connect(
            self.update_history,
            Qt.ConnectionType.QueuedConnection,  # type: ignore
        )

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: str) -> None:
        self.__completer_model.set_connection_id(connection_id)

    @pyqtSlot()
    def search(self) -> None:
        if not self.isEnabled():
            return

        search_string = self.text()
        if len(search_string) == 0:
            self.reset_requested.emit()
            return

        search_string = search_string.strip()

        settings = SearchSettings()
        settings.add_text_query_to_history(search_string)

        self.search_requested.emit(search_string)

    @pyqtSlot()
    def update_history(self) -> None:
        self.__completer_model.update_history()

    @pyqtSlot()
    def __show_loading_icon(self) -> None:
        if self.__loading_action is not None:
            return

        self.__loading_action = self.addAction(
            QIcon(self.__loading_icon_movie.currentPixmap()),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.__loading_icon_movie.frameChanged.connect(
            lambda: self.__loading_action.setIcon(
                QIcon(self.__loading_icon_movie.currentPixmap())
            )
        )
        self.__loading_icon_movie.start()

    @pyqtSlot()
    def __hide_loading_icon(self) -> None:
        self.__loading_icon_movie.stop()
        if self.__loading_action is not None:
            self.__loading_action.deleteLater()
            self.__loading_action = None
