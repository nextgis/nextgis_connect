import os
from typing import ClassVar, List, Optional, cast

from qgis.core import Qgis, QgsApplication, QgsMessageLogNotifyBlocker
from qgis.gui import (
    QgsMessageBar,
    QgsOptionsPageWidget,
    QgsOptionsWidgetFactory,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect.logging import logger, update_level
from nextgis_connect.ng_connect_dock import NgConnectDock
from nextgis_connect.ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings
from nextgis_connect.ngw_connection.ngw_connection import NgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.ngw_connection.ngw_connections_widget import (
    NgwConnectionsWidget,
)
from nextgis_connect.settings import NgConnectCacheManager, NgConnectSettings
from nextgis_connect.widgets.labeled_slider import LabeledSlider


class NgConnectOptionsPageWidget(QgsOptionsPageWidget):
    """NextGIS Connect settings page"""

    __widget: QWidget
    __current_connection: Optional[NgwConnection]
    __connections: List[NgwConnection]
    __is_accepted: bool
    __is_cancelled: bool

    CACHE_SIZE_VALUES: ClassVar[List[int]] = [
        8 * 1024,
        12 * 1024,
        16 * 1024,
        24 * 1024,
        32 * 1024,
        64 * 1024,
        -1,
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        plugin_path = os.path.dirname(__file__)
        widget: Optional[QWidget] = None
        try:
            widget = uic.loadUi(
                os.path.join(plugin_path, "settings_dialog_base.ui")
            )  # type: ignore
        except FileNotFoundError as error:
            message = self.tr("Can't load settings UI")
            logger.exception(message)
            raise RuntimeError(message) from error
        if widget is None:
            message = self.tr("Errors in settings UI")
            logger.error(message)
            raise RuntimeError(message)

        self.__widget = widget
        self.__widget.setParent(self)

        self.connections_widget = NgwConnectionsWidget(self.__widget)
        self.__widget.connectionsGroupBox.layout().addWidget(
            self.connections_widget
        )

        unit = self.tr("GiB")
        self.__widget.cacheSizeSlider = LabeledSlider(
            [f"{number} {unit}" for number in [8, 12, 16, 24, 32, 64]] + ["∞"],
            self.__widget,
        )
        self.__widget.maxSizeLayout.addWidget(self.__widget.cacheSizeSlider)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)  # type: ignore
        self.setLayout(layout)
        layout.addWidget(self.__widget)

        self.__init_settings()

    def apply(self) -> None:
        self.__is_accepted = True

        settings = NgConnectSettings()

        # Connections settings
        self.__save_current_connection()

        # Cache settings
        cache_manager = NgConnectCacheManager()
        cache_directory = self.__widget.cacheDirectoryLineEdit.text()
        cache_manager.cache_directory = (
            cache_directory if len(cache_directory) > 0 else None
        )
        cache_duration_combobox = cast(
            QComboBox, self.__widget.autoRemoveCacheComboBox
        )
        cache_manager.cache_duration = cache_duration_combobox.currentData()
        cache_size_index = self.__widget.cacheSizeSlider.value()
        cache_manager.cache_max_size = self.CACHE_SIZE_VALUES[cache_size_index]

        # Sanitize settings
        NgwPluginSettings.set_sanitize_rename_fields(
            self.__widget.renameFieldsCheckBox.isChecked()
        )
        NgwPluginSettings.set_sanitize_fix_geometry(
            self.__widget.fixGeometryCheckBox.isChecked()
        )

        # Creation settings
        settings.open_web_map_after_creation = (
            self.__widget.openWebMapAfterCreationCheckBox.isChecked()
        )
        settings.add_layer_after_service_creation = (
            self.__widget.addWfsLayerAfterServiceCreationCheckBox.isChecked()
        )

        # Other settings
        NgwPluginSettings.set_upload_cog_rasters(
            self.__widget.cogCheckBox.isChecked()
        )

        old_debug_enabled = settings.is_debug_enabled
        new_debug_enabled = self.__widget.debugEnabledCheckBox.isChecked()
        settings.is_debug_enabled = new_debug_enabled
        if old_debug_enabled != new_debug_enabled:
            debug_state = "enabled" if new_debug_enabled else "disabled"
            update_level()
            logger.info(f"Debug messages are now {debug_state}")

    def __del__(self):
        # Workaround
        if not self.__is_accepted and not self.__is_cancelled:
            self.cancel()

    def cancel(self) -> None:
        self.__is_cancelled = True
        connections_manager = NgwConnectionsManager()
        current_connections = connections_manager.connections()

        # Remove new
        delta = set(current_connections) - set(self.__connections)
        for connection in delta:
            connections_manager.remove(connection.id)

        # Restore old
        for connection in self.__connections:
            connections_manager.save(connection)

    def __init_settings(self) -> None:
        settings = NgConnectSettings()
        self.__is_accepted = False
        self.__is_cancelled = False
        self.__init_connections(settings)
        self.__init_cache_settings(settings)
        self.__init_sanitize_settings(settings)
        self.__init_creation_settings(settings)
        self.__init_other_settings(settings)

    def __init_connections(self, settings: NgConnectSettings) -> None:
        connections_manager = NgwConnectionsManager()
        self.__current_connection = connections_manager.current_connection
        self.__connections = connections_manager.connections()

    def __init_sanitize_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.renameFieldsCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_rename_fields()
        )
        self.__widget.fixGeometryCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_fix_geometry()
        )
        self.__widget.fixGeometryCheckBox.hide()  # Rely on NGW

    def __init_creation_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.openWebMapAfterCreationCheckBox.setChecked(
            settings.open_web_map_after_creation
        )
        self.__widget.addWfsLayerAfterServiceCreationCheckBox.setChecked(
            settings.add_layer_after_service_creation
        )

    def __init_cache_settings(self, settings: NgConnectSettings) -> None:
        cache_manager = NgConnectCacheManager()
        is_cache_directory_default = (
            cache_manager.cache_directory
            == cache_manager.cache_directory_default
        )

        # Cache directory lineedit
        self.__widget.cacheDirectoryLineEdit.setPlaceholderText(
            cache_manager.cache_directory_default
        )
        if not is_cache_directory_default:
            self.__widget.cacheDirectoryLineEdit.setText(
                cache_manager.cache_directory
            )
        self.__widget.cacheDirectoryLineEdit.textChanged.connect(
            self.__update_reset_cache_button
        )

        # Choose cache directory button
        self.__widget.cacheDirectoryButton.setIcon(
            QgsApplication.getThemeIcon("mActionFileOpen.svg")
        )
        self.__widget.cacheDirectoryButton.clicked.connect(
            self.__choose_cache_directory
        )

        # Cache directory reset button
        self.__widget.resetCacheDirectoryButton.setIcon(
            QgsApplication.getThemeIcon("mActionUndo.svg")
        )
        self.__widget.resetCacheDirectoryButton.clicked.connect(
            self.__reset_cache_directory
        )
        self.__widget.resetCacheDirectoryButton.setDisabled(
            is_cache_directory_default
        )

        # Cache duration combobox
        cache_duration_combobox = cast(
            QComboBox, self.__widget.autoRemoveCacheComboBox
        )
        cache_duration_combobox.setItemData(0, 1)
        cache_duration_combobox.setItemData(1, 7)
        cache_duration_combobox.setItemData(2, 30)
        cache_duration_combobox.setItemData(3, -1)
        cache_duration_combobox.setCurrentIndex(
            cache_duration_combobox.findData(cache_manager.cache_duration)
        )

        # Cache size button
        self.__widget.cacheSizeSlider.setValue(
            self.CACHE_SIZE_VALUES.index(cache_manager.cache_max_size)
        )

        # Clear cache button
        self.__widget.clearCacheButton.setIcon(
            QgsApplication.getThemeIcon("mActionDeleteSelected.svg")
        )
        self.__widget.clearCacheButton.clicked.connect(self.__clear_cache)

        if (cache_size := cache_manager.cache_size) == 0:
            self.__widget.clearCacheButton.setText(self.tr("Clear Cache"))
            self.__widget.clearCacheButton.setToolTip(
                self.tr("Cache is empty")
            )
            self.__widget.clearCacheButton.setEnabled(False)
        else:
            self.__widget.clearCacheButton.setText(
                self.tr("Clear Cache") + f"  ({self.format_size(cache_size)})"
            )
            self.__widget.clearCacheButton.setEnabled(True)

    def __init_other_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.cogCheckBox.setChecked(
            NgwPluginSettings.get_upload_cog_rasters()
        )
        self.__widget.debugEnabledCheckBox.setChecked(
            settings.is_debug_enabled
        )

    def __save_current_connection(self):
        connections_manager = NgwConnectionsManager()
        old_connection = self.__current_connection
        new_connection_id = self.connections_widget.connection_id()

        need_reinint = False

        if (
            old_connection is not None
            and new_connection_id is None
            or old_connection is None
            and new_connection_id is not None
        ):
            need_reinint = True
            connections_manager.current_connection_id = new_connection_id
        elif old_connection is not None and new_connection_id is not None:
            new_connection = connections_manager.connection(new_connection_id)
            if old_connection != new_connection:
                need_reinint = True
                connections_manager.current_connection_id = new_connection_id

        if need_reinint:
            dock = iface.mainWindow().findChild(NgConnectDock, "NGConnectDock")
            dock.reinit_tree(force=True)

    def __choose_cache_directory(self) -> None:
        cache_manager = NgConnectCacheManager()
        directory = QFileDialog.getExistingDirectory(
            self,
            caption=self.tr(
                "Choose a directory to store NextGIS Connect cache"
            ),
            directory=cache_manager.cache_directory,
        )
        if not directory:
            return

        self.__widget.cacheDirectoryLineEdit.setText(directory)

    def __update_reset_cache_button(self, text: str) -> None:
        self.__widget.resetCacheDirectoryButton.setEnabled(len(text) > 0)

    def __reset_cache_directory(self) -> None:
        self.__widget.cacheDirectoryLineEdit.setText("")

    def __clear_cache(self) -> None:
        log_blocker = QgsMessageLogNotifyBlocker()

        cache_manager = NgConnectCacheManager()
        cache_manager.clear_cache()
        message = self.tr("Cache has been successfully cleared")
        cast(QgsMessageBar, self.__widget.messageBar).pushMessage(
            message,
            Qgis.MessageLevel.Success,
        )
        logger.success(message)
        self.__widget.clearCacheButton.setText(self.tr("Clear Cache"))
        self.__widget.clearCacheButton.setEnabled(False)

        del log_blocker

    def format_size(self, size_in_kb):
        units = [
            self.tr("KiB"),
            self.tr("MiB"),
            self.tr("GiB"),
            self.tr("TiB"),
        ]
        size = size_in_kb
        unit_index = 0
        while size > 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        precision = 2 if size < 10 else 1
        return f"{size:.{precision}f} {units[unit_index]}"


class NgConnectOptionsErrorPageWidget(QgsOptionsPageWidget):
    widget: QWidget

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.widget = QLabel(self.tr("Settings dialog was crashed"), self)
        self.widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.widget)

    def apply(self) -> None:
        pass

    def cancel(self) -> None:
        pass


class NgConnectOptionsWidgetFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        ICONS_PATH = os.path.join(os.path.dirname(__file__), "icons/")
        super().__init__(
            "NextGIS Connect", QIcon(os.path.join(ICONS_PATH, "logo.svg"))
        )

    def path(self) -> List[str]:
        return ["NextGIS"]

    def createWidget(
        self, parent: Optional[QWidget] = None
    ) -> Optional[QgsOptionsPageWidget]:
        try:
            return NgConnectOptionsPageWidget(parent)
        except Exception:
            logger.exception("Settings dialog was crashed")
            return NgConnectOptionsErrorPageWidget(parent)
