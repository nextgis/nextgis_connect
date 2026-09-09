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

import html
import logging
from pprint import pformat
from typing import Dict, List, Optional, Set, Union, cast

import qgis.utils
from qgis.core import Qgis, QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtWidgets import QPlainTextEdit, QTabWidget

from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.qgis.compat import QGIS_3_42_2
from nextgis_connect.shared.constants import PLUGIN_NAME

SUCCESS_LEVEL = logging.INFO + 1
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def _iface() -> QgisInterface:
    iface = qgis.utils.iface
    assert isinstance(iface, QgisInterface)
    return iface


def map_logging_level_to_qgis(level: int) -> Qgis.MessageLevel:
    """Map a Python logging level to a QGIS message level.

    :param level: Python logging level.
    :return: Matching QGIS message level.
    """
    if level >= logging.ERROR:
        return Qgis.MessageLevel.Critical
    if level >= logging.WARNING:
        return Qgis.MessageLevel.Warning
    if level == SUCCESS_LEVEL:
        return Qgis.MessageLevel.Success
    if level >= logging.DEBUG:
        return Qgis.MessageLevel.Info

    return Qgis.MessageLevel.NoLevel


def map_qgis_level_to_logging(level: Qgis.MessageLevel) -> int:
    """Map a QGIS message level to a Python logging level.

    :param level: QGIS message level.
    :return: Matching Python logging level.
    """
    if level == Qgis.MessageLevel.Critical:
        return logging.ERROR
    if level == Qgis.MessageLevel.Warning:
        return logging.WARNING
    if level == Qgis.MessageLevel.Success:
        return SUCCESS_LEVEL
    if level == Qgis.MessageLevel.Info:
        return logging.INFO

    return logging.NOTSET


class QgisLogger(logging.Logger):
    """Integrate Python logging with QGIS.

    Route messages through the standard logging API while supporting
    QGIS message levels and the plugin-specific success level.
    """

    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        """Initialize the logger.

        :param name: Logger name.
        :param level: Initial logging level.
        """
        super().__init__(name, level)

    def log(
        self,
        level: Union[int, Qgis.MessageLevel],
        msg: str,
        *args,
        **kwargs,
    ) -> None:
        """Log a message with a Python or QGIS severity level.

        :param level: Python logging level or QGIS message level.
        :param msg: Log message format string.
        :param args: Positional formatting arguments.
        :param kwargs: Keyword options passed to the base logger.
        """
        if isinstance(level, Qgis.MessageLevel):
            level = map_qgis_level_to_logging(level)

        super().log(level, msg, *args, **kwargs)

    def success(self, message: str, *args, **kwargs) -> None:
        """Log a message with the success level.

        :param message: Log message format string.
        :param args: Positional formatting arguments.
        :param kwargs: Keyword options passed to the base logger.
        """
        if self.isEnabledFor(SUCCESS_LEVEL):
            self._log(SUCCESS_LEVEL, message, args, **kwargs)


class QgisLoggerHandler(logging.Handler):
    """Send logging records to the QGIS message log.

    Convert Python log records into QGIS message log entries using the
    plugin logger name and message-level mapping.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the QGIS message log.

        :param record: Log record to emit.
        """
        level = map_logging_level_to_qgis(record.levelno)
        message = self.format(record)
        message_log = QgsApplication.messageLog()
        if record.levelno == logging.DEBUG:
            message = f"[DEBUG]    {message}"
        assert message_log is not None

        message_log.logMessage(self._process_html(message), record.name, level)

    def _process_html(self, message: str) -> str:
        """Process a message for QGIS log HTML handling.

        :param message: Log message.
        :return: Processed log message.
        """
        message = message.replace(" ", "\u00a0")

        if Qgis.versionInt() < QGIS_3_42_2:
            # https://github.com/qgis/QGIS/issues/45834
            return html.escape(message)

        return message


def load_logger() -> QgisLogger:
    """Create and configure the plugin logger.

    :return: Configured plugin logger instance.
    """
    original_logger_class = logging.getLoggerClass()
    logging.setLoggerClass(QgisLogger)
    logger = logging.getLogger(PLUGIN_NAME)
    logging.setLoggerClass(original_logger_class)

    logger.propagate = False

    handler = QgisLoggerHandler()
    logger.addHandler(handler)

    is_debug_logs_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_logs_enabled else logging.INFO)
    if is_debug_logs_enabled:
        logger.warning("Debug messages are enabled")

    return cast(QgisLogger, logger)


def update_logging_level() -> None:
    """Update the plugin logger level from settings."""
    is_debug_logs_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_logs_enabled else logging.INFO)


def unload_logger() -> None:
    """Remove plugin logger handlers and reset propagation."""
    logger = logging.getLogger(PLUGIN_NAME)

    handlers = logger.handlers.copy()
    for handler in handlers:
        logger.removeHandler(handler)
        handler.close()

    logger.propagate = True

    logger.setLevel(logging.NOTSET)


def format_container_data(data: Union[List, Set, Dict]) -> str:
    """Format container data for logging.

    :param data: Container data to format.
    :return: Formatted string representation.
    """
    return pformat(data)


def extract_plugin_logs() -> str:
    """Extract messages from the plugin log tab.

    :return: Plugin log messages as a single string.
    """
    iface = _iface()
    log_viewer = iface.mainWindow().logViewer()
    tab_widget: QTabWidget = log_viewer.findChild(QTabWidget)
    assert tab_widget is not None

    text_edit: Optional[QPlainTextEdit] = None
    for index in range(tab_widget.count()):
        if tab_widget.tabText(index) == PLUGIN_NAME:
            text_edit = tab_widget.widget(index)
            break

    if text_edit is None:
        return ""

    return text_edit.toPlainText()


def open_plugin_logs() -> None:
    """Open the QGIS log viewer with the plugin tab selected."""
    iface = _iface()
    if Qgis.versionInt() >= 34400:
        iface.openMessageLog(PLUGIN_NAME)
    else:
        iface.openMessageLog()


logger = load_logger()
