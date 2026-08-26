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

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QSettings

from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.shared.constants import PLUGIN_SETTINGS_GROUP


def test_migration_removes_obsolete_uploading_settings(
    reset_qgis_settings: None,
) -> None:
    del reset_qgis_settings

    _reset_settings_migration()

    qgs_settings = QgsSettings()
    old_settings = QSettings("NextGIS", "NextGIS WEB API")
    old_settings.clear()

    obsolete_qgs_keys = [
        "synchronization/period",
        "uploading/rasterAsCog",
        "uploading/vectorWithVersioning",
        "uploading/renameForbiddenFields",
    ]
    obsolete_old_keys = [
        "upload_cog_rasters",
        "upload_vector_with_versioning",
    ]

    for key in obsolete_qgs_keys:
        qgs_settings.setValue(f"{PLUGIN_SETTINGS_GROUP}/{key}", True)

    for key in obsolete_old_keys:
        old_settings.setValue(key, True)

    try:
        NgConnectSettings()

        for key in obsolete_qgs_keys:
            assert qgs_settings.value(f"{PLUGIN_SETTINGS_GROUP}/{key}") is None

        for key in obsolete_old_keys:
            assert old_settings.value(key) is None
    finally:
        old_settings.clear()
        _reset_settings_migration()


def test_resource_creation_metadata_setting_defaults_to_enabled(
    reset_qgis_settings: None,
) -> None:
    del reset_qgis_settings

    _reset_settings_migration()

    assert NgConnectSettings().add_resource_creation_metadata is True


def test_resource_creation_metadata_setting_can_be_disabled(
    reset_qgis_settings: None,
) -> None:
    del reset_qgis_settings

    _reset_settings_migration()

    settings = NgConnectSettings()
    settings.add_resource_creation_metadata = False

    assert NgConnectSettings().add_resource_creation_metadata is False


def test_project_webmap_creation_setting_can_be_disabled(
    reset_qgis_settings: None,
) -> None:
    del reset_qgis_settings

    _reset_settings_migration()

    settings = NgConnectSettings()
    settings.create_webmap_when_uploading_project = False

    assert NgConnectSettings().create_webmap_when_uploading_project is False


def _reset_settings_migration() -> None:
    NgConnectSettings._NgConnectSettings__is_migrated = False
