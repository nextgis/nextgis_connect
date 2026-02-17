from dataclasses import dataclass, field
from typing import List, Optional

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    AttachmentConflictResolution,
    ConflictResolution,
    DescriptionConflictResolution,
    FeatureConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteFeatureDeletionConflict,
    VersioningConflict,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDeletion,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentDeleteAction,
    FeatureDeleteAction,
)
from nextgis_connect.types import Unset, UnsetType


@dataclass
class ConflictsAutoResolution:
    """Represent automatic conflict resolution result.

    Holds lists with conflict resolutions produced by the auto-resolver and
    conflicts that were not automatically resolved.

    :ivar resolved_conflicts: list of `ConflictResolution` objects produced by
        the auto resolver.
    :ivar remaining_conflicts: list of `VersioningConflict` objects that the
        resolver could not resolve automatically.
    """

    resolved_conflicts: List[ConflictResolution] = field(default_factory=list)
    remaining_conflicts: List[VersioningConflict] = field(default_factory=list)


class ConflictsAutoResolver:
    """Automatically resolve simple versioning conflicts.

    The resolver applies a small set of deterministic rules to reduce user
    interaction when resolving conflicts. Rules include:

    - feature deleted both locally and remotely -> mark as remote resolution
    - attachment deleted both locally and remotely -> mark as remote
    - identical description values locally and remotely -> mark as remote
    - identical fields and geometry locally and remotely -> mark as remote

    Use `resolve` to obtain a `ConflictsAutoResolution` with resolved items
    and remaining conflicts that require manual handling.
    """

    def resolve(
        self, conflicts: List[VersioningConflict]
    ) -> ConflictsAutoResolution:
        """Resolve provided conflicts using automatic rules.

        Iterate over `conflicts` and try to resolve each item according to
        built-in deterministic rules. Resolved conflicts are returned as
        `resolved_conflicts` in the result; items that could not be
        automatically resolved are returned in `remaining_conflicts`.

        :param conflicts: a list of `VersioningConflict` instances to process
        :return: a `ConflictsAutoResolution` instance with resolution results
        """
        resolved_conflicts: List[ConflictResolution] = []
        remaining_conflicts: List[VersioningConflict] = []

        for conflict in conflicts:
            resolution = self._resolve_conflict(conflict)
            if resolution is None:
                remaining_conflicts.append(conflict)
                continue

            resolved_conflicts.append(resolution)

        return ConflictsAutoResolution(
            resolved_conflicts=resolved_conflicts,
            remaining_conflicts=remaining_conflicts,
        )

    def _resolve_conflict(
        self, conflict: VersioningConflict
    ) -> Optional[ConflictResolution]:
        if self._is_feature_deleted_both_sides(conflict):
            return ConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
            )

        if self._is_local_feature_delete_vs_remote_attachment_delete(conflict):
            return ConflictResolution(
                resolution_type=ResolutionType.Local,
                conflict=conflict,
            )

        if self._is_remote_feature_delete_vs_local_attachment_delete(conflict):
            return ConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
            )

        if self._is_attachment_deleted_both_sides(conflict):
            return ConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
            )

        if self._is_same_description_update(conflict):
            assert isinstance(conflict, DescriptionConflict)
            return DescriptionConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
                value=conflict.remote_action.value,
            )

        if self._is_same_feature_data_update(conflict):
            assert isinstance(conflict, FeatureDataConflict)
            return FeatureConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
            )

        if self._is_same_attachment_data_update(conflict):
            assert isinstance(conflict, AttachmentDataConflict)
            return AttachmentConflictResolution(
                resolution_type=ResolutionType.Remote,
                conflict=conflict,
            )

        return None

    def _is_feature_deleted_both_sides(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, LocalFeatureDeletionConflict):
            return False

        return any(
            isinstance(action, FeatureDeleteAction)
            for action in conflict.remote_actions
        )

    def _is_attachment_deleted_both_sides(
        self, conflict: VersioningConflict
    ) -> bool:
        return isinstance(
            conflict,
            LocalAttachmentDeletionConflict,
        ) and isinstance(conflict.remote_action, AttachmentDeleteAction)

    def _is_local_feature_delete_vs_remote_attachment_delete(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, LocalFeatureDeletionConflict):
            return False

        if len(conflict.remote_actions) == 0:
            return False

        return all(
            isinstance(action, AttachmentDeleteAction)
            for action in conflict.remote_actions
        )

    def _is_remote_feature_delete_vs_local_attachment_delete(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, RemoteFeatureDeletionConflict):
            return False

        if len(conflict.local_changes) == 0:
            return False

        return all(
            isinstance(change, AttachmentDeletion)
            for change in conflict.local_changes
        )

    def _is_same_description_update(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, DescriptionConflict):
            return False

        return (
            conflict.local_change.description == conflict.remote_action.value
        )

    def _is_same_feature_data_update(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, FeatureDataConflict):
            return False

        has_same_fields = self._is_same_fields(
            conflict.local_change.fields,
            conflict.remote_action.fields,
        )
        has_same_geometry = self._is_same_geometry(
            conflict.local_change.geometry,
            conflict.remote_action.geom,
        )

        return has_same_fields and has_same_geometry

    def _is_same_fields(self, local_fields, remote_fields) -> bool:
        if isinstance(local_fields, UnsetType) or isinstance(
            remote_fields,
            UnsetType,
        ):
            return isinstance(local_fields, UnsetType) and isinstance(
                remote_fields,
                UnsetType,
            )

        local_fields_dict = {
            field_id: value for field_id, value in local_fields
        }
        remote_fields_dict = {
            field_id: value for field_id, value in remote_fields
        }

        return local_fields_dict == remote_fields_dict

    def _is_same_geometry(self, local_geometry, remote_geometry) -> bool:
        if local_geometry is Unset or remote_geometry is Unset:
            return local_geometry is remote_geometry

        if local_geometry is None or remote_geometry is None:
            return local_geometry is remote_geometry

        return local_geometry.equals(remote_geometry)

    def _is_same_attachment_data_update(
        self, conflict: VersioningConflict
    ) -> bool:
        if not isinstance(conflict, AttachmentDataConflict):
            return False

        if conflict.has_file_conflict:
            return False

        return all(
            self._is_same_unsettable(local_value, remote_value)
            for local_value, remote_value in (
                (
                    conflict.local_change.keyname,
                    conflict.remote_action.keyname,
                ),
                (
                    conflict.local_change.name,
                    conflict.remote_action.name,
                ),
                (
                    conflict.local_change.description,
                    conflict.remote_action.description,
                ),
                (
                    conflict.local_change.mime_type,
                    conflict.remote_action.mime_type,
                ),
            )
        )

    def _is_same_unsettable(self, local_value, remote_value) -> bool:
        if isinstance(local_value, UnsetType) or isinstance(
            remote_value,
            UnsetType,
        ):
            return isinstance(local_value, UnsetType) and isinstance(
                remote_value,
                UnsetType,
            )

        return local_value == remote_value
