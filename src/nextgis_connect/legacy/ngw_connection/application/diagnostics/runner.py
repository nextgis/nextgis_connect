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

from typing import List, Optional, Tuple, cast

from qgis.core import QgsApplication, QgsFeedback
from qgis.PyQt.QtCore import QObject, pyqtSignal

from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckResult,
    ConnectionCheckState,
    ConnectionCheckUpdate,
    ConnectionDiagnosticContext,
    ConnectionDiagnosticsReport,
    ConnectionDiagnosticsSummary,
    ConnectionIssue,
    ConnectionIssueSource,
    ConnectionVerificationResult,
    CurrentUserInfo,
)
from nextgis_connect.legacy.ngw_connection.domain.parsers import (
    NgwServerTitleParser,
    suggested_connection_name,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.tasks import NgConnectTask
from nextgis_connect.plugin.plugin_interface import NgConnectInterface

from .checks import build_connection_checks
from .checks.base import CheckCancelledError
from .checks.current_user import CurrentUserCheck
from .checks.root_resource import RootResourceAccessCheck
from .logs import DiagnosticLogCapture


class ConnectionDiagnosticsTaskSignals(QObject):
    check_updated = pyqtSignal(object)
    finished = pyqtSignal(object)


class ConnectionVerificationTaskSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    finished = pyqtSignal()


class NgwConnectionDiagnosticsTask(NgConnectTask):
    _connection: NgwConnection
    _checks: List
    _feedback: QgsFeedback
    _report: Optional[ConnectionDiagnosticsReport]
    signals: ConnectionDiagnosticsTaskSignals

    def __init__(self, connection: NgwConnection) -> None:
        super().__init__()
        self._connection = connection
        self._checks = build_connection_checks(connection)
        self._feedback = QgsFeedback()
        self._report = None
        self.signals = ConnectionDiagnosticsTaskSignals()
        # fmt: off
        self.setDescription(
            QgsApplication.translate(
                "NgwConnectionDiagnosticsTask",
                'Web GIS connection check for "{name}"'
            ).format(name=connection.name)
        )
        # fmt: on

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    def initial_updates(self) -> Tuple[ConnectionCheckUpdate, ...]:
        updates = []
        for check in self._checks:
            updates.append(
                ConnectionCheckUpdate(
                    check_id=check.check_id,
                    title=check.title,
                    state=ConnectionCheckState.NOT_STARTED,
                    description="",
                )
            )

        return tuple(updates)

    def run(self) -> bool:
        if not super().run():
            return False

        context = ConnectionDiagnosticContext(self._connection)
        ngw_connection = QgsNgwConnection(self._connection, log_network=True)
        with DiagnosticLogCapture() as log_capture:
            try:
                self._log_context(context)
                return self._run_checks(
                    context,
                    ngw_connection,
                    log_capture,
                )

            except CheckCancelledError:
                self._report = self._build_report(
                    context,
                    log_capture.text,
                    is_canceled=True,
                )
                return False

            except Exception as error:
                logger.exception("Connection diagnostics failed")
                self._error = error
                self._report = self._build_report(
                    context,
                    log_capture.text,
                    error=ConnectionIssue(
                        ConnectionIssueSource.CLIENT,
                        self.tr("Connection diagnostics failed unexpectedly."),
                        self.tr(
                            "Run the diagnostics again. If the problem persists, update the plugin and inspect the logs."
                        ),
                        technical_details=str(error),
                    ),
                )
                return False

    def finished(self, result: bool) -> None:
        report = self._report
        if report is None:
            report = ConnectionDiagnosticsReport(
                summary=ConnectionDiagnosticsSummary(tuple()),
                logs="",
                is_canceled=self.isCanceled(),
            )

        self.signals.finished.emit(report)

    def _build_summary(
        self,
        context: ConnectionDiagnosticContext,
    ) -> ConnectionDiagnosticsSummary:
        ordered_results = tuple(
            context.results.get(check.check_id)
            or self._not_completed_result(check)
            for check in self._checks
        )
        return ConnectionDiagnosticsSummary(ordered_results)

    def _build_report(
        self,
        context: ConnectionDiagnosticContext,
        logs: str,
        *,
        is_canceled: bool = False,
        error: Optional[ConnectionIssue] = None,
    ) -> ConnectionDiagnosticsReport:
        return ConnectionDiagnosticsReport(
            summary=self._build_summary(context),
            logs=logs,
            is_canceled=is_canceled,
            error=error,
        )

    def _run_checks(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: QgsNgwConnection,
        log_capture: DiagnosticLogCapture,
    ) -> bool:
        logger.debug(
            f"Starting Web GIS checks for '{self._connection.name}' at {self._connection.url} using auth method '{self._connection.method or 'guest'}'."
        )
        total_checks = len(self._checks)
        for index, check in enumerate(self._checks, start=1):
            self._raise_if_canceled()
            result = self._run_single_check(context, ngw_connection, check)
            if result is None:
                continue

            context.store_result(result)
            self._emit_result_update(result)
            self.setProgress(index * 100 / total_checks)

        self._report = self._build_report(context, log_capture.text)
        return True

    def _run_single_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: QgsNgwConnection,
        check,
    ) -> Optional[ConnectionCheckResult]:
        if not self._dependencies_ready(context, check):
            return self._skipped_result(check)

        if self._has_failed_dependencies(context, check):
            return self._skipped_result(check)

        return check.execute(
            context,
            ngw_connection,
            self._feedback,
            self.signals.check_updated.emit,
        )

    def _dependencies_ready(self, context, check) -> bool:
        return all(
            context.result(dependency_id) is not None
            for dependency_id in check.dependencies
        )

    def _has_failed_dependencies(self, context, check) -> bool:
        return any(
            result is not None and result.state == ConnectionCheckState.FAILURE
            for result in (
                context.result(dependency_id)
                for dependency_id in check.dependencies
            )
        )

    def _skipped_result(self, check) -> ConnectionCheckResult:
        return ConnectionCheckResult(
            check_id=check.check_id,
            title=check.title,
            state=ConnectionCheckState.FAILURE,
            description=self.tr(
                "The check was skipped because a prerequisite check failed."
            ),
            issue=ConnectionIssue(
                ConnectionIssueSource.CLIENT,
                self.tr(
                    "A prerequisite check failed before this check could start."
                ),
                self.tr(
                    "Resolve the earlier failures and rerun the diagnostics."
                ),
            ),
            is_blocking=check.is_blocking,
        )

    def _not_completed_result(self, check) -> ConnectionCheckResult:
        return ConnectionCheckResult(
            check_id=check.check_id,
            title=check.title,
            state=ConnectionCheckState.FAILURE,
            description=self.tr("The check did not finish."),
            issue=ConnectionIssue(
                ConnectionIssueSource.CLIENT,
                self.tr("The check did not report a final state."),
                self.tr(
                    "Rerun the diagnostics. If the problem persists, inspect the logs."
                ),
            ),
            is_blocking=check.is_blocking,
        )

    def _emit_result_update(self, result: ConnectionCheckResult) -> None:
        logger.debug(
            f"Check '{result.title}' finished with {result.state.name.lower()}: {result.description or '-'}"
        )
        self.signals.check_updated.emit(
            ConnectionCheckUpdate(
                check_id=result.check_id,
                title=result.title,
                state=result.state,
                description=result.description,
                issue=result.issue,
            )
        )

    def _raise_if_canceled(self) -> None:
        if self.isCanceled() or self._feedback.isCanceled():
            raise CheckCancelledError

    def _log_context(self, context: ConnectionDiagnosticContext) -> None:
        logger.debug(
            f"Diagnostics context: connection_id={context.connection.id}, name='{context.connection.name}', url={context.connection.url}, auth_config_id={context.connection.auth_config_id or '-'}"
        )
        logger.debug(f"\n{context.proxy_settings.to_debug_message()}")


