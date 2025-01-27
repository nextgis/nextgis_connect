from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from nextgis_connect.resources.ngw_field import FieldId


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

    def __str__(self) -> str:
        return str(self.value)


FeatureId = int
VersionId = int


class VersioningAction:
    def __init__(self, action: ActionType):
        self.action = action


class FeatureAction(VersioningAction):
    fid: FeatureId
    vid: Optional[VersionId]

    def __init__(
        self,
        action: ActionType,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
    ):
        super().__init__(action)
        self.fid = fid
        self.vid = vid


class DataChangeAction(FeatureAction):
    fields: List[Tuple[FieldId, Any]]
    geom: Optional[str]

    def __init__(
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

    @property
    def fields_dict(self) -> Dict[FieldId, Any]:
        return {field_data[0]: field_data[1] for field_data in self.fields}


class FeatureCreateAction(DataChangeAction):
    def __init__(
        self,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
        geom: Optional[str] = None,
        fields: Optional[List[List[Any]]] = None,
    ):
        super().__init__(ActionType.FEATURE_CREATE, fid, vid, geom, fields)


class FeatureUpdateAction(DataChangeAction):
    def __init__(
        self,
        fid: FeatureId,
        vid: Optional[VersionId] = None,
        geom: Optional[str] = None,
        fields: Optional[List[List[Any]]] = None,
    ):
        super().__init__(ActionType.FEATURE_UPDATE, fid, vid, geom, fields)


class FeatureDeleteAction(DataChangeAction):
    def __init__(self, fid: FeatureId, vid: Optional[VersionId] = None):
        super().__init__(ActionType.FEATURE_DELETE, fid, vid)


class DescriptionPutAction(FeatureAction):
    def __init__(self, fid: FeatureId, vid: Optional[VersionId], value: str):
        super().__init__(ActionType.DESCRIPTION_PUT, fid, vid)
        self.value = value


class AttachmentAction(FeatureAction):
    pass


class AttachmentCreateAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_CREATE, -1)


class AttachmentUpdateAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_UPDATE, -1)


class AttachmentDeleteAction(AttachmentAction):
    def __init__(self, **_):
        super().__init__(ActionType.ATTACHMENT_DELETE, -1)


class ContinueAction(VersioningAction):
    url: str

    def __init__(self, url: str):
        super().__init__(ActionType.CONTINUE)
        self.url = url
