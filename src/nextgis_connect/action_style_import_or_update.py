from qgis.core import QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtWidgets import QAction

from nextgis_connect.ngw_api.core.ngw_raster_layer import NGWRasterLayer
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer


class ActionStyleImportUpdate(QAction):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(False)

    def setEnabledByType(self, qgis_layer, ngw_vector_layer):
        enabled = False

        if isinstance(qgis_layer, QgsRasterLayer) and isinstance(
            ngw_vector_layer, NGWRasterLayer
        ):
            enabled = True

        elif isinstance(qgis_layer, QgsVectorLayer) and isinstance(
            ngw_vector_layer, NGWVectorLayer
        ):
            enabled = (
                qgis_layer.geometryType() == ngw_vector_layer.geometry_type
            )

        self.setEnabled(enabled)
