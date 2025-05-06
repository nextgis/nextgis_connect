import json
from typing import List, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import (
    QObject,
    QStringListModel,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from nextgis_connect.logging import logger
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.search.search_settings import SearchSettings


class TextSearchCompleterModel(QStringListModel):
    fetching_started = pyqtSignal()
    fetching_finished = pyqtSignal()
    complete_requested = pyqtSignal()

    __connection_id: Optional[str]
    __bouncing_timer: QTimer
    __network_manager: Optional[QgsNetworkAccessManager]
    __suggestions_network_reply: Optional[QNetworkReply]

    __prefix: str
    __history_suggestions: List[str]
    __search_suggestions: List[str]

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.__connection_id = connection_id

        # Setup a timer to debounce suggestion fetching
        self.__bouncing_timer = QTimer(self)
        self.__bouncing_timer.setInterval(500)
        self.__bouncing_timer.timeout.connect(self.__fetch_suggestions)

        # Network manager and reply for handling network requests
        self.__network_manager = None
        self.__suggestions_network_reply = None

        # Prefix string for the search
        self.__prefix = ""

        # Fetch history suggestions from settings
        self.__update_history_suggestions()
        self.__search_suggestions = []
        self.__combine()

    @pyqtSlot(str)
    def set_prefix(self, prefix: str) -> None:
        """Set the prefix for search and reset suggestions"""

        self.__prefix = prefix
        self.__search_suggestions = []
        self.__combine()

        # Stop fetching if the prefix is too short
        if len(self.__prefix) < 3:
            self.__stop_fetching()
            return

        # Cancel any ongoing fetching before starting a new one
        self.__discard_previous_fetching()

        # Start the timer to debounce the fetch requests
        self.__bouncing_timer.start()

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: Optional[str]) -> None:
        """Update connection ID and reset suggestions"""
        connection_id = connection_id if connection_id != "" else None
        self.__connection_id = connection_id
        self.__search_suggestions = []
        self.__combine()

    @pyqtSlot()
    def stop_fetching(self) -> None:
        """Stop any ongoing fetching operations"""
        self.__stop_fetching()

    @pyqtSlot()
    def update_history(self) -> None:
        """Update history suggestions"""
        self.__update_history_suggestions()
        self.__combine()

    def __update_history_suggestions(self) -> None:
        """Fetch text queries history from settings"""
        settings = SearchSettings()
        self.__history_suggestions = settings.text_queries_history

    def __combine(self) -> None:
        """Combine current search suggestions with history"""
        found_suggestions = [
            suggestion
            for suggestion in self.__search_suggestions
            if suggestion not in self.__history_suggestions
        ]
        self.setStringList(self.__history_suggestions + found_suggestions)

    def __discard_previous_fetching(self) -> None:
        """Abort any ongoing network request for suggestions"""
        if self.__suggestions_network_reply is None:
            return

        self.__suggestions_network_reply.abort()
        logger.debug("Previous suggestions fetching has been cancelled")

    def __stop_fetching(self) -> None:
        """Stop the bouncing timer and abort previous fetching"""
        self.__bouncing_timer.stop()
        self.__discard_previous_fetching()

    @pyqtSlot()
    def __fetch_suggestions(self) -> None:
        """Fetch suggestions based on the current prefix"""
        self.__bouncing_timer.stop()

        search_string = self.__prefix
        if (
            search_string.strip().startswith("@")
            or self.__connection_id is None
        ):
            return

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None

        query = f"display_name__ilike={search_string}%&serialization=resource"
        search_url = f"/api/resource/search/?{query}&serialization=resource"

        # Setup network request to fetch suggestions
        request = QNetworkRequest(QUrl(connection.url + search_url))
        connection.update_network_request(request)

        self.__network_manager = QgsNetworkAccessManager()
        self.__suggestions_network_reply = self.__network_manager.get(request)
        self.__suggestions_network_reply.finished.connect(
            self.__update_suggestions
        )

        self.fetching_started.emit()
        logger.debug(f"⬇️ Fetching suggestions for: {search_string}")

    @pyqtSlot()
    def __update_suggestions(self) -> None:
        """Update suggestions once fetching is complete"""
        self.fetching_finished.emit()

        if self.__suggestions_network_reply is None:
            return

        if (
            self.__suggestions_network_reply.error()  # type: ignore
            != QNetworkReply.NetworkError.NoError
        ):
            self.__suggestions_network_reply.deleteLater()
            self.__suggestions_network_reply = None
            return

        results = json.loads(
            self.__suggestions_network_reply.readAll().data().decode()
        )
        display_names = list(
            set(resource["resource"]["display_name"] for resource in results)
        )

        self.__suggestions_network_reply.close()
        self.__suggestions_network_reply.deleteLater()
        self.__suggestions_network_reply = None

        logger.debug(f"Fetched suggestions: {display_names}")

        # Update the search suggestions and combine them with history
        self.__search_suggestions = display_names
        self.__combine()

        if len(self.__search_suggestions) > 0:
            self.complete_requested.emit()
