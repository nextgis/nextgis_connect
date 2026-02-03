from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from qgis.core import QgsGeometry

from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import (
    FileObjectId,
    NgwAttachmentId,
    NgwFeatureId,
    Unset,
    Unsettable,
    UnsetType,
    VersionId,
)

FieldsChanges = List[Tuple[FieldId, Any]]
GeometryChange = QgsGeometry


class ActionType(str, Enum):
    CONTINUE = "continue"
    FEATURE_CREATE = "feature.create"
    FEATURE_UPDATE = "feature.update"
    FEATURE_DELETE = "feature.delete"
    FEATURE_RESTORE = "feature.restore"
    DESCRIPTION_PUT = "description.put"
    ATTACHMENT_CREATE = "attachment.create"
    ATTACHMENT_UPDATE = "attachment.update"
    ATTACHMENT_DELETE = "attachment.delete"
    ATTACHMENT_RESTORE = "attachment.restore"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class VersioningAction(ABC):
    """Base class for all versioning actions"""

    TYPE: ClassVar[ActionType]


@dataclass(frozen=True)
class ContinueAction(VersioningAction):
    """Action with url to next page with actions"""

    TYPE: ClassVar[ActionType] = ActionType.CONTINUE

    url: str


@dataclass(frozen=True)
class FeatureAction(VersioningAction):
    """Base class for feature actions"""

    fid: NgwFeatureId


@dataclass(frozen=True)
class FeatureLifecycleAction(FeatureAction):
    """Base class for feature lifecycle actions"""

    vid: VersionId
    """Feature version"""


@dataclass(frozen=True)
class FeatureDataChangeMixin:
    """Mixin for actions with fields and geometry changes"""

    fields: Unsettable[FieldsChanges] = Unset
    geom: Unsettable[GeometryChange] = Unset

    @property
    def fields_dict(self) -> Dict[FieldId, Any]:
        if isinstance(self.fields, UnsetType):
            return {}

        return {field_data[0]: field_data[1] for field_data in self.fields}


@dataclass(frozen=True)
class FeatureCreateAction(FeatureDataChangeMixin, FeatureLifecycleAction):
    """Action for feature creation"""

    TYPE: ClassVar[ActionType] = ActionType.FEATURE_CREATE


@dataclass(frozen=True)
class FeatureUpdateAction(FeatureDataChangeMixin, FeatureLifecycleAction):
    """Action for feature update"""

    TYPE: ClassVar[ActionType] = ActionType.FEATURE_UPDATE


@dataclass(frozen=True)
class FeatureDeleteAction(FeatureLifecycleAction):
    """Action for feature deletion"""

    TYPE: ClassVar[ActionType] = ActionType.FEATURE_DELETE


@dataclass(frozen=True)
class FeatureRestoreAction(FeatureDataChangeMixin, FeatureLifecycleAction):
    """Action for feature restoration"""

    TYPE: ClassVar[ActionType] = ActionType.FEATURE_RESTORE


@dataclass(frozen=True)
class ExtensionAction(FeatureAction):
    """Base class for extension actions"""


@dataclass(frozen=True)
class DescriptionPutAction(ExtensionAction):
    """Action for putting description"""

    TYPE: ClassVar[ActionType] = ActionType.DESCRIPTION_PUT

    vid: VersionId
    """Description version"""

    value: Optional[str]
    """Description value"""


@dataclass(frozen=True)
class AttachmentAction(ExtensionAction):
    """Base class for attachment actions"""

    aid: NgwAttachmentId
    """Attachment id"""

    vid: VersionId
    """Attachment version"""


@dataclass(frozen=True)
class AttachmentChangeMixin:
    """Mixin for actions with attachment changes"""

    keyname: Unsettable[str] = Unset
    name: Unsettable[Optional[str]] = Unset
    description: Unsettable[Optional[str]] = Unset
    fileobj: Unsettable[FileObjectId] = Unset
    mime_type: Unsettable[Optional[str]] = Unset


@dataclass(frozen=True)
class AttachmentCreateAction(AttachmentChangeMixin, AttachmentAction):
    """Action for attachment creation"""

    TYPE: ClassVar[ActionType] = ActionType.ATTACHMENT_CREATE


@dataclass(frozen=True)
class AttachmentUpdateAction(AttachmentChangeMixin, AttachmentAction):
    """Action for attachment update"""

    TYPE: ClassVar[ActionType] = ActionType.ATTACHMENT_UPDATE

    @property
    def is_file_new(self) -> bool:
        return bool(self.fileobj)


@dataclass(frozen=True)
class AttachmentDeleteAction(AttachmentAction):
    """Action for attachment deletion"""

    TYPE: ClassVar[ActionType] = ActionType.ATTACHMENT_DELETE


@dataclass(frozen=True)
class AttachmentRestoreAction(AttachmentChangeMixin, AttachmentAction):
    """Action for attachment restoration"""

    TYPE: ClassVar[ActionType] = ActionType.ATTACHMENT_RESTORE
