import logging
from types import MethodType
from typing import List, Protocol

from qgis.core import Qgis, QgsApplication

from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings import NgConnectSettings


class QgisLoggerProtocol(Protocol):
    handlers: List[logging.Handler]

    def setLevel(self, level: int) -> None: ...  # noqa: N802
    def addHandler(self, handler: logging.Handler) -> None: ...  # noqa: N802
    def removeHandler(self, handler: logging.Handler) -> None: ...  # noqa: N802

    def debug(self, message: str, *args, **kwargs) -> None: ...
    def info(self, message: str, *args, **kwargs) -> None: ...
    def success(self, message: str, *args, **kwargs) -> None: ...
    def warning(self, message: str, *args, **kwargs) -> None: ...
    def error(self, message: str, *args, **kwargs) -> None: ...
    def exception(self, message: str, *args, **kwargs) -> None: ...
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
            message = f"<i>[DEBUG]&nbsp;&nbsp;&nbsp;&nbsp;{message}</i>"
        assert message_log is not None
        message_log.logMessage(message, record.name, level)

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


def init_logger() -> QgisLoggerProtocol:
    logger: QgisLoggerProtocol = logging.getLogger(
        NgConnectInterface.PLUGIN_NAME
    )  # type: ignore
    logger.success = MethodType(_log_success, logger)

    handler = QgisLoggerHandler()
    logger.addHandler(handler)

    is_debug_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_enabled else logging.INFO)
    if is_debug_enabled:
        logger.warning("Debug messages are enabled")

    return logger


def update_level() -> None:
    is_debug_enabled = NgConnectSettings().is_debug_enabled
    logger.setLevel(logging.DEBUG if is_debug_enabled else logging.INFO)


def unload_logger():
    handlers = logger.handlers.copy()
    for handler in handlers:
        logger.removeHandler(handler)
        handler.close()

    del logger.success

    logger.setLevel(logging.NOTSET)


logger = init_logger()
