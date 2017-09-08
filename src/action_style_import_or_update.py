from PyQt4.QtGui import *
from PyQt4.QtCore import *

from qgis.core import QgsVectorLayer, QGis

from ngw_api.core.ngw_vector_layer import NGWVectorLayer


class ActionStyleImportUpdate(QAction):
    def __init__(self, parent=None):
        super(ActionStyleImportUpdate, self).__init__(parent)
        super(ActionStyleImportUpdate, self).setText(self.tr("Import/Update style")),
        super(ActionStyleImportUpdate, self).setEnabled(False)

    def setEnabled(self, qgis_vector_layer, ngw_vector_layer):
        if not isinstance(qgis_vector_layer, QgsVectorLayer):
            super(ActionStyleImportUpdate, self).setEnabled(False)
            return
        
        if not isinstance(ngw_vector_layer, NGWVectorLayer):
            super(ActionStyleImportUpdate, self).setEnabled(False)
            return


        qgis_vector_layer_geom = qgis_vector_layer.geometryType() 
        ngw_vector_layer_geom = ngw_vector_layer.geom_type()

        if qgis_vector_layer_geom in [QGis.Point ] and ngw_vector_layer_geom in [NGWVectorLayer.POINT, NGWVectorLayer.MULTIPOINT, ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return
        elif qgis_vector_layer_geom in [QGis.Line, ] and ngw_vector_layer_geom in [NGWVectorLayer.LINESTRING, NGWVectorLayer.MULTILINESTRING, ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return
        elif qgis_vector_layer_geom in [QGis.Polygon, ] and ngw_vector_layer_geom in [NGWVectorLayer.POLYGON, NGWVectorLayer.MULTIPOLYGON, ]:
            super(ActionStyleImportUpdate, self).setEnabled(True)
            return
        
        super(ActionStyleImportUpdate, self).setEnabled(False)
