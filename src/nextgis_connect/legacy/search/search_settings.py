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

from typing import List, Optional

from qgis.core import QgsSettings

from nextgis_connect.legacy.search.utils import SearchType


class SearchSettings:
    __settings: QgsSettings

    def __init__(self, settings: Optional[QgsSettings] = None) -> None:
        self.__settings = QgsSettings() if settings is None else settings

    @property
    def help_viewed(self) -> bool:
        return self.__settings.value(
            self.__group + "/helpViewed", False, type=bool
        )

    @help_viewed.setter
    def help_viewed(self, value: bool) -> None:
        self.__settings.setValue(self.__group + "/helpViewed", value)

    @property
    def history_size(self) -> int:
        return self.__settings.value(self.__group + "/historySize", 5)

    @history_size.setter
    def history_size(self, value: int) -> None:
        self.__settings.setValue(self.__group + "/historySize", value)

    @property
    def last_used_type(self) -> SearchType:
        return SearchType(
            self.__settings.value(
                self.__group + "/lastUsedType", str(SearchType.ByDisplayName)
            )
        )

    @last_used_type.setter
    def last_used_type(self, value: SearchType) -> None:
        self.__settings.setValue(self.__group + "/lastUsedType", str(value))

    @property
    def text_queries_history(self) -> List[str]:
        return self.__settings.value(self.__group + "/queries/text", [])

    def add_text_query_to_history(self, item: str) -> None:
        if len(item) == 0:
            return

        items = self.text_queries_history
        if item in items:
            index = items.index(item)
            items.pop(index)

        items.insert(0, item)

        self.__settings.setValue(
            self.__group + "/queries/text", items[: self.history_size]
        )

    @property
    def metadata_keys(self) -> List[str]:
        return self.__settings.value(self.__group + "/metadataKeys", [])

    @metadata_keys.setter
    def metadata_keys(self, keys: List[str]) -> None:
        self.__settings.setValue(self.__group + "/metadataKeys", keys)

    @property
    def metadata_queries_history(self) -> List[str]:
        return self.__settings.value(
            self.__group + "/queries/metadata/all", []
        )

    def add_metadata_query_to_history(self, item: str) -> None:
        if len(item) == 0:
            return

        items = self.metadata_queries_history
        if item in items:
            index = items.index(item)
            items.pop(index)

        items.insert(0, item)

        self.__settings.setValue(
            self.__group + "/queries/metadata/all", items[: self.history_size]
        )

    def clear_history(self) -> None:
        self.__settings.setValue(self.__group + "/queries/text", [])

    @property
    def __group(self) -> str:
        return "NextGIS/Connect/search"
