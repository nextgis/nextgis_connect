import json
from typing import Any, ClassVar, Dict, Iterable, List, Type, Union

from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.exceptions import DetachedEditingError, ErrorCode

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

    def __init__(self, layer_metadata: DetachedContainerMetaData) -> None:
        self.__layer_metadata = layer_metadata

    def to_json(
        self, actions: Iterable[VersioningAction], last_action_number: int = 0
    ) -> str:
        action_converter = (
            self.__convert_versioning_action
            if self.__layer_metadata.is_versioning_enabled
            else self.__convert_action
        )

        actions_container = actions

        if self.__layer_metadata.is_versioning_enabled:
            actions_container = list(
                (number, action)
                for number, action in enumerate(
                    actions, start=last_action_number
                )
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

    def __convert_versioning_action(self, action: VersioningAction) -> Any:
        if not isinstance(action, DataChangeAction):
            if isinstance(action, (QDate, QTime, QDateTime)):
                return self.__serialize_date_and_time(action)

            class_name = action.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            code = ErrorCode.SynchronizationError
            raise DetachedEditingError(message, code=code)

        def is_not_empty(value) -> bool:
            if isinstance(value, list):
                return len(value) > 0
            return value is not None

        result = {
            key: (value if value != "" else None)
            for key, value in action.__dict__.items()
            if is_not_empty(value)
        }

        if action.action == ActionType.FEATURE_CREATE:
            result.pop("fid", None)
            result.pop("vid", None)

        return result

    def __convert_action(self, action: VersioningAction) -> Any:
        if not isinstance(action, FeatureAction):
            if isinstance(action, (QDate, QTime, QDateTime)):
                return self.__serialize_date_and_time(action)

            class_name = action.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            code = ErrorCode.SynchronizationError
            raise DetachedEditingError(message, code=code)

        result: Dict[str, Any] = {}

        if not isinstance(action, FeatureCreateAction):
            result["id"] = action.fid

        if isinstance(action, FeatureAction):
            fields = self.__layer_metadata.fields
            fields_values = {
                fields.get_with(ngw_id=field_ngw_id).keyname: value
                for field_ngw_id, value in action.fields
            }
            if len(fields_values) > 0:
                result["fields"] = fields_values
            if action.geom is not None:
                result["geom"] = action.geom if action.geom != "" else None

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

    def __serialize_date_and_time(
        self, date_object: Union[QDateTime, QDate, QTime]
    ) -> Any:
        date = None
        time = None
        if isinstance(date_object, QDateTime):
            date = date_object.date()
            time = date_object.time()
        elif isinstance(date_object, QDate):
            date = date_object
        elif isinstance(date_object, QTime):
            time = date_object

        result = {}
        if date is not None:
            result["year"] = date.year()
            result["month"] = date.month()
            result["day"] = date.day()

        if time is not None:
            result["hour"] = time.hour()
            result["minute"] = time.minute()
            result["second"] = time.second()

        # return date_object.toString(Qt.DateFormat.ISODate)

        return result
