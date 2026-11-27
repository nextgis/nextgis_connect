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

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple, Union

from qgis._3d import QgsPointCloudLayer3DRenderer
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsPointCloudLayer,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsTask,
    QgsTaskManager,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEventLoop, QModelIndex

from nextgis_connect.legacy.detached_editing.utils import is_ngw_container
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.tasks import NgConnectTask

BatchLayerId = Union[QModelIndex, int]


@dataclass(frozen=True)
class QgisLayerCreationParameters:
    """Store provider arguments required to construct one QGIS layer."""

    uri: str
    name: str
    provider_key: str

    @property
    def is_empty(self) -> bool:
        return self.provider_key == ""

    def as_arguments(self) -> Tuple[str, str, str]:
        return self.uri, self.name, self.provider_key


class QgisLayerCreatorTask(NgConnectTask):
    """Construct vector and raster layers outside the GUI thread."""

    _VECTOR_PROVIDERS = ("ogr", "wfs", "oapif", "postgres")

    def __init__(
        self,
        parameters: Mapping[BatchLayerId, QgisLayerCreationParameters],
    ) -> None:
        super().__init__(QgsTask.Flag.CanCancel)
        self._parameters = dict(parameters)
        self._layers: Dict[BatchLayerId, QgsMapLayer] = {}

    @property
    def layers(self) -> Dict[BatchLayerId, QgsMapLayer]:
        return self._layers

    def run(self) -> bool:
        """Construct the configured layers."""
        super().run()
        main_thread = QgsApplication.instance().thread()
        count = len(self._parameters)

        for i, (insertion_id, parameters) in enumerate(
            self._parameters.items()
        ):
            if self.isCanceled():
                return False

            counter = f"[{i + 1}/{count}] " if count > 1 else ""
            logger.debug(
                f"{counter}Creating {parameters.provider_key} layer "
                f'"{parameters.name}"'
            )

            if parameters.provider_key.lower() in self._VECTOR_PROVIDERS:
                layer = QgsVectorLayer(*parameters.as_arguments())
            else:
                layer = QgsRasterLayer(*parameters.as_arguments())

            layer.setParent(None)
            layer.moveToThread(main_thread)
            if self.isCanceled():
                # Keep ownership until the GUI thread clears the result.
                self._layers[insertion_id] = layer
                return False

            if not layer.isValid():
                error = layer.error().summary()
                logger.warning(
                    f'Layer "{parameters.name}" is not valid: {error}'
                )

            self._fix_crs(layer)
            self._layers[insertion_id] = layer

        return True

    @staticmethod
    def _fix_crs(layer: QgsMapLayer) -> None:
        """Apply provider-specific CRS compatibility corrections."""
        provider = layer.dataProvider().name()
        if provider == "wms":
            provider_metadata = (
                QgsProviderRegistry.instance().providerMetadata("wms")
            )
            if provider_metadata is None:
                return

            parameters = provider_metadata.decodeUri(layer.source())
            crs_id = parameters.get("crs")
            if crs_id is None:
                return

            crs = QgsCoordinateReferenceSystem.fromOgcWmsCrs(crs_id)
            if crs.isValid():
                layer.setCrs(crs)
            return

        if (
            provider == "ogr"
            and not layer.crs().isValid()
            and is_ngw_container(layer)
        ):
            layer.setCrs(QgsCoordinateReferenceSystem.fromEpsgId(3857))


