from datetime import timedelta
from pathlib import Path
from typing import ClassVar, List, Optional, cast

from qgis.core import Qgis, QgsApplication
from qgis.gui import (
    QgsMessageBar,
    QgsOptionsPageWidget,
    QgsOptionsWidgetFactory,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSize, Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect import NgConnectInterface
from nextgis_connect.core.ui.labeled_slider import LabeledSlider
from nextgis_connect.logging import logger, update_level
from nextgis_connect.ng_connect_dock import NgConnectDock
from nextgis_connect.ngw_connection.ngw_connection import NgwConnection
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.ngw_connection.ngw_connections_widget import (
    NgwConnectionsWidget,
)
from nextgis_connect.settings import NgConnectSettings
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from nextgis_connect.settings.tasks.clear_ng_connect_cache_task import (
    ClearNgConnectCacheTask,
)


class NgConnectOptionsPageWidget(QgsOptionsPageWidget):
    """NextGIS Connect settings page"""

    __widget: QWidget
    __clear_task: Optional[ClearNgConnectCacheTask]
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

        plugin_path = Path(__file__).parent
        widget: Optional[QWidget] = None
        try:
            widget = uic.loadUi(str(plugin_path / "settings_dialog_base.ui"))  # type: ignore
        except FileNotFoundError as error:
            message = self.tr("An error occured while settings UI loading")
            logger.exception(message)
            raise RuntimeError(message) from error
        if widget is None:
            message = self.tr("An error occured in settings UI")
            logger.error(message)
            raise RuntimeError(message)

        self.__widget = widget
        self.__widget.setParent(self)

        self.__clear_task = None

        self.connections_widget = NgwConnectionsWidget(self.__widget)
        self.__widget.connectionsGroupBox.layout().addWidget(
            self.connections_widget
        )

        icon_path = Path(__file__).parents[2] / "icons" / "experimental.svg"
        warning_icon = QIcon(str(icon_path))
        size = int(
            max(18.0, self.__widget.versioningCheckBox.minimumSize().height())
        )
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )

        self.__widget.versioningIcon.setPixmap(pixmap)
        self.__widget.versioningIcon.setToolTip(
            self.tr(
                "Experimental feature. Some operations may not work if feature"
                " versioning is enabled."
            )
        )

        unit = self.tr("GiB")
        self.__widget.cacheSizeSlider = LabeledSlider(
            [f"{number} {unit}" for number in [8, 12, 16, 24, 32, 64]] + ["∞"],
            self.__widget,
        )
        self.__widget.maxSizeLayout.addWidget(self.__widget.cacheSizeSlider)

        self.__widget.clearCacheProgressBar.hide()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)  # type: ignore
        self.setLayout(layout)
        layout.addWidget(self.__widget)

        self.__init_settings()

    def __del__(self):
        # Workaround
        if not self.__is_accepted and not self.__is_cancelled:
            self.cancel()

    def apply(self) -> None:
        self.__is_accepted = True

        settings = NgConnectSettings()

        self.__save_current_connection()
        self.__save_uploading_settings(settings)
        self.__save_resources_settings(settings)
        self.__save_search_settings(settings)
        self.__save_sync_settings(settings)
        self.__save_cache_settings()
        self.__save_other_settings(settings)

        plugin = NgConnectInterface.instance()
        plugin.settings_changed.emit()

    def cancel(self) -> None:
        self.__is_cancelled = True
        connections_manager = NgwConnectionsManager()
        current_connections = connections_manager.connections

        # Remove new
        delta = set(current_connections) - set(self.__connections)
        for connection in delta:
            connections_manager.remove(connection.id)

        # Restore old
        for connection in self.__connections:
            connections_manager.save(connection)

        if self.__need_reinit:
            # TODO (ivanbarsukov): refactoring
            dock = iface.mainWindow().findChild(NgConnectDock, "NGConnectDock")  # type: ignore
            dock.reinit_tree(force=True)

    def __init_settings(self) -> None:
        settings = NgConnectSettings()
        self.__is_accepted = False
        self.__is_cancelled = False
        self.__init_connections()
        self.__init_uploading_settings(settings)
        self.__init_resources_settings(settings)
        self.__init_search_settings(settings)
        self.__init_sync_settings(settings)
        self.__init_cache_settings()
        self.__init_other_settings(settings)

    def __init_connections(self) -> None:
        connections_manager = NgwConnectionsManager()
        self.__current_connection = connections_manager.current_connection
        self.__connections = connections_manager.connections

        self.__need_reinit = False

        if connections_manager.has_not_converted_connections():
            message_bar = cast(QgsMessageBar, self.__widget.messageBar)
            widget = message_bar.createMessage(
                self.tr(
                    "Do you want to convert connections created in previous"
                    " versions of NextGIS Connect?"
                )
            )

            button = QPushButton(widget)
            button.setText("Convert")
            button.pressed.connect(self.__convert_old_connections)
            widget.layout().addWidget(button)

            message_bar.pushWidget(widget, Qgis.MessageLevel.Warning)

    def __init_uploading_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.fixGeometryCheckBox.setChecked(
            settings.fix_incorrect_geometries
        )
        self.__widget.fixGeometryCheckBox.hide()  # Rely on NGW

        self.__widget.openWebMapAfterCreationCheckBox.setChecked(
            settings.open_web_map_after_creation
        )
        self.__widget.cogCheckBox.setChecked(settings.upload_raster_as_cog)
        self.__widget.versioningCheckBox.setChecked(
            settings.upload_vector_with_versioning
        )

    def __init_resources_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.addWfsLayerAfterServiceCreationCheckBox.setChecked(
            settings.add_layer_after_service_creation
        )

    def __init_search_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.search_groupbox.setVisible(settings.is_developer_mode)
        self.__widget.metadataKeysLineEdit.setText(
            ", ".join(settings.search.metadata_keys)
        )

    def __init_sync_settings(self, settings: NgConnectSettings) -> None:
        period = settings.synchronizatin_period

        if period // timedelta(minutes=1) < 59:
            value = period // timedelta(minutes=1)
            index = 0
        else:
            value = period // timedelta(hours=1)
            index = 1

        self.__widget.syncPeriodSpinBox.setValue(value)
        self.__widget.syncPeriodSpinBox.valueChanged.connect(
            self.__update_sync_combobox
        )

        period_combobox = cast(QComboBox, self.__widget.syncPeriodComboBox)
        period_combobox.addItem("", "minutes")
        period_combobox.addItem("", "hours")
        self.__update_sync_combobox(value)

        period_combobox.setCurrentIndex(index)

    def __update_sync_combobox(self, value: int) -> None:
        period_combobox = cast(QComboBox, self.__widget.syncPeriodComboBox)

        minute_string = self.tr("%n$minute", None, value)
        if minute_string == f"{value}$minute" and value != 1:
            minute_string += "s"
        minute_string = minute_string[minute_string.find("$") + 1 :]
        period_combobox.setItemText(0, minute_string)

        hour_string = self.tr("%n$hour", None, value)
        if hour_string == f"{value}$hour" and value != 1:
            hour_string += "s"
        hour_string = hour_string[hour_string.find("$") + 1 :]
        period_combobox.setItemText(1, hour_string)

    def __init_cache_settings(self) -> None:
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

        self.__update_cache_button(cache_manager)

    def __update_cache_button(
        self, cache_manager: NgConnectCacheManager
    ) -> None:
        cache_size = cache_manager.cache_size
        if cache_size == 0:
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
        self.__widget.debugEnabledCheckBox.setChecked(
            settings.is_debug_enabled
        )
        self.__widget.debugEnabledCheckBox.toggled.connect(
            self.__on_debug_state_changed
        )

        self.__widget.debugNetworkCheckBox.setChecked(
            settings.is_network_debug_enabled
        )
        self.__widget.debugNetworkCheckBox.setEnabled(
            settings.is_debug_enabled
        )

    def __save_current_connection(self):
        connections_manager = NgwConnectionsManager()
        old_connection = self.__current_connection
        new_connection_id = self.connections_widget.connection_id()

        if not self.__need_reinit:
            if (old_connection is not None and new_connection_id is None) or (
                old_connection is None and new_connection_id is not None
            ):
                self.__need_reinit = True
                connections_manager.current_connection_id = new_connection_id
            elif old_connection is not None and new_connection_id is not None:
                new_connection = connections_manager.connection(
                    new_connection_id
                )
                if old_connection != new_connection:
                    self.__need_reinit = True
                    connections_manager.current_connection_id = (
                        new_connection_id
                    )

        self.__current_connection = connections_manager.current_connection
        self.__connections = connections_manager.connections

        method = ""
        if self.__current_connection is not None:
            method = QgsApplication.authManager().configAuthMethodKey(
                self.__current_connection.auth_config_id
            )

        # If method is NextGIS tree will be automatically updated on apply
        if self.__need_reinit and method != "NextGIS":
            # TODO (ivanbarsukov): refactoring
            dock = iface.mainWindow().findChild(NgConnectDock, "NGConnectDock")  # type: ignore
            dock.reinit_tree(force=True)

        self.__need_reinit = False

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

    def __save_uploading_settings(self, settings: NgConnectSettings) -> None:
        settings.fix_incorrect_geometries = (
            self.__widget.fixGeometryCheckBox.isChecked()
        )

        settings.upload_raster_as_cog = self.__widget.cogCheckBox.isChecked()
        settings.upload_vector_with_versioning = (
            self.__widget.versioningCheckBox.isChecked()
        )

        settings.open_web_map_after_creation = (
            self.__widget.openWebMapAfterCreationCheckBox.isChecked()
        )

    def __save_resources_settings(self, settings: NgConnectSettings) -> None:
        settings.add_layer_after_service_creation = (
            self.__widget.addWfsLayerAfterServiceCreationCheckBox.isChecked()
        )

    def __save_search_settings(self, settings: NgConnectSettings) -> None:
        keys = [
            key.strip()
            for key in self.__widget.metadataKeysLineEdit.text().split(",")
        ]
        settings.search.metadata_keys = [key for key in keys if len(key) != 0]

    def __save_sync_settings(self, settings: NgConnectSettings) -> None:
        period_spinbox = cast(QSpinBox, self.__widget.syncPeriodSpinBox)
        period_combobox = cast(QComboBox, self.__widget.syncPeriodComboBox)

        param = {period_combobox.currentData(): period_spinbox.value()}
        settings.synchronizatin_period = timedelta(**param)

    def __save_cache_settings(self) -> None:
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

    def __save_other_settings(self, settings: NgConnectSettings) -> None:
        old_debug_enabled = settings.is_debug_enabled
        new_debug_enabled = self.__widget.debugEnabledCheckBox.isChecked()
        settings.is_debug_enabled = new_debug_enabled
        if old_debug_enabled != new_debug_enabled:
            debug_state = "enabled" if new_debug_enabled else "disabled"
            update_level()
            logger.info(f"Debug messages are now {debug_state}")
        settings.is_network_debug_enabled = (
            self.__widget.debugNetworkCheckBox.isChecked()
        )

    def __clear_cache(self) -> None:
        self.__widget.clearCacheProgressBar.show()
        self.__widget.clearCacheButton.hide()

        cache_manager = NgConnectCacheManager()

        if cache_manager.has_files_used_by_project:
            message = self.tr(
                "It is not possible to clear the cache while layers from it"
                " are being used in a project."
            )
            cast(QgsMessageBar, self.__widget.messageBar).pushMessage(
                message,
                Qgis.MessageLevel.Warning,
            )

            return

        if cache_manager.has_containers_with_changes:
            answer = QMessageBox.question(
                self,
                self.tr("Possible data loss"),
                self.tr(
                    "Some layers in the cache contain unsynchronized changes."
                    " If you continue, you will lose them forever.\n\n"
                    "Are you sure you want to continue?"
                ),
                QMessageBox.StandardButtons()
                | QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.__clear_task = ClearNgConnectCacheTask()
        self.__clear_task.taskCompleted.connect(
            lambda: self.__on_clear_completed(True)
        )
        self.__clear_task.taskTerminated.connect(
            lambda: self.__on_clear_completed(False)
        )

        plugin = NgConnectInterface.instance()
        plugin.task_manager.addTask(self.__clear_task)

    @pyqtSlot(bool)
    def __on_clear_completed(self, result: bool) -> None:
        if result:
            message = self.tr("Cache has been successfully cleared")
            cast(QgsMessageBar, self.__widget.messageBar).pushMessage(
                message,
                Qgis.MessageLevel.Success,
            )
            logger.success(message)
        else:
            message = self.tr(
                "Some files were not cleared. Perhaps they are in use."
            )
            cast(QgsMessageBar, self.__widget.messageBar).pushMessage(
                message,
                Qgis.MessageLevel.Warning,
            )
            logger.warning(message)

        self.__clear_task = None

        self.__widget.clearCacheProgressBar.hide()
        self.__widget.clearCacheButton.show()

        cache_manager = NgConnectCacheManager()
        self.__update_cache_button(cache_manager)

    def __on_debug_state_changed(self, state: bool) -> None:
        self.__widget.debugNetworkCheckBox.setEnabled(state)

    def __convert_old_connections(self) -> None:
        connections_manager = NgwConnectionsManager()
        connections_manager.convert_old_connections(convert_auth=True)

        self.__current_connection = connections_manager.current_connection
        self.__connections = connections_manager.connections

        message_bar = cast(QgsMessageBar, self.__widget.messageBar)

        message_bar.popWidget()
        message_bar.pushMessage(
            self.tr("Connections were successfully converted!"),
            Qgis.MessageLevel.Success,
        )

        self.connections_widget.refresh()

        self.__need_reinit = True

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
        icons_path = Path(__file__).parents[2] / "icons"
        super().__init__(
            "NextGIS Connect", QIcon(str(icons_path / "connect_logo.svg"))
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
