import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.actions import (
    VersioningAction,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
)
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger
from nextgis_connect.tasks.detached_editing.detached_editing_task import (
    DetachedEditingTask,
)


class ApplyDeltaTask(DetachedEditingTask):
    apply_finished = pyqtSignal(bool, name="applyFinished")

    _container_path: Path
    _metadata: DetachedContainerMetaData

    __target: int
    __timestamp: datetime
    __delta: List[VersioningAction]

    def __init__(
        self,
        container_path: Path,
        target: int,
        timestamp: datetime,
        delta: List[VersioningAction],
    ) -> None:
        super().__init__(container_path)
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

        logger.debug(
            f"<b>Start changes applying</b> for layer {self._metadata}"
        )

        try:
            applier = ActionApplier(self._container_path, self._metadata)
            applier.apply(self.__delta)

            with closing(
                sqlite3.connect(str(self._container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    f"""
                    UPDATE ngw_metadata
                    SET version={self.__target}, sync_date={self.__timestamp}
                    """
                )
                connection.commit()

        except SynchronizationError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                f"An error occured while applying layer {self._metadata}"
                " changes"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True

    def finished(self, result: bool) -> None:
        self.apply_finished.emit(result)

        return super().finished(result)
