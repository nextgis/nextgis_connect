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

from typing import List, Tuple

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation import (
    connection_switch_menu,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_edit_dialog import (
    LoginChoice,
    LoginChoiceKind,
    NextgisQgisUserAvailability,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_switch_menu import (
    ConnectionSwitchMenu,
)


class LoginChoiceResolverStub:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def existing_choices(
        self,
        current_auth_config_id: str,
    ) -> Tuple[List[LoginChoice], List[LoginChoice]]:
        del current_auth_config_id
        return (
            [],
            [
                LoginChoice(
                    LoginChoiceKind.EXISTING,
                    "Alice",
                    "Basic",
                    "auth001",
                    "Alice - username and password",
                ),
                LoginChoice(
                    LoginChoiceKind.EXISTING,
                    "Bob",
                    "Basic",
                    "auth002",
                    "Bob - username and password",
                ),
            ],
        )


class NextgisLoginChoiceResolverStub(LoginChoiceResolverStub):
    def existing_choices(
        self,
        current_auth_config_id: str,
    ) -> Tuple[List[LoginChoice], List[LoginChoice]]:
        del current_auth_config_id
        return (
            [
                LoginChoice(
                    LoginChoiceKind.EXISTING,
                    "NextGIS QGIS User",
                    "NextGIS",
                    "NextGIS",
                )
            ],
            [],
        )


def test_switch_menu_marks_current_connection_and_user(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        connection_switch_menu,
        "LoginChoiceResolver",
        LoginChoiceResolverStub,
    )
    first_connection = NgwConnection(
        "first",
        "First Web GIS",
        "https://first.nextgis.com",
        "auth001",
    )
    second_connection = NgwConnection(
        "second",
        "Second Web GIS",
        "https://second.nextgis.com",
        None,
    )

    menu = ConnectionSwitchMenu(
        [first_connection, second_connection],
        first_connection.id,
    )
    connection_actions = menu.actions()

    assert [action.text() for action in connection_actions] == [
        first_connection.name,
        second_connection.name,
    ]
    assert connection_actions[0].isCheckable()
    assert connection_actions[0].isChecked()
    assert connection_actions[0].font().bold()
    assert not connection_actions[1].isCheckable()
    assert not connection_actions[1].isChecked()
    assert not connection_actions[1].font().bold()

    first_user_actions = connection_actions[0].menu().actions()
    assert [action.text() for action in first_user_actions] == [
        "Guest access",
        "Alice",
        "Bob",
    ]
    assert not first_user_actions[0].isChecked()
    assert first_user_actions[1].isChecked()
    assert not first_user_actions[2].isChecked()
    assert first_user_actions[1].toolTip() == "Alice - username and password"

    second_user_actions = connection_actions[1].menu().actions()
    assert second_user_actions[0].isChecked()
    menu.deleteLater()


def test_switch_menu_emits_selected_connection_and_user(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        connection_switch_menu,
        "LoginChoiceResolver",
        LoginChoiceResolverStub,
    )
    connection = NgwConnection(
        "connection-id",
        "Web GIS",
        "https://example.nextgis.com",
        None,
    )
    menu = ConnectionSwitchMenu([connection], connection.id)
    emitted_requests = []
    menu.switch_requested.connect(
        lambda connection_id, auth_config_id: emitted_requests.append(
            (connection_id, auth_config_id)
        )
    )

    user_actions = menu.actions()[0].menu().actions()
    user_actions[2].trigger()

    assert emitted_requests == [(connection.id, "auth002")]
    menu.deleteLater()


def test_clicking_connection_selects_its_default_user(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        connection_switch_menu,
        "LoginChoiceResolver",
        LoginChoiceResolverStub,
    )
    first_connection = NgwConnection(
        "first",
        "First Web GIS",
        "https://first.nextgis.com",
        "auth001",
    )
    second_connection = NgwConnection(
        "second",
        "Second Web GIS",
        "https://second.nextgis.com",
        None,
    )
    menu = ConnectionSwitchMenu(
        [first_connection, second_connection],
        first_connection.id,
    )
    observed_switches = []
    menu.switch_requested.connect(
        lambda connection_id, auth_config_id: observed_switches.append(
            (connection_id, auth_config_id, menu.isVisible())
        )
    )
    menu.popup(QPoint(100, 100))
    QApplication.processEvents()
    second_connection_action = menu.actions()[1]

    QTest.mouseClick(
        menu,
        Qt.MouseButton.LeftButton,
        pos=menu.actionGeometry(second_connection_action).center(),
    )

    assert observed_switches == [(second_connection.id, None, False)]
    menu.deleteLater()


def test_clicking_connection_selects_missing_saved_user(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        connection_switch_menu,
        "LoginChoiceResolver",
        LoginChoiceResolverStub,
    )
    connection = NgwConnection(
        "connection-id",
        "Web GIS",
        "https://example.nextgis.com",
        "missing-auth-config",
    )
    menu = ConnectionSwitchMenu([connection], None)
    observed_switches = []
    menu.switch_requested.connect(
        lambda connection_id, auth_config_id: observed_switches.append(
            (connection_id, auth_config_id, menu.isVisible())
        )
    )

    menu.popup(QPoint(100, 100))
    QApplication.processEvents()
    connection_action = menu.actions()[0]
    QTest.mouseClick(
        menu,
        Qt.MouseButton.LeftButton,
        pos=menu.actionGeometry(connection_action).center(),
    )

    assert observed_switches == [(connection.id, "missing-auth-config", False)]
    menu.deleteLater()


def test_empty_switch_menu_has_disabled_placeholder(qgis_app) -> None:
    del qgis_app
    menu = ConnectionSwitchMenu([], None)

    assert len(menu.actions()) == 1
    assert not menu.actions()[0].isEnabled()
    menu.deleteLater()


def test_unavailable_saved_nextgis_user_is_visible_but_disabled(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        connection_switch_menu,
        "LoginChoiceResolver",
        NextgisLoginChoiceResolverStub,
    )
    monkeypatch.setattr(
        NextgisQgisUserAvailability,
        "is_available",
        lambda: False,
    )
    connection = NgwConnection(
        "connection-id",
        "Web GIS",
        "https://example.nextgis.com",
        "NextGIS",
    )
    menu = ConnectionSwitchMenu([connection], connection.id)
    emitted_requests = []
    menu.switch_requested.connect(
        lambda connection_id, auth_config_id: emitted_requests.append(
            (connection_id, auth_config_id)
        )
    )

    connection_action = menu.actions()[0]
    nextgis_action = menu.actions()[0].menu().actions()[1]

    assert nextgis_action.isChecked()
    assert not nextgis_action.isEnabled()

    menu.popup(QPoint(100, 100))
    QApplication.processEvents()
    QTest.mouseClick(
        menu,
        Qt.MouseButton.LeftButton,
        pos=menu.actionGeometry(connection_action).center(),
    )

    assert emitted_requests == []
    menu.deleteLater()
