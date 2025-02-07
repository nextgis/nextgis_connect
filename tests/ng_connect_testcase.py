import atexit
import json
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Union
from unittest.mock import MagicMock

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsMapLayer,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.testing import QgisTestCase

from nextgis_connect.ngw_api.core import NGWResource
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection import NgwConnection, NgwConnectionsManager


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


@dataclass
class ApplicationInfo:
    APPLICATION_NAME = "TestNextGISConnect"
    ORGANIZATION_NAME = "NextGIS_Test"
    ORGANIZATION_DOMAIN = "TestNextGISConnect.com"

    application: QgsApplication
    qgis_custom_config_path: Path
    qgis_auth_db_path: Path


APPLICATION_INFO: Optional[ApplicationInfo] = None


class NgConnectTestCase(QgisTestCase):
    _connections_id: ClassVar[Dict[TestConnection, str]] = {}
    _temp_paths: ClassVar[List[Path]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._temp_paths = []
        start_qgis()

    @classmethod
    def tearDownClass(cls):
        QgsSettings().clear()

        for path in cls._temp_paths:
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink(missing_ok=True)

        super().tearDownClass()

    @classmethod
    def create_temp_file(cls, suffix: str = "") -> Path:
        path = Path(
            tempfile.mktemp(
                prefix=f"{ApplicationInfo.APPLICATION_NAME}-", suffix=suffix
            )
        )
        cls._temp_paths.append(path)
        return path

    @classmethod
    def create_temp_dir(cls, suffix: str = "") -> Path:
        path = Path(
            tempfile.mkdtemp(
                prefix=f"{ApplicationInfo.APPLICATION_NAME}-", suffix=suffix
            )
        )
        cls._temp_paths.append(path)
        return path

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
    def resource_json(
        test_data: TestData,
    ) -> Dict[str, Any]:
        data_path = NgConnectTestCase.data_path(test_data)
        json_path = data_path.with_suffix(".json")
        return json.loads(json_path.read_text())

    @staticmethod
    def resource(
        test_data: Union[TestData, Dict[str, Any]],
        test_connection: Union[
            TestConnection, NgwConnection
        ] = TestConnection.SandboxGuest,
    ) -> NGWResource:
        if isinstance(test_data, TestData):
            resource_json = NgConnectTestCase.resource_json(test_data)
        else:
            resource_json = test_data

        if isinstance(test_connection, TestConnection):
            connection = NgConnectTestCase.connection(test_connection)
        else:
            connection = test_connection

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


def start_qgis() -> None:
    """
    Will start a QgsApplication and call all initialization code like
    registering the providers and other infrastructure. It will not load
    any plugins.

    You can always get the reference to a running app by calling `QgsApplication.instance()`.

    The initialization will only happen once, so it is safe to call this method repeatedly.
    """
    global APPLICATION_INFO

    if APPLICATION_INFO is not None:
        return

    # Application params
    QgsApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )

    # Tests params
    QgsApplication.setOrganizationName(ApplicationInfo.ORGANIZATION_NAME)
    QgsApplication.setOrganizationDomain(ApplicationInfo.ORGANIZATION_DOMAIN)
    QgsApplication.setApplicationName(ApplicationInfo.APPLICATION_NAME)
    QgsSettings().clear()

    # In python3 we need to convert to a bytes object (or should
    # QgsApplication accept a QString instead of const char* ?)
    argvb = list(map(os.fsencode, sys.argv))

    # Note: QGIS_PREFIX_PATH is evaluated in QgsApplication -
    # no need to mess with it here.
    application = QgsApplication(argvb, GUIenabled=True)

    # Setup paths
    qgis_custom_config_path = tempfile.mkdtemp(
        prefix=f"{ApplicationInfo.APPLICATION_NAME}-config-"
    )
    qgis_auth_db_path = tempfile.mkdtemp(
        prefix=f"{ApplicationInfo.APPLICATION_NAME}-authdb-"
    )
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = qgis_custom_config_path
    os.environ["QGIS_AUTH_DB_DIR_PATH"] = qgis_auth_db_path

    # Save application info
    APPLICATION_INFO = ApplicationInfo(
        application=application,
        qgis_custom_config_path=Path(qgis_custom_config_path),
        qgis_auth_db_path=Path(qgis_auth_db_path),
    )

    # Initialize qgis
    application.initQgis()

    # Setup logging
    def print_log_message(message, tag, level):
        print(f"{tag}({level}): {message}")  # noqa: T201

    QgsApplication.instance().messageLog().messageReceived.connect(
        print_log_message
    )

    # Setup auth manager
    auth_manager = QgsApplication.authManager()
    assert not auth_manager.isDisabled(), auth_manager.disabledMessage()
    assert (
        Path(auth_manager.authenticationDatabasePath())
        == APPLICATION_INFO.qgis_auth_db_path / "qgis-auth.db"
    )
    assert auth_manager.setMasterPassword("masterpassword", True)

    # print(QGISAPP.showSettings())

    atexit.register(stop_qgis)


def stop_qgis() -> None:
    """
    Cleans up and exits QGIS
    """

    if APPLICATION_INFO is None:
        return

    APPLICATION_INFO.application.exitQgis()
    del APPLICATION_INFO.application

    shutil.rmtree(APPLICATION_INFO.qgis_custom_config_path)
    shutil.rmtree(APPLICATION_INFO.qgis_auth_db_path)

    for temp_file in Path(tempfile.gettempdir()).glob(
        f"{ApplicationInfo.APPLICATION_NAME}*"
    ):
        if temp_file.is_dir():
            shutil.rmtree(str(temp_file))
        else:
            temp_file.unlink(missing_ok=True)
