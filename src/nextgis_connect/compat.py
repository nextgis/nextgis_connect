from qgis.core import Qgis, QgsMapLayerType, QgsWkbTypes

QGIS_3_30 = 33000


if Qgis.versionInt() >= QGIS_3_30:
    WkbType = Qgis.WkbType
    LayerType = Qgis.LayerType  # type: ignore
else:
    WkbType = QgsWkbTypes.Type  # type: ignore

    class LayerType(QgsMapLayerType):
        Vector = QgsMapLayerType.VectorLayer  # type: ignore
        Raster = QgsMapLayerType.RasterLayer  # type: ignore
        Plugin = QgsMapLayerType.PluginLayer  # type: ignore
        Mesh = QgsMapLayerType.MeshLayer  # type: ignore
        VectorTile = QgsMapLayerType.VectorTileLayer  # type: ignore
        Annotation = QgsMapLayerType.AnnotationLayer  # type: ignore
        PointCloud = QgsMapLayerType.PointCloudLayer  # type: ignore
