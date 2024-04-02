from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsField
from qgis.PyQt.QtCore import QVariant

FieldId = int


@dataclass(frozen=True)
class NgwField:
    attribute: int
    ngw_id: FieldId
    keyname: str
    display_name: str
    datatype_name: str
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

    def to_qgsfield(self) -> QgsField:
        return QgsField(self.keyname, self.datatype)
