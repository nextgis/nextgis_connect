from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.actions import (
    FeatureAction,
)
from nextgis_connect.detached_editing.tasks.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)
from nextgis_connect.exceptions import SynchronizationError
from nextgis_connect.logging import logger


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

        logger.debug(
            f"<b>Start changes applying</b> for layer {self._metadata}"
        )

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
                f"An error occured while applying layer {self._metadata}"
                " changes"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True
