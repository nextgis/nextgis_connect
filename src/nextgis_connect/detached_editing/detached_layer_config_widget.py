import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from qgis.core import QgsMapLayer, QgsVectorLayer
from qgis.gui import (
    QgsMapCanvas,
    QgsMapLayerConfigWidget,
    QgsMapLayerConfigWidgetFactory,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from nextgis_connect.exceptions import NgConnectError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_connection.ngw_connections_widget import (
    NgwConnectionsWidget,
)

from . import utils


class DetachedLayerConfigPage(QgsMapLayerConfigWidget):
    __path: Path
    __metadata: utils.DetachedContainerMetaData
    __layer: QgsVectorLayer

    def __init__(
        self,
        layer: Optional[QgsMapLayer],
        canvas: Optional[QgsMapCanvas],
        parent: Optional[QWidget],
    ) -> None:
        super().__init__(layer, canvas, parent)
        self.setPanelTitle(self.tr("NextGIS"))

        directory = Path(__file__).parent
        widget: Optional[QWidget] = None
        try:
            widget = uic.loadUi(
                str(directory / "detached_layer_config_widget_base.ui")
            )  # type: ignore
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

        assert isinstance(layer, QgsVectorLayer)
        self.__path = utils.container_path(layer)
        try:
            self.__metadata = utils.container_metadata(self.__path)
        except Exception:
            logger.exception(
                "An error occured while layer metadata extracting"
            )
            raise

        self.__layer = layer

        self.__connections_widget = NgwConnectionsWidget(self.__widget)
        self.__connections_widget.set_connection_id(
            self.__metadata.connection_id
        )
        self.__widget.connectionGroupBox.layout().addWidget(
            self.__connections_widget
        )

        self.__widget.synchronizationGroupBox.hide()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)  # type: ignore
        self.setLayout(layout)
        layout.addWidget(self.__widget)

    def apply(self) -> None:
        """Called when changes to the layer need to be made"""
        new_connection_id = self.__connections_widget.connection_id()
        if new_connection_id == self.__metadata.connection_id:
            return

        with closing(sqlite3.connect(self.__path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                f'UPDATE ngw_metadata SET connection_id="{new_connection_id}"'
            )

            connection.commit()

        self.__metadata = utils.container_metadata(self.__path)

        self.__layer.setCustomProperty("ngw_need_update_state", True)

    def shouldTriggerLayerRepaint(self) -> bool:
        return super().shouldTriggerLayerRepaint()

    def syncToLayer(self, layer: Optional[QgsMapLayer]) -> None:
        super().syncToLayer(layer)
        self.__connections_widget.set_connection_id(
            self.__metadata.connection_id
        )


class DetachedLayerConfigErrorPage(QgsMapLayerConfigWidget):
    widget: QWidget

    def __init__(
        self,
        layer: Optional[QgsMapLayer],
        canvas: Optional[QgsMapCanvas],
        parent: Optional[QWidget],
        message: Optional[str] = None,
    ) -> None:
        super().__init__(layer, canvas, parent)
        self.setPanelTitle(self.tr("NextGIS"))

        self.widget = QLabel(
            self.tr("Layer options widget was crashed")
            if message is None
            else message,
            self,
        )
        self.widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.widget)

    def apply(self) -> None:
        pass


class DetachedLayerConfigWidgetFactory(QgsMapLayerConfigWidgetFactory):
    def __init__(self):
        icons_path = Path(__file__).parents[1] / "icons"
        super().__init__("NextGIS", QIcon(str(icons_path / "logo.svg")))
        self.setSupportLayerPropertiesDialog(True)

    def __del__(self) -> None:
        logger.debug("Delete detached layer config factory")

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
        try:
            return DetachedLayerConfigPage(layer, canvas, parent)

        except NgConnectError as error:
            return DetachedLayerConfigErrorPage(
                layer, canvas, parent, error.user_message
            )

        except Exception:
            logger.exception("Layer settings dialog was crashed")
            return DetachedLayerConfigErrorPage(layer, canvas, parent)
