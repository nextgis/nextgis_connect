from typing import Optional

from qgis.core import QgsMapLayer, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtWidgets import QAction

from nextgis_connect.ngw_api.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from nextgis_connect.ngw_api.core.ngw_raster_layer import NGWRasterLayer


class ActionStyleImportUpdate(QAction):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(False)

    def setEnabledByType(
        self, qgis_layer: Optional[QgsMapLayer], ngw_vector_layer
    ):
        enabled = False

        if isinstance(qgis_layer, QgsRasterLayer) and isinstance(
            ngw_vector_layer, NGWRasterLayer
        ):
            enabled = True

        elif isinstance(qgis_layer, QgsVectorLayer) and isinstance(
            ngw_vector_layer, NGWAbstractVectorResource
        ):
            enabled = (
                qgis_layer.geometryType() == ngw_vector_layer.geometry_type
            )

        self.setEnabled(enabled)