class QgisBatchLayerFactory:
    """Create QGIS layers for batch resource imports."""

    def __init__(self, task_manager: QgsTaskManager) -> None:
        self._task_manager: QgsTaskManager = task_manager
        self._active_task: Optional[QgisLayerCreatorTask] = None
        self._cancel_requested: bool = False

    def cancel(self) -> None:
        """Request cancellation of the current creation operation."""
        if self._active_task is not None:
            self._active_task.cancel()
        self._cancel_requested = True

    def create(
        self,
        parameters: Mapping[BatchLayerId, QgisLayerCreationParameters],
    ) -> Dict[BatchLayerId, QgsMapLayer]:
        """Create all requested layers.

        :param parameters: Provider arguments keyed by insertion target.
        :return: Constructed layers keyed by insertion target.
        """
        self._cancel_requested = False
        worker_parameters: Dict[BatchLayerId, QgisLayerCreationParameters] = {}
        gui_parameters: Dict[BatchLayerId, QgisLayerCreationParameters] = {}
        for insertion_id, layer_parameters in parameters.items():
            if layer_parameters.provider_key.lower() == "copc":
                gui_parameters[insertion_id] = layer_parameters
            else:
                worker_parameters[insertion_id] = layer_parameters

        if not worker_parameters:
            return self._create_point_cloud_layers(gui_parameters)

        worker_layers = self._create_worker_layers(worker_parameters)
        if self._cancel_requested:
            worker_layers.clear()
            return worker_layers

        worker_layers.update(self._create_point_cloud_layers(gui_parameters))
        return worker_layers

    def _create_worker_layers(
        self,
        parameters: Mapping[BatchLayerId, QgisLayerCreationParameters],
    ) -> Dict[BatchLayerId, QgsMapLayer]:
        """Create vector and raster layers through a background QGIS task.

        :param parameters: Provider arguments keyed by insertion target.
        :return: Constructed layers keyed by insertion target.
        """
        task = QgisLayerCreatorTask(parameters)
        self._active_task = task
        event_loop = QEventLoop()
        task.taskCompleted.connect(event_loop.exit)
        task.taskTerminated.connect(event_loop.exit)
        self._task_manager.addTask(task)
        event_loop.exec()
        try:
            if task.isCanceled():
                task.layers.clear()
            return task.layers
        finally:
            self._active_task = None

    def _create_point_cloud_layers(
        self,
        parameters: Mapping[BatchLayerId, QgisLayerCreationParameters],
    ) -> Dict[BatchLayerId, QgsMapLayer]:
        """Construct point-cloud layers in the GUI thread.
        :param parameters: COPC provider arguments keyed by insertion target.
        :return: Constructed point-cloud layers keyed by insertion target.
        """
        layers: Dict[BatchLayerId, QgsMapLayer] = {}
        count = len(parameters)
        for index, (insertion_id, layer_parameters) in enumerate(
            parameters.items()
        ):
            if self._cancel_requested:
                break

            layer = self._create_point_cloud_layer(
                layer_parameters,
                index,
                count,
            )
            if layer is None:
                break

            layers[insertion_id] = layer

        return layers

    def _create_point_cloud_layer(
        self,
        parameters: QgisLayerCreationParameters,
        index: int,
        count: int,
    ) -> Optional[QgsPointCloudLayer]:
        """Construct and configure one point-cloud layer in the GUI thread.

        :param parameters: Provider arguments for the point-cloud layer.
        :param index: Zero-based layer position in the batch.
        :param count: Total number of point-cloud layers in the batch.
        :return: Configured layer, or ``None`` when cancellation was requested.
        """
        counter = f"[{index + 1}/{count}] " if count > 1 else ""
        logger.debug(
            f"{counter}Creating {parameters.provider_key} layer "
            f'"{parameters.name}"'
        )
        layer = QgsPointCloudLayer(*parameters.as_arguments())
        if self._cancel_requested:
            layer.deleteLater()
            return None

        if not layer.isValid():
            error = layer.error().summary()
            logger.warning(f'Layer "{parameters.name}" is not valid: {error}')
            return layer

        self._configure_point_cloud_renderer(layer)
        return layer

    @staticmethod
    def _configure_point_cloud_renderer(layer: QgsPointCloudLayer) -> None:
        """Initialize a 3D renderer from the layer's 2D renderer when possible.

        :param layer: Valid point-cloud layer to configure.
        """
        if layer.renderer3D() is not None:
            return
        if not layer.sync3DRendererTo2DRenderer():
            return

        renderer_3d = QgsPointCloudLayer3DRenderer()
        renderer_3d.convertFrom2DRenderer(layer.renderer())
        layer.setRenderer3D(renderer_3d)
