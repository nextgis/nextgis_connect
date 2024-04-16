import json
from typing import Any, ClassVar, Dict, Iterable, List, Type, Union

from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.exceptions import DetachedEditingError, ErrorCode
from nextgis_connect.resources.ngw_field import FieldId, NgwField

from .actions import (
    ActionType,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    ContinueAction,
    DataChangeAction,
    DescriptionPutAction,
    FeatureAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureUpdateAction,
    VersioningAction,
)


class ActionSerializer:
    action_classes: ClassVar[Dict[str, Type[VersioningAction]]] = {
        ActionType.CONTINUE: ContinueAction,
        ActionType.FEATURE_CREATE: FeatureCreateAction,
        ActionType.FEATURE_UPDATE: FeatureUpdateAction,
        ActionType.FEATURE_DELETE: FeatureDeleteAction,
        ActionType.DESCRIPTION_PUT: DescriptionPutAction,
        ActionType.ATTACHMENT_CREATE: AttachmentCreateAction,
        ActionType.ATTACHMENT_UPDATE: AttachmentUpdateAction,
        ActionType.ATTACHMENT_DELETE: AttachmentDeleteAction,
    }

    __layer_metadata: DetachedContainerMetaData
    __fields: Dict[FieldId, NgwField]

    def __init__(self, layer_metadata: DetachedContainerMetaData) -> None:
        self.__layer_metadata = layer_metadata
        self.__fields = {}

    def to_json(self, actions: Iterable[VersioningAction]) -> str:
        if len(self.__fields) == 0:
            self.__fields = {
                field.ngw_id: field for field in self.__layer_metadata.fields
            }

        action_converter = (
            self.__convert_versioning_action
            if self.__layer_metadata.is_versioning_enabled
            else self.__convert_action
        )

        actions_container = actions

        if self.__layer_metadata.is_versioning_enabled:
            actions_container = list(
                (number, action) for number, action in enumerate(actions)
            )

        return json.dumps(actions_container, default=action_converter)

    def from_json(
        self,
        json_data: Union[str, Iterable[Dict[str, Any]]],
    ) -> List[VersioningAction]:
        dicts_list = (
            json.loads(json_data) if isinstance(json_data, str) else json_data
        )

        if not self.__layer_metadata.is_versioning_enabled:
            return self.__deserialize_extensions(dicts_list)

        return self.__deserialize_actions(dicts_list)

    def __convert_versioning_action(
        self, action: VersioningAction
    ) -> Dict[str, Any]:
        if not isinstance(action, DataChangeAction):
            class_name = action.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            code = ErrorCode.SynchronizationError
            raise DetachedEditingError(message, code=code)

        result = {
            key: value for key, value in action.__dict__.items() if value
        }

        if isinstance(action, FeatureCreateAction):
            result.pop("fid")
            result.pop("vid", None)

        return result

    def __convert_action(self, action: VersioningAction) -> Dict[str, Any]:
        if not isinstance(action, FeatureAction):
            class_name = action.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            code = ErrorCode.SynchronizationError
            raise DetachedEditingError(message, code=code)

        result: Dict[str, Any] = {}

        if not isinstance(action, FeatureCreateAction):
            result["id"] = action.fid

        if isinstance(action, FeatureAction):
            fields = {
                self.__fields[field_id].keyname: value
                for field_id, value in action.fields
            }
            if len(fields) > 0:
                result["fields"] = fields
            if action.geom is not None:
                result["geom"] = action.geom

        return result

    def __deserialize_extensions(
        self, features: Iterable[Dict[str, Any]]
    ) -> List[VersioningAction]:
        result = []

        for feature in features:
            ngw_fid = feature["id"]
            extensions = feature.get("extensions")

            if not extensions:
                continue

            description = extensions.get("description")
            if description is not None:
                result.append(DescriptionPutAction(ngw_fid, None, description))

            attachments = extensions.get("attachment")
            if attachments is None:
                attachments = []

            # for attachment in attachments:
            #     pass

        return result

    def __deserialize_actions(
        self, actions: Iterable[Dict[str, Any]]
    ) -> List[VersioningAction]:
        def json_to_action(action_dict: Dict[str, Any]) -> VersioningAction:
            action_type = action_dict.pop("action")
            action_class = ActionSerializer.action_classes[action_type]
            return action_class(**action_dict)

        return [json_to_action(item.copy()) for item in actions]
