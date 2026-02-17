from typing import List

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    AttachmentConflictResolution,
    AttachmentResolutionData,
    ConflictResolution,
    DescriptionConflictResolution,
    FeatureConflictResolution,
    FeatureResolutionData,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentDataConflictResolvingItem,
    BaseConflictResolvingItem,
    DescriptionConflictResolvingItem,
    FeatureDataConflictResolvingItem,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    serialize_geometry,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerContext,
)
from nextgis_connect.types import UnsetType


class ItemToResolutionConverter:
    _context: DetachedContainerContext

    def __init__(self, context: DetachedContainerContext) -> None:
        self._context = context

    def convert(
        self, items: List[BaseConflictResolvingItem]
    ) -> List[ConflictResolution]:
        return [self._convert_item(item) for item in items]

    def _convert_item(
        self,
        item: BaseConflictResolvingItem,
    ) -> ConflictResolution:
        if isinstance(item, FeatureDataConflictResolvingItem):
            return self._convert_feature_data_item(item)

        if isinstance(item, DescriptionConflictResolvingItem):
            return self._convert_description_item(item)

        if isinstance(item, AttachmentDataConflictResolvingItem):
            return self._convert_attachment_data_item(item)

        return ConflictResolution(
            resolution_type=item.resolution_type,
            conflict=item.conflict,
        )

    def _convert_feature_data_item(
        self,
        item: FeatureDataConflictResolvingItem,
    ) -> FeatureConflictResolution:
        result_feature = item.result_feature
        assert not isinstance(result_feature, UnsetType)
        assert result_feature is not None

        fields = []
        for field in self._context.metadata.fields:
            fields.append(
                (field.ngw_id, result_feature.attribute(field.attribute))
            )

        return FeatureConflictResolution(
            resolution_type=item.resolution_type,
            conflict=item.conflict,
            feature_data=FeatureResolutionData(
                fields=fields,
                geom=serialize_geometry(
                    result_feature.geometry(),
                    self._context.metadata.is_versioning_enabled,
                ),
            ),
        )

    def _convert_description_item(
        self,
        item: DescriptionConflictResolvingItem,
    ) -> DescriptionConflictResolution:
        result_description = item.result_description
        assert not isinstance(result_description, UnsetType)

        return DescriptionConflictResolution(
            resolution_type=item.resolution_type,
            conflict=item.conflict,
            value=result_description,
        )

    def _convert_attachment_data_item(
        self,
        item: AttachmentDataConflictResolvingItem,
    ) -> AttachmentConflictResolution:
        result_attachment = item.result_attachment
        assert not isinstance(result_attachment, UnsetType)
        assert result_attachment is not None

        return AttachmentConflictResolution(
            resolution_type=item.resolution_type,
            conflict=item.conflict,
            attachment_data=AttachmentResolutionData.from_metadata(
                result_attachment
            ),
        )
