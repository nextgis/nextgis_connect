from typing import TypeVar, Union

from nextgis_connect.compat import QgsFeatureId

FeatureId = QgsFeatureId
FieldId = int
AttachmentId = int

NgwFeatureId = int
NgwFieldId = int
NgwAttachmentId = int

VersionId = int

FileObjectId = int

WktString = str
Wkb64String = str


class UnsetType:
    """Represent an unset value."""

    def __repr__(self) -> str:
        return "<UNSET>"

    def __bool__(self):
        return False


Unset = UnsetType()

T = TypeVar("T")
Unsettable = Union[T, UnsetType]
