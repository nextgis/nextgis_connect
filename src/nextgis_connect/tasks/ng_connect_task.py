from typing import Optional, Union

from qgis.core import QgsTask

from nextgis_connect.exceptions import NgConnectError
from nextgis_connect.settings import NgConnectSettings


class NgConnectTask(QgsTask):
    _error: Optional[NgConnectError]

    def __init__(self, flags: Union[QgsTask.Flags, QgsTask.Flag]) -> None:
        super().__init__(flags=flags)
        self._error = None

    @property
    def error(self) -> Optional[NgConnectError]:
        return self._error

    def run(self) -> bool:
        if NgConnectSettings().is_developer_mode:
            import debugpy  # noqa: T100

            if debugpy.is_client_connected():
                debugpy.debug_this_thread()

        if self._error is not None:
            return False

        return True
