from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Set, Union

from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    ExistingAttachmentChange,
    FeatureChange,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentAction,
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
)
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import (
    AttachmentId,
    FeatureId,
    NgwAttachmentId,
    NgwFeatureId,
    UnsetType,
)


class VersioningConflict(ABC):
    """Define the base interface for versioning conflicts."""

    @property
    @abstractmethod
    def fid(self) -> FeatureId: ...

    @property
    @abstractmethod
    def ngw_fid(self) -> NgwFeatureId: ...


@dataclass(frozen=True)
class FeatureChangeConflict(VersioningConflict, ABC):
    """Represent a base feature-level versioning conflict."""


@dataclass(frozen=True)
class LocalFeatureDeletionConflict(FeatureChangeConflict):
    """Represent a conflict caused by local feature deletion.

    :ivar local_change: Local deletion that conflicts with remote actions.
    :ivar remote_actions: Remote actions applied to the same feature.
    """

    local_change: FeatureDeletion
    remote_actions: List[FeatureAction]

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.local_change.ngw_fid


@dataclass(frozen=True)
class RemoteFeatureDeletionConflict(FeatureChangeConflict):
    """Represent a conflict caused by remote feature deletion.

    :ivar local_changes: Local changes applied to the deleted feature.
    :ivar remote_action: Remote deletion action.
    """

    local_changes: List[FeatureChange]
    remote_action: FeatureDeleteAction

    @property
    def fid(self) -> FeatureId:
        return self.local_changes[0].fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.remote_action.fid


@dataclass(frozen=True)
class FeatureDataConflict(FeatureChangeConflict):
    """Represent conflicting feature attribute or geometry updates.

    :ivar local_change: Local feature update or restoration.
    :ivar remote_action: Remote feature update or restoration.
    :ivar conflicting_fields: Field identifiers changed on both sides.
    :ivar has_geometry_conflict: Whether local and remote geometries differ.
    """

    local_change: Union[FeatureUpdate, FeatureRestoration]
    remote_action: Union[FeatureUpdateAction, FeatureRestoreAction]

    conflicting_fields: Set[FieldId] = field(init=False)
    has_geometry_conflict: bool = field(init=False)

    def __post_init__(self) -> None:
        """Calculate derived conflict flags from local and remote changes."""

        conflicting_fields = set()
        has_geometry_conflict = False

        if not isinstance(
            self.local_change.fields, UnsetType
        ) and not isinstance(self.remote_action.fields, UnsetType):
            local_fields = set(self.local_change.fields_dict.keys())
            remote_fields = set(self.remote_action.fields_dict.keys())
            conflicting_fields = local_fields.intersection(remote_fields)

        has_geometry_conflict = (
            not isinstance(self.local_change.geometry, UnsetType)
            and not isinstance(self.remote_action.geom, UnsetType)
            and self.local_change.geometry != self.remote_action.geom
        )

        super().__setattr__("conflicting_fields", conflicting_fields)
        super().__setattr__("has_geometry_conflict", has_geometry_conflict)

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.local_change.ngw_fid


@dataclass(frozen=True)
class DescriptionConflict(VersioningConflict):
    """Represent conflicting feature description updates.

    :ivar local_change: Local description change.
    :ivar remote_action: Remote description action.
    """

    local_change: DescriptionPut
    remote_action: DescriptionPutAction

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.remote_action.fid


@dataclass(frozen=True)
class AttachmentConflict(VersioningConflict, ABC):
    """Define the base interface for attachment-level conflicts."""

    @property
    @abstractmethod
    def aid(self) -> AttachmentId: ...

    @property
    @abstractmethod
    def ngw_aid(self) -> NgwAttachmentId: ...


@dataclass(frozen=True)
class LocalAttachmentDeletionConflict(AttachmentConflict):
    """Represent a conflict caused by local attachment deletion.

    :ivar local_change: Local attachment deletion.
    :ivar remote_action: Remote action affecting the same attachment.
    """

    local_change: AttachmentDeletion
    remote_action: AttachmentAction

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.remote_action.fid

    @property
    def aid(self) -> AttachmentId:
        return self.local_change.aid

    @property
    def ngw_aid(self) -> NgwAttachmentId:
        return self.local_change.ngw_aid


@dataclass(frozen=True)
class RemoteAttachmentDeletionConflict(AttachmentConflict):
    """Represent a conflict caused by remote attachment deletion.

    :ivar local_change: Local change applied to the deleted attachment.
    :ivar remote_action: Remote attachment deletion action.
    """

    local_change: ExistingAttachmentChange
    remote_action: AttachmentDeleteAction

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.remote_action.fid

    @property
    def aid(self) -> AttachmentId:
        return self.local_change.aid

    @property
    def ngw_aid(self) -> NgwAttachmentId:
        return self.remote_action.aid


@dataclass(frozen=True)
class AttachmentDataConflict(AttachmentConflict):
    """Represent conflicting attachment metadata or file updates.

    :ivar local_change: Local attachment update or restoration.
    :ivar remote_action: Remote attachment update or restoration.
    :ivar has_name_conflict: Whether attachment names differ.
    :ivar has_description_conflict: Whether attachment descriptions differ.
    :ivar has_file_conflict: Whether both sides uploaded a new file.
    """

    local_change: Union[AttachmentUpdate, AttachmentRestoration]
    remote_action: Union[AttachmentUpdateAction, AttachmentRestoreAction]
    has_name_conflict: bool = field(init=False)
    has_description_conflict: bool = field(init=False)
    has_file_conflict: bool = field(init=False)

    def __post_init__(self) -> None:
        """Calculate derived conflict flags from local and remote changes."""

        has_name_conflict = (
            not isinstance(self.local_change.name, UnsetType)
            and not isinstance(self.remote_action.name, UnsetType)
            and self.local_change.name != self.remote_action.name
        )
        has_description_conflict = (
            not isinstance(self.local_change.description, UnsetType)
            and not isinstance(self.remote_action.description, UnsetType)
            and self.local_change.description != self.remote_action.description
        )
        has_file_conflict = (
            self.local_change.is_file_new and self.remote_action.is_file_new
        )
        super().__setattr__("has_name_conflict", has_name_conflict)
        super().__setattr__(
            "has_description_conflict", has_description_conflict
        )
        super().__setattr__("has_file_conflict", has_file_conflict)

    @property
    def fid(self) -> FeatureId:
        return self.local_change.fid

    @property
    def ngw_fid(self) -> NgwFeatureId:
        return self.remote_action.fid

    @property
    def aid(self) -> AttachmentId:
        return self.local_change.aid

    @property
    def ngw_aid(self) -> NgwAttachmentId:
        return self.local_change.ngw_aid
