from typing import Optional
from pathlib import Path
from datetime import datetime
from pkg_resources import resource_filename

from qgis.PyQt.QtCore import QObject, pyqtSlot
from qgis.PyQt.QtGui import QIcon

from qgis.core import QgsVectorLayer
from qgis.gui import QgsLayerTreeViewIndicator

from .detached_layer_status_dialog import DetachedLayerStatusDialog
from . import utils
from .utils import DetachedLayerState


class DetachedLayerIndicator(QgsLayerTreeViewIndicator):
    __layer: QgsVectorLayer

    def __init__(
        self, layer: QgsVectorLayer, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)

        self.__layer = layer
        self.__layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )
        self.__on_custom_property_changed('ngw_layer_state')
        self.clicked.connect(self.__open_details)

    def __on_custom_property_changed(self, property_name: str) -> None:
        if property_name != 'ngw_layer_state':
            return

        state_string = self.__layer.customProperty('ngw_layer_state')
        state = DetachedLayerState(state_string)

        icons_path = (
            Path(resource_filename('nextgis_connect', ''))
            / 'icons'
            / 'detached_layers'
        )

        tooltip = self.tr('NGW Layer')
        date_property: datetime = \
            self.__layer.customProperty('ngw_synchronization_date')
        sync_datetime = date_property.strftime('%c')
        sync_date_label = self.tr("Synchronization date")
        date_tooltip = f'\n{sync_date_label}: {sync_datetime}'

        if state == DetachedLayerState.NotSynchronized:
            self.setIcon(QIcon(str(icons_path / 'not_synchronized.svg')))
            tooltip = self.tr('Layer is not synchronized!') + date_tooltip
        elif state == DetachedLayerState.Synchronized:
            self.setIcon(QIcon(str(icons_path / 'synchronized.svg')))
            tooltip = self.tr('Layer is synchronized') + date_tooltip
        elif state == DetachedLayerState.Synchronization:
            self.setIcon(QIcon(str(icons_path / 'synchronization.svg')))
            tooltip = self.tr('Layer is syncing')
        elif state == DetachedLayerState.Error:
            self.setIcon(QIcon(str(icons_path / 'error.svg')))
            tooltip = self.tr('Synchronization error!') + date_tooltip

        self.setToolTip(tooltip)

    @pyqtSlot(name='openDetails')
    def __open_details(self) -> None:
        dialog = DetachedLayerStatusDialog(utils.container_path(self.__layer))
        dialog.exec_()
