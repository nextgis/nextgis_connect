from unittest.mock import MagicMock

from qgis.PyQt.QtCore import QObject


class MagicQObjectMock(QObject, MagicMock):
    def __init__(self, *args, **kwargs):
        QObject.__init__(self)
        MagicMock.__init__(self, *args, **kwargs)

    def __getattr__(self, name):
        return super(MagicMock, self).__getattr__(name)
