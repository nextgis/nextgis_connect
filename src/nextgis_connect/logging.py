import html
import logging
import re
import sys
from pprint import pformat
from types import MethodType
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Union, cast

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtWidgets import QPlainTextEdit, QTabWidget
from qgis.utils import iface

from nextgis_connect.compat import QGIS_3_42_2
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings import NgConnectSettings

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    Protocol = object

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    assert isinstance(iface, QgisInterface)


class QgisLoggerProtocol(Protocol):
    def setLevel(self, level: int) -> None: ...

    def debug(self, message: str, *args, **kwargs) -> None: ...
    def info(self, message: str, *args, **kwargs) -> None: ...
    def success(self, message: str, *args, **kwargs) -> None: ...
    def warning(self, message: str, *args, **kwargs) -> None: ...
    def error(self, message: str, *args, **kwargs) -> None: ...
    def exception(
        self,
        message: str,
        *args,
        exc_info: Optional[Exception] = None,
        **kwargs,
    ) -> None: ...
    def critical(self, message: str, *args, **kwargs) -> None: ...
    def fatal(self, message: str, *args, **kwargs) -> None: ...


SUCCESS_LEVEL = logging.INFO + 1
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def _log_success(self, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


class QgisLoggerHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        level = self._map_logging_level_to_qgis(record.levelno)
        message = self.format(record)
        message_log = QgsApplication.messageLog()
        if record.levelno == logging.DEBUG:
            message = f"[DEBUG]    {message}"
        assert message_log is not None

        message_log.logMessage(self._process_html(message), record.name, level)

    def _map_logging_level_to_qgis(self, level):
        if level >= logging.ERROR:
            return Qgis.MessageLevel.Critical
        if level >= logging.WARNING:
            return Qgis.MessageLevel.Warning
        if level == SUCCESS_LEVEL:
            return Qgis.MessageLevel.Success
        if level >= logging.DEBUG:
            return Qgis.MessageLevel.Info

        return Qgis.MessageLevel.NoLevel

    def _process_html(self, message: str) -> str:
        message = message.replace(" ", "\u00a0")

        if Qgis.versionInt() < QGIS_3_42_2:
            return message

        # https://github.com/qgis/QGIS/issues/45834

        for tag in {"i", "b"}:
            message = re.sub(
                rf"<{tag}\b[^>]*?>", "", message, flags=re.IGNORECASE
            )
            message = re.sub(rf"</{tag}>", "", message, flags=re.IGNORECASE)

        return message


def escape_html(message: str) -> str:
    # https://github.com/qgis/QGIS/issues/45834
    return html.escape(message) if Qgis.versionInt() < QGIS_3_42_2 else message


def format_container_data(data: Union[List, Set, Dict]) -> str:
    return pformat(data)


def init_logger() -> QgisLoggerProtocol:
    logger = logging.getLogger(NgConnectInterface.PLUGIN_NAME)
    logger.propagate = False

    logger.success = MethodType(_log_success, logger)  # type: ignore

    handler = QgisLoggerHandler()
    logger.addHandler(handler)

    is_debug_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_enabled else logging.INFO)
    if is_debug_enabled:
        logger.warning("Debug messages are enabled")

    return cast(QgisLoggerProtocol, logger)


def update_level() -> None:
    is_debug_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_enabled else logging.INFO)


def unload_logger():
    logger = logging.getLogger(NgConnectInterface.PLUGIN_NAME)

    handlers = logger.handlers.copy()
    for handler in handlers:
        logger.removeHandler(handler)
        handler.close()

    logger.propagate = True

    if hasattr(logger, "success"):
        del logger.success  # type: ignore

    logger.setLevel(logging.NOTSET)


def extract_logs() -> str:
    """
    Extract log messages from QGIS log viewer for the plugin tab.
    :returns: Log messages as a single string.
    :rtype: str
    """
    log_viewer = iface.mainWindow().logViewer()
    tab_widget: QTabWidget = log_viewer.findChild(QTabWidget)
    assert tab_widget is not None

    text_edit: Optional[QPlainTextEdit] = None
    for index in range(tab_widget.count()):
        if tab_widget.tabText(index) == NgConnectInterface.PLUGIN_NAME:
            text_edit = tab_widget.widget(index)
            break

    if text_edit is None:
        return ""

    return text_edit.toPlainText()


logger = init_logger()
