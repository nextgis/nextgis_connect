import shutil
import tempfile
import urllib.parse
from contextlib import closing
from pathlib import Path
from typing import cast

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
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
        logger.debug(
            f"<b>Start GPKG downloading</b> for layer {self.__metadata}"
        )

        is_downloaded = self.__download_layer()
        if not is_downloaded:
            return False

        # It's too slow now
        # is_downloaded = self.__download_extensions()
        # if not is_downloaded:
        #     return False

        logger.debug("Downloading GPKG completed")

        return True

    def finished(self, result: bool) -> None:  # noqa: FBT001
        if result:
            try:
                shutil.move(self.__temp_path, self.__stub_path)
            except Exception:
                logger.exception("Can't replace stub file")
                result = False

        self.download_finished.emit(result)
        return super().finished(result)

    def __download_layer(self) -> bool:
        connection_id = self.__metadata.connection_id
        resource_id = self.__metadata.resource_id
        srs_id = self.__metadata.srs_id

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

            logger.debug("Downloading layer")

            ngw_connection.download(export_url, str(self.__temp_path))

            logger.debug("Downloading completed")

            detached_factory = DetachedLayerFactory()
            is_updated = detached_factory.update_container(
                cast(NGWVectorLayer, ngw_layer), self.__temp_path
            )
            if not is_updated:
                return False

        except Exception:
            logger.exception(
                f"An error occured while downloading layer {self.__metadata}"
            )
            return False

        return True

    def __download_extensions(self) -> bool:
        connection_id = self.__metadata.connection_id
        resource_id = self.__metadata.resource_id

        extensions_params = {
            "geom": "no",
            "fields": "",
        }
        extensions_url = (
            f"/api/resource/{resource_id}/feature/?"
            + urllib.parse.urlencode(extensions_params)
        )

        try:
            logger.debug("Adding extensions")

            ngw_connection = QgsNgwConnection(connection_id)
            features_extensions = ngw_connection.get(extensions_url)

            with closing(
                spatialite_connect(str(self.__temp_path))
            ) as connection, closing(connection.cursor()) as cursor:
                metadata = container_metadata(cursor)

                serializer = ActionSerializer(metadata)
                actions = serializer.from_json(features_extensions)

                applier = ActionApplier(metadata, cursor)
                applier.apply(actions)

                connection.commit()

            logger.debug("Feature metadata updated")

        except Exception:
            logger.exception(
                f"An error occured while downloading layer {self.__metadata}"
            )
            return False

        return True
