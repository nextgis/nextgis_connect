from itertools import chain
from pathlib import Path
from typing import Dict, List

from nextgis_connect.detached_editing.action_extractor import ActionExtractor
from nextgis_connect.detached_editing.actions import (
    ActionType,
    FeatureAction,
    FeatureId,
    FeatureUpdateAction,
    VersioningAction,
)
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData


class ConflictsDetector:
    __container_path: Path
    __metadata: DetachedContainerMetaData

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata

    def detect(
        self, remote_actions: List[VersioningAction]
    ) -> List[VersioningConflict]:
        # Check remote list
        grouped_remote = self.__group_actions(remote_actions)
        if len(grouped_remote) == 0:
            return []

        # Check local list
        extractor = ActionExtractor(self.__container_path, self.__metadata)
        local_actions = extractor.extract_all()
        grouped_local = self.__group_actions(local_actions)
        if len(grouped_local) == 0:
            return []

        # Check intersection
        intersected_fids = set(grouped_local.keys()).intersection(
            grouped_remote.keys()
        )
        if len(intersected_fids) == 0:
            return []

        # Detect conflicts
        return list(
            chain.from_iterable(
                self.__detect_conflicts(
                    grouped_local[fid], grouped_remote[fid]
                )
                for fid in intersected_fids
            )
        )

    def __group_actions(
        self, actions: List[VersioningAction]
    ) -> Dict[FeatureId, List[FeatureAction]]:
        result: Dict[FeatureId, List[FeatureAction]] = {}

        for action in actions:
            if not isinstance(action, FeatureAction):
                continue
            if action.action == ActionType.FEATURE_CREATE:
                continue

            filtered_list = result.get(action.fid)
            if filtered_list is None:
                filtered_list = []
                result[action.fid] = filtered_list

            filtered_list.append(action)

        return result

    def __detect_conflicts(
        self,
        local_actions: List[FeatureAction],
        remote_actions: List[FeatureAction],
    ) -> List[VersioningConflict]:
        result = []

        for local_action in local_actions:
            for remote_action in remote_actions:
                if not self.__is_conflict(local_action, remote_action):
                    continue
                result.append(VersioningConflict(local_action, remote_action))

        return result

    def __is_conflict(
        self, local_action: FeatureAction, remote_action: FeatureAction
    ) -> bool:
        return self.__is_delete_conflict(
            local_action, remote_action
        ) or self.__is_update_conflict(local_action, remote_action)

    def __is_delete_conflict(
        self, local_action: FeatureAction, remote_action: FeatureAction
    ) -> bool:
        return (
            local_action.action == ActionType.FEATURE_DELETE
            or remote_action.action == ActionType.FEATURE_DELETE
        )

    def __is_update_conflict(
        self, local_action: FeatureAction, remote_action: FeatureAction
    ) -> bool:
        if not isinstance(local_action, FeatureUpdateAction) or not isinstance(
            remote_action, FeatureUpdateAction
        ):
            return False

        if local_action.geom is not None and remote_action.geom is not None:
            return True

        if not local_action.fields or not remote_action.fields:
            return False

        local_fields = set(field[0] for field in local_action.fields)
        remote_fields = set(field[0] for field in remote_action.fields)

        return len(local_fields.intersection(remote_fields)) > 0
