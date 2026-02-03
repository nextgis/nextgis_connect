from typing import Any, Sequence, Type, Union, cast

from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentUpdate,
    DescriptionPut,
    FeatureChange,
    FeatureCreation,
    FeatureDeletion,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.common.changes_applier import (
    ChangesApplier,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerContext,
    FeatureMetadata,
)
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.types import Unset


class FeatureApiChangesApplier(ChangesApplier):
    def __init__(self, container_context: DetachedContainerContext) -> None:
        super().__init__(container_context)

    def apply(
        self,
        changes: Union[FeatureChange, Sequence[FeatureChange]],
        operation_result: Any = None,
    ) -> None:
        changes_list = changes
        operation_result_list = operation_result

        if not isinstance(changes, (list, tuple)):
            changes_list = [changes]
        if not isinstance(operation_result, (list, tuple)):
            operation_result_list = [operation_result]

        changes_list = cast(Sequence[FeatureChange], changes_list)

        if len(changes_list) == 0:
            return

        first_action_type = type(changes_list[0])
        if not all(
            isinstance(change, first_action_type) for change in changes_list
        ):
            raise SynchronizationError("Action types should be the same")

        self.__apply(first_action_type, changes_list, operation_result_list)

    def __apply(
        self,
        changes_type: Type[FeatureChange],
        changes: Sequence[FeatureChange],
        operation_result: Any,
    ) -> None:
        VERSION_STUB = -1

        if changes_type == FeatureCreation:
            assert operation_result is not None
            creation_changes = cast(Sequence[FeatureCreation], changes)
            added_features = [
                FeatureMetadata(
                    fid=change.fid,
                    ngw_fid=change_result["id"],
                )
                for change, change_result in zip(
                    creation_changes, operation_result
                )
            ]
            self._process_added_features(added_features)

        elif changes_type == FeatureDeletion:
            deletion_changes = cast(Sequence[FeatureDeletion], changes)
            self._process_deleted_features(deletion_changes)

        elif changes_type == FeatureUpdate:
            update_changes = cast(Sequence[FeatureUpdate], changes)
            self._process_updated_features(update_changes)

        elif changes_type == DescriptionPut:
            description_changes = cast(Sequence[DescriptionPut], changes)
            self._process_updated_descriptions(description_changes)

        elif changes_type == AttachmentCreation:
            assert operation_result is not None
            creation_changes = cast(Sequence[AttachmentCreation], changes)
            added_attachments = [
                AttachmentMetadata(
                    fid=change.fid,
                    ngw_fid=change.ngw_fid,
                    aid=change.aid,
                    ngw_aid=change_result["id"],
                    version=VERSION_STUB,
                )
                for change, change_result in zip(
                    creation_changes, operation_result
                )
            ]
            self._process_created_attachments(added_attachments)

        elif changes_type == AttachmentUpdate:
            update_changes = cast(Sequence[AttachmentUpdate], changes)
            updated_attachments = [
                AttachmentMetadata(
                    fid=change.ngw_fid,
                    aid=change.aid,
                    ngw_fid=change.ngw_fid,
                    ngw_aid=change.ngw_aid,
                    version=VERSION_STUB if change.is_file_new else Unset,
                )
                for change in update_changes
            ]
            self._process_updated_attachments(updated_attachments)

        elif changes_type == AttachmentDeletion:
            deletion_changes = cast(Sequence[AttachmentDeletion], changes)
            self._process_deleted_attachments(deletion_changes)

        else:
            raise SynchronizationError("Unknown change type")
