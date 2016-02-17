# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NGW Connect
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


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load CompulinkToolsPlugin class from file CompulinkToolsPlugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #check
    import ngw_api
    try:
        ngw_api.check_env()
    except EnvironmentError, ex:
        from qgis.gui import QgsMessageBar
        iface.messageBar().pushMessage("NGWConnext Error", ex.message, level=QgsMessageBar.CRITICAL)
        raise

    from .ngw_connect import NGWConnectPlugin
    return NGWConnectPlugin(iface)
