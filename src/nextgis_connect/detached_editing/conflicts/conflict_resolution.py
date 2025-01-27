from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, List, Optional, Tuple

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.resources.ngw_field import FieldId


class ResolutionType(Enum):
    NoResolution = auto()
    Local = auto()
    Remote = auto()
    Custom = auto()


@dataclass
class ConflictResolution:
    resolution_type: ResolutionType
    conflict: VersioningConflict

    custom_fields: List[Tuple[FieldId, Any]] = field(default_factory=list)
    custom_geom: Optional[str] = None
