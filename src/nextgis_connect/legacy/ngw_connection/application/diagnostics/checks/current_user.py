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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsFeedback

from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.base import (
    BaseConnectionCheck,
    UpdateReporter,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckId,
    ConnectionCheckResult,
    ConnectionDiagnosticContext,
    CurrentUserInfo,
)
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgwError,
)

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )

CURRENT_USER_SUB_URL = "/api/component/auth/current_user"


@dataclass(frozen=True)
class CurrentUserExpectation:
    expects_guest: bool
    expected_keyname: Optional[str]

    @classmethod
    def from_connection(
        cls, connection: NgwConnection
    ) -> "CurrentUserExpectation":
        if connection.auth_config_id is None:
            return cls(expects_guest=True, expected_keyname="guest")

        expected_keyname = None
        if connection.method == "Basic":
            auth_manager = QgsApplication.authManager()
            is_loaded, auth_config = auth_manager.loadAuthenticationConfig(
                connection.auth_config_id,
                QgsAuthMethodConfig(),
                full=True,
            )
            if is_loaded and auth_config is not None:
                expected_keyname = auth_config.configMap().get("username")

        return cls(expects_guest=False, expected_keyname=expected_keyname)

    def matches(self, keyname: str) -> bool:
        if self.expects_guest:
            return keyname == "guest"

        return keyname != "guest"


class CurrentUserCheck(BaseConnectionCheck):
    check_id = ConnectionCheckId.CURRENT_USER
    is_blocking = True

    @property
    def title(self) -> str:
        return self.tr("Current user")

    @property
    def initial_description(self) -> str:
        return self.tr("Checking the current user response.")

    def run_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult:
        resolution = self.tr(
            "Check the network settings or the selected authentication configuration and try again."
        )
        try:
            response = ngw_connection.get(
                CURRENT_USER_SUB_URL,
                feedback=feedback,
            )
        except NgwError as error:
            self._raise_if_canceled(feedback, error)
            if self._is_network_error(error):
                return self._failure(
                    self.tr("Unable to read the current user."),
                    issue=self._network_issue(error, resolution),
                )

            if error.code == ErrorCode.AuthorizationError:
                return self._failure(
                    self.tr(
                        "The current user endpoint rejected authentication."
                    ),
                    issue=self._client_issue(
                        self.tr(
                            "The selected sign-in settings were rejected by the Web GIS."
                        ),
                        self.tr(
                            "Check the username and password or choose another saved user."
                        ),
                        technical_details=error.detail,
                    ),
                )

            issue_resolution = self.tr(
                "Ask the administrator to inspect the authentication component on the server."
            )
            issue_class = self._server_issue
            if self._connection.auth_config_id is not None:
                issue_resolution = self.tr(
                    "Check the selected authentication configuration or create a new one."
                )
                issue_class = self._client_issue

            return self._failure(
                self.tr("The current user endpoint returned an error."),
                issue=issue_class(
                    self.tr(
                        "The server did not return a valid current user response."
                    ),
                    issue_resolution,
                    technical_details=error.detail,
                ),
            )
        except NgConnectError as error:
            self._raise_if_canceled(feedback, error)
            return self._failure(
                self.tr("Unable to read the current user."),
                issue=self._network_issue(error, resolution),
            )

        response_json = self._response_to_json(
            response,
            self.tr(
                "Ask the administrator to inspect the authentication response on the server."
            ),
        )
        if isinstance(response_json, ConnectionCheckResult):
            return response_json

        if not isinstance(response_json, dict):
            return self._failure(
                self.tr("The current user response has an unexpected format."),
                issue=self._server_issue(
                    self.tr("The current user payload is not an object."),
                    self.tr(
                        "Ask the administrator to inspect the authentication response on the server."
                    ),
                ),
            )

        keyname = response_json.get("keyname")
        if not isinstance(keyname, str) or len(keyname) == 0:
            return self._failure(
                self.tr("The current user name is missing in the response."),
                issue=self._server_issue(
                    self.tr(
                        "The current user payload does not contain a valid keyname field."
                    ),
                    self.tr(
                        "Ask the administrator to inspect the authentication response on the server."
                    ),
                ),
            )

        display_name = response_json.get("display_name")
        if not isinstance(display_name, str) or len(display_name) == 0:
            display_name = keyname

        expectation = CurrentUserExpectation.from_connection(self._connection)
        if not expectation.matches(keyname):
            if expectation.expects_guest:
                issue = self._server_issue(
                    self.tr(
                        "The server returned an authenticated user for a guest connection."
                    ),
                    self.tr(
                        "Ask the administrator to inspect the authentication chain or active reverse proxy sessions."
                    ),
                )
            else:
                issue = self._client_issue(
                    self.tr(
                        "The selected authentication configuration resolved to guest access."
                    ),
                    self.tr(
                        "Check the selected authentication configuration or choose another saved user."
                    ),
                )

            return self._failure(
                self.tr(
                    "The current user does not match the connection settings."
                ),
                issue=issue,
            )

        payload = CurrentUserInfo(
            keyname=keyname,
            display_name=display_name,
            expected_keyname=expectation.expected_keyname,
            expects_guest=expectation.expects_guest,
        )
        if expectation.expects_guest:
            description = self.tr("The server returned guest access.")
        else:
            description = self.tr(
                "The server authenticated user {user}."
            ).format(user=keyname)

        return self._success(
            description,
            payload=payload,
        )
