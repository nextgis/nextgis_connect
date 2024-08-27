import unittest

from nextgis_connect.detached_editing import utils
from qgis.testing import start_app

from tests.ng_connect_testcase import NgConnectTestCase, TestData

start_app()


class TestDetachedLayerEditingUtils(NgConnectTestCase):
    def test_container_path(self) -> None:
        layer_path = self.data_path(TestData.Points)
        self.assertEqual(utils.container_path(layer_path), layer_path)
        self.assertEqual(
            utils.container_path(self.layer(TestData.Points)), layer_path
        )

    def test_detached_layer_uri(self) -> None:
        layer_path = self.data_path(TestData.Points)
        layer_uri = self.layer_uri(TestData.Points)
        self.assertEqual(utils.detached_layer_uri(layer_path), layer_uri)

    def test_is_ngw_container(self) -> None:
        with self.subTest("With path"):
            layer_path = self.data_path(TestData.Points)
            self.assertFalse(utils.is_ngw_container(layer_path))
            # TODO true

        with self.subTest("With layer"):
            layer = self.layer(TestData.Points)

            layer.setCustomProperty("ngw_is_detached_layer", True)
            self.assertTrue(utils.is_ngw_container(layer))
            layer.setCustomProperty("ngw_is_detached_layer", False)
            self.assertFalse(utils.is_ngw_container(layer))


if __name__ == "__main__":
    unittest.main()
