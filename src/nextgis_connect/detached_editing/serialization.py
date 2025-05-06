import json
from base64 import b64decode, b64encode
from datetime import date, datetime, time
from typing import Any, Dict, Optional, Union

from qgis.core import QgsApplication, QgsGeometry, QgsWkbTypes
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QVariant

from nextgis_connect.compat import GeometryType
from nextgis_connect.exceptions import NgConnectError


def simplify_date_and_time(
    date_object: Union[datetime, date, time, QDateTime, QDate, QTime],
    *,
    iso_format: bool = False,
) -> Union[str, Dict[str, int], None]:
    if (
        isinstance(date_object, QVariant) and date_object.isNull()
    ) or date_object == QgsApplication.nullRepresentation():
        return None

    if isinstance(date_object, (QDateTime, QDate, QTime)):
        if date_object.isNull() or not date_object.isValid():
            return None

        if (isinstance(date_object, QDate) and date_object.year() < 1) or (
            isinstance(date_object, QDateTime)
            and date_object.date().year() < 1
        ):
            return None

    if iso_format:
        if isinstance(date_object, (datetime, date, time)):
            return date_object.isoformat()
        elif isinstance(date_object, QDateTime):
            return date_object.toString("yyyy-MM-dd'T'HH:mm:ss")
        return date_object.toString(Qt.DateFormat.ISODate)

    extracted_date = None
    extracted_time = None
    if isinstance(date_object, datetime):
        extracted_date = date_object.date()
        extracted_time = date_object.time()
    elif isinstance(date_object, date):
        extracted_date = date_object
    elif isinstance(date_object, time):
        extracted_time = date_object
    elif isinstance(date_object, QDateTime):
        extracted_date = date_object.date()
        extracted_time = date_object.time()
    elif isinstance(date_object, QDate):
        extracted_date = date_object
    elif isinstance(date_object, QTime):
        extracted_time = date_object

    def get_int_value(date_part):
        return date_part() if callable(date_part) else date_part

    result = {}
    if extracted_date is not None:
        result["year"] = get_int_value(extracted_date.year)
        result["month"] = get_int_value(extracted_date.month)
        result["day"] = get_int_value(extracted_date.day)

    if extracted_time is not None:
        result["hour"] = get_int_value(extracted_time.hour)
        result["minute"] = get_int_value(extracted_time.minute)
        result["second"] = get_int_value(extracted_time.second)

    return result


def simplify_value(value: Any) -> Any:
    if (
        isinstance(value, QVariant) and value.isNull()
    ) or value == QgsApplication.nullRepresentation():
        value = None

    elif isinstance(value, (datetime, date, time, QDate, QTime, QDateTime)):
        value = simplify_date_and_time(value, iso_format=True)

    return value


def serialize_value(value: Any) -> Any:
    return json.dumps(simplify_value(value))


def deserialize_value(value: str) -> Any:
    return json.loads(value)


def serialize_geometry(
    geometry: Optional[QgsGeometry], is_versioning_enabled: bool = False
) -> str:
    """
    Serializes a QgsGeometry object to a string representation.

    :param geometry: The geometry to serialize. If None or empty, returns an empty string.
    :type geometry: Optional[QgsGeometry]
    :param is_versioning_enabled: If True, serializes the geometry to a base64-encoded WKB string.
                                  If False, serializes the geometry to a WKT string.
    :type is_versioning_enabled: bool
    :return: The serialized geometry as a string.
    :rtype: str
    """
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
    """
    Deserialize a geometry string into a QgsGeometry object.

    :param geometry_string: The geometry string to deserialize. Can be in WKT or WKB format.
    :type geometry_string: Optional[str]
    :param is_versioning_enabled: Flag indicating if versioning is enabled. If True, the geometry string is expected to be in WKB format and base64 encoded.
    :type is_versioning_enabled: bool
    :return: The deserialized QgsGeometry object.
    :rtype: QgsGeometry
    """
    if geometry_string is None or geometry_string == "":
        return QgsGeometry()

    if is_versioning_enabled:
        geometry = QgsGeometry()
        geometry.fromWkb(b64decode(geometry_string))
    else:
        geometry = QgsGeometry.fromWkt(geometry_string)

    return geometry
