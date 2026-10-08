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
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from nextgis_connect.legacy.detached_editing.container.container import (
    DetachedContainer,
)
from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentSource,
    FeatureCreation,
)
from nextgis_connect.legacy.detached_editing.sync.common.upload_changes_task import (
    UploadChangesTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.versioned_changes_serializer import (
    VersionedChangesSerializer,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedLayerState,
    container_metadata,
)
from nextgis_connect.shared.types import UnsetType
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import NgConnectTestCase, TestData


class TestUploadChangesTask(NgConnectTestCase):
    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_pending_confirmation_is_recovered_before_fetching_delta(
        self, container_mock: MagicMock, qgs_layer
    ) -> None:
        with ContainerReadWriteSession(container_mock.path) as cursor:
            cursor.execute(
                "UPDATE ngw_metadata SET epoch=1, version=1, transaction_id=42, "
                "transaction_changes='[]'"
            )
        container = DetachedContainer(container_mock.path)
        self.assertEqual(container.state, DetachedLayerState.NotSynchronized)
        module = "nextgis_connect.legacy.detached_editing.container.container"
        with patch(f"{module}.NgConnectInterface.instance"):
            container.add_layer(qgs_layer)
        self.assertTrue(qgs_layer.readOnly())
        container.set_edit_allowed(True)
        self.assertTrue(qgs_layer.readOnly())

        with patch(f"{module}.UploadChangesTask") as upload, patch(
            f"{module}.FetchDeltaTask"
        ) as fetch:
            task = cast(
                Any, container
            )._DetachedContainer__init_versioning_task()
        self.assertIs(task, upload.return_value)
        upload.assert_called_once_with(container_mock.path, recover_only=True)
        fetch.assert_not_called()

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_interrupted_transaction_resumes_without_duplicate_creation(
        self, container_mock: MagicMock, _qgs_layer
    ) -> None:
        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "upload_changes_task"
        )
        for failure in ("commit", "result", "local", "completion"):
            with self.subTest(failure=failure):
                with ContainerReadWriteSession(container_mock.path) as cursor:
                    cursor.execute(
                        "UPDATE ngw_metadata SET epoch=1, version=1"
                    )
                    cursor.execute(
                        "UPDATE ngw_features_metadata SET ngw_fid=NULL WHERE fid=1"
                    )
                    cursor.execute(
                        "INSERT INTO ngw_added_features (fid) VALUES (1)"
                    )
                    if failure == "local":
                        cursor.execute(
                            "CREATE TRIGGER fail_confirmation BEFORE DELETE "
                            "ON ngw_added_features BEGIN "
                            "SELECT RAISE(ABORT, 'confirmation failed'); END"
                        )
                    if failure == "completion":
                        cursor.execute(
                            "CREATE TRIGGER fail_completion BEFORE UPDATE OF transaction_id "
                            "ON ngw_metadata WHEN NEW.transaction_id IS NULL BEGIN "
                            "SELECT RAISE(ABORT, 'completion failed'); END"
                        )
                before = container_metadata(container_mock.path)
                connection = MagicMock()
                committed = {
                    "status": "committed",
                    "committed": "2026-10-08T12:00:00",
                }
                connection.post.side_effect = [
                    {"id": 42, "started": "2026-10-08T11:59:00"},
                    RuntimeError("Lost commit reply")
                    if failure == "commit"
                    else committed,
                ]
                connection.get.return_value = [[0, {"fid": 101}]]
                if failure == "result":
                    connection.get.side_effect = RuntimeError("Lost result")
                task = UploadChangesTask(container_mock.path)
                with patch(
                    f"{module}.QgsNgwConnection", return_value=connection
                ), patch.object(
                    task,
                    "_UploadChangesTask__extract_and_prepare_versioned_changes",
                    return_value=[[FeatureCreation(fid=1)]],
                ):
                    self.assertFalse(task.run())

                metadata = container_metadata(container_mock.path)
                if metadata.transaction_id is None and task.error is not None:
                    raise task.error
                self.assertEqual(metadata.transaction_id, 42, str(task.error))
                self.assertEqual(metadata.sync_date, before.sync_date)
                self.assertTrue(metadata.has_changes)
                connection.delete.assert_not_called()
                with ContainerReadWriteSession(container_mock.path) as cursor:
                    if failure in ("local", "completion"):
                        # The earlier NGW fid update must also roll back.
                        self.assertIsNone(
                            cursor.execute(
                                "SELECT ngw_fid FROM ngw_features_metadata WHERE fid=1"
                            ).fetchone()[0],
                        )
                        self.assertEqual(
                            cursor.execute(
                                "SELECT fid FROM ngw_added_features"
                            ).fetchall(),
                            [(1,)],
                        )
                        trigger = (
                            "fail_confirmation"
                            if failure == "local"
                            else "fail_completion"
                        )
                        cursor.execute(f"DROP TRIGGER {trigger}")

                connection.reset_mock()
                connection.post.side_effect = None
                connection.post.return_value = committed
                connection.get.side_effect = None
                retry = UploadChangesTask(
                    container_mock.path, recover_only=True
                )
                with patch(
                    f"{module}.QgsNgwConnection", return_value=connection
                ):
                    self.assertTrue(retry.run(), retry.error)

                connection.post.assert_called_once_with(
                    f"/api/resource/{metadata.resource_id}/feature/transaction/42",
                    is_lunkwill=True,
                )
                connection.put.assert_not_called()
                connection.delete.assert_not_called()
                metadata = container_metadata(container_mock.path)
                self.assertIsNone(metadata.transaction_id)
                self.assertFalse(metadata.has_changes)
                self.assertEqual(
                    metadata.sync_date.isoformat(), committed["committed"]
                )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_new_attachment_uses_file_upload_metadata(
        self, container_mock: MagicMock, _qgs_layer
    ) -> None:
        task = UploadChangesTask(container_mock.path)
        change = AttachmentCreation(
            fid=1,
            ngw_fid=101,
            aid=-1,
            name="max.jpg",
            mime_type="",
        )
        storage_service = MagicMock()
        storage_service.attachment_path.return_value = Path("/cache/max.jpg")
        connection = MagicMock()
        connection.tus_upload_file.return_value = {
            "id": "upload-id",
            "name": "max.jpg",
            "size": 100256,
            "mime_type": "image/jpeg",
        }
        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "upload_changes_task"
        )

        with patch(
            f"{module}.DetachedStorageServiceFactory.create",
            return_value=storage_service,
        ):
            upload_task = cast(Any, task)
            upload_task._UploadChangesTask__upload_attachments_and_patch_changes(
                connection,
                [change],
            )

        upload_call = connection.tus_upload_file.call_args
        self.assertEqual(upload_call.args[0], "/cache/max.jpg")
        self.assertEqual(upload_call.kwargs["upload_name"], "max.jpg")
        assert not isinstance(change.source, UnsetType)
        self.assertEqual(change.source.data, {"id": "upload-id"})

        serializer = VersionedChangesSerializer(container_mock.metadata)
        self.assertEqual(
            json.loads(serializer.to_json([change])),
            [
                [
                    0,
                    {
                        "action": "attachment.create",
                        "fid": 101,
                        "source": {
                            "type": "file_upload",
                            "id": "upload-id",
                        },
                    },
                ]
            ],
        )

    @mock_container(TestData.Points)
    def test_new_attachment_feature_api_payload_uses_upload_metadata(
        self, container_mock: MagicMock, _qgs_layer
    ) -> None:
        task = UploadChangesTask(container_mock.path)
        change = AttachmentCreation(
            fid=1,
            ngw_fid=101,
            aid=-1,
            source=AttachmentSource(
                source_type="file_upload",
                data={"id": "upload-id"},
            ),
            name="max.jpg",
            mime_type="image/jpeg",
        )
        extractor = MagicMock()
        extractor.extract_added_attachments.return_value = [change]
        changes_applier = MagicMock()
        connection = MagicMock()
        connection.post.return_value = {"id": 1}
        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "upload_changes_task"
        )

        with patch(
            f"{module}.ChangesExtractor", return_value=extractor
        ), patch(
            f"{module}.FeatureApiChangesApplier",
            return_value=changes_applier,
        ), patch.object(
            task,
            "_UploadChangesTask__upload_attachments_and_patch_changes",
        ):
            upload_task = cast(Any, task)
            upload_task._UploadChangesTask__added_fids_mapping = {}
            self.assertTrue(
                upload_task._UploadChangesTask__upload_added_attachments(
                    connection
                )
            )

        connection.post.assert_called_once_with(
            f"/api/resource/{container_mock.metadata.resource_id}/feature/101/attachment/",
            {"file_upload": {"id": "upload-id"}},
        )
