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

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


def classFactory(iface: "QgisInterface") -> NgConnectInterface:
    try:
        with QgsRuntimeProfiler.profile("Import plugin"):  # type: ignore
            from nextgis_connect.ng_connect_plugin import NgConnectPlugin

        plugin = NgConnectPlugin()

    except Exception as error:
        from nextgis_connect.ng_connect_plugin_stub import NgConnectPluginStub

        plugin = NgConnectPluginStub()
        plugin.show_error(error)

    return plugin
