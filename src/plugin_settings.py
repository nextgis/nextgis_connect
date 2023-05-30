"""
/***************************************************************************
 Plugins settings
                                 A QGIS plugin
 Compulink QGIS tools
                             -------------------
        begin                : 2014-10-31
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from .ngw_api.qgis.common_plugin_settings import PluginSettings as CommonPluginSettings


class PluginSettings(CommonPluginSettings):

    _company_name = 'NextGIS'
    _product = 'NextGISConnect'

    @classmethod
    def auto_open_web_map_option(cls):
        settings = cls.get_settings()
        return settings.value('/ui/autoOpenWebMapByDefault', True, type=bool)

    @classmethod
    def set_auto_open_web_map_option(cls, val):
        settings = cls.get_settings()
        settings.setValue('/ui/autoOpenWebMapByDefault', val)

    @classmethod
    def auto_add_wfs_option(cls):
        settings = cls.get_settings()
        return settings.value('/ui/autoAddWFSByDefault', True, type=bool)

    @classmethod
    def set_auto_add_wfs_option(cls, val):
        settings = cls.get_settings()
        settings.setValue('/ui/autoAddWFSByDefault', val)

    @classmethod
    def debug_mode(cls):
        settings = cls.get_settings()
        return settings.value('/debugMode', False, type=bool)

    @classmethod
    def set_debug_mode(cls, val):
        settings = cls.get_settings()
        settings.setValue('/debugMode', val)
