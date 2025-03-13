from dataclasses import dataclass, field
from typing import Set

from nextgis_connect.detached_editing.actions import (
    DataChangeAction,
    FeatureAction,
    FeatureId,
)
from nextgis_connect.resources.ngw_field import FieldId


@dataclass
class VersioningConflict:
    local_action: FeatureAction
    remote_action: FeatureAction

    conflicting_fields: Set[FieldId] = field(init=False)
    has_geometry_conflict: bool = field(init=False)

    def __post_init__(self) -> None:
        conflicting_fields = set()
        has_geometry_conflict = False

        if isinstance(self.local_action, DataChangeAction) and isinstance(
            self.remote_action, DataChangeAction
        ):
            if self.local_action.fields and self.remote_action.fields:
                local_fields = self.local_action.fields_dict
                remote_fields = self.remote_action.fields_dict

                conflicting_fields = set(
                    field_id
                    for field_id, value in local_fields.items()
                    if remote_fields.get(field_id) != value
                )

            has_geometry_conflict = (
                self.local_action.geom is not None
                and self.remote_action.geom is not None
                and self.local_action.geom != self.remote_action.geom
            )

        super().__setattr__("conflicting_fields", conflicting_fields)
        super().__setattr__("has_geometry_conflict", has_geometry_conflict)

    @property
    def fid(self) -> FeatureId:
        return self.local_action.fid
