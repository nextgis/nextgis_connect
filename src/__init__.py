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


def classFactory(iface):
    from .ng_connect import NGConnectPlugin
    return NGConnectPlugin(iface)
