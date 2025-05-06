import unittest
from base64 import b64encode
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from qgis.core import QgsApplication, QgsGeometry
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QTimeZone, QVariant

from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
    serialize_geometry,
    serialize_value,
    simplify_date_and_time,
    simplify_value,
)
from nextgis_connect.exceptions import SerializationError
from tests.ng_connect_testcase import (
    NgConnectTestCase,
)


@dataclass
class AttributeValuesTestData:
    initial_value: Any
    expected_serialized: Any
    expected_deserialized: Any


@dataclass
class AttributeDateValuesTestData:
    initial_value: Any
    expected_dict: Any
    expected_serialized: Any
    expected_deserialized: Any


@dataclass
class GeometryTestData:
    wkt: str
    expected_serialized_wkt: str
    expected_serialized_wkb: str
    expected_deserialized_wkt: QgsGeometry
    expected_deserialized_wkb: QgsGeometry


class TestSerialization(NgConnectTestCase):
    def setUp(self):
        super().setUp()
        self.attribute_values = [
            AttributeValuesTestData(12345, "12345", 12345),  # integer
            AttributeValuesTestData(8388607, "8388607", 8388607),  # mediumint
            AttributeValuesTestData(3.14159, "3.14159", 3.14159),  # real
            AttributeValuesTestData(None, "null", None),  # None value
            AttributeValuesTestData(
                "Hello, World!", '"Hello, World!"', "Hello, World!"
            ),  # text
            AttributeValuesTestData("", '""', ""),  # empty string
            AttributeValuesTestData("NULL", "null", None),
            AttributeValuesTestData(
                QgsApplication.nullRepresentation(), "null", None
            ),
            AttributeValuesTestData(None, "null", None),
            AttributeValuesTestData(QVariant(), "null", None),
        ]

        VALID_DATE_PARTS = (2025, 3, 4)
        VALID_TIME_PARTS = (14, 30, 15)
        VALID_DATETIME_PARTS = (*VALID_DATE_PARTS, *VALID_TIME_PARTS)
        VALID_DATE_STR = "2025-03-04"
        VALID_TIME_STR = "14:30:15"
        VALID_DATETIME_STR = f"{VALID_DATE_STR}T{VALID_TIME_STR}"

        DATE_KEYS = ("year", "month", "day")
        TIME_KEYS = ("hour", "minute", "second")
        DATETIME_KEYS = (*DATE_KEYS, *TIME_KEYS)

        self.date_and_time_values = [
            # Valid date
            AttributeDateValuesTestData(
                QDate(*VALID_DATE_PARTS),
                dict(zip(DATE_KEYS, VALID_DATE_PARTS)),
                f'"{VALID_DATE_STR}"',
                VALID_DATE_STR,
            ),
            AttributeDateValuesTestData(
                date(*VALID_DATE_PARTS),
                dict(zip(DATE_KEYS, VALID_DATE_PARTS)),
                f'"{VALID_DATE_STR}"',
                VALID_DATE_STR,
            ),
            # Valid time
            AttributeDateValuesTestData(
                QTime(*VALID_TIME_PARTS),
                dict(zip(TIME_KEYS, VALID_TIME_PARTS)),
                f'"{VALID_TIME_STR}"',
                VALID_TIME_STR,
            ),
            AttributeDateValuesTestData(
                time(*VALID_TIME_PARTS),
                dict(zip(TIME_KEYS, VALID_TIME_PARTS)),
                f'"{VALID_TIME_STR}"',
                VALID_TIME_STR,
            ),
            # Valid datetime
            AttributeDateValuesTestData(
                QDateTime(*VALID_DATETIME_PARTS),
                dict(zip(DATETIME_KEYS, VALID_DATETIME_PARTS)),
                f'"{VALID_DATETIME_STR}"',
                VALID_DATETIME_STR,
            ),
            AttributeDateValuesTestData(
                datetime(*VALID_DATETIME_PARTS),
                dict(zip(DATETIME_KEYS, VALID_DATETIME_PARTS)),
                f'"{VALID_DATETIME_STR}"',
                VALID_DATETIME_STR,
            ),
            # With timezones
            AttributeDateValuesTestData(
                QDateTime(*VALID_DATETIME_PARTS, 0, Qt.TimeSpec.UTC),
                dict(zip(DATETIME_KEYS, VALID_DATETIME_PARTS)),
                f'"{VALID_DATETIME_STR}"',
                VALID_DATETIME_STR,
            ),
            AttributeDateValuesTestData(
                QDateTime(
                    QDate(*VALID_DATE_PARTS),
                    QTime(*VALID_TIME_PARTS),
                    QTimeZone(b"Europe/Paris"),
                ),
                dict(zip(DATETIME_KEYS, VALID_DATETIME_PARTS)),
                f'"{VALID_DATETIME_STR}"',
                VALID_DATETIME_STR,
            ),
            # Empty objects
            AttributeDateValuesTestData(
                QDateTime(),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QDate(),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QTime(),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QVariant(),
                None,
                "null",
                None,
            ),
            # Negative year
            AttributeDateValuesTestData(
                QDate(-1, 1, 1),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QDateTime(QDate(-1, 1, 1), QTime(*VALID_TIME_PARTS)),
                None,
                "null",
                None,
            ),
            # Invalid date
            AttributeDateValuesTestData(
                QDate(2025, 2, 30),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QDateTime(QDate(2025, 2, 30), QTime(*VALID_TIME_PARTS)),
                None,
                "null",
                None,
            ),
            # Invalid time
            AttributeDateValuesTestData(
                QTime(25, 0, 0),
                None,
                "null",
                None,
            ),
            AttributeDateValuesTestData(
                QDateTime(QDate(*VALID_DATE_PARTS), QTime(25, 0, 0)),
                dict(zip(DATETIME_KEYS, (*VALID_DATE_PARTS, 0, 0, 0))),
                f'"{VALID_DATE_STR}T00:00:00"',
                f"{VALID_DATE_STR}T00:00:00",
            ),
        ]

        wkt_geometries = [
            "Point (1 1)",
            "LineString (0 0, 1 1, 2 2)",
            "Polygon ((0 0, 1 0, 1 1, 0 1, 0 0))",
            "MultiPoint ((1 1),(2 2))",
            "MultiLineString ((0 0, 1 1),(2 2, 3 3))",
            "MultiPolygon (((0 0, 1 0, 1 1, 0 1, 0 0)),((2 2, 3 2, 3 3, 2 3, 2 2)))",
            # WKT with Z coordinate
            "Point Z (1 2 3)",
            "LineString Z (0 0 1, 1 1 2, 2 2 3)",
            "Polygon Z ((0 0 1, 1 0 2, 1 1 3, 0 1 4, 0 0 5))",
            "MultiPoint Z ((1 1 1),(2 2 2))",
            "MultiLineString Z ((0 0 1, 1 1 2),(2 2 3, 3 3 4))",
            "MultiPolygon Z (((0 0 1, 1 0 2, 1 1 3, 0 1 4, 0 0 5)),((2 2 6, 3 2 7, 3 3 8, 2 3 9, 2 2 10)))",
        ]

        self.geometries = [
            GeometryTestData(
                wkt=wkt,
                expected_serialized_wkt=wkt,
                expected_serialized_wkb=b64encode(
                    QgsGeometry.fromWkt(wkt).asWkb().data()
                ).decode("ascii"),
                expected_deserialized_wkt=QgsGeometry.fromWkt(wkt),
                expected_deserialized_wkb=QgsGeometry.fromWkt(wkt),
            )
            for wkt in wkt_geometries
        ]

    def test_simplify_value(self):
        for case in self.attribute_values:
            with self.subTest(value=case.initial_value):
                simplified_value = simplify_value(case.initial_value)
                self.assertEqual(simplified_value, case.expected_deserialized)

    def test_simplify_date_and_time(self):
        for case in self.date_and_time_values:
            with self.subTest(value=case.initial_value):
                simplified_value = simplify_value(case.initial_value)

                simplified_datetime_iso_value = simplify_date_and_time(
                    case.initial_value, iso_format=True
                )
                self.assertTrue(
                    simplified_value
                    == simplified_datetime_iso_value
                    == case.expected_deserialized
                )

                simplified_datetime_dict_value = simplify_date_and_time(
                    case.initial_value, iso_format=False
                )
                self.assertEqual(
                    simplified_datetime_dict_value, case.expected_dict
                )

    def test_serialize_value(self) -> None:
        for case in [*self.attribute_values, *self.date_and_time_values]:
            with self.subTest(value=case.initial_value):
                serialized = serialize_value(case.initial_value)
                self.assertEqual(serialized, case.expected_serialized)

    def test_deserialize_value(self) -> None:
        for case in [*self.attribute_values, *self.date_and_time_values]:
            with self.subTest(value=case.initial_value):
                deserialized = deserialize_value(case.expected_serialized)
                self.assertEqual(deserialized, case.expected_deserialized)

    def test_serialization_deserialization_cycle_value(self) -> None:
        for case in [*self.attribute_values, *self.date_and_time_values]:
            with self.subTest(value=case.initial_value):
                serialized = serialize_value(case.initial_value)
                self.assertEqual(serialized, case.expected_serialized)

                deserialized = deserialize_value(serialized)
                self.assertEqual(deserialized, case.expected_deserialized)

    def test_serialize_empty_geometry(self) -> None:
        self.assertEqual(serialize_geometry(None), "")
        self.assertEqual(serialize_geometry(QgsGeometry()), "")

    def test_serialize_geometry(self) -> None:
        for case in self.geometries:
            with self.subTest(geometry=case.wkt):
                geom = QgsGeometry.fromWkt(case.wkt)
                serialized_wkt = serialize_geometry(
                    geom, is_versioning_enabled=False
                )
                serialized_wkb = serialize_geometry(
                    geom, is_versioning_enabled=True
                )

                self.assertEqual(serialized_wkt, case.expected_serialized_wkt)
                self.assertEqual(serialized_wkb, case.expected_serialized_wkb)

    def test_deserialize_empty_geometry(self) -> None:
        self.assertTrue(deserialize_geometry("").isEmpty())
        self.assertTrue(deserialize_geometry(None).isEmpty())

    def test_deserialize_geometry(self) -> None:
        for case in self.geometries:
            with self.subTest(geometry=case.wkt):
                deserialized_wkt = deserialize_geometry(
                    case.expected_serialized_wkt, is_versioning_enabled=False
                )
                deserialized_wkb = deserialize_geometry(
                    case.expected_serialized_wkb, is_versioning_enabled=True
                )

                self.assertTrue(
                    deserialized_wkt.equals(case.expected_deserialized_wkt)
                )
                self.assertTrue(
                    deserialized_wkb.equals(case.expected_deserialized_wkb)
                )

    def test_serialization_deserialization_cycle_geometry(self) -> None:
        for case in self.geometries:
            with self.subTest(geometry=case.wkt):
                original_geometry = QgsGeometry.fromWkt(case.wkt)
                serialized_wkt = serialize_geometry(
                    original_geometry, is_versioning_enabled=False
                )
                serialized_wkb = serialize_geometry(
                    original_geometry, is_versioning_enabled=True
                )

                deserialized_wkt = deserialize_geometry(
                    serialized_wkt, is_versioning_enabled=False
                )
                deserialized_wkb = deserialize_geometry(
                    serialized_wkb, is_versioning_enabled=True
                )

                self.assertTrue(
                    deserialized_wkt.equals(case.expected_deserialized_wkt)
                )
                self.assertTrue(
                    deserialized_wkb.equals(case.expected_deserialized_wkb)
                )

    def test_serialize_value_with_unknown_type(self):
        class Dummy:
            pass

        with self.assertRaises(SerializationError):
            serialize_value(Dummy())

    def test_deserialize_value_with_invalid_json(self):
        with self.assertRaises(SerializationError):
            deserialize_value("{invalid_json}")

    def test_deserialize_invalid_geometry(self):
        with self.subTest("Invalid WKT"):
            with self.assertRaises(SerializationError):
                deserialize_geometry(
                    "INVALIDWKT",
                    is_versioning_enabled=False,
                )

        with self.subTest("Invalid WKB64"):
            with self.assertRaises(SerializationError):
                deserialize_geometry(
                    "!!notbase64@@",
                    is_versioning_enabled=True,
                )


if __name__ == "__main__":
    unittest.main()
