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

from types import SimpleNamespace


class _MessageLog:
    def __init__(self) -> None:
        self.messages = []

    def logMessage(self, message, tag, level) -> None:
        self.messages.append((message, tag, level))


class _Application:
    message_log = _MessageLog()

    @classmethod
    def messageLog(cls):
        return cls.message_log


def test_diagnostic_capture_keeps_unescaped_legacy_qgis_log(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    from nextgis_connect.legacy.ngw_connection.application.diagnostics.logs import (
        DiagnosticLogCapture,
    )
    from nextgis_connect.platform import logging as logging_module

    message = "{'display_name': 'Основная группа ресурсов'}"
    qgis = logging_module.Qgis
    monkeypatch.setattr(logging_module, "QgsApplication", _Application)
    monkeypatch.setattr(
        logging_module,
        "Qgis",
        SimpleNamespace(
            MessageLevel=qgis.MessageLevel,
            versionInt=lambda: 34201,
        ),
    )

    with DiagnosticLogCapture() as log_capture:
        logging_module.logger.debug(
            message,
        )

    logged_message, _, _ = _Application.message_log.messages[-1]
    assert "&#x27;" in logged_message
    assert log_capture.text.endswith(message)
