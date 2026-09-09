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
)
from nextgis_connect.platform.qgis.errors import NgConnectError, NgwError

from .base import BaseConnectionCheck, UpdateReporter

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )

PYRAMID_SETTINGS_SUB_URL = "/api/component/pyramid/settings?component=pyramid"


class DownloadCheck(BaseConnectionCheck):
    check_id = ConnectionCheckId.DOWNLOAD

    @property
    def title(self) -> str:
        return self.tr("Download")

    @property
    def initial_description(self) -> str:
        return self.tr("Checking the Lunkwill server setting.")

    def run_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult:
        resolution = self.tr(
            "Ask the administrator to inspect the Lunkwill setting in the server response."
        )
        try:
            response = ngw_connection.get(
                PYRAMID_SETTINGS_SUB_URL,
                feedback=feedback,
            )
        except NgwError as error:
            self._raise_if_canceled(feedback, error)
            if self._is_network_error(error):
                return self._failure(
                    self.tr("Unable to read the Lunkwill server setting."),
                    issue=self._network_issue(
                        error,
                        self.tr(
                            "Check the network settings and retry the checks."
                        ),
                    ),
                )

            return self._failure(
                self.tr("The server settings endpoint returned an error."),
                issue=self._server_issue(
                    self.tr(
                        "The server did not return the expected Lunkwill setting."
                    ),
                    resolution,
                    technical_details=error.detail,
                ),
            )
        except NgConnectError as error:
            self._raise_if_canceled(feedback, error)
            return self._failure(
                self.tr("Unable to read the Lunkwill server setting."),
                issue=self._network_issue(
                    error,
                    self.tr(
                        "Check the network settings and retry the checks."
                    ),
                ),
            )

        response_json = self._response_to_json(response, resolution)
        if isinstance(response_json, ConnectionCheckResult):
            return response_json

        if not isinstance(response_json, dict):
            return self._failure(
                self.tr(
                    "The server settings response has an unexpected format."
                ),
                issue=self._server_issue(
                    self.tr("The server settings payload is not an object."),
                    resolution,
                ),
            )

        enabled_value = response_json.get("lunkwill.enabled")
        if enabled_value is None:
            lunkwill_section = response_json.get("lunkwill")
            if isinstance(lunkwill_section, dict):
                enabled_value = lunkwill_section.get("enabled")

        if enabled_value is True:
            return self._success(
                self.tr("Lunkwill is enabled in the server settings."),
            )

        return self._warning(
            self.tr("Lunkwill is disabled or missing in the server settings."),
            issue=self._server_issue(
                self.tr(
                    "Long-running server operations may be processed synchronously."
                ),
                self.tr(
                    "Ask the administrator to enable Lunkwill if long-running server operations are expected."
                ),
            ),
        )
