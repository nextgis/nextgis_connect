from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsWkbTypes
from qgis.PyQt.QtWidgets import QAction

from .ngw_api.core.ngw_vector_layer import NGWVectorLayer
from .ngw_api.core.ngw_raster_layer import NGWRasterLayer


class ActionStyleImportUpdate(QAction):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        super().setText(text)
        super().setEnabled(False)

    def setEnabledByType(self, qgis_layer, ngw_vector_layer):
        if isinstance(qgis_layer, QgsRasterLayer) and isinstance(ngw_vector_layer, NGWRasterLayer):
            enabled = True
        elif isinstance(qgis_layer, QgsVectorLayer) and isinstance(ngw_vector_layer, NGWVectorLayer):
            qgis_vector_layer_geom = qgis_layer.geometryType()
            ngw_vector_layer_geom = ngw_vector_layer.geom_type()

            enabled = (
                qgis_vector_layer_geom == QgsWkbTypes.PointGeometry
                and ngw_vector_layer_geom in (
                    NGWVectorLayer.POINT, NGWVectorLayer.MULTIPOINT,
                    NGWVectorLayer.POINTZ, NGWVectorLayer.MULTIPOINTZ
            )) or (
                qgis_vector_layer_geom == QgsWkbTypes.LineGeometry
                and ngw_vector_layer_geom in (
                    NGWVectorLayer.LINESTRING, NGWVectorLayer.MULTILINESTRING,
                    NGWVectorLayer.LINESTRINGZ, NGWVectorLayer.MULTILINESTRINGZ,
            )) or (
                qgis_vector_layer_geom == QgsWkbTypes.PolygonGeometry
                and ngw_vector_layer_geom in (
                    NGWVectorLayer.POLYGON, NGWVectorLayer.MULTIPOLYGON,
                    NGWVectorLayer.POLYGONZ, NGWVectorLayer.MULTIPOLYGONZ,
            ))
        else:
            enabled = False

        super().setEnabled(enabled)
