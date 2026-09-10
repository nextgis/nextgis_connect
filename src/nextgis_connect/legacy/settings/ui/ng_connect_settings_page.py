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

from pathlib import Path
from typing import ClassVar, List, Optional, cast

from qgis.core import Qgis, QgsApplication
from qgis.gui import (
    QgsMessageBar,
    QgsOptionsPageWidget,
    QgsOptionsWidgetFactory,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect.features.synchronization.infrastructure.storage.cache_maintenance_service import (
    CacheMaintenanceService,
)
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation.connections_widget import (
    NgwConnectionsWidget,
)
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.legacy.settings.tasks.clear_ng_connect_cache_task import (
    ClearNgConnectCacheTask,
)
from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
    NgConnectDock,
)
from nextgis_connect.platform.logging import logger, update_logging_level
from nextgis_connect.platform.qgis.utils import human_readable_size
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.icons import plugin_icon, qgis_icon
from nextgis_connect.ui_kit.widgets.labeled_slider import LabeledSlider


class NgConnectOptionsPageWidget(QgsOptionsPageWidget):
    """NextGIS Connect settings page"""

    __clear_task: Optional[ClearNgConnectCacheTask]
    __current_connection: Optional[NgwConnection]
    __connections_manager: NgwConnectionsManager

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
            message = self.tr("An error occurred while settings UI loading")
            logger.exception(message)
            raise RuntimeError(message) from error
        if widget is None:
            message = self.tr("An error occurred in settings UI")
            logger.error(message)
            raise RuntimeError(message)

        self.__widget = widget
        self.__widget.setParent(self)

        self.__clear_task = None
        self.__connections_manager = NgwConnectionsManager(parent=self)
        self.__connections_manager.connection_updated.connect(
            NgConnectInterface.instance().connection_updated.emit,
        )

        self.connections_widget = NgwConnectionsWidget(
            self.__widget,
            connections_manager=self.__connections_manager,
        )
        self.__widget.connectionsGroupBox.layout().addWidget(
            self.connections_widget
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

    def apply(self) -> None:
        settings = NgConnectSettings()

        self.__connections_manager.save()
        self.__save_current_connection()
        self.__save_resources_settings(settings)
        self.__save_search_settings(settings)
        self.__save_notification_settings(settings)
        self.__save_cache_settings()
        self.__save_other_settings(settings)

        plugin = NgConnectInterface.instance()
        plugin.settings_changed.emit()

    def cancel(self) -> None:
        self.__connections_manager.reset()

    def __init_settings(self) -> None:
        settings = NgConnectSettings()
        self.__init_connections()
        self.__init_resources_settings(settings)
        self.__init_search_settings(settings)
        self.__init_notification_settings(settings)
        self.__init_cache_settings()
        self.__init_other_settings(settings)

    def __init_connections(self) -> None:
        if self.__connections_manager.has_not_converted_connections():
            self.__connections_manager.convert_old_connections(
                convert_auth=True
            )

        self.__current_connection = (
            self.__connections_manager.current_connection
        )

        self.__need_reinit = False

    def __init_resources_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.addResourceCreationMetadataCheckBox.setChecked(
            settings.add_resource_creation_metadata
        )
        self.__widget.embedSvgImagesInQmlCheckBox.setChecked(
            settings.embed_svg_images_in_qml
        )
        self.__widget.addWfsLayerAfterServiceCreationCheckBox.setChecked(
            settings.add_layer_after_service_creation
        )
        self.__widget.openWebMapAfterCreationCheckBox.setChecked(
            settings.open_web_map_after_creation
        )

    def __init_search_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.metadataKeysLineEdit.setText(
            ", ".join(settings.search.metadata_keys)
        )

    def __init_notification_settings(
        self, settings: NgConnectSettings
    ) -> None:
        attachments_checkbox = (
            self.__widget.deletingFeaturesWithAttachmentsCheckbox
        )
        attachments_checkbox.setChecked(
            settings.notify_when_deleting_features_with_attachments
        )

    def __init_cache_settings(self) -> None:
        cache_service = CacheMaintenanceService()
        is_cache_directory_default = (
            cache_service.cache_directory
            == cache_service.default_user_profile_cache_directory
        )

        # Cache directory lineedit
        self.__widget.cacheDirectoryLineEdit.setPlaceholderText(
            cache_service.default_user_profile_cache_directory
        )
        if not is_cache_directory_default:
            self.__widget.cacheDirectoryLineEdit.setText(
                cache_service.cache_directory
            )
        self.__widget.cacheDirectoryLineEdit.textChanged.connect(
            self.__update_reset_cache_button
        )

        # Choose cache directory button
        self.__widget.cacheDirectoryButton.setIcon(
            qgis_icon("mActionFileOpen.svg")
        )
        self.__widget.cacheDirectoryButton.clicked.connect(
            self.__choose_cache_directory
        )

        # Cache directory reset button
        self.__widget.resetCacheDirectoryButton.setIcon(
            qgis_icon("mActionUndo.svg")
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
            cache_duration_combobox.findData(cache_service.cache_duration)
        )

        # Cache size button
        self.__widget.cacheSizeSlider.setValue(
            self.CACHE_SIZE_VALUES.index(cache_service.cache_max_size)
        )

        # Clear cache button
        self.__widget.clearCacheButton.setIcon(
            qgis_icon("mActionDeleteSelected.svg")
        )
        self.__widget.clearCacheButton.clicked.connect(self.__clear_cache)

        self.__update_cache_button(cache_service)

    def __update_cache_button(
        self, cache_service: CacheMaintenanceService
    ) -> None:
        cache_size = cache_service.cache_size
        if cache_size == 0:
            self.__widget.clearCacheButton.setText(self.tr("Clear Cache"))
            self.__widget.clearCacheButton.setToolTip(
                self.tr("Cache is empty")
            )
            self.__widget.clearCacheButton.setEnabled(False)
        else:
            self.__widget.clearCacheButton.setText(
                self.tr("Clear Cache")
                + f"  ({human_readable_size(cache_size)})"
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
        old_connection = self.__current_connection
        new_connection = self.__connections_manager.current_connection

        if not self.__need_reinit:
            if (old_connection is not None and new_connection is None) or (
                old_connection is None and new_connection is not None
            ):
                self.__need_reinit = True
            elif old_connection is not None and new_connection is not None:
                self.__need_reinit = old_connection != new_connection

        self.__current_connection = new_connection

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
        cache_service = CacheMaintenanceService()
        initial_directory = self.__cache_directory_input_path(cache_service)
        initial_directory.mkdir(parents=True, exist_ok=True)
        file_dialog = QFileDialog(
            self,
            caption=self.tr(
                "Choose a directory to store NextGIS Connect cache"
            ),
        )
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        file_dialog.setFileMode(QFileDialog.FileMode.Directory)
        file_dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        file_dialog.setDirectory(str(initial_directory))

        if not file_dialog.exec():
            return

        directory = file_dialog.selectedFiles()[0]
        self.__widget.cacheDirectoryLineEdit.setText(directory)

    def __cache_directory_input_path(
        self,
        cache_service: CacheMaintenanceService,
    ) -> Path:
        cache_directory = self.__widget.cacheDirectoryLineEdit.text()
        if len(cache_directory) > 0:
            return Path(cache_directory)
        return Path(cache_service.cache_directory)

    def __update_reset_cache_button(self, text: str) -> None:
        self.__widget.resetCacheDirectoryButton.setEnabled(len(text) > 0)

    def __reset_cache_directory(self) -> None:
        self.__widget.cacheDirectoryLineEdit.setText("")

    def __save_resources_settings(self, settings: NgConnectSettings) -> None:
        settings.add_resource_creation_metadata = (
            self.__widget.addResourceCreationMetadataCheckBox.isChecked()
        )
        settings.embed_svg_images_in_qml = (
            self.__widget.embedSvgImagesInQmlCheckBox.isChecked()
        )
        settings.add_layer_after_service_creation = (
            self.__widget.addWfsLayerAfterServiceCreationCheckBox.isChecked()
        )
        settings.open_web_map_after_creation = (
            self.__widget.openWebMapAfterCreationCheckBox.isChecked()
        )

    def __save_search_settings(self, settings: NgConnectSettings) -> None:
        keys = [
            key.strip()
            for key in self.__widget.metadataKeysLineEdit.text().split(",")
        ]
        settings.search.metadata_keys = [key for key in keys if len(key) != 0]

    def __save_notification_settings(
        self, settings: NgConnectSettings
    ) -> None:
        attachments_checkbox = (
            self.__widget.deletingFeaturesWithAttachmentsCheckbox
        )
        settings.notify_when_deleting_features_with_attachments = (
            attachments_checkbox.isChecked()
        )

    def __save_cache_settings(self) -> None:
        cache_service = CacheMaintenanceService()
        cache_directory = self.__widget.cacheDirectoryLineEdit.text()
        cache_service.cache_directory = (
            cache_directory if len(cache_directory) > 0 else None
        )
        cache_duration_combobox = cast(
            QComboBox, self.__widget.autoRemoveCacheComboBox
        )
        cache_service.cache_duration = cache_duration_combobox.currentData()
        cache_size_index = self.__widget.cacheSizeSlider.value()
        cache_service.cache_max_size = self.CACHE_SIZE_VALUES[cache_size_index]

    def __save_other_settings(self, settings: NgConnectSettings) -> None:
        old_debug_enabled = settings.is_debug_enabled
        new_debug_enabled = self.__widget.debugEnabledCheckBox.isChecked()
        settings.is_debug_enabled = new_debug_enabled
        if old_debug_enabled != new_debug_enabled:
            debug_state = "enabled" if new_debug_enabled else "disabled"
            update_logging_level()
            logger.info(f"Debug messages are now {debug_state}")
        settings.is_network_debug_enabled = (
            self.__widget.debugNetworkCheckBox.isChecked()
        )

    def __clear_cache(self) -> None:
        self.__widget.clearCacheProgressBar.show()
        self.__widget.clearCacheButton.hide()

        cache_service = CacheMaintenanceService()

        if cache_service.has_files_used_by_project:
            message = self.tr(
                "It is not possible to clear the cache while layers from it"
                " are being used in a project."
            )
            cast(QgsMessageBar, self.__widget.messageBar).pushMessage(
                message,
                Qgis.MessageLevel.Warning,
            )
            self.__widget.clearCacheProgressBar.hide()
            self.__widget.clearCacheButton.show()
            return

        if cache_service.has_containers_with_changes:
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
                self.__widget.clearCacheProgressBar.hide()
                self.__widget.clearCacheButton.show()
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

        cache_service = CacheMaintenanceService()
        self.__update_cache_button(cache_service)

    def __on_debug_state_changed(self, state: bool) -> None:
        self.__widget.debugNetworkCheckBox.setEnabled(state)

    def __convert_old_connections(self) -> None:
        self.__connections_manager.convert_old_connections(convert_auth=True)

        self.__current_connection = (
            self.__connections_manager.current_connection
        )

        message_bar = cast(QgsMessageBar, self.__widget.messageBar)

        message_bar.popWidget()
        message_bar.pushMessage(
            self.tr("Connections were successfully converted!"),
            Qgis.MessageLevel.Success,
        )

        self.connections_widget.load_connections()

        self.__need_reinit = True


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
        super().__init__(
            "NextGIS Connect",
            plugin_icon("branding/connect_logo.svg"),
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
