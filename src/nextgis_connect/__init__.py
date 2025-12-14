"""
/***************************************************************************
 NG Connect
                                 A QGIS plugin
 QGIS plugin for operating NGW resources
                             -------------------
        begin                : 2015-01-30
        copyright            : (C) 2015 by NextGIS
        email                : info@nextgis.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""

from typing import TYPE_CHECKING

from qgis.core import QgsRuntimeProfiler

from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


def classFactory(iface: "QgisInterface") -> NgConnectInterface:
    settings = NgConnectSettings()

    try:
        with QgsRuntimeProfiler.profile("Import plugin"):  # type: ignore
            from nextgis_connect.ng_connect_plugin import NgConnectPlugin

        plugin = NgConnectPlugin()

        settings.did_last_launch_fail = False

    except Exception as error:
        import copy

        from qgis.PyQt.QtCore import QTimer

        from nextgis_connect.exceptions import (
            NgConnectReloadAfterUpdateWarning,
        )
        from nextgis_connect.ng_connect_plugin_stub import NgConnectPluginStub

        error_copy = copy.deepcopy(error)
        exception = error_copy

        if not settings.did_last_launch_fail and isinstance(
            error, ImportError
        ):
            exception = NgConnectReloadAfterUpdateWarning()
            exception.__cause__ = error_copy

        settings.did_last_launch_fail = True

        plugin = NgConnectPluginStub()

        def display_exception() -> None:
            plugin.notifier.display_exception(exception)

        QTimer.singleShot(0, display_exception)

    return plugin
