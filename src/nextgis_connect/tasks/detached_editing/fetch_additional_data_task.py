import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Set

from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.utils import (
    container_metadata,
)
from nextgis_connect.exceptions import (
    SynchronizationError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.tasks.detached_editing import DetachedEditingTask


class FetchAdditionalDataTask(DetachedEditingTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    __need_update_structure: bool

    __is_edit_allowed: bool
    __attributes_with_removed_lookup_table: Set[FieldId]
    __lookup_tables: Dict[int, List[Dict[str, str]]]

    def __init__(
        self, container_path: Path, *, need_update_structure: bool = False
    ) -> None:
        super().__init__(container_path)
        description = self.tr(
            'Downloading layer "{layer_name}" metadata'
        ).format(layer_name=self._metadata.layer_name)
        self.setDescription(description)

        if self._error is not None:
            return

        self.__need_update_structure = need_update_structure
        self.__is_edit_allowed = False
        self.__attributes_with_removed_lookup_table = set()
        self.__lookup_tables = {}

    @property
    def is_edit_allowed(self) -> bool:
        return self.__is_edit_allowed

    @property
    def lookup_tables(self) -> Dict[int, List[Dict[str, str]]]:
        return self.__lookup_tables

    @property
    def attributes_with_removed_lookup_table(self) -> Set[FieldId]:
        return self.__attributes_with_removed_lookup_table

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(f"<b>Fetch extra data</b> for layer {self._metadata}")

        try:
            ngw_connection = QgsNgwConnection(self._metadata.connection_id)

            if self.__need_update_structure:
                self.__update_structure(ngw_connection)

            self.__get_permissions(ngw_connection)
            self.__get_lookup_tables(ngw_connection)

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                "An error occured while fetching extra data for layer "
                f"{self._metadata}"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True

    def finished(self, result: bool) -> None:
        self.download_finished.emit(result)

        return super().finished(result)

    def __update_structure(self, ngw_connection: QgsNgwConnection) -> None:
        logger.debug("Update structure")

        ngw_layer = self._get_layer(ngw_connection)

        self.__attributes_with_removed_lookup_table = set(
            field.attribute
            for field in self._metadata.fields
            if field.lookup_table is not None
        )

        with closing(
            sqlite3.connect(str(self._container_path))
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executemany(
                """
                UPDATE ngw_fields_metadata
                SET
                    display_name=?,
                    is_label=?,
                    lookup_table=?
                WHERE ngw_id=?
                """,
                (
                    (
                        field.display_name,
                        field.is_label,
                        field.lookup_table,
                        field.ngw_id,
                    )
                    for field in ngw_layer.fields
                ),
            )
            connection.commit()

        # Update for next tasks
        self._metadata = container_metadata(self._container_path)

        self.__attributes_with_removed_lookup_table -= set(
            field.attribute
            for field in self._metadata.fields
            if field.lookup_table is not None
        )

    def __get_permissions(self, ngw_connection: QgsNgwConnection) -> None:
        logger.debug("Get permissions")

        resource_id = self._metadata.resource_id
        permission_url = f"/api/resource/{resource_id}/permission"
        permissions = ngw_connection.get(permission_url)
        self.__is_edit_allowed = permissions["data"]["write"]

    def __get_lookup_tables(self, ngw_connection: QgsNgwConnection) -> None:
        resource_id = self._metadata.resource_id
        resource_url = "/api/resource/{resource_id}"

        lookup_table_resources_id = list(
            set(
                field.lookup_table
                for field in self._metadata.fields
                if field.lookup_table is not None
            )
        )

        if len(lookup_table_resources_id) > 0:
            logger.debug("Get lookup tables")

        for lookup_table_id in lookup_table_resources_id:
            try:
                result = ngw_connection.get(
                    resource_url.format(resource_id=lookup_table_id)
                )
            except Exception:
                logger.exception(f"Can't get lookup table {resource_id}")
                continue

            lookup_table = result.get("lookup_table")
            if lookup_table is None:
                continue

            self.__lookup_tables[lookup_table_id] = [
                {description: value}
                for value, description in lookup_table["items"].items()
            ]
