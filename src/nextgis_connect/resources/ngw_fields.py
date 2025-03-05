from collections.abc import Sequence
from dataclasses import field as dataclass_field
from dataclasses import replace
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union, cast

from qgis.core import QgsField, QgsFields

from nextgis_connect.resources.ngw_field import FieldId, NgwField


class NgwFields(Sequence[NgwField]):
    _fields: List[NgwField]
    _label_field: Optional[NgwField]
    _ngw_ids: Dict[FieldId, NgwField] = dataclass_field(init=False)
    _attributes: Dict[FieldId, NgwField] = dataclass_field(init=False)
    _keynames: Dict[str, NgwField] = dataclass_field(init=False)

    def __init__(self, fields: Iterable[NgwField]) -> None:
        self._fields = list(fields)

        self._label_field = None
        for field in self._fields:
            if field.is_label:
                self._label_field = field
                break

        self._ngw_ids = {field.ngw_id: field for field in self._fields}
        self._attributes = {field.attribute: field for field in self._fields}
        self._keynames = {field.keyname: field for field in self._fields}

    def __len__(self) -> int:
        return len(self._fields)

    def __getitem__(self, index: int) -> NgwField:  # type: ignore
        return self._fields[index]

    def __setitem__(self, index: int, field: NgwField) -> None:
        old_field = self._fields[index]

        if not old_field.is_label and field.is_label:
            self.__reset_previous_label()
            self._label_field = field

        self._fields[index] = field
        if field.ngw_id != -1:
            self._ngw_ids[field.ngw_id] = field
        if field.attribute != -1:
            self._attributes[field.attribute] = field
        self._keynames[field.keyname] = field

        # Remove old field from dictionaries if the new field has different
        # identifiers
        if old_field.ngw_id != field.ngw_id:
            del self._ngw_ids[old_field.ngw_id]
        if old_field.attribute != field.attribute:
            del self._attributes[old_field.attribute]
        if old_field.keyname != field.keyname:
            del self._keynames[old_field.keyname]

    def __delitem__(self, index: int) -> None:
        field = self._fields.pop(index)
        if field.ngw_id in self._ngw_ids:
            del self._ngw_ids[field.ngw_id]
        if field.attribute in self._attributes:
            del self._attributes[field.attribute]
        if field.is_label:
            self._label_field = None
        del self._keynames[field.keyname]

    @property
    def label_field(self) -> Optional[NgwField]:
        return self._label_field

    def append(self, field: NgwField) -> None:
        if field.is_label:
            self.__reset_previous_label()
            self._label_field = field

        self._fields.append(field)
        if field.ngw_id != -1:
            self._ngw_ids[field.ngw_id] = field
        if field.attribute != -1:
            self._attributes[field.attribute] = field
        self._keynames[field.keyname] = field

    def insert(self, index: int, field: NgwField) -> None:
        if field.is_label:
            self.__reset_previous_label()
            self._label_field = field

        self._fields.insert(index, field)
        if field.ngw_id != -1:
            self._ngw_ids[field.ngw_id] = field
        if field.attribute != -1:
            self._attributes[field.attribute] = field
        self._keynames[field.keyname] = field

    def move(self, source: int, destination: int) -> None:
        self._fields.insert(destination, self._fields.pop(source))

    def __iter__(self) -> Iterator[NgwField]:
        return iter(self._fields)

    def find_with(
        self,
        *,
        ngw_id: Optional[FieldId] = None,
        attribute: Optional[FieldId] = None,
        keyname: Optional[str] = None,
    ) -> Optional[NgwField]:
        if ngw_id is not None:
            return self._ngw_ids.get(ngw_id)
        if attribute is not None:
            return self._attributes.get(attribute)
        if keyname is not None:
            return self._keynames.get(keyname)

        raise AttributeError

    def get_with(
        self,
        *,
        ngw_id: Optional[FieldId] = None,
        attribute: Optional[FieldId] = None,
        keyname: Optional[str] = None,
    ) -> NgwField:
        field = self.find_with(
            ngw_id=ngw_id, attribute=attribute, keyname=keyname
        )
        if field is None:
            raise KeyError

        return field

    def is_compatible(
        self,
        rhs: Union["NgwFields", QgsFields, List[NgwField], List[QgsField]],
        *,
        skip_fields: Union[str, List[str], None] = None,
    ) -> bool:
        if skip_fields is None:
            skip_fields = []
        if isinstance(skip_fields, str):
            skip_fields = [skip_fields]

        if isinstance(rhs, QgsFields):
            rhs = [
                field
                for field in cast(Iterable[QgsField], rhs.toList())
                if field.name() not in skip_fields
            ]

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

    def to_json(self) -> List[Dict[str, Any]]:
        return [field.to_json() for field in self._fields]

    @staticmethod
    def from_json(json: List[Dict[str, Any]]) -> "NgwFields":
        return NgwFields(
            NgwField.from_json(field, index=index)
            for index, field in enumerate(json)
        )

    def __reset_previous_label(self) -> None:
        for i, field in enumerate(self._fields):
            if not field.is_label:
                continue

            self._fields[i] = replace(field, is_label=False)
