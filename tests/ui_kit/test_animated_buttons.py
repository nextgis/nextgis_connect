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

import pytest
from qgis.PyQt.QtCore import QAbstractAnimation, Qt

from nextgis_connect.ui_kit.buttons import (
    CancelButton,
    PrimaryButton,
    SecondaryButton,
    ShiningButton,
)


@pytest.mark.parametrize(
    "button_class",
    [PrimaryButton, SecondaryButton, ShiningButton, CancelButton],
)
def test_leave_before_first_hover_frame_cancels_transition(
    qgis_app, button_class
):
    button = button_class()
    normal = button._normal_state()
    button._is_hovered = True
    button._refresh_visual_state()
    assert button._transition.state() == QAbstractAnimation.State.Running
    assert button._states_equal(button._current_state, normal)
    button._is_hovered = False
    button._refresh_visual_state()
    assert button._transition.state() == QAbstractAnimation.State.Stopped
    assert button._states_equal(button._current_state, normal)
    assert button._states_equal(button._animation_end_state, normal)
    button.close()


def test_secondary_button_returns_to_normal_after_interrupted_hover(qgis_app):
    button = SecondaryButton("Action")
    button._is_hovered = True
    button._refresh_visual_state()
    button._transition.setCurrentTime(100)
    button._is_hovered = False
    button._refresh_visual_state()
    button._transition.setCurrentTime(button._TRANSITION_DURATION_MS)
    assert button._states_equal(button._current_state, button._normal_state())
    button.close()


def test_button_hide_resets_hover_and_pressed_states(qgis_app):
    button = SecondaryButton("Action")
    button.show()
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    button._is_hovered = True
    button._is_pressed = True
    button._refresh_visual_state()
    button.hide()
    assert not button._is_hovered
    assert not button._is_pressed
    assert button._transition.state() == QAbstractAnimation.State.Stopped
    assert button._states_equal(button._current_state, button._normal_state())
    button.close()
