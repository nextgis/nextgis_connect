import json
from typing import Any, Dict, Iterable, Union

from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentSource,
    AttachmentUpdate,
    DescriptionPut,
    FeatureChange,
    FeatureCreation,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    serialize_geometry,
)
from nextgis_connect.detached_editing.sync.versioned.actions import ActionType
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.exceptions import (
    SynchronizationError,
)
from nextgis_connect.types import UnsetType


class VersionedChangesSerializer:
    """Serialize versioned container changes into JSON.

    This serializer converts container change objects into a JSON
    representation suitable for sending to a versioned server API. The
    serializer encodes action types, feature ids, versions and common
    payload fields for features, descriptions and attachments.

    :ivar _metadata: Detached container metadata used to resolve
        field and resource information.
    :ivar _serializer_by_type: Internal mapping from change classes to
        their serializer callables.
    """

    _metadata: DetachedContainerMetaData

    def __init__(self, layer_metadata: DetachedContainerMetaData):
        """Create a serializer bound to container metadata.

        :param layer_metadata: Detached container metadata used to resolve
            field and resource information when serializing changes.
        """
        self._metadata = layer_metadata
        self._serializer_by_type = self.__build_serializer_by_type()

    def to_json(
        self,
        changes: Iterable[FeatureChange],
        *,
        last_action_number: int = 0,
    ) -> str:
        """Serialize an iterable of changes to a JSON string.

        :param changes: Iterable of container change objects to serialize.
        :param last_action_number: Start index for numbering actions when
            embedding the action number into the serialized container.
        :return: JSON string representing the numbered change container.
        """
        changes_container = [
            (number, change)
            for number, change in enumerate(changes, start=last_action_number)
        ]
        return json.dumps(
            changes_container, default=self.__change_to_json_serializer
        )

    def __change_to_json_serializer(self, change: FeatureChange):
        """Return a JSON-serializable mapping for a single change.

        :param change: Container data change object to serialize.
        :raises SynchronizationError: When no serializer exists for the
            change type.
        :return: Mapping representing the change suitable for JSON encoding.
        """
        serializer_method = self._serializer_by_type.get(type(change))
        if serializer_method is None:
            class_name = change.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            raise SynchronizationError(message)

        return serializer_method(change)

    def __build_serializer_by_type(self):
        """Build and return the mapping of change types to serializer callables.

        :return: Dict mapping change classes to bound serializer methods.
        """
        return {
            FeatureCreation: self.__serialize_feature_creation,
            FeatureUpdate: self.__serialize_feature_update,
            FeatureRestoration: self.__serialize_feature_restoration,
            FeatureDeletion: self.__serialize_feature_deletion,
            DescriptionPut: self.__serialize_description_put,
            AttachmentCreation: self.__serialize_attachment_creation,
            AttachmentUpdate: self.__serialize_attachment_update,
            AttachmentDeletion: self.__serialize_attachment_deletion,
            AttachmentRestoration: self.__serialize_attachment_restoration,
            AttachmentSource: self.__serialize_attachment_source,
        }

    def __serialize_feature_creation(
        self, change: FeatureCreation
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.FEATURE_CREATE),
        }
        self.__add_feature_common_fields(result, change)
        return result

    def __serialize_feature_update(
        self, change: FeatureUpdate
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.FEATURE_UPDATE),
            "fid": change.ngw_fid,
            "vid": change.version,
        }
        self.__add_feature_common_fields(result, change)
        return result

    def __serialize_feature_restoration(
        self, change: FeatureRestoration
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.FEATURE_RESTORE),
            "fid": change.ngw_fid,
            "vid": change.version,
        }
        self.__add_feature_common_fields(result, change)
        return result

    def __serialize_feature_deletion(
        self, change: FeatureDeletion
    ) -> Dict[str, Any]:
        return {
            "action": str(ActionType.FEATURE_DELETE),
            "fid": change.ngw_fid,
            "vid": change.version,
        }

    def __serialize_description_put(
        self, change: DescriptionPut
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.DESCRIPTION_PUT),
            "fid": change.ngw_fid,
            "value": change.description,
        }
        if not isinstance(change.version, UnsetType):
            result["vid"] = change.version
        return result

    def __serialize_attachment_creation(
        self, change: AttachmentCreation
    ) -> Dict[str, Any]:
        assert not isinstance(change.source, UnsetType)

        result = {
            "action": str(ActionType.ATTACHMENT_CREATE),
            "fid": change.ngw_fid,
            "source": change.source,
        }
        self.__add_attachment_common_fields(result, change)
        return result

    def __serialize_attachment_update(
        self, change: AttachmentUpdate
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.ATTACHMENT_UPDATE),
            "fid": change.ngw_fid,
            "aid": change.ngw_aid,
            "vid": change.version,
        }

        if not isinstance(change.source, UnsetType):
            result["source"] = change.source

        self.__add_attachment_common_fields(result, change)
        return result

    def __serialize_attachment_deletion(
        self, change: AttachmentDeletion
    ) -> Dict[str, Any]:
        return {
            "action": str(ActionType.ATTACHMENT_DELETE),
            "fid": change.ngw_fid,
            "aid": change.ngw_aid,
            "vid": change.version,
        }

    def __serialize_attachment_restoration(
        self, change: AttachmentRestoration
    ) -> Dict[str, Any]:
        result = {
            "action": str(ActionType.ATTACHMENT_RESTORE),
            "fid": change.ngw_fid,
            "aid": change.ngw_aid,
            "vid": change.version,
        }

        if not isinstance(change.source, UnsetType):
            result["source"] = change.source

        self.__add_attachment_common_fields(result, change)
        return result

    def __serialize_attachment_source(
        self, source: AttachmentSource
    ) -> Dict[str, Any]:
        return {"type": source.source_type, **source.data}

    def __add_feature_common_fields(
        self,
        result: Dict[str, Any],
        change: Union[
            FeatureCreation,
            FeatureUpdate,
            FeatureRestoration,
        ],
    ) -> None:
        """Add common feature payload fields to the serialized map.

        :param result: Mapping to update with feature fields.
        :param change: Feature-related change instance to inspect.
        """
        if not isinstance(change.fields, UnsetType):
            result["fields"] = change.fields
        if not isinstance(change.geometry, UnsetType):
            result["geom"] = serialize_geometry(
                change.geometry, is_versioning_enabled=True
            )

    def __add_attachment_common_fields(
        self,
        result: Dict[str, Any],
        change: Union[
            AttachmentCreation,
            AttachmentUpdate,
            AttachmentRestoration,
        ],
    ) -> None:
        """Add common attachment payload fields to the serialized map.

        :param result: Mapping to update with attachment fields.
        :param change: Attachment-related change instance to inspect.
        """
        if not isinstance(change.name, UnsetType):
            result["name"] = change.name
        if not isinstance(change.description, UnsetType):
            result["description"] = change.description
        if not isinstance(change.keyname, UnsetType):
            result["keyname"] = change.keyname
        if not isinstance(change.mime_type, UnsetType):
            result["mime_type"] = change.mime_type
