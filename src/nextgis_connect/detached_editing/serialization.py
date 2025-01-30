from base64 import b64decode, b64encode
from typing import Any, Optional, Union

from qgis.core import QgsGeometry, QgsWkbTypes
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QVariant

from nextgis_connect.compat import GeometryType
from nextgis_connect.exceptions import NgConnectError


def _serialize_date_and_time(
    date_object: Union[QDateTime, QDate, QTime],
    is_versioning_enabled: bool = False,
) -> Any:
    if is_versioning_enabled:
        return date_object.toString(Qt.DateFormat.ISODate)

    date = None
    time = None
    if isinstance(date_object, QDateTime):
        date = date_object.date()
        time = date_object.time()
    elif isinstance(date_object, QDate):
        date = date_object
    elif isinstance(date_object, QTime):
        time = date_object

    result = {}
    if date is not None:
        result["year"] = date.year()
        result["month"] = date.month()
        result["day"] = date.day()

    if time is not None:
        result["hour"] = time.hour()
        result["minute"] = time.minute()
        result["second"] = time.second()

    return result


def serialize_value(value: Any, is_versioning_enabled: bool = False) -> Any:
    if isinstance(value, QVariant) and value.isNull():
        return None

    if isinstance(value, (QDate, QTime, QDateTime)):
        return _serialize_date_and_time(value)

    return value


def serialize_geometry(
    geometry: Optional[QgsGeometry], is_versioning_enabled: bool = False
) -> str:
    if geometry is None or geometry.isEmpty():
        return ""

    def as_wkt(geometry: QgsGeometry) -> str:
        wkt = geometry.asWkt()

        if not QgsWkbTypes.hasZ(geometry.wkbType()):
            return wkt

        geometry_type = geometry.type()
        if geometry_type == GeometryType.Point:
            replacement = ("tZ", "t Z")
        elif geometry_type == GeometryType.Line:
            replacement = ("gZ", "g Z")
        elif geometry_type == GeometryType.Polygon:
            replacement = ("nZ", "n Z")
        else:
            raise NgConnectError("Unknown geometry")

        return wkt.replace(*replacement)

    def as_wkb64(geometry: QgsGeometry) -> str:
        return b64encode(geometry.asWkb().data()).decode("ascii")

    return as_wkb64(geometry) if is_versioning_enabled else as_wkt(geometry)


def deserialize_geometry(
    geometry_string: Optional[str], is_versioning_enabled: bool = False
) -> QgsGeometry:
    if geometry_string is None or geometry_string == "":
        return QgsGeometry()

    if is_versioning_enabled:
        geometry = QgsGeometry()
        geometry.fromWkb(b64decode(geometry_string))
    else:
        geometry = QgsGeometry.fromWkt(geometry_string)

    return geometry
