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

from qgis.PyQt.QtCore import QObject, pyqtSignal

from nextgis_connect.legacy.tree_widget.overlay import (
    OverlayAction,
    OverlayButtonState,
    OverlayFacts,
    OverlayKind,
    PluginOverlayController,
    PluginOverlayResolver,
    PluginOverlayStateModel,
)


class FakeOverlayHost(QObject):
    action_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.states = []

    def set_overlay_state(self, state) -> None:
        self.states.append(state)


def test_loading_has_highest_priority() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=False,
            is_loading=True,
            loading_title="Loading",
            loading_compact_title="Wait",
            loading_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text="Cancel",
            ),
            has_auth_error=True,
            is_available=False,
            unavailable_message="Unavailable",
        )
    )

    assert state.kind == OverlayKind.LOADING
    assert state.compact_title == "Wait"
    assert state.title == "Loading"
    assert state.secondary_action.action == OverlayAction.CANCEL
    assert state.logo_action == OverlayAction.OPEN_NEXTGIS_SITE


def test_loading_without_corporate_background_hides_logo_action() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            is_loading=True,
            loading_draw_background=False,
        )
    )

    assert state.kind == OverlayKind.LOADING
    assert state.draw_background is False
    assert state.logo_action == OverlayAction.NONE


def test_loading_propagates_cancel_pending() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            is_loading=True,
            loading_cancel_pending=True,
            loading_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text="Cancel",
            ),
        )
    )

    assert state.kind == OverlayKind.LOADING
    assert state.cancel_pending is True
    assert state.secondary_action.action == OverlayAction.CANCEL


def test_auth_has_priority_over_unavailable() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            has_auth_error=True,
            is_available=False,
            unavailable_message="Unavailable",
        )
    )

    assert state.kind == OverlayKind.AUTH_REQUIRED
    assert state.primary_action.action == OverlayAction.OPEN_NEXTGIS_SETTINGS


def test_error_overlay_has_background_without_logo() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            has_error=True,
            error_message="The request failed.",
        )
    )

    assert state.kind == OverlayKind.ERROR
    assert state.draw_background is True
    assert state.logo_action == OverlayAction.NONE


def test_first_connection_state_has_expected_actions_and_copy() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(has_connections=False)
    )

    assert state.kind == OverlayKind.WELCOME
    assert "Web GIS" in state.title
    assert (
        state.message
        == "Set up a connection to your Web GIS or create a new one to keep geodata, maps, and team workflows in sync."
    )
    assert (
        state.details
        == "Your resources will appear here after you add a connection."
    )
    assert state.primary_action.action == OverlayAction.CREATE_CONNECTION
    assert state.secondary_action.action == OverlayAction.CREATE_WEB_GIS
    assert state.secondary_action.text == "Create Web GIS"
    assert state.secondary_action.tooltip != state.secondary_action.text
    assert "web interface" in state.secondary_action.tooltip
    assert (
        state.footer_action.action == OverlayAction.CREATE_SANDBOX_CONNECTION
    )
    assert state.footer_action.text == "Try sandbox"
    assert state.logo_action == OverlayAction.OPEN_NEXTGIS_SITE


def test_controller_accepts_footer_and_logo_actions() -> None:
    state_model = PluginOverlayStateModel()
    overlay_host = FakeOverlayHost()
    controller = PluginOverlayController(state_model, overlay_host)
    emitted_actions = []
    controller.action_requested.connect(emitted_actions.append)

    state_model.update(has_connections=False)

    overlay_host.action_requested.emit(OverlayAction.CREATE_SANDBOX_CONNECTION)
    overlay_host.action_requested.emit(OverlayAction.OPEN_NEXTGIS_SITE)
    overlay_host.action_requested.emit(OverlayAction.CONTACT_SUPPORT)

    assert emitted_actions == [
        OverlayAction.CREATE_SANDBOX_CONNECTION,
        OverlayAction.OPEN_NEXTGIS_SITE,
    ]


