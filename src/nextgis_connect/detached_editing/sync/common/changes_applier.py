import shutil
from abc import ABC, abstractmethod
from typing import Any, Dict, Sequence, Union, cast

from nextgis_connect.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDeletion,
    DescriptionPut,
    FeatureChange,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerContext,
    FeatureMetadata,
)
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from nextgis_connect.types import FeatureId, NgwFeatureId


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
        with ContainerReadWriteSession(self._context) as cursor:
            cursor.executescript(
                f"""
                DELETE FROM ngw_removed_features
                    WHERE fid IN ({removed_fids});
                DELETE FROM ngw_features_metadata
                    WHERE fid IN ({removed_fids});
                """
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

        cache_manager = NgConnectCacheManager()
        for change in deletion_changes:
            path = cache_manager.attachment_directory(
                self._context.metadata.instance_id,
                self._context.metadata.resource_id,
                change.aid,
                fileobj=change.fileobj,
            )
            if path.exists():
                shutil.rmtree(path.parent)

            path = cache_manager.attachment_thumbnail_directory(
                self._context.metadata.instance_id,
                self._context.metadata.resource_id,
                change.aid,
                fileobj=change.fileobj,
            )
            if path.exists():
                shutil.rmtree(path.parent)

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
