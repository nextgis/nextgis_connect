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
# with this program.  If not, see <https://www.gnu.org/licenses/>.

from pathlib import Path
from types import SimpleNamespace

import pytest
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QBoxLayout

from nextgis_connect.legacy.tree_widget.overlay.state import (
    OverlayAction,
    OverlayButtonState,
    OverlayKind,
    OverlayState,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.action import (
    ActionOverlayWidget,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.loading import (
    LoadingOverlayWidget,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.buttons import ShiningButton
from nextgis_connect.ui_kit.graphics.background import NextgisBackgroundPainter
from nextgis_connect.ui_kit.graphics.decorator import NextgisDecorator


@pytest.fixture
def overlay_widget_environment(monkeypatch):
    plugin_path = (
        Path(__file__).resolve().parents[2] / "src" / "nextgis_connect"
    )
    plugin = SimpleNamespace(path=plugin_path)
    monkeypatch.setattr(NgConnectInterface, "instance", lambda: plugin)


def _process_events() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def test_action_overlay_switches_button_layout_on_resize(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(380, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            title="Unable to load resources",
            message="The request failed.",
            primary_action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text="Try again",
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text="Run diagnostics",
            ),
        )
    )
    widget.show()
    _process_events()

    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.LeftToRight
    )

    widget.resize(300, 500)
    _process_events()

    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.TopToBottom
    )

    widget.resize(380, 500)
    _process_events()

    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.LeftToRight
    )
    assert widget._card_stack.currentWidget() is widget._content_widget


def test_action_overlay_does_not_reset_stacked_buttons_before_layout(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    compact_title = 'Connect <span style="color: #0c65af;">Web GIS</span>'
    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.WELCOME,
            title="Connect your first Web GIS",
            compact_title=compact_title,
            primary_action=OverlayButtonState(
                action=OverlayAction.CREATE_CONNECTION,
                text="Add connection",
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.CREATE_WEB_GIS,
                text="Create Web GIS",
            ),
        )
    )
    metrics = widget._title_label.fontMetrics()
    compact_width = metrics.horizontalAdvance("Connect Web GIS")
    widget._sync_title_text(compact_width + metrics.horizontalAdvance("M"))
    assert widget._title_label.text() == compact_title.replace(
        "Web GIS",
        "Web\u00a0GIS",
    )

    widget._update_responsive_layout(content_width=1, card_width=1)
    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.TopToBottom
    )

    widget._prepare_content_for_layout()

    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.TopToBottom
    )


def test_background_grid_is_darker_in_light_theme(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor("white"))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor("black"))
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("black"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("white"))

    assert NextgisBackgroundPainter._grid_color(light_palette).alpha() == 64
    assert NextgisBackgroundPainter._grid_color(dark_palette).alpha() == 50


def test_action_overlay_centers_title_with_icon(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            title="Plugin update required",
            title_icon_name="update",
        )
    )

    assert not widget._title_icon_label.isHidden()
    assert (
        widget._title_layout.itemAt(1).alignment()
        == Qt.AlignmentFlag.AlignVCenter
    )
    assert widget._title_label.alignment() == (
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


def test_action_overlay_uses_compact_spacing_and_illustration(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            illustration_name="globe_2_cancel",
        )
    )

    assert widget._content_layout.spacing() == NextgisDecorator.CARD_SPACING
    assert widget._buttons_layout.contentsMargins().top() == 0
    assert widget._illustration_widget.preferred_size() == 48


def test_action_overlay_keeps_spacing_and_illustration_when_narrowed(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(700, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            illustration_name="globe_2_cancel",
        )
    )
    widget.show()
    _process_events()

    assert widget._card.width() == NextgisDecorator.CARD_MAX_WIDTH
    assert not widget._illustration_widget.isHidden()
    assert widget._content_layout.spacing() == NextgisDecorator.CARD_SPACING

    widget.resize(320, 500)
    _process_events()

    assert not widget._illustration_widget.isHidden()
    assert widget._content_layout.spacing() == NextgisDecorator.CARD_SPACING


def test_action_overlay_keeps_title_on_one_line_when_compact(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(294, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            title="Server update required",
            title_icon_name="update",
            primary_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
        )
    )
    widget.show()
    _process_events()

    assert (
        widget._content_layout.contentsMargins().left()
        == widget._MINIMUM_CARD_PADDING
    )
    assert not widget._title_label.wordWrap()
    assert (
        widget._title_label.height() == widget._title_label.sizeHint().height()
    )
    assert widget._title_label.heightForWidth(widget._title_label.width()) == (
        widget._title_label.fontMetrics().height()
    )


