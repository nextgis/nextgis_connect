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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

from qgis.core import QgsFeedback
from qgis.PyQt.QtCore import QByteArray, QCoreApplication

from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckId,
    ConnectionCheckResult,
    ConnectionCheckState,
    ConnectionCheckUpdate,
    ConnectionDiagnosticContext,
    ConnectionIssue,
    ConnectionIssueSource,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import ErrorCode, NgConnectException

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )


class CheckCancelledError(Exception):
    pass


UpdateReporter = Callable[[ConnectionCheckUpdate], None]


class BaseConnectionCheck(ABC):
    check_id: ConnectionCheckId
    dependencies: Tuple[ConnectionCheckId, ...] = tuple()
    is_blocking = False

    _connection: NgwConnection
    _context: ConnectionDiagnosticContext

    def __init__(self, connection: NgwConnection) -> None:
        self._connection = connection

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    def initial_description(self) -> str:
        return self.tr("The check is running.")

    def tr(self, text: str) -> str:
        return QCoreApplication.translate(type(self).__name__, text)

    def execute(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult:
        self._context = context
        self._ensure_not_canceled(feedback)
        self._report_update(
            ConnectionCheckState.STARTED,
            self.initial_description,
            report_update,
        )
        return self.run_check(
            context,
            ngw_connection,
            feedback,
            report_update,
        )

    @abstractmethod
    def run_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult: ...

    def _report_update(
        self,
        state: ConnectionCheckState,
        description: str,
        report_update: UpdateReporter,
        issue: Optional[ConnectionIssue] = None,
    ) -> None:
        logger.debug(
            f"Check '{self.title}' is now {state.name.lower()}: {description or '-'}"
        )
        if issue is not None:
            logger.debug(
                f"Issue for '{self.title}' ({issue.source.name.lower()}): {issue.details or '-'} Resolution: {issue.resolution or '-'}"
            )
        report_update(
            ConnectionCheckUpdate(
                check_id=self.check_id,
                title=self.title,
                state=state,
                description=description,
                issue=issue,
            )
        )

    def _result(
        self,
        state: ConnectionCheckState,
        description: str,
        *,
        issue: Optional[ConnectionIssue] = None,
        payload: Optional[Any] = None,
    ) -> ConnectionCheckResult:
        return ConnectionCheckResult(
            check_id=self.check_id,
            title=self.title,
            state=state,
            description=description,
            issue=issue,
            is_blocking=self.is_blocking,
            payload=payload,
        )

    def _success(
        self,
        description: str,
        *,
        payload: Optional[Any] = None,
    ) -> ConnectionCheckResult:
        return self._result(
            ConnectionCheckState.SUCCESS,
            description,
            payload=payload,
        )

    def _warning(
        self,
        description: str,
        *,
        issue: Optional[ConnectionIssue] = None,
        payload: Optional[Any] = None,
    ) -> ConnectionCheckResult:
        return self._result(
            ConnectionCheckState.WARNING,
            description,
            issue=issue,
            payload=payload,
        )

    def _failure(
        self,
        description: str,
        *,
        issue: Optional[ConnectionIssue] = None,
        payload: Optional[Any] = None,
    ) -> ConnectionCheckResult:
        return self._result(
            ConnectionCheckState.FAILURE,
            description,
            issue=issue,
            payload=payload,
        )

    def _ensure_not_canceled(self, feedback: QgsFeedback) -> None:
        if feedback.isCanceled():
            raise CheckCancelledError

    def _raise_if_canceled(
        self,
        feedback: QgsFeedback,
        error: Exception,
    ) -> None:
        if feedback.isCanceled():
            raise CheckCancelledError from error

    def _is_network_error(self, error: NgConnectException) -> bool:
        if error.is_network_problem:
            return True

        return error.code in (
            ErrorCode.NetworkError,
            ErrorCode.QgisTimeoutError,
            ErrorCode.SslHandshakeError,
        )

    def _is_ssl_error(self, error: NgConnectException) -> bool:
        return error.code == ErrorCode.SslHandshakeError

    def _network_issue(
        self,
        error: NgConnectException,
        resolution: str,
    ) -> ConnectionIssue:
        details = error.user_message or error.log_message
        if (
            error.is_network_problem
            and error.code != ErrorCode.QgisTimeoutError
        ):
            details = self.tr("Unable to reach the Web GIS.")
        if error.code == ErrorCode.QgisTimeoutError:
            details = self.tr(
                "The request timed out before the server responded."
            )

        if self._context.proxy_settings.enabled:
            resolution = self.tr(
                "{resolution} Also verify the QGIS proxy settings."
            ).format(resolution=resolution)

        return ConnectionIssue(
            ConnectionIssueSource.NETWORK,
            details,
            resolution,
            technical_details=error.detail,
        )

    def _server_issue(
        self,
        details: str,
        resolution: str,
        *,
        technical_details: Optional[str] = None,
    ) -> ConnectionIssue:
        return ConnectionIssue(
            ConnectionIssueSource.SERVER,
            details,
            resolution,
            technical_details=technical_details,
        )

    def _client_issue(
        self,
        details: str,
        resolution: str,
        *,
        technical_details: Optional[str] = None,
    ) -> ConnectionIssue:
        return ConnectionIssue(
            ConnectionIssueSource.CLIENT,
            details,
            resolution,
            technical_details=technical_details,
        )

    def _as_bytes(self, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value

        if isinstance(value, QByteArray):
            return value.data()

        message = self.tr("The response body is not binary data.")
        raise ValueError(message)

    def _response_to_json(
        self,
        response: Any,
        resolution: str,
    ) -> Optional[Any]:
        try:
            if isinstance(response, dict):
                return response

            message = self.tr("The response body is not JSON.")
            raise ValueError(message)
        except ValueError as error:
            return self._failure(
                self.tr("The server returned invalid JSON."),
                issue=self._server_issue(
                    self.tr("The response body is not valid JSON."),
                    resolution,
                    technical_details=str(error),
                ),
            )

    def _unexpected_response_issue(
        self,
        details: str,
        resolution: str,
    ) -> ConnectionIssue:
        return self._server_issue(details, resolution)
