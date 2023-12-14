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

import os
from typing import Optional

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QSettings, QStandardPaths


class NgConnectSettings:
    """Convenience class for working with plugin settings"""

    __settings: QgsSettings

    def __init__(self) -> None:
        self.__settings = QgsSettings()
        self.__migrate()

    @property
    def supported_ngw_version(self) -> str:
        return "4.7.0"

    @property
    def open_web_map_after_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "openWebMapAfterCreation", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @open_web_map_after_creation.setter
    def open_web_map_after_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("openWebMapAfterCreation", value)
        self.__settings.endGroup()

    @property
    def add_layer_after_service_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        # TODO: remove "wfs" from key
        result = self.__settings.value(
            "addWfsLayerAfterServiceCreation", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @add_layer_after_service_creation.setter
    def add_layer_after_service_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("addWfsLayerAfterServiceCreation", value)
        self.__settings.endGroup()

    @property
    def is_debug_enabled(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "debugEnabled", defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @is_debug_enabled.setter
    def is_debug_enabled(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("debugEnabled", value)
        self.__settings.endGroup()

    @property
    def cache_directory(self) -> str:
        return self.__settings.value(
            self.__plugin_group + '/cache/directory',
            defaultValue=self.cache_directory_default,
            type=str
        )

    @property
    def cache_directory_default(self) -> str:
        application_cache_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        return application_cache_path + '/NGConnect'

    @cache_directory.setter
    def cache_directory(self, value: Optional[str]) -> None:
        self.__settings.setValue(
            self.__plugin_group + '/cache/directory', value
        )

    @property
    def cache_duration(self) -> int:
        """Keeping cache duration in days"""
        return self.__settings.value(
            self.__plugin_group + '/cache/duration',
            defaultValue=30,
            type=int
        )

    @cache_duration.setter
    def cache_duration(self, value: int) -> None:
        self.__settings.setValue(
            self.__plugin_group + '/cache/duration', value
        )

    @property
    def cache_max_size(self) -> int:
        """Cache max size in MB"""
        return self.__settings.value(
            self.__plugin_group + '/cache/size',
            defaultValue=12 * 1024,  # 12 GB
            type=int
        )

    @cache_max_size.setter
    def cache_max_size(self, value: int) -> None:
        self.__settings.setValue(
            self.__plugin_group + '/cache/size', value
        )

    @property
    def __plugin_group(self) -> str:
        return "NextGIS/Connect"

    def __migrate(self) -> None:
        self.__migrate_from_qsettings()
        self.__migrate_to_more_beautiful_path()

        self.__settings.sync()

    def __migrate_from_qsettings(self):
        """Migrate from QSettings to QgsSettings"""
        settings = QSettings("NextGIS", "NextGISConnect")
        if len(settings.allKeys()) == 0:
            return

        mapping = {
            "ui/autoOpenWebMapByDefault": "openWebMapAfterCreation",
            "ui/autoAddWFSByDefault": "addWfsLayerAfterServiceCreation",
            "debugMode": "debugEnabled",
        }
        self.__settings.beginGroup(self.__plugin_group)
        for old_key, new_key in mapping.items():
            value = settings.value(old_key)
            if value is None:
                continue
            self.__settings.setValue(new_key, value)
        self.__settings.endGroup()

        settings.clear()

    def __migrate_to_more_beautiful_path(self):
        """Rename NextGIS/NGConnect to NextGIS/Connect"""
        self.__settings.beginGroup("NextGIS/NGConnect")
        keys = self.__settings.allKeys()
        if len(keys) == 0:
            self.__settings.endGroup()
            return

        values = {key: self.__settings.value(key) for key in keys}
        self.__settings.endGroup()

        self.__settings.beginGroup(self.__plugin_group)
        for key, value in values.items():
            self.__settings.setValue(key, value)
        self.__settings.endGroup()

        self.__settings.beginGroup("NextGIS/NGConnect")
        for key in keys:
            self.__settings.remove(key)
        self.__settings.endGroup()
