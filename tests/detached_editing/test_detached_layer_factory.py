import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from qgis.core import QgsVectorLayer

from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import container_metadata
from nextgis_connect.ngw_api.core import NGWVectorLayer
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestConnection,
    TestData,
)


class TestDetachedLayerFactory(NgConnectTestCase):
    def test_create_stub(self) -> None:
        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(TestData.Points, TestConnection.SandboxGuest)
        assert isinstance(ngw_layer, NGWVectorLayer)

        factory = DetachedLayerFactory()
        container_path = Path(tempfile.mktemp(suffix=".gpkg"))
        factory.create_container(ngw_layer, container_path)

        metadata = container_metadata(container_path)
        self.assertEqual(metadata.container_version, "1.0.0")
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)
        self.assertEqual(metadata.resource_id, ngw_layer.resource_id)
        self.assertEqual(metadata.table_name, ngw_layer.display_name)
        self.assertEqual(metadata.layer_name, ngw_layer.display_name)
        self.assertEqual(metadata.description, ngw_layer.description)
        self.assertEqual(metadata.geometry_name, ngw_layer.geom_name)
        self.assertIsNone(metadata.transaction_id)
        self.assertIsNone(metadata.epoch)
        self.assertIsNone(metadata.version)
        self.assertIsNone(metadata.sync_date)
        self.assertEqual(metadata.is_auto_sync_enabled, True)
        self.assertEqual(metadata.fields, ngw_layer.fields)
        self.assertEqual(metadata.features_count, 0)
        self.assertEqual(metadata.has_changes, False)
        self.assertEqual(metadata.srs_id, ngw_layer.srs())

        self.assertTrue(metadata.is_not_initialized)
        self.assertFalse(metadata.is_versioning_enabled)

    @mock.patch(
        "nextgis_connect.ngw_api.core.NGWVectorLayer.is_versioning_enabled",
        new_callable=mock.PropertyMock,
        return_value=True,
    )
    @mock.patch(
        "nextgis_connect.ngw_api.core.NGWVectorLayer.epoch",
        new_callable=mock.PropertyMock,
        return_value=42,
    )
    @mock.patch(
        "nextgis_connect.ngw_api.core.NGWVectorLayer.version",
        new_callable=mock.PropertyMock,
        return_value=24,
    )
    def test_create_initial_vesrioning(self, mock_1, mock_2, mock_3) -> None:
        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(TestData.Points, TestConnection.SandboxGuest)
        assert isinstance(ngw_layer, NGWVectorLayer)

        factory = DetachedLayerFactory()
        container_path = Path(tempfile.mktemp(suffix=".gpkg"))

        factory.create_container(ngw_layer, container_path)

        metadata = container_metadata(container_path)
        self.assertEqual(metadata.container_version, "1.0.0")
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)
        self.assertEqual(metadata.resource_id, ngw_layer.resource_id)
        self.assertEqual(metadata.table_name, ngw_layer.display_name)
        self.assertEqual(metadata.layer_name, ngw_layer.display_name)
        self.assertEqual(metadata.description, ngw_layer.description)
        self.assertEqual(metadata.geometry_name, ngw_layer.geom_name)
        self.assertIsNone(metadata.transaction_id)
        self.assertEqual(metadata.epoch, 42)
        self.assertEqual(metadata.version, 24)
        self.assertIsNone(metadata.sync_date)
        self.assertEqual(metadata.is_auto_sync_enabled, True)
        self.assertEqual(metadata.fields, ngw_layer.fields)
        self.assertEqual(metadata.features_count, 0)
        self.assertEqual(metadata.has_changes, False)
        self.assertEqual(metadata.srs_id, ngw_layer.srs())

        self.assertTrue(metadata.is_not_initialized)
        self.assertTrue(metadata.is_versioning_enabled)

    @mock.patch(
        "nextgis_connect.detached_editing.detached_layer_factory.datetime"
    )
    def test_update(self, datetime_mock) -> None:
        datetime_mock.now.return_value = datetime(2006, 5, 4, 3, 2, 1)

        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(TestData.Points, TestConnection.SandboxGuest)
        assert isinstance(ngw_layer, NGWVectorLayer)
        qgs_layer = self.layer(TestData.Points)
        assert isinstance(qgs_layer, QgsVectorLayer)

        factory = DetachedLayerFactory()
        temp_file_path = tempfile.mktemp(suffix=".gpkg")
        shutil.copy(self.data_path(TestData.Points), temp_file_path)

        factory.update_container(ngw_layer, Path(temp_file_path))

        metadata = container_metadata(temp_file_path)
        self.assertEqual(metadata.container_version, "1.0.0")
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)
        self.assertEqual(metadata.resource_id, ngw_layer.resource_id)
        self.assertEqual(metadata.table_name, ngw_layer.display_name)
        self.assertEqual(metadata.layer_name, ngw_layer.display_name)
        self.assertEqual(metadata.description, ngw_layer.description)
        self.assertEqual(metadata.geometry_name, ngw_layer.geom_name)
        self.assertIsNone(metadata.transaction_id)
        self.assertIsNone(metadata.epoch)
        self.assertIsNone(metadata.version)
        self.assertEqual(metadata.sync_date, datetime(2006, 5, 4, 3, 2, 1))
        self.assertEqual(metadata.is_auto_sync_enabled, True)
        self.assertEqual(metadata.fields, ngw_layer.fields)
        self.assertEqual(metadata.features_count, qgs_layer.featureCount())
        self.assertEqual(metadata.has_changes, False)
        self.assertEqual(metadata.srs_id, ngw_layer.srs())

        self.assertFalse(metadata.is_not_initialized)
        self.assertFalse(metadata.is_versioning_enabled)


if __name__ == "__main__":
    unittest.main()
