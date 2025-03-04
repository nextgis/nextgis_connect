from copy import deepcopy
from typing import Optional, Union

from qgis.core import QgsTask

from nextgis_connect.exceptions import NgConnectError, NgConnectException
from nextgis_connect.logging import logger
from nextgis_connect.settings import NgConnectSettings


class NgConnectTask(QgsTask):
    __error: Optional[NgConnectException]

    def __init__(
        self, flags: Union[QgsTask.Flags, QgsTask.Flag, None] = None
    ) -> None:
        if flags is None:
            flags = QgsTask.Flags()
        super().__init__(flags=flags)
        self.__error = None

    @property
    def error(self) -> Optional[NgConnectException]:
        return self._error

    @property
    def _error(self) -> Optional[NgConnectException]:
        return self.__error

    @_error.setter
    def _error(self, error: Exception) -> None:
        if isinstance(error, NgConnectException):
            self.__error = deepcopy(error)
        else:
            self.__error = NgConnectError()
            self.__error.__cause__ = deepcopy(error)

    def run(self) -> bool:
        if NgConnectSettings().is_developer_mode:
            try:
                import debugpy  # noqa: T100
            except ImportError:
                logger.warning(
                    "To support threads debugging you need to install debugpy"
                )
            else:
                if debugpy.is_client_connected():
                    debugpy.debug_this_thread()

        if self._error is not None:
            return False

        return True
