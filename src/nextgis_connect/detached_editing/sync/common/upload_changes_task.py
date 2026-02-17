from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from nextgis_connect.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentRestoration,
    AttachmentSource,
    AttachmentUpdate,
    DescriptionPut,
    FeatureChange,
)
from nextgis_connect.detached_editing.sync.common.changes_extractor import (
    ChangesExtractor,
)
from nextgis_connect.detached_editing.sync.common.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.detached_editing.sync.non_versioned import (
    FeatureApiChangesApplier,
    FeatureApiChangesSerializer,
)
from nextgis_connect.detached_editing.sync.versioned.versioned_changes_applier import (
    VersionedChangesApplier,
)
from nextgis_connect.detached_editing.sync.versioned.versioned_changes_serializer import (
    VersionedChangesSerializer,
)
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from nextgis_connect.types import (
    FeatureId,
    NgwAttachmentId,
    NgwFeatureId,
    Unset,
    UnsetType,
)


class UploadChangesTask(DetachedEditingTask):
    BATCH_SIZE = 1000

    def __init__(self, container_path: Path) -> None:
        super().__init__(container_path)
        if self._error is not None:
            return

        description = self.tr('"{layer_name}" layer synchronization').format(
            layer_name=self._metadata.layer_name
        )
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(
            f"<b>Started changes uploading</b> for layer {self._metadata}"
        )

        self.__added_fids_mapping: Dict[FeatureId, NgwFeatureId] = {}

        try:
            self.__upload_changes()

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = f"An error occurred while uploading changes for {self._metadata}"
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True

    def __upload_changes(self) -> None:
        ngw_connection = QgsNgwConnection(self._metadata.connection_id)

        if self._metadata.is_versioning_enabled:
            use_transaction_for_extensions = (
                True  # TODO replace with version check
            )
            split_transaction_for_new_features = (
                True  # TODO replace with version check
            )
            self.__upload_versioned_changes(
                ngw_connection,
                skip_extensions=not use_transaction_for_extensions,
                split_transaction_for_new_features=(
                    split_transaction_for_new_features
                ),
            )
            if not use_transaction_for_extensions:
                self.__upload_extensions_with_feature_api(ngw_connection)
        else:
            self.__upload_not_versioned_changes(ngw_connection)
            self.__upload_extensions_with_feature_api(ngw_connection)

    def __upload_added(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        feature_creation_changes = extractor.extract_added_features()

        if len(feature_creation_changes) == 0:
            return

        logger.debug(f"Found {len(feature_creation_changes)} new features")

        serializer = FeatureApiChangesSerializer(layer_metadata)
        changes_applier = FeatureApiChangesApplier(self._context)

        resource_id = layer_metadata.resource_id
        url = f"/api/resource/{resource_id}/feature/?geom_null=true&dt_format=iso"

        iterator = iter(feature_creation_changes)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            body = serializer.to_json(batch)

            logger.debug(f"Create {len(batch)} features")

            operation_result: List[Dict[str, Any]] = ngw_connection.patch(
                url, body
            )
            changes_applier.apply(batch, operation_result)

            batch = tuple(islice(iterator, self.BATCH_SIZE))

        self.__added_fids_mapping = changes_applier.added_fids_mapping

    def __upload_deleted(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        feature_deletion_changes = extractor.extract_deleted_features()

        if len(feature_deletion_changes) == 0:
            return

        logger.debug(
            f"Found {len(feature_deletion_changes)} features to delete"
        )

        serializer = FeatureApiChangesSerializer(layer_metadata)
        changes_applier = FeatureApiChangesApplier(self._context)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"

        iterator = iter(feature_deletion_changes)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            body = serializer.to_json(batch)

            logger.debug(f"Delete {len(batch)} features")

            ngw_connection.delete(url, body)

            changes_applier.apply(batch)

            batch = tuple(islice(iterator, self.BATCH_SIZE))

    def __upload_updated(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> bool:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        feature_update_changes = extractor.extract_updated_features()

        if len(feature_update_changes) == 0:
            return False

        logger.debug(f"Found {len(feature_update_changes)} updated features")

        serializer = FeatureApiChangesSerializer(layer_metadata)
        changes_applier = FeatureApiChangesApplier(self._context)

        resource_id = layer_metadata.resource_id
        url = f"/api/resource/{resource_id}/feature/?geom_null=true&dt_format=iso"

        iterator = iter(feature_update_changes)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            body = serializer.to_json(batch)

            logger.debug(f"Update {len(batch)} features")

            ngw_connection.patch(url, body)

            changes_applier.apply(batch)

            batch = tuple(islice(iterator, self.BATCH_SIZE))

        return True

    def __upload_descriptions(self, ngw_connection: QgsNgwConnection) -> bool:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        updated_descriptions = extractor.extract_updated_descriptions()

        if len(updated_descriptions) == 0:
            return False

        logger.debug(f"Found {len(updated_descriptions)} description updates")

        serializer = FeatureApiChangesSerializer(layer_metadata)
        changes_applier = FeatureApiChangesApplier(self._context)

        resource_id = layer_metadata.resource_id
        url = f"/api/resource/{resource_id}/feature/"

        self.__patch_new_feature_fids(updated_descriptions)

        iterator = iter(updated_descriptions)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            body = serializer.to_json(batch)

            logger.debug(f"Apply {len(batch)} description updates")

            ngw_connection.patch(url, body)

            changes_applier.apply(batch)

            batch = tuple(islice(iterator, self.BATCH_SIZE))

        return True

    def __upload_added_attachments(
        self, ngw_connection: QgsNgwConnection
    ) -> bool:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        added_attachments_changes = extractor.extract_added_attachments()

        if len(added_attachments_changes) == 0:
            return False

        logger.debug(f"Found {len(added_attachments_changes)} new attachments")

        changes_applier = FeatureApiChangesApplier(self._context)

        resource_id = layer_metadata.resource_id
        feature_url = f"/api/resource/{resource_id}/feature"

        self.__upload_attachments_and_patch_changes(
            ngw_connection, added_attachments_changes
        )

        for change in added_attachments_changes:
            logger.debug(
                f"Creating attachment {change.aid} for feature {change.ngw_fid}"
            )

            if change.fid in self.__added_fids_mapping:
                change.ngw_fid = self.__added_fids_mapping[change.fid]

            assert not isinstance(change.source, UnsetType)
            payload = {
                "keyname": change.keyname,
                "name": change.name,
                "description": change.description,
                "file_upload": change.source.data,
                "mime_type": change.mime_type,
            }
            url = f"{feature_url}/{change.ngw_fid}/attachment/"
            result = ngw_connection.post(url, payload)

            changes_applier.apply([change], [result])

        return True

    def __upload_deleted_attachments(
        self, ngw_connection: QgsNgwConnection
    ) -> bool:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        deleted_attachments_changes = extractor.extract_deleted_attachments()

        if len(deleted_attachments_changes) == 0:
            return False

        logger.debug(
            f"Found {len(deleted_attachments_changes)} deleted attachments"
        )

        resource_id = layer_metadata.resource_id
        feature_url = f"/api/resource/{resource_id}/feature"

        changes_applier = FeatureApiChangesApplier(self._context)

        # Small optimization for single attachment delete
        if len(deleted_attachments_changes) == 1:
            logger.debug(
                f"Delete attachment {deleted_attachments_changes[0].ngw_aid}"
                f" of feature {deleted_attachments_changes[0].ngw_fid}"
            )
            change = deleted_attachments_changes[0]
            url = f"{feature_url}/{change.ngw_fid}/attachment/{change.ngw_aid}"
            ngw_connection.delete(url)
            changes_applier.apply(deleted_attachments_changes)
            return True

        # Collect feature ids and attachments to delete
        feature_ids: Set[FeatureId] = set()
        deleted_attachments_for_feature: Dict[
            NgwFeatureId, Set[NgwAttachmentId]
        ] = dict()
        for change in deleted_attachments_changes:
            feature_ids.add(change.ngw_fid)
            if change.ngw_fid not in deleted_attachments_for_feature:
                deleted_attachments_for_feature[change.ngw_fid] = set()
            deleted_attachments_for_feature[change.ngw_fid].add(change.ngw_aid)

        # Get current attachments for features and filter deleted ones
        payload = list()
        for feature_id in feature_ids:
            url = f"{feature_url}/{feature_id}/attachment/"
            feature_attachments = ngw_connection.get(url)
            updated_attachments = [
                attachment
                for attachment in feature_attachments
                if attachment["id"]
                not in deleted_attachments_for_feature[feature_id]
            ]
            payload.append(
                {
                    "id": feature_id,
                    "extensions": {"attachment": updated_attachments},
                }
            )

        iterator = iter(payload)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            logger.debug(f"Delete attachments for {len(batch)} features")

            ngw_connection.patch(f"{feature_url}/", batch)

            batch = tuple(islice(iterator, self.BATCH_SIZE))

        changes_applier.apply(deleted_attachments_changes)

        return True

    def __upload_updated_attachments(
        self, ngw_connection: QgsNgwConnection
    ) -> bool:
        layer_metadata = self._metadata

        extractor = ChangesExtractor(self._context)
        attachments_updates = extractor.extract_updated_attachments()

        if len(attachments_updates) == 0:
            return False

        logger.debug(f"Found {len(attachments_updates)} updated attachments")

        resource_id = layer_metadata.resource_id
        feature_url = f"/api/resource/{resource_id}/feature"

        changes_applier = FeatureApiChangesApplier(self._context)

        self.__upload_attachments_and_patch_changes(
            ngw_connection, attachments_updates
        )

        # Small optimization for single attachment update
        if len(attachments_updates) == 1:
            logger.debug(
                f"Update attachment {attachments_updates[0].ngw_aid} of "
                f"feature {attachments_updates[0].ngw_fid}"
            )
            change = attachments_updates[0]
            url = f"{feature_url}/{change.ngw_fid}/attachment/{change.ngw_aid}"
            single_payload: Dict[str, Any] = {
                "name": change.name,
                "description": change.description,
            }
            if change.source is not Unset:
                single_payload["file_upload"] = change.source

            ngw_connection.put(url, single_payload)
            changes_applier.apply(attachments_updates)
            return True

        # Collect feature ids and attachments to update
        feature_ids: Set[FeatureId] = set()
        updated_attachments_for_feature: Dict[
            NgwFeatureId,
            Dict[
                NgwAttachmentId,
                Tuple[Union[str, UnsetType], Union[str, UnsetType]],
            ],
        ] = dict()
        for change in attachments_updates:
            feature_ids.add(change.ngw_fid)
            if change.ngw_fid not in updated_attachments_for_feature:
                updated_attachments_for_feature[change.ngw_fid] = dict()
            updated_attachments_for_feature[change.ngw_fid][change.ngw_aid] = (
                change.name,
                change.description,
            )

        # Get current attachments for features and update them
        payload = list()
        for feature_id in feature_ids:
            url = f"{feature_url}/{feature_id}/attachment/"
            feature_attachments = ngw_connection.get(url)

            for attachment in feature_attachments:
                aid = attachment["id"]
                if aid in updated_attachments_for_feature[feature_id]:
                    name, description = updated_attachments_for_feature[
                        feature_id
                    ][aid]
                    attachment["name"] = name or ""
                    attachment["description"] = description or ""

            payload.append(
                {
                    "id": feature_id,
                    "extensions": {"attachment": feature_attachments},
                }
            )

        iterator = iter(payload)
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            logger.debug(f"Update {len(batch)} features with attachments")
            ngw_connection.patch(f"{feature_url}/", batch)
            batch = tuple(islice(iterator, self.BATCH_SIZE))

        changes_applier.apply(attachments_updates)

        return True

    def __extract_and_prepare_versioned_changes(
        self,
        connection: QgsNgwConnection,
        skip_extensions: bool = False,
        split_extensions_for_new_features: bool = True,
    ) -> List[List[FeatureChange]]:
        extractor = ChangesExtractor(self._context)

        feature_changes = extractor.extract_features_changes()
        updated_descriptions = []
        added_attachments = []
        deleted_attachments = []
        updated_attachments = []
        restored_attachments = []
        if not skip_extensions:
            updated_descriptions = extractor.extract_updated_descriptions()
            added_attachments = extractor.extract_added_attachments()
            deleted_attachments = extractor.extract_deleted_attachments()
            updated_attachments = extractor.extract_updated_attachments()
            restored_attachments = extractor.extract_restored_attachments()

        total_changes_count = (
            len(feature_changes)
            + len(updated_descriptions)
            + len(added_attachments)
            + len(deleted_attachments)
            + len(updated_attachments)
            + len(restored_attachments)
        )
        if total_changes_count == 0:
            return []

        logger.debug(f"Found {total_changes_count} pending changes")

        self.__upload_attachments_and_patch_changes(
            connection,
            added_attachments,
        )
        self.__upload_attachments_and_patch_changes(
            connection,
            restored_attachments,
        )

        first_transaction_changes: List[FeatureChange] = feature_changes
        second_transaction_changes: List[FeatureChange] = []

        if not split_extensions_for_new_features:
            raise NotImplementedError
        for changes_pack in (updated_descriptions, added_attachments):
            for change in changes_pack:
                if change.is_feature_new:
                    second_transaction_changes.append(change)
                else:
                    first_transaction_changes.append(change)

        first_transaction_changes.extend(deleted_attachments)
        first_transaction_changes.extend(updated_attachments)
        first_transaction_changes.extend(restored_attachments)

        if not second_transaction_changes:
            return [first_transaction_changes]

        return [first_transaction_changes, second_transaction_changes]

    def __upload_versioned_changes(
        self,
        connection: QgsNgwConnection,
        skip_extensions: bool = False,
        split_transaction_for_new_features: bool = True,
    ) -> None:
        splitted_changes = self.__extract_and_prepare_versioned_changes(
            connection,
            skip_extensions=skip_extensions,
            split_extensions_for_new_features=split_transaction_for_new_features,
        )
        if not splitted_changes:
            return

        commit_datetime = None
        for changes in splitted_changes:
            self.__patch_new_feature_fids(changes)
            commit_datetime = self.__upload_with_transaction(
                connection, changes
            )

        self.__update_sync_date(commit_datetime=commit_datetime)

    def __upload_not_versioned_changes(
        self, connection: QgsNgwConnection
    ) -> None:
        # Check structure etc
        self._get_layer(connection)

        # Uploading
        self.__upload_deleted(connection)
        self.__upload_added(connection)
        self.__upload_updated(connection)
        self.__update_sync_date()

    def __upload_extensions_with_feature_api(
        self, connection: QgsNgwConnection
    ) -> None:
        has_descriptions = self.__upload_descriptions(connection)
        has_added_attachments = self.__upload_added_attachments(connection)
        has_deleted_attachments = self.__upload_deleted_attachments(connection)
        has_updated_attachments = self.__upload_updated_attachments(connection)

        if (
            has_descriptions
            or has_added_attachments
            or has_deleted_attachments
            or has_updated_attachments
        ):
            self.__update_sync_date()

    def __patch_new_feature_fids(
        self,
        changes: Sequence[FeatureChange],
    ) -> None:
        if len(self.__added_fids_mapping) == 0:
            return

        for change in changes:
            if (
                not isinstance(change, (DescriptionPut, AttachmentCreation))
                or not change.is_feature_new
            ):
                continue

            change.ngw_fid = self.__added_fids_mapping[change.fid]

    def __upload_attachments_and_patch_changes(
        self,
        ngw_connection: QgsNgwConnection,
        changes: Sequence[
            Union[AttachmentCreation, AttachmentUpdate, AttachmentRestoration]
        ],
    ) -> None:
        cache_manager = NgConnectCacheManager()

        for change in changes:
            if (
                isinstance(change, (AttachmentUpdate, AttachmentRestoration))
                and not change.is_file_new
            ):
                continue

            path = cache_manager.attachment_path(
                self._metadata.instance_id,
                self._metadata.resource_id,
                change.aid,
                file_name=change.name
                if not isinstance(change.name, UnsetType)
                else None,
                mime_type=change.mime_type
                if not isinstance(change.mime_type, UnsetType)
                else None,
            )

            uploaded_file = ngw_connection.tus_upload_file(
                str(path), lambda _1=None, _2=None, _3=None: None
            )

            change.source = AttachmentSource(
                source_type="file_upload", data=uploaded_file
            )
            change.source.data.pop("name")  # Drop auto-generated name

    def __upload_with_transaction(
        self,
        connection: QgsNgwConnection,
        changes: List[FeatureChange],
    ) -> str:
        layer_metadata = self._metadata
        resource_id = layer_metadata.resource_id
        resource_url = f"/api/resource/{resource_id}"

        transaction_answer = self.__create_transaction(connection, resource_id)
        transaction_id = transaction_answer["id"]
        transaction_start_time = transaction_answer["started"]

        logger.debug(
            f"Transaction {transaction_id} started at {transaction_start_time}"
        )

        serializer = VersionedChangesSerializer(layer_metadata)

        iterator = iter(changes)
        last_change_number = 0
        batch = tuple(islice(iterator, self.BATCH_SIZE))
        while batch:
            body = serializer.to_json(
                batch, last_action_number=last_change_number
            )

            logger.debug(f"Apply {len(batch)} changes")

            connection.put(
                f"{resource_url}/feature/transaction/{transaction_id}",
                body,
            )

            last_change_number += len(batch)
            batch = tuple(islice(iterator, self.BATCH_SIZE))

        commit_datetime, transaction_result = self.__commit_transaction(
            connection, resource_id, transaction_id
        )

        transaction_applier = VersionedChangesApplier(self._context)
        transaction_applier.apply(changes, transaction_result)

        self.__added_fids_mapping = transaction_applier.added_fids_mapping

        return commit_datetime

    def __create_transaction(
        self, connection: QgsNgwConnection, resource_id: int
    ) -> Dict[str, Any]:
        transaction_answer = connection.post(
            f"/api/resource/{resource_id}/feature/transaction/",
            dict(epoch=self._metadata.epoch),
        )
        return transaction_answer

    def __commit_transaction(
        self,
        connection: QgsNgwConnection,
        resource_id: int,
        transaction_id: int,
    ) -> Tuple[str, Sequence]:
        logger.debug(f"Commit transaction {transaction_id}")

        resource_url = f"/api/resource/{resource_id}"

        try:
            result = connection.post(
                f"{resource_url}/feature/transaction/{transaction_id}",
                is_lunkwill=True,
            )
        except Exception:
            logger.exception("Exception occurred while commiting transaction")
            connection.delete(
                f"{resource_url}/feature/transaction/{transaction_id}"
            )
            logger.debug(f"Transaction {transaction_id} disposed")
            raise

        if result["status"] != "committed":
            error = SynchronizationError("Transaction is not committed")
            error.add_note(f"Synchronization id: {transaction_id}")
            error.add_note(f"Status: {result['status']}")
            if "errors" in result:
                error.add_note(f"Error: {result['errors']}")
            raise error

        transaction_result = connection.get(
            f"{resource_url}/feature/transaction/{transaction_id}"
        )
        return result["committed"], transaction_result

    def __update_sync_date(
        self, *, commit_datetime: Optional[str] = None
    ) -> None:
        if commit_datetime is None:
            sync_date = datetime.now().isoformat()
        else:
            sync_date = commit_datetime

        with ContainerReadWriteSession(self._context) as cursor:
            cursor.execute(f"UPDATE ngw_metadata SET sync_date='{sync_date}'")
