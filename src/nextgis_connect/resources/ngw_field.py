from collections.abc import Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

from qgis.core import QgsField, QgsFields
from qgis.PyQt.QtCore import QVariant

FieldId = int


@dataclass(frozen=True)
class NgwField:
    attribute: int
    ngw_id: FieldId
    datatype: QVariant.Type = dataclass_field(init=False)
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

    def is_compatible(self, rhs: Union["NgwField", QgsField]) -> bool:
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


class NgwFields(Sequence):
    _fields: List[NgwField]
    _ngw_ids: Dict[FieldId, NgwField] = dataclass_field(init=False)
    _attributes: Dict[FieldId, NgwField] = dataclass_field(init=False)
    _names: Dict[str, NgwField] = dataclass_field(init=False)

    def __init__(self, fields: Iterable[NgwField]) -> None:
        self._fields = list(fields)
        self._ngw_ids = {field.ngw_id: field for field in self._fields}
        self._attributes = {field.attribute: field for field in self._fields}
        self._names = {field.keyname: field for field in self._fields}

    def __len__(self) -> int:
        return len(self._fields)

    def __getitem__(self, index: int) -> NgwField:
        return self._fields[index]

    def __iter__(self) -> Iterator[NgwField]:
        return iter(self._fields)

    def find_with(
        self,
        *,
        ngw_id: Optional[FieldId] = None,
        attribute: Optional[FieldId] = None,
        name: Optional[str] = None,
    ) -> Optional[NgwField]:
        if ngw_id is not None:
            return self._ngw_ids.get(ngw_id)
        if attribute is not None:
            return self._attributes.get(attribute)
        if name is not None:
            return self._names.get(name)

        raise AttributeError

    def get_with(
        self,
        *,
        ngw_id: Optional[FieldId] = None,
        attribute: Optional[FieldId] = None,
        name: Optional[str] = None,
    ) -> NgwField:
        field = self.find_with(ngw_id=ngw_id, attribute=attribute, name=name)
        if field is None:
            raise KeyError

        return field

    def is_compatible(
        self, rhs: Union["NgwFields", List[Union[NgwField, QgsField]]]
    ) -> bool:
        if len(self._fields) != len(rhs):
            return False

        return all(
            lhs_field.is_compatible(rhs_field)
            for lhs_field, rhs_field in zip(self._fields, rhs)
        )

    def __eq__(self, value: object) -> bool:
        if (
            not isinstance(value, NgwFields)
            or len(self) != len(value)
            or len(self) == 0
        ):
            return False

        shift = self[0].attribute - value[0].attribute
        if shift != 0:
            value = NgwFields(
                list(
                    replace(field, attribute=field.attribute + shift)
                    for field in value
                )
            )

        return list.__eq__(self._fields, value._fields)

    def to_qgs_fields(self) -> QgsFields:
        fields = QgsFields()
        for field in self._fields:
            fields.append(field.to_qgsfield())
        return fields

    @staticmethod
    def from_json(json: List[Dict[str, Any]]) -> "NgwFields":
        return NgwFields(
            NgwField.from_json(field, index=index)
            for index, field in enumerate(json)
        )
