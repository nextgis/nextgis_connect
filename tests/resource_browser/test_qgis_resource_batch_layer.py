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

from typing import Dict

from nextgis_connect.features.resource_browser.infrastructure import (
    qgis_resource_batch_layer as layer_module,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_layer import (
    BatchLayerId,
    QgisLayerCreationParameters,
    QgisLayerCreatorTask,
)


def test_layer_creator_stops_after_cancellation(qgis_app, monkeypatch) -> None:
    del qgis_app
    created_layer_names = []
    task = None

    class _CancelingLayer:
        def __init__(self, uri: str, name: str, provider_key: str) -> None:
            del uri, provider_key
            created_layer_names.append(name)
            task.cancel()

        def setParent(self, parent) -> None:
            del parent

        def moveToThread(self, thread) -> None:
            del thread

    monkeypatch.setattr(layer_module, "QgsVectorLayer", _CancelingLayer)
    parameters: Dict[BatchLayerId, QgisLayerCreationParameters] = {
        1: QgisLayerCreationParameters("uri-1", "First", "ogr"),
        2: QgisLayerCreationParameters("uri-2", "Second", "ogr"),
    }
    task = QgisLayerCreatorTask(parameters)

    assert task.run() is False
    assert list(task.layers) == [1]
    assert created_layer_names == ["First"]
