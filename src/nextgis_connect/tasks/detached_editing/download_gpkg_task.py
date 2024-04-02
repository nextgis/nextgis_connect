import shutil
import tempfile
import urllib.parse
from pathlib import Path
from typing import cast

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.tasks.ng_connect_task import NgConnectTask


class DownloadGpkgTask(NgConnectTask):
    download_finished = pyqtSignal(bool, name="downloadFinished")

    __metadata: DetachedContainerMetaData
    __stub_path: Path
    __temp_path: Path

    def __init__(self, stub_path: Path) -> None:
        flags = QgsTask.Flags()
        super().__init__(flags=flags)

        try:
            self.__metadata = container_metadata(stub_path)
        except Exception:
            logger.exception("An error occured while GPKG downloading")
            raise

        description = self.tr('Downloading layer "{layer_name}"').format(
            layer_name=self.__metadata.layer_name
        )
        self.setDescription(description)

        self.__stub_path = stub_path
        self.__temp_path = Path(tempfile.mktemp(suffix=".gpkg"))

    def run(self) -> bool:
        connection_id = self.__metadata.connection_id
        resource_id = self.__metadata.resource_id
        srs_id = self.__metadata.srs_id

        logger.debug(
            f"<b>Start GPKG downloading</b> for layer {self.__metadata}"
        )

        connections_manager = NgwConnectionsManager()
        if not connections_manager.is_valid(connection_id):
            logger.error(f"Invalid connection for layer {self.__metadata}")
            return False

        export_params = {
            "format": "GPKG",
            "srs": srs_id,
            "fid": "",
            "zipped": "false",
        }
        export_url = (
            f"/api/resource/{resource_id}/export?"
            + urllib.parse.urlencode(export_params)
        )

        try:
            ngw_connection = QgsNgwConnection(connection_id)
            resources_factory = NGWResourceFactory(ngw_connection)
            ngw_layer = resources_factory.get_resource(resource_id)

            ngw_connection.download(export_url, str(self.__temp_path))

            detached_factory = DetachedLayerFactory()
            result = detached_factory.update_container(
                cast(NGWVectorLayer, ngw_layer), self.__temp_path
            )
        except Exception:
            logger.exception(
                f"An error occured while downloading layer {self.__metadata}"
            )
            return False

        return result

    def finished(self, result: bool) -> None:  # noqa: FBT001
        if result:
            try:
                shutil.move(self.__temp_path, self.__stub_path)
            except Exception:
                logger.exception("Can't replace stub file")
                result = False

        self.download_finished.emit(result)
        return super().finished(result)
