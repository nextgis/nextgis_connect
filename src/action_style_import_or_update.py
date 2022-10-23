from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtCore import *

from qgis.core import QgsVectorLayer, QgsRasterLayer

from .ngw_api.core.ngw_vector_layer import NGWVectorLayer
from .ngw_api.core.ngw_raster_layer import NGWRasterLayer

from .ngw_api.qgis.compat_qgis import CompatQgisGeometryType


class ActionStyleImportUpdate(QAction):
    def __init__(self, text, parent=None):
        super(ActionStyleImportUpdate, self).__init__(parent)
        super(ActionStyleImportUpdate, self).setText(text)
        super(ActionStyleImportUpdate, self).setEnabled(False)

    def setEnabledByType(self, qgis_layer, ngw_vector_layer):
        if isinstance(qgis_layer, QgsRasterLayer) and isinstance(ngw_vector_layer, NGWRasterLayer):
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return

        if not isinstance(qgis_layer, QgsVectorLayer):
            super(ActionStyleImportUpdate, self).setEnabled(False)
            return
        if not isinstance(ngw_vector_layer, NGWVectorLayer):
            super(ActionStyleImportUpdate, self).setEnabled(False)
            return

        qgis_vector_layer_geom = qgis_layer.geometryType()
        ngw_vector_layer_geom = ngw_vector_layer.geom_type()

        if qgis_vector_layer_geom in [CompatQgisGeometryType.Point ] and ngw_vector_layer_geom in [
                                                                            NGWVectorLayer.POINT, NGWVectorLayer.MULTIPOINT,
                                                                            NGWVectorLayer.POINTZ, NGWVectorLayer.MULTIPOINTZ,
                                                                        ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return
        elif qgis_vector_layer_geom in [CompatQgisGeometryType.Line, ] and ngw_vector_layer_geom in [
                                                                            NGWVectorLayer.LINESTRING, NGWVectorLayer.MULTILINESTRING,
                                                                            NGWVectorLayer.LINESTRINGZ, NGWVectorLayer.MULTILINESTRINGZ,
                                                                        ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return
        elif qgis_vector_layer_geom in [CompatQgisGeometryType.Polygon, ] and ngw_vector_layer_geom in [
                                                                            NGWVectorLayer.POLYGON, NGWVectorLayer.MULTIPOLYGON,
                                                                            NGWVectorLayer.POLYGONZ, NGWVectorLayer.MULTIPOLYGONZ,
                                                                        ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return

        super(ActionStyleImportUpdate, self).setEnabled(False)
