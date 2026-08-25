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
from qgis.PyQt.QtCore import QSize
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


def test_loading_overlay_elides_dynamic_status_and_reflows_title(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    title = "Loading resources from the selected Web GIS connection"
    status = "very-long-resource-name-" * 12
    widget = LoadingOverlayWidget()
    widget.resize(360, 500)
    widget.set_state(
        OverlayState(
            kind=OverlayKind.LOADING,
            title=title,
            message=status,
            secondary_action=OverlayButtonState(
                action=OverlayAction.CANCEL,
                text="Cancel",
            ),
        )
    )
    widget.show()
    _process_events()

    widget.resize(250, 500)
    _process_events()

    assert widget._card_stack.currentWidget() is widget._content_widget
    assert widget._message_label.text() != status
    assert widget._message_label.toolTip() == status
    assert widget._title_label.height() >= widget._title_label.heightForWidth(
        widget._title_label.width()
    )


def test_loading_overlay_uses_equal_vertical_padding(
    qgis_app,
    overlay_widget_environment,
) -> None:
    del qgis_app, overlay_widget_environment

    widget = LoadingOverlayWidget()
    widget.set_state(OverlayState(kind=OverlayKind.LOADING, title="Loading"))

    margins = widget._content_layout.contentsMargins()
    assert margins.top() == margins.bottom()


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
