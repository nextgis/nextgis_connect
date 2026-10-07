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

from nextgis_connect.legacy.tree_widget.overlay.state import (
    OverlayAction,
    OverlayButtonState,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.surface import (
    FooterLinkLabel,
)


def test_skip_update_footer_link_uses_stronger_opacity_on_hover() -> None:
    action_state = OverlayButtonState(
        action=OverlayAction.SKIP_PLUGIN_UPDATE,
        text="Skip this time",
        text_opacity=0.5,
    )

    assert (
        FooterLinkLabel._effective_text_opacity_for(
            action_state,
            is_hovered=False,
        )
        == 0.5
    )
    assert (
        FooterLinkLabel._effective_text_opacity_for(
            action_state,
            is_hovered=True,
        )
        == 0.8
    )


def test_regular_footer_link_keeps_configured_opacity_on_hover() -> None:
    action_state = OverlayButtonState(
        action=OverlayAction.CREATE_SANDBOX_CONNECTION,
        text="Try in sandbox",
        text_opacity=0.5,
    )

    assert (
        FooterLinkLabel._effective_text_opacity_for(
            action_state,
            is_hovered=True,
        )
        == 0.5
    )