class NgwConnectionVerificationTask(NgConnectTask):
    _connection: NgwConnection
    _fetch_title: bool
    _feedback: QgsFeedback
    _result: Optional[ConnectionVerificationResult]
    _issue: Optional[ConnectionIssue]
    signals: ConnectionVerificationTaskSignals

    def __init__(
        self, connection: NgwConnection, *, fetch_title: bool
    ) -> None:
        super().__init__()
        self._connection = connection
        self._fetch_title = fetch_title
        self._feedback = QgsFeedback()
        self._result = None
        self._issue = None
        self.signals = ConnectionVerificationTaskSignals()
        # fmt: off
        self.setDescription(
            QgsApplication.translate(
                "NgwConnectionVerificationTask",
                'Web GIS connection verification for "{name}"'
            ).format(name=connection.name)
        )
        # fmt: on

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    def run(self) -> bool:
        if not super().run():
            return False

        context = ConnectionDiagnosticContext(self._connection)
        ngw_connection = QgsNgwConnection(self._connection)
        try:
            if not self._run_required_check(
                context,
                ngw_connection,
                RootResourceAccessCheck(self._connection),
            ):
                return False

            current_user_result = self._run_current_user_check(
                context,
                ngw_connection,
            )
            if current_user_result is None:
                return False

            current_user_info = cast(
                CurrentUserInfo, current_user_result.payload
            )
            resolved_name = self._resolve_connection_name(
                ngw_connection,
                self._feedback,
            )

            self._result = ConnectionVerificationResult(
                resolved_name=resolved_name,
                current_user=current_user_info,
            )
            return True

        except CheckCancelledError:
            return False

        except Exception as error:
            logger.exception("Connection verification failed")
            self._error = error
            self._issue = ConnectionIssue(
                ConnectionIssueSource.CLIENT,
                self.tr("Connection verification failed unexpectedly."),
                self.tr(
                    "Run the verification again. If the problem persists, inspect the logs."
                ),
                technical_details=str(error),
            )
            return False

    def finished(self, result: bool) -> None:
        if result and self._result is not None:
            self.signals.succeeded.emit(self._result)
        else:
            self.signals.failed.emit(self._issue)

        self.signals.finished.emit()

    def _run_required_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: QgsNgwConnection,
        check,
    ) -> bool:
        result = check.execute(
            context,
            ngw_connection,
            self._feedback,
            lambda update: None,
        )
        if result.state != ConnectionCheckState.SUCCESS:
            self._issue = result.issue
            return False

        context.store_result(result)
        return True

    def _run_current_user_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: QgsNgwConnection,
    ) -> Optional[ConnectionCheckResult]:
        check = CurrentUserCheck(self._connection)
        result = check.execute(
            context,
            ngw_connection,
            self._feedback,
            lambda update: None,
        )
        if result.state != ConnectionCheckState.SUCCESS:
            self._issue = result.issue
            return None

        context.store_result(result)
        return result

    def _resolve_connection_name(
        self,
        ngw_connection: QgsNgwConnection,
        feedback: QgsFeedback,
    ) -> str:
        fallback_name = suggested_connection_name(self._connection.url)
        if not self._fetch_title:
            return fallback_name

        return self._resolve_title(ngw_connection, feedback)

    def _resolve_title(
        self,
        ngw_connection: QgsNgwConnection,
        feedback: QgsFeedback,
    ) -> str:
        fallback_name = suggested_connection_name(self._connection.url)
        try:
            response = ngw_connection.get("/resource/0", feedback=feedback)
        except Exception:
            return fallback_name

        if feedback.isCanceled():
            raise CheckCancelledError

        try:
            html = bytes(response).decode("utf-8", errors="replace")
        except Exception:
            if not hasattr(response, "data"):
                return fallback_name

            try:
                html = response.data().decode("utf-8", errors="replace")
            except Exception:
                return fallback_name

        parsed_title = NgwServerTitleParser.extract_title(html)
        return parsed_title or fallback_name