def test_action_overlay_uses_compact_title_then_elides(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    full_title = "Server update required"
    compact_title = "Update required"
    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            title=full_title,
            compact_title=compact_title,
            title_icon_name="update",
        )
    )

    metrics = widget._title_label.fontMetrics()
    icon_width = widget._TITLE_ICON_SIZE + widget._title_layout.spacing()
    compact_width = metrics.horizontalAdvance(compact_title)
    glyph_reserve = metrics.horizontalAdvance("M")
    widget._sync_title_text(icon_width + compact_width + glyph_reserve)

    assert widget._title_label.text() == compact_title
    assert widget._title_label.toolTip() == full_title

    widget._sync_title_text(icon_width + compact_width * 3 // 4)

    assert widget._title_label.text() != compact_title
    assert widget._title_label.text().endswith("…")
    assert widget._title_label.toolTip() == full_title


def test_action_overlay_footer_does_not_stretch_vertically(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(324, 345)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            title="Update is available",
            title_icon_name="update",
            message="A newer version of NextGIS Connect is available.",
            details="Current version: 3.0.6\nAvailable version: 4.0.6",
            primary_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
            footer_action=OverlayButtonState(
                action=OverlayAction.SKIP_PLUGIN_UPDATE,
                text="Skip this time",
            ),
        )
    )
    widget.show()
    _process_events()

    assert (
        widget._footer_link.height() == widget._footer_link.sizeHint().height()
    )
    assert widget._title_layout.geometry().top() == (
        widget._content_widget.height()
        - widget._footer_link.geometry().bottom()
        - 1
    )


def test_action_overlay_preserves_single_newline_in_details(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            details="Current version: 3.0.6\nAvailable version: 4.0.6",
        )
    )

    assert "Current version: 3.0.6<br/>Available version: 4.0.6" in (
        widget._details_label.text()
    )


def test_action_overlay_renders_html_in_details(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            details="<b>Invalid connection</b>",
        )
    )

    assert "<b>Invalid connection</b>" in widget._details_label.text()
    assert "&lt;b&gt;" not in widget._details_label.text()


def test_action_overlay_reduces_illustration_for_limited_height(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(350, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            title="Unable to connect",
            message="The selected connection is invalid or unavailable.",
            details=(
                "Run diagnostics to check the connection settings and server availability."
            ),
            illustration_name="globe_2_cancel",
            primary_action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text="Run diagnostics",
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text="Try again",
            ),
        )
    )
    widget.show()
    _process_events()

    preferred_size = widget._illustration_widget.preferred_size()
    widget.resize(350, 180)
    _process_events()

    assert (
        widget._illustration_widget.isHidden()
        or widget._illustration_widget.current_size() < preferred_size
    )


