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
from typing import List, Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import (
    QModelIndex,
    QObject,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from nextgis_connect.features.search.domain.query_suggestions import (
    TextSearchSuggestionBuilder,
)
from nextgis_connect.features.search.domain.resource_blueprint import (
    ResourceBlueprintTypeParser,
)
from nextgis_connect.features.search.domain.resource_owners import (
    ResourceOwnerSuggestionParser,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.platform.logging import logger


class TextSearchCompleterModel(QStringListModel):
    TAG_DESCRIPTION_ROLE = Qt.ItemDataRole.UserRole + 1
    fetching_started = pyqtSignal()
    fetching_finished = pyqtSignal()
    complete_requested = pyqtSignal()

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role == self.TAG_DESCRIPTION_ROLE:
            return self._syntax_suggestions
        value = super().data(index, role)
        if (
            role == Qt.ItemDataRole.DisplayRole
            and self._syntax_suggestions
            and isinstance(value, str)
            and value.endswith("@metadata[")
        ):
            return value[:-1]
        return value

    __connection_id: Optional[str]
    __bouncing_timer: QTimer
    __network_manager: Optional[QgsNetworkAccessManager]
    __suggestions_network_reply: Optional[QNetworkReply]
    __resource_types_network_reply: Optional[QNetworkReply]
    __owners_network_reply: Optional[QNetworkReply]

    __prefix: str
    __history_suggestions: List[str]
    __search_suggestions: List[str]
    __resource_type_suggestions_cache: Optional[List[str]]
    __owner_suggestions_cache: Optional[List[str]]
    __suggestion_builder: TextSearchSuggestionBuilder
    __blueprint_type_parser: ResourceBlueprintTypeParser
    __owner_parser: ResourceOwnerSuggestionParser

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self._syntax_suggestions = False
        self.__connection_id = connection_id

        # Setup a timer to debounce suggestion fetching
        self.__bouncing_timer = QTimer(self)
        self.__bouncing_timer.setInterval(500)
        self.__bouncing_timer.timeout.connect(self.__fetch_suggestions)

        # Network manager and reply for handling network requests
        self.__network_manager = None
        self.__suggestions_network_reply = None
        self.__resource_types_network_reply = None
        self.__owners_network_reply = None

        # Prefix string for the search
        self.__prefix = ""
        self.__resource_type_suggestions_cache = None
        self.__owner_suggestions_cache = None
        self.__suggestion_builder = TextSearchSuggestionBuilder()
        self.__blueprint_type_parser = ResourceBlueprintTypeParser()
        self.__owner_parser = ResourceOwnerSuggestionParser()

        # Fetch history suggestions from settings
        self.__update_history_suggestions()
        self.__search_suggestions = []
        self.__combine()

    @pyqtSlot(str)
    def set_prefix(self, prefix: str) -> None:
        """Set the prefix for search and reset suggestions"""

        self.__prefix = prefix

        if self.__update_operation_suggestions():
            self.__stop_name_suggestion_fetching()
            self.__discard_resource_type_fetching()
            self.__discard_owner_fetching()
            return

        if self.__update_keyword_suggestions():
            self.__stop_name_suggestion_fetching()
            self.__discard_resource_type_fetching()
            self.__discard_owner_fetching()
            return

        if self.__update_logical_operation_suggestions():
            self.__stop_name_suggestion_fetching()
            self.__discard_resource_type_fetching()
            self.__discard_owner_fetching()
            return

        if self.__update_resource_type_suggestions():
            self.__stop_name_suggestion_fetching()
            self.__discard_owner_fetching()
            return

        if self.__update_owner_suggestions():
            self.__stop_name_suggestion_fetching()
            self.__discard_resource_type_fetching()
            return

        if self.__prefix.strip().startswith("@"):
            self.__search_suggestions = []
            self.setStringList([])
            self.__stop_fetching()
            return

        self.__discard_resource_type_fetching()
        self.__discard_owner_fetching()
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
        self.__resource_type_suggestions_cache = None
        self.__owner_suggestions_cache = None
        self.__discard_resource_type_fetching()
        self.__discard_owner_fetching()
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
        self._syntax_suggestions = False
        history_suggestions = self.__history_suggestions_for_prefix()
        found_suggestions = [
            suggestion
            for suggestion in self.__search_suggestions
            if suggestion not in history_suggestions
        ]
        self.setStringList(history_suggestions + found_suggestions)

    def __history_suggestions_for_prefix(self) -> List[str]:
        history_prefix = self.__prefix.strip().lower()
        if len(history_prefix) == 0:
            return self.__history_suggestions

        return [
            suggestion
            for suggestion in self.__history_suggestions
            if suggestion.lower().startswith(history_prefix)
        ]

    def __set_syntax_suggestions(self, suggestions: List[str]) -> None:
        self._syntax_suggestions = True
        self.__search_suggestions = suggestions
        self.setStringList(suggestions)

        if len(suggestions) > 0:
            self.complete_requested.emit()

    def __update_keyword_suggestions(self) -> bool:
        suggestions = self.__suggestion_builder.keyword_suggestions(
            self.__prefix
        )
        if suggestions is None:
            return False

        self.__set_syntax_suggestions(suggestions)
        return True

    def __update_operation_suggestions(self) -> bool:
        suggestions = self.__suggestion_builder.operation_suggestions(
            self.__prefix
        )
        if suggestions is None:
            return False

        self.__set_syntax_suggestions(suggestions)
        return True

    def __update_logical_operation_suggestions(self) -> bool:
        suggestions = self.__suggestion_builder.logical_operation_suggestions(
            self.__prefix
        )
        if suggestions is None:
            return False

        self.__set_syntax_suggestions(suggestions)
        return True

    def __update_resource_type_suggestions(self) -> bool:
        context = self.__suggestion_builder.resource_type_context(
            self.__prefix
        )
        if context is None:
            return False

        if self.__resource_type_suggestions_cache is not None:
            suggestions = (
                self.__suggestion_builder.resource_type_suggestions(
                    self.__prefix,
                    self.__resource_type_suggestions_cache,
                )
                or []
            )
            self.__set_syntax_suggestions(suggestions)
            return True

        self.__set_syntax_suggestions([])
        self.__fetch_resource_types()
        return True

    def __update_owner_suggestions(self) -> bool:
        context = self.__suggestion_builder.owner_context(self.__prefix)
        if context is None:
            return False

        if self.__owner_suggestions_cache is not None:
            suggestions = (
                self.__suggestion_builder.owner_suggestions(
                    self.__prefix,
                    self.__owner_suggestions_cache,
                )
                or []
            )
            self.__set_syntax_suggestions(suggestions)
            return True

        self.__set_syntax_suggestions([])
        self.__fetch_owners()
        return True

    def __discard_previous_fetching(self) -> None:
        """Abort any ongoing network request for suggestions"""
        if self.__suggestions_network_reply is None:
            return

        self.__suggestions_network_reply.abort()
        logger.debug("Previous suggestions fetching has been cancelled")

    def __discard_resource_type_fetching(self) -> None:
        if self.__resource_types_network_reply is None:
            return

        self.__resource_types_network_reply.abort()
        logger.debug("Resource type suggestions fetching has been cancelled")

    def __discard_owner_fetching(self) -> None:
        if self.__owners_network_reply is None:
            return

        self.__owners_network_reply.abort()
        logger.debug("Owner suggestions fetching has been cancelled")

    def __stop_name_suggestion_fetching(self) -> None:
        self.__bouncing_timer.stop()
        self.__discard_previous_fetching()

    def __stop_fetching(self) -> None:
        """Stop the bouncing timer and abort previous fetching"""
        self.__stop_name_suggestion_fetching()
        self.__discard_resource_type_fetching()
        self.__discard_owner_fetching()

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
        logger.debug(f"↓ Fetching suggestions for: {search_string}")

    def __fetch_resource_types(self) -> None:
        if (
            self.__connection_id is None
            or self.__resource_types_network_reply is not None
        ):
            return

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None

        request = QNetworkRequest(
            QUrl(connection.url + "/api/component/resource/blueprint")
        )
        connection.update_network_request(request)

        self.__network_manager = QgsNetworkAccessManager()
        self.__resource_types_network_reply = self.__network_manager.get(
            request
        )
        self.__resource_types_network_reply.finished.connect(
            self.__update_resource_types
        )

        self.fetching_started.emit()
        logger.debug("↓ Fetching resource type suggestions")

    def __fetch_owners(self) -> None:
        if (
            self.__connection_id is None
            or self.__owners_network_reply is not None
        ):
            return

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None

        request = QNetworkRequest(
            QUrl(connection.url + "/api/component/auth/user/?brief=true")
        )
        connection.update_network_request(request)

        self.__network_manager = QgsNetworkAccessManager()
        self.__owners_network_reply = self.__network_manager.get(request)
        self.__owners_network_reply.finished.connect(self.__update_owners)

        self.fetching_started.emit()
        logger.debug("↓ Fetching owner suggestions")

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

    @pyqtSlot()
    def __update_resource_types(self) -> None:
        self.fetching_finished.emit()

        if self.__resource_types_network_reply is None:
            return

        if (
            self.__resource_types_network_reply.error()  # type: ignore
            != QNetworkReply.NetworkError.NoError
        ):
            self.__resource_types_network_reply.deleteLater()
            self.__resource_types_network_reply = None
            return

        try:
            blueprint = json.loads(
                self.__resource_types_network_reply.readAll().data().decode()
            )
            self.__resource_type_suggestions_cache = (
                self.__blueprint_type_parser.parse(blueprint)
            )
        except Exception:
            logger.exception("Can't fetch resource type suggestions")
            self.__resource_type_suggestions_cache = []

        self.__resource_types_network_reply.close()
        self.__resource_types_network_reply.deleteLater()
        self.__resource_types_network_reply = None

        self.__update_resource_type_suggestions()

    @pyqtSlot()
    def __update_owners(self) -> None:
        self.fetching_finished.emit()

        if self.__owners_network_reply is None:
            return

        if (
            self.__owners_network_reply.error()  # type: ignore
            != QNetworkReply.NetworkError.NoError
        ):
            self.__owners_network_reply.deleteLater()
            self.__owners_network_reply = None
            return

        try:
            users = json.loads(
                self.__owners_network_reply.readAll().data().decode()
            )
            self.__owner_suggestions_cache = self.__owner_parser.parse(users)
        except Exception:
            logger.exception("Can't fetch owner suggestions")
            self.__owner_suggestions_cache = []

        self.__owners_network_reply.close()
        self.__owners_network_reply.deleteLater()
        self.__owners_network_reply = None

        self.__update_owner_suggestions()
