from pathlib import Path
from typing import TYPE_CHECKING, cast

from qgis.gui import QgsLayerTreeViewIndicator
from qgis.PyQt.QtCore import QTimer, pyqtSlot
from qgis.PyQt.QtGui import QIcon

from nextgis_connect.logging import logger

from .detached_layer_status_dialog import DetachedLayerStatusDialog
from .utils import DetachedLayerState

if TYPE_CHECKING:
    from .detached_container import DetachedContainer


class DetachedLayerIndicator(QgsLayerTreeViewIndicator):
    __tick: int
    __timer: QTimer

    def __init__(self, container: "DetachedContainer") -> None:
        super().__init__(container)

        self.clicked.connect(self.__open_details)

        self.__tick = 0
        self.__timer = QTimer(self)
        self.__timer.setInterval(250)
        self.__timer.timeout.connect(self.__sync_tick)

        self.__container.state_changed.connect(self.__on_state_changed)
        self.__on_state_changed(self.__container.state)

        logger.debug(f"Create indicator for container {container.metadata}")

    def __del__(self) -> None:
        logger.debug(f"Delete indicator for {self.__container.metadata}")

    @property
    def __container(self) -> "DetachedContainer":
        return cast("DetachedContainer", self.parent())

    @pyqtSlot(DetachedLayerState, name="onStateChanged")
    def __on_state_changed(self, state: DetachedLayerState) -> None:
        icons_path = Path(__file__).parents[1] / "icons" / "detached_layers"

        self.__timer.stop()
        self.__tick = 0

        tooltip = self.tr("NextGIS Web Layer")
        date_tooltip = ""

        sync_date = self.__container.sync_date
        if sync_date is not None:
            sync_datetime = sync_date.strftime("%c")
            sync_date_label = self.tr("Synchronization date")
            date_tooltip += f"\n{sync_date_label}: {sync_datetime}"

        check_date = self.__container.check_date
        if check_date is not None:
            check_datetime = check_date.strftime("%c")
            check_date_label = self.tr("Check date")
            date_tooltip += f"\n{check_date_label}: {check_datetime}"

        if state in (
            DetachedLayerState.NotInitialized,
            DetachedLayerState.NotSynchronized,
        ):
            self.setIcon(QIcon(str(icons_path / "not_synchronized.svg")))
            status_tooltip = self.tr("Layer is not synchronized!")
            tooltip = f"{status_tooltip}{date_tooltip}"
        elif state == DetachedLayerState.Synchronized:
            self.setIcon(QIcon(str(icons_path / "synchronized.svg")))
            status_tooltip = self.tr("Layer is synchronized")
            tooltip = f"{status_tooltip}{date_tooltip}"
        elif state == DetachedLayerState.Synchronization:
            self.setIcon(QIcon(str(icons_path / "synchronization.svg")))
            tooltip = self.tr("Layer is syncing")
        elif state == DetachedLayerState.Error:
            self.setIcon(QIcon(str(icons_path / "error.svg")))
            if self.__container.error_code.is_synchronization_error:
                status_tooltip = self.tr("Synchronization error!")
            elif self.__container.error_code.is_container_error:
                status_tooltip = self.tr("Layer error!")
            else:
                status_tooltip = self.tr("Unknown error!")
            spoiler = self.tr("Click to see more details")
            tooltip = f"{status_tooltip}{date_tooltip}\n\n{spoiler}"

        self.setToolTip(tooltip)

        if state == DetachedLayerState.Synchronization:
            self.__timer.start()

    @pyqtSlot(name="openDetails")
    def __open_details(self) -> None:
        dialog = DetachedLayerStatusDialog(self.__container)
        dialog.exec()

    @pyqtSlot(name="syncTick")
    def __sync_tick(self) -> None:
        self.__tick += 1

        icons_path = Path(__file__).parents[1] / "icons" / "detached_layers"
        if self.__tick % 5 == 0:
            self.setIcon(QIcon(str(icons_path / "empty.svg")))
        else:
            self.setIcon(QIcon(str(icons_path / "synchronization.svg")))
