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
from typing import TYPE_CHECKING, Optional

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSize, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QLayout,
    QMenu,
    QWidget,
)

from nextgis_connect.legacy.detached_editing.reset import (
    confirm_reset_container,
)
from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.ui_kit.buttons.loading import LoadingToolButton
from nextgis_connect.ui_kit.icons import material_icon, qgis_icon

if TYPE_CHECKING:
    from nextgis_connect.legacy.detached_editing.container.container import (
        DetachedContainer,
    )


WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "layer_status_dialog_base.ui")
)


class DetachedLayerStatusDialog(QDialog, WIDGET):
    __container: "DetachedContainer"

    def __init__(
        self, container: "DetachedContainer", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.__replace_sync_button()

        warning_icon = qgis_icon("mIconWarning.svg")
        size = int(max(24.0, self.syncButton.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.warningLabel.setToolTip(
            self.tr(
                "Synchronization is not possible while the layer is in edit"
                " mode"
            )
        )
        self.warningLabel.setPixmap(pixmap)
        self.warningLabel.hide()

        Button = QDialogButtonBox.StandardButton
        button_box_template = QDialogButtonBox(
            QDialogButtonBox.StandardButtons() | Button.Reset | Button.Close
        )

        reset_button = button_box_template.button(Button.Reset)
        assert reset_button is not None
        reset_button.setText(self.tr("Synchronization"))
        close_button = button_box_template.button(Button.Close)
        assert close_button is not None

        self.__sync_action = QAction(
            icon=material_icon("sync"),
            text=reset_button.text(),
            parent=self,
        )
        self.__sync_action.triggered.connect(self.__synchronize)

        self.__forced_sync_action = QAction(
            icon=material_icon("undo"),
            text=self.tr("Reset layer"),
            parent=self,
        )
        self.__forced_sync_action.triggered.connect(self.__reset_container)

        sync_menu = QMenu(self)
        sync_menu.addAction(self.__forced_sync_action)
        self.syncButton.setMenu(sync_menu)
        self.syncButton.setDefaultAction(self.__sync_action)
        self.syncButton.setFixedHeight(reset_button.sizeHint().height())

        self.closeButton.setIcon(close_button.icon())
        self.closeButton.setFixedHeight(close_button.sizeHint().height())
        self.closeButton.clicked.connect(self.reject)

        self.__container = container
        self.__container.editing_started.connect(self.__update_sync_button)
        self.__container.editing_finished.connect(self.__update_sync_button)
        self.__container.state_changed.connect(self.__on_state_changed)

        self.__on_state_changed(container.state)

    def __replace_sync_button(self) -> None:
        original_button = self.syncButton
        parent = original_button.parentWidget()
        assert parent is not None
        layout = self.horizontalLayout
        assert isinstance(layout, QLayout)
        index = layout.indexOf(original_button)
        assert index != -1

        sync_button = LoadingToolButton(parent=parent)
        sync_button.setObjectName(original_button.objectName())
        sync_button.setPopupMode(original_button.popupMode())
        sync_button.setToolButtonStyle(original_button.toolButtonStyle())
        sync_button.setSizePolicy(original_button.sizePolicy())
        sync_button.setMinimumSize(original_button.minimumSize())
        sync_button.setMaximumSize(original_button.maximumSize())

        layout.removeWidget(original_button)
        original_button.hide()
        original_button.deleteLater()
        layout.insertWidget(index, sync_button)
        self.syncButton = sync_button

    @pyqtSlot(DetachedLayerState, name="onStateChanged")
    def __on_state_changed(self, state: DetachedLayerState) -> None:
        is_sync_active = state == DetachedLayerState.Synchronization

        self.progressBar.setVisible(is_sync_active)

        self.__update_sync_button()

        self.changesGroupBox.setEnabled(
            state != DetachedLayerState.Synchronization
        )

        self.__fill_status()
        self.__fill_changes()

    @pyqtSlot(name="synchronize")
    def __synchronize(self) -> None:
        self.__container.synchronize(is_manual=True)

    @pyqtSlot(name="resetContainer")
    def __reset_container(self) -> None:
        confirm_reset_container(self.__container, self)

    @pyqtSlot(name="updateSyncButton")
    def __update_sync_button(self) -> None:
        self.syncButton.setDefaultAction(
            self.__sync_action
            if self.__container.metadata is not None
            else self.__forced_sync_action
        )
        if self.__container.state == DetachedLayerState.Synchronization:
            self.syncButton.start()
        elif self.syncButton.is_loading():
            self.syncButton.stop()

        self.syncButton.setEnabled(
            self.__container.state != DetachedLayerState.Synchronization
            and not self.__container.is_edit_mode_enabled
        )
        self.warningLabel.setVisible(self.__container.is_edit_mode_enabled)

    def __fill_status(self) -> None:
        sync_datetime = self.__container.sync_date
        sync_datetime = (
            sync_datetime.strftime("%c") if sync_datetime is not None else "—"
        )
        self.latestUpdateLabel.setText(sync_datetime)

        states = {
            DetachedLayerState.NotInitialized: self.tr("Not initialized"),
            DetachedLayerState.Error: self.tr("Error"),
            DetachedLayerState.NotSynchronized: self.tr("Not synchronized"),
            DetachedLayerState.Synchronization: self.tr("Synchronization"),
            DetachedLayerState.Synchronized: self.tr("Synchronized"),
        }

        state = self.__container.state
        self.stateLabel.setText(states[state])
        is_error = state == DetachedLayerState.Error
        self.line.setVisible(is_error)
        self.errorLabel.setVisible(is_error)
        if is_error and self.__container.error is not None:
            self.errorLabel.setText(self.__container.error.user_message)

    def __fill_changes(self) -> None:
        changes = self.__container.changes_info

        self.addedFeaturesLabel.setText(str(changes.added_features_count))
        self.removedFeaturesLabel.setText(str(changes.removed_features_count))
        self.updatedFeaturesLabel.setText(str(changes.updated_features_count))
