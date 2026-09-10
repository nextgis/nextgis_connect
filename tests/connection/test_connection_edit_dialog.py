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

import uuid
from typing import List
from unittest.mock import MagicMock

import pytest
from qgis.PyQt.QtCore import Qt

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation import (
    connection_edit_dialog,
)
from nextgis_connect.legacy.ngw_connection.presentation.connection_edit_dialog import (
    LoginChoiceLabels,
    LoginChoiceResolver,
    NextgisQgisUserAvailability,
    NgwConnectionEditDialog,
)


def test_nextgis_qgis_user_is_unavailable_without_ngstd(monkeypatch) -> None:
    monkeypatch.setattr(connection_edit_dialog, "HAS_NGSTD", False)
    monkeypatch.setattr(connection_edit_dialog, "NGAccess", None)

    assert not NextgisQgisUserAvailability.is_available()


@pytest.mark.parametrize(
    (
        "is_auth_manager_disabled",
        "auth_method",
        "is_user_authorized",
        "endpoint",
        "expected_result",
    ),
    (
        (True, "NextGIS", True, "https://auth.nextgis.com", False),
        (False, "", True, "https://auth.nextgis.com", False),
        (False, "NextGIS", False, "https://auth.nextgis.com", False),
        (False, "NextGIS", True, "", False),
        (False, "NextGIS", True, "https://my.nextgis.com", False),
        (False, "NextGIS", True, "https://auth.nextgis.com", True),
    ),
)
def test_nextgis_qgis_user_availability_requires_usable_auth(
    monkeypatch,
    is_auth_manager_disabled: bool,
    auth_method: str,
    is_user_authorized: bool,
    endpoint: str,
    expected_result: bool,
) -> None:
    auth_manager = MagicMock()
    auth_manager.isDisabled.return_value = is_auth_manager_disabled
    auth_manager.configAuthMethodKey.return_value = auth_method
    qgs_application = MagicMock()
    qgs_application.authManager.return_value = auth_manager

    access = MagicMock()
    access.isUserAuthorized.return_value = is_user_authorized
    access.endPoint.return_value = endpoint
    ng_access = MagicMock()
    ng_access.instance.return_value = access

    monkeypatch.setattr(connection_edit_dialog, "HAS_NGSTD", True)
    monkeypatch.setattr(connection_edit_dialog, "NGAccess", ng_access)
    monkeypatch.setattr(
        connection_edit_dialog,
        "QgsApplication",
        qgs_application,
    )

    assert NextgisQgisUserAvailability.is_available() is expected_result


def test_current_nextgis_qgis_user_remains_visible_when_editing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        NextgisQgisUserAvailability,
        "is_available",
        lambda: False,
    )
    auth_manager = MagicMock()
    auth_manager.availableAuthMethodConfigs.return_value = {}
    auth_manager.configAuthMethodKey.return_value = "NextGIS"
    qgs_application = MagicMock()
    qgs_application.authManager.return_value = auth_manager
    monkeypatch.setattr(
        connection_edit_dialog,
        "QgsApplication",
        qgs_application,
    )
    resolver = LoginChoiceResolver(
        "https://example.nextgis.com",
        is_edit=True,
        filter_by_resource=True,
        labels=LoginChoiceLabels(
            nextgis_qgis_account="NextGIS QGIS account",
            saved_basic_sign_in="Saved sign-in",
            basic_sign_in_tooltip_format="{} - username and password",
        ),
    )

    nextgis_choices, _ = resolver.existing_choices("NextGIS")

    assert [choice.auth_config_id for choice in nextgis_choices] == ["NextGIS"]


