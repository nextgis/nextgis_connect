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

from datetime import timedelta
from typing import ClassVar, Optional

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QSettings, QStandardPaths

from nextgis_connect.search.search_settings import SearchSettings


class NgConnectSettings:
    """Convenience class for working with plugin settings"""

    __settings: QgsSettings
    __search_settings: Optional[SearchSettings]
    __is_migrated: ClassVar[bool] = False

    def __init__(self) -> None:
        self.__settings = QgsSettings()
        self.__search_settings = None
        self.__migrate()

    @property
    def supported_ngw_version(self) -> str:
        return "5.0.0"

    @property
    def supported_container_version(self) -> str:
        return "2.0.0"

    @property
    def search(self) -> SearchSettings:
        if self.__search_settings is None:
            self.__search_settings = SearchSettings(self.__settings)
        return self.__search_settings

    @property
    def fix_incorrect_geometries(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/fixIncorrectGeometries", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @fix_incorrect_geometries.setter
    def fix_incorrect_geometries(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("uploading/fixIncorrectGeometries", value)
        self.__settings.endGroup()

    @property
    def upload_raster_as_cog(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/rasterAsCog", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @upload_raster_as_cog.setter
    def upload_raster_as_cog(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("uploading/rasterAsCog", value)
        self.__settings.endGroup()

    @property
    def upload_vector_with_versioning(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/vectorWithVersioning", defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @upload_vector_with_versioning.setter
    def upload_vector_with_versioning(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("uploading/vectorWithVersioning", value)
        self.__settings.endGroup()

    @property
    def open_web_map_after_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "resources/openWebMapAfterCreation", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @open_web_map_after_creation.setter
    def open_web_map_after_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("resources/openWebMapAfterCreation", value)
        self.__settings.endGroup()

    @property
    def add_layer_after_service_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "resources/addLayerAfterServiceCreation",
            defaultValue=True,
            type=bool,
        )
        self.__settings.endGroup()
        return result

    @add_layer_after_service_creation.setter
    def add_layer_after_service_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue(
            "resources/addLayerAfterServiceCreation", value
        )
        self.__settings.endGroup()

    @property
    def is_developer_mode(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "other/developerMode", defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @is_developer_mode.setter
    def is_developer_mode(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("other/developerMode", value)
        self.__settings.endGroup()

    @property
    def is_debug_enabled(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "other/debugEnabled", defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @is_debug_enabled.setter
    def is_debug_enabled(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("other/debugEnabled", value)
        self.__settings.endGroup()

    @property
    def is_network_debug_enabled(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "other/debugNetworkEnabled", defaultValue=False, type=bool
        )
        self.__settings.endGroup()
        return result

    @is_network_debug_enabled.setter
    def is_network_debug_enabled(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("other/debugNetworkEnabled", value)
        self.__settings.endGroup()

    @property
    def cache_directory(self) -> str:
        return self.__settings.value(
            self.__plugin_group + "/cache/directory",
            defaultValue=self.cache_directory_default,
            type=str,
        )

    @property
    def cache_directory_default(self) -> str:
        application_cache_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        return application_cache_path + "/NGConnect"

    @cache_directory.setter
    def cache_directory(self, value: Optional[str]) -> None:
        self.__settings.setValue(
            self.__plugin_group + "/cache/directory", value
        )

    @property
    def cache_duration(self) -> int:
        """Keeping cache duration in days"""
        return self.__settings.value(
            self.__plugin_group + "/cache/duration", defaultValue=30, type=int
        )

    @cache_duration.setter
    def cache_duration(self, value: int) -> None:
        self.__settings.setValue(
            self.__plugin_group + "/cache/duration", value
        )

    @property
    def cache_max_size(self) -> int:
        """Cache max size in MB"""
        return self.__settings.value(
            self.__plugin_group + "/cache/size",
            defaultValue=12 * 1024,  # 12 GB
            type=int,
        )

    @cache_max_size.setter
    def cache_max_size(self, value: int) -> None:
        self.__settings.setValue(self.__plugin_group + "/cache/size", value)

    @property
    def layer_check_period(self) -> int:
        return int(timedelta(seconds=15) / timedelta(milliseconds=1))

    @property
    def synchronizatin_period(self) -> timedelta:
        value = self.__settings.value(
            self.__plugin_group + "/synchronization/period",
            defaultValue=60,
            type=int,
        )
        return timedelta(seconds=value)

    @synchronizatin_period.setter
    def synchronizatin_period(self, value: timedelta) -> None:
        self.__settings.setValue(
            self.__plugin_group + "/synchronization/period",
            value.total_seconds(),
        )

    @property
    def did_last_launch_fail(self) -> bool:
        value = self.__settings.value(
            self.__plugin_group + "/other/did_last_launch_fail",
            defaultValue=False,
            type=bool,
        )
        return value

    @did_last_launch_fail.setter
    def did_last_launch_fail(self, value: bool) -> None:
        self.__settings.setValue(
            self.__plugin_group + "/other/did_last_launch_fail", value
        )

    @property
    def __plugin_group(self) -> str:
        return "NextGIS/Connect"

    def __migrate(self) -> None:
        if self.__is_migrated:
            return

        self.__migrate_from_qsettings()
        self.__migrate_to_more_beautiful_path()
        self.__migrate_ngw_api_settings()
        self.__migrate_keys_names()

        self.__remove_old_settings()

        self.__settings.sync()

        self.__class__.__is_migrated = True

    def __migrate_from_qsettings(self):
        """Migrate from QSettings to QgsSettings"""
        settings = QSettings("NextGIS", "NextGISConnect")
        if len(settings.allKeys()) == 0:
            return

        mapping = {
            "ui/autoOpenWebMapByDefault": "resources/openWebMapAfterCreation",
            "ui/autoAddWFSByDefault": "resources/addLayerAfterServiceCreation",
            "debugMode": "other/debugEnabled",
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

    def __migrate_keys_names(self) -> None:
        mapping = {
            "addWfsLayerAfterServiceCreation": "resources/addLayerAfterServiceCreation",
            "openWebMapAfterCreation": "resources/openWebMapAfterCreation",
            "debugEnabled": "other/debugEnabled",
        }
        if any(
            self.__settings.value(key) is not None for key in mapping.values()
        ):
            return

        self.__settings.beginGroup(self.__plugin_group)
        for old_name, new_name in mapping.items():
            value = self.__settings.value(old_name)
            if value is None:
                continue
            self.__settings.setValue(new_name, value)
            self.__settings.remove(old_name)
        self.__settings.endGroup()

    def __migrate_ngw_api_settings(self) -> None:
        mapping = {
            "sanitize_rename_fields": "uploading/renameForbiddenFields",
            "sanitize_fix_geometry": "uploading/fixIncorrectGeometries",
            "upload_cog_rasters": "uploading/rasterAsCog",
        }

        if any(
            self.__settings.value(key) is not None for key in mapping.values()
        ):
            return

        settings = QSettings("NextGIS", "NextGIS WEB API")
        self.__settings.beginGroup(self.__plugin_group)
        for old_key, new_key in mapping.items():
            value = settings.value(old_key)
            if value is None:
                continue
            self.__settings.setValue(new_key, value)
            settings.remove(old_key)
        self.__settings.endGroup()

    def __remove_old_settings(self) -> None:
        self.__settings.value(
            f"{self.__plugin_group}/uploading/renameForbiddenFields"
        )
