from contextlib import closing
from pathlib import Path
from typing import Dict, List, Set, cast

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    is_fields_compatible,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.tasks.ng_connect_task import NgConnectTask


class FetchAdditionalDataTask(NgConnectTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    __need_update_structure: bool
    __container_path: Path
    __metadata: DetachedContainerMetaData

    __is_edit_allowed: bool
    __attributes_with_removed_lookup_table: Set[FieldId]
    __lookup_tables: Dict[int, List[Dict[str, str]]]

    def __init__(
        self, container_path: Path, *, need_update_structure: bool = False
    ) -> None:
        flags = QgsTask.Flags()
        super().__init__(flags=flags)

        self.__need_update_structure = need_update_structure
        self.__container_path = container_path

        try:
            self.__metadata = container_metadata(container_path)
        except Exception:
            logger.exception(
                "An error occured while layer metadata downloading"
            )
            raise

        description = self.tr(
            'Downloading layer "{layer_name}" metadata'
        ).format(layer_name=self.__metadata.layer_name)
        self.setDescription(description)

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
        logger.debug(f"<b>Fetch extra data</b> for layer {self.__metadata}")

        connection_id = self.__metadata.connection_id

        connections_manager = NgwConnectionsManager()
        if not connections_manager.is_valid(connection_id):
            logger.error(f"Invalid connection for layer {self.__metadata}")
            return False

        try:
            ngw_connection = QgsNgwConnection(connection_id)

            if self.__need_update_structure:
                self.__update_structure(ngw_connection)

            self.__get_permissions(ngw_connection)
            self.__get_lookup_tables(ngw_connection)

        except Exception:
            logger.exception(
                "An error occured while fetching extra data for layer "
                f'"{self.__metadata}"'
            )
            return False

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        self.download_finished.emit(result)

        return super().finished(result)

    def __update_structure(self, ngw_connection: QgsNgwConnection) -> None:
        logger.debug("Update structure")

        resource_id = self.__metadata.resource_id
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = cast(
            NGWVectorLayer, resources_factory.get_resource(resource_id)
        )

        if not is_fields_compatible(self.__metadata.fields, ngw_layer.fields):
            message = "Fields is not compatible"
            raise RuntimeError(message)

        self.__attributes_with_removed_lookup_table = set(
            field.attribute
            for field in self.__metadata.fields
            if field.lookup_table is not None
        )

        with closing(
            spatialite_connect(str(self.__container_path))
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
        self.__metadata = container_metadata(self.__container_path)

        self.__attributes_with_removed_lookup_table -= set(
            field.attribute
            for field in self.__metadata.fields
            if field.lookup_table is not None
        )

    def __get_permissions(self, ngw_connection: QgsNgwConnection) -> None:
        logger.debug("Get permissions")

        resource_id = self.__metadata.resource_id
        permission_url = f"/api/resource/{resource_id}/permission"
        permissions = ngw_connection.get(permission_url)
        self.__is_edit_allowed = permissions["data"]["write"]

    def __get_lookup_tables(self, ngw_connection: QgsNgwConnection) -> None:
        resource_id = self.__metadata.resource_id
        resource_url = "/api/resource/{resource_id}"

        lookup_table_resources_id = list(
            set(
                field.lookup_table
                for field in self.__metadata.fields
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
