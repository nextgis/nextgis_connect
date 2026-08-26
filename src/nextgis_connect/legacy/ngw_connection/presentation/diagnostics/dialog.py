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

from typing import Optional

from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw_connection.application.diagnostics.runner import (
    NgwConnectionDiagnostics,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionDiagnosticsReport,
)
from nextgis_connect.legacy.ngw_connection.presentation.diagnostics.ui import (
    NgwConnectionDiagnosticsWidget,
)
from nextgis_connect.platform.clipboard import Clipboard


class NgwConnectionDiagnosticsDialog(QDialog):
    _connection: NgwConnection
    _controller: NgwConnectionDiagnostics
    _widget: NgwConnectionDiagnosticsWidget
    _progress_bar: QProgressBar
    _start_button: QPushButton
    _copy_logs_button: QPushButton
    _is_running: bool
    _logs: str
    _is_finished: bool

    def __init__(
        self,
        connection,
        parent: Optional[QWidget] = None,
        *,
        start_immediately: bool = False,
    ) -> None:
        super().__init__(parent)
        self._connection = connection
        self.setWindowTitle(self.tr("Web GIS diagnostics"))
        self.resize(760, 420)

        self._controller = NgwConnectionDiagnostics(connection, self)
        self._widget = NgwConnectionDiagnosticsWidget(self)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(0)
        self._progress_bar.hide()
        self._start_button = QPushButton(self.tr("Run"), self)
        self._start_button.clicked.connect(self._start)
        self._copy_logs_button = QPushButton(self.tr("Copy logs"), self)
        self._copy_logs_button.setEnabled(False)
        self._copy_logs_button.clicked.connect(self._copy_logs)
        self._close_button = QPushButton(self.tr("Close"), self)
        self._close_button.clicked.connect(self.reject)
        self._is_running = False
        self._logs = ""
        self._is_finished = False

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self._copy_logs_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self._start_button)
        button_layout.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._widget)
        layout.addWidget(self._progress_bar)
        layout.addLayout(button_layout)

        self._controller.check_updated.connect(self._widget.apply_update)
        self._controller.finished.connect(self._handle_finished)

        self._widget.reset()
        self._widget.set_connection_title(connection.name)
        for update in self._controller.initial_updates():
            self._widget.apply_update(update)

        if start_immediately:
            self._start()

    def reject(self) -> None:
        if self._is_running:
            self._controller.cancel()
        super().reject()

    def _start(self) -> None:
        if self._is_running:
            return

        self._is_finished = False
        self._is_running = True
        self._logs = ""
        self._widget.reset()
        self._widget.set_connection_title(self._connection.name)
        for update in self._controller.initial_updates():
            self._widget.apply_update(update)
        self._widget.show_running()
        self._progress_bar.show()
        self._start_button.setEnabled(False)
        self._copy_logs_button.setEnabled(False)
        self._controller.start()

    def _handle_finished(self, report: ConnectionDiagnosticsReport) -> None:
        self._is_running = False
        self._is_finished = True
        self._logs = report.logs
        self._progress_bar.hide()
        self._start_button.setEnabled(True)
        self._copy_logs_button.setEnabled(True)

        if report.is_canceled:
            self._widget.set_summary_text(
                self.tr("Web GIS checks were canceled.")
            )
            return

        if len(report.summary.results) > 0:
            self._widget.apply_summary(report.summary)

        if report.error is not None:
            self._widget.set_summary_text(
                self.tr("Web GIS checks finished with an unexpected error.")
            )

    def _copy_logs(self) -> None:
        logs = self._logs or self.tr("No logs were captured.")

        Clipboard().set_data(
            "text/plain",
            logs.encode("utf-8"),
            logs,
        )