def test_unavailable_update_state_uses_title_icon() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            is_available=False,
            unavailable_title="Update is available",
            unavailable_compact_title="Update available",
            unavailable_message=(
                "Please update the plugin from the QGIS plugin manager."
            ),
            unavailable_details="Details",
            unavailable_icon="update",
            unavailable_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
        )
    )

    assert state.kind == OverlayKind.UNAVAILABLE
    assert state.title == "Update is available"
    assert state.compact_title == "Update available"
    assert "Update is available" not in state.message
    assert state.title_icon_name == "update"
    assert state.illustration_name == ""
    assert state.primary_action.action == OverlayAction.OPEN_PLUGIN_MANAGER


def test_plugin_update_state_reuses_update_overlay_with_skip_action() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            has_plugin_update=True,
            plugin_update_title="Update is available",
            plugin_update_message=(
                "Please update the plugin from the QGIS plugin manager."
            ),
            plugin_update_details="Details",
            plugin_update_icon="update",
            plugin_update_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
            plugin_update_footer_action=OverlayButtonState(
                action=OverlayAction.SKIP_PLUGIN_UPDATE,
                text="Skip this time",
                text_opacity=0.5,
            ),
        )
    )

    assert state.kind == OverlayKind.UNAVAILABLE
    assert state.title == "Update is available"
    assert "Update is available" not in state.message
    assert state.title_icon_name == "update"
    assert state.illustration_name == ""
    assert state.primary_action.action == OverlayAction.OPEN_PLUGIN_MANAGER
    assert state.footer_action.action == OverlayAction.SKIP_PLUGIN_UPDATE
    assert state.footer_action.text == "Skip this time"
    assert state.footer_action.text_opacity == 0.5


def test_unsupported_version_state_has_priority_over_skippable_update() -> (
    None
):
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            is_available=False,
            unavailable_title="Update is available",
            unavailable_message=(
                "Please update the plugin from the QGIS plugin manager."
            ),
            unavailable_icon="update",
            unavailable_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
            has_plugin_update=True,
            plugin_update_footer_action=OverlayButtonState(
                action=OverlayAction.SKIP_PLUGIN_UPDATE,
                text="Skip this time",
                text_opacity=0.5,
            ),
        )
    )

    assert state.kind == OverlayKind.UNAVAILABLE
    assert state.title_icon_name == "update"
    assert state.primary_action.action == OverlayAction.OPEN_PLUGIN_MANAGER
    assert state.footer_action.action == OverlayAction.NONE


def test_search_empty_is_used_when_other_states_are_clear() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            search_empty=True,
        )
    )

    assert state.kind == OverlayKind.SEARCH_EMPTY
    assert state.draw_background is True
    assert state.logo_action == OverlayAction.NONE
    assert state.title_icon_name == "inbox"


def test_search_connection_target_offers_saved_connection_switch() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            has_search_connection_target=True,
            search_connection_exists=True,
            search_connection_url="https://target.nextgis.com",
            search_connection_name="Target",
            search_empty=True,
        )
    )

    assert state.kind == OverlayKind.SEARCH_CONNECTION
    assert state.details == "Target"
    assert (
        state.primary_action.action == OverlayAction.SWITCH_SEARCH_CONNECTION
    )
    assert state.logo_action == OverlayAction.NONE


def test_search_connection_target_offers_new_connection_creation() -> None:
    state = PluginOverlayResolver().resolve(
        OverlayFacts(
            has_connections=True,
            has_search_connection_target=True,
            search_connection_exists=False,
            search_connection_url="https://new.nextgis.com",
            search_empty=True,
        )
    )

    assert state.kind == OverlayKind.SEARCH_CONNECTION
    assert state.details == "https://new.nextgis.com"
    assert (
        state.primary_action.action == OverlayAction.CREATE_SEARCH_CONNECTION
    )
    assert state.logo_action == OverlayAction.NONE
