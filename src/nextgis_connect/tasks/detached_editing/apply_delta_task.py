from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.actions import (
    VersioningAction,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
)
from nextgis_connect.logging import logger
from nextgis_connect.tasks.ng_connect_task import NgConnectTask


class ApplyDeltaTask(NgConnectTask):
    apply_finished = pyqtSignal(bool, name="applyFinished")

    __container_path: Path
    __metadata: DetachedContainerMetaData

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
        flags = QgsTask.Flags()
        super().__init__(flags=flags)

        self.__container_path = container_path
        self.__target = target
        self.__timestamp = timestamp
        self.__delta = delta

        try:
            self.__metadata = container_metadata(container_path)
        except Exception:
            logger.exception("An error occured while applying changes")
            raise

        description = self.tr(
            'Applying changes for layer "{layer_name}"'
        ).format(layer_name=self.__metadata.layer_name)
        self.setDescription(description)

    def run(self) -> bool:
        try:
            with closing(
                spatialite_connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                applier = ActionApplier(self.__metadata, cursor)
                applier.apply(self.__delta)

                cursor.execute(
                    f"""
                    UPDATE ngw_metadata
                    SET version={self.__target}, sync_date={self.__timestamp}
                    """
                )
                connection.commit()

        except Exception:
            logger.exception(
                f"An error occured while applying layer {self.__metadata}"
                " changes"
            )
            return False

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        self.apply_finished.emit(result)

        return super().finished(result)
