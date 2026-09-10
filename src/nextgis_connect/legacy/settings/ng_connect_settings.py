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

import json
from pathlib import Path
from typing import ClassVar, Optional

import qgis.utils
from qgis.core import QgsSettings
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QSettings, QStandardPaths

from nextgis_connect.legacy.search.search_settings import SearchSettings
from nextgis_connect.shared.constants import PLUGIN_SETTINGS_GROUP


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
        return "5.6.0"

    @property
    def supported_container_version(self) -> str:
        return "3.0.0"

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
    def add_resource_creation_metadata(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/addResourceCreationMetadata",
            defaultValue=True,
            type=bool,
        )
        self.__settings.endGroup()
        return result

    @add_resource_creation_metadata.setter
    def add_resource_creation_metadata(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue(
            "uploading/addResourceCreationMetadata", value
        )
        self.__settings.endGroup()

    @property
    def embed_svg_images_in_qml(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/embedSvgImagesInQml",
            defaultValue=True,
            type=bool,
        )
        self.__settings.endGroup()
        return result

    @embed_svg_images_in_qml.setter
    def embed_svg_images_in_qml(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("uploading/embedSvgImagesInQml", value)
        self.__settings.endGroup()

    @property
    def create_webmap_when_uploading_project(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "uploading/createWebMapForProject", defaultValue=True, type=bool
        )
        self.__settings.endGroup()
        return result

    @create_webmap_when_uploading_project.setter
    def create_webmap_when_uploading_project(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue("uploading/createWebMapForProject", value)
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
    def add_vector_layer_after_creation(self) -> bool:
        self.__settings.beginGroup(self.__plugin_group)
        result = self.__settings.value(
            "resources/addVectorLayerAfterCreation",
            defaultValue=True,
            type=bool,
        )
        self.__settings.endGroup()
        return result

    @add_vector_layer_after_creation.setter
    def add_vector_layer_after_creation(self, value: bool) -> None:
        self.__settings.beginGroup(self.__plugin_group)
        self.__settings.setValue(
            "resources/addVectorLayerAfterCreation", value
        )
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
            defaultValue=self.user_profile_cache_directory,
            type=str,
        )

    @cache_directory.setter
    def cache_directory(self, value: Optional[str]) -> None:
        self.__settings.setValue(
            self.__plugin_group + "/cache/directory", value
        )

    @property
    def old_plugin_cache_directory(self) -> str:
        application_cache_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        return application_cache_path + "/NGConnect"

    @property
    def user_profile_cache_directory(self) -> str:
        assert isinstance(qgis.utils.iface, QgisInterface)
        active_profile = qgis.utils.iface.userProfileManager().userProfile()
        assert active_profile is not None
        user_folder = Path(active_profile.folder())
        return str(user_folder / "NGConnect")

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
        return 15 * 1000

    @property
    def notify_when_deleting_features_with_attachments(self) -> bool:
        value = self.__settings.value(
            self.__plugin_group
            + "/editing/notifyWhenDeletingFeaturesWithAttachments",
            defaultValue=True,
            type=bool,
        )
        return value

    @notify_when_deleting_features_with_attachments.setter
    def notify_when_deleting_features_with_attachments(
        self, value: bool
    ) -> None:
        self.__settings.setValue(
            self.__plugin_group
            + "/editing/notifyWhenDeletingFeaturesWithAttachments",
            value,
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

    def dismiss_promo(self, promo_id: str) -> None:
        dismissed_promos = self.__settings.value(
            f"{self.__plugin_group}/other/dismissedPromos",
            defaultValue="[]",
            type=str,
        )
        dismissed_promos = json.loads(dismissed_promos)

        dismissed_promos.append(promo_id)
        dismissed_promos = set(dismissed_promos)

        self.__settings.setValue(
            f"{self.__plugin_group}/other/dismissedPromos",
            json.dumps(list(dismissed_promos)),
        )

    def is_promo_dismissed(self, promo_id: str) -> bool:
        dismissed_promos = self.__settings.value(
            f"{self.__plugin_group}/other/dismissedPromos",
            defaultValue="[]",
            type=str,
        )
        dismissed_promos = json.loads(dismissed_promos)
        return promo_id in dismissed_promos

    @property
    def __plugin_group(self) -> str:
        return PLUGIN_SETTINGS_GROUP

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
        obsolete_keys = (
            "synchronization/period",
            "uploading/rasterAsCog",
            "uploading/vectorWithVersioning",
            "uploading/renameForbiddenFields",
        )
        for key in obsolete_keys:
            self.__settings.remove(f"{self.__plugin_group}/{key}")

        old_settings = QSettings("NextGIS", "NextGIS WEB API")
        old_settings.remove("upload_cog_rasters")
        old_settings.remove("upload_vector_with_versioning")
