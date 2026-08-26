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

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import qgis.utils
from qgis import core as qgis_core
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtWidgets import QToolBar

import nextgis_connect
from nextgis_connect.shared.constants import PACKAGE_NAME


def test_plugin_package_imports(qgis_iface) -> None:
    del qgis_iface

    plugin_module = importlib.import_module("nextgis_connect.plugin.plugin")

    assert callable(nextgis_connect.classFactory)
    assert plugin_module.NgConnectPlugin is not None


def test_plugin_module_imports_without_vector_tile_layer() -> None:
    source_root = Path(nextgis_connect.__file__).resolve().parents[1]
    script = """
import sys
import qgis.core

sys.path.insert(0, sys.argv[1])
if hasattr(qgis.core, "QgsVectorTileLayer"):
    del qgis.core.QgsVectorTileLayer

import nextgis_connect.plugin.plugin
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(source_root)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_plugin_loads(qgis_iface) -> None:
    plugin = nextgis_connect.classFactory(qgis_iface)
    qgis.utils.plugins[PACKAGE_NAME] = plugin

    plugin._load()

    try:
        assert plugin.container is not None
    finally:
        plugin._unload()
        qgis.utils.plugins.pop(PACKAGE_NAME, None)


def test_plugin_loads_without_vector_tile_layer(
    qgis_iface,
    monkeypatch,
) -> None:
    monkeypatch.delattr(qgis_core, "QgsVectorTileLayer", raising=False)
    plugin = nextgis_connect.classFactory(qgis_iface)
    qgis.utils.plugins[PACKAGE_NAME] = plugin

    plugin._load()

    try:
        assert plugin.container is not None
    finally:
        plugin._unload()
        qgis.utils.plugins.pop(PACKAGE_NAME, None)


def test_unload_ignores_deleted_cache_purge_task(monkeypatch) -> None:
    from nextgis_connect.plugin import plugin_container
    from nextgis_connect.plugin.plugin_container import PluginContainer

    container = object.__new__(PluginContainer)
    purge_cache_task = MagicMock()
    task_attribute = "_PluginContainer__purge_cache_task"
    unload_method = "_PluginContainer__unload_cache_purging"
    setattr(container, task_attribute, purge_cache_task)
    monkeypatch.setattr(plugin_container.sip, "isdeleted", lambda _: True)

    getattr(container, unload_method)()

    purge_cache_task.cancel.assert_not_called()
    purge_cache_task.waitForFinished.assert_not_called()
    assert getattr(container, task_attribute) is None


def test_plugin_reload_cleans_ui_resources(qgis_iface) -> None:
    from nextgis_connect.legacy.detached_editing.identification.identification_tool import (
        IdentificationTool,
    )
    from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
        NgConnectDock,
    )
    from nextgis_connect.platform.qgis import utils as qgis_platform_utils

    qgis_platform_utils.iface = qgis_iface
    main_window = qgis_iface.mainWindow()
    initial_rubber_band_count = sum(
        isinstance(item, QgsRubberBand)
        for item in qgis_iface.mapCanvas().scene().items()
    )
    qgis_iface.addDockWidget.side_effect = main_window.addDockWidget
    qgis_iface.removeDockWidget.side_effect = main_window.removeDockWidget
    initial_layer_action_additions = (
        qgis_iface.addCustomActionForLayerType.call_count
    )
    initial_layer_action_removals = (
        qgis_iface.removeCustomActionForLayerType.call_count
    )
    initial_project_export_additions = (
        qgis_iface.addProjectExportAction.call_count
    )
    initial_project_export_removals = (
        qgis_iface.removeProjectExportAction.call_count
    )

    for _ in range(2):
        plugin = nextgis_connect.classFactory(qgis_iface)
        qgis.utils.plugins[PACKAGE_NAME] = plugin
        plugin._load()

        try:
            assert main_window.findChildren(QToolBar, "NgConnectToolBar")
            assert main_window.findChildren(NgConnectDock, "NGConnectDock")
            identify_tools = qgis_iface.mapCanvas().findChildren(
                IdentificationTool
            )
            assert len(identify_tools) == 1
            qgis_iface.mapCanvas().setMapTool(identify_tools[0])
        finally:
            plugin._unload()
            qgis.utils.plugins.pop(PACKAGE_NAME, None)

        assert main_window.findChildren(QToolBar, "NgConnectToolBar") == []
        assert main_window.findChildren(NgConnectDock, "NGConnectDock") == []
        assert qgis_iface.mapCanvas().findChildren(IdentificationTool) == []
        assert (
            sum(
                isinstance(item, QgsRubberBand)
                for item in qgis_iface.mapCanvas().scene().items()
            )
            == initial_rubber_band_count
        )

    layer_action_additions = (
        qgis_iface.addCustomActionForLayerType.call_count
        - initial_layer_action_additions
    )
    layer_action_removals = (
        qgis_iface.removeCustomActionForLayerType.call_count
        - initial_layer_action_removals
    )
    assert layer_action_removals == layer_action_additions
    assert (
        qgis_iface.addProjectExportAction.call_count
        - initial_project_export_additions
    ) == 2
    assert (
        qgis_iface.removeProjectExportAction.call_count
        - initial_project_export_removals
    ) == 2
