from itertools import chain
from typing import (
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteAttachmentDeletionConflict,
    RemoteFeatureDeletionConflict,
    VersioningConflict,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDataMixin,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    ExistingAttachmentChange,
    ExistingFeatureLifecycleChange,
    FeatureChange,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentAction,
    AttachmentChangeMixin,
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
    VersioningAction,
)
from nextgis_connect.types import NgwFeatureId, UnsetType


class ConflictsDetector:
    """Detect versioning conflicts between local and remote changes.

    Compare provided local changes with remote actions
    and return typed conflicts for intersected feature ids.
    """

    def detect(
        self,
        local_changes: Sequence[FeatureChange],
        remote_actions: Sequence[VersioningAction],
    ) -> List[VersioningConflict]:
        """Detect conflicts for provided local changes and remote actions.

        :param local_changes: Local detached container changes for comparison.
        :param remote_actions: Remote versioning actions for comparison.
        :return: Detected conflicts for intersected feature ids.
        """
        grouped_remote = self._group_remote_actions(remote_actions)
        if not grouped_remote:
            return []

        grouped_local = self._group_changes(local_changes)
        if not grouped_local:
            return []

        return list(
            chain.from_iterable(
                self._detect_conflicts_for_feature(
                    local_changes_by_feature,
                    grouped_remote[ngw_feature_id],
                )
                for ngw_feature_id, local_changes_by_feature in grouped_local.items()
                if ngw_feature_id in grouped_remote
            )
        )

    def _group_changes(
        self, changes: Sequence[FeatureChange]
    ) -> Dict[NgwFeatureId, List[FeatureChange]]:
        result: Dict[NgwFeatureId, List[FeatureChange]] = {}

        for change in changes:
            if (
                not isinstance(
                    change,
                    (
                        ExistingFeatureLifecycleChange,
                        DescriptionPut,
                        AttachmentCreation,
                        ExistingAttachmentChange,
                    ),
                )
                or change.ngw_fid is None
            ):
                continue

            result.setdefault(change.ngw_fid, []).append(change)

        return result

    def _group_remote_actions(
        self, actions: Sequence[VersioningAction]
    ) -> Dict[NgwFeatureId, List[FeatureAction]]:
        result: Dict[NgwFeatureId, List[FeatureAction]] = {}

        for action in actions:
            if not isinstance(action, FeatureAction):
                continue

            if isinstance(action, FeatureCreateAction):
                continue

            result.setdefault(action.fid, []).append(action)

        return result

    def _detect_conflicts_for_feature(
        self,
        local_changes: Sequence[FeatureChange],
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        local_feature_delete = self._feature_delete_change(local_changes)
        if local_feature_delete is not None:
            return [
                LocalFeatureDeletionConflict(
                    local_change=local_feature_delete,
                    remote_actions=list(remote_actions),
                )
            ]

        remote_feature_delete = self._feature_delete_action(remote_actions)
        if remote_feature_delete is not None:
            return [
                RemoteFeatureDeletionConflict(
                    local_changes=list(local_changes),
                    remote_action=remote_feature_delete,
                )
            ]

        result: List[VersioningConflict] = []
        for local_change in local_changes:
            result.extend(
                self._conflicts_for_local_change(local_change, remote_actions)
            )

        return result

    def _feature_delete_change(
        self, changes: Sequence[FeatureChange]
    ) -> Optional[FeatureDeletion]:
        for change in changes:
            if isinstance(change, FeatureDeletion):
                return change
        return None

    def _feature_delete_action(
        self, actions: Sequence[FeatureAction]
    ) -> Optional[FeatureDeleteAction]:
        for action in actions:
            if isinstance(action, FeatureDeleteAction):
                return action
        return None

    def _conflicts_for_local_change(
        self,
        local_change: FeatureChange,
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        if isinstance(local_change, (FeatureUpdate, FeatureRestoration)):
            return self._feature_update_conflicts(
                local_change,
                remote_actions,
            )

        if isinstance(local_change, DescriptionPut):
            return self._description_conflicts(
                local_change,
                remote_actions,
            )

        if isinstance(local_change, AttachmentDeletion):
            return self._attachment_deletion_conflicts(
                local_change,
                remote_actions,
            )

        if isinstance(local_change, (AttachmentUpdate, AttachmentRestoration)):
            return self._attachment_update_conflicts(
                local_change,
                remote_actions,
            )

        return []

    def _feature_update_conflicts(
        self,
        local_change: Union[FeatureUpdate, FeatureRestoration],
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        result: List[VersioningConflict] = []

        for remote_action in remote_actions:
            if not isinstance(
                remote_action, (FeatureUpdateAction, FeatureRestoreAction)
            ):
                continue

            if not self._has_feature_update_overlap(
                local_change,
                remote_action,
            ):
                continue

            result.append(
                FeatureDataConflict(
                    local_change=local_change,
                    remote_action=remote_action,
                )
            )

        return result

    def _description_conflicts(
        self,
        local_change: DescriptionPut,
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        result: List[VersioningConflict] = []

        for remote_action in remote_actions:
            if not isinstance(remote_action, DescriptionPutAction):
                continue

            result.append(
                DescriptionConflict(
                    local_change=local_change,
                    remote_action=remote_action,
                )
            )

        return result

    def _attachment_deletion_conflicts(
        self,
        local_change: AttachmentDeletion,
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        result: List[VersioningConflict] = []

        for remote_action in remote_actions:
            if not isinstance(remote_action, AttachmentAction):
                continue

            if local_change.ngw_aid != remote_action.aid:
                continue

            result = [
                LocalAttachmentDeletionConflict(
                    local_change=local_change,
                    remote_action=remote_action,
                )
            ]

            # We can break here, because there can't be more than one remote
            # action with the same aid
            break

        return result

    def _attachment_update_conflicts(
        self,
        local_change: Union[AttachmentUpdate, AttachmentRestoration],
        remote_actions: Sequence[FeatureAction],
    ) -> List[VersioningConflict]:
        result: List[VersioningConflict] = []

        for remote_action in remote_actions:
            if not isinstance(remote_action, AttachmentAction):
                continue

            if local_change.ngw_aid != remote_action.aid:
                continue

            if isinstance(remote_action, AttachmentDeleteAction):
                result = [
                    RemoteAttachmentDeletionConflict(
                        local_change=local_change,
                        remote_action=remote_action,
                    )
                ]
                break

            if not isinstance(
                remote_action,
                (AttachmentUpdateAction, AttachmentRestoreAction),
            ) or not self._has_attachment_update_overlap(
                local_change,
                remote_action,
            ):
                continue

            result.append(
                AttachmentDataConflict(
                    local_change=local_change,
                    remote_action=remote_action,
                )
            )

        return result

    def _has_feature_update_overlap(
        self,
        local_change: Union[FeatureUpdate, FeatureRestoration],
        remote_action: Union[FeatureUpdateAction, FeatureRestoreAction],
    ) -> bool:
        has_geometry_overlap = self._is_geometry_conflict(
            local_change,
            remote_action,
        )
        if has_geometry_overlap:
            return True

        local_fields = self._fields_changed(local_change)
        if local_fields is None:
            return False

        remote_fields = self._fields_changed(remote_action)
        if remote_fields is None:
            return False

        return len(local_fields.intersection(remote_fields)) > 0

    def _fields_changed(
        self,
        change: Union[
            FeatureUpdate,
            FeatureUpdateAction,
            FeatureRestoration,
            FeatureRestoreAction,
        ],
    ) -> Optional[Set[int]]:
        if isinstance(change.fields, UnsetType):
            return None

        return set(change.fields_dict.keys())

    def _is_geometry_conflict(
        self,
        local_change: Union[FeatureUpdate, FeatureRestoration],
        remote_action: Union[FeatureUpdateAction, FeatureRestoreAction],
    ) -> bool:
        return not isinstance(
            local_change.geometry, UnsetType
        ) and not isinstance(remote_action.geom, UnsetType)

    def _has_attachment_update_overlap(
        self,
        local_change: Union[AttachmentUpdate, AttachmentRestoration],
        remote_action: Union[
            AttachmentUpdateAction,
            AttachmentRestoreAction,
        ],
    ) -> bool:
        if local_change.is_file_new and remote_action.is_file_new:
            return True

        return any(
            self._has_unsettable_overlap(local_value, remote_value)
            for local_value, remote_value in self._attachment_fields_pairs(
                local_change,
                remote_action,
            )
        )

    def _attachment_fields_pairs(
        self,
        local_change: AttachmentDataMixin,
        remote_action: AttachmentChangeMixin,
    ) -> Iterable[Tuple[object, object]]:
        return (
            (local_change.keyname, remote_action.keyname),
            (local_change.name, remote_action.name),
            (local_change.description, remote_action.description),
            (local_change.mime_type, remote_action.mime_type),
        )

    def _has_unsettable_overlap(
        self,
        local_value: object,
        remote_value: object,
    ) -> bool:
        return not isinstance(local_value, UnsetType) and not isinstance(
            remote_value,
            UnsetType,
        )
