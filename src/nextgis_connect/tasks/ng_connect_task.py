from typing import Optional, Union

from qgis.core import QgsTask

from nextgis_connect.exceptions import NgConnectError


class NgConnectTask(QgsTask):
    _error: Optional[NgConnectError]

    def __init__(self, flags: Union[QgsTask.Flags, QgsTask.Flag]) -> None:
        super().__init__(flags=flags)
        self._error = None

    @property
    def error(self) -> Optional[NgConnectError]:
        return self._error

    def run(self) -> bool:
        return True
