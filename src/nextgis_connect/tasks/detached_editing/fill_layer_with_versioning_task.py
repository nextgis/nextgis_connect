import sqlite3
from contextlib import closing
from pathlib import Path

from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.actions import ContinueAction
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.tasks.detached_editing.detached_editing_task import (
    DetachedEditingTask,
)


class FillLayerWithVersioning(DetachedEditingTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    def __init__(self, stub_path: Path) -> None:
        super().__init__(stub_path)
        if self._error is not None:
            return

        description = self.tr('Downloading layer "{layer_name}"').format(
            layer_name=self._metadata.layer_name
        )
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(f"<b>Start filling</b> layer{self._metadata}")

        connection_id = self._metadata.connection_id
        resource_id = self._metadata.resource_id

        try:
            ngw_connection = QgsNgwConnection(connection_id)

            # Check structure etc
            self._get_layer(ngw_connection)

            check_result = ngw_connection.get(
                f"/api/resource/{resource_id}/feature/changes/check"
            )
            fetch_url = check_result["fetch"]

            serializer = ActionSerializer(self._metadata)
            actions = serializer.from_json(ngw_connection.get(fetch_url))
            while len(actions) > 0:
                applier = ActionApplier(self._container_path, self._metadata)
                applier.apply(actions)

                continue_action = actions[-1]
                assert isinstance(continue_action, ContinueAction)
                actions = serializer.from_json(
                    ngw_connection.get(continue_action.url)
                )

            sync_date = check_result["tstamp"]
            with closing(
                sqlite3.connect(str(self._container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    f"UPDATE ngw_metadata SET sync_date='{sync_date}'"
                )
                connection.commit()

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                f"An error occured while downloading layer {self._metadata}"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True

    def finished(self, result: bool) -> None:
        self.download_finished.emit(result)
        return super().finished(result)
