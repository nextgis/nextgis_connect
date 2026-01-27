from qgis import core
from qgis.PyQt import QtCore

COMPAT_PYQT_VERSION = QtCore.PYQT_VERSION_STR.split(".")


class CompatQt:
    @classmethod
    def has_redirect_policy(cls):
        pyqt_version = (
            int(COMPAT_PYQT_VERSION[0]),
            int(COMPAT_PYQT_VERSION[1]),
        )
        return pyqt_version >= (5, 9)

    @classmethod
    def get_clean_python_value(cls, v):
        if v == core.NULL:
            return None
        if isinstance(v, QtCore.QDateTime):
            return v.toPyDateTime()
        if isinstance(v, QtCore.QDate):
            return v.toPyDate()
        if isinstance(v, QtCore.QTime):
            return v.toPyTime()
        return v
