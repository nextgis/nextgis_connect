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

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsTask,
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
    """Construct QGIS layers away from the GUI thread."""

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
    """Run a layer creation task and return its constructed layers."""

    def __init__(self, task_manager) -> None:
        self._task_manager = task_manager
        self._active_task: Optional[QgisLayerCreatorTask] = None

    def cancel(self) -> None:
        if self._active_task is not None:
            self._active_task.cancel()

    def create(
        self,
        parameters: Mapping[BatchLayerId, QgisLayerCreationParameters],
    ) -> Dict[BatchLayerId, QgsMapLayer]:
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
