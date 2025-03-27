import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List

from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.actions import (
    ContinueAction,
    VersioningAction,
)
from nextgis_connect.detached_editing.tasks.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection


class FetchDeltaTask(DetachedEditingTask):
    __target: int
    __timestamp: datetime
    __delta: List[VersioningAction]

    def __init__(self, stub_path: Path) -> None:
        super().__init__(stub_path)
        if self._error is not None:
            return

        description = self.tr(
            'Downloading changes for layer "{layer_name}"'
        ).format(layer_name=self._metadata.layer_name)
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
        if not super().run():
            return False

        logger.debug(
            f"<b>Start changes fetching</b> for layer {self._metadata}"
        )

        connection_id = self._metadata.connection_id
        resource_id = self._metadata.resource_id

        try:
            ngw_connection = QgsNgwConnection(connection_id)

            # Check structure etc
            self._get_layer(ngw_connection)

            check_params = urllib.parse.urlencode(
                {
                    "epoch": self._metadata.epoch,
                    "initial": self._metadata.version,
                }
            )
            check_result = ngw_connection.get(
                f"/api/resource/{resource_id}/feature/changes/check?{check_params}"
            )
            if check_result is None:
                self.__delta = []
                return True

            self.__target = check_result["target"]
            self.__timestamp = datetime.fromisoformat(check_result["tstamp"])
            fetch_url = check_result["fetch"]

            serializer = ActionSerializer(self._metadata)
            actions = serializer.from_json(ngw_connection.get(fetch_url))

            while len(actions) > 0:
                self.__delta.extend(actions)

                continue_action = actions[-1]
                assert isinstance(continue_action, ContinueAction)
                actions = serializer.from_json(
                    ngw_connection.get(continue_action.url)
                )

            logger.debug(f"Fetched {len(self.__delta)} actions")

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                f"An error occurred while downloading layer {self._metadata}"
                " changes"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True
