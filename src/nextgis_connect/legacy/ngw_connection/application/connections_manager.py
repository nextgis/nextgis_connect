# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from dataclasses import replace
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QObject, pyqtSignal

from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.infrastructure.settings_migrator import (
    NgwConnectionSettingsMigrator,
)
from nextgis_connect.legacy.ngw_connection.infrastructure.settings_repository import (
    QgisConnectionSettingsRepository,
)


class ConnectionUpdateState(Enum):
    CREATED = auto()
    DELETED = auto()
    MODIFIED = auto()


class NgwConnectionsManager(QObject):
    connection_updated = pyqtSignal(str, object)

    __settings_repository: QgisConnectionSettingsRepository
    __connections: Dict[str, NgwConnection]
    __initial_connections: Dict[str, NgwConnection]
    __current_connection_id: Optional[str]
    __initial_current_connection_id: Optional[str]
    __migrator: NgwConnectionSettingsMigrator
    __auth_config_ids_to_remove: Set[str]
    __is_migrated: bool

    def __init__(
        self,
        connections: Optional[List[NgwConnection]] = None,
        parent: Optional[QObject] = None,
        *,
        current_connection_id: Optional[str] = None,
        settings_repository: Optional[QgisConnectionSettingsRepository] = None,
        migrator: Optional[NgwConnectionSettingsMigrator] = None,
    ) -> None:
        super().__init__(parent)
        self.__settings_repository = (
            QgisConnectionSettingsRepository()
            if settings_repository is None
            else settings_repository
        )
        self.__migrator = (
            NgwConnectionSettingsMigrator() if migrator is None else migrator
        )
        self.__auth_config_ids_to_remove = set()
        self.__is_migrated = False

        if connections is None:
            snapshot = self.__settings_repository.read_snapshot()
            loaded_connections = list(snapshot.connections)
            loaded_current_connection_id = snapshot.current_connection_id
            (
                loaded_connections,
                loaded_current_connection_id,
                is_migrated,
            ) = self.__migrator.migrate(
                loaded_connections,
                loaded_current_connection_id,
            )
        else:
            loaded_connections = connections
            loaded_current_connection_id = (
                self.__settings_repository.read_current_connection_id()
                if current_connection_id is None
                else current_connection_id
            )
            is_migrated = False

        self.__connections = self.__connections_by_id(loaded_connections)
        self.__current_connection_id = self.__normalized_current_connection_id(
            loaded_current_connection_id
        )
        if is_migrated:
            self.__is_migrated = True
            self.__write_all_connections()

        self.__initial_connections = dict(self.__connections)
        self.__initial_current_connection_id = self.__current_connection_id

    @property
    def connections(self) -> List[NgwConnection]:
        connections = list(self.__connections.values())
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
        return self.__current_connection_id

    @current_connection_id.setter
    def current_connection_id(self, connection_id: Optional[str]) -> None:
        self.__current_connection_id = self.__normalized_current_connection_id(
            connection_id
        )

    @property
    def is_changed(self) -> bool:
        return (
            self.__current_connection_id
            != self.__initial_current_connection_id
            or self.__connections != self.__initial_connections
        )

    @property
    def is_migrated(self) -> bool:
        return self.__is_migrated

    def connection(self, connection_id: str) -> Optional[NgwConnection]:
        connection = self.__connections.get(connection_id)
        if connection is not None:
            return connection

        for connection in self.__connections.values():
            if connection.matches_id(connection_id):
                return connection

        return None

    def find_connection_by_url(
        self,
        url: str,
        *,
        exclude_connection_id: Optional[str] = None,
    ) -> Optional[NgwConnection]:
        normalized_url = NgwConnection.normalize_url(url)

        for connection in self.connections:
            if connection.id == exclude_connection_id:
                continue

            if NgwConnection.normalize_url(connection.url) == normalized_url:
                return connection

        return None

    def upsert(self, connection: NgwConnection) -> None:
        self.__connections[connection.id] = connection
        if self.__current_connection_id is None:
            self.__current_connection_id = connection.id

    def replace_connections(self, connections: List[NgwConnection]) -> None:
        self.__connections = self.__connections_by_id(connections)
        self.__current_connection_id = self.__normalized_current_connection_id(
            self.__current_connection_id
        )

    def remove(self, connection_id: str) -> None:
        self.__auth_config_ids_to_remove.update(
            self.auth_config_ids_for_connection(connection_id)
        )
        self.__connections.pop(connection_id, None)
        self.__current_connection_id = self.__normalized_current_connection_id(
            self.__current_connection_id
        )

    def reset(self) -> None:
        self.__connections = dict(self.__initial_connections)
        self.__current_connection_id = self.__initial_current_connection_id
        self.__auth_config_ids_to_remove.clear()

    def auth_config_ids_for_connection(self, connection_id: str) -> List[str]:
        connection = self.connection(connection_id)
        if connection is None:
            return []

        auth_config_ids: Set[str] = set()
        if (
            connection.auth_config_id is not None
            and connection.auth_config_id != "NextGIS"
        ):
            auth_config_ids.add(connection.auth_config_id)

        normalized_url = NgwConnection.normalize_url(connection.url)
        auth_manager = QgsApplication.authManager()
        configs = auth_manager.availableAuthMethodConfigs()
        for config_id, config in configs.items():
            if config_id == "NextGIS":
                continue

            method = config.method() or auth_manager.configAuthMethodKey(
                config_id
            )
            if method != "Basic":
                continue

            resource = config.uri().strip()
            if len(resource) == 0:
                continue

            if NgwConnection.normalize_url(resource) != normalized_url:
                continue

            auth_config_ids.add(config_id)

        return sorted(auth_config_ids)

    def set_connection_auth_config_id(
        self,
        connection_id: str,
        auth_config_id: Optional[str],
        *,
        persist: bool = False,
    ) -> None:
        connection = self.__connections.get(connection_id)
        initial_connection = self.__initial_connections.get(connection_id)
        if connection is None and initial_connection is None:
            return

        if connection is not None:
            self.__connections[connection_id] = replace(
                connection,
                auth_config_id=auth_config_id,
            )

        if initial_connection is None:
            return

        updated_initial_connection = replace(
            initial_connection,
            auth_config_id=auth_config_id,
        )
        self.__initial_connections[connection_id] = updated_initial_connection
        if persist:
            self.__write_connection(updated_initial_connection)

    def save(self) -> None:
        if not self.is_changed:
            return

        previous_connections = dict(self.__initial_connections)
        current_connections = dict(self.__connections)
        connection_updates = self.__collect_updates(
            previous_connections,
            current_connections,
        )

        self.__write_all_connections()

        self.__initial_connections = current_connections
        self.__initial_current_connection_id = self.__current_connection_id

        for connection_id, state in connection_updates:
            self.connection_updated.emit(connection_id, state)

        auth_config_ids_to_remove = set(self.__auth_config_ids_to_remove)

        for connection_id, state in connection_updates:
            if state != ConnectionUpdateState.DELETED:
                continue

            removed_connection = previous_connections.get(connection_id)
            if removed_connection is None:
                continue

            if (
                removed_connection.auth_config_id is not None
                and removed_connection.auth_config_id != "NextGIS"
            ):
                auth_config_ids_to_remove.add(
                    removed_connection.auth_config_id
                )

        for auth_config_id in sorted(auth_config_ids_to_remove):
            self.__migrator.remove_auth_if_unused(
                auth_config_id,
                self.connections,
            )
        self.__auth_config_ids_to_remove.clear()

    def __write_connection(self, connection: NgwConnection) -> None:
        self.__settings_repository.write_connection(connection)

    def __write_all_connections(self) -> None:
        self.__settings_repository.write_snapshot(
            list(self.__connections.values()),
            self.__current_connection_id,
        )

    def is_valid(self, connection_id: Optional[str]) -> bool:
        return self.invalid_reason(connection_id) is None

    def invalid_reason(self, connection_id: Optional[str]) -> Optional[str]:
        if connection_id is None or connection_id == "":
            return self.tr("No connection is selected.")

        connection = self.connection(connection_id)
        if connection is None:
            return self.tr("The selected connection no longer exists.")

        if connection.auth_config_id is not None:
            auth_manager = QgsApplication.instance().authManager()
            configs = auth_manager.availableAuthMethodConfigs()
            if connection.auth_config_id not in configs:
                return self.tr(
                    "Saved sign-in parameters for the selected connection were "
                    "deleted from the QGIS authentication database."
                )

        return None

    def has_not_converted_connections(self) -> bool:
        return self.__migrator.has_not_converted_connections(self.connections)

    def convert_old_connections(self, convert_auth: bool = False) -> None:
        connections, current_connection_id, changed = (
            self.__migrator.convert_old_connections(
                self.connections,
                self.__current_connection_id,
                convert_auth=convert_auth,
            )
        )
        if not changed:
            return

        self.__connections = self.__connections_by_id(connections)
        self.__current_connection_id = self.__normalized_current_connection_id(
            current_connection_id
        )
        self.save()

    def clear_old_connections_if_converted(self) -> None:
        self.__migrator.clear_old_connections_if_converted(self.connections)

    def __connections_by_id(
        self,
        connections: List[NgwConnection],
    ) -> Dict[str, NgwConnection]:
        return {connection.id: connection for connection in connections}

    def __normalized_current_connection_id(
        self,
        connection_id: Optional[str],
    ) -> Optional[str]:
        if connection_id in self.__connections:
            return connection_id

        if connection_id is not None:
            connection = self.connection(connection_id)
            if connection is not None:
                return connection.id

        if len(self.__connections) == 0:
            return None

        return self.connections[0].id

    def __collect_updates(
        self,
        previous_connections: Dict[str, NgwConnection],
        current_connections: Dict[str, NgwConnection],
    ) -> Tuple[Tuple[str, ConnectionUpdateState], ...]:
        updates = []

        for connection_id in sorted(previous_connections):
            if connection_id in current_connections:
                continue
            updates.append((connection_id, ConnectionUpdateState.DELETED))

        for connection_id in sorted(current_connections):
            previous_connection = previous_connections.get(connection_id)
            connection = current_connections[connection_id]
            if previous_connection is None:
                updates.append((connection_id, ConnectionUpdateState.CREATED))
                continue

            if previous_connection != connection:
                updates.append((connection_id, ConnectionUpdateState.MODIFIED))

        return tuple(updates)
