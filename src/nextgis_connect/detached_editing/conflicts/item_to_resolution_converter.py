from pathlib import Path
from typing import List

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    ConflictResolvingItem,
)
from nextgis_connect.detached_editing.serialization import (
    serialize_geometry,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
)


class ItemToResolutionConverter:
    __container_path: Path
    __metadata: DetachedContainerMetaData

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata

    def convert(
        self, items: List[ConflictResolvingItem]
    ) -> List[ConflictResolution]:
        resolutions = []

        for item in items:
            resolution_type = item.resolution_type
            custom_fields = []
            custom_geom = None

            if resolution_type == ResolutionType.Custom:
                for field_id in item.conflict.conflicting_fields:
                    attribute = self.__metadata.fields.find_with(
                        ngw_id=field_id
                    ).attribute
                    custom_fields.append(
                        (field_id, item.result_feature.attribute(attribute))
                    )

                custom_geom = serialize_geometry(
                    item.result_feature.geometry(),
                    self.__metadata.is_versioning_enabled,
                )

            resolutions.append(
                ConflictResolution(
                    resolution_type, item.conflict, custom_fields, custom_geom
                )
            )

        return resolutions
