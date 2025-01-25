from dataclasses import dataclass

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)


@dataclass
class ConflictResolution:
    conflict: VersioningConflict
