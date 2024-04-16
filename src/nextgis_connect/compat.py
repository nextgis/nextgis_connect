from typing import TYPE_CHECKING

from qgis.core import Qgis, QgsMapLayerType, QgsWkbTypes

QGIS_3_30 = 33000


if Qgis.versionInt() >= QGIS_3_30 or TYPE_CHECKING:
    WkbType = Qgis.WkbType  # type: ignore
    LayerType = Qgis.LayerType  # type: ignore
    GeometryType = Qgis.GeometryType  # type: ignore
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

    GeometryType = QgsWkbTypes.GeometryType  # type: ignore

try:
    from packaging import version

    parse_version = version.parse
except Exception:
    import pkg_resources

    parse_version = pkg_resources.parse_version
