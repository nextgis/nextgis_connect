from enum import Enum
from typing import Any, List, Optional, Tuple

from nextgis_connect.resources.ngw_field import FieldId


class ActionType(str, Enum):
    CONTINUE = "continue"
    FEATURE_CREATE = "feature.create"
    FEATURE_UPDATE = "feature.update"
    FEATURE_DELETE = "feature.delete"
    DESCRIPTION_PUT = "description.put"
    ATTACHMENT_CREATE = "attachment.create"
    ATTACHMENT_UPDATE = "attachment.update"
    ATTACHMENT_DELETE = "attachment.delete"

    def __str__(self) -> str:
        return str(self.value)


FeatureId = int
VersionId = int


class VersioningAction:
    def __init__(self, action: ActionType):
        self.action = action


class DataChangeAction(VersioningAction):
    fid: Optional[FeatureId]
    vid: Optional[VersionId]

    def __init__(
        self,
        action: ActionType,
        fid: Optional[FeatureId] = None,
        vid: Optional[VersionId] = None,
    ):
        super().__init__(action)
        self.fid = fid
        self.vid = vid


class FeatureAction(DataChangeAction):
    geom: Optional[str]
    fields: List[Tuple[FieldId, Any]]

    def __init__(  # noqa: PLR0913
        self,
        action: ActionType,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
        geom: Optional[str] = None,
        fields: Optional[List[List[Any]]] = None,
    ):
        super().__init__(action, fid, vid)
        self.geom = geom
        self.fields = (
            [(field_id, value) for field_id, value in fields]
            if fields is not None
            else []
        )


class FeatureCreateAction(FeatureAction):
    def __init__(
        self,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
        geom: Optional[str] = None,
        fields: Optional[List[List[Any]]] = None,
    ):
        super().__init__(ActionType.FEATURE_CREATE, fid, vid, geom, fields)


class FeatureUpdateAction(FeatureAction):
    fid: FeatureId

    def __init__(
        self,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
        geom: Optional[str] = None,
        fields: Optional[List[List[Any]]] = None,
    ):
        super().__init__(ActionType.FEATURE_UPDATE, fid, vid, geom, fields)


class FeatureDeleteAction(FeatureAction):
    fid: FeatureId

    def __init__(self, fid: FeatureId, vid: Optional[VersionId] = None):
        super().__init__(ActionType.FEATURE_DELETE, fid, vid)


class DescriptionPutAction(DataChangeAction):
    fid: FeatureId

    def __init__(self, fid: FeatureId, vid: Optional[VersionId], value: str):
        super().__init__(ActionType.DESCRIPTION_PUT, fid, vid)
        self.value = value


class AttachmentAction(VersioningAction):
    pass


class AttachmentCreateAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_CREATE)


class AttachmentUpdateAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_UPDATE)


class AttachmentDeleteAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_DELETE)


class ContinueAction(VersioningAction):
    url: str

    def __init__(self, url: str):
        super().__init__(ActionType.CONTINUE)
        self.url = url
