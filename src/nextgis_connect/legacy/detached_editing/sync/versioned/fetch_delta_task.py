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

import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nextgis_connect.legacy.detached_editing.sync.common.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions import (
    ContinueAction,
    VersioningAction,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions_filter import (
    ActionsFilter,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions_serializer import (
    ActionSerializer,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.resources.ngw_fields import NgwFields
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgwError,
    SynchronizationError,
)


class FetchDeltaTask(DetachedEditingTask):
    _VERSIONING_NOT_ENABLED = "FVersioningNotEnabled"
    _VERSIONING_EPOCH_MISMATCH = "FVersioningEpochMismatch"

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

        logger.debug(f"Start changes fetching for layer {self._metadata}")

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
                synchronization_error = self._synchronization_error(error)
                if synchronization_error is None:
                    raise

                raise synchronization_error from error

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

            actions_filter = ActionsFilter()
            self.__delta = actions_filter.filter(self.__delta)

            logger.debug(f"Fetched {len(self.__delta)} actions")

        except SynchronizationError as error:
            self._error = error
            return False

        except NgwError as error:
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

    def _synchronization_error(
        self,
        error: NgwError,
    ) -> Optional[SynchronizationError]:
        exception_class = self._ngw_exception_class_name(error)
        if exception_class == self._VERSIONING_NOT_ENABLED:
            return SynchronizationError(
                "Versioning is not enabled",
                code=ErrorCode.VersioningDisabled,
            )

        if exception_class == self._VERSIONING_EPOCH_MISMATCH:
            return SynchronizationError(
                "Epoch changed",
                code=ErrorCode.EpochChanged,
            )

        return None

    def _ngw_exception_class_name(self, error: NgwError) -> Optional[str]:
        if error.ngw_exception_class is None:
            return None

        return error.ngw_exception_class.split(".")[-1]

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
            error.add_note(f"Local: {self._metadata.srs_id}")
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
