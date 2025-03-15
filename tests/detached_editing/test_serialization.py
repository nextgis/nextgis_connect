import unittest
from base64 import b64encode
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from qgis.core import QgsGeometry
from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
    serialize_geometry,
    serialize_value,
    simplify_date_and_time,
    simplify_value,
)
from tests.ng_connect_testcase import (
    NgConnectTestCase,
)


@dataclass
class AttributeValuesTestData:
    initial_value: Any
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
            AttributeValuesTestData(
                "NULL", "null", None
            ),  # NULL representation
        ]

        self.date_and_time_values = [
            AttributeValuesTestData(
                QDate(2025, 3, 4), '"2025-03-04"', "2025-03-04"
            ),  # date
            AttributeValuesTestData(
                QTime(14, 30, 15), '"14:30:15"', "14:30:15"
            ),  # time
            AttributeValuesTestData(
                QDateTime(QDate(2025, 3, 4), QTime(14, 30, 15)),
                '"2025-03-04T14:30:15"',
                "2025-03-04T14:30:15",
            ),  # datetime
            # Invalid date, time and datetime
            AttributeValuesTestData(QDate(), "null", None),
            AttributeValuesTestData(
                QDate(-1, 1, 1), '""', ""
            ),  # Negative year
            AttributeValuesTestData(
                QDate(2025, 2, 30), "null", None
            ),  # Non-existent year
            AttributeValuesTestData(QTime(), "null", None),
            AttributeValuesTestData(
                QTime(25, 0, 0), "null", None
            ),  # Hours more than 24
            AttributeValuesTestData(QDateTime(), "null", None),
            AttributeValuesTestData(
                QDateTime(QDate(-1, 1, 1), QTime(14, 30, 15)),
                '""',
                "",
            ),  # Incorrect date
            AttributeValuesTestData(
                QDateTime(QDate(2025, 2, 30), QTime(14, 30, 15)),
                "null",
                None,
            ),  # Incorrect date
            AttributeValuesTestData(
                QDateTime(QDate(2025, 1, 1), QTime(25, 0, 0)),
                '"2025-01-01T00:00:00"',
                "2025-01-01T00:00:00",
            ),  # Incorrect time
            # datetime library types
            AttributeValuesTestData(
                date(2025, 3, 4), '"2025-03-04"', "2025-03-04"
            ),  # date
            AttributeValuesTestData(
                time(14, 30, 15), '"14:30:15"', "14:30:15"
            ),  # time
            AttributeValuesTestData(
                datetime(2025, 3, 4, 14, 30, 15),
                '"2025-03-04T14:30:15"',
                "2025-03-04T14:30:15",
            ),  # datetime
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

    def test_simplify_date_and_time(self) -> None:
        # Date case
        qdate = QDate(2025, 3, 4)
        expected_qdate = "2025-03-04"
        py_date = date(2025, 3, 4)
        self.assertTrue(
            simplify_date_and_time(qdate, iso_format=True)
            == simplify_value(qdate)
            == expected_qdate
        )
        self.assertTrue(
            simplify_date_and_time(py_date, iso_format=True)
            == simplify_value(py_date),
            expected_qdate,
        )

        # Time case
        qtime = QTime(14, 30, 15)
        expected_qtime = "14:30:15"
        py_time = time(14, 30, 15)
        self.assertTrue(
            simplify_date_and_time(qtime, iso_format=True)
            == simplify_value(qtime)
            == expected_qtime
        )
        self.assertTrue(
            simplify_date_and_time(py_time, iso_format=True)
            == simplify_value(py_time)
            == expected_qtime
        )

        # Datetime case
        qdatetime = QDateTime(QDate(2025, 3, 4), QTime(14, 30, 15))
        expected_qdatetime = "2025-03-04T14:30:15"
        py_datetime = datetime(2025, 3, 4, 14, 30, 15)
        self.assertTrue(
            simplify_date_and_time(qdatetime, iso_format=True)
            == simplify_value(qdatetime)
            == expected_qdatetime
        )
        self.assertTrue(
            simplify_date_and_time(py_datetime, iso_format=True)
            == simplify_value(py_datetime)
            == expected_qdatetime
        )

        # Invalid date
        invalid_qdate_1 = QDate(-1, 1, 1)
        self.assertTrue(
            simplify_date_and_time(invalid_qdate_1, iso_format=True)
            == simplify_value(invalid_qdate_1)
            == ""
        )

        invalid_qdate_2 = QDate(2025, 2, 30)
        self.assertTrue(
            simplify_date_and_time(invalid_qdate_2, iso_format=True)
            == simplify_value(invalid_qdate_2)
            is None
        )

        # Invalid time
        invalid_qtime = QTime(25, 0, 0)
        self.assertTrue(
            simplify_date_and_time(invalid_qtime, iso_format=True)
            == simplify_value(invalid_qtime)
            is None
        )

        # Cases for invalid QDateTime with invalid date and valid time
        invalid_qdatetime_1 = QDateTime(QDate(-1, 1, 1), QTime(14, 30, 15))
        self.assertTrue(
            simplify_date_and_time(invalid_qdatetime_1, iso_format=True)
            == simplify_value(invalid_qdatetime_1)
            == ""
        )
        invalid_qdatetime_2 = QDateTime(QDate(2025, 2, 30), QTime(14, 30, 15))
        self.assertTrue(
            simplify_date_and_time(invalid_qdatetime_2, iso_format=True)
            == simplify_value(invalid_qdatetime_2)
            is None
        )

        # Case for invalid QDateTime with valid date and invalid time
        invalid_qdatetime_3 = QDateTime(QDate(2025, 1, 1), QTime(25, 0, 0))
        expected_invalid_qdatetime_3 = "2025-01-01T00:00:00"
        self.assertTrue(
            simplify_date_and_time(invalid_qdatetime_3, iso_format=True)
            == simplify_value(invalid_qdatetime_3)
            == expected_invalid_qdatetime_3
        )

    def test_simplify_value(self):
        for case in self.attribute_values:
            with self.subTest(value=case.initial_value):
                simplified_value = simplify_value(case.initial_value)
                self.assertEqual(simplified_value, case.expected_deserialized)

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


if __name__ == "__main__":
    unittest.main()
