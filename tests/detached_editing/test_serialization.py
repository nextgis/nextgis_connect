import json
import unittest
from base64 import b64decode, b64encode

from qgis.core import QgsGeometry
from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
    serialize_geometry,
    serialize_value,
)
from tests.ng_connect_testcase import (
    NgConnectTestCase,
)


class TestSerialization(NgConnectTestCase):
    def setUp(self):
        super().setUp()

        self.types = [
            (12345, "12345", 12345),  # integer
            (8388607, "8388607", 8388607),  # mediumint
            (3.14159, "3.14159", 3.14159),  # real
            ("Hello, World!", '"Hello, World!"', "Hello, World!"),  # text
            (
                QDate(2025, 3, 4),
                json.dumps("2025-03-04"),
                "2025-03-04",
            ),  # date
            (QTime(14, 30, 15), json.dumps("14:30:15"), "14:30:15"),  # time
            (
                QDateTime(QDate(2025, 3, 4), QTime(14, 30, 15)),
                json.dumps("2025-03-04T14:30:15"),
                "2025-03-04T14:30:15",
            ),  # datetime
        ]

        self.geometries = [
            "Point (1 1)",
            "LineString (0 0, 1 1, 2 2)",
            "Polygon ((0 0, 1 0, 1 1, 0 1, 0 0))",
            "MultiPoint ((1 1),(2 2))",
            "MultiLineString ((0 0, 1 1),(2 2, 3 3))",
            "MultiPolygon (((0 0, 1 0, 1 1, 0 1, 0 0)),((2 2, 3 2, 3 3, 2 3, 2 2)))",
        ]

    def test_serialize_value(self) -> None:
        for value, expected_serialized, _expected_deserialized in self.types:
            with self.subTest(value=value):
                serialized = serialize_value(value)
                self.assertEqual(serialized, expected_serialized)

    def test_deserialize_value(self) -> None:
        for value, expected_serialized, expected_deserialized in self.types:
            with self.subTest(value=value):
                deserialized = deserialize_value(expected_serialized)
                self.assertEqual(deserialized, expected_deserialized)

    def test_serialization_deserialization_cycle_value(self) -> None:
        for value, expected_serialized, expected_deserialized in self.types:
            with self.subTest(value=value):
                serialized = serialize_value(value)
                self.assertEqual(serialized, expected_serialized)

                deserialized = deserialize_value(serialized)
                self.assertEqual(deserialized, expected_deserialized)

    def test_serialize_empty_geometry(self) -> None:
        self.assertEqual(serialize_geometry(None), "")
        self.assertEqual(serialize_geometry(QgsGeometry()), "")

    def test_serialize_geometry(self) -> None:
        for wkt in self.geometries:
            with self.subTest(geometry=wkt):
                geom = QgsGeometry.fromWkt(wkt)
                serialized_wkt = serialize_geometry(
                    geom, is_versioning_enabled=False
                )
                serialized_wkb = serialize_geometry(
                    geom, is_versioning_enabled=True
                )

                self.assertEqual(serialized_wkt, wkt)
                self.assertEqual(
                    serialized_wkb,
                    b64encode(geom.asWkb().data()).decode("ascii"),
                )

    def test_deserialize_empty_geometry(self) -> None:
        self.assertTrue(deserialize_geometry("").isEmpty())
        self.assertTrue(deserialize_geometry(None).isEmpty())

    def test_deserialize_geometry(self) -> None:
        for wkt in self.geometries:
            wkb = b64encode(QgsGeometry.fromWkt(wkt).asWkb().data()).decode(
                "ascii"
            )
            with self.subTest(geometry=wkt):
                deserialized_wkt = deserialize_geometry(
                    wkt, is_versioning_enabled=False
                )
                deserialized_wkb = deserialize_geometry(
                    wkb, is_versioning_enabled=True
                )

                self.assertTrue(
                    deserialized_wkt.equals(QgsGeometry.fromWkt(wkt))
                )
                geometry_wkb = QgsGeometry()
                geometry_wkb.fromWkb(b64decode(wkb))
                self.assertTrue(deserialized_wkb.equals(geometry_wkb))

    def test_serialization_deserialization_cycle_geometry(self) -> None:
        for wkt in self.geometries:
            with self.subTest(geometry=wkt):
                original_geometry = QgsGeometry.fromWkt(wkt)
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

                self.assertTrue(deserialized_wkt.equals(original_geometry))
                self.assertTrue(deserialized_wkb.equals(original_geometry))


if __name__ == "__main__":
    unittest.main()
