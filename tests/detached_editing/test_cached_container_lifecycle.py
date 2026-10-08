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

import shutil
import sqlite3
import uuid
from contextlib import closing
from unittest.mock import MagicMock

from qgis.core import QgsProject, QgsVectorLayer

from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_import import (
    QgisResourceBatchImporter,
)
from nextgis_connect.features.synchronization.infrastructure.storage.cache_maintenance_service import (
    CacheMaintenanceService,
)
from nextgis_connect.features.synchronization.infrastructure.storage.detached_storage_service import (
    DetachedStorageService,
)
from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadOnlySession,
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.container.migrations import (
    ContainerMigrator,
)
from nextgis_connect.legacy.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
    make_connection,
)
from nextgis_connect.legacy.ngw_connection import (
    NgwConnection,
    NgwConnectionsManager,
)
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.filesystem import cp
from nextgis_connect.platform.qgis.errors import ContainerError
from tests.detached_editing.utils import (
    copy_legacy_36_points_container,
    mark_container_changed,
    mock_container,
    set_container_connection_metadata,
    set_container_version,
)
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestConnection,
    TestData,
)


class TestCachedContainerLifecycle(NgConnectTestCase):
    @mock_container(TestData.Points)
    def test_migrates_current_container_preserving_local_changes(
        self, container_mock: MagicMock, _qgs_layer
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        path = self._move_to_cache(container_mock)
        with ContainerReadWriteSession(path) as cursor:
            cursor.execute(
                "ALTER TABLE ngw_metadata DROP COLUMN transaction_changes"
            )
            cursor.execute("UPDATE ngw_metadata SET container_version='3.0.0'")
        mark_container_changed(path)
        before = container_metadata(path)

        self._collect_detached_layer_params(ngw_layer)
        ContainerMigrator().migrate(path)

        after = container_metadata(path)
        self.assertEqual(after.container_version, "3.1.0")
        self.assertTrue(after.has_changes)
        self.assertEqual(after.features_count, before.features_count)
        self.assertEqual(after.sync_date, before.sync_date)
        self.assertEqual(after.version, before.version)
        self.assertEqual(after.epoch, before.epoch)

    @mock_container(TestData.Points)
    def test_failed_migration_rolls_back_schema_and_version(
        self, container_mock: MagicMock, _qgs_layer
    ) -> None:
        path = container_mock.path
        with ContainerReadWriteSession(path) as cursor:
            cursor.execute(
                "ALTER TABLE ngw_metadata DROP COLUMN transaction_changes"
            )
            cursor.execute("UPDATE ngw_metadata SET container_version='3.0.0'")
            cursor.execute(
                "CREATE TRIGGER fail_migration BEFORE UPDATE ON ngw_metadata "
                "BEGIN SELECT RAISE(ABORT, 'migration failed'); END"
            )

        with self.assertRaises(ContainerError) as raised:
            ContainerMigrator().migrate(path)
        self.assertIsInstance(
            raised.exception.__cause__, sqlite3.IntegrityError
        )

        with ContainerReadOnlySession(path) as cursor:
            self.assertEqual(
                cursor.execute(
                    "SELECT container_version FROM ngw_metadata"
                ).fetchone()[0],
                "3.0.0",
            )
            self.assertNotIn(
                "transaction_changes",
                [
                    row[1]
                    for row in cursor.execute(
                        "PRAGMA table_info(ngw_metadata)"
                    )
                ],
            )

    def setUp(self) -> None:
        super().setUp()
        self.cache_directory = self.create_temp_dir("-Cache")
        CacheMaintenanceService().cache_directory = str(self.cache_directory)

    def tearDown(self) -> None:
        shutil.rmtree(str(self.cache_directory))
        super().tearDown()

    @mock_container(TestData.Points)
    def test_tree_add_rebinds_cached_container_after_connection_migration(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._move_to_cache(container_mock)
        obsolete_connection_id = str(uuid.uuid4())
        set_container_connection_metadata(
            container_path,
            connection_id=obsolete_connection_id,
        )

        layer_params = self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)
        self.assertFalse(metadata.has_changes)
        self.assertEqual(
            layer_params,
            (
                detached_layer_uri(container_path),
                ngw_layer.display_name,
                "ogr",
            ),
        )

    @mock_container(TestData.Points)
    def test_tree_add_rebinds_cached_container_with_local_changes(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._move_to_cache(container_mock)
        obsolete_connection_id = str(uuid.uuid4())
        set_container_connection_metadata(
            container_path,
            connection_id=obsolete_connection_id,
        )
        mark_container_changed(container_path)

        self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertTrue(metadata.has_changes)

    @mock_container(TestData.Points)
    def test_tree_add_recreates_outdated_cached_container_without_changes(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        container_path = self._move_to_cache(container_mock)
        set_container_version(container_path, "0.1.0")

        self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertEqual(
            metadata.container_version,
            NgConnectSettings().supported_container_version,
        )
        self.assertTrue(metadata.is_not_initialized)
        self.assertEqual(metadata.features_count, 0)

    def test_tree_add_recreates_old_schema_cached_container_without_changes(
        self,
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._storage_service().ensure_container_placeholder(
            connection.domain_uuid,
            ngw_layer.resource_id,
        )
        copy_legacy_36_points_container(container_path)
        set_container_connection_metadata(
            container_path,
            connection_id=connection.id,
            instance_id=connection.domain_uuid,
        )

        self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertTrue(metadata.is_schema_complete)
        self.assertTrue(metadata.is_not_initialized)
        self.assertEqual(metadata.features_count, 0)

    def test_tree_add_preserves_old_schema_cached_container_with_changes(
        self,
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._storage_service().ensure_container_placeholder(
            connection.domain_uuid,
            ngw_layer.resource_id,
        )
        copy_legacy_36_points_container(container_path)
        set_container_connection_metadata(
            container_path,
            connection_id=connection.id,
            instance_id=connection.domain_uuid,
        )
        mark_container_changed(container_path)

        layer_params = self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertFalse(metadata.is_schema_complete)
        self.assertTrue(metadata.has_changes)
        self.assertEqual(
            layer_params,
            (
                detached_layer_uri(container_path),
                ngw_layer.display_name,
                "ogr",
            ),
        )

    @mock_container(TestData.Points)
    def test_tree_add_recreates_broken_cached_container_without_user_error(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        ngw_layer = self.resource(TestData.Points)
        container_path = self._move_to_cache(container_mock)
        with closing(make_connection(container_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE gpkg_contents")
            connection.commit()

        layer_params = self._collect_detached_layer_params(ngw_layer)

        metadata = container_metadata(container_path)
        self.assertTrue(metadata.is_not_initialized)
        self.assertEqual(metadata.features_count, 0)
        self.assertEqual(
            layer_params,
            (
                detached_layer_uri(container_path),
                ngw_layer.display_name,
                "ogr",
            ),
        )

    @mock_container(TestData.Points)
    def test_tree_add_rebinds_container_after_connection_recreation(
        self,
        container_mock: MagicMock,
        _qgs_layer: QgsVectorLayer,
    ) -> None:
        base_connection = self.connection(TestConnection.SandboxGuest)
        resource = self.resource(TestData.Points, base_connection)
        old_connection = NgwConnection(
            str(uuid.uuid4()),
            "Deleted connection",
            base_connection.url,
            None,
        )
        new_connection = NgwConnection(
            NgwConnection.domain_uuid_for_url(base_connection.url),
            "Recreated connection",
            base_connection.url,
            None,
        )
        self.assertNotEqual(old_connection.id, new_connection.id)
        self.assertEqual(
            old_connection.domain_uuid,
            new_connection.domain_uuid,
        )

        manager = NgwConnectionsManager()
        saved_connections = manager.connections
        saved_current_connection_id = manager.current_connection_id

        try:
            manager.replace_connections([old_connection])
            manager.current_connection_id = old_connection.id
            manager.save()

            container_path = (
                self._storage_service().ensure_container_placeholder(
                    old_connection.domain_uuid,
                    resource.resource_id,
                )
            )
            container_path.parent.mkdir(exist_ok=True, parents=True)
            cp(container_mock.path, container_path)
            set_container_connection_metadata(
                container_path,
                connection_id=old_connection.id,
                instance_id=old_connection.domain_uuid,
            )

            project_layer = QgsVectorLayer(
                detached_layer_uri(container_path),
                "cached layer",
                "ogr",
            )
            self.assertTrue(project_layer.isValid())
            QgsProject.instance().addMapLayer(project_layer)
            QgsProject.instance().removeMapLayer(project_layer.id())

            manager.remove(old_connection.id)
            manager.save()
            manager.upsert(new_connection)
            manager.current_connection_id = new_connection.id
            manager.save()

            ngw_layer = self.resource(TestData.Points, new_connection)
            layer_params = self._collect_detached_layer_params(ngw_layer)

            metadata = container_metadata(container_path)
            self.assertEqual(metadata.connection_id, new_connection.id)
            self.assertEqual(metadata.instance_id, new_connection.domain_uuid)
            self.assertEqual(
                layer_params,
                (
                    detached_layer_uri(container_path),
                    ngw_layer.display_name,
                    "ogr",
                ),
            )
        finally:
            manager.replace_connections(saved_connections)
            manager.current_connection_id = saved_current_connection_id
            manager.save()

    @mock_container(TestData.Points)
    def test_cache_migration_reassigns_cached_container_connection_id(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._move_to_cache(container_mock)
        obsolete_connection_id = str(uuid.uuid4())
        set_container_connection_metadata(
            container_path,
            connection_id=obsolete_connection_id,
        )

        is_succeeded = (
            CacheMaintenanceService().reassign_container_connection_ids(
                [connection]
            )
        )

        metadata = container_metadata(container_path)
        self.assertTrue(is_succeeded)
        self.assertEqual(metadata.connection_id, connection.id)

    @mock_container(TestData.Points)
    def test_cache_migration_moves_reassigned_container_to_domain_cache_path(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        resource = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        obsolete_connection_id = str(uuid.uuid4())
        legacy_container_path = (
            self.cache_directory
            / obsolete_connection_id
            / f"{resource.resource_id}.gpkg"
        )
        legacy_container_path.parent.mkdir(exist_ok=True, parents=True)
        cp(container_mock.path, legacy_container_path)
        set_container_connection_metadata(
            legacy_container_path,
            connection_id=obsolete_connection_id,
        )
        cache_service = CacheMaintenanceService()
        canonical_container_path = (
            self._storage_service().ensure_container_placeholder(
                connection.domain_uuid,
                resource.resource_id,
            )
        )

        is_succeeded = cache_service.reassign_container_connection_ids(
            [connection]
        )

        metadata = container_metadata(canonical_container_path)
        self.assertTrue(is_succeeded)
        self.assertFalse(legacy_container_path.exists())
        self.assertTrue(canonical_container_path.exists())
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)

    @mock_container(TestData.Points)
    def test_cache_migration_skips_ambiguous_domain_connections(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        connection = self.connection(TestConnection.SandboxGuest)
        duplicate_connection = NgwConnection(
            str(uuid.uuid4()),
            "Duplicate sandbox",
            connection.url,
            None,
        )
        container_path = self._move_to_cache(container_mock)
        obsolete_connection_id = str(uuid.uuid4())
        set_container_connection_metadata(
            container_path,
            connection_id=obsolete_connection_id,
        )

        is_succeeded = (
            CacheMaintenanceService().reassign_container_connection_ids(
                [connection, duplicate_connection]
            )
        )

        metadata = container_metadata(container_path)
        self.assertTrue(is_succeeded)
        self.assertEqual(metadata.connection_id, obsolete_connection_id)

    def _move_to_cache(self, container_mock: MagicMock):
        resource = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        container_path = self._storage_service().ensure_container_placeholder(
            connection.domain_uuid,
            resource.resource_id,
        )
        container_path.parent.mkdir(exist_ok=True, parents=True)
        cp(container_mock.path, container_path)
        return container_path

    def _storage_service(self) -> DetachedStorageService:
        return DetachedStorageService(self.cache_directory)

    def _collect_detached_layer_params(self, ngw_layer):
        importer = QgisResourceBatchImporter.__new__(QgisResourceBatchImporter)
        return importer._QgisResourceBatchImporter__collect_params_for_detached_layer(
            ngw_layer,
        )
