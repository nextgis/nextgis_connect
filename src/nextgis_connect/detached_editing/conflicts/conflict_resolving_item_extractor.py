import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast

from qgis.core import QgsFeature, QgsFeatureRequest, QgsVectorLayer

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentConflictResolvingItem,
    AttachmentDataConflictResolvingItem,
    AttachmentDeleteConflictResolvingItem,
    BaseConflictResolvingItem,
    DescriptionConflictResolvingItem,
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentConflict,
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureChangeConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteAttachmentDeletionConflict,
    RemoteFeatureDeletionConflict,
    VersioningConflict,
)
from nextgis_connect.detached_editing.container.editing.container_sessions import (
    ContainerReadOnlySession,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    deserialize_geometry,
    deserialize_value,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentAction,
    AttachmentChangeMixin,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureAction,
    FeatureDataChangeMixin,
    FeatureRestoreAction,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerContext,
    detached_layer_uri,
)
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import AttachmentId, FeatureId, Unset, UnsetType


@dataclass
class _FeatureExtractionContext:
    """Store feature-related state required for conflict item extraction.

    :ivar actual_features: Existing features indexed by local feature id.
    :ivar deleted_features: Restored deleted features indexed by local id.
    :ivar deleted_features_backups: Raw backups for deleted features.
    :ivar fields_backups: Backed up attribute values by feature and field id.
    :ivar geometries_backups: Backed up geometries by feature id.
    :ivar actual_descriptions: Current feature descriptions by feature id.
    :ivar actual_attachments: Current feature attachments by feature id.
    """

    actual_features: Dict[FeatureId, QgsFeature]
    deleted_features: Dict[FeatureId, QgsFeature]

    deleted_features_backups: Dict[FeatureId, Dict[str, Any]]

    fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str]
    geometries_backups: Dict[QgsFeatureId, str]

    actual_descriptions: Dict[FeatureId, Optional[str]]
    actual_attachments: Dict[FeatureId, List[AttachmentMetadata]]


@dataclass
class _AttachmentExtractionContext:
    """Store attachment-related state required for conflict item extraction.

    :ivar actual_attachments: Existing attachments indexed by local id.
    :ivar deleted_attachments: Restored deleted attachments indexed by id.
    :ivar attachment_changes_backups: Backups for changed attachments.
    """

    actual_attachments: Dict[AttachmentId, AttachmentMetadata]
    deleted_attachments: Dict[AttachmentId, AttachmentMetadata]
    attachment_changes_backups: Dict[AttachmentId, AttachmentMetadata]


