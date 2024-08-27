import unittest
from dataclasses import FrozenInstanceError

from nextgis_connect.resources.ngw_field import NgwField
from PyQt5.QtCore import QVariant
from qgis.core import QgsField


class TestNgwField(unittest.TestCase):
    def setUp(self):
        self.field_json = {
            "id": 1,
            "datatype": "STRING",
            "keyname": "name",
            "display_name": "Name",
            "label_field": True,
            "lookup_table": {"id": 10},
        }

    def test_datatypes_serializing(self):
        field_types = {
            "INTEGER": QVariant.Type.Int,
            "BIGINT": QVariant.Type.LongLong,
            "REAL": QVariant.Type.Double,
            "STRING": QVariant.Type.String,
            "DATE": QVariant.Type.Date,
            "TIME": QVariant.Type.Time,
            "DATETIME": QVariant.Type.DateTime,
            # ---
            "UNKNOWN": QVariant.Type.String,
        }
        for datatype_name, datatype in field_types.items():
            field = NgwField(
                attribute=0,
                ngw_id=1,
                datatype_name=datatype_name,
                keyname="name",
                display_name="Name",
                is_label=False,
            )
            self.assertEqual(field.datatype, datatype)

    def test_is_compatible_with_ngwfield(self):
        field1 = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=False,
        )
        field2 = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=False,
        )
        self.assertTrue(field1.is_compatible(field2))

        field1 = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=False,
        )
        field2 = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="REAL",
            keyname="name",
            display_name="Name",
            is_label=False,
        )
        self.assertFalse(field1.is_compatible(field2))

    def test_is_compatible_with_qgsfield(self):
        field = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=True,
        )
        qgs_field = QgsField("name", QVariant.Type.String)
        self.assertTrue(field.is_compatible(qgs_field))

        field = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=True,
        )
        qgs_field = QgsField("name", QVariant.Type.Int)
        self.assertFalse(field.is_compatible(qgs_field))

    def test_to_qgsfield(self):
        field = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=True,
        )
        qgs_field = field.to_qgsfield()
        self.assertEqual(qgs_field.name(), "name")
        self.assertEqual(qgs_field.type(), QVariant.Type.String)

    def test_from_json(self):
        field = NgwField.from_json(self.field_json)
        self.assertEqual(field.ngw_id, 1)
        self.assertEqual(field.datatype_name, "STRING")
        self.assertEqual(field.keyname, "name")
        self.assertEqual(field.display_name, "Name")
        self.assertTrue(field.is_label)
        self.assertEqual(field.lookup_table, 10)

    def test_list_from_json(self):
        fields_data = [
            {**self.field_json, "id": 1, "keyname": "field_1"},
            {**self.field_json, "id": 2, "keyname": "field_2"},
        ]

        fields = NgwField.list_from_json(fields_data)
        self.assertEqual(len(fields), 2)
        self.assertEqual(fields[0].attribute, 0)
        self.assertEqual(fields[1].attribute, 1)

    def test_frozen_class(self):
        field = NgwField(
            attribute=0,
            ngw_id=1,
            datatype_name="STRING",
            keyname="name",
            display_name="Name",
            is_label=True,
        )
        with self.assertRaises(FrozenInstanceError):
            field.ngw_id = 2  # type: ignore


if __name__ == "__main__":
    unittest.main()
