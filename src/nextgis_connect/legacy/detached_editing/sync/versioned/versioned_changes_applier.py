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

import sqlite3
from collections import defaultdict
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, Union

from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadOnlySession,
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    FeatureChange,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes_applier import (
    ChangesApplier,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions import (
    ActionType,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.transaction_changes_serializer import (
    TransactionChange,
    TransactionChangesSerializer,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerContext,
)
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    SynchronizationError,
)

TransactionResult = Sequence[Tuple[int, Dict[str, Any]]]
GroupedResults = Dict[
    ActionType, List[Tuple[TransactionChange, Dict[str, Any]]]
]


class VersionedChangesApplier(ChangesApplier):
    _FEATURE_TABLES: ClassVar[Dict[ActionType, Tuple[str, ...]]] = {
        ActionType.FEATURE_CREATE: ("ngw_added_features",),
        ActionType.FEATURE_UPDATE: (
            "ngw_updated_attributes",
            "ngw_updated_geometries",
        ),
        ActionType.FEATURE_DELETE: (
            "ngw_removed_features",
            "ngw_features_metadata",
        ),
        ActionType.FEATURE_RESTORE: ("ngw_restored_features",),
        ActionType.DESCRIPTION_PUT: ("ngw_updated_descriptions",),
    }
    _ATTACHMENT_TABLES: ClassVar[Dict[ActionType, Tuple[str, ...]]] = {
        ActionType.ATTACHMENT_CREATE: ("ngw_added_attachments",),
        ActionType.ATTACHMENT_UPDATE: ("ngw_updated_attachments",),
        ActionType.ATTACHMENT_DELETE: (
            "ngw_removed_attachments",
            "ngw_features_attachments",
        ),
        ActionType.ATTACHMENT_RESTORE: ("ngw_restored_attachments",),
    }

    def __init__(self, container_context: DetachedContainerContext) -> None:
        super().__init__(container_context)
        if not container_context.metadata.is_versioning_enabled:
            raise ContainerError("Container does not have versioning enabled")

    def apply(
        self,
        changes: Union[FeatureChange, Sequence[FeatureChange]],
        operation_result: Any = None,
    ) -> None:
        changes_list = (
            [changes] if isinstance(changes, FeatureChange) else changes
        )
        if not changes_list:
            return
        confirmation = TransactionChangesSerializer().from_changes(
            changes_list
        )
        self.apply_transaction(confirmation, operation_result)

    def apply_transaction(
        self,
        changes: Sequence[TransactionChange],
        operation_result: TransactionResult,
        *,
        commit_datetime: Optional[str] = None,
    ) -> None:
        grouped = self.__group_results(changes, operation_result)
        # Cache operations are retryable; retain all markers until they succeed.
        self.__update_attachment_cache(grouped)
        with ContainerReadWriteSession(self._context) as cursor:
            self.__confirm_features(cursor, grouped)
            self.__confirm_attachments(cursor, grouped)
            if commit_datetime is not None:
                self.__complete_transaction(cursor, commit_datetime)

        self._added_fids_mapping.update(
            (change.local_id, result["fid"])
            for change, result in grouped[ActionType.FEATURE_CREATE]
        )

    def __group_results(
        self,
        changes: Sequence[TransactionChange],
        operation_result: TransactionResult,
    ) -> GroupedResults:
        if not operation_result:
            raise SynchronizationError("Empty operation result")
        if len(changes) != len(operation_result):
            raise SynchronizationError("Result length is not equal")
        grouped: GroupedResults = defaultdict(list)
        for index, (change, (number, result)) in enumerate(
            zip(changes, operation_result)
        ):
            if number != index:
                raise SynchronizationError(
                    "Unexpected transaction result order"
                )
            if (
                change.action not in self._FEATURE_TABLES
                and change.action not in self._ATTACHMENT_TABLES
            ):
                raise SynchronizationError("Unsupported transaction action")
            grouped[change.action].append((change, result))
        return grouped

    def __confirm_features(
        self, cursor: sqlite3.Cursor, grouped: GroupedResults
    ) -> None:
        cursor.executemany(
            "UPDATE ngw_features_metadata SET ngw_fid=? WHERE fid=?",
            (
                (result["fid"], change.local_id)
                for change, result in grouped[ActionType.FEATURE_CREATE]
            ),
        )
        self.__clear_markers(cursor, grouped, self._FEATURE_TABLES, "fid")

    def __confirm_attachments(
        self, cursor: sqlite3.Cursor, grouped: GroupedResults
    ) -> None:
        cursor.executemany(
            "UPDATE ngw_features_attachments SET ngw_aid=?, fileobj=? WHERE aid=?",
            (
                (result["aid"], result["fileobj"] or None, change.local_id)
                for change, result in grouped[ActionType.ATTACHMENT_CREATE]
            ),
        )
        updated_files = self.__uploaded_files(
            grouped[ActionType.ATTACHMENT_UPDATE]
            + grouped[ActionType.ATTACHMENT_RESTORE]
        )
        cursor.executemany(
            "UPDATE ngw_features_attachments SET fileobj=? WHERE aid=?",
            ((fileobj, aid) for aid, fileobj in updated_files),
        )
        self.__clear_markers(cursor, grouped, self._ATTACHMENT_TABLES, "aid")

    @staticmethod
    def __clear_markers(
        cursor: sqlite3.Cursor,
        grouped: GroupedResults,
        tables_by_action: Dict[ActionType, Tuple[str, ...]],
        id_column: str,
    ) -> None:
        for action, tables in tables_by_action.items():
            ids = [(change.local_id,) for change, _ in grouped[action]]
            if not ids:
                continue
            for table in tables:
                cursor.executemany(
                    f"DELETE FROM {table} WHERE {id_column}=?", ids
                )

    @staticmethod
    def __uploaded_files(
        attachments: Sequence[Tuple[TransactionChange, Dict[str, Any]]],
    ) -> List[Tuple[int, int]]:
        return [
            (change.local_id, result["fileobj"])
            for change, result in attachments
            if change.file_changed
        ]

    def __update_attachment_cache(self, grouped: GroupedResults) -> None:
        storage = DetachedStorageServiceFactory.create()
        metadata = self._context.metadata
        uploaded_files = self.__uploaded_files(
            grouped[ActionType.ATTACHMENT_CREATE]
            + grouped[ActionType.ATTACHMENT_UPDATE]
            + grouped[ActionType.ATTACHMENT_RESTORE]
        )
        for aid, fileobj in uploaded_files:
            storage.move_attachment_cache_to_fileobj(
                metadata.instance_id,
                metadata.resource_id,
                aid,
                old_fileobj=None,
                new_fileobj=fileobj,
            )

        removed = [
            (change.local_id, change.fileobj)
            for change, _ in grouped[ActionType.ATTACHMENT_DELETE]
        ]
        deleted_fids = [
            change.local_id for change, _ in grouped[ActionType.FEATURE_DELETE]
        ]
        if deleted_fids:
            with ContainerReadOnlySession(self._context) as cursor:
                removed.extend(
                    self._deleted_feature_attachment_cache_refs(
                        cursor, deleted_fids
                    )
                )
        if removed:
            self._remove_attachment_cache_refs(removed)

    @staticmethod
    def __complete_transaction(
        cursor: sqlite3.Cursor, commit_datetime: str
    ) -> None:
        cursor.execute(
            "UPDATE ngw_metadata SET transaction_id=NULL, "
            "transaction_changes=NULL, sync_date=?",
            (commit_datetime,),
        )
