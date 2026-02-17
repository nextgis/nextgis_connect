from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, List, Optional, Tuple

from nextgis_connect.detached_editing.conflicts.conflicts import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import FileObjectId, UnsetType


class ResolutionType(Enum):
    """Describe available conflict resolution strategies."""

    NoResolution = auto()
    Local = auto()
    Remote = auto()
    Custom = auto()


@dataclass
class ConflictResolution:
    """Store the selected resolution for a conflict.

    :ivar resolution_type: Selected conflict resolution strategy.
    :ivar conflict: Conflict associated with the resolution.
    """

    resolution_type: ResolutionType
    conflict: VersioningConflict


@dataclass(frozen=True)
class FeatureResolutionData:
    """Store resolved feature values.

    :ivar fields: Resolved field values keyed by field identifier.
    :ivar geom: Resolved feature geometry in string representation.
    """

    fields: List[Tuple[FieldId, Any]] = field(default_factory=list)
    geom: Optional[str] = None


@dataclass
class FeatureConflictResolution(ConflictResolution):
    """Store the resolution selected for a feature conflict.

    :ivar feature_data: Resolved feature payload.
    """

    feature_data: FeatureResolutionData = field(
        default_factory=FeatureResolutionData
    )


@dataclass
class DescriptionConflictResolution(ConflictResolution):
    """Store the resolution selected for a description conflict.

    :ivar value: Resolved description value.
    """

    value: Optional[str]


@dataclass(frozen=True)
class AttachmentResolutionData:
    """Store resolved attachment metadata.

    :ivar keyname: Resolved attachment key name.
    :ivar name: Resolved attachment display name.
    :ivar description: Resolved attachment description.
    :ivar fileobj: Resolved remote file object identifier.
    :ivar mime_type: Resolved attachment MIME type.
    """

    keyname: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    fileobj: Optional[FileObjectId] = None
    mime_type: Optional[str] = None

    @classmethod
    def from_metadata(
        cls,
        attachment: AttachmentMetadata,
    ) -> "AttachmentResolutionData":
        """Build resolution data from attachment metadata.

        :param attachment: Attachment metadata to normalize.
        :return: Resolution data populated from the attachment.
        """

        file_object_id = attachment.fileobj
        if file_object_id is None or isinstance(file_object_id, UnsetType):
            normalized_file_object_id = None
        else:
            normalized_file_object_id = FileObjectId(file_object_id)

        return cls(
            keyname=attachment.keyname,
            name=attachment.name,
            description=attachment.description,
            fileobj=normalized_file_object_id,
            mime_type=attachment.mime_type,
        )


@dataclass
class AttachmentConflictResolution(ConflictResolution):
    """Store the resolution selected for an attachment conflict.

    :ivar attachment_data: Resolved attachment payload.
    """

    attachment_data: AttachmentResolutionData = field(
        default_factory=AttachmentResolutionData
    )
