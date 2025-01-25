from dataclasses import dataclass

from nextgis_connect.detached_editing.actions import (
    FeatureAction,
)


@dataclass
class VersioningConflict:
    local: FeatureAction
    remote: FeatureAction
