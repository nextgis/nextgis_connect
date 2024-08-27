from enum import Enum
from pathlib import Path

from qgis.core import QgsMapLayer, QgsVectorLayer
from qgis.testing import QgisTestCase


class TestData(str, Enum):
    Points = "layers/points_layer.gpkg"

    def __str__(self) -> str:
        return str(self.value)


class NgConnectTestCase(QgisTestCase):
    @staticmethod
    def data_path(test_data: TestData) -> Path:
        return Path(__file__).parent / "test_data" / str(test_data)

    @staticmethod
    def layer_uri(test_data: TestData) -> str:
        assert str(test_data).startswith("layers")

        data_path = NgConnectTestCase.data_path(test_data)
        if not data_path.suffix == ".gpkg":
            return str(data_path)

        return f"{data_path}|layername={data_path.stem}"

    @staticmethod
    def layer(test_data: TestData) -> QgsMapLayer:
        if str(test_data).endswith(("gpkg", "shp")):
            return QgsVectorLayer(
                NgConnectTestCase.layer_uri(test_data),
                Path(str(test_data)).stem,
                "ogr",
            )

        raise NotImplementedError
