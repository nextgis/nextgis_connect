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

from typing import Set

from qgis.core import QgsSettings
from qgis.gui import QgsMapToolIdentify
from qgis.PyQt.QtCore import Qt

from nextgis_connect.legacy.detached_editing.identification.types import (
    AttachmentsSortMode,
    IdentificationTab,
)
from nextgis_connect.shared.constants import PLUGIN_SETTINGS_GROUP


class IdentificationSettings:
    """
    Manage persistent settings for the identification tool.
    """

    FEATURE_GROUP = f"{PLUGIN_SETTINGS_GROUP}/identification"
    KEY_IDENTIFY_MODE = "Map/identifyMode"
    KEY_LAST_USED_TAB = f"{FEATURE_GROUP}/lastUsedTab"
    KEY_AUTO_PAN = f"{FEATURE_GROUP}/autoPanToFeature"
    KEY_AUTO_ZOOM = f"{FEATURE_GROUP}/autoZoomToFeature"
    KEY_ATTACHMENTS_SORT_MODE = f"{FEATURE_GROUP}/attachmentsSortMode"
    KEY_ATTACHMENTS_SORT_ORDER = f"{FEATURE_GROUP}/attachmentsSortOrder"
    KEY_IMAGE_PREVIEW_MODE = f"{FEATURE_GROUP}/imagePreviewMode"

    def __init__(self) -> None:
        self.__settings = QgsSettings()

    @property
    def mode(self) -> QgsMapToolIdentify.IdentifyMode:
        raw_value: str = self.__settings.value(
            self.KEY_IDENTIFY_MODE, "ActiveLayer"
        )
        return getattr(QgsMapToolIdentify.IdentifyMode, raw_value)

    @mode.setter
    def mode(self, value: QgsMapToolIdentify.IdentifyMode) -> None:
        mapping = {
            QgsMapToolIdentify.IdentifyMode.DefaultQgsSetting: "DefaultQgsSetting",
            QgsMapToolIdentify.IdentifyMode.ActiveLayer: "ActiveLayer",
            QgsMapToolIdentify.IdentifyMode.TopDownStopAtFirst: "TopDownStopAtFirst",
            QgsMapToolIdentify.IdentifyMode.TopDownAll: "TopDownAll",
            QgsMapToolIdentify.IdentifyMode.LayerSelection: "LayerSelection",
        }
        self.__settings.setValue(
            self.KEY_IDENTIFY_MODE, mapping.get(value, "ActiveLayer")
        )

    @property
    def last_used_tab(self) -> IdentificationTab:
        str_value = self.__settings.value(
            self.KEY_LAST_USED_TAB, IdentificationTab.ATTRIBUTES.name
        )
        return IdentificationTab[str_value]

    @last_used_tab.setter
    def last_used_tab(self, value: IdentificationTab) -> None:
        self.__settings.setValue(self.KEY_LAST_USED_TAB, value.name)

    @property
    def auto_pan(self) -> bool:
        return self.__settings.value(self.KEY_AUTO_PAN, False, type=bool)

    @auto_pan.setter
    def auto_pan(self, value: bool) -> None:
        self.__settings.setValue(self.KEY_AUTO_PAN, value)

    @property
    def auto_zoom(self) -> bool:
        return self.__settings.value(self.KEY_AUTO_ZOOM, False, type=bool)

    @auto_zoom.setter
    def auto_zoom(self, value: bool) -> None:
        self.__settings.setValue(self.KEY_AUTO_ZOOM, value)

    @property
    def zoom_map_scale(self) -> float:
        return 50000

    @property
    def zoom_geometry_scale_factor(self) -> float:
        return 1.2

    @property
    def attachment_thumbnail_size(self) -> int:
        return 48

    @property
    def attachment_thumbnail_mime_types(self) -> Set[str]:
        return {
            "image/bmp",
            "image/gif",
            "image/jpg",
            "image/jpeg",
            "image/png",
            "image/svg+xml",
            "image/tiff",
            "image/webp",
        }

    @property
    def attachments_sort_mode(self) -> AttachmentsSortMode:
        raw_value = self.__settings.value(
            self.KEY_ATTACHMENTS_SORT_MODE, AttachmentsSortMode.BY_NAME.name
        )
        return AttachmentsSortMode[raw_value]

    @attachments_sort_mode.setter
    def attachments_sort_mode(self, value: AttachmentsSortMode) -> None:
        self.__settings.setValue(self.KEY_ATTACHMENTS_SORT_MODE, value.name)

    @property
    def attachments_sort_order(self) -> Qt.SortOrder:
        return self.__settings.value(
            self.KEY_ATTACHMENTS_SORT_ORDER,
            Qt.SortOrder.AscendingOrder,
            type=Qt.SortOrder,
        )

    @attachments_sort_order.setter
    def attachments_sort_order(self, value: Qt.SortOrder) -> None:
        self.__settings.setValue(self.KEY_ATTACHMENTS_SORT_ORDER, value)

    @property
    def image_preview_mode(self) -> str:
        mode = self.__settings.value(
            self.KEY_IMAGE_PREVIEW_MODE,
            "panorama",
            type=str,
        )
        return mode if mode in ("flat", "panorama") else "panorama"

    @image_preview_mode.setter
    def image_preview_mode(self, value: str) -> None:
        if value not in ("flat", "panorama"):
            raise ValueError(f"Unsupported image preview mode: {value}")
        self.__settings.setValue(self.KEY_IMAGE_PREVIEW_MODE, value)
