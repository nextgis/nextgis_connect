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

from unittest.mock import patch

from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadOnlySession,
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureCreation,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.transaction_changes_serializer import (
    TransactionChangesSerializer,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.versioned_changes_applier import (
    VersionedChangesApplier,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerContext,
    container_metadata,
)
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import NgConnectTestCase, TestData


class TestVersionedChangesApplier(NgConnectTestCase):
    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_confirms_mixed_transaction_and_can_replay_confirmation(
        self, container_mock, _qgs_layer
    ) -> None:
        path = container_mock.path
        with ContainerReadWriteSession(path) as cursor:
            cursor.executemany(
                "INSERT INTO ngw_features_metadata (fid, ngw_fid) VALUES (?, ?)",
                [(1001, None), (1002, 102), (1003, 103), (1004, 104)],
            )
            cursor.execute(
                "INSERT INTO ngw_features_descriptions (fid, description) "
                "VALUES (1002, 'edited description')"
            )
            for table, fid in (
                ("ngw_added_features", 1001),
                ("ngw_updated_geometries", 1002),
                ("ngw_updated_descriptions", 1002),
                ("ngw_restored_features", 1004),
            ):
                cursor.execute(f"INSERT INTO {table} (fid) VALUES (?)", (fid,))
            cursor.execute(
                "INSERT INTO ngw_removed_features (fid, backup) VALUES (1003, '{}')"
            )
            cursor.execute(
                "INSERT INTO ngw_updated_attributes (fid, attribute) "
                "SELECT 1002, MIN(attribute) FROM ngw_fields_metadata"
            )
            cursor.executemany(
                "INSERT INTO ngw_features_attachments "
                "(fid, aid, ngw_aid, fileobj) VALUES (1002, ?, ?, ?)",
                [
                    (1001, None, None),
                    (1002, 202, 502),
                    (1003, 203, None),
                    (1004, 204, 504),
                ],
            )
            for table, aid in (
                ("ngw_added_attachments", 1001),
                ("ngw_updated_attachments", 1002),
                ("ngw_restored_attachments", 1003),
                ("ngw_removed_attachments", 1004),
            ):
                cursor.execute(f"INSERT INTO {table} (aid) VALUES (?)", (aid,))

        changes = [
            FeatureCreation(fid=1001),
            FeatureUpdate(fid=1002, ngw_fid=102),
            FeatureDeletion(fid=1003, ngw_fid=103),
            FeatureRestoration(fid=1004, ngw_fid=104),
            DescriptionPut(fid=1002, ngw_fid=102),
            AttachmentCreation(fid=1002, aid=1001, ngw_fid=102),
            AttachmentUpdate(
                fid=1002, aid=1002, ngw_fid=102, ngw_aid=202, fileobj=502
            ),
            AttachmentRestoration(
                fid=1002, aid=1003, ngw_fid=102, ngw_aid=203
            ),
            AttachmentDeletion(
                fid=1002, aid=1004, ngw_fid=102, ngw_aid=204, fileobj=504
            ),
        ]
        result = list(
            enumerate(
                [
                    {"fid": 101},
                    {},
                    {},
                    {},
                    {},
                    {"aid": 201, "fileobj": 501},
                    {},
                    {"fileobj": 503},
                    {},
                ]
            )
        )
        context = DetachedContainerContext(path, container_mock.metadata)
        module = "nextgis_connect.legacy.detached_editing.sync.versioned.versioned_changes_applier"
        with patch(
            f"{module}.DetachedStorageServiceFactory.create"
        ) as storage:
            applier = VersionedChangesApplier(context)
            applier.apply(changes, result)
            self.assertEqual(applier.added_fids_mapping, {1001: 101})

            serializer = TransactionChangesSerializer()
            payload = serializer.to_json(serializer.from_changes(changes))
            with ContainerReadWriteSession(path) as cursor:
                cursor.execute(
                    "UPDATE ngw_metadata SET transaction_id=42, transaction_changes=?",
                    (payload,),
                )
            applier = VersionedChangesApplier(context)
            applier.apply_transaction(
                serializer.from_json(payload),
                result,
                commit_datetime="2026-10-08T12:00:00",
            )
            self.assertEqual(applier.added_fids_mapping, {1001: 101})

            storage.return_value.remove_attachment_cache.assert_any_call(
                context.metadata.instance_id,
                context.metadata.resource_id,
                1004,
                fileobj=504,
            )

        self.assertFalse(container_metadata(path).has_changes)
        self.assertIsNone(container_metadata(path).transaction_id)
        self.assertEqual(
            container_metadata(path).sync_date.isoformat(),
            "2026-10-08T12:00:00",
        )
        with ContainerReadOnlySession(path) as cursor:
            self.assertEqual(
                cursor.execute(
                    "SELECT fid, ngw_fid FROM ngw_features_metadata WHERE fid>=1001 ORDER BY fid"
                ).fetchall(),
                [(1001, 101), (1002, 102), (1004, 104)],
            )
            self.assertEqual(
                cursor.execute(
                    "SELECT aid, ngw_aid, fileobj FROM ngw_features_attachments "
                    "WHERE fid=1002 ORDER BY aid"
                ).fetchall(),
                [(1001, 201, 501), (1002, 202, 502), (1003, 203, 503)],
            )
