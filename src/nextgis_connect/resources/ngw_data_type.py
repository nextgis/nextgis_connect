from enum import IntEnum

from qgis.core import QgsFields
from qgis.PyQt.QtGui import QIcon

from nextgis_connect.compat import FieldType


class NgwDataType(IntEnum):
    INTEGER = FieldType.Int
    BIGINT = FieldType.LongLong
    REAL = FieldType.Double
    STRING = FieldType.QString
    TIME = FieldType.QTime
    DATE = FieldType.QDate
    DATETIME = FieldType.QDateTime

    @property
    def icon(self) -> QIcon:
        return QgsFields.iconForFieldType(self.qt_value)

    @property
    def qt_value(self):
        return FieldType(int(self))

    @staticmethod
    def from_name(type_name: str):
        try:
            return NgwDataType[type_name]
        except KeyError:
            return NgwDataType.STRING

    @staticmethod
    def from_qt_value(qt_value: FieldType):
        return NgwDataType(int(qt_value))
