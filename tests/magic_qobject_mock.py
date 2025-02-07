from typing import Any
from unittest.mock import MagicMock

from qgis.PyQt.QtCore import QObject


class MagicQObjectMock(QObject):
    _magic_mock: MagicMock

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._magic_mock = MagicMock()

    def __getattr__(self, name: str) -> Any:
        if hasattr(QObject, name):
            return getattr(super(), name)
        return getattr(self._magic_mock, name)
