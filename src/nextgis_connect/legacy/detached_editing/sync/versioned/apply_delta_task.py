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

from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

from nextgis_connect.legacy.detached_editing.sync.common.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions import (
    FeatureAction,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions_applier import (
    ActionApplier,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import SynchronizationError


class ApplyDeltaTask(DetachedEditingTask):
    _container_path: Path
    _metadata: DetachedContainerMetaData

    __target: int
    __timestamp: datetime
    __delta: List[FeatureAction]

    def __init__(
        self,
        container_path: Path,
        target: int,
        timestamp: datetime,
        delta: List[FeatureAction],
    ) -> None:
        super().__init__(container_path)
        if self._error is not None:
            return

        description = self.tr(
            'Applying changes for layer "{layer_name}"'
        ).format(layer_name=self._metadata.layer_name)
        self.setDescription(description)

        self.__target = target
        self.__timestamp = timestamp
        self.__delta = delta

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(f"Start changes applying for layer {self._metadata}")

        try:
            applier = ActionApplier(self._container_path, self._metadata)
            applier.apply(self.__delta)

            with closing(
                make_connection(self._container_path)
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    "UPDATE ngw_metadata SET version=?, sync_date=?",
                    (self.__target, self.__timestamp),
                )
                connection.commit()

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                f"An error occurred while applying layer {self._metadata}"
                " changes"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True
