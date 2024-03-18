import os
from typing import Optional

from qgis.core import QgsMapLayer
from qgis.gui import (
    QgsMapCanvas,
    QgsMapLayerConfigWidget,
    QgsMapLayerConfigWidgetFactory,
)
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QHBoxLayout, QWidget

# from ..ngw_connection.ngw_connections_widget import NgwConnectionsWidget
from . import utils


class DetachedLayerConfigWidget(QgsMapLayerConfigWidget):
    def __init__(
        self,
        layer: Optional[QgsMapLayer],
        canvas: Optional[QgsMapCanvas],
        parent: Optional[QWidget],
    ) -> None:
        super().__init__(layer, canvas, parent)
        self.setPanelTitle(self.tr("NextGIS"))

        # TODO try-catch
        plugin_path = os.path.dirname(__file__)
        self.widget = uic.loadUi(
            os.path.join(plugin_path, "detached_layer_config_widget_base.ui")
        )  # type: ignore
        if self.widget is None:
            # TODO log
            return

        # connections_widget = NgwConnectionsWidget(self.widget)
        # self.widget.connectionGroupBox.layout().addWidget(
        #     connections_widget
        # )

        self.widget.setParent(self)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)  # type: ignore
        self.setLayout(layout)
        layout.addWidget(self.widget)

    def apply(self) -> None:
        """Called when changes to the layer need to be made"""

    def focusDefaultWidget(self) -> None:
        return self.synchronizeButton.setFocus()

    def shouldTriggerLayerRepaint(self) -> bool:
        return super().shouldTriggerLayerRepaint()

    def syncToLayer(self, layer: Optional[QgsMapLayer]) -> None:
        return super().syncToLayer(layer)


class DetachedLayerConfigWidgetFactory(QgsMapLayerConfigWidgetFactory):
    def __init__(self):
        icon = QIcon(
            os.path.join(
                os.path.dirname(__file__), os.pardir, "icons/", "logo.svg"
            )
        )
        super().__init__("NextGIS", icon)
        self.setSupportLayerPropertiesDialog(True)

    def supportsLayer(self, layer: Optional[QgsMapLayer]) -> bool:
        if layer is None:
            return False
        return utils.is_ngw_container(layer)

    def supportLayerPropertiesDialog(self) -> bool:
        return True

    def createWidget(
        self,
        layer: Optional[QgsMapLayer],
        canvas: Optional[QgsMapCanvas],
        dockWidget: bool = True,
        parent: Optional[QWidget] = None,
    ) -> QgsMapLayerConfigWidget:
        return DetachedLayerConfigWidget(layer, canvas, parent)
