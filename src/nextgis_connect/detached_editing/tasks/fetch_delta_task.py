import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from nextgis_connect.detached_editing.actions import (
    ContinueAction,
    VersioningAction,
)
from nextgis_connect.detached_editing.actions.serializer import (
    ActionSerializer,
)
from nextgis_connect.detached_editing.tasks.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.exceptions import (
    ErrorCode,
    NgwError,
    SynchronizationError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.resources.ngw_fields import NgwFields


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

            check_params = urllib.parse.urlencode(
                {
                    "epoch": self._metadata.epoch,
                    "initial": self._metadata.version,
                    "extensions": "attachment,description",
                }
            )
            check_url = f"/api/resource/{resource_id}/feature/changes/check?{check_params}"

            try:
                check_result = ngw_connection.get(check_url)
            except NgwError as error:
                if (
                    error.ngw_exception_class.split(".")[-1]
                    != "FVersioningNotEnabled"
                ):
                    raise

                error = SynchronizationError(
                    "Versioning is not enabled",
                    code=ErrorCode.VersioningDisabled,
                )
                raise error

            if check_result is None:
                self.__delta = []
                return True

            self._check_compatibility(check_result)

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

    def _check_compatibility(self, answer: Dict[str, Any]) -> None:
        if self._metadata.epoch != answer["epoch"]:
            message = "Epoch changed"
            code = ErrorCode.EpochChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.epoch}")
            error.add_note(f"Remote: {answer['epoch']}")
            raise error

        if self._metadata.geometry_name != answer["geometry_type"]:
            message = "Geometry is not compatible"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.geometry_name}")
            error.add_note(f"Remote: {answer['geometry_type']}")
            raise error

        if self._metadata.srs_id != answer["srs"]["id"]:
            message = "SRS is not compatible"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.geometry_name}")
            error.add_note(f"Remote: {answer['srs']['id']}")
            raise error

        if self._is_container_fields_changed():
            message = "Fields changed in QGIS"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            raise error

        ngw_layer_fields = NgwFields.from_json(answer["fields"])
        if not self._is_fields_compatible(ngw_layer_fields):
            message = "Fields changed in NGW"
            code = ErrorCode.StructureChanged
            error = SynchronizationError(message, code=code)
            error.add_note(f"Local: {self._metadata.fields}")
            error.add_note(f"Remote: {ngw_layer_fields}")
            raise error
