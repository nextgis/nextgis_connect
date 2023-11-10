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


from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QSettings


class NgConnectSettings:
    """Convenience class for working with plugin settings"""

    __settings: QgsSettings

    def __init__(self) -> None:
        self.__settings = QgsSettings()
        self.__migrate()

    @property
    def open_web_map_after_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            'openWebMapAfterCreation', defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @open_web_map_after_creation.setter
    def open_web_map_after_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue('openWebMapAfterCreation', value)
        self.__settings.endGroup()

    @property
    def add_layer_after_service_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        # TODO: remove "wfs" from key
        result = self.__settings.value(
            'addWfsLayerAfterServiceCreation', defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @add_layer_after_service_creation.setter
    def add_layer_after_service_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue('addWfsLayerAfterServiceCreation', value)
        self.__settings.endGroup()

    @property
    def is_debug_enabled(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            'debugEnabled', defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @is_debug_enabled.setter
    def is_debug_enabled(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue('debugEnabled', value)
        self.__settings.endGroup()

    @property
    def __plugin_group(self) -> str:
        return 'NextGIS/NGConnect'

    def __migrate(self) -> None:
        """Migrate from QSettings to QgsSettings"""
        settings = QSettings('NextGIS', 'NextGISConnect')
        if len(settings.allKeys()) == 0:
            return

        mapping = {
            'ui/autoOpenWebMapByDefault': 'openWebMapAfterCreation',
            'ui/autoAddWFSByDefault': 'addWfsLayerAfterServiceCreation',
            'debugMode': 'debugEnabled',
        }
        self.__settings.beginGroup(self.__plugin_group)
        for old_key, new_key in mapping.items():
            if (value := settings.value(old_key)) is None:
                continue
            self.__settings.setValue(new_key, value)
        self.__settings.endGroup()

        self.__settings.sync()

        settings.clear()
