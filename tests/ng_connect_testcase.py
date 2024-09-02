import json
import os
import shutil
import tempfile
import uuid
from enum import Enum, auto
from pathlib import Path
from typing import ClassVar, Dict
from unittest.mock import MagicMock

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsMapLayer,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.testing import QgisTestCase, start_app

from nextgis_connect.ngw_api.core import NGWResource
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection import NgwConnection, NgwConnectionsManager

QGIS_AUTH_DB_DIR_PATH = tempfile.mkdtemp()

os.environ["QGIS_AUTH_DB_DIR_PATH"] = QGIS_AUTH_DB_DIR_PATH


class TestData(str, Enum):
    Points = "layers/points_layer.gpkg"

    def __str__(self) -> str:
        return str(self.value)


class TestConnection(Enum):
    SandboxGuest = auto()
    SandboxWithLogin = auto()
    # UserWithEmail = auto()
    # UserWithOAuth = auto()
    # UserWithNgStd = auto()


class NgConnectTestCase(QgisTestCase):
    _connections_id: ClassVar[Dict[TestConnection, str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        # Setup settings
        QgsApplication.setOrganizationName("NextGIS_Test")
        QgsApplication.setOrganizationDomain("TestNextGISConnect.com")
        QgsApplication.setApplicationName("TestNextGISConnect")
        QgsSettings().clear()
        start_app()

        # Setup auth manager
        auth_manager = QgsApplication.authManager()
        assert not auth_manager.isDisabled(), auth_manager.disabledMessage()
        assert (
            Path(auth_manager.authenticationDatabasePath())
            == Path(QGIS_AUTH_DB_DIR_PATH) / "qgis-auth.db"
        )
        assert auth_manager.setMasterPassword("masterpassword", True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(QGIS_AUTH_DB_DIR_PATH)
        QgsSettings().clear()
        super().tearDownClass()

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

    @staticmethod
    def resource(
        test_data: TestData,
        test_connection: TestConnection = TestConnection.SandboxGuest,
    ) -> NGWResource:
        data_path = NgConnectTestCase.data_path(test_data)
        json_path = data_path.with_suffix(".json")
        resource_json = json.loads(json_path.read_text())

        connection = NgConnectTestCase.connection(test_connection)

        ngw_connection = MagicMock(spec=QgsNgwConnection)
        ngw_connection.connection_id = connection.id
        ngw_connection.server_url = connection.url

        factory = NGWResourceFactory(ngw_connection)
        return factory.get_resource_by_json(resource_json)

    @classmethod
    def connection_id(cls, test_connection: TestConnection) -> str:
        cls._init_connections()
        return cls._connections_id[test_connection]

    @classmethod
    def connection(cls, test_connection: TestConnection) -> NgwConnection:
        cls._init_connections()

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(
            cls._connections_id[test_connection]
        )
        assert connection is not None
        return connection

    @classmethod
    def _init_connections(cls) -> None:
        if len(cls._connections_id) > 0:
            return

        connections_manager = NgwConnectionsManager()
        auth_manager = QgsApplication.authManager()

        # Create guest connection
        guest_connection_id = str(uuid.uuid4())
        guest_connection = NgwConnection(
            guest_connection_id,
            "TEST_GUEST_CONNECTION",
            "https://sandbox.nextgis.com/",
            None,
        )
        connections_manager.save(guest_connection)
        cls._connections_id[TestConnection.SandboxGuest] = guest_connection_id

        # Create basic connection
        auth_config = QgsAuthMethodConfig("Basic")
        auth_config.setName("test_auth_config")
        auth_config.setConfig("username", "administrator")
        auth_config.setConfig("password", "demodemo")
        assert auth_manager.storeAuthenticationConfig(auth_config)[0]

        basic_connection_id = str(uuid.uuid4())
        basic_connection = NgwConnection(
            basic_connection_id,
            "TEST_LOGIN_CONNECTION",
            "https://sandbox.nextgis.com/",
            auth_config.id(),
        )
        connections_manager.save(basic_connection)
        cls._connections_id[TestConnection.SandboxWithLogin] = (
            basic_connection_id
        )
