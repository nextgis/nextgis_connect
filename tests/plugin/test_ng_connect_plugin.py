from pathlib import Path

import qgis.utils
from qgis.utils import updateAvailablePlugins

import nextgis_connect
from nextgis_connect.compat import parse_version
from nextgis_connect.core.constants import PACKAGE_NAME
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from tests.ng_connect_testcase import NgConnectTestCase, TestConnection


class TestNgConnectPlugin(NgConnectTestCase):
    def test_plugin_deprecation(self) -> None:
        settings = NgConnectSettings()
        suppoted_version_for_connect = parse_version(
            settings.supported_ngw_version
        )

        connection_id = self.connection_id(TestConnection.DemoGuest)
        connection = QgsNgwConnection(connection_id)
        data = connection.get("api/component/pyramid/pkg_version")
        ngw_version = parse_version(data["nextgisweb"])

        self.assertTrue(
            suppoted_version_for_connect.major == ngw_version.major
            and suppoted_version_for_connect.minor == ngw_version.minor
        )

    def test_plugin_creation(self) -> None:
        nextgis_connect_path = Path(nextgis_connect.__file__).parents[1]
        qgis.utils.plugin_paths.append(str(nextgis_connect_path))
        updateAvailablePlugins()
        qgis.utils.plugins[PACKAGE_NAME] = nextgis_connect.classFactory(
            qgis.utils.iface  # pyright: ignore[reportArgumentType]
        )
