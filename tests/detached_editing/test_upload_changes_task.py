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

from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentSource,
)
from nextgis_connect.legacy.detached_editing.sync.common.upload_changes_task import (
    UploadChangesTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.versioned_changes_serializer import (
    VersionedChangesSerializer,
)
from nextgis_connect.shared.types import UnsetType
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import NgConnectTestCase, TestData


class TestUploadChangesTask(NgConnectTestCase):
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
