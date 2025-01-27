from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

from nextgis_connect.detached_editing.actions import (
    ActionType,
    FeatureAction,
    FeatureId,
    VersioningAction,
)
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)


class ConflictsDeduplicator:
    __container_path: Path
    __metadata: DetachedContainerMetaData
    __both_deleted: List[FeatureId]

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata
        self.__both_deleted = []

    def deduplicate(
        self,
        remote_actions: List[VersioningAction],
        conflicts: List[VersioningConflict],
    ) -> Tuple[bool, List[FeatureAction], List[VersioningConflict]]:
        self.__both_deleted = []

        # Process conflicts and collect info for container and actions changes
        updated_conflicts = self.__process_conflicts(conflicts)
        updated_actions = self.__process_actons(remote_actions)

        # Apply changes
        self.__apply_changes_to_container()

        # If local container changed we need to update state
        need_update_state = len(self.__both_deleted) > 0 or len(conflicts) > 0

        return need_update_state, updated_actions, updated_conflicts

    def __process_conflicts(
        self, conflicts: List[VersioningConflict]
    ) -> List[VersioningConflict]:
        result = []
        for conlict in conflicts:
            processed = self.__process_conflict(conlict)
            if processed is None:
                continue
            result.append(processed)
        return result

    def __process_conflict(
        self, conflict: VersioningConflict
    ) -> Optional[VersioningConflict]:
        if (
            conflict.local.action
            == conflict.remote.action
            == ActionType.FEATURE_DELETE
        ):
            return self.__prorcess_deletion(conflict)

        return conflict

    def __prorcess_deletion(self, conflict: VersioningConflict) -> None:
        self.__both_deleted.append(conflict.local.fid)
        return None

    def __process_actons(
        self, remote_actions: List[VersioningAction]
    ) -> List[FeatureAction]:
        return [
            action
            for action in remote_actions
            if isinstance(action, FeatureAction)
            and action.fid not in self.__both_deleted
        ]

    def __apply_changes_to_container(self) -> None:
        if len(self.__both_deleted) == 0:
            return

        deleted_ngw_fids = ",".join(map(str, self.__both_deleted))

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(f"""
                DELETE FROM ngw_removed_features
                WHERE fid IN (
                    SELECT fid FROM ngw_features_metadata
                    WHERE ngw_fid IN ({deleted_ngw_fids})
                );
            """)
            connection.commit()