class ConflictResolvingItemExtractor:
    """Extract UI-ready items for resolving detached editing conflicts.

    Use the detached container state and conflict models to reconstruct
    local, remote, and merged representations required by resolving items.

    :ivar _context: Detached editing container context.
    """

    _context: DetachedContainerContext

    def __init__(self, context: DetachedContainerContext) -> None:
        """Initialize the extractor.

        :param context: Detached editing container context.
        """

        self._context = context

    def extract(
        self, conflicts: List[VersioningConflict]
    ) -> List[BaseConflictResolvingItem]:
        """Build resolving items for the provided conflicts.

        :param conflicts: Conflicts to convert into resolving items.
        :return: Sorted resolving items ready for presentation.
        """

        feature_conflicts: List[FeatureChangeConflict] = []
        attachment_conflicts: List[AttachmentConflict] = []

        for conflict in conflicts:
            if isinstance(conflict, FeatureChangeConflict):
                feature_conflicts.append(conflict)
            elif isinstance(conflict, AttachmentConflict):
                attachment_conflicts.append(conflict)

        feature_context = self._prepare_feature_context(feature_conflicts)
        attachment_context = self._prepare_attachment_context(
            attachment_conflicts
        )

        result: List[BaseConflictResolvingItem] = []
        for conflict in conflicts:
            item = self._extract_item(
                conflict,
                feature_context,
                attachment_context,
            )
            if item is None:
                continue
            result.append(item)

        result.sort(key=self._item_sort_key)

        return result

    def _item_sort_key(
        self,
        item: BaseConflictResolvingItem,
    ) -> Tuple[int, int]:
        """Return a stable sort key for resolving items.

        :param item: Resolving item to order.
        :return: Tuple grouping items by conflict kind and remote id.
        """

        conflict = item.conflict

        if isinstance(conflict, FeatureChangeConflict):
            feature_id = conflict.ngw_fid
            return 0, feature_id

        if isinstance(conflict, DescriptionConflict):
            feature_id = conflict.ngw_fid
            return 1, feature_id

        if isinstance(conflict, AttachmentConflict):
            attachment_id = conflict.ngw_aid
            return 2, attachment_id

        return 3, 0

    def _extract_item(
        self,
        conflict: VersioningConflict,
        feature_context: _FeatureExtractionContext,
        attachment_context: _AttachmentExtractionContext,
    ) -> Optional[BaseConflictResolvingItem]:
        """Extract a resolving item for a single conflict.

        :param conflict: Conflict to convert.
        :param feature_context: Prepared feature extraction state.
        :param attachment_context: Prepared attachment extraction state.
        :return: Extracted resolving item or None if unsupported.
        """

        if isinstance(conflict, FeatureChangeConflict):
            return self._extract_feature_item(conflict, feature_context)

        if isinstance(conflict, DescriptionConflict):
            return DescriptionConflictResolvingItem(
                conflict=conflict,
                local_description=conflict.local_change.description,
                remote_description=conflict.remote_action.value,
            )

        if isinstance(conflict, AttachmentConflict):
            return self._extract_attachment_item(
                conflict,
                attachment_context,
            )

        return None

    def _prepare_feature_context(
        self,
        feature_conflicts: List[FeatureChangeConflict],
    ) -> _FeatureExtractionContext:
        """Collect feature data required to resolve feature conflicts.

        :param feature_conflicts: Feature conflicts requiring extraction.
        :return: Prepared feature extraction context.
        """

        fids_for_extraction = set()
        fids_for_restoring = set()
        for conflict in feature_conflicts:
            if isinstance(conflict, LocalFeatureDeletionConflict):
                fids_for_restoring.add(conflict.fid)
            else:
                fids_for_extraction.add(conflict.fid)

        fids_for_extensions = fids_for_extraction | fids_for_restoring

        actual_features = self._extract_existed_features(fids_for_extraction)
        deleted_features = self._extract_deleted_features(fids_for_restoring)
        deleted_features_backups = self._extract_deleted_feature_backups(
            fids_for_restoring
        )
        fields_backups, geometries_backups = (
            self._extract_feature_changes_backups(list(fids_for_extraction))
        )
        descriptions = self._extract_existed_descriptions(
            fids_for_extensions,
        )
        attachments = self._extract_existed_attachments_for_features(
            fids_for_extensions,
        )

        return _FeatureExtractionContext(
            actual_features=actual_features,
            deleted_features=deleted_features,
            deleted_features_backups=deleted_features_backups,
            fields_backups=fields_backups,
            geometries_backups=geometries_backups,
            actual_descriptions=descriptions,
            actual_attachments=attachments,
        )

    def _extract_feature_item(
        self,
        conflict: VersioningConflict,
        context: _FeatureExtractionContext,
    ) -> BaseConflictResolvingItem:
        """Extract a resolving item for a feature-related conflict.

        :param conflict: Feature conflict to convert.
        :param context: Prepared feature extraction context.
        :return: Feature resolving item.
        :raises NotImplementedError: If the conflict type is unsupported.
        """

        if isinstance(conflict, FeatureDataConflict):
            return self._extract_feature_data_item(
                conflict,
                context,
            )

        if isinstance(conflict, LocalFeatureDeletionConflict):
            return self._extract_local_feature_deletion_item(
                conflict,
                context,
            )

        if isinstance(conflict, RemoteFeatureDeletionConflict):
            return self._extract_remote_feature_deletion_item(
                conflict,
                context,
            )

        raise NotImplementedError

    def _extract_feature_data_item(
        self,
        conflict: FeatureDataConflict,
        context: _FeatureExtractionContext,
    ) -> FeatureDataConflictResolvingItem:
        """Extract a resolving item for feature data conflicts.

        :param conflict: Feature data conflict to convert.
        :param context: Prepared feature extraction context.
        :return: Resolving item with local, remote, and merged features.
        """

        local_feature = context.actual_features[conflict.fid]
        if isinstance(conflict.remote_action, FeatureRestoreAction):
            feature_after_sync = QgsFeature(
                local_feature.fields(), local_feature.id()
            )
        else:
            feature_after_sync = self._restore_feature_to_last_synced(
                local_feature,
                context.fields_backups,
                context.geometries_backups,
            )

        remote_feature = self._feature_with_remote_changes(
            feature_after_sync,
            [conflict.remote_action],
        )
        result_feature = self._feature_with_combined_changes(
            local_feature,
            conflict,
        )

        return FeatureDataConflictResolvingItem(
            conflict=conflict,
            local_feature=local_feature,
            remote_feature=remote_feature,
            result_feature=result_feature,
        )

    def _extract_local_feature_deletion_item(
        self,
        conflict: LocalFeatureDeletionConflict,
        context: _FeatureExtractionContext,
    ) -> FeatureDeleteConflictResolvingItem:
        """Extract a resolving item for local feature deletion conflicts.

        :param conflict: Conflict caused by local feature deletion.
        :param context: Prepared feature extraction context.
        :return: Resolving item describing the remote state.
        """

        feature_after_sync = context.deleted_features[conflict.fid]
        remote_feature = self._feature_with_remote_changes(
            feature_after_sync,
            conflict.remote_actions,
        )
        after_sync_description = self._description_from_deleted_feature_backup(
            context.deleted_features_backups,
            conflict.fid,
            section="after_sync",
        )
        remote_description = self._remote_description_with_actions(
            after_sync_description,
            conflict.remote_actions,
        )
        after_sync_attachments = self._attachments_from_deleted_feature_backup(
            context.deleted_features_backups,
            conflict.fid,
            section="after_sync",
        )
        remote_attachments = self._remote_attachments_with_actions(
            after_sync_attachments,
            conflict.remote_actions,
            conflict.fid,
        )

        return FeatureDeleteConflictResolvingItem(
            conflict=conflict,
            local_feature=None,
            remote_feature=remote_feature,
            result_feature=Unset,
            local_description=None,
            remote_description=remote_description,
            local_attachments=[],
            remote_attachments=remote_attachments,
        )

    def _extract_remote_feature_deletion_item(
        self,
        conflict: RemoteFeatureDeletionConflict,
        context: _FeatureExtractionContext,
    ) -> FeatureDeleteConflictResolvingItem:
        """Extract a resolving item for remote feature deletion conflicts.

        :param conflict: Conflict caused by remote feature deletion.
        :param context: Prepared feature extraction context.
        :return: Resolving item describing the local state.
        """

        local_feature = context.actual_features[conflict.fid]
        local_description = context.actual_descriptions.get(conflict.fid)
        local_attachments = context.actual_attachments.get(conflict.fid, [])

        return FeatureDeleteConflictResolvingItem(
            conflict=conflict,
            local_feature=local_feature,
            remote_feature=None,
            result_feature=Unset,
            local_description=local_description,
            remote_description=None,
            local_attachments=local_attachments,
            remote_attachments=[],
        )

    def _prepare_attachment_context(
        self,
        attachment_conflicts: List[AttachmentConflict],
    ) -> _AttachmentExtractionContext:
        """Collect attachment data required to resolve attachment conflicts.

        :param attachment_conflicts: Attachment conflicts requiring extraction.
        :return: Prepared attachment extraction context.
        """

        aids_for_extraction = set()
        aids_for_restoring = set()
        for conflict in attachment_conflicts:
            if isinstance(conflict, LocalAttachmentDeletionConflict):
                aids_for_restoring.add(conflict.aid)
            else:
                aids_for_extraction.add(conflict.aid)

        return _AttachmentExtractionContext(
            actual_attachments=self._extract_existing_attachments(
                aids_for_extraction
            ),
            deleted_attachments=self._extract_deleted_attachments(
                aids_for_restoring
            ),
            attachment_changes_backups=self._extract_attachment_changes_backups(
                aids_for_extraction
            ),
        )

    def _extract_attachment_item(
        self,
        conflict: VersioningConflict,
        context: _AttachmentExtractionContext,
    ) -> AttachmentConflictResolvingItem:
        """Extract a resolving item for an attachment-related conflict.

        :param conflict: Attachment conflict to convert.
        :param context: Prepared attachment extraction context.
        :return: Attachment resolving item.
        :raises NotImplementedError: If the conflict type is unsupported.
        """

        if isinstance(conflict, AttachmentDataConflict):
            return self._extract_attachment_data_item(conflict, context)

        if isinstance(conflict, LocalAttachmentDeletionConflict):
            return self._extract_local_attachment_deletion_item(
                conflict,
                context,
            )

        if isinstance(conflict, RemoteAttachmentDeletionConflict):
            return self._extract_remote_attachment_deletion_item(
                conflict,
                context,
            )

        raise NotImplementedError

    def _extract_attachment_data_item(
        self,
        conflict: AttachmentDataConflict,
        context: _AttachmentExtractionContext,
    ) -> AttachmentDataConflictResolvingItem:
        """Extract a resolving item for attachment data conflicts.

        :param conflict: Attachment data conflict to convert.
        :param context: Prepared attachment extraction context.
        :return: Resolving item with local, remote, and merged attachments.
        """

        local_attachment = context.actual_attachments[conflict.aid]
        attachment_after_sync = context.attachment_changes_backups.get(
            conflict.aid,
            local_attachment,
        )
        remote_attachment = self._attachment_with_remote_change(
            attachment_after_sync,
            conflict.remote_action,
        )
        result_attachment = self._attachment_with_combined_changes(
            remote_attachment,
            conflict,
        )

        return AttachmentDataConflictResolvingItem(
            conflict=conflict,
            local_attachment=local_attachment,
            remote_attachment=remote_attachment,
            result_attachment=result_attachment,
        )

    def _extract_local_attachment_deletion_item(
        self,
        conflict: LocalAttachmentDeletionConflict,
        context: _AttachmentExtractionContext,
    ) -> AttachmentDeleteConflictResolvingItem:
        """Extract a resolving item for local attachment deletion conflicts.

        :param conflict: Conflict caused by local attachment deletion.
        :param context: Prepared attachment extraction context.
        :return: Resolving item describing the remote attachment.
        """

        attachment_after_sync = context.deleted_attachments[conflict.aid]
        remote_attachment = self._attachment_with_remote_change(
            attachment_after_sync,
            conflict.remote_action,
        )

        return AttachmentDeleteConflictResolvingItem(
            conflict=conflict,
            local_attachment=None,
            remote_attachment=remote_attachment,
            result_attachment=Unset,
        )

    def _extract_remote_attachment_deletion_item(
        self,
        conflict: RemoteAttachmentDeletionConflict,
        context: _AttachmentExtractionContext,
    ) -> AttachmentDeleteConflictResolvingItem:
        """Extract a resolving item for remote attachment deletion conflicts.

        :param conflict: Conflict caused by remote attachment deletion.
        :param context: Prepared attachment extraction context.
        :return: Resolving item describing the local attachment.
        """

        local_attachment = context.actual_attachments[conflict.aid]

        return AttachmentDeleteConflictResolvingItem(
            conflict=conflict,
            local_attachment=local_attachment,
            remote_attachment=None,
            result_attachment=Unset,
        )

    def _attachment_with_combined_changes(
        self,
        remote_attachment: AttachmentMetadata,
        conflict: AttachmentDataConflict,
    ) -> AttachmentMetadata:
        """Merge remote attachment state with local non-conflicting changes.

        :param remote_attachment: Attachment state after applying remote changes.
        :param conflict: Attachment conflict describing local changes.
        :return: Attachment metadata containing unresolved markers.
        """

        result = remote_attachment

        if conflict.has_name_conflict:
            result = replace(result, name=Unset)
        elif conflict.local_change.name:
            result = replace(result, name=conflict.local_change.name)

        if conflict.has_description_conflict:
            result = replace(result, description=Unset)
        elif conflict.local_change.description:
            result = replace(
                result, description=conflict.local_change.description
            )

        if conflict.has_file_conflict:
            result = replace(result, fileobj=Unset)
        elif conflict.local_change.is_file_new:
            result = replace(result, fileobj=conflict.local_change.fileobj)

        return result

    def _attachment_with_remote_change(
        self,
        attachment: AttachmentMetadata,
        action: AttachmentAction,
    ) -> AttachmentMetadata:
        """Apply a remote attachment action to attachment metadata.

        :param attachment: Base attachment metadata.
        :param action: Remote action to apply.
        :return: Updated attachment metadata.
        """

        result = replace(
            attachment,
            ngw_fid=action.fid,
            ngw_aid=action.aid,
            version=action.vid,
        )
        assert isinstance(action, AttachmentChangeMixin)
        if not isinstance(action.keyname, UnsetType):
            result = replace(result, keyname=action.keyname)
        if not isinstance(action.name, UnsetType):
            result = replace(result, name=action.name)
        if not isinstance(action.description, UnsetType):
            result = replace(result, description=action.description)
        if not isinstance(action.fileobj, UnsetType):
            result = replace(result, fileobj=action.fileobj)
        if not isinstance(action.mime_type, UnsetType):
            result = replace(result, mime_type=action.mime_type)

        return result

    def _extract_existing_attachments(
        self,
        aids: Iterable[AttachmentId],
    ) -> Dict[AttachmentId, AttachmentMetadata]:
        """Load existing attachments from the container database.

        :param aids: Local attachment ids to load.
        :return: Existing attachments indexed by local id.
        """

        aids_list = list(aids)
        if len(aids_list) == 0:
            return {}

        result: Dict[AttachmentId, AttachmentMetadata] = {}

        joined_aids = ",".join(map(str, aids_list))
        with ContainerReadOnlySession(self._context) as cursor:
            rows = cursor.execute(
                f"""
                SELECT
                    attachments.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.ngw_aid,
                    attachments.version,
                    attachments.keyname,
                    attachments.name,
                    attachments.description,
                    attachments.fileobj,
                    attachments.mime_type
                FROM ngw_features_attachments AS attachments
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
                WHERE attachments.aid IN ({joined_aids});
                """
            )

            result = {
                aid: AttachmentMetadata(
                    fid=fid,
                    ngw_fid=ngw_fid,
                    aid=aid,
                    ngw_aid=ngw_aid,
                    version=version,
                    keyname=keyname,
                    name=name,
                    description=description,
                    fileobj=fileobj,
                    mime_type=mime_type,
                )
                for (
                    fid,
                    ngw_fid,
                    aid,
                    ngw_aid,
                    version,
                    keyname,
                    name,
                    description,
                    fileobj,
                    mime_type,
                ) in rows
            }

        return result

    def _extract_deleted_attachments(
        self,
        aids: Iterable[AttachmentId],
    ) -> Dict[AttachmentId, AttachmentMetadata]:
        """Load deleted attachments restored from backups.

        :param aids: Local attachment ids to restore.
        :return: Restored attachments indexed by local id.
        """

        aids_list = list(aids)
        if len(aids_list) == 0:
            return {}

        result: Dict[AttachmentId, AttachmentMetadata] = {}

        joined_aids = ",".join(map(str, aids_list))
        with ContainerReadOnlySession(self._context) as cursor:
            rows = cursor.execute(
                f"""
                SELECT aid, backup
                FROM ngw_removed_attachments
                WHERE aid IN ({joined_aids});
                """
            )

            for aid, backup in rows:
                backup_data = cast(Dict[str, Any], json.loads(backup))
                result[aid] = self._deserialize_attachment_backup(
                    cast(Dict[str, Any], backup_data["after_sync"])
                )

        return result

    def _extract_attachment_changes_backups(
        self,
        aids: Iterable[AttachmentId],
    ) -> Dict[AttachmentId, AttachmentMetadata]:
        """Load backups for locally changed attachments.

        :param aids: Local attachment ids with local updates.
        :return: Backed up attachment metadata indexed by local id.
        """

        aids_list = list(aids)
        if len(aids_list) == 0:
            return {}

        result: Dict[AttachmentId, AttachmentMetadata] = {}

        joined_aids = ",".join(map(str, aids_list))
        with ContainerReadOnlySession(self._context) as cursor:
            rows = cursor.execute(
                f"""
                SELECT aid, backup
                FROM ngw_updated_attachments
                WHERE aid IN ({joined_aids});
                """
            )

            for aid, backup in rows:
                backup_data = cast(Dict[str, Any], json.loads(backup))
                result[aid] = self._deserialize_attachment_backup(backup_data)

        return result

    def _deserialize_attachment_backup(
        self,
        backup: Dict[str, Any],
    ) -> AttachmentMetadata:
        """Deserialize attachment metadata stored in a backup payload.

        :param backup: Serialized attachment backup data.
        :return: Deserialized attachment metadata.
        """

        return AttachmentMetadata(
            fid=backup["fid"],
            ngw_fid=backup.get("ngw_fid"),
            aid=backup["aid"],
            ngw_aid=backup.get("ngw_aid"),
            version=deserialize_value(backup["version"]),
            keyname=backup.get("keyname"),
            name=backup.get("name"),
            description=backup.get("description"),
            fileobj=deserialize_value(backup["fileobj"]),
            mime_type=backup.get("mime_type"),
        )

    def _restore_feature_to_last_synced(
        self,
        local_feature: QgsFeature,
        fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str],
        geometries_backups: Dict[QgsFeatureId, str],
    ) -> QgsFeature:
        """Restore a feature to the last synchronized state.

        :param local_feature: Current local feature.
        :param fields_backups: Backed up attribute values.
        :param geometries_backups: Backed up geometries.
        :return: Feature reconstructed to the synchronized state.
        """

        result_feature = QgsFeature(local_feature)
        for field in self._context.metadata.fields:
            key = (local_feature.id(), field.attribute)
            if key not in fields_backups:
                continue
            result_feature.setAttribute(field.attribute, fields_backups[key])
        if local_feature.id() in geometries_backups:
            result_feature.setGeometry(
                deserialize_geometry(
                    geometries_backups[local_feature.id()],
                    self._context.metadata.is_versioning_enabled,
                )
            )
        return result_feature

    def _feature_with_remote_changes(
        self,
        feature: QgsFeature,
        actions: List[FeatureAction],
    ) -> QgsFeature:
        """Apply remote feature actions to a feature copy.

        :param feature: Base feature state.
        :param actions: Remote actions to apply.
        :return: Updated feature state.
        """

        fields = self._context.metadata.fields

        result_feature = QgsFeature(feature)
        for action in actions:
            if not isinstance(action, FeatureDataChangeMixin):
                continue

            if not isinstance(action.fields, UnsetType):
                for field_id, value in action.fields:
                    result_feature.setAttribute(
                        fields.find_with(ngw_id=field_id).attribute, value
                    )

            if not isinstance(action.geom, UnsetType):
                result_feature.setGeometry(action.geom)

        return result_feature

    def _feature_with_combined_changes(
        self,
        local_feature: QgsFeature,
        conflict: FeatureDataConflict,
    ) -> QgsFeature:
        """Combine remote feature changes with unresolved local conflicts.

        :param local_feature: Current local feature.
        :param conflict: Feature conflict describing local and remote edits.
        :return: Feature with unresolved values cleared.
        """

        result_feature = self._feature_with_remote_changes(
            local_feature, [conflict.remote_action]
        )

        if len(conflict.conflicting_fields) > 0:
            fields = self._context.metadata.fields
            for field_id in conflict.conflicting_fields:
                result_feature.setAttribute(
                    fields.find_with(ngw_id=field_id).attribute, None
                )

        if conflict.has_geometry_conflict:
            result_feature.setGeometry(None)

        return result_feature

    def _extract_deleted_feature_backups(
        self,
        fids: Iterable[QgsFeatureId],
    ) -> Dict[FeatureId, Dict[str, Any]]:
        """Load raw backups for deleted features.

        :param fids: Feature ids to restore backups for.
        :return: Raw backup payloads indexed by feature id.
        """

        fids_list = list(fids)
        if len(fids_list) == 0:
            return {}

        joined_fids = ",".join(map(str, fids_list))
        result: Dict[FeatureId, Dict[str, Any]] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            for fid, backup in cursor.execute(
                f"""
                SELECT fid, backup
                FROM ngw_removed_features
                WHERE fid IN ({joined_fids});
                """
            ):
                result[fid] = cast(Dict[str, Any], json.loads(backup))

        return result

    def _extract_existed_descriptions(
        self,
        fids: Iterable[QgsFeatureId],
    ) -> Dict[FeatureId, Optional[str]]:
        """Load current descriptions for existing features.

        :param fids: Feature ids whose descriptions should be loaded.
        :return: Descriptions indexed by feature id.
        """

        fids_list = list(fids)
        if len(fids_list) == 0:
            return {}

        joined_fids = ",".join(map(str, fids_list))
        result: Dict[FeatureId, Optional[str]] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            for fid, description in cursor.execute(
                f"""
                SELECT fid, description
                FROM ngw_features_descriptions
                WHERE fid IN ({joined_fids});
                """
            ):
                result[fid] = description

        return result

    def _description_from_deleted_feature_backup(
        self,
        backups: Dict[FeatureId, Dict[str, Any]],
        fid: FeatureId,
        *,
        section: str,
    ) -> Optional[str]:
        """Extract a description value from a deleted feature backup.

        :param backups: Raw deleted feature backups.
        :param fid: Feature id whose description should be extracted.
        :param section: Backup section to inspect.
        :return: Extracted description or None.
        """

        if fid not in backups:
            return None

        section_data = cast(Dict[str, Any], backups[fid].get(section, {}))
        if "description" not in section_data:
            return None

        description = cast(Dict[str, Any], section_data.get("description", {}))
        if not isinstance(description, dict) or "value" not in description:
            return None

        return cast(Optional[str], description.get("value"))

    def _extract_existed_attachments_for_features(
        self,
        fids: Iterable[QgsFeatureId],
    ) -> Dict[FeatureId, List[AttachmentMetadata]]:
        """Load current attachments for existing features.

        :param fids: Feature ids whose attachments should be loaded.
        :return: Attachments grouped by feature id.
        """

        fids_list = list(fids)
        if len(fids_list) == 0:
            return {}

        joined_fids = ",".join(map(str, fids_list))
        result: Dict[FeatureId, List[AttachmentMetadata]] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            rows = cursor.execute(
                f"""
                SELECT
                    attachments.fid,
                    metadata.ngw_fid,
                    attachments.aid,
                    attachments.ngw_aid,
                    attachments.version,
                    attachments.keyname,
                    attachments.name,
                    attachments.description,
                    attachments.fileobj,
                    attachments.mime_type
                FROM ngw_features_attachments AS attachments
                LEFT JOIN ngw_features_metadata AS metadata
                    ON metadata.fid = attachments.fid
                LEFT JOIN ngw_removed_attachments AS removed
                    ON removed.aid = attachments.aid
                WHERE attachments.fid IN ({joined_fids})
                    AND removed.aid IS NULL;
                """
            )

            for (
                fid,
                ngw_fid,
                aid,
                ngw_aid,
                version,
                keyname,
                name,
                description,
                fileobj,
                mime_type,
            ) in rows:
                attachment = AttachmentMetadata(
                    fid=fid,
                    ngw_fid=ngw_fid,
                    aid=aid,
                    ngw_aid=ngw_aid,
                    version=version,
                    keyname=keyname,
                    name=name,
                    description=description,
                    fileobj=fileobj,
                    mime_type=mime_type,
                )
                if fid not in result:
                    result[fid] = []
                result[fid].append(attachment)

        return result

    def _attachments_from_deleted_feature_backup(
        self,
        backups: Dict[FeatureId, Dict[str, Any]],
        fid: FeatureId,
        *,
        section: str,
    ) -> List[AttachmentMetadata]:
        """Extract attachments from a deleted feature backup section.

        :param backups: Raw deleted feature backups.
        :param fid: Feature id whose attachments should be extracted.
        :param section: Backup section to inspect.
        :return: Deserialized attachment metadata list.
        """

        if fid not in backups:
            return []

        section_data = cast(Dict[str, Any], backups[fid].get(section, {}))
        if "attachments" not in section_data:
            return []

        if not isinstance(section_data["attachments"], list):
            return []

        return [
            self._deserialize_attachment_backup(attachment)
            for attachment in section_data["attachments"]
        ]

    def _remote_description_with_actions(
        self,
        base_description: Optional[str],
        actions: Any,
    ) -> Optional[str]:
        """Apply remote description actions to a base description.

        :param base_description: Description before remote actions.
        :param actions: Remote actions affecting the feature.
        :return: Description after applying remote actions.
        """

        result = base_description
        for action in actions:
            if isinstance(action, DescriptionPutAction):
                result = action.value

        return result

    def _remote_attachments_with_actions(
        self,
        base_attachments: List[AttachmentMetadata],
        actions: Any,
        feature_id: FeatureId,
    ) -> List[AttachmentMetadata]:
        """Apply remote attachment actions to a base attachment list.

        :param base_attachments: Attachments before remote actions.
        :param actions: Remote actions affecting attachments.
        :param feature_id: Feature id used for created attachments.
        :return: Attachments after applying remote actions.
        """

        attachments_by_id: Dict[int, AttachmentMetadata] = {
            int(attachment.ngw_aid): replace(attachment)
            for attachment in base_attachments
            if attachment.ngw_aid is not None
        }

        for action in actions:
            if isinstance(action, AttachmentDeleteAction):
                continue

            if isinstance(action, AttachmentCreateAction):
                attachment = AttachmentMetadata(
                    fid=feature_id,
                    aid=-cast(AttachmentId, action.aid),
                    ngw_fid=action.fid,
                    ngw_aid=action.aid,
                    version=action.vid,
                )
                if isinstance(action, AttachmentChangeMixin):
                    if not isinstance(action.keyname, UnsetType):
                        attachment = replace(
                            attachment, keyname=action.keyname
                        )
                    if not isinstance(action.name, UnsetType):
                        attachment = replace(attachment, name=action.name)
                    if not isinstance(action.description, UnsetType):
                        attachment = replace(
                            attachment,
                            description=action.description,
                        )
                    if not isinstance(action.fileobj, UnsetType):
                        attachment = replace(
                            attachment, fileobj=action.fileobj
                        )
                    if not isinstance(action.mime_type, UnsetType):
                        attachment = replace(
                            attachment, mime_type=action.mime_type
                        )

                attachments_by_id[int(action.aid)] = attachment
                continue

            if isinstance(action, AttachmentUpdateAction):
                existing = attachments_by_id.get(int(action.aid))
                if existing is None:
                    continue

                updated = replace(existing, version=action.vid)
                if not isinstance(action.keyname, UnsetType):
                    updated = replace(updated, keyname=action.keyname)
                if not isinstance(action.name, UnsetType):
                    updated = replace(updated, name=action.name)
                if not isinstance(action.description, UnsetType):
                    updated = replace(updated, description=action.description)
                if not isinstance(action.fileobj, UnsetType):
                    updated = replace(updated, fileobj=action.fileobj)
                if not isinstance(action.mime_type, UnsetType):
                    updated = replace(updated, mime_type=action.mime_type)

                attachments_by_id[int(action.aid)] = updated

        return list(attachments_by_id.values())

    def _extract_existed_features(
        self, fids: Iterable[QgsFeatureId]
    ) -> Dict[FeatureId, QgsFeature]:
        """Load existing features from the detached layer.

        :param fids: Feature ids to load.
        :return: Existing features indexed by local feature id.
        :raises ValueError: If the detached layer cannot be opened.
        """

        layer = QgsVectorLayer(detached_layer_uri(self._context), "", "ogr")
        if not layer.isValid():
            raise ValueError("Invalid layer")

        request = QgsFeatureRequest(list(fids))
        return {
            feature.id(): feature
            for feature in cast(
                Iterable[QgsFeature], layer.getFeatures(request)
            )
        }

    def _extract_deleted_features(
        self, fids: Iterable[QgsFeatureId]
    ) -> Dict[FeatureId, QgsFeature]:
        """Restore deleted features from backup records.

        :param fids: Feature ids to restore.
        :return: Restored features indexed by local feature id.
        """

        fids_str = ",".join(map(str, fids))
        backups: Dict[FeatureId, str] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            backups = {
                fid: backup
                for fid, backup in cursor.execute(f"""
                    SELECT fid, backup FROM ngw_removed_features
                    WHERE fid IN ({fids_str});
                """)
            }

        fields = QgsVectorLayer(
            detached_layer_uri(self._context), "", "ogr"
        ).fields()

        deleted_features = {}
        for fid in fids:
            backup = json.loads(backups[fid])
            attributes_after_sync = backup["after_sync"]["fields"]
            feature = QgsFeature(fields, fid)
            for field_id, value in attributes_after_sync:
                feature.setAttribute(
                    self._context.metadata.fields.get_with(
                        ngw_id=field_id
                    ).attribute,
                    value,
                )
            feature.setGeometry(
                deserialize_geometry(
                    backup["after_sync"]["geom"],
                    self._context.metadata.is_versioning_enabled,
                )
            )
            deleted_features[feature.id()] = feature

        return deleted_features

    def _extract_feature_changes_backups(
        self, locally_changed_fids: Sequence[QgsFeatureId]
    ) -> Tuple[
        Dict[Tuple[QgsFeatureId, FieldId], str], Dict[QgsFeatureId, str]
    ]:
        """Load backups for locally changed feature attributes and geometries.

        :param locally_changed_fids: Feature ids with local modifications.
        :return: Tuple of attribute backups and geometry backups.
        """

        if len(locally_changed_fids) == 0:
            return {}, {}

        joined_locally_changed_fids = ",".join(map(str, locally_changed_fids))
        fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str] = {}
        geometries_backups: Dict[QgsFeatureId, str] = {}
        with ContainerReadOnlySession(self._context) as cursor:
            fields_backups = self._extract_fields_changes_backups(
                cursor, joined_locally_changed_fids
            )
            geometries_backups = self._extract_geometries_changes_backups(
                cursor, joined_locally_changed_fids
            )
        return fields_backups, geometries_backups

    def _extract_fields_changes_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[Tuple[QgsFeatureId, FieldId], str]:
        """Load backed up attribute values for the specified features.

        :param cursor: Open database cursor.
        :param joined_fids: Comma-separated feature ids for SQL filtering.
        :return: Backed up attribute values indexed by feature and field id.
        """

        return {
            (fid, attribute): deserialize_value(backup)
            for fid, attribute, backup in cursor.execute(
                f"""
                SELECT fid, attribute, backup
                FROM ngw_updated_attributes
                WHERE fid IN ({joined_fids})
                """
            )
        }

    def _extract_geometries_changes_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[QgsFeatureId, str]:
        """Load backed up geometries for the specified features.

        :param cursor: Open database cursor.
        :param joined_fids: Comma-separated feature ids for SQL filtering.
        :return: Backed up geometries indexed by feature id.
        """

        return {
            fid: backup
            for fid, backup in cursor.execute(
                f"""
                SELECT fid, backup
                FROM ngw_updated_geometries
                WHERE fid IN ({joined_fids})
                """
            )
        }
