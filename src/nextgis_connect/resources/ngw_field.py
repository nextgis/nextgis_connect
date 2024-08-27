from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from qgis.core import QgsField
from qgis.PyQt.QtCore import QVariant

FieldId = int


@dataclass(frozen=True)
class NgwField:
    attribute: int
    ngw_id: FieldId
    datatype: QVariant.Type = field(init=False)
    datatype_name: str
    keyname: str
    display_name: str
    is_label: bool
    lookup_table: Optional[int] = None

    def __post_init__(self) -> None:
        field_types = {
            "INTEGER": QVariant.Type.Int,
            "BIGINT": QVariant.Type.LongLong,
            "REAL": QVariant.Type.Double,
            "STRING": QVariant.Type.String,
            "DATE": QVariant.Type.Date,
            "TIME": QVariant.Type.Time,
            "DATETIME": QVariant.Type.DateTime,
        }
        datatype = field_types.get(self.datatype_name, QVariant.Type.String)
        super().__setattr__("datatype", datatype)

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
    def from_json(json: Dict[str, Any], *, index: int = -1) -> "NgwField":
        def get_lookup_table(field: Dict[str, Any]) -> Optional[int]:
            table = field.get("lookup_table")
            if table is None:
                return None
            return table.get("id")

        return NgwField(
            attribute=index,
            ngw_id=json["id"],
            datatype_name=json["datatype"],
            keyname=json["keyname"],
            display_name=json["display_name"],
            is_label=json["label_field"],
            lookup_table=get_lookup_table(json),
        )

    @staticmethod
    def list_from_json(json: List[Dict[str, Any]]) -> List["NgwField"]:
        return [
            NgwField.from_json(field, index=index)
            for index, field in enumerate(json)
        ]
