# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import json
from dataclasses import dataclass
from typing import ClassVar, Dict, List, Optional, Sequence, Type

from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureChange,
    FeatureCreation,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions import (
    ActionType,
)
from nextgis_connect.platform.qgis.errors import SynchronizationError
from nextgis_connect.shared.types import FileObjectId


@dataclass(frozen=True)
class TransactionChange:
    action: ActionType
    local_id: int
    fileobj: Optional[FileObjectId] = None
    file_changed: bool = False


class TransactionChangesSerializer:
    _ACTIONS: ClassVar[Dict[Type[FeatureChange], ActionType]] = {
        FeatureCreation: ActionType.FEATURE_CREATE,
        FeatureUpdate: ActionType.FEATURE_UPDATE,
        FeatureDeletion: ActionType.FEATURE_DELETE,
        FeatureRestoration: ActionType.FEATURE_RESTORE,
        DescriptionPut: ActionType.DESCRIPTION_PUT,
        AttachmentCreation: ActionType.ATTACHMENT_CREATE,
        AttachmentUpdate: ActionType.ATTACHMENT_UPDATE,
        AttachmentDeletion: ActionType.ATTACHMENT_DELETE,
        AttachmentRestoration: ActionType.ATTACHMENT_RESTORE,
    }
    _FILE_UPDATE_ACTIONS = (
        ActionType.ATTACHMENT_UPDATE,
        ActionType.ATTACHMENT_RESTORE,
    )

    def from_changes(
        self, changes: Sequence[FeatureChange]
    ) -> List[TransactionChange]:
        return [self._pack(change) for change in changes]

    def to_json(self, changes: Sequence[TransactionChange]) -> str:
        records = []
        for change in changes:
            record: Dict[str, object] = {
                "action": change.action.value,
                "id": change.local_id,
            }
            if change.action == ActionType.ATTACHMENT_DELETE:
                record["fileobj"] = change.fileobj
            if change.action in self._FILE_UPDATE_ACTIONS:
                record["file_changed"] = change.file_changed
            records.append(record)
        return json.dumps(records)

    def from_json(self, payload: str) -> List[TransactionChange]:
        try:
            records = json.loads(payload)
            if not isinstance(records, list) or not records:
                raise ValueError("Expected a non-empty operation list")
            return [self._unpack(record) for record in records]
        except (KeyError, TypeError, ValueError) as error:
            raise SynchronizationError(
                "Invalid transaction recovery data"
            ) from error

    def _pack(self, change: FeatureChange) -> TransactionChange:
        action = self._ACTIONS.get(type(change))
        if action is None:
            raise SynchronizationError(
                f"Unsupported change: {type(change).__name__}"
            )

        local_id = change.fid
        if isinstance(
            change,
            (
                AttachmentCreation,
                AttachmentUpdate,
                AttachmentDeletion,
                AttachmentRestoration,
            ),
        ):
            local_id = change.aid
        fileobj = (
            change.fileobj if isinstance(change, AttachmentDeletion) else None
        )
        file_changed = isinstance(change, AttachmentCreation)
        if isinstance(change, (AttachmentUpdate, AttachmentRestoration)):
            file_changed = change.is_file_new
        return TransactionChange(action, local_id, fileobj, file_changed)

    def _unpack(self, record: object) -> TransactionChange:
        if not isinstance(record, dict) or type(record.get("id")) is not int:
            raise ValueError("Invalid local operation id")
        action = ActionType(record["action"])
        if action not in self._ACTIONS.values():
            raise ValueError("Unsupported transaction action")
        fileobj = (
            record["fileobj"]
            if action == ActionType.ATTACHMENT_DELETE
            else None
        )
        if fileobj is not None and type(fileobj) is not int:
            raise ValueError("Invalid file object id")
        file_changed = action == ActionType.ATTACHMENT_CREATE
        if action in self._FILE_UPDATE_ACTIONS:
            file_changed = record["file_changed"]
        if type(file_changed) is not bool:
            raise ValueError("Invalid file change flag")
        return TransactionChange(action, record["id"], fileobj, file_changed)
