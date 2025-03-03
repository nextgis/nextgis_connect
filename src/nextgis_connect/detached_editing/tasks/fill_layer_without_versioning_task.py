import tempfile
import urllib.parse
from contextlib import closing
from pathlib import Path
from typing import cast

from nextgis_connect.detached_editing.action_applier import ActionApplier
from nextgis_connect.detached_editing.action_serializer import ActionSerializer
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.tasks.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    make_connection,
)
from nextgis_connect.exceptions import (
    SynchronizationError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection


class FillLayerWithoutVersioningTask(DetachedEditingTask):
    def __init__(self, stub_path: Path) -> None:
        super().__init__(stub_path)
        if self._error is not None:
            return

        description = self.tr('Downloading layer "{layer_name}"').format(
            layer_name=self._metadata.layer_name
        )
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(
            f"<b>Start GPKG downloading</b> for layer {self._metadata}"
        )

        self.__temp_path = Path(tempfile.mktemp(suffix=".gpkg"))

        try:
            connection_id = self._metadata.connection_id
            ngw_connection = QgsNgwConnection(connection_id)

            self.__download_layer(ngw_connection)
            self.__copy_features(ngw_connection)

        except SynchronizationError as error:
            self._error = error
            self.__temp_path.unlink(missing_ok=True)
            return False

        except Exception as error:
            message = (
                f"An error occured while downloading layer {self._metadata}"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            self.__temp_path.unlink(missing_ok=True)
            return False

        logger.debug("Downloading GPKG completed")

        return True

    def __download_layer(self, ngw_connection: QgsNgwConnection) -> None:
        resource_id = self._metadata.resource_id
        srs_id = self._metadata.srs_id

        export_params = {
            "format": "GPKG",
            "srs": srs_id,
            "fid": self._metadata.fid_field,
            "zipped": "false",
        }
        export_url = (
            f"/api/resource/{resource_id}/export?"
            + urllib.parse.urlencode(export_params)
        )

        logger.debug("Downloading layer")
        ngw_connection.download(export_url, str(self.__temp_path))
        logger.debug("Downloading completed")

    def __copy_features(self, ngw_connection: QgsNgwConnection) -> None:
        resources_factory = NGWResourceFactory(ngw_connection)
        ngw_layer = resources_factory.get_resource(self._metadata.resource_id)

        detached_factory = DetachedLayerFactory()
        detached_factory.fill_container(
            cast(NGWVectorLayer, ngw_layer),
            source_path=self.__temp_path,
            container_path=self._container_path,
        )

    def __download_extensions(self) -> None:
        # TODO (ivanbarsukov): Uncomment. But it's too slow now
        return

        connection_id = self._metadata.connection_id
        resource_id = self._metadata.resource_id

        extensions_params = {
            "geom": "no",
            "fields": "",
        }
        extensions_url = (
            f"/api/resource/{resource_id}/feature/?"
            + urllib.parse.urlencode(extensions_params)
        )

        logger.debug("Adding extensions")

        ngw_connection = QgsNgwConnection(connection_id)
        features_extensions = ngw_connection.get(extensions_url)

        with closing(make_connection(self.__temp_path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            metadata = container_metadata(cursor)

            serializer = ActionSerializer(metadata)
            actions = serializer.from_json(features_extensions)

            applier = ActionApplier(metadata, cursor)
            applier.apply(actions)

            connection.commit()

        logger.debug("Features extensions added")
