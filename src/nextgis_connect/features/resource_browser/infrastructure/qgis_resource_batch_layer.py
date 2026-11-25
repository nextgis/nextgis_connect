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
            destination = (
                gui_parameters
                if layer_parameters.provider_key.lower() == "copc"
                else worker_parameters
            )
            destination[insertion_id] = layer_parameters

        if len(worker_parameters) == 0:
            return self._create_point_cloud_layers(gui_parameters)

        task = QgisLayerCreatorTask(worker_parameters)
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

            # Route subsequent cancellation to the GUI phase.
            self._active_task = None
            task.layers.update(self._create_point_cloud_layers(gui_parameters))
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
        for i, (insertion_id, layer_parameters) in enumerate(
            parameters.items()
        ):
            if self._cancel_requested:
                break

            counter = f"[{i + 1}/{count}] " if count > 1 else ""
            logger.debug(
                f"{counter}Creating {layer_parameters.provider_key} layer "
                f'"{layer_parameters.name}"'
            )
            layer = QgsPointCloudLayer(*layer_parameters.as_arguments())
            if self._cancel_requested:
                layer.deleteLater()
                break

            if not layer.isValid():
                error = layer.error().summary()
                logger.warning(
                    f'Layer "{layer_parameters.name}" is not valid: {error}'
                )
            elif (
                layer.renderer3D() is None
                and layer.sync3DRendererTo2DRenderer()
            ):
                renderer_3d = QgsPointCloudLayer3DRenderer()
                renderer_3d.convertFrom2DRenderer(layer.renderer())
                layer.setRenderer3D(renderer_3d)

            layers[insertion_id] = layer

        return layers
