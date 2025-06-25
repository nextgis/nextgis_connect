import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFields,
    QgsPathResolver,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDir

from nextgis_connect.compat import WkbType
from nextgis_connect.detached_editing.path_preprocessor import (
    DetachedEditingPathPreprocessor,
)
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestConnection,
    TestData,
)
from tests.utils import safe_move


class TestPathPreprocessor(NgConnectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.__path_preprocessor = DetachedEditingPathPreprocessor()
        self.__path_preprocessor_id = QgsPathResolver.setPathPreprocessor(
            self.__path_preprocessor  # type: ignore
        )

        cache_manager = NgConnectCacheManager()
        self.cache_directory = self.create_temp_dir("-Cache")
        cache_manager.cache_directory = str(self.cache_directory)

        self.project_directory = self.create_temp_dir("-Project")
        project = QgsProject.instance()
        project.write(f"{self.project_directory}/project.qgs")

    def tearDown(self) -> None:
        QgsPathResolver.removePathPreprocessor(self.__path_preprocessor_id)
        del self.__path_preprocessor
        shutil.rmtree(str(self.cache_directory))
        super().tearDown()

    def test_not_a_container(self) -> None:
        with self.subTest("WMS"):
            wms_source = "crs=EPSG:3857&format=image/png&layers=ngw_id_7063&styles=&url=https://demo.nextgis.com/api/resource/7835/wms"
            self.assertEqual(
                QgsPathResolver().readPath(wms_source), wms_source
            )

        with self.subTest("PostGIS"):
            postgis_source = "dbname='demo' host=sandbox.nextgis.com port=54321 user='demo' password='demo123' key='id' checkPrimaryKeyUnicity='1' table=\"public\".\"madcity\" (geom)"
            self.assertEqual(
                QgsPathResolver().readPath(postgis_source), postgis_source
            )

        connection = self.connection(TestConnection.SandboxGuest)
        (self.cache_directory / connection.domain_uuid).mkdir(
            exist_ok=True, parents=True
        )

        with self.subTest("GeoTIFF"):
            raster_path = (
                self.cache_directory / connection.domain_uuid / "1.tiff"
            )
            raster_path.touch()
            raster_source = str(raster_path)
            self.assertEqual(
                QgsPathResolver().readPath(raster_source), raster_source
            )

        with self.subTest("Simple GPKG"):
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "vector_layer"
            options.fileEncoding = "UTF-8"
            options.layerOptions = QgsVectorFileWriter.defaultDatasetOptions(
                "GPKG"
            )
            gpkg_path = str(
                self.cache_directory / connection.domain_uuid / "1.gpkg"
            )
            writer = QgsVectorFileWriter.create(
                fileName=gpkg_path,
                fields=QgsFields(),
                geometryType=WkbType.Point,
                transformContext=QgsProject.instance().transformContext(),
                srs=QgsCoordinateReferenceSystem.fromEpsgId(3857),
                options=options,
            )
            assert writer is not None
            writer = None

            gpkg_source = f"{gpkg_path}|layername=wrong_name"
            self.assertEqual(
                QgsPathResolver().readPath(gpkg_source), gpkg_source
            )

        with self.subTest("Broken GPKG"):
            connection = self.connection(TestConnection.SandboxGuest)
            (self.cache_directory / connection.domain_uuid).mkdir(
                exist_ok=True, parents=True
            )
            gpkg_path_with_layer_name = (
                self.cache_directory / connection.domain_uuid / "1.gpkg"
            )
            gpkg_path_with_layer_name.touch()
            gpkg_source_with_layer_name = (
                f"{gpkg_path_with_layer_name}|layername=not_existed"
            )
            self.assertEqual(
                QgsPathResolver().readPath(gpkg_source_with_layer_name),
                gpkg_source_with_layer_name,
            )

    def test_wrong_path(self) -> None:
        connection = self.connection(TestConnection.SandboxGuest)

        with self.subTest("Not in cache directory"):
            source = str(
                Path(tempfile.gettempdir()) / connection.domain_uuid / "1.gpkg"
            )
            self.assertEqual(QgsPathResolver().readPath(source), source)

        with self.subTest("Without id"):
            domain_uuid = connection.domain_uuid

            (self.cache_directory / domain_uuid).mkdir(
                parents=True, exist_ok=True
            )

            temp_file = self.cache_directory / domain_uuid / "abc.gpkg"
            temp_file.touch()

            source = str(temp_file)
            self.assertEqual(QgsPathResolver().readPath(source), source)

    def test_without_connections(self) -> None:
        domain_uuid = str(uuid.uuid4())
        (self.cache_directory / domain_uuid).mkdir(parents=True, exist_ok=True)
        temp_file = self.cache_directory / domain_uuid / "1.gpkg"
        source = str(temp_file)

        with self.subTest("Not existed container"):
            self.assertEqual(QgsPathResolver().readPath(source), source)
            self.assertFalse(temp_file.exists())

        with self.subTest("Existed container"):
            temp_file.touch()
            self.assertEqual(QgsPathResolver().readPath(source), source)

    @mock_container(TestData.Points)
    def test_existed(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        self.__move_container(container_mock)

        table_name = container_mock.metadata.table_name
        layername = f"|layername={table_name}"

        with self.subTest("Absolute path"):
            self.assertTrue(container_mock.path.is_absolute())
            source = str(container_mock.path)
            self.assertEqual(QgsPathResolver().readPath(source), source)

        with self.subTest("Relative path"):
            source = QDir(str(self.project_directory)).relativeFilePath(
                str(container_mock.path)
            )
            self.assertTrue(
                source.startswith("..") and source.endswith(".gpkg")
            )
            self.assertEqual(QgsPathResolver().readPath(source), source)

        with self.subTest("Absolute path with layer name"):
            self.assertTrue(container_mock.path.is_absolute())
            source = f"{container_mock.path}{layername}"
            self.assertEqual(QgsPathResolver().readPath(source), source)

        with self.subTest("Relative path with layer name"):
            source = (
                QDir(str(self.project_directory)).relativeFilePath(
                    str(container_mock.path)
                )
                + layername
            )
            self.assertTrue(
                source.startswith("..")
                and source.endswith(".gpkg" + layername)
            )
            self.assertEqual(QgsPathResolver().readPath(source), source)

    @mock_container(TestData.Points)
    def test_old_existed(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        self.__move_container(container_mock)
        old_layername = "|layername=old_layer_name"
        table_name = container_mock.metadata.table_name
        new_layername = f"|layername={table_name}"

        with self.subTest("Absolute path"):
            self.assertTrue(container_mock.path.is_absolute())
            old_source = f"{container_mock.path}{old_layername}"
            new_source = f"{container_mock.path}{new_layername}"
            self.assertEqual(
                QgsPathResolver().readPath(old_source), new_source
            )

        with self.subTest("Absolute path"):
            relative_path = QDir(str(self.project_directory)).relativeFilePath(
                str(container_mock.path)
            )
            self.assertTrue(
                relative_path.startswith("..")
                and relative_path.endswith(".gpkg")
            )

            old_source = relative_path + old_layername
            new_source = relative_path + new_layername

            self.assertEqual(
                QgsPathResolver().readPath(old_source), new_source
            )

    @patch(
        "nextgis_connect.detached_editing.path_preprocessor.NGWResourceFactory"
    )
    @patch(
        "nextgis_connect.detached_editing.path_preprocessor.QgsNgwConnection"
    )
    def test_not_existed(
        self, connection_mock: MagicMock, factory_mock: MagicMock
    ) -> None:
        resource = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        layer_name = f"|layername=vector_layer_{resource.resource_id}"

        creation_mock = MagicMock()
        creation_mock.get_resource.return_value = resource
        factory_mock.return_value = creation_mock

        permissions_mock = MagicMock()
        permissions_mock.get.return_value = {
            "data": {"write": True, "read": True}
        }
        connection_mock.return_value = permissions_mock

        domain_directory = self.cache_directory / connection.domain_uuid
        container_path = domain_directory / f"{resource.resource_id}.gpkg"
        self.assertTrue(container_path.is_absolute())

        with self.subTest("Absolute path"):
            source = str(container_path)
            restored_source = QgsPathResolver().readPath(source)
            self.assertEqual(restored_source, source)

            layer = QgsVectorLayer(restored_source, "test layer", "ogr")
            self.assertTrue(layer.isValid())
            del layer
            container_path.unlink()
            self.assertFalse(container_path.exists())

        with self.subTest("Relative path"):
            source = QDir(str(self.project_directory)).relativeFilePath(
                str(container_path)
            )
            self.assertTrue(
                source.startswith("..") and source.endswith(".gpkg")
            )
            restored_source = QgsPathResolver().readPath(source)
            self.assertEqual(restored_source, source)

            layer = QgsVectorLayer(str(container_path), "test layer", "ogr")
            self.assertTrue(layer.isValid())
            del layer
            container_path.unlink()
            self.assertFalse(container_path.exists())

        with self.subTest("Absolute path with layer name"):
            source = f"{container_path}{layer_name}"
            restored_source = QgsPathResolver().readPath(source)
            self.assertEqual(restored_source, source)

            layer = QgsVectorLayer(restored_source, "test layer", "ogr")
            self.assertTrue(layer.isValid())
            del layer
            container_path.unlink()
            self.assertFalse(container_path.exists())

        with self.subTest("Relative path with layer name"):
            source = QDir(str(self.project_directory)).relativeFilePath(
                str(container_path)
            )
            self.assertTrue(
                source.startswith("..") and source.endswith(".gpkg")
            )

            source += layer_name
            restored_source = QgsPathResolver().readPath(source)
            self.assertEqual(restored_source, source)

            layer = QgsVectorLayer(str(container_path), "test layer", "ogr")
            self.assertTrue(layer.isValid())
            del layer
            container_path.unlink()
            self.assertFalse(container_path.exists())

    @mock_container(TestData.Points)
    def test_from_windows_to_current(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        self.__move_container(container_mock)
        connection = self.connection(TestConnection.SandboxGuest)
        resource = self.resource(TestData.Points)
        layer_name = container_mock.metadata.table_name

        with self.subTest("Absolute path"):
            windows_source = (
                r"C:/Users/User/AppData/Local/NextGIS/ngqgis/cache/NGConnect/"
                + connection.domain_uuid
                + "/"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = str(
                self.cache_directory
                / connection.domain_uuid
                / f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(windows_source), current_source
            )

        with self.subTest("Absolute path with backslashes"):
            windows_source = (
                r"C:\Users\User\AppData\Local\NextGIS\ngqgis\cache\NGConnect"
                "\\"
                + connection.domain_uuid
                + "\\"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = str(
                self.cache_directory
                / connection.domain_uuid
                / f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(windows_source), current_source
            )

        with self.subTest("Relative path"):
            posix_source = (
                r"../../AppData/Local/NextGIS/ngqgis/cache/NGConnect/"
                + connection.domain_uuid
                + "/"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = (
                QDir(str(self.project_directory)).relativeFilePath(
                    str(container_mock.path)
                )
                + f"|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(posix_source), current_source
            )

        with self.subTest("Relative path with backslashes"):
            posix_source = (
                r"..\..\AppData\Local\NextGIS\ngqgis\cache\NGConnect"
                "\\"
                + connection.domain_uuid
                + "/"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = (
                QDir(str(self.project_directory)).relativeFilePath(
                    str(container_mock.path)
                )
                + f"|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(posix_source), current_source
            )

    @mock_container(TestData.Points)
    def test_from_unix_to_current(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        self.__move_container(container_mock)
        connection = self.connection(TestConnection.SandboxGuest)
        resource = self.resource(TestData.Points)
        layer_name = container_mock.metadata.table_name

        with self.subTest("Absolute path"):
            posix_source = (
                "/home/user/.cache/NextGIS/ngqgis/NGConnect/"
                + connection.domain_uuid
                + "/"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = str(
                self.cache_directory
                / connection.domain_uuid
                / f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(posix_source), current_source
            )

        with self.subTest("Relative path"):
            posix_source = (
                "../../.cache/NextGIS/ngqgis/NGConnect/"
                + connection.domain_uuid
                + "/"
                + f"{resource.resource_id}.gpkg|layername={layer_name}"
            )

            current_source = (
                QDir(str(self.project_directory)).relativeFilePath(
                    str(container_mock.path)
                )
                + f"|layername={layer_name}"
            )

            self.assertEqual(
                QgsPathResolver().readPath(posix_source), current_source
            )

    def __move_container(self, container_mock: MagicMock) -> None:
        resource = self.resource(TestData.Points)
        connection = self.connection(TestConnection.SandboxGuest)
        domain_directory = self.cache_directory / connection.domain_uuid
        domain_directory.mkdir(exist_ok=True, parents=True)

        container_path = domain_directory / f"{resource.resource_id}.gpkg"
        safe_move(container_mock.path, container_path)

        container_mock.path = container_path


if __name__ == "__main__":
    unittest.main()