class NgwConnectionDiagnostics(QObject):
    check_updated = pyqtSignal(object)
    finished = pyqtSignal(object)

    _connection: NgwConnection
    _task: Optional[NgwConnectionDiagnosticsTask]

    def __init__(
        self,
        connection: NgwConnection,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._connection = connection
        self._task = None

    def initial_updates(self) -> Tuple[ConnectionCheckUpdate, ...]:
        return NgwConnectionDiagnosticsTask(self._connection).initial_updates()

    def start(self) -> None:
        if self._task is not None:
            return

        self._task = NgwConnectionDiagnosticsTask(self._connection)
        self._task.signals.check_updated.connect(self.check_updated.emit)
        self._task.signals.finished.connect(self._handle_finished)
        NgConnectInterface.instance().task_manager.addTask(self._task)

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _handle_finished(self, report: ConnectionDiagnosticsReport) -> None:
        self._task = None
        self.finished.emit(report)


class NgwConnectionVerifier(QObject):
    started = pyqtSignal()
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    finished = pyqtSignal()

    _connection: NgwConnection
    _fetch_title: bool
    _task: Optional[NgwConnectionVerificationTask]

    def __init__(
        self,
        connection: NgwConnection,
        *,
        fetch_title: bool,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._connection = connection
        self._fetch_title = fetch_title
        self._task = None

    def start(self) -> None:
        if self._task is not None:
            return

        self._task = NgwConnectionVerificationTask(
            self._connection,
            fetch_title=self._fetch_title,
        )
        self._task.signals.succeeded.connect(self.succeeded.emit)
        self._task.signals.failed.connect(self.failed.emit)
        self._task.signals.finished.connect(self._handle_finished)
        self.started.emit()
        NgConnectInterface.instance().task_manager.addTask(self._task)

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _handle_finished(self) -> None:
        self._task = None
        self.finished.emit()
