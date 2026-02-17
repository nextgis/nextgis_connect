from typing import Iterable, List, Set

from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentDeleteAction,
    ContinueAction,
    FeatureDeleteAction,
    VersioningAction,
)
from nextgis_connect.types import NgwFeatureId


class ActionsFilter:
    _deleted_feature_ids: Set[NgwFeatureId]

    def __init__(self) -> None:
        self._deleted_feature_ids = set()

    def filter(
        self, actions: Iterable[VersioningAction]
    ) -> List[VersioningAction]:
        self._deleted_feature_ids = set()

        filtered_actions = []
        for action in actions:
            if self._should_keep(action):
                filtered_actions.append(action)

            self._process(action)

        return filtered_actions

    def _should_keep(self, action: VersioningAction) -> bool:
        if self._is_continue_action(action):
            return False

        if self._is_attachment_delete_after_feature_delete(action):
            return False

        return True

    def _process(self, action: VersioningAction) -> None:
        if isinstance(action, FeatureDeleteAction):
            self._deleted_feature_ids.add(action.fid)

    def _is_continue_action(self, action: VersioningAction) -> bool:
        return isinstance(action, ContinueAction)

    def _is_attachment_delete_after_feature_delete(
        self, action: VersioningAction
    ) -> bool:
        if not isinstance(action, AttachmentDeleteAction):
            return False

        return action.fid in self._deleted_feature_ids
