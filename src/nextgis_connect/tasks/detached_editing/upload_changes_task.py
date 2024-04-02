import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from nextgis_connect.detached_editing.action_extractor import ActionExtractor
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)


class UploadChangesTask(QgsTask):
    synchronization_finished = pyqtSignal(bool, name="synchronizationFinished")

    __metadata: DetachedContainerMetaData
    __container_path: Path

    def __init__(self, container_path: Path) -> None:
        flags = QgsTask.Flags()
        if hasattr(QgsTask.Flag, "Silent"):
            flags |= QgsTask.Flag.Silent
        super().__init__(flags=flags)

        try:
            self.__metadata = container_metadata(container_path)
        except Exception:
            logger.exception("An error occured while layer synchronization")
            raise

        description = self.tr('"{layer_name}" layer synchronization').format(
            layer_name=self.__metadata.layer_name
        )
        self.setDescription(description)

        self.__container_path = container_path

    def run(self) -> bool:
        container_path = str(self.__container_path)
        layer_name = self.__metadata.layer_name
        resource_id = self.__metadata.resource_id

        logger.debug(
            f'Started changes uploading for layer "{layer_name}" '
            f"(id={resource_id})"
        )

        try:
            with (
                closing(spatialite_connect(container_path)) as connection,
                closing(connection.cursor()) as cursor,
            ):
                self.__upload_changes(cursor)
                connection.commit()

        except Exception:
            logger.exception("Uploading changes error")
            return False

        logger.debug("Changes were successfully uploaded")

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        self.synchronization_finished.emit(result)

        return super().finished(result)

    def __upload_changes(self, cursor: sqlite3.Cursor) -> None:
        connection_id = self.__metadata.connection_id

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None

        ngw_connection = QgsNgwConnection(connection_id)

        if self.__metadata.is_versioning_enabled:
            self.__upload_versioned_changes(ngw_connection, cursor)
        else:
            self.__upload_added(ngw_connection, cursor)
            self.__upload_deleted(ngw_connection, cursor)
            self.__upload_updated(ngw_connection, cursor)
            self.__update_sync_date(cursor)

    def __upload_added(
        self,
        connection: QgsNgwConnection,
        cursor: sqlite3.Cursor,
    ) -> None:
        layer_metadata = self.__metadata

        extractor = ActionExtractor(layer_metadata, cursor)
        create_actions = extractor.extract_added_features()

        if len(create_actions) == 0:
            logger.debug("There are no creation actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(create_actions)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        assigned_fids = connection.patch(url, body)

        values = (
            (assigned_fids[i]["id"], action.fid)
            for i, action in enumerate(create_actions)
        )
        cursor.executemany(
            "UPDATE ngw_features_metadata SET ngw_fid=? WHERE fid=?", values
        )
        self.__clear_added(cursor)

    def __upload_deleted(
        self,
        connection: QgsNgwConnection,
        cursor: sqlite3.Cursor,
    ) -> None:
        layer_metadata = self.__metadata

        extractor = ActionExtractor(layer_metadata, cursor)
        deleted_actions = extractor.extract_deleted_features()

        if len(deleted_actions) == 0:
            logger.debug("There are no deletion actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(deleted_actions)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        connection.delete(url, body)

        self.__clear_deleted(cursor)

    def __upload_updated(
        self,
        connection: QgsNgwConnection,
        cursor: sqlite3.Cursor,
    ) -> None:
        layer_metadata = self.__metadata

        extractor = ActionExtractor(layer_metadata, cursor)
        updated_actions = extractor.extract_updated_features()

        if len(updated_actions) == 0:
            logger.debug("There are no update actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(updated_actions)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        connection.patch(url, body)

        self.__clear_updated(cursor)

    def __update_sync_date(self, cursor: sqlite3.Cursor) -> None:
        now = datetime.now()
        sync_date = now.isoformat()
        cursor.execute(f"UPDATE ngw_metadata SET sync_date='{sync_date}'")

    def __upload_versioned_changes(
        self,
        connection: QgsNgwConnection,
        cursor: sqlite3.Cursor,
    ) -> None:
        layer_metadata = self.__metadata
        resource_id = layer_metadata.resource_id
        resource_url = f"/api/resource/{resource_id}"

        extractor = ActionExtractor(layer_metadata, cursor)
        actions = extractor.extract_all()

        if len(actions) == 0:
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(actions)

        transaction_answer = connection.post(
            f"{resource_url}/feature/transaction/",
            dict(epoch=layer_metadata.epoch),
        )

        transaction_id = transaction_answer["id"]
        transaction_start_time = transaction_answer["started"]

        logger.debug(
            f"Transaction {transaction_id} started at {transaction_start_time}"
        )

        logger.debug(f"Put {len(actions)} actions")

        # TODO try
        connection.put(
            f"{resource_url}/feature/transaction/{transaction_id}",
            body,
        )

        logger.debug(f"Commit transaction {transaction_id}")

        try:
            result = connection.post(
                f"{resource_url}/feature/transaction/{transaction_id}"
            )
        except Exception:
            logger.exception("Exception occured while commiting transaction")
            connection.delete(
                f"{resource_url}/feature/transaction/{transaction_id}"
            )
            logger.debug(f"Transaction {transaction_id} disposed")
            raise

        if result["status"] != "committed":
            logger.error(f"Errors: {result}")
            raise RuntimeError

    def __clear_added(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("DELETE FROM ngw_added_features")

    def __clear_deleted(self, cursor: sqlite3.Cursor) -> None:
        cursor.executescript(
            """
            DELETE FROM ngw_features_metadata
                WHERE fid in (SELECT fid FROM ngw_removed_features);
            DELETE FROM ngw_removed_features;
            """
        )

    def __clear_updated(self, cursor: sqlite3.Cursor) -> None:
        cursor.executescript(
            """
            DELETE FROM ngw_updated_attributes;
            DELETE FROM ngw_updated_geometries;
            """
        )
