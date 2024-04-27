from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qgis.core import QgsApplication
from qgis.PyQt import uic
from qgis.PyQt.QtCore import pyqtSlot
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QMenu,
    QWidget,
)

from .utils import DetachedLayerState

if TYPE_CHECKING:
    from .detached_container import DetachedContainer


WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "detached_layer_status_dialog_base.ui")
)


class DetachedLayerStatusDialog(QDialog, WIDGET):
    __container: "DetachedContainer"

    def __init__(
        self, container: "DetachedContainer", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setupUi(self)

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
            icon=QgsApplication.getThemeIcon("mActionRefresh.svg"),
            text=reset_button.text(),
            parent=self,
        )
        self.__sync_action.triggered.connect(self.__synchronize)

        self.__forced_sync_action = QAction(
            icon=reset_button.icon(),
            text=self.tr("Forced synchronization"),
            parent=self,
        )
        self.__forced_sync_action.triggered.connect(self.__forced_synchronize)

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

    @pyqtSlot(name="forceSynchronize")
    def __forced_synchronize(self) -> None:
        self.__container.force_synchronize()

    @pyqtSlot(name="updateSyncButton")
    def __update_sync_button(self) -> None:
        self.syncButton.setDefaultAction(
            self.__sync_action
            if self.__container.metadata is not None
            else self.__forced_sync_action
        )
        self.syncButton.setEnabled(
            self.__container.state != DetachedLayerState.Synchronization
            and not self.__container.is_edit_mode_enabled
        )

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
        if is_error:
            self.errorLabel.setText(self.__container.error.user_message)

    def __fill_changes(self) -> None:
        changes = self.__container.changes_info

        self.addedFeaturesLabel.setText(str(changes.added_features))
        self.removedFeaturesLabel.setText(str(changes.removed_features))
        self.updatedFeaturesLabel.setText(str(changes.updated_features))
