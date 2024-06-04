from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from qgis.core import QgsField
from qgis.PyQt.QtCore import QVariant

FieldId = int


@dataclass(frozen=True)
class NgwField:
    attribute: int
    ngw_id: FieldId
    datatype_name: str
    keyname: str
    display_name: str
    is_label: bool
    lookup_table: Optional[int] = None

    @property
    def datatype(self) -> QVariant.Type:
        field_types = {
            "INTEGER": QVariant.Type.Int,
            "BIGINT": QVariant.Type.LongLong,
            "REAL": QVariant.Type.Double,
            "STRING": QVariant.Type.String,
            "DATE": QVariant.Type.Date,
            "TIME": QVariant.Type.Time,
            "DATETIME": QVariant.Type.DateTime,
        }
        return field_types.get(self.datatype_name, QVariant.Type.String)

    def is_compatible(self, rhs: Union["NgwField", QgsField]):
        if isinstance(rhs, NgwField):
            return (
                self.ngw_id == rhs.ngw_id
                and self.datatype_name == rhs.datatype_name
                and self.keyname == rhs.keyname
            )
        else:
            return self.datatype == rhs.type() and self.keyname == rhs.name()

    def to_qgsfield(self) -> QgsField:
        return QgsField(self.keyname, self.datatype)

    @staticmethod
    def list_from_json(json: List[Dict[str, Any]]) -> List["NgwField"]:
        def get_lookup_table(field):
            table = field.get("lookup_table")
            if table is None:
                return None
            return table.get("id")

        return [
            NgwField(
                attribute,
                field["id"],
                field["datatype"],
                field["keyname"],
                field["display_name"],
                field["label_field"],
                get_lookup_table(field),
            )
            for attribute, field in enumerate(json)
        ]
