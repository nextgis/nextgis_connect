from dataclasses import dataclass, field
from typing import Optional, Set

from qgis.core import QgsFeature

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)
from nextgis_connect.resources.ngw_field import FieldId


@dataclass
class ConflictResolvingItem:
    conflict: VersioningConflict
    local_feature: Optional[QgsFeature]
    remote_feature: Optional[QgsFeature]
    result_feature: Optional[QgsFeature]
    changed_fields: Set[FieldId] = field(default_factory=set)
    is_geometry_changed: bool = False
    is_resolved: bool = False

    @property
    def resolution_type(self) -> ResolutionType:
        if not self.is_resolved:
            return ResolutionType.NoResolution
        if self.result_feature == self.local_feature:
            return ResolutionType.Local
        if self.result_feature == self.remote_feature:
            return ResolutionType.Remote
        return ResolutionType.Custom

    def resolve_as_local(self) -> None:
        self.is_resolved = True

        if self.conflict.has_geometry_conflict:
            self.is_geometry_changed = True

        self.changed_fields = self.conflict.conflicting_fields

        if self.local_feature is None:
            self.result_feature = None
            return

        self.result_feature = QgsFeature(self.local_feature)

    def resolve_as_remote(self) -> None:
        self.is_resolved = True

        if self.conflict.has_geometry_conflict:
            self.is_geometry_changed = True

        self.changed_fields = self.conflict.conflicting_fields

        if self.remote_feature is None:
            self.result_feature = None
            return

        self.result_feature = QgsFeature(self.remote_feature)

    def update_state(self) -> None:
        self.is_resolved = (
            len(self.conflict.conflicting_fields) == 0
            or self.changed_fields == self.conflict.conflicting_fields
        ) and (
            not self.conflict.has_geometry_conflict or self.is_geometry_changed
        )