def test_action_overlay_centers_text(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()

    assert widget._message_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert widget._details_label.alignment() == Qt.AlignmentFlag.AlignCenter


def test_action_overlay_hides_empty_message(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(OverlayState(kind=OverlayKind.ERROR, message=""))

    assert widget._message_label.isHidden()


def test_action_overlay_compensates_title_line_box_without_message(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(350, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            title="Unable to connect",
            details="The selected connection is invalid.\n\nRun diagnostics.",
            primary_action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text="Run diagnostics",
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text="Try again",
            ),
        )
    )
    widget.show()
    _process_events()

    title_bottom = widget._title_layout.geometry().bottom() + 1
    details_top = widget._details_label.geometry().top()
    details_bottom = widget._details_label.geometry().bottom() + 1
    buttons_top = widget._buttons_layout.geometry().top()

    assert details_top - title_bottom == widget._TITLE_TO_DETAILS_SPACING
    assert buttons_top - details_bottom == NextgisDecorator.CARD_SPACING
    assert "margin: 0px 0px 4px 0px" in widget._details_label.text()


def test_transparent_overlay_does_not_draw_decorated_background(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(400, 500)
    widget.set_state(
        OverlayState(kind=OverlayKind.ERROR, draw_background=False)
    )
    widget.show()
    _process_events()

    assert not widget._draw_background


def test_plugin_update_uses_shining_button(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.UNAVAILABLE,
            primary_action=OverlayButtonState(
                action=OverlayAction.OPEN_PLUGIN_MANAGER,
                text="Update plugin",
            ),
        )
    )

    assert isinstance(widget._shining_primary_button, ShiningButton)
    assert not widget._shining_primary_button.isHidden()
    assert widget._primary_button.isHidden()


def test_connection_actions_are_stacked(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.resize(500, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.ERROR,
            primary_action=OverlayButtonState(
                action=OverlayAction.RUN_DIAGNOSTICS,
                text="Run diagnostics",
            ),
            secondary_action=OverlayButtonState(
                action=OverlayAction.RELOAD_TREE,
                text="Try again",
            ),
        )
    )
    widget.show()
    _process_events()

    assert (
        widget._buttons_layout.direction() == QBoxLayout.Direction.TopToBottom
    )
    assert not widget._primary_button.icon().isNull()


def test_loading_overlay_message_uses_secondary_text_color(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = LoadingOverlayWidget()
    expected_color = NextgisDecorator.system_muted_text_color(widget.palette())

    assert (
        widget._message_label.palette().color(
            widget._message_label.foregroundRole()
        )
        == expected_color
    )


def test_loading_overlay_uses_compact_title_and_right_elides_status(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    title = "Downloading styles for Web GIS"
    compact_title = "Downloading styles"
    status = "very-long-resource-name-" * 12
    widget = LoadingOverlayWidget()
    widget.resize(500, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.LOADING,
            title=title,
            compact_title=compact_title,
            message="Loading resources from the selected Web GIS connection.",
            details=status,
            secondary_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text="Cancel",
            ),
        )
    )
    widget.show()
    _process_events()
    assert widget._title_label.text() == title.replace(
        "Web GIS", "Web\u00a0GIS"
    )

    widget.resize(250, 500)
    _process_events()

    assert widget._card_stack.currentWidget() is widget._content_widget
    assert widget._title_label.text() == compact_title
    assert widget._message_label.toolTip() == ""
    assert (
        widget._message_label.height()
        >= widget._message_label.heightForWidth(widget._message_label.width())
    )
    expected_status = widget._details_label.fontMetrics().elidedText(
        status,
        Qt.TextElideMode.ElideRight,
        widget._details_label.contentsRect().width(),
    )
    assert widget._details_label.text() == expected_status
    assert widget._details_label.toolTip() == status
    assert (
        widget._title_label.height() == widget._title_label.sizeHint().height()
    )

    title_top = widget._card.y() + widget._title_label.y()
    progress_top = widget._card.y() + widget._progress_bar.y()
    widget.set_state(
        OverlayState(
            kind=OverlayKind.LOADING,
            title=title,
            compact_title=compact_title,
            message="Loading resources from the selected Web GIS connection.",
            details="another-resource-name-" * 12,
            secondary_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text="Cancel",
            ),
        )
    )
    _process_events()

    assert widget._card.y() + widget._title_label.y() == title_top
    assert widget._card.y() + widget._progress_bar.y() == progress_top


def test_loading_overlay_uses_equal_vertical_padding(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = LoadingOverlayWidget()
    widget.resize(320, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.LOADING,
            title="Downloading styles...",
            message="Please wait while the current operation finishes.",
            details="A very long resource name that is currently downloading",
        )
    )
    widget.show()
    _process_events()

    margins = widget._content_layout.contentsMargins()
    assert margins.top() == margins.bottom()
    assert widget._title_label.geometry().top() == margins.top()
    assert (
        widget._content_widget.height()
        - widget._details_label.geometry().bottom()
        - 1
        == margins.bottom()
    )


def test_loading_and_action_overlays_use_same_padding(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    action_widget = ActionOverlayWidget()
    loading_widget = LoadingOverlayWidget()
    for widget in (action_widget, loading_widget):
        widget.resize(350, 500)
        widget.show()
        widget.sync_layout()
    _process_events()

    action_margins = action_widget._content_layout.contentsMargins()
    loading_margins = loading_widget._content_layout.contentsMargins()
    assert loading_margins == action_margins
    assert (
        loading_widget._content_layout.spacing()
        == action_widget._content_layout.spacing()
    )


def test_logo_uses_fixed_margin_or_is_hidden_when_space_is_insufficient(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = ActionOverlayWidget()
    widget.set_logo_action(OverlayAction.OPEN_NEXTGIS_SITE)

    logo_size = widget._logo_widget.sizeHint()
    margin = widget._LOGO_MARGIN_NORMAL
    card_bottom = 100
    required_height = logo_size.height() + 2 * margin

    assert (
        widget._logo_geometry_for_card(
            QSize(400, card_bottom + required_height - 1),
            card_bottom,
        )
        is None
    )

    geometry = widget._logo_geometry_for_card(
        QSize(400, card_bottom + required_height),
        card_bottom,
    )
    assert geometry is not None
    assert geometry.bottom() == card_bottom + required_height - margin - 1
