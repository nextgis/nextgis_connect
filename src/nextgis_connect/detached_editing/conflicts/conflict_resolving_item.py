from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, List, Optional, Set, Union, cast

from qgis.core import QgsFeature

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentConflict,
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalFeatureDeletionConflict,
    RemoteFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import Unset, Unsettable, UnsetType


@dataclass
class BaseConflictResolvingItem(ABC):
    conflict: Any

    @property
    @abstractmethod
    def local_item(self) -> Optional[Any]: ...

    @property
    @abstractmethod
    def remote_item(self) -> Optional[Any]: ...

    @property
    @abstractmethod
    def result_item(self) -> Optional[Any]: ...

    @result_item.setter
    @abstractmethod
    def result_item(self, value: Optional[Any]) -> None: ...

    @property
    def is_resolved(self) -> bool:
        return self.result_item is not Unset and (
            self.result_item == self.local_item
            or self.result_item == self.remote_item
        )

    @property
    def resolution_type(self) -> ResolutionType:
        if not self.is_resolved:
            return ResolutionType.NoResolution

        if self.result_item == self.local_item:
            return ResolutionType.Local
        if self.result_item == self.remote_item:
            return ResolutionType.Remote
        return ResolutionType.Custom

    def resolve_as_local(self) -> None:
        self.result_item = self._copy_item(self.local_item)

    def resolve_as_remote(self) -> None:
        self.result_item = self._copy_item(self.remote_item)

    @abstractmethod
    def _copy_item(self, item: Optional[Any]) -> Optional[Any]: ...


@dataclass
class FeatureDataConflictResolvingItem(BaseConflictResolvingItem):
    conflict: FeatureDataConflict
    local_feature: Optional[QgsFeature]
    remote_feature: Optional[QgsFeature]
    result_feature: Unsettable[Optional[QgsFeature]] = Unset
    changed_fields: Set[FieldId] = field(default_factory=set, init=False)
    is_geometry_changed: bool = field(default=False, init=False)

    @property
    def local_item(self) -> Optional[QgsFeature]:
        return self.local_feature

    @property
    def remote_item(self) -> Optional[QgsFeature]:
        return self.remote_feature

    @property
    def result_item(self) -> Unsettable[Optional[QgsFeature]]:
        return self.result_feature

    @result_item.setter
    def result_item(self, value: Optional[QgsFeature]) -> None:
        self.result_feature = value

    @property
    def is_resolved(self) -> bool:
        return (
            len(self.conflict.conflicting_fields) == 0
            or self.changed_fields == self.conflict.conflicting_fields
        ) and (
            not self.conflict.has_geometry_conflict or self.is_geometry_changed
        )

    def _copy_item(self, item: Optional[QgsFeature]) -> Optional[QgsFeature]:
        if item is None:
            return None
        return QgsFeature(item)

    def resolve_as_local(self) -> None:
        super().resolve_as_local()

        if self.conflict.has_geometry_conflict:
            self.is_geometry_changed = True

        self.changed_fields = self.conflict.conflicting_fields

    def resolve_as_remote(self) -> None:
        super().resolve_as_remote()

        if self.conflict.has_geometry_conflict:
            self.is_geometry_changed = True

        self.changed_fields = self.conflict.conflicting_fields


@dataclass
class FeatureDeleteConflictResolvingItem(BaseConflictResolvingItem):
    conflict: Union[
        LocalFeatureDeletionConflict,
        RemoteFeatureDeletionConflict,
    ]

    local_feature: Optional[QgsFeature]
    remote_feature: Optional[QgsFeature]

    result_feature: Unsettable[Optional[QgsFeature]] = Unset

    local_description: Optional[str] = None
    remote_description: Optional[str] = None

    local_attachments: List[AttachmentMetadata] = field(default_factory=list)
    remote_attachments: List[AttachmentMetadata] = field(default_factory=list)

    @property
    def local_item(self) -> Optional[QgsFeature]:
        return self.local_feature

    @property
    def remote_item(self) -> Optional[QgsFeature]:
        return self.remote_feature

    @property
    def result_item(self) -> Unsettable[Optional[QgsFeature]]:
        return self.result_feature

    @result_item.setter
    def result_item(self, value: Optional[QgsFeature]) -> None:
        self.result_feature = value

    def _copy_item(self, item: Optional[QgsFeature]) -> Optional[QgsFeature]:
        if item is None:
            return None
        return QgsFeature(item)


@dataclass
class AttachmentConflictResolvingItem(BaseConflictResolvingItem):
    conflict: AttachmentConflict
    local_attachment: Optional[AttachmentMetadata]
    remote_attachment: Optional[AttachmentMetadata]
    result_attachment: Unsettable[Optional[AttachmentMetadata]] = Unset

    @property
    def local_item(self) -> Optional[AttachmentMetadata]:
        return self.local_attachment

    @property
    def remote_item(self) -> Optional[AttachmentMetadata]:
        return self.remote_attachment

    @property
    def result_item(self) -> Unsettable[Optional[AttachmentMetadata]]:
        return self.result_attachment

    @result_item.setter
    def result_item(self, value: Optional[AttachmentMetadata]) -> None:
        self.result_attachment = value

    def _copy_item(
        self, item: Optional[AttachmentMetadata]
    ) -> Optional[AttachmentMetadata]:
        if item is None:
            return None
        return replace(item)


@dataclass
class AttachmentDataConflictResolvingItem(AttachmentConflictResolvingItem):
    @property
    def is_resolved(self) -> bool:
        assert not isinstance(self.result_attachment, UnsetType)
        return Unset not in (
            self.result_attachment.name,
            self.result_attachment.description,
            self.result_attachment.fileobj,
        )

    @property
    def is_name_changed(self) -> bool:
        conflict = cast(AttachmentDataConflict, self.conflict)
        assert not isinstance(self.result_attachment, UnsetType)
        return conflict.has_name_conflict and not isinstance(
            self.result_attachment.name, UnsetType
        )

    @property
    def is_description_changed(self) -> bool:
        conflict = cast(AttachmentDataConflict, self.conflict)
        assert not isinstance(self.result_attachment, UnsetType)
        return conflict.has_description_conflict and not isinstance(
            self.result_attachment.description, UnsetType
        )

    @property
    def is_file_changed(self) -> bool:
        conflict = cast(AttachmentDataConflict, self.conflict)
        assert not isinstance(self.result_attachment, UnsetType)
        return conflict.has_file_conflict and not isinstance(
            self.result_attachment.fileobj, UnsetType
        )


@dataclass
class AttachmentDeleteConflictResolvingItem(AttachmentConflictResolvingItem):
    pass


@dataclass
class DescriptionConflictResolvingItem(BaseConflictResolvingItem):
    conflict: DescriptionConflict
    local_description: Optional[str]
    remote_description: Optional[str]
    result_description: Unsettable[Optional[str]] = field(
        default_factory=lambda: Unset, init=False
    )

    @property
    def local_item(self) -> Optional[str]:
        return self.local_description

    @property
    def remote_item(self) -> Optional[str]:
        return self.remote_description

    @property
    def result_item(self) -> Unsettable[Optional[str]]:
        return self.result_description

    @property
    def is_resolved(self) -> bool:
        return self.result_item is not Unset

    @result_item.setter
    def result_item(self, value: Optional[str]) -> None:
        self.result_description = value

    def _copy_item(self, item: Optional[str]) -> Optional[str]:
        if item is None:
            return None
        return f"{item}"
