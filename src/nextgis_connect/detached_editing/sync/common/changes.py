from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsGeometry

from nextgis_connect.types import (
    AttachmentId,
    FeatureId,
    FieldId,
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


@dataclass()
class FeatureChange:
    """Base class for feature changes"""

    fid: FeatureId
    """Feature id in detached container"""


@dataclass()
class FeatureLifecycleChange(FeatureChange):
    """Base class for feature lifecycle changes"""


@dataclass()
class ExistingFeatureLifecycleChange(FeatureLifecycleChange):
    """Base class for feature lifecycle changes with existed features"""

    ngw_fid: NgwFeatureId
    """Feature id in NextGIS Web"""
    version: Unsettable[VersionId] = Unset
    """Feature version at the moment of last synchronization"""


@dataclass()
class FeatureDataMixin:
    """Mixin for changes with fields and geometry changes"""

    fields: Unsettable[FieldsChanges] = Unset
    geometry: Unsettable[GeometryChange] = Unset

    @property
    def fields_dict(self) -> Dict[FieldId, Any]:
        if isinstance(self.fields, UnsetType):
            return {}

        return {field_data[0]: field_data[1] for field_data in self.fields}


@dataclass()
class FeatureCreation(FeatureDataMixin, FeatureLifecycleChange):
    """Feature creation representation"""


@dataclass()
class FeatureUpdate(FeatureDataMixin, ExistingFeatureLifecycleChange):
    """Feature update representation"""


@dataclass()
class FeatureDeletion(ExistingFeatureLifecycleChange):
    """Feature deletion representation"""


@dataclass()
class FeatureRestoration(FeatureDataMixin, ExistingFeatureLifecycleChange):
    """Feature restoration representation"""


@dataclass()
class ExtensionChange(FeatureChange):
    """Base class for extension changes"""


@dataclass()
class DescriptionPut(ExtensionChange):
    """Description put representation"""

    ngw_fid: Optional[NgwFeatureId] = None
    """Feature id in NextGIS Web. None for new features"""
    version: Unsettable[VersionId] = Unset
    """Description version at the moment of last synchronization"""
    description: Optional[str] = None
    """New description value"""

    @property
    def is_feature_new(self) -> bool:
        return self.ngw_fid is None


@dataclass()
class AttachmentSource:
    """Attachment source data"""

    source_type: str
    """Source type, e.g. 'file_upload'"""
    data: Dict[str, Any]
    """Source data"""


@dataclass()
class AttachmentChange(ExtensionChange):
    """Base class for attachment changes"""


@dataclass()
class ExistingAttachmentChange(AttachmentChange):
    """Base class for attachment changes"""

    ngw_fid: NgwFeatureId
    """Feature id in NextGIS Web. None for new features"""
    aid: AttachmentId
    """Attachment id in detached container"""
    ngw_aid: NgwAttachmentId
    """Attachment id in NextGIS Web"""
    version: Unsettable[VersionId] = Unset
    """Attachment version at the moment of last synchronization"""
    fileobj: Optional[FileObjectId] = None
    """File object id"""

    @property
    def is_file_new(self) -> bool:
        return self.fileobj is None


@dataclass()
class AttachmentDataMixin:
    """Mixin for changes with attachment data"""

    source: Unsettable[AttachmentSource] = Unset
    name: Unsettable[str] = Unset
    description: Unsettable[str] = Unset
    keyname: Unsettable[str] = Unset
    mime_type: Unsettable[str] = Unset


@dataclass()
class _AttachmentCreation(AttachmentChange):
    """Attachment base class for creation"""

    fid: FeatureId
    """Feature id in detached container"""
    aid: AttachmentId
    """Attachment id in detached container"""
    ngw_fid: Optional[NgwFeatureId]
    """Feature id in NextGIS Web. None for new features"""

    @property
    def is_feature_new(self) -> bool:
        return self.ngw_fid is None


@dataclass()
class AttachmentCreation(AttachmentDataMixin, _AttachmentCreation):
    """Attachment creation representation"""


@dataclass()
class AttachmentUpdate(AttachmentDataMixin, ExistingAttachmentChange):
    """Attachment update representation"""


@dataclass()
class AttachmentDeletion(ExistingAttachmentChange):
    """Attachment deletion representation"""


@dataclass()
class AttachmentRestoration(AttachmentDataMixin, ExistingAttachmentChange):
    """Attachment restoration representation"""
