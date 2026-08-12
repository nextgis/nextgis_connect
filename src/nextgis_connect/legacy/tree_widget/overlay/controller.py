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

from qgis.PyQt.QtCore import QCoreApplication, QObject, pyqtSignal

from nextgis_connect.platform.qgis.utils import utm_tags

from .state import (
    OverlayAction,
    OverlayButtonState,
    OverlayFacts,
    OverlayKind,
    OverlayState,
    PluginOverlayStateModel,
)


class PluginOverlayResolver:
    def resolve(self, facts: OverlayFacts) -> OverlayState:
        if facts.is_loading:
            return OverlayState(
                kind=OverlayKind.LOADING,
                title=facts.loading_title or self.tr("Please wait"),
                message=facts.loading_message
                or self.tr("The resource tree is being updated."),
                details=facts.loading_details,
                secondary_action=facts.loading_action,
                logo_action=(
                    OverlayAction.OPEN_NEXTGIS_SITE
                    if facts.loading_draw_background
                    else OverlayAction.NONE
                ),
                draw_background=facts.loading_draw_background,
                show_progress=True,
                cancel_pending=facts.loading_cancel_pending,
            )

        if facts.has_auth_error:
            return OverlayState(
                kind=OverlayKind.AUTH_REQUIRED,
                title=self.tr("Sign in to continue"),
                message=self.tr(
                    "The selected connection uses a NextGIS account."
                ),
                details=self.tr(
                    "Open NextGIS settings in QGIS and sign in, then reload the resource tree."
                ),
                primary_action=OverlayButtonState(
                    action=OverlayAction.OPEN_NEXTGIS_SETTINGS,
                    text=self.tr("Open NextGIS settings"),
                ),
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if not facts.is_available:
            is_update_state = facts.unavailable_icon == "update"
            return OverlayState(
                kind=OverlayKind.UNAVAILABLE,
                title=facts.unavailable_title
                or self.tr("Web GIS is unavailable"),
                message=facts.unavailable_message,
                details=facts.unavailable_details,
                title_icon_name=(
                    facts.unavailable_icon if is_update_state else ""
                ),
                illustration_name=(
                    "" if is_update_state else facts.unavailable_icon
                ),
                primary_action=facts.unavailable_action,
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if facts.has_error:
            return OverlayState(
                kind=OverlayKind.ERROR,
                title=facts.error_title or self.tr("Request failed"),
                message=facts.error_message,
                details=facts.error_details,
                illustration_name=facts.error_icon,
                primary_action=facts.error_action,
                secondary_action=facts.error_secondary_action,
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if facts.has_pending_migration:
            return OverlayState(
                kind=OverlayKind.MIGRATION_REQUIRED,
                title=self.tr("Update saved connections"),
                message=self.tr(
                    "Saved connections need to be converted to the QGIS authentication system before the tree can be loaded."
                ),
                details=self.tr(
                    "The conversion is performed once and keeps the existing connections available in the plugin."
                ),
                primary_action=OverlayButtonState(
                    action=OverlayAction.CONVERT_CONNECTIONS,
                    text=self.tr("Convert connections"),
                ),
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if facts.has_plugin_update:
            return OverlayState(
                kind=OverlayKind.UNAVAILABLE,
                title=facts.plugin_update_title
                or self.tr("Update NextGIS Connect"),
                message=facts.plugin_update_message
                or self.tr("A newer plugin version is available."),
                details=facts.plugin_update_details,
                title_icon_name=facts.plugin_update_icon or "update",
                primary_action=facts.plugin_update_action,
                footer_action=facts.plugin_update_footer_action,
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if not facts.has_connections:
            return OverlayState(
                kind=OverlayKind.WELCOME,
                title=self.tr(
                    'Connect your first <span style="color: #0c65af;">Web GIS</span>'
                ),
                message=self.tr(
                    "Set up a connection to your Web GIS or create a new one to keep geodata, maps, and team workflows in sync."
                ),
                details=self.tr(
                    "Your resources will appear here after you add a connection."
                ),
                primary_action=OverlayButtonState(
                    action=OverlayAction.CREATE_CONNECTION,
                    text=self.tr("Add connection"),
                ),
                secondary_action=OverlayButtonState(
                    action=OverlayAction.CREATE_WEB_GIS,
                    text=self.tr("Create Web GIS"),
                    tooltip=self.tr(
                        "Open the web interface to create a new Web GIS."
                    ),
                ),
                footer_action=OverlayButtonState(
                    action=OverlayAction.CREATE_SANDBOX_CONNECTION,
                    text=self.tr("Try sandbox"),
                    tooltip=self.tr(
                        "Create a connection to the sandbox Web GIS."
                    ),
                ),
                logo_action=OverlayAction.OPEN_NEXTGIS_SITE,
            )

        if facts.has_search_connection_target:
            if facts.search_connection_exists:
                connection_name = (
                    facts.search_connection_name or facts.search_connection_url
                )
                return OverlayState(
                    kind=OverlayKind.SEARCH_CONNECTION,
                    title=self.tr("Search in another Web GIS"),
                    message=self.tr(
                        "Switch to the saved connection to continue searching."
                    ),
                    details=connection_name,
                    primary_action=OverlayButtonState(
                        action=OverlayAction.SWITCH_SEARCH_CONNECTION,
                        text=self.tr("Switch connection"),
                    ),
                    draw_background=True,
                )

            return OverlayState(
                kind=OverlayKind.SEARCH_CONNECTION,
                title=self.tr("Connection required"),
                message=self.tr(
                    "Create a connection to this Web GIS to continue searching."
                ),
                details=facts.search_connection_url,
                primary_action=OverlayButtonState(
                    action=OverlayAction.CREATE_SEARCH_CONNECTION,
                    text=self.tr("Add connection"),
                ),
                draw_background=True,
            )

        if facts.search_empty:
            return OverlayState(
                kind=OverlayKind.SEARCH_EMPTY,
                title=self.tr("Nothing found"),
                message=self.tr(
                    "No resources match the current search query."
                ),
                title_icon_name="inbox",
                draw_background=True,
            )

        return OverlayState(kind=OverlayKind.NONE)

    def create_web_gis_url(self) -> str:
        return f"https://my.nextgis.com/?{utm_tags('start')}"

    def tr(self, text: str) -> str:
        return QCoreApplication.translate("PluginOverlayResolver", text)


class PluginOverlayController(QObject):
    action_requested = pyqtSignal(object)
    state_changed = pyqtSignal(object)

    _current_state: OverlayState

    def __init__(
        self,
        state_model: PluginOverlayStateModel,
        overlay_host,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._state_model = state_model
        self._overlay_host = overlay_host
        self._resolver = PluginOverlayResolver()
        self._current_state = OverlayState(kind=OverlayKind.NONE)

        self._state_model.changed.connect(self.refresh)
        self._overlay_host.action_requested.connect(self._handle_action)
        self.refresh()

    @property
    def current_state(self) -> OverlayState:
        return self._current_state

    @property
    def resolver(self) -> PluginOverlayResolver:
        return self._resolver

    def refresh(self) -> None:
        self._current_state = self._resolver.resolve(
            self._state_model.snapshot()
        )
        self._overlay_host.set_overlay_state(self._current_state)
        self.state_changed.emit(self._current_state)

    def _handle_action(self, action: OverlayAction) -> None:
        if action == OverlayAction.NONE:
            return

        active_actions = {
            self._current_state.primary_action.action,
            self._current_state.secondary_action.action,
            self._current_state.footer_action.action,
            self._current_state.logo_action,
        }
        if action not in active_actions:
            return

        self.action_requested.emit(action)
