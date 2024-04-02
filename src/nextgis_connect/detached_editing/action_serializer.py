import json
from typing import Any, ClassVar, Dict, Iterable, List, Type, Union

from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
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
        if not self.__layer_metadata.is_versioning_enabled:
            raise NotImplementedError

        actions_list = (
            json.loads(json_data) if isinstance(json_data, str) else json_data
        )

        def json_to_action(action_dict: Dict[str, Any]) -> VersioningAction:
            action_type = action_dict.pop("action")
            action_class = ActionSerializer.action_classes[action_type]
            return action_class(**action_dict)

        return [json_to_action(item.copy()) for item in actions_list]

    def __convert_versioning_action(
        self, action: VersioningAction
    ) -> Dict[str, Any]:
        if not isinstance(action, DataChangeAction):
            class_name = action.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            raise TypeError(message)

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
            raise TypeError(message)

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
