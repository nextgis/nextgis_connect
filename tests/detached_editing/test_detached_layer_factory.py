import shutil
import unittest
from datetime import datetime
from typing import List, cast
from unittest import mock

from qgis.core import QgsFeature, QgsField, QgsVectorLayer, edit

from nextgis_connect.compat import FieldType
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    detached_layer_uri,
)
from nextgis_connect.ngw_api.core import NGWVectorLayer
from nextgis_connect.ngw_connection import NgwConnection
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestConnection,
    TestData,
)


class TestDetachedLayerFactory(NgConnectTestCase):
    def test_create_without_versioning(self) -> None:
        def check_test_metadata(metadata: DetachedContainerMetaData):
            self.assertIsNone(metadata.transaction_id)
            self.assertIsNone(metadata.epoch)
            self.assertIsNone(metadata.version)
            self.assertIsNone(metadata.sync_date)
            self.assertEqual(metadata.features_count, 0)
            self.assertTrue(metadata.is_not_initialized)
            self.assertFalse(metadata.is_versioning_enabled)

        connection = self.connection(TestConnection.SandboxGuest)
        layer_json = self.resource_json(TestData.Points)

        factory = DetachedLayerFactory()

        with self.subTest("1. Ordinary layer"):
            ngw_layer = cast(
                NGWVectorLayer, self.resource(layer_json, connection)
            )

            container_path = self.create_temp_file(".gpkg")
            factory.create_initial_container(ngw_layer, container_path)

            metadata = container_metadata(container_path)
            self._check_common_metadata(metadata, ngw_layer, connection)
            check_test_metadata(metadata)
            self.assertEqual(metadata.fid_field, "fid")
            self.assertEqual(metadata.geom_field, "geom")

        with self.subTest("2. Layer with fid field"):
            layer_json["feature_layer"]["fields"].append(
                {
                    "id": 50000,
                    "keyname": "fid",
                    "datatype": "INTEGER",
                    "display_name": "fid",
                }
            )

            ngw_layer = cast(
                NGWVectorLayer, self.resource(layer_json, connection)
            )

            container_path = self.create_temp_file(".gpkg")
            factory.create_initial_container(ngw_layer, container_path)

            metadata = container_metadata(container_path)
            self._check_common_metadata(metadata, ngw_layer, connection)
            check_test_metadata(metadata)
            self.assertEqual(metadata.fid_field, "fid_1")
            self.assertEqual(metadata.geom_field, "geom")

        with self.subTest("3. Layer with fid fields"):
            for i in range(1, 11):
                layer_json["feature_layer"]["fields"].append(
                    {
                        "id": 50000 + i,
                        "keyname": f"fid_{i}",
                        "datatype": "INTEGER",
                        "display_name": f"fid_{i}",
                    }
                )

                ngw_layer = cast(
                    NGWVectorLayer, self.resource(layer_json, connection)
                )

                container_path = self.create_temp_file(".gpkg")
                factory.create_initial_container(ngw_layer, container_path)

                metadata = container_metadata(container_path)
                self._check_common_metadata(metadata, ngw_layer, connection)
                check_test_metadata(metadata)
                self.assertEqual(metadata.fid_field, f"fid_{i + 1}")
                self.assertEqual(metadata.geom_field, "geom")

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
    def test_create_with_vesrioning(self, mock_1, mock_2, mock_3) -> None:
        def check_test_metadata(metadata: DetachedContainerMetaData):
            self.assertIsNone(metadata.transaction_id)
            self.assertEqual(metadata.epoch, 42)
            self.assertEqual(metadata.version, 24)
            self.assertIsNone(metadata.sync_date)
            self.assertEqual(metadata.features_count, 0)

            self.assertTrue(metadata.is_not_initialized)
            self.assertTrue(metadata.is_versioning_enabled)

        connection = self.connection(TestConnection.SandboxGuest)
        layer_json = self.resource_json(TestData.Points)

        factory = DetachedLayerFactory()

        with self.subTest("1. Ordinary layer"):
            ngw_layer = cast(
                NGWVectorLayer, self.resource(layer_json, connection)
            )

            container_path = self.create_temp_file(".gpkg")
            factory.create_initial_container(ngw_layer, container_path)

            metadata = container_metadata(container_path)
            self._check_common_metadata(metadata, ngw_layer, connection)
            check_test_metadata(metadata)
            self.assertEqual(metadata.fid_field, "fid")
            self.assertEqual(metadata.geom_field, "geom")

        with self.subTest("2. Layer with fid field"):
            layer_json["feature_layer"]["fields"].append(
                {
                    "id": 50000,
                    "keyname": "fid",
                    "datatype": "INTEGER",
                    "display_name": "fid",
                }
            )

            ngw_layer = cast(
                NGWVectorLayer, self.resource(layer_json, connection)
            )

            container_path = self.create_temp_file(".gpkg")
            factory.create_initial_container(ngw_layer, container_path)

            metadata = container_metadata(container_path)
            self._check_common_metadata(metadata, ngw_layer, connection)
            check_test_metadata(metadata)
            self.assertEqual(metadata.fid_field, "fid_1")
            self.assertEqual(metadata.geom_field, "geom")

        with self.subTest("3. Layer with fid fields"):
            for i in range(1, 11):
                layer_json["feature_layer"]["fields"].append(
                    {
                        "id": 50000 + i,
                        "keyname": f"fid_{i}",
                        "datatype": "INTEGER",
                        "display_name": f"fid_{i}",
                    }
                )

                ngw_layer = cast(
                    NGWVectorLayer, self.resource(layer_json, connection)
                )

                container_path = self.create_temp_file(".gpkg")
                factory.create_initial_container(ngw_layer, container_path)

                metadata = container_metadata(container_path)
                self._check_common_metadata(metadata, ngw_layer, connection)
                check_test_metadata(metadata)
                self.assertEqual(metadata.fid_field, f"fid_{i + 1}")
                self.assertEqual(metadata.geom_field, "geom")

    @mock.patch(
        "nextgis_connect.detached_editing.detached_layer_factory.datetime"
    )
    def test_fill(self, datetime_mock) -> None:
        datetime_mock.now.return_value = datetime(2006, 5, 4, 3, 2, 1)

        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(TestData.Points, connection)
        assert isinstance(ngw_layer, NGWVectorLayer)

        source_path = self.create_temp_file(".gpkg")
        shutil.copyfile(str(self.data_path(TestData.Points)), str(source_path))

        source_layer = QgsVectorLayer(
            detached_layer_uri(source_path), "", "ogr"
        )

        # Check fid sequence
        with edit(source_layer):
            source_layer.deleteFeature(3)

        factory = DetachedLayerFactory()

        temp_file_path = self.create_temp_file(".gpkg")

        factory.create_initial_container(ngw_layer, temp_file_path)
        factory.fill_container(
            ngw_layer,
            source_path=source_path,
            container_path=temp_file_path,
        )
        metadata = container_metadata(temp_file_path)
        target_layer = QgsVectorLayer(
            detached_layer_uri(temp_file_path), "", "ogr"
        )
        self._check_common_metadata(metadata, ngw_layer, connection)
        self._check_filled_metadata(metadata)
        self._compare_layers(source_layer, target_layer)
        self.assertEqual(metadata.fid_field, "fid")
        self.assertEqual(metadata.geom_field, "geom")

    @mock.patch(
        "nextgis_connect.detached_editing.detached_layer_factory.datetime"
    )
    def test_fill_with_fid_field(self, datetime_mock) -> None:
        datetime_mock.now.return_value = datetime(2006, 5, 4, 3, 2, 1)

        layer_json_with_fid_field = self.resource_json(TestData.Points)
        layer_json_with_fid_field["feature_layer"]["fields"].insert(
            0,
            {
                "id": 50000,
                "keyname": "fid",
                "datatype": "INTEGER",
                "display_name": "fid",
            },
        )

        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(layer_json_with_fid_field, connection)
        assert isinstance(ngw_layer, NGWVectorLayer)

        source_path = self.create_temp_file(".gpkg")
        shutil.copyfile(str(self.data_path(TestData.Points)), str(source_path))

        source_layer = QgsVectorLayer(
            detached_layer_uri(source_path), "", "ogr"
        )

        with edit(source_layer):
            self.assertTrue(
                source_layer.addAttribute(
                    QgsField("fid_1", FieldType.LongLong)
                )
            )

            i = 1
            for feature in source_layer.getFeatures():  # type: ignore
                assert isinstance(feature, QgsFeature)
                feature.setAttribute("fid_1", i)
                # Deleted feature simulation
                i += 1 if i != 3 else 2
                source_layer.updateFeature(feature)

        factory = DetachedLayerFactory()

        container_path = self.create_temp_file(".gpkg")

        factory.create_initial_container(ngw_layer, container_path)
        factory.fill_container(
            ngw_layer,
            source_path=source_path,
            container_path=container_path,
        )
        metadata = container_metadata(container_path)
        target_layer = QgsVectorLayer(
            detached_layer_uri(container_path), "", "ogr"
        )
        self._check_common_metadata(metadata, ngw_layer, connection)
        self._check_filled_metadata(metadata)
        self._compare_layers(source_layer, target_layer)
        self.assertEqual(metadata.fid_field, "fid_1")
        self.assertEqual(metadata.geom_field, "geom")

    def _check_common_metadata(
        self,
        metadata: DetachedContainerMetaData,
        ngw_layer: NGWVectorLayer,
        connection: NgwConnection,
    ) -> None:
        self.assertEqual(metadata.container_version, "1.0.0")
        self.assertEqual(metadata.connection_id, connection.id)
        self.assertEqual(metadata.instance_id, connection.domain_uuid)
        self.assertEqual(metadata.resource_id, ngw_layer.resource_id)
        self.assertEqual(metadata.table_name, ngw_layer.display_name)
        self.assertEqual(metadata.layer_name, ngw_layer.display_name)
        self.assertEqual(metadata.description, ngw_layer.description)
        self.assertEqual(metadata.geometry_name, ngw_layer.geom_name)
        self.assertEqual(metadata.fields, ngw_layer.fields)
        self.assertEqual(metadata.srs_id, ngw_layer.srs())
        self.assertEqual(metadata.is_auto_sync_enabled, True)
        self.assertEqual(metadata.has_changes, False)

    def _check_filled_metadata(self, metadata: DetachedContainerMetaData):
        self.assertIsNone(metadata.transaction_id)
        self.assertIsNone(metadata.epoch)
        self.assertIsNone(metadata.version)
        self.assertFalse(metadata.is_not_initialized)
        self.assertFalse(metadata.is_versioning_enabled)
        self.assertEqual(metadata.sync_date, datetime(2006, 5, 4, 3, 2, 1))

    def _compare_layers(
        self, source_layer: QgsVectorLayer, target_layer: QgsVectorLayer
    ) -> None:
        source_features: List[QgsFeature] = list(
            source_layer.getFeatures()  # type: ignore
        )
        target_features: List[QgsFeature] = list(
            target_layer.getFeatures()  # type: ignore
        )

        source_fid = (
            source_layer.fields()
            .at(source_layer.primaryKeyAttributes()[0])
            .name()
        )
        target_fid = (
            target_layer.fields()
            .at(target_layer.primaryKeyAttributes()[0])
            .name()
        )

        self.assertEqual(len(source_features), len(target_features))

        for source_feature, target_feature in zip(
            source_features, target_features
        ):
            self.assertEqual(
                source_feature.attribute(target_fid), target_feature.id()
            )

            source_feature_attributes = source_feature.attributeMap()
            target_feature_attributes = target_feature.attributeMap()

            if source_fid not in target_feature_attributes:
                del source_feature_attributes[source_fid]
            if target_fid in source_feature_attributes:
                del source_feature_attributes[target_fid]
            del target_feature_attributes[target_fid]

            self.assertDictEqual(
                source_feature_attributes, target_feature_attributes
            )


if __name__ == "__main__":
    unittest.main()
