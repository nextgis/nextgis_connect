# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

import sqlite3
from contextlib import closing
from dataclasses import replace
from unittest.mock import MagicMock

from qgis.core import QgsVectorLayer

from nextgis_connect.legacy.detached_editing.attachment_files import (
    AttachmentFiles,
)
from nextgis_connect.legacy.detached_editing.change_journal import (
    DetachedChangeJournal,
)
from nextgis_connect.legacy.detached_editing.change_tracker import (
    DetachedChangeTracker,
    ExtensionChanges,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    serialize_geometry,
    serialize_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    make_connection,
)
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import NgConnectTestCase, TestData

ATTACHMENTS = [
    AttachmentMetadata(
        fid=1, aid=1, ngw_aid=1, name="first", mime_type="text/plain"
    ),
    AttachmentMetadata(
        fid=1, aid=2, ngw_aid=2, name="second", mime_type="text/plain"
    ),
]


class TestChangeJournal(NgConnectTestCase):
    def _files(self, metadata):
        storage = MagicMock()
        directory = self.create_temp_dir()
        storage.attachment_path.side_effect = lambda _, __, aid, **kwargs: (
            directory / f"{aid}.txt"
        )
        return AttachmentFiles(metadata, storage)

    def _batch(self, container, qgs_layer):
        attribute = qgs_layer.fields().indexOf("STRING")
        changes = DetachedChangeTracker(container.metadata)
        changes.added.add(999)
        changes.removed.add(2)
        changes.deleted_features[2] = qgs_layer.getFeature(2)
        changes.attributes[1] = {attribute}
        changes.attribute_backups[(1, attribute)] = serialize_value("original")
        changes.geometries.add(1)
        changes.geometry_backups[1] = serialize_geometry(
            qgs_layer.getFeature(1).geometry(),
            container.metadata.is_versioning_enabled,
        )
        source = self.create_temp_file(".txt")
        source.write_text("attachment content")
        extensions = ExtensionChanges(
            descriptions={1: "changed", 999: "new feature description"},
            added_attachments={
                999: {
                    -1: AttachmentMetadata(
                        fid=999,
                        aid=-1,
                        name="new.txt",
                        mime_type="text/plain",
                        file_path=source,
                    )
                }
            },
            updated_attachments={
                1: {1: replace(ATTACHMENTS[0], name="changed")}
            },
            removed_attachments={1: {2}},
        )
        return changes, extensions

    def _snapshot(self, path):
        with closing(make_connection(path)) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'ngw_%'"
                )
            ]
            return {
                table: connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
                for table in tables
            }

    @mock_container(
        TestData.Points,
        descriptions={1: "before", 2: "deleted"},
        attachments=ATTACHMENTS,
    )
    def test_every_metadata_failure_rolls_back_entire_batch(
        self, container: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        changes, extensions = self._batch(container, qgs_layer)
        before = self._snapshot(container.path)
        for table, operation in (
            ("ngw_features_metadata", "INSERT"),
            ("ngw_added_features", "INSERT"),
            ("ngw_updated_attributes", "INSERT"),
            ("ngw_updated_geometries", "INSERT"),
            ("ngw_removed_features", "INSERT"),
            ("ngw_features_descriptions", "DELETE"),
            ("ngw_features_descriptions", "UPDATE"),
            ("ngw_updated_descriptions", "INSERT"),
            ("ngw_features_attachments", "INSERT"),
            ("ngw_added_attachments", "INSERT"),
            ("ngw_removed_attachments", "INSERT"),
            ("ngw_features_attachments", "UPDATE"),
            ("ngw_updated_attachments", "INSERT"),
        ):
            with self.subTest(table=table, operation=operation):
                with closing(make_connection(container.path)) as connection:
                    connection.execute(
                        f"CREATE TRIGGER fail_batch BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'Injected journal failure'); END"
                    )
                    connection.commit()
                files = MagicMock(spec=AttachmentFiles)
                journal = DetachedChangeJournal(
                    container.path, container.metadata, files
                )
                with self.assertRaisesRegex(
                    sqlite3.IntegrityError, "Injected journal failure"
                ):
                    journal.write(changes, extensions)
                self.assertEqual(self._snapshot(container.path), before)
                files.register.assert_not_called()
                files.rollback.assert_called_once()
                with closing(make_connection(container.path)) as connection:
                    connection.execute("DROP TRIGGER fail_batch")
                    connection.commit()

    @mock_container(
        TestData.Points,
        descriptions={1: "before", 2: "deleted"},
        attachments=ATTACHMENTS,
    )
    def test_commit_failure_rolls_back_all_metadata_and_prepared_files(
        self, container: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        changes, extensions = self._batch(container, qgs_layer)
        before = self._snapshot(container.path)
        with closing(make_connection(container.path)) as connection:
            connection.execute(
                "CREATE TABLE commit_guard (fid INTEGER REFERENCES ngw_features_metadata(fid) DEFERRABLE INITIALLY DEFERRED)"
            )
            connection.execute(
                "CREATE TRIGGER fail_commit AFTER INSERT ON ngw_updated_attachments BEGIN INSERT INTO commit_guard VALUES (-999); END"
            )
            connection.commit()
        files = self._files(container.metadata)
        journal = DetachedChangeJournal(
            container.path, container.metadata, files
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            journal.write(changes, extensions)
        self.assertEqual(self._snapshot(container.path), before)
        self.assertEqual(files.prepared, [])
        source = extensions.added_attachments[999][-1].file_path
        self.assertEqual(source.read_text(), "attachment content")
        # A successful retry must be able to reuse the rolled-back attachment ID.
        with closing(make_connection(container.path)) as connection:
            connection.execute("DROP TRIGGER fail_commit")
            connection.commit()
        self.assertTrue(journal.write(changes, extensions))
        after = self._snapshot(container.path)
        self.assertEqual(after["ngw_added_features"], [(999,)])
        self.assertEqual(after["ngw_added_attachments"], [(3,)])
        self.assertEqual(
            [row[0] for row in after["ngw_removed_features"]], [2]
        )
        self.assertEqual(
            [row[0] for row in after["ngw_updated_attributes"]], [1]
        )
        self.assertEqual(
            [row[0] for row in after["ngw_updated_geometries"]], [1]
        )
        self.assertEqual(
            [row[0] for row in after["ngw_updated_descriptions"]], [1, 999]
        )
        self.assertEqual(
            [row[0] for row in after["ngw_removed_attachments"]], [2]
        )
        self.assertEqual(
            [row[0] for row in after["ngw_updated_attachments"]], [1]
        )
        destination = files.storage.attachment_path(
            container.metadata.instance_id, container.metadata.resource_id, 3
        )
        self.assertEqual(destination.read_text(), "attachment content")
        self.assertEqual(source.read_text(), "attachment content")

    @mock_container(
        TestData.Points,
        descriptions={1: "before", 2: "deleted"},
        attachments=ATTACHMENTS,
    )
    def test_other_connections_cannot_see_partial_metadata(
        self, container: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        changes, extensions = self._batch(container, qgs_layer)
        before = self._snapshot(container.path)
        files = MagicMock(spec=AttachmentFiles)
        files.prepare.side_effect = lambda attachment: self.assertEqual(
            self._snapshot(container.path), before
        )
        journal = DetachedChangeJournal(
            container.path, container.metadata, files
        )
        self.assertTrue(journal.write(changes, extensions))
        files.prepare.assert_called_once()
        self.assertNotEqual(self._snapshot(container.path), before)

    @mock_container(
        TestData.Points, descriptions={1: "before"}, attachments=ATTACHMENTS
    )
    def test_missing_attachment_source_rolls_back_metadata(
        self, container: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        changes, extensions = self._batch(container, qgs_layer)
        extensions.added_attachments[999][-1].file_path.unlink()
        before = self._snapshot(container.path)
        journal = DetachedChangeJournal(
            container.path, container.metadata, self._files(container.metadata)
        )
        with self.assertRaises(FileNotFoundError):
            journal.write(changes, extensions)
        self.assertEqual(self._snapshot(container.path), before)

    @mock_container(TestData.Points)
    def test_empty_batch_does_not_open_database(
        self, container: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        # An invalid path would fail immediately if a connection were opened.
        journal = DetachedChangeJournal(
            container.path / "missing", container.metadata
        )
        self.assertFalse(
            journal.write(
                DetachedChangeTracker(container.metadata), ExtensionChanges()
            )
        )
