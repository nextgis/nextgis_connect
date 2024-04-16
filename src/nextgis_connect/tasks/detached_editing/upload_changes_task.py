import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.action_extractor import ActionExtractor
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.tasks.detached_editing.detached_editing_task import (
    DetachedEditingTask,
)


class UploadChangesTask(DetachedEditingTask):
    synchronization_finished = pyqtSignal(bool, name="synchronizationFinished")

    def __init__(self, container_path: Path) -> None:
        super().__init__(container_path)
        description = self.tr('"{layer_name}" layer synchronization').format(
            layer_name=self._metadata.layer_name
        )
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(
            f"<b>Started changes uploading</b> for layer {self._metadata}"
        )

        try:
            self.__upload_changes()

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = f"An error occured while uploading changes for {self._metadata}"
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True

    def finished(self, result: bool) -> None:
        self.synchronization_finished.emit(result)
        return super().finished(result)

    def __upload_changes(self) -> None:
        ngw_connection = QgsNgwConnection(self._metadata.connection_id)

        if self._metadata.is_versioning_enabled:
            self.__upload_versioned_changes(ngw_connection)
        else:
            # Check structure etc
            self._get_layer(ngw_connection)

            # Uploading
            self.__upload_added(ngw_connection)
            self.__upload_deleted(ngw_connection)
            self.__upload_updated(ngw_connection)
            self.__update_sync_date()

    def __upload_added(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata

        extractor = ActionExtractor(self._container_path, layer_metadata)
        create_actions = extractor.extract_added_features()

        if len(create_actions) == 0:
            logger.debug("There are no creation actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(create_actions)

        logger.debug(f"Send {len(create_actions)} create actions")

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        assigned_fids = ngw_connection.patch(url, body)

        values = (
            (assigned_fids[i]["id"], action.fid)
            for i, action in enumerate(create_actions)
        )

        with closing(self._make_connection()) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.executemany(
                "UPDATE ngw_features_metadata SET ngw_fid=? WHERE fid=?",
                values,
            )
            self.__clear_added(cursor)
            connection.commit()

    def __upload_deleted(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata

        extractor = ActionExtractor(self._container_path, layer_metadata)
        deleted_actions = extractor.extract_deleted_features()

        if len(deleted_actions) == 0:
            logger.debug("There are no deletion actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(deleted_actions)

        logger.debug(f"Send {len(deleted_actions)} delete actions")

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        ngw_connection.delete(url, body)

        with closing(self._make_connection()) as connection, closing(
            connection.cursor()
        ) as cursor:
            self.__clear_deleted(cursor)
            connection.commit()

    def __upload_updated(
        self,
        ngw_connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata

        extractor = ActionExtractor(self._container_path, layer_metadata)
        updated_actions = extractor.extract_updated_features()

        if len(updated_actions) == 0:
            logger.debug("There are no update actions")
            return

        serializer = ActionSerializer(layer_metadata)
        body = serializer.to_json(updated_actions)

        logger.debug(f"Send {len(updated_actions)} update actions")

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        ngw_connection.patch(url, body)

        with closing(self._make_connection()) as connection, closing(
            connection.cursor()
        ) as cursor:
            self.__clear_updated(cursor)
            connection.commit()

    def __update_sync_date(self) -> None:
        now = datetime.now()
        sync_date = now.isoformat()

        with closing(self._make_connection()) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(f"UPDATE ngw_metadata SET sync_date='{sync_date}'")
            connection.commit()

    def __upload_versioned_changes(
        self,
        connection: QgsNgwConnection,
    ) -> None:
        layer_metadata = self._metadata
        resource_id = layer_metadata.resource_id
        resource_url = f"/api/resource/{resource_id}"

        extractor = ActionExtractor(self._container_path, layer_metadata)
        actions = extractor.extract_all()

        if len(actions) == 0:
            logger.debug("There are no changes for uploading")
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

        logger.debug(f"Send {len(actions)} actions")

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
            error = SynchronizationError("Transaction is not committed")
            error.add_note(f"Synchronization id: {transaction_id}")
            error.add_note(f"Status: {result['status']}")
            raise error

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
