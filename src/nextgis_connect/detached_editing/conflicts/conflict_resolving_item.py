from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsFeature

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)


@dataclass
class ConflictResolvingItem:
    conflict: VersioningConflict
    local_feature: Optional[QgsFeature]
    remote_feature: Optional[QgsFeature]
    result_feature: Optional[QgsFeature]
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
        self.result_feature = self.local_feature
        self.is_resolved = True

    def resolve_as_remote(self) -> None:
        self.result_feature = self.remote_feature
        self.is_resolved = True
