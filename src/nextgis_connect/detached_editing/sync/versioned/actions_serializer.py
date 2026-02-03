import json
from typing import Any, ClassVar, Dict, Iterable, List, Type, Union

from nextgis_connect.detached_editing.sync.common.serialization import (
    deserialize_geometry,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    ActionType,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    ContinueAction,
    DescriptionPutAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
    VersioningAction,
)
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.exceptions import SerializationError


class ActionSerializer:
    """Deserialize versioning actions.

    Convert persisted JSON action payloads into concrete `VersioningAction`
    instances, resolving geometry.

    :ivar action_classes: Mapping from action type strings to their corresponding
        `VersioningAction` classes used for deserialization.
    :ivar _metadata: Detached container metadata used to resolve field and resource
        information when deserializing actions.
    """

    action_classes: ClassVar[Dict[str, Type[VersioningAction]]] = {
        ActionType.CONTINUE: ContinueAction,
        ActionType.FEATURE_CREATE: FeatureCreateAction,
        ActionType.FEATURE_UPDATE: FeatureUpdateAction,
        ActionType.FEATURE_DELETE: FeatureDeleteAction,
        ActionType.FEATURE_RESTORE: FeatureRestoreAction,
        ActionType.DESCRIPTION_PUT: DescriptionPutAction,
        ActionType.ATTACHMENT_CREATE: AttachmentCreateAction,
        ActionType.ATTACHMENT_UPDATE: AttachmentUpdateAction,
        ActionType.ATTACHMENT_DELETE: AttachmentDeleteAction,
        ActionType.ATTACHMENT_RESTORE: AttachmentRestoreAction,
    }

    _metadata: DetachedContainerMetaData

    def __init__(self, layer_metadata: DetachedContainerMetaData) -> None:
        """Create a serializer bound to container metadata.

        :param layer_metadata: Detached container metadata used to resolve
            field and resource information when serializing changes.
        """
        self._metadata = layer_metadata

    def from_json(
        self,
        json_data: Union[str, Iterable[Dict[str, Any]]],
    ) -> List[VersioningAction]:
        """Deserialize actions from a JSON string or an iterable of dicts.

        :param json_data: JSON string or iterable of action dictionaries.
        :return: Deserialized action instances.
        :raises KeyError: If an action type is not recognized.
        :raises json.JSONDecodeError: If the input string is not valid JSON.
        """
        try:
            dicts_list = (
                json.loads(json_data)
                if isinstance(json_data, str)
                else json_data
            )

            return self.__deserialize_actions(dicts_list)

        except SerializationError:
            raise

        except Exception as error:
            raise SerializationError from error

    def __deserialize_actions(
        self, actions_json: Iterable[Dict[str, Any]]
    ) -> List[VersioningAction]:
        def json_to_action(action_dict: Dict[str, Any]) -> VersioningAction:
            action_type = action_dict.pop("action", None)
            action_class = ActionSerializer.action_classes[action_type]

            geom = action_dict.pop("geom", None)
            if bool(geom):
                action_dict["geom"] = deserialize_geometry(
                    geom, is_versioning_enabled=True
                )

            return action_class(**action_dict)

        return [json_to_action(action_json) for action_json in actions_json]
