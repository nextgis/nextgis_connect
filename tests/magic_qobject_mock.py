from unittest.mock import MagicMock

from qgis.PyQt.QtCore import QObject


class MagicQObjectMock(QObject, MagicMock):
    def __init__(self, *args, **kwargs):
        super(QObject, self).__init__()
        super(MagicMock, self).__init__(*args, **kwargs)
