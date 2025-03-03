import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, cast
from unittest import mock

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from nextgis_connect.compat import FieldType
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    detached_layer_uri,
    make_connection,
)
from nextgis_connect.ngw_api.core import NGWVectorLayer
from nextgis_connect.ngw_connection import NgwConnection
from nextgis_connect.resources.ngw_field import NgwFields
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.utils import is_version_supported
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestConnection,
    TestData,
)

DELETED_FEATURE = 3
FIXED_DATETIME = datetime(2006, 5, 4, 3, 2, 1)


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

        with self.subTest("4. Special symbols in layer name"):
            for display_name in (
                "point's_layer",
                "point''s_layer",
                'point"s_layer',
                'point""s_layer',
            ):
                layer_json["resource"]["display_name"] = display_name

                ngw_layer = cast(
                    NGWVectorLayer, self.resource(layer_json, connection)
                )

                container_path = self.create_temp_file(".gpkg")
                factory.create_initial_container(ngw_layer, container_path)

                metadata = container_metadata(container_path)
                self._check_common_metadata(metadata, ngw_layer, connection)
                check_test_metadata(metadata)
                self.assertEqual(metadata.layer_name, display_name)

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

        with self.subTest("4. Special symbols in layer name"):
            for display_name in (
                "point's_layer",
                "point''s_layer",
                'point"s_layer',
                'point""s_layer',
            ):
                layer_json["resource"]["display_name"] = display_name

                ngw_layer = cast(
                    NGWVectorLayer, self.resource(layer_json, connection)
                )

                container_path = self.create_temp_file(".gpkg")
                factory.create_initial_container(ngw_layer, container_path)

                metadata = container_metadata(container_path)
                self._check_common_metadata(metadata, ngw_layer, connection)
                check_test_metadata(metadata)
                self.assertEqual(metadata.layer_name, display_name)

    @mock.patch(
        "nextgis_connect.detached_editing.detached_layer_factory.datetime"
    )
    def test_fill(self, datetime_mock) -> None:
        datetime_mock.now.return_value = FIXED_DATETIME

        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(TestData.Points, connection)
        assert isinstance(ngw_layer, NGWVectorLayer)

        with self.subTest("1.0 Before 5.0"):
            self.assertTrue(is_version_supported("4.9.0"))
            export_path = self._create_pseudo_export(
                ngw_layer,
                source_path=self.data_path(TestData.Points),
                fid_field="fid",
                ngw_fid_field="fid",
            )
            self._test_fill(
                connection, ngw_layer, export_path, fid_field="fid"
            )

        with self.subTest("2. After 5.0"):
            export_path = self._create_pseudo_export(
                ngw_layer,
                source_path=self.data_path(TestData.Points),
                fid_field="fid_1",
                ngw_fid_field="fid",
            )
            self._test_fill(
                connection, ngw_layer, export_path, fid_field="fid"
            )

    @mock.patch(
        "nextgis_connect.detached_editing.detached_layer_factory.datetime"
    )
    def test_fill_with_fid_field(self, datetime_mock) -> None:
        datetime_mock.now.return_value = FIXED_DATETIME

        # Create json
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

        # Create resource
        connection = self.connection(TestConnection.SandboxGuest)
        ngw_layer = self.resource(layer_json_with_fid_field, connection)
        assert isinstance(ngw_layer, NGWVectorLayer)

        with self.subTest("1.0 Before 5.0"):
            self.assertTrue(is_version_supported("4.9.0"))
            source_layer = cast(QgsVectorLayer, self.layer(TestData.Points))
            export_path = self._create_pseudo_export(
                ngw_layer,
                source_path=self.data_path(TestData.Points),
                fid_field="fid",
                ngw_fid_field="fid_1",
                custom_values={
                    fid: {"fid": fid + 100}
                    for fid in source_layer.allFeatureIds()
                },
            )
            self._test_fill(
                connection, ngw_layer, export_path, fid_field="fid_1"
            )

        with self.subTest("2. After 5.0"):
            source_layer = cast(QgsVectorLayer, self.layer(TestData.Points))
            export_path = self._create_pseudo_export(
                ngw_layer,
                source_path=self.data_path(TestData.Points),
                fid_field="fid_2",
                ngw_fid_field="fid_1",
                custom_values={
                    fid: {"fid": fid + 100}
                    for fid in source_layer.allFeatureIds()
                },
            )
            self._test_fill(
                connection, ngw_layer, export_path, fid_field="fid_1"
            )

    def _test_fill(
        self,
        connection: NgwConnection,
        ngw_layer: NGWVectorLayer,
        export_path: Path,
        *,
        fid_field: str,
    ) -> None:
        exported_layer = QgsVectorLayer(
            detached_layer_uri(export_path), "", "ogr"
        )

        # Create and fill container
        factory = DetachedLayerFactory()
        container_path = self.create_temp_file(".gpkg")
        factory.create_initial_container(ngw_layer, container_path)
        factory.fill_container(
            ngw_layer,
            source_path=export_path,
            container_path=container_path,
        )
        metadata = container_metadata(container_path)

        # Check integrity
        detached_layer = QgsVectorLayer(
            detached_layer_uri(container_path), "", "ogr"
        )
        self._check_common_metadata(metadata, ngw_layer, connection)
        self._check_metadata_for_filled(metadata)
        self.assertEqual(metadata.fid_field, fid_field)
        self.assertEqual(metadata.geom_field, "geom")

        self._compare_layers(exported_layer, detached_layer)
        self._check_features_metadata(detached_layer)

    def _create_pseudo_export(
        self,
        ngw_layer: NGWVectorLayer,
        *,
        source_path: Path,
        fid_field: str,
        ngw_fid_field: str,
        custom_values: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Path:
        if custom_values is None:
            custom_values = {}

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = ngw_layer.display_name
        options.fileEncoding = "UTF-8"
        ngw_fields = NgwFields(
            ngw_field
            for ngw_field in ngw_layer.fields
            if not (ngw_field.keyname == fid_field == "fid")
        )

        fields = QgsFields()
        fields.append(QgsField(fid_field, FieldType.LongLong))
        fields.extend(ngw_fields.to_qgs_fields())
        fields.append(QgsField(ngw_fid_field, FieldType.Int))

        options.layerOptions = [
            *QgsVectorFileWriter.defaultDatasetOptions("GPKG"),
            f"FID={fid_field}",
        ]

        export_path = self.create_temp_file(".gpkg")
        writer = QgsVectorFileWriter.create(
            fileName=str(export_path),
            fields=fields,
            geometryType=ngw_layer.wkb_geom_type,
            transformContext=QgsProject.instance().transformContext(),
            srs=ngw_layer.qgs_srs,
            options=options,
        )
        self.assertIsNotNone(writer)
        self.assertEqual(
            writer.hasError(), QgsVectorFileWriter.WriterError.NoError
        )

        source_layer = QgsVectorLayer(
            detached_layer_uri(source_path), "", "ogr"
        )

        ngw_fid = 1
        for i, source_feature in enumerate(
            cast(Iterable[QgsFeature], source_layer.getFeatures()), start=1
        ):
            exported_feature = QgsFeature(fields)

            fid = custom_values.get(source_feature.id(), {}).get(fid_field, i)
            exported_feature.setId(fid)
            exported_feature.setAttribute(fid_field, fid)

            exported_feature.setAttribute(ngw_fid_field, ngw_fid)
            for field in ngw_fields:
                source_feature_value = source_feature.attribute(field.keyname)
                value = custom_values.get(source_feature.id(), {}).get(
                    field.keyname, source_feature_value
                )

                exported_feature.setAttribute(field.keyname, value)

            exported_feature.setGeometry(source_feature.geometry())

            # Deleted feature simulation
            ngw_fid += 1 if ngw_fid != DELETED_FEATURE - 1 else 2

            writer.addFeature(exported_feature)

        self.assertEqual(
            writer.hasError(), QgsVectorFileWriter.WriterError.NoError
        )

        del writer

        return export_path

    def _check_common_metadata(
        self,
        metadata: DetachedContainerMetaData,
        ngw_layer: NGWVectorLayer,
        connection: NgwConnection,
    ) -> None:
        settings = NgConnectSettings()
        self.assertEqual(
            metadata.container_version, settings.supported_container_version
        )
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

    def _check_metadata_for_filled(self, metadata: DetachedContainerMetaData):
        self.assertIsNone(metadata.transaction_id)
        self.assertIsNone(metadata.epoch)
        self.assertIsNone(metadata.version)
        self.assertFalse(metadata.is_not_initialized)
        self.assertFalse(metadata.is_versioning_enabled)
        self.assertEqual(metadata.sync_date, FIXED_DATETIME)

    def _compare_layers(
        self,
        exported_layer: QgsVectorLayer,
        target_layer: QgsVectorLayer,
    ) -> None:
        exported_features: List[QgsFeature] = list(
            exported_layer.getFeatures()  # type: ignore
        )
        target_features: List[QgsFeature] = list(
            target_layer.getFeatures()  # type: ignore
        )

        exported_fid_field = (
            exported_layer.fields()
            .at(exported_layer.primaryKeyAttributes()[0])
            .name()
        )
        target_fid_field = (
            target_layer.fields()
            .at(target_layer.primaryKeyAttributes()[0])
            .name()
        )

        self.assertEqual(len(exported_features), len(target_features))

        for source_feature, target_feature in zip(
            exported_features, target_features
        ):
            exported_feature_attributes = source_feature.attributeMap()
            target_feature_attributes = target_feature.attributeMap()

            # If exported_fid_field is "fid" it will be in target
            if exported_fid_field not in target_feature_attributes:
                del exported_feature_attributes[exported_fid_field]

            # Target fid field is ngw_id field in exported data
            self.assertEqual(
                source_feature.attribute(target_fid_field), target_feature.id()
            )
            if target_fid_field in exported_feature_attributes:
                del exported_feature_attributes[target_fid_field]
            del target_feature_attributes[target_fid_field]

            # Check remaining fields
            self.assertDictEqual(
                exported_feature_attributes, target_feature_attributes
            )

    def _check_features_metadata(self, detached_layer: QgsVectorLayer) -> None:
        fid_to_ngw_fid = {}
        with closing(make_connection(detached_layer)) as connection, closing(
            connection.cursor()
        ) as cursor:
            fid_to_ngw_fid.update(
                (fid, ngw_id)
                for fid, ngw_id in cursor.execute(
                    "SELECT fid, ngw_fid FROM ngw_features_metadata"
                )
            )

        self.assertEqual(len(fid_to_ngw_fid), detached_layer.featureCount())
        self.assertTrue(DELETED_FEATURE not in fid_to_ngw_fid)

        for fid, ngw_fid in fid_to_ngw_fid.items():
            self.assertEqual(fid, ngw_fid)


if __name__ == "__main__":
    unittest.main()
