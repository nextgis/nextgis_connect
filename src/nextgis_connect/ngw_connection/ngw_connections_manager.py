import uuid
from pathlib import Path
from typing import List, Optional

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings
from qgis.PyQt.QtCore import QSettings

from .ngw_connection import NgwConnection


class NgwConnectionsManager:
    __settings: QgsSettings
    __key: str = "/NextGIS/Connect/connections"

    def __init__(self) -> None:
        self.__settings = QgsSettings()

    @property
    def connections(self) -> List[NgwConnection]:
        self.__settings.beginGroup(self.__key)
        connection_ids = self.__settings.childGroups()
        self.__settings.endGroup()
        connections = [
            self.__read_connection(connection_id)
            for connection_id in connection_ids
        ]
        connections.sort(key=lambda connection: connection.name)
        return connections

    @property
    def current_connection(self) -> Optional[NgwConnection]:
        current_connection_id = self.current_connection_id
        if current_connection_id is None:
            return None
        return self.connection(current_connection_id)

    @property
    def current_connection_id(self) -> Optional[str]:
        value = self.__settings.value(
            "NextGIS/Connect/currentConnectionId", defaultValue=None
        )

        self.__settings.beginGroup(self.__key)
        connection_ids = self.__settings.childGroups()
        self.__settings.endGroup()

        if value is None or value not in connection_ids:
            if len(connection_ids) == 0:
                value = None
                self.current_connection_id = None
            else:
                value = next(iter(connection_ids))
                self.current_connection_id = value

        return value

    @current_connection_id.setter
    def current_connection_id(self, connecton_id: Optional[str]) -> None:
        self.__settings.setValue(
            "NextGIS/Connect/currentConnectionId", connecton_id
        )

    def connection(self, connection_id: str) -> Optional[NgwConnection]:
        return self.__read_connection(connection_id)

    def save(self, connection: NgwConnection) -> None:
        connection_key = f"{self.__key}/{connection.id}"
        self.__settings.setValue(f"{connection_key}/name", connection.name)
        self.__settings.setValue(f"{connection_key}/url", connection.url)
        self.__settings.setValue(
            f"{connection_key}/auth_config", connection.auth_config_id
        )

    def remove(self, connection_id: str) -> None:
        self.__settings.beginGroup(self.__key)
        self.__settings.remove(connection_id)
        self.__settings.endGroup()

        if connection_id == self.current_connection_id:
            self.current_connection_id = None

    def is_valid(self, connection_id: Optional[str]) -> bool:
        if connection_id is None or connection_id == "":
            return False

        self.__settings.beginGroup(self.__key)
        connection_ids = self.__settings.childGroups()
        self.__settings.endGroup()
        if connection_id not in connection_ids:
            return False

        connection = self.__read_connection(connection_id)
        if connection.auth_config_id is not None:
            auth_manager = QgsApplication.instance().authManager()
            configs = auth_manager.availableAuthMethodConfigs()
            if connection.auth_config_id not in configs:
                return False

        return True

    def has_not_converted_connections(self) -> bool:
        # Get old connections
        old_settings = QSettings("NextGIS", "NextGIS WEB API")
        old_settings.beginGroup("/connections")
        old_connections = old_settings.childGroups()
        old_settings.endGroup()

        # Get new connections
        new_connections = [connection.name for connection in self.connections]

        return len(set(old_connections) - set(new_connections)) > 0

    def convert_old_connections(self, convert_auth: bool = False) -> None:
        # Get old connections
        old_settings = QSettings("NextGIS", "NextGIS WEB API")
        selected_name = old_settings.value(
            "/ui/selectedConnection", "", type=str
        )
        old_settings.beginGroup("/connections")
        old_connection_names = old_settings.childGroups()
        old_settings.endGroup()

        # Get converted connections
        converted_connection_names = [
            connection.name for connection in self.connections
        ]

        for old_connection_name in old_connection_names:
            if old_connection_name in converted_connection_names:
                continue

            id = str(uuid.uuid4())
            key = "/connections/" + old_connection_name
            url = old_settings.value(key + "/server_url", "", type=str)
            username = old_settings.value(key + "/username", "", type=str)
            password = old_settings.value(key + "/password", "", type=str)
            is_oauth = old_settings.value(key + "/oauth", "", type=bool)

            auth_config_id = None
            if is_oauth:
                auth_config_id = "NextGIS"
            elif convert_auth:
                auth_config_id = self.__save_auth_method(
                    old_connection_name, username, password
                )

            self.save(
                NgwConnection(id, old_connection_name, url, auth_config_id)
            )

            if selected_name == old_connection_name:
                self.current_connection_id = id

        self.clear_old_connections_if_converted()

    def clear_old_connections_if_converted(self) -> None:
        if self.has_not_converted_connections():
            return

        old_settings = QSettings("NextGIS", "NextGIS WEB API")
        settings_path = Path(old_settings.fileName())
        if settings_path.exists() and settings_path.is_file():
            old_settings = None
            settings_path.unlink()
        else:
            old_settings.clear()

    def __read_connection(self, id: str):
        name = self.__settings.value(f"{self.__key}/{id}/name")
        url = self.__settings.value(f"{self.__key}/{id}/url")
        auth_config = self.__settings.value(f"{self.__key}/{id}/auth_config")
        return NgwConnection(id, name, url, auth_config)

    def __save_auth_method(
        self, connection_name, username, password
    ) -> Optional[str]:
        if len(username) == 0 or len(password) == 0:
            return None

        config_name = f"{connection_name} / {username}"

        auth_manager = QgsApplication.instance().authManager()

        # Check for duplicates
        configs = auth_manager.availableAuthMethodConfigs()
        for config_id, config in configs.items():
            if config.method() == "Basic" and config.name() == config_name:
                return config_id

        # Create new auth config
        auth_config = QgsAuthMethodConfig()
        auth_config.setName(config_name)
        auth_config.setMethod("Basic")
        auth_config.setConfig("username", username)
        auth_config.setConfig("password", password)

        # Store new config
        auth_manager.storeAuthenticationConfig(auth_config, overwrite=True)

        return auth_config.id()
