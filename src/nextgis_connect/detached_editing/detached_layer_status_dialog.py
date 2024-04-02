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

        Button = QDialogButtonBox.StandardButton  # noqa: N806
        button_box_template = QDialogButtonBox(
            QDialogButtonBox.StandardButtons() | Button.Reset | Button.Close
        )

        reset_button = button_box_template.button(Button.Reset)
        assert reset_button is not None
        reset_button.setText(self.tr("Synchronization"))
        close_button = button_box_template.button(Button.Close)
        assert close_button is not None

        sync_action = QAction(
            icon=QgsApplication.getThemeIcon("mActionRefresh.svg"),
            text=reset_button.text(),
            parent=self,
        )
        sync_action.triggered.connect(self.__synchronize)

        forced_sync_action = QAction(
            icon=reset_button.icon(),
            text=self.tr("Forced synchronization"),
            parent=self,
        )
        forced_sync_action.triggered.connect(self.__forced_synchronize)

        sync_menu = QMenu(self)
        sync_menu.addAction(forced_sync_action)
        self.syncButton.setMenu(sync_menu)
        self.syncButton.setDefaultAction(sync_action)
        self.syncButton.setFixedHeight(reset_button.sizeHint().height())

        self.closeButton.setIcon(close_button.icon())
        self.closeButton.setFixedHeight(close_button.sizeHint().height())
        self.closeButton.clicked.connect(self.reject)

        self.__container = container
        self.__container.state_changed.connect(self.__on_state_changed)
        self.__on_state_changed(self.__container.state)

    @pyqtSlot(DetachedLayerState, name="onStateChanged")
    def __on_state_changed(self, state: DetachedLayerState) -> None:
        is_sync_active = state == DetachedLayerState.Synchronization

        self.progressBar.setVisible(is_sync_active)
        self.syncButton.setEnabled(
            self.__container.state != DetachedLayerState.Synchronization
        )
        self.changesPage.setEnabled(
            self.__container.state != DetachedLayerState.Synchronization
        )

        self.__fill_status()
        self.__fill_changes()

    @pyqtSlot(name="synchronize")
    def __synchronize(self) -> None:
        self.__container.synchronize(is_manual=True)

    @pyqtSlot(name="forceSynchronize")
    def __forced_synchronize(self) -> None:
        self.__container.force_synchronize()

    def __fill_status(self) -> None:
        sync_datetime = self.__container.metadata.sync_date
        sync_datetime = (
            sync_datetime.strftime("%c") if sync_datetime is not None else "—"
        )
        self.latestUpdateLabel.setText(sync_datetime)

    def __fill_changes(self) -> None:
        changes = self.__container.changes

        self.addedFeaturesLabel.setText(str(changes.added_features))
        self.removedFeaturesLabel.setText(str(changes.removed_features))
        self.updatedFeaturesLabel.setText(str(changes.updated_features))
