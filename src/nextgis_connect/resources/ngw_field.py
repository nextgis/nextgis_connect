from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from qgis.core import QgsField

from nextgis_connect.compat import FieldType
from nextgis_connect.resources.ngw_data_type import NgwDataType

FieldId = int


@dataclass(frozen=True, init=False)
class NgwField:
    ngw_id: FieldId
    datatype: NgwDataType
    keyname: str
    display_name: str
    is_label: bool
    is_visible: bool
    is_used_for_search: bool
    lookup_table: Optional[int] = None
    attribute: int

    def __init__(
        self,
        ngw_id: FieldId,
        datatype: Union[str, FieldType, NgwDataType],
        keyname: str,
        display_name: str,
        is_label: bool,
        is_visible: bool = True,
        is_used_for_search: bool = True,
        lookup_table: Optional[int] = None,
        attribute: int = -1,
    ) -> None:
        super().__setattr__("ngw_id", ngw_id)
        if isinstance(datatype, str):
            super().__setattr__("datatype", NgwDataType.from_name(datatype))
        elif isinstance(datatype, FieldType):
            super().__setattr__(
                "datatype", NgwDataType.from_qt_value(datatype)
            )
        elif isinstance(datatype, NgwDataType):
            super().__setattr__("datatype", datatype)
        super().__setattr__("keyname", keyname)
        super().__setattr__("display_name", display_name)
        super().__setattr__("is_label", is_label)
        super().__setattr__("is_visible", is_visible)
        super().__setattr__("is_used_for_search", is_used_for_search)
        super().__setattr__("lookup_table", lookup_table)
        super().__setattr__("attribute", attribute)

    def is_compatible(self, rhs: Union["NgwField", QgsField]) -> bool:
        if isinstance(rhs, NgwField):
            return (
                self.ngw_id == rhs.ngw_id
                and self.datatype == rhs.datatype
                and self.keyname == rhs.keyname
            )
        else:
            datatype = self.datatype.qt_value

            if datatype == FieldType.QTime:
                # GPKG does not have Time type
                datatype = FieldType.QString

            if self.keyname == "fid":
                # Workaround for NGW-1326
                return (
                    datatype == rhs.type() or FieldType.LongLong == rhs.type()
                )

            return datatype == rhs.type() and self.keyname == rhs.name()

    def to_qgs_field(self) -> QgsField:
        return QgsField(self.keyname, self.datatype.qt_value)

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.ngw_id if self.ngw_id != -1 else None,
            "datatype": self.datatype.name,
            "keyname": self.keyname,
            "display_name": self.display_name,
            "label_field": self.is_label,
            "grid_visibility": self.is_visible,
            "text_search": self.is_used_for_search,
            "lookup_table": {"id": self.lookup_table}
            if self.lookup_table
            else None,
        }

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
            datatype=json["datatype"],
            keyname=json["keyname"],
            display_name=json["display_name"],
            is_label=json.get("label_field", False),
            is_visible=json.get("grid_visibility", True),
            is_used_for_search=json.get("text_search", True),
            lookup_table=get_lookup_table(json),
        )
