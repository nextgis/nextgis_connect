import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.actions import (
    ContinueAction,
    VersioningAction,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.tasks.ng_connect_task import NgConnectTask


class FetchDeltaTask(NgConnectTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    __metadata: DetachedContainerMetaData
    __target: int
    __timestamp: datetime
    __delta: List[VersioningAction]

    def __init__(self, stub_path: Path) -> None:
        flags = QgsTask.Flags()
        super().__init__(flags=flags)

        try:
            self.__metadata = container_metadata(stub_path)
        except Exception:
            logger.exception("An error occured while layer downloading")
            raise

        description = self.tr(
            'Downloading changes for layer "{layer_name}"'
        ).format(layer_name=self.__metadata.layer_name)
        self.setDescription(description)

        self.__target = -1
        self.__timestamp = datetime.now()
        self.__delta = []

    @property
    def target(self) -> int:
        return self.__target

    @property
    def timestamp(self) -> datetime:
        return self.__timestamp

    @property
    def delta(self) -> List[VersioningAction]:
        return self.__delta

    def run(self) -> bool:
        connection_id = self.__metadata.connection_id
        resource_id = self.__metadata.resource_id

        connections_manager = NgwConnectionsManager()
        if not connections_manager.is_valid(connection_id):
            logger.error(f"Invalid connection for layer {self.__metadata}")
            return False

        try:
            ngw_connection = QgsNgwConnection(connection_id)
            check_params = urllib.parse.urlencode(
                {
                    "epoch": self.__metadata.epoch,
                    "initial": self.__metadata.version,
                }
            )
            check_result = ngw_connection.get(
                f"/api/resource/{resource_id}/feature/changes/check?{check_params}"
            )

            self.__target = check_result["target"]
            self.__timestamp = datetime.fromisoformat(check_result["tstamp"])
            fetch_url = check_result["fetch"]

            serializer = ActionSerializer(self.__metadata)
            actions = serializer.from_json(ngw_connection.get(fetch_url))

            while len(actions) > 0:
                self.__delta.extend(actions)

                continue_action = actions[-1]
                assert isinstance(continue_action, ContinueAction)
                actions = serializer.from_json(
                    ngw_connection.get(continue_action.url)
                )

        except Exception:
            logger.exception(
                f"An error occured while downloading layer {self.__metadata}"
                " changes"
            )
            return False

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        self.download_finished.emit(result)

        return super().finished(result)
