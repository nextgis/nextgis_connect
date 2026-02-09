import json
from typing import Any, Dict, Iterable

from nextgis_connect.detached_editing.sync.common.changes import (
    DescriptionPut,
    FeatureChange,
    FeatureCreation,
    FeatureDeletion,
    FeatureUpdate,
    FieldsChanges,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    serialize_geometry,
)
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.exceptions import (
    SynchronizationError,
)
from nextgis_connect.types import UnsetType


class FeatureApiChangesSerializer:
    """Serialize non-versioned container changes for the feature API.

    This serializer converts container change objects into the payload
    expected by the vector layer feature API. It encodes feature
    creations, updates, deletions and description updates using the
    minimal fields required by the API.

    :ivar _metadata: Detached container metadata used to resolve
        field keynames when serializing field changes.
    """

    def __init__(self, layer_metadata: DetachedContainerMetaData):
        """Create a serializer bound to container metadata.

        :param layer_metadata: Detached container metadata used to resolve
            field keynames for serialized field dictionaries.
        """
        self._metadata = layer_metadata

    def to_json(self, changes: Iterable[FeatureChange]) -> str:
        """Serialize an iterable of changes to a JSON string.

        :param changes: Iterable of container change objects to serialize.
        :return: JSON string representing the list of serialized changes.
        """
        return json.dumps(changes, default=self.__change_serializer)

    def __change_serializer(self, change: FeatureChange):
        """Return a JSON-serializable mapping for a single change.

        :param change: Container data change object to serialize.
        :raises SynchronizationError: When no serializer exists for the
            change type.
        :return: Mapping representing the change suitable for JSON encoding.
        """
        result: Dict[str, Any] = {}

        if isinstance(change, FeatureCreation):
            if not isinstance(change.fields, UnsetType):
                result["fields"] = self.__serialize_fields(change.fields)
            if not isinstance(change.geometry, UnsetType):
                result["geom"] = serialize_geometry(
                    change.geometry, is_versioning_enabled=False
                )

        elif isinstance(change, FeatureUpdate):
            result["id"] = change.ngw_fid
            if not isinstance(change.fields, UnsetType):
                result["fields"] = self.__serialize_fields(change.fields)
            if not isinstance(change.geometry, UnsetType):
                result["geom"] = serialize_geometry(
                    change.geometry, is_versioning_enabled=False
                )

        elif isinstance(change, FeatureDeletion):
            result["id"] = change.ngw_fid

        elif isinstance(change, DescriptionPut):
            result["id"] = change.ngw_fid
            result["extensions"] = {
                "description": change.description,
            }

        else:
            class_name = change.__class__.__name__
            message = f"Object of type '{class_name}' is not serializable"
            raise SynchronizationError(message)

        return result

    def __serialize_fields(
        self, fields_changes: FieldsChanges
    ) -> Dict[str, Any]:
        """Convert internal fields changes into a keyname -> value map.

        :param fields_changes: Sequence of (field_ngw_id, value) pairs.
        :return: Dictionary mapping field keynames to values for the API.
        """
        fields = self._metadata.fields
        return {
            fields.get_with(ngw_id=field_ngw_id).keyname: value
            for field_ngw_id, value in fields_changes
        }