def test_unavailable_nextgis_qgis_user_is_hidden_when_not_current(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        NextgisQgisUserAvailability,
        "is_available",
        lambda: False,
    )
    auth_manager = MagicMock()
    auth_manager.availableAuthMethodConfigs.return_value = {}
    auth_manager.configAuthMethodKey.return_value = "NextGIS"
    qgs_application = MagicMock()
    qgs_application.authManager.return_value = auth_manager
    monkeypatch.setattr(
        connection_edit_dialog,
        "QgsApplication",
        qgs_application,
    )
    resolver = LoginChoiceResolver(
        "https://example.nextgis.com",
        is_edit=False,
        filter_by_resource=True,
        labels=LoginChoiceLabels(
            nextgis_qgis_account="NextGIS QGIS account",
            saved_basic_sign_in="Saved sign-in",
            basic_sign_in_tooltip_format="{} - username and password",
        ),
    )

    nextgis_choices, _ = resolver.existing_choices("NextGIS")

    assert nextgis_choices == []


def test_edit_connection_marks_missing_saved_user(qgis_app) -> None:
    connection = NgwConnection(
        id="connection-id",
        name="Missing user",
        url="https://example.com",
        auth_config_id=str(uuid.uuid4()),
    )
    connections_manager = NgwConnectionsManager(
        [connection],
        current_connection_id=connection.id,
    )
    dialog = NgwConnectionEditDialog(
        None,
        connection=connection,
        connections_manager=connections_manager,
        save_on_accept=False,
    )

    assert dialog.userComboBox.currentIndex() == -1
    assert dialog.authGroupBox.isHidden()
    assert not dialog.authWarningLabel.isHidden()
    assert dialog.authWarningLabel.toolTip() == (
        "Saved sign-in parameters for the selected connection were deleted "
        "from the QGIS authentication database."
    )
    assert (
        dialog.authWarningLabel.minimumWidth()
        == dialog.authWarningLabel.maximumWidth()
        == dialog.authWarningLabel.pixmap().width()
    )
    assert dialog.authWarningLabel.alignment() == (
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    )
    assert dialog.loginLayout.spacing() == 2
    assert not dialog.testConnectionButton.isEnabled()

    dialog.userComboBox.setCurrentIndex(0)

    assert dialog.authWarningLabel.isHidden()
    assert dialog.testConnectionButton.isEnabled()

    dialog.deleteLater()


@pytest.mark.parametrize(
    ("filter_by_resource", "expected_auth_config_ids"),
    (
        (True, ["matching"]),
        (False, ["matching", "other"]),
    ),
)
def test_login_choice_resolver_filters_basic_users_by_web_gis(
    monkeypatch,
    filter_by_resource: bool,
    expected_auth_config_ids: List[str],
) -> None:
    matching_config = MagicMock()
    matching_config.method.return_value = "Basic"
    matching_config.uri.return_value = "https://example.nextgis.com"
    matching_config.configMap.return_value = {"username": "Alice"}
    other_config = MagicMock()
    other_config.method.return_value = "Basic"
    other_config.uri.return_value = "https://other.nextgis.com"
    other_config.configMap.return_value = {"username": "Bob"}
    auth_manager = MagicMock()
    auth_manager.availableAuthMethodConfigs.return_value = {
        "matching": matching_config,
        "other": other_config,
    }
    qgs_application = MagicMock()
    qgs_application.authManager.return_value = auth_manager
    monkeypatch.setattr(
        connection_edit_dialog,
        "QgsApplication",
        qgs_application,
    )
    resolver = LoginChoiceResolver(
        "https://example.nextgis.com",
        is_edit=True,
        filter_by_resource=filter_by_resource,
        labels=LoginChoiceLabels(
            nextgis_qgis_account="NextGIS QGIS account",
            saved_basic_sign_in="Saved sign-in",
            basic_sign_in_tooltip_format="{} - username and password",
        ),
    )

    _, basic_choices = resolver.existing_choices("")

    assert [
        choice.auth_config_id for choice in basic_choices
    ] == expected_auth_config_ids
    assert [choice.title for choice in basic_choices] == [
        "Alice",
        "Bob",
    ][: len(expected_auth_config_ids)]
    assert [choice.tooltip for choice in basic_choices] == [
        "Alice - username and password",
        "Bob - username and password",
    ][: len(expected_auth_config_ids)]
