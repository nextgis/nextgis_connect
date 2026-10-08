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
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentDeletion,
    DescriptionPut,
    FeatureChange,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    deserialize_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerContext,
    FeatureMetadata,
)
from nextgis_connect.shared.types import (
    AttachmentId,
    FeatureId,
    FileObjectId,
    NgwFeatureId,
    UnsetType,
)


class ChangesApplier(ABC):
    """Apply server-side results to the local detached container state.

    This abstract base provides utilities to update container metadata
    after changes have been successfully applied to the server. Subclasses
    must implement ``apply`` to handle the concrete synchronization
    flow and call provided helpers to persist results.

    """

    _context: DetachedContainerContext
    _added_fids_mapping: Dict[FeatureId, NgwFeatureId]

    def __init__(self, container_context: DetachedContainerContext) -> None:
        """Create an applier bound to a container context.

        :param container_context: Detached container context used to open
            read-write sessions and update metadata tables.
        """
        super().__init__()
        self._context = container_context
        self._added_fids_mapping = {}

    @property
    def added_fids_mapping(self) -> Dict[FeatureId, NgwFeatureId]:
        """Return a mapping of local feature ids to newly assigned NGW ids.

        :return: Dictionary mapping local `FeatureId` to `NgwFeatureId` for
            features that were created on the server during
            synchronization.
        """
        return self._added_fids_mapping

    @abstractmethod
    def apply(
        self,
        changes: Union[FeatureChange, Sequence[FeatureChange]],
        operation_result: Any = None,
    ) -> None:
        """Apply changes and handle the server operation result.

        :param changes: A single change or a sequence of changes that
            were sent to the server.
        :param operation_result: Optional result returned by server
            calls, used by implementations to extract NGW ids,
            versions, etc.
        """
        ...

    def _process_added_features(
        self, features_metadata: Sequence[FeatureMetadata]
    ) -> None:
        """Remove added feature markers for features that were confirmed by
        the server and persist NGW feature ids assigned to newly created
        features.

        :param features_metadata: Sequence of `FeatureMetadata` objects
            where `ngw_fid` is set to the newly created NGW feature id.
        """
        if len(features_metadata) == 0:
            return

        added_fids = ",".join(str(action.fid) for action in features_metadata)

        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executemany(
                "UPDATE ngw_features_metadata SET ngw_fid=? WHERE fid=?",
                (
                    (feature.ngw_fid, feature.fid)
                    for feature in features_metadata
                ),
            )
            cursor.execute(
                f"DELETE FROM ngw_added_features WHERE fid in ({added_fids})"
            )

        self._added_fids_mapping.update(
            (feature.fid, cast(NgwFeatureId, feature.ngw_fid))
            for feature in features_metadata
        )

    def _process_updated_features(
        self, update_changes: Sequence[FeatureUpdate]
    ) -> None:
        """Clear local updated attribute and geometry markers for
        changes that were confirmed by the server.

        :param update_changes: Sequence of `FeatureUpdate` objects that
            were confirmed by the server.
        """
        if len(update_changes) == 0:
            return

        updated_fids = ",".join(str(change.fid) for change in update_changes)
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                DELETE FROM ngw_updated_attributes
                    WHERE fid in ({updated_fids});
                DELETE FROM ngw_updated_geometries
                    WHERE fid in ({updated_fids});
                """
            )

    def _process_deleted_features(
        self, deletion_changes: Sequence[FeatureDeletion]
    ) -> None:
        """Remove deleted feature markers and metadata for features that were
        confirmed deleted by the server.

        :param deletion_changes: Sequence of `FeatureDeletion` objects
            with NGW feature ids to delete.
        """
        if len(deletion_changes) == 0:
            return

        removed_fids = ",".join(
            str(deletion.fid) for deletion in deletion_changes
        )
        attachment_cache_refs: List[
            Tuple[AttachmentId, Optional[FileObjectId]]
        ] = []
        with ContainerReadWriteSession(self._context) as cursor:
            attachment_cache_refs = (
                self._deleted_feature_attachment_cache_refs(
                    cursor,
                    [change.fid for change in deletion_changes],
                )
            )
            cursor.executescript(
                f"""
                DELETE FROM ngw_removed_features
                    WHERE fid IN ({removed_fids});
                DELETE FROM ngw_features_metadata
                    WHERE fid IN ({removed_fids});
                """
            )

        self._remove_attachment_cache_refs(attachment_cache_refs)

    def _deleted_feature_attachment_cache_refs(
        self,
        cursor: Any,
        deleted_fids: Sequence[FeatureId],
    ) -> List[Tuple[AttachmentId, Optional[FileObjectId]]]:
        """Return attachment cache refs from deleted feature backups."""
        placeholders = ", ".join("?" for _ in deleted_fids)
        rows = cursor.execute(
            f"""
            SELECT backup
            FROM ngw_removed_features
            WHERE fid IN ({placeholders});
            """,
            tuple(deleted_fids),
        )

        refs: Set[Tuple[AttachmentId, Optional[FileObjectId]]] = set()
        for (backup_data,) in rows:
            refs.update(
                self._attachment_cache_refs_from_feature_backup(backup_data)
            )

        return sorted(
            refs,
            key=lambda ref: (ref[0], -1 if ref[1] is None else ref[1]),
        )

    def _attachment_cache_refs_from_feature_backup(
        self,
        backup_data: str,
    ) -> Set[Tuple[AttachmentId, Optional[FileObjectId]]]:
        """Extract attachment cache refs from one feature deletion backup."""
        backup = cast(Dict[str, Any], json.loads(backup_data))
        refs: Set[Tuple[AttachmentId, Optional[FileObjectId]]] = set()
        for state_key in ("before_deletion", "after_sync"):
            state = backup.get(state_key)
            if not isinstance(state, dict):
                continue

            attachments = state.get("attachments")
            if not isinstance(attachments, list):
                continue

            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue

                attachment_id = attachment.get("aid")
                if attachment_id is None:
                    continue

                refs.add(
                    (
                        int(attachment_id),
                        self._attachment_fileobj_from_backup(attachment),
                    )
                )

        return refs

    def _attachment_fileobj_from_backup(
        self,
        attachment: Dict[str, Any],
    ) -> Optional[FileObjectId]:
        """Return attachment fileobj from a serialized backup record."""
        value = attachment.get("fileobj")
        if value is None:
            return None

        fileobj = deserialize_value(value)
        if fileobj is None or isinstance(fileobj, UnsetType):
            return None

        return int(fileobj)

    def _remove_attachment_cache_refs(
        self,
        attachment_cache_refs: Sequence[
            Tuple[AttachmentId, Optional[FileObjectId]]
        ],
    ) -> None:
        """Remove cached files for attachments that no longer exist."""
        storage_service = DetachedStorageServiceFactory.create()
        for attachment_id, fileobj in attachment_cache_refs:
            storage_service.remove_attachment_cache(
                self._context.metadata.instance_id,
                self._context.metadata.resource_id,
                attachment_id,
                fileobj=fileobj,
            )

    def _process_restored_features(
        self, restore_changes: Sequence[FeatureRestoration]
    ) -> None:
        """Clear restored feature markers for features confirmed by
        the server.

        :param restore_changes: Sequence of `FeatureRestoration` objects
            with NGW feature ids that were restored.
        """
        if len(restore_changes) == 0:
            return

        restored_fids = ",".join(str(change.fid) for change in restore_changes)
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                DELETE FROM ngw_restored_features
                WHERE fid IN ({restored_fids});
                """
            )

    def _process_updated_descriptions(
        self, description_changes: Sequence[DescriptionPut]
    ) -> None:
        """Remove local updated description markers for features whose
        description was updated on the server.

        :param description_changes: Sequence of `DescriptionPut` objects.
        """
        if len(description_changes) == 0:
            return

        updated_fids = ",".join(
            str(change.fid) for change in description_changes
        )
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.execute(
                f"""
                DELETE FROM ngw_updated_descriptions
                WHERE fid in ({updated_fids});
                """
            )

    def _process_created_attachments(
        self, attachments: Sequence[AttachmentMetadata]
    ) -> None:
        """Remove local added-attachment markers and persist NGW attachment ids
        for attachments that were successfully created on the server.

        :param attachments: Sequence of `AttachmentMetadata` objects
            where `ngw_aid` has been set to the server-assigned
            attachment id.
        """
        if len(attachments) == 0:
            return

        added_aids = ",".join(
            str(attachment.aid) for attachment in attachments
        )
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executemany(
                """
                UPDATE ngw_features_attachments
                    SET ngw_aid=?, fileobj=?
                WHERE aid=?
                """,
                (
                    (
                        attachment.ngw_aid,
                        attachment.fileobj or None,
                        attachment.aid,
                    )
                    for attachment in attachments
                ),
            )
            cursor.execute(
                f"DELETE FROM ngw_added_attachments WHERE aid in ({added_aids})"
            )

    def _process_updated_attachments(
        self, updated_attachments: Sequence[AttachmentMetadata]
    ) -> None:
        """Clear local markers for attachments that were updated on the
        server.

        :param updated_attachments: Sequence of `AttachmentMetadata`
            objects identifying NGW attachment ids and their parent
            features.
        """
        if len(updated_attachments) == 0:
            return

        updated_fileobj_query = ""
        for attachment in updated_attachments:
            if not bool(attachment.fileobj):
                continue

            updated_fileobj_query += f"""
                UPDATE ngw_features_attachments
                    SET fileobj={attachment.fileobj}
                WHERE aid={attachment.aid};
            """

        updated_aids = ",".join(
            str(change.aid) for change in updated_attachments
        )
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                {updated_fileobj_query}
                DELETE FROM ngw_updated_attachments
                WHERE aid in ({updated_aids});
                """
            )

    def _process_deleted_attachments(
        self, deletion_changes: Sequence[AttachmentDeletion]
    ) -> None:
        """Remove local markers for attachments that were deleted on the server
        and delete their metadata and files from the local cache.

        :param deletion_changes: Sequence of `AttachmentDeletion`
            describing NGW attachment ids to remove.
        """
        if len(deletion_changes) == 0:
            return

        removed_aids = ",".join(str(change.aid) for change in deletion_changes)

        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                DELETE FROM ngw_removed_attachments
                    WHERE aid IN ({removed_aids});
                DELETE FROM ngw_features_attachments
                    WHERE aid IN ({removed_aids});
                """
            )

        storage_service = DetachedStorageServiceFactory.create()
        for change in deletion_changes:
            storage_service.remove_attachment_cache(
                self._context.metadata.instance_id,
                self._context.metadata.resource_id,
                change.aid,
                fileobj=change.fileobj,
            )

    def _process_restored_attachments(
        self, restoration_changes: Sequence[AttachmentMetadata]
    ) -> None:
        """Clear local markers for attachments that were restored on the server.

        :param restoration_changes: Sequence of `AttachmentMetadata` objects
            describing NGW attachment ids that were restored.
        """
        if len(restoration_changes) == 0:
            return

        updated_fileobj_query = ""
        for attachment in restoration_changes:
            if not bool(attachment.fileobj):
                continue

            updated_fileobj_query += f"""
                UPDATE ngw_features_attachments
                    SET fileobj={attachment.fileobj}
                WHERE aid={attachment.aid};
            """

        restored_aids = ",".join(
            str(change.aid) for change in restoration_changes
        )
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                {updated_fileobj_query}
                DELETE FROM ngw_restored_attachments
                WHERE aid IN ({restored_aids});
                """
            )
