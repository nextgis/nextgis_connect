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

from typing import TYPE_CHECKING

from qgis.core import QgsFeedback

from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckId,
    ConnectionCheckResult,
    ConnectionDiagnosticContext,
    ConnectionIssue,
    ConnectionIssueSource,
)
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgwError,
)

from .base import BaseConnectionCheck, UpdateReporter

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )

ROOT_RESOURCE_SUB_URL = "/api/resource/0"


class RootResourceAccessCheck(BaseConnectionCheck):
    check_id = ConnectionCheckId.ROOT_RESOURCE
    is_blocking = True

    @property
    def title(self) -> str:
        return self.tr("Root resource access")

    @property
    def initial_description(self) -> str:
        return self.tr("Checking read access to the root resource.")

    def run_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult:
        resolution = self.tr(
            "Check the server availability or ask the administrator to inspect the root resource permissions."
        )
        try:
            response = ngw_connection.get(
                ROOT_RESOURCE_SUB_URL,
                feedback=feedback,
            )
        except NgwError as error:
            self._raise_if_canceled(feedback, error)
            if self._is_network_error(error):
                return self._failure(
                    self.tr("Unable to read the root resource."),
                    issue=self._network_issue(error, resolution),
                )

            if error.code == ErrorCode.NotFound:
                return self._failure(
                    self.tr("Web GIS was not found at the specified address."),
                    issue=self._client_issue(
                        self.tr(
                            "Web GIS was not found at the specified address."
                        ),
                        self.tr(
                            "Check the Web GIS URL and run the verification again."
                        ),
                        technical_details=error.detail,
                    ),
                )

            if error.code in (
                ErrorCode.AuthorizationError,
                ErrorCode.PermissionsError,
            ):
                resolution = self.tr(
                    "Use another account or ask the administrator to grant read access to the root resource."
                )
                if self._connection.auth_config_id is None:
                    resolution = self.tr(
                        "Sign in with an account that can read the root resource or ask the administrator to grant guest access."
                    )
                details = self.tr(
                    "The selected sign-in settings do not grant access to the root resource."
                )
                if error.code == ErrorCode.AuthorizationError:
                    details = self.tr(
                        "The selected sign-in settings were rejected by the Web GIS."
                    )
                    resolution = self.tr(
                        "Check the username and password or choose another saved user."
                    )

                return self._failure(
                    self.tr("The root resource is not readable."),
                    issue=ConnectionIssue(
                        source=ConnectionIssueSource.CLIENT,
                        details=details,
                        resolution=resolution,
                        technical_details=error.detail,
                    ),
                )

            return self._failure(
                self.tr("The root resource is not readable."),
                issue=self._server_issue(
                    self.tr("The server denied access to the root resource."),
                    resolution,
                    technical_details=error.detail,
                ),
            )
        except NgConnectError as error:
            self._raise_if_canceled(feedback, error)
            if not self._is_network_error(error):
                return self._failure(
                    self.tr("Unable to read the root resource."),
                    issue=self._client_issue(
                        self.tr(
                            "Connection verification failed unexpectedly."
                        ),
                        self.tr(
                            "Check the Web GIS URL and run the verification again."
                        ),
                        technical_details=str(error),
                    ),
                )

            return self._failure(
                self.tr("Unable to read the root resource."),
                issue=self._network_issue(error, resolution),
            )

        response_json = self._response_to_json(
            response,
            self.tr(
                "Ask the administrator to inspect the root resource response."
            ),
        )
        if isinstance(response_json, ConnectionCheckResult):
            return response_json

        if not isinstance(response_json, dict):
            return self._failure(
                self.tr(
                    "The root resource response has an unexpected format."
                ),
                issue=self._server_issue(
                    self.tr("The root resource payload is not an object."),
                    self.tr(
                        "Ask the administrator to inspect the root resource response."
                    ),
                ),
            )

        return self._success(
            self.tr("The root resource is readable."),
            payload=response_json,
        )
