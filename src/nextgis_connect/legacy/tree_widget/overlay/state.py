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

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal


class OverlayKind(Enum):
    NONE = auto()
    WELCOME = auto()
    MIGRATION_REQUIRED = auto()
    LOADING = auto()
    AUTH_REQUIRED = auto()
    UNAVAILABLE = auto()
    ERROR = auto()
    SEARCH_CONNECTION = auto()
    SEARCH_EMPTY = auto()


class OverlayAction(Enum):
    NONE = auto()
    CREATE_CONNECTION = auto()
    CREATE_SANDBOX_CONNECTION = auto()
    OPEN_PLUGIN_SETTINGS = auto()
    OPEN_PLUGIN_MANAGER = auto()
    OPEN_NEXTGIS_SETTINGS = auto()
    CONVERT_CONNECTIONS = auto()
    CREATE_WEB_GIS = auto()
    OPEN_NEXTGIS_SITE = auto()
    CONTACT_SUPPORT = auto()
    RUN_DIAGNOSTICS = auto()
    RELOAD_TREE = auto()
    TRY_AGAIN = auto()
    CANCEL = auto()
    SKIP_PLUGIN_UPDATE = auto()
    SWITCH_SEARCH_CONNECTION = auto()
    CREATE_SEARCH_CONNECTION = auto()


@dataclass(frozen=True)
class OverlayButtonState:
    action: OverlayAction = OverlayAction.NONE
    text: str = ""
    tooltip: str = ""
    text_opacity: float = 1.0


@dataclass(frozen=True)
class OverlayState:
    kind: OverlayKind
    title: str = ""
    compact_title: str = ""
    message: str = ""
    details: Optional[str] = None
    primary_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    secondary_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    footer_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    logo_action: OverlayAction = OverlayAction.NONE
    title_icon_name: str = ""
    illustration_name: str = ""
    illustration_size: int = 48
    illustration_themed: bool = True
    draw_background: bool = True
    show_progress: bool = False
    cancel_pending: bool = False


@dataclass(frozen=True)
class OverlayFacts:
    has_connections: bool = False
    has_pending_migration: bool = False
    is_loading: bool = False
    loading_title: str = ""
    loading_compact_title: str = ""
    loading_message: str = ""
    loading_details: Optional[str] = None
    loading_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    loading_draw_background: bool = True
    loading_cancel_pending: bool = False
    is_available: bool = True
    unavailable_title: str = ""
    unavailable_compact_title: str = ""
    unavailable_message: str = ""
    unavailable_details: Optional[str] = None
    unavailable_icon: str = ""
    unavailable_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    has_plugin_update: bool = False
    plugin_update_title: str = ""
    plugin_update_message: str = ""
    plugin_update_details: Optional[str] = None
    plugin_update_icon: str = ""
    plugin_update_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    plugin_update_footer_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    has_auth_error: bool = False
    has_error: bool = False
    error_title: str = ""
    error_message: str = ""
    error_details: Optional[str] = None
    error_icon: str = ""
    error_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    error_secondary_action: OverlayButtonState = field(
        default_factory=OverlayButtonState
    )
    has_search_connection_target: bool = False
    search_connection_url: str = ""
    search_connection_name: str = ""
    search_connection_exists: bool = False
    search_empty: bool = False


class PluginOverlayStateModel(QObject):
    changed = pyqtSignal()

    _facts: OverlayFacts

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._facts = OverlayFacts()

    def snapshot(self) -> OverlayFacts:
        return self._facts

    def update(self, **changes) -> None:
        next_facts = replace(self._facts, **changes)
        if next_facts == self._facts:
            return

        self._facts = next_facts
        self.changed.emit()
