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

from enum import Enum, auto
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Any, Optional, Tuple

import qgis.utils
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsSettings,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QLocale
from qgis.PyQt.QtWidgets import (
    QAction,
    QMenu,
)

from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.qgis.compat import QGIS_3_30
from nextgis_connect.shared.constants import PACKAGE_NAME
from nextgis_connect.shell.presentation.about.about_dialog import AboutDialog


class SupportStatus(Enum):
    """Represent NextGIS Web support status.

    Distinguish whether the connected server is older, newer, or within
    the version range accepted by the current plugin settings.
    """

    OLD_NGW = auto()
    OLD_CONNECT = auto()
    SUPPORTED = auto()


def _iface() -> "QgisInterface":
    iface = qgis.utils.iface
    assert isinstance(iface, QgisInterface)
    return iface


def open_plugin_help():
    """Open the plugin help dialog."""
    package_path = Path(__file__).resolve().parents[2]
    components_path = package_path / "assets" / "components" / "index.json"
    dialog = AboutDialog(PACKAGE_NAME, components_path=components_path)
    dialog.exec()


def is_version_supported(current_version_string: str) -> SupportStatus:
    """Return support status for a NextGIS Web version.

    :param current_version_string: NextGIS Web version string.
    :return: Version support status.
    """

    def version_to_tuple(version: str) -> Tuple[int, int]:
        minor, major = islice(map(int, version.split(".")), 2)
        return minor, major

    def version_shift(version: Tuple[int, int], shift: int) -> Tuple[int, int]:
        version_number = version[0] * 10 + version[1]
        shifted_version = version_number + shift
        return shifted_version // 10, shifted_version % 10

    current_version = version_to_tuple(current_version_string)

    settings = NgConnectSettings()
    if settings.is_developer_mode:
        return SupportStatus.SUPPORTED

    supported_version_string = settings.supported_ngw_version
    supported_version = version_to_tuple(supported_version_string)

    oldest_version = version_shift(supported_version, -2)
    newest_version = version_shift(supported_version, 1)

    if current_version < oldest_version:
        return SupportStatus.OLD_NGW

    if current_version > newest_version:
        return SupportStatus.OLD_CONNECT

    return SupportStatus.SUPPORTED


def get_project_import_export_menu() -> Optional[QMenu]:
    """Return the application Project Import/Export submenu.

    :return: Import/Export menu or ``None``.
    """
    iface = _iface()
    if Qgis.versionInt() >= QGIS_3_30:
        return iface.projectImportExportMenu()

    project_menu = iface.projectMenu()
    matches = [
        m
        for m in project_menu.children()
        if m.objectName() == "menuImport_Export"
    ]
    if matches:
        return matches[0]

    return None


def add_project_export_action(project_export_action: QAction) -> None:
    """Add a project export action to the Project menu.

    :param project_export_action: Action to add to the export menu.
    """
    iface = _iface()
    if Qgis.versionInt() >= QGIS_3_30:
        iface.addProjectExportAction(project_export_action)
    else:
        import_export_menu = get_project_import_export_menu()
        if import_export_menu:
            export_separators = [
                action
                for action in import_export_menu.actions()
                if action.isSeparator()
            ]
            if export_separators:
                import_export_menu.insertAction(
                    export_separators[0],
                    project_export_action,
                )
            else:
                import_export_menu.addAction(project_export_action)


@lru_cache(maxsize=1)
def locale() -> str:
    """Return the active two-letter QGIS locale.

    :return: Lowercase locale code.
    """
    override_locale = QgsSettings().value(
        "locale/overrideFlag", defaultValue=False, type=bool
    )
    if not override_locale:
        locale_full_name = QLocale.system().name()
    else:
        locale_full_name = QgsSettings().value("locale/userLocale", "")
    locale = locale_full_name[0:2].lower()

    return locale if locale.lower() != "c" else "en"


@lru_cache(maxsize=1)
def is_russian_speaking() -> bool:
    """Return whether the active locale uses Russian-language services.

    :return: ``True`` for Russian-speaking locales.
    """
    return locale() in ["be", "kk", "ky", "ru", "uk"]


@lru_cache(maxsize=1)
def nextgis_domain(subdomain: Optional[str] = None) -> str:
    """Return a localized NextGIS domain URL.

    :param subdomain: Optional subdomain prefix.
    :return: Localized NextGIS domain URL.
    """
    speaks_russian = is_russian_speaking()
    if subdomain is None:
        subdomain = ""
    elif not subdomain.endswith("."):
        subdomain += "."
    return f"https://{subdomain}nextgis.{'ru' if speaks_russian else 'com'}"


def utm_tags(utm_medium: str, *, utm_campaign: str = "constant") -> str:
    """Return plugin UTM query parameters.

    :param utm_medium: UTM medium value.
    :param utm_campaign: UTM campaign value.
    :return: Encoded UTM query string.
    """
    utm = (
        f"utm_source=qgis_plugin&utm_medium={utm_medium}"
        f"&utm_campaign={utm_campaign}&utm_term=nextgis_connect"
        f"&utm_content={locale()}"
    )
    return utm


def wrap_sql_value(value: Any) -> str:
    """Convert a Python value to a SQL literal.

    :param value: Value to convert.
    :return: SQL-compatible string representation.
    """
    if isinstance(value, str):
        value = value.replace("'", r"''")
        return f"'{value}'"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "NULL"
    return str(value)


def wrap_sql_table_name(value: Any) -> str:
    """Wrap a value as a SQL table name.

    :param value: Table name to wrap.
    :return: Double-quoted SQL table name.
    """
    value = value.replace('"', r'""')
    return f'"{value}"'


def human_readable_size(size_in_kb: float) -> str:
    """Convert a size in KiB to localized human-readable text.

    :param size_in_kb: Size in KiB.
    :return: Human-readable size string.
    """
    units = [
        QgsApplication.translate("SizeUnits", "KiB"),
        QgsApplication.translate("SizeUnits", "MiB"),
        QgsApplication.translate("SizeUnits", "GiB"),
        QgsApplication.translate("SizeUnits", "TiB"),
    ]
    size = size_in_kb
    unit_index = 0
    while size > 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    precision = 2 if size < 10 else 1
    return f"{size:.{precision}f} {units[unit_index]}"
