from contextlib import closing
from pathlib import Path

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.actions import ContinueAction
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


class FillLayerWithVersioning(NgConnectTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    __metadata: DetachedContainerMetaData
    __output_path: Path

    def __init__(self, stub_path: Path) -> None:
        flags = QgsTask.Flags()
        super().__init__(flags=flags)

        try:
            self.__metadata = container_metadata(stub_path)
        except Exception:
            logger.exception("An error occured while layer downloading")
            raise

        description = self.tr('Downloading layer "{layer_name}"').format(
            layer_name=self.__metadata.layer_name
        )
        self.setDescription(description)

        self.__output_path = stub_path

    def run(self) -> bool:
        connection_id = self.__metadata.connection_id
        resource_id = self.__metadata.resource_id
        layer_name = self.__metadata.layer_name

        connections_manager = NgwConnectionsManager()
        if not connections_manager.is_valid(connection_id):
            logger.error(f'Invalid connection for layer "{layer_name}"')
            return False

        try:
            ngw_connection = QgsNgwConnection(connection_id)
            check_result = ngw_connection.get(
                f"/api/resource/{resource_id}/feature/changes/check"
            )
            fetch_url = check_result["fetch"]

            serializer = ActionSerializer(self.__metadata)
            actions = serializer.from_json(ngw_connection.get(fetch_url))
            while len(actions) > 0:
                with (
                    closing(
                        spatialite_connect(str(self.__output_path))
                    ) as connection,
                    closing(connection.cursor()) as cursor,
                ):
                    applier = ActionApplier(self.__metadata, cursor)
                    applier.apply(actions)
                    connection.commit()

                continue_action = actions[-1]
                assert isinstance(continue_action, ContinueAction)
                actions = serializer.from_json(
                    ngw_connection.get(continue_action.url)
                )

            sync_date = check_result["tstamp"]
            with (
                closing(
                    spatialite_connect(str(self.__output_path))
                ) as connection,
                closing(connection.cursor()) as cursor,
            ):
                cursor.execute(
                    f"UPDATE ngw_metadata SET sync_date='{sync_date}'"
                )
                connection.commit()

        except Exception:
            logger.exception(
                "An error occured while downloading layer "
                f'"{self.__metadata.layer_name}"'
            )
            return False

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        self.download_finished.emit(result)

        return super().finished(result)
