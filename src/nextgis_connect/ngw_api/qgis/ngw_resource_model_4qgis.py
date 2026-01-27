"""
/***************************************************************************
 Common Plugins settings

 NextGIS WEB API
                             -------------------
        begin                : 2014-10-31
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, cast

from osgeo import ogr
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsLayerTree,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
    QgsMapLayer,
    QgsPluginLayer,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterProjector,
    QgsReferencedRectangle,
    QgsValueRelationFieldFormatter,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgisInterface, QgsFileWidget
from qgis.PyQt.QtCore import QCoreApplication, QVariant

from nextgis_connect.compat import (
    QGIS_3_42,
    FieldType,
    GeometryType,
    LayerType,
    WkbType,
)
from nextgis_connect.exceptions import ErrorCode, NgConnectError, NgwError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_base_map import (
    NGWBaseMap,
    NGWBaseMapExtSettings,
)
from nextgis_connect.ngw_api.core.ngw_feature import NGWFeature
from nextgis_connect.ngw_api.core.ngw_group_resource import NGWGroupResource
from nextgis_connect.ngw_api.core.ngw_qgis_style import (
    NGWQGISStyle,
    NGWQGISVectorStyle,
)
from nextgis_connect.ngw_api.core.ngw_raster_layer import NGWRasterLayer
from nextgis_connect.ngw_api.core.ngw_resource import NGWResource
from nextgis_connect.ngw_api.core.ngw_resource_creator import ResourceCreator
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.core.ngw_webmap import (
    NGWWebMap,
    NGWWebMapGroup,
    NGWWebMapLayer,
    NGWWebMapRoot,
)
from nextgis_connect.ngw_api.core.ngw_wms_connection import NGWWmsConnection
from nextgis_connect.ngw_api.core.ngw_wms_layer import NGWWmsLayer
from nextgis_connect.ngw_api.core.ngw_wms_service import NGWWmsService
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job import (
    NGWResourceModelJob,
)
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job_error import (
    JobError,
    JobWarning,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.settings import NgConnectSettings

from .compat_qgis import CompatQt


def getQgsMapLayerEPSG(qgs_map_layer):
    crs = qgs_map_layer.crs().authid()
    if crs.find("EPSG:") >= 0:
        return int(crs.split(":")[1])
    return None


def yOriginTopFromQgisTmsUrl(qgs_tms_url):
    return qgs_tms_url.find("{-y}")


def get_wkt(qgis_geometry: QgsGeometry):
    wkt = qgis_geometry.asWkt()

    # if qgis_geometry.wkbType() < 0: # TODO: why this check was made?
    wkb_type = qgis_geometry.wkbType()
    wkt_fixes = {
        WkbType.PointZ: ("PointZ", "Point Z"),
        WkbType.LineString25D: ("LineStringZ", "LineString Z"),
        WkbType.Polygon25D: ("PolygonZ", "Polygon Z"),
        WkbType.MultiPoint25D: ("MultiPointZ", "MultiPoint Z"),
        WkbType.MultiLineString25D: (
            "MultiLineStringZ",
            "MultiLineString Z",
        ),
        WkbType.MultiPolygon25D: (
            "MultiPolygonZ",
            "MultiPolygon Z",
        ),
    }

    if wkb_type in wkt_fixes:
        wkt = wkt.replace(*wkt_fixes[wkb_type])

    return wkt


def get_real_wkb_type(qgs_vector_layer: QgsVectorLayer) -> WkbType:
    if Qgis.versionInt() >= QGIS_3_42:
        return qgs_vector_layer.wkbType()

    MAPINFO_DRIVER = "MapInfo File"
    if qgs_vector_layer.storageType() != MAPINFO_DRIVER:
        return qgs_vector_layer.wkbType()

    layer_path = qgs_vector_layer.source().split("|")[0]
    driver: ogr.Driver = ogr.GetDriverByName(MAPINFO_DRIVER)
    datasource: Optional[ogr.DataSource] = driver.Open(layer_path)
    assert datasource is not None
    layer: Optional[ogr.Layer] = datasource.GetLayer()
    assert layer is not None

    wkb_type: int = layer.GetGeomType()
    wkb_type_2d: int = (wkb_type & ~ogr.wkb25DBit) % 1000

    is_multi = False
    has_z = False

    for feature in layer:
        geometry: Optional[ogr.Geometry] = feature.GetGeometryRef()
        if geometry is None:
            continue

        feature_wkb_type = geometry.GetGeometryType()
        feature_wkb_type_2d = (feature_wkb_type & ~ogr.wkb25DBit) % 1000
        is_multi = is_multi or wkb_type_2d + 3 == feature_wkb_type_2d
        has_z = has_z or bool(feature_wkb_type & ogr.wkb25DBit)

        if is_multi and has_z:
            break

    if is_multi:
        wkb_type += 3
    if has_z:
        wkb_type |= ogr.wkb25DBit

    return WkbType(wkb_type)


@dataclass(frozen=True)
class ValueRelation:
    layer_id: str
    key_field: str
    value_field: str
    filter_expression: str

    @staticmethod
    def from_config(config: Dict[str, Any]) -> "ValueRelation":
        filter_expression = config.get("FilterExpression")
        return ValueRelation(
            config["Layer"],
            config["Key"],
            config["Value"],
            filter_expression.strip() if filter_expression else "",
        )


class QGISResourceJob(NGWResourceModelJob):
    SUITABLE_LAYER = 0
    SUITABLE_LAYER_BAD_GEOMETRY = 1

    _value_relations: Set[ValueRelation]
    _lookup_tables_id: Dict[ValueRelation, int]
    _groups: Dict[QgsLayerTreeGroup, NGWGroupResource]

    def __init__(self, ngw_version=None):
        super().__init__()

        self.ngw_version = ngw_version

        self._value_relations = set()
        self._lookup_tables_id = {}
        self._groups = {}

    def _layer_status(self, layer_name, status):
        self.statusChanged.emit(f""""{layer_name}" - {status}""")

    def isSuitableLayer(self, qgs_map_layer: QgsVectorLayer):
        layer_type = qgs_map_layer.type()

        if layer_type == LayerType.Vector and qgs_map_layer.geometryType() in [
            GeometryType.Unknown,
            GeometryType.Null,
        ]:
            return self.SUITABLE_LAYER_BAD_GEOMETRY

        return self.SUITABLE_LAYER

    def importQGISMapLayer(self, qgs_map_layer, ngw_parent_resource):
        ngw_parent_resource.update()

        layer_type = qgs_map_layer.type()

        if layer_type == LayerType.Vector:
            return [
                self.importQgsVectorLayer(qgs_map_layer, ngw_parent_resource)
            ]

        if layer_type == LayerType.Raster:
            layer_data_provider = qgs_map_layer.dataProvider().name()

            if layer_data_provider == "wms":
                return self.importQgsWMSLayer(
                    qgs_map_layer, ngw_parent_resource
                )

            return [
                self.importQgsRasterLayer(qgs_map_layer, ngw_parent_resource)
            ]

        elif layer_type == LayerType.Plugin:
            return self.importQgsPluginLayer(
                qgs_map_layer, ngw_parent_resource
            )

        return []

    def importQgsPluginLayer(self, qgs_plugin_layer, ngw_group):
        # Look for QMS plugin layer
        if (
            qgs_plugin_layer.pluginLayerType() == "PyTiledLayer"
            and hasattr(qgs_plugin_layer, "layerDef")
            and hasattr(qgs_plugin_layer.layerDef, "serviceUrl")
        ):
            logger.debug(
                f'<b>↑ Uploading plugin layer</b> "{qgs_plugin_layer.name()}"'
            )

            new_layer_name = self.unique_resource_name(
                qgs_plugin_layer.name(), ngw_group
            )

            epsg = getattr(qgs_plugin_layer.layerDef, "epsg_crs_id", None)
            if epsg is None:
                epsg = getQgsMapLayerEPSG(qgs_plugin_layer)

            basemap_ext_settings = NGWBaseMapExtSettings(
                getattr(qgs_plugin_layer.layerDef, "serviceUrl", None),
                epsg,
                getattr(qgs_plugin_layer.layerDef, "zmin", None),
                getattr(qgs_plugin_layer.layerDef, "zmax", None),
                getattr(qgs_plugin_layer.layerDef, "yOriginTop", None),
            )

            ngw_basemap = NGWBaseMap.create_in_group(
                new_layer_name,
                ngw_group,
                qgs_plugin_layer.layerDef.serviceUrl,
                basemap_ext_settings,
            )

            return [ngw_basemap]

        return []

    def importQgsWMSLayer(self, qgs_wms_layer, ngw_group):
        logger.debug(f'<b>↑ Uploading WMS layer</b> "{qgs_wms_layer.name()}"')

        self._layer_status(
            qgs_wms_layer.name(),
            QgsApplication.translate(
                "QGISResourceJob", "create WMS connection"
            ),
        )

        layer_source = qgs_wms_layer.source()
        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            "wms"
        )
        parameters = provider_metadata.decodeUri(layer_source)

        if parameters.get("type", "") == "xyz":
            epsg = getQgsMapLayerEPSG(qgs_wms_layer)

            basemap_ext_settings = NGWBaseMapExtSettings(
                parameters.get("url"),
                epsg,
                parameters.get("zmin"),
                parameters.get("zmax"),
                yOriginTopFromQgisTmsUrl(parameters.get("url", "")),
            )

            ngw_basemap_name = self.unique_resource_name(
                qgs_wms_layer.name(), ngw_group
            )
            ngw_basemap = NGWBaseMap.create_in_group(
                ngw_basemap_name,
                ngw_group,
                parameters.get("url", ""),
                basemap_ext_settings,
            )
            return [ngw_basemap]
        else:
            ngw_wms_connection_name = self.unique_resource_name(
                qgs_wms_layer.name(), ngw_group
            )
            wms_connection = NGWWmsConnection.create_in_group(
                ngw_wms_connection_name,
                ngw_group,
                parameters.get("url", ""),
                parameters.get("version", "1.1.1"),
                (parameters.get("username"), parameters.get("password")),
            )

            self._layer_status(
                qgs_wms_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "creating WMS layer"
                ),
            )

            ngw_wms_layer_name = self.unique_resource_name(
                wms_connection.display_name + "_layer", ngw_group
            )

            layer_ids = parameters.get("layers", wms_connection.layers)
            if not isinstance(layer_ids, list):
                layer_ids = [layer_ids]

            wms_layer = NGWWmsLayer.create_in_group(
                ngw_wms_layer_name,
                ngw_group,
                wms_connection.resource_id,
                layer_ids,
                parameters.get("format"),
            )
            return [wms_connection, wms_layer]

    def importQgsRasterLayer(self, qgs_raster_layer, ngw_parent_resource):
        new_layer_name = self.unique_resource_name(
            qgs_raster_layer.name(), ngw_parent_resource
        )
        logger.debug(
            f'<b>↑ Uploading raster layer</b> "{qgs_raster_layer.name()}" (with the name "{new_layer_name}")'
        )

        def uploadFileCallback(total_size, readed_size, value=None):
            if value is None:
                value = round(readed_size * 100 / total_size)
            self._layer_status(
                qgs_raster_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(value),
            )

        def createLayerCallback():
            self._layer_status(
                qgs_raster_layer.name(),
                QgsApplication.translate("QGISResourceJob", "creating"),
            )

        is_converted, filepath = self.prepareImportRasterFile(qgs_raster_layer)

        ngw_raster_layer = ResourceCreator.create_raster_layer(
            ngw_parent_resource,
            filepath,
            new_layer_name,
            NgConnectSettings().upload_raster_as_cog,
            uploadFileCallback,
            createLayerCallback,
        )

        if is_converted:
            os.remove(filepath)

        return ngw_raster_layer

    def importQgsVectorLayer(
        self,
        qgs_vector_layer: QgsVectorLayer,
        ngw_parent_resource: NGWGroupResource,
    ) -> Optional[NGWVectorLayer]:
        new_layer_name = self.unique_resource_name(
            qgs_vector_layer.name(), ngw_parent_resource
        )
        logger.debug(
            f'<b>↑ Uploading vector layer</b> "{qgs_vector_layer.name()}" (with the name "{new_layer_name}")'
        )

        def uploadFileCallback(total_size, readed_size, value=None):
            self._layer_status(
                qgs_vector_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(
                    int(
                        readed_size * 100 / total_size
                        if value is None
                        else value
                    )
                ),
            )

        def createLayerCallback():
            self._layer_status(
                qgs_vector_layer.name(),
                QgsApplication.translate("QGISResourceJob", "creating"),
            )

        if (
            self.isSuitableLayer(qgs_vector_layer)
            == self.SUITABLE_LAYER_BAD_GEOMETRY
        ):
            self.errorOccurred.emit(
                JobError(
                    f"Vector layer '{qgs_vector_layer.name()}' has no suitable geometry"
                )
            )
            return None

        filepath, old_fid_name, tgt_qgs_layer = self.prepareImportVectorFile(
            qgs_vector_layer
        )
        if filepath is None:
            self.errorOccurred.emit(
                JobError(
                    f"Can't prepare layer '{qgs_vector_layer.name()}'. Skipped!"
                )
            )
            return None

        ngw_vector_layer = ResourceCreator.create_vector_layer(
            ngw_parent_resource,
            filepath,
            new_layer_name,
            old_fid_name,
            uploadFileCallback,
            createLayerCallback,
        )

        fields_aliases: Dict[str, Dict[str, str]] = {}
        fields_lookup_table: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for field in qgs_vector_layer.fields():
            alias = field.alias()
            lookup_table = None
            editor_widget_setup = field.editorWidgetSetup()
            if editor_widget_setup.type() == "ValueRelation":
                config = editor_widget_setup.config().copy()
                related_layer = QgsValueRelationFieldFormatter.resolveLayer(
                    config, QgsProject.instance()
                )
                if related_layer is None:
                    continue

                config["Layer"] = related_layer.id()
                value_relation = ValueRelation.from_config(config)
                lookup_table = self._lookup_tables_id[value_relation]

            if len(alias) == 0 and lookup_table is None:
                continue

            field_name = field.name()

            if len(alias) > 0:
                fields_aliases[field_name] = dict(display_name=alias)
            if lookup_table is not None:
                fields_lookup_table[field_name] = dict(
                    lookup_table=dict(id=lookup_table)
                )

        if len(fields_aliases) > 0:
            self._layer_status(
                qgs_vector_layer.name(),
                QgsApplication.translate("QGISResourceJob", "adding aliases"),
            )

            try:
                ngw_vector_layer.update_fields_params(fields_aliases)
            except Exception as error:
                self.warningOccurred.emit(error)

        if len(fields_lookup_table) > 0:
            self._layer_status(
                qgs_vector_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "adding lookup tables"
                ),
            )
            try:
                ngw_vector_layer.update_fields_params(fields_lookup_table)
            except Exception as error:
                self.warningOccurred.emit(error)

        self._layer_status(
            qgs_vector_layer.name(),
            QgsApplication.translate("QGISResourceJob", "finishing"),
        )
        os.remove(filepath)

        return ngw_vector_layer

    def prepareImportVectorFile(self, qgs_vector_layer):
        self._layer_status(
            qgs_vector_layer.name(),
            QgsApplication.translate("QGISResourceJob", "preparing"),
        )

        gpkg_path, old_fid_name = self.prepareAsGPKG(qgs_vector_layer)
        return gpkg_path, old_fid_name, qgs_vector_layer

    def prepareImportRasterFile(
        self, qgs_raster_layer: QgsRasterLayer
    ) -> Tuple[bool, str]:
        source = qgs_raster_layer.source()
        source_crs = qgs_raster_layer.crs()
        if (
            Path(source).exists()
            and Path(source).suffix in (".tif", ".tiff")
            and source_crs.postgisSrid() == 3857
        ):
            return False, source

        logger.debug(
            f"<b>Transform</b> raster layer {qgs_raster_layer.name()}"
        )

        self._layer_status(
            qgs_raster_layer.name(),
            QgsApplication.translate("QGISResourceJob", "preparing"),
        )

        if not source_crs.isValid():
            raise NgwError(
                QgsApplication.translate(
                    "QGISResourceJob", "Raster layer has no spatial reference."
                ),
                code=ErrorCode.SpatialReferenceError,
            )

        output_path = tempfile.mktemp(suffix=".tif")

        pipe = QgsRasterPipe()
        if not pipe.set(qgs_raster_layer.dataProvider().clone()):
            raise RuntimeError

        extent = qgs_raster_layer.extent()

        output_crs = QgsCoordinateReferenceSystem.fromEpsgId(3857)
        transform_context = QgsProject.instance().transformContext()

        if source_crs != output_crs:
            projector = QgsRasterProjector()
            projector.setCrs(source_crs, output_crs, transform_context)
            if not pipe.insert(1, projector):
                raise NgwError(
                    "Cannot set pipe projector",
                    code=ErrorCode.SpatialReferenceError,
                )

            transform = QgsCoordinateTransform(
                source_crs, output_crs, QgsProject.instance()
            )
            transform.setBallparkTransformsAreAppropriate(True)
            extent = transform.transformBoundingBox(extent)

        raster_writer = QgsRasterFileWriter(output_path)
        raster_writer.setOutputFormat("GTiff")

        raster_writer.writeRaster(
            pipe,
            qgs_raster_layer.dataProvider().xSize(),
            qgs_raster_layer.dataProvider().ySize(),
            extent,
            output_crs,
            transform_context,
        )

        return True, output_path

    def checkGeometry(self, qgs_vector_layer):
        has_simple_geometries = False
        has_multipart_geometries = False

        fids_with_not_valid_geom = []

        features_count = qgs_vector_layer.featureCount()
        progress = 0
        for features_counter, feature in enumerate(
            qgs_vector_layer.getFeatures(), start=1
        ):
            v = round(features_counter * 100 / features_count)
            if progress < v:
                progress = v
                self._layer_status(
                    qgs_vector_layer.name(),
                    QgsApplication.translate(
                        "QGISResourceJob", "checking geometry ({}%)"
                    ).format(progress),
                )

            fid, geom = feature.geometry(), feature.id()

            if geom is None:
                fids_with_not_valid_geom.append(fid)
                continue

            # Fix one point line. Method isGeosValid return true for same geometry.
            if geom.type() == GeometryType.Line:
                if geom.isMultipart():
                    for polyline in geom.asMultiPolyline():
                        if len(polyline) < 2:
                            fids_with_not_valid_geom.append(fid)
                            break
                elif len(geom.asPolyline()) < 2:
                    fids_with_not_valid_geom.append(fid)

            elif geom.type() == GeometryType.Polygon:
                if geom.isMultipart():
                    for polygon in geom.asMultiPolygon():
                        for polyline in polygon:
                            if len(polyline) < 4:
                                logger.warning(
                                    f"Feature {fid} has not valid geometry (less then 4 points)"
                                )
                                fids_with_not_valid_geom.append(fid)
                                break
                else:
                    for polyline in geom.asPolygon():
                        if len(polyline) < 4:
                            logger.warning(
                                f"Feature {fid} has not valid geometry (less then 4 points)"
                            )
                            fids_with_not_valid_geom.append(fid)
                            break

            if geom.isMultipart():
                has_multipart_geometries = True
            else:
                has_simple_geometries = True

            # Do not validate geometries (rely on NGW):
            # errors = feature.geometry().validateGeometry()
            # if len(errors) != 0:
            #     log("Feature %s has invalid geometry: %s" % (str(feature.id()), ', '.join(err.what() for err in errors)))
            #     fids_with_not_valid_geom.append(feature.id())

        return (
            has_multipart_geometries and has_simple_geometries,
            fids_with_not_valid_geom,
        )

    def createLayer4Upload(
        self,
        qgs_vector_layer_src,
        fids_with_notvalid_geom,
        has_mixed_geoms,
    ):
        geometry_type = self.determineGeometry4MemoryLayer(
            qgs_vector_layer_src, has_mixed_geoms
        )

        import_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
        qgs_vector_layer_dst = QgsVectorLayer(
            f"{geometry_type}?crs={import_crs.authid()}",
            "temp",
            "memory",
        )

        qgs_vector_layer_dst.startEditing()

        for field in qgs_vector_layer_src.fields():
            qgs_vector_layer_dst.addAttribute(field)

        qgs_vector_layer_dst.commitChanges()
        qgs_vector_layer_dst.startEditing()
        features_count = qgs_vector_layer_src.featureCount()

        progress = 0
        for features_counter, feature in enumerate(
            qgs_vector_layer_src.getFeatures(), start=1
        ):
            if feature.id() in fids_with_notvalid_geom:
                continue

            # Additional checks for geom correctness.
            # TODO: this was done in self.checkGeometry() but we've remove using of this method. Maybe return using this method back.
            if feature.geometry().isNull():
                logger.warning(f"Skip feature {feature.id()}: empty geometry")
                continue

            new_geometry: QgsGeometry = feature.geometry()
            new_geometry.get().convertTo(
                QgsWkbTypes.dropZ(new_geometry.wkbType())
            )
            new_geometry.transform(
                QgsCoordinateTransform(
                    qgs_vector_layer_src.crs(),
                    import_crs,
                    QgsProject.instance(),
                )
            )
            if has_mixed_geoms:
                new_geometry.convertToMultiType()

            # Add field values one by one. While in QGIS 2 we can just addFeature() regardless of field names, in QGIS 3 we must strictly
            # define field names where the values are copied to.
            new_feature = QgsFeature(qgs_vector_layer_dst.fields())
            new_feature.setGeometry(new_geometry)
            for field in qgs_vector_layer_src.fields():
                fname = field.name()
                fval = feature[field.name()]
                new_feature.setAttribute(fname, fval)
            qgs_vector_layer_dst.addFeature(new_feature)

            v = round(features_counter * 100 / features_count)
            if progress < v:
                progress = v
                self._layer_status(
                    qgs_vector_layer_src.name(),
                    QgsApplication.translate(
                        "QGISResourceJob", "preparing layer ({}%)"
                    ).format(progress),
                )

        qgs_vector_layer_dst.commitChanges()

        if len(fids_with_notvalid_geom) != 0:
            msg = QCoreApplication.translate(
                "QGISResourceJob",
                "We've excluded features with id {0} for layer '{1}'. Reason: invalid geometry.",
            ).format(
                "["
                + ", ".join(str(fid) for fid in fids_with_notvalid_geom)
                + "]",
                qgs_vector_layer_src.name(),
            )

            self.warningOccurred.emit(JobWarning(msg))

        return qgs_vector_layer_dst

    def determineGeometry4MemoryLayer(self, qgs_vector_layer, has_mixed_geoms):
        geometry_type = None
        if qgs_vector_layer.geometryType() == GeometryType.Point:
            geometry_type = "point"
        elif qgs_vector_layer.geometryType() == GeometryType.Line:
            geometry_type = "linestring"
        elif qgs_vector_layer.geometryType() == GeometryType.Polygon:
            geometry_type = "polygon"
        else:
            raise NgConnectError("Unsupported geometry")

        # if has_multipart_geometries:
        if has_mixed_geoms:
            geometry_type = "multi" + geometry_type
        else:
            for feature in qgs_vector_layer.getFeatures():
                g = feature.geometry()
                if g.isNull():
                    continue  # cannot detect geom type because of empty geom
                if g.isMultipart():
                    geometry_type = "multi" + geometry_type
                break

        return geometry_type

    def prepareAsGPKG(
        self, qgs_vector_layer: QgsVectorLayer
    ) -> Tuple[str, Optional[str]]:
        tmp_gpkg_path = tempfile.mktemp(".gpkg")

        source_srs = qgs_vector_layer.sourceCrs()
        destination_srs = QgsCoordinateReferenceSystem.fromEpsgId(3857)

        project = QgsProject.instance()
        assert project is not None

        old_fid_name = None
        pk_attributes = qgs_vector_layer.primaryKeyAttributes()
        if len(pk_attributes) == 1:
            pk_field = qgs_vector_layer.fields().at(pk_attributes[0])
            if pk_field.type() in (
                NgwDataType.INTEGER.qt_value,
                NgwDataType.BIGINT.qt_value,
            ):
                old_fid_name = pk_field.name()

        fid_name = "0xFEEDC0DE"

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = qgs_vector_layer.name()
        options.fileEncoding = "UTF-8"
        options.layerOptions = [
            *QgsVectorFileWriter.defaultDatasetOptions("GPKG"),
            f"FID={fid_name}",
            "SPATIAL_INDEX=NO",
        ]

        fields = QgsFields()
        fields.append(QgsField(fid_name, FieldType.LongLong))
        for field in qgs_vector_layer.fields().toList():
            fields.append(field)

        writer = QgsVectorFileWriter.create(
            fileName=tmp_gpkg_path,
            fields=fields,
            geometryType=get_real_wkb_type(qgs_vector_layer),
            transformContext=project.transformContext(),
            srs=destination_srs,
            options=options,
        )
        assert writer is not None

        transform = None
        if source_srs != destination_srs:
            transform = QgsCoordinateTransform(
                source_srs, destination_srs, QgsProject.instance()
            )

        for feature in cast(
            Iterable[QgsFeature], qgs_vector_layer.getFeatures()
        ):
            try:
                target_feature = QgsFeature(fields)
                geometry = feature.geometry()
                if transform is not None:
                    geometry.transform(transform)
                target_feature.setGeometry(geometry)

                target_feature.setAttributes([None, *feature.attributes()])

                writer.addFeature(target_feature)
            except Exception:
                # fmt: off
                self.warningOccurred.emit(
                    JobWarning(
                        QgsApplication.translate(
                            "QGISResourceJob",
                            "Feature {} haven't been added."
                            " Please check geometry"
                        ).format(feature.id())
                    )
                )
                # fmt: on
                continue

        del writer  # save changes

        return tmp_gpkg_path, old_fid_name

    def upload_qml_file(
        self, ngw_layer_resource, qml_filename, style_name=None
    ):
        def uploadFileCallback(total_size, readed_size):
            self.statusChanged.emit(
                QgsApplication.translate(
                    "QGISResourceJob", 'Style for "{}"'
                ).format(ngw_layer_resource.display_name)
                + " - "
                + QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(int(readed_size * 100 / total_size))
            )

        return ngw_layer_resource.create_qml_style(
            qml_filename, uploadFileCallback, style_name
        )

    def addStyle(
        self, ngw_layer_resource, qgs_map_layer, style_name
    ) -> Optional[NGWQGISStyle]:
        if not isinstance(qgs_map_layer, (QgsVectorLayer, QgsRasterLayer)):
            return None

        style_manager = qgs_map_layer.styleManager()
        assert style_manager is not None

        temp_filename = tempfile.mktemp(suffix=".qml")
        with open(temp_filename, "w") as qml_file:
            qml_data = style_manager.style(style_name).xmlData()
            qml_file.write(qml_data)

        if style_manager.isDefault(style_name):
            style_name = None

        ngw_resource = self.upload_qml_file(
            ngw_layer_resource, temp_filename, style_name
        )
        os.remove(temp_filename)
        return ngw_resource

    def updateStyle(self, qgs_map_layer, ngw_layer_resource):
        if not isinstance(qgs_map_layer, (QgsVectorLayer, QgsRasterLayer)):
            return

        style_manager = qgs_map_layer.styleManager()
        assert style_manager is not None

        current_style = style_manager.currentStyle()

        temp_filename = tempfile.mktemp(suffix=".qml")
        with open(temp_filename, "w") as qml_file:
            qml_data = style_manager.style(current_style).xmlData()
            qml_file.write(qml_data)

        self.updateQMLStyle(temp_filename, ngw_layer_resource)

        os.remove(temp_filename)

    def updateQMLStyle(self, qml, ngw_layer_resource):
        def uploadFileCallback(total_size, readed_size):
            self.statusChanged.emit(
                QgsApplication.translate(
                    "QGISResourceJob", 'Style for "{}"'
                ).format(ngw_layer_resource.display_name)
                + " - "
                + QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(int(readed_size * 100 / total_size))
            )

        ngw_layer_resource.update_qml(qml, uploadFileCallback)

    def getQMLDefaultStyle(self):
        gtype = self.ngw_layer._json[self.ngw_layer.type_id]["geometry_type"]

        if gtype in ["LINESTRING", "MULTILINESTRING"]:
            return os.path.join(
                os.path.dirname(__file__), "qgis_styles", "line_style.qml"
            )
        if gtype in ["POINT", "MULTIPOINT"]:
            return os.path.join(
                os.path.dirname(__file__), "qgis_styles", "point_style.qml"
            )
        if gtype in ["POLYGON", "MULTIPOLYGON"]:
            return os.path.join(
                os.path.dirname(__file__), "qgis_styles", "polygon_style.qml"
            )

        return None

    def _defStyleForVector(self, ngw_layer) -> Optional[NGWResource]:
        qml = self.getQMLDefaultStyle()

        if qml is None:
            self.errorOccurred.emit(
                "There is no defalut style description for create new style."
            )
            return None

        return self.upload_qml_file(ngw_layer, qml)

    def _defStyleForRaster(self, ngw_layer):
        return ngw_layer.create_style()

    def importAttachments(
        self, qgs_vector_layer: QgsVectorLayer, ngw_resource: NGWVectorLayer
    ):
        """Checks if the layer attributes have widgets
        of type "Attachment" and "Storage Type"
        matches "existing file" and then tries
        to import the attachment
        """

        def uploadFileCallback(total_size, readed_size, value=None):
            self._layer_status(
                full_path,
                QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(
                    int(
                        readed_size * 100 / total_size
                        if value is None
                        else value
                    )
                ),
            )

        if ngw_resource.type_id != NGWVectorLayer.type_id:
            return

        ngw_ftrs = []
        for attrInx in qgs_vector_layer.attributeList():
            editor_widget = qgs_vector_layer.editorWidgetSetup(attrInx)
            if editor_widget.type() != "ExternalResource":
                continue

            editor_config = editor_widget.config()

            # storagetype can be str or null qvariant
            is_local = not editor_config["StorageType"]
            GET_FILE_MODE = QgsFileWidget.StorageMode.GetFile
            is_file = editor_config["StorageMode"] == GET_FILE_MODE
            if is_local and is_file:
                root_dir = ""

                if (
                    editor_config["RelativeStorage"]
                    == QgsFileWidget.RelativeStorage.RelativeProject
                ):
                    root_dir = QgsProject.instance().homePath()
                if (
                    editor_config["RelativeStorage"]
                    == QgsFileWidget.RelativeStorage.RelativeDefaultPath
                ):
                    root_dir = editor_config["DefaultRoot"]

                root_dir = (
                    Path(root_dir)
                    if root_dir is not None
                    and not isinstance(root_dir, QVariant)
                    else Path()
                )

                for finx, ftr in enumerate(
                    cast(Iterable[QgsFeature], qgs_vector_layer.getFeatures())
                ):
                    file_path = ftr.attributes()[attrInx]
                    if not isinstance(file_path, str):
                        continue

                    full_path = root_dir / file_path
                    if not full_path.is_file():
                        continue

                    if len(ngw_ftrs) == 0:
                        # Lazy loading
                        ngw_ftrs = ngw_resource.get_features()

                    logger.debug(f"Load file: {full_path}")
                    uploaded_file_info = ngw_ftrs[
                        finx
                    ].ngw_vector_layer.res_factory.connection.upload_file(
                        str(full_path), uploadFileCallback
                    )
                    logger.debug(f"Uploaded file info: {uploaded_file_info}")
                    ngw_ftrs[finx].link_attachment(
                        full_path.name, uploaded_file_info
                    )

    def overwriteQGISMapLayer(self, qgs_map_layer, ngw_layer_resource):
        layer_type = qgs_map_layer.type()

        if layer_type == LayerType.Vector:
            return self.overwriteQgsVectorLayer(
                qgs_map_layer, ngw_layer_resource
            )

        return None

    def overwriteQgsVectorLayer(self, qgs_map_layer, ngw_layer_resource):
        block_size = 10
        total_count = qgs_map_layer.featureCount()

        self._layer_status(
            ngw_layer_resource.display_name,
            QgsApplication.translate(
                "QGISResourceJob", "removing all features"
            ),
        )
        ngw_layer_resource.delete_all_features()

        features_counter = 0
        progress = 0
        for features in self.getFeaturesPart(
            qgs_map_layer, ngw_layer_resource, block_size
        ):
            ngw_layer_resource.patch_features(features)

            features_counter += len(features)
            v = int(features_counter * 100 / total_count)
            if progress < v:
                progress = v
                self._layer_status(
                    ngw_layer_resource.display_name,
                    QgsApplication.translate(
                        "QGISResourceJob", "adding features ({}%)"
                    ).format(progress),
                )

    def getFeaturesPart(self, qgs_map_layer, ngw_layer_resource, pack_size):
        ngw_features = []
        for qgsFeature in qgs_map_layer.getFeatures():
            ngw_features.append(
                NGWFeature(
                    self.createNGWFeatureDictFromQGSFeature(
                        ngw_layer_resource, qgsFeature, qgs_map_layer
                    ),
                    ngw_layer_resource,
                )
            )

            if len(ngw_features) == pack_size:
                yield ngw_features
                ngw_features = []

        if len(ngw_features) > 0:
            yield ngw_features

    def createNGWFeatureDictFromQGSFeature(
        self, ngw_layer_resource, qgs_feature, qgs_map_layer
    ):
        feature_dict = {}

        # id need only for update not for create
        # feature_dict["id"] = qgs_feature.id() + 1 # Fix NGW behavior
        g = qgs_feature.geometry()
        g.transform(
            QgsCoordinateTransform(
                qgs_map_layer.crs(),
                QgsCoordinateReferenceSystem.fromEpsgId(
                    ngw_layer_resource.srs(),
                ),
                QgsProject.instance(),
            )
        )
        if ngw_layer_resource.is_geom_multy():
            g.convertToMultiType()
        feature_dict["geom"] = get_wkt(g)

        attributes = {}
        for qgsField in qgs_feature.fields().toList():
            value = qgs_feature.attribute(qgsField.name())
            attributes[qgsField.name()] = CompatQt.get_clean_python_value(
                value
            )

        feature_dict["fields"] = (
            ngw_layer_resource.construct_ngw_feature_as_json(attributes)
        )

        return feature_dict


class QGISResourcesUploader(QGISResourceJob):
    def __init__(
        self,
        qgs_layer_tree_nodes: List[QgsLayerTreeNode],
        parent_group_resource: NGWGroupResource,
        iface: QgisInterface,
        ngw_version=None,
    ):
        super().__init__(ngw_version)
        self.qgs_layer_tree_nodes = qgs_layer_tree_nodes
        self.parent_group_resource = parent_group_resource
        self.iface = iface

    def _do(self):
        self._find_lookup_tables()
        self._check_quote()

        self._add_group_tree()
        self._add_lookup_tables()

        ngw_webmap_root_group = NGWWebMapRoot()
        ngw_webmap_basemaps = []
        self.process_one_level_of_layers_tree(
            self.qgs_layer_tree_nodes,
            self.parent_group_resource,
            ngw_webmap_root_group,
            ngw_webmap_basemaps,
        )

        # The group was attached resources,  therefore, it is necessary to upgrade for get children flag
        self.parent_group_resource.update()

    def _check_quote(self, add_map: bool = False) -> None:
        def resource_type_for_layer(node: QgsLayerTreeNode) -> Optional[str]:
            layer = cast(QgsLayerTreeLayer, node).layer()
            if isinstance(layer, QgsVectorLayer):
                return "vector_layer"
            if isinstance(layer, QgsRasterLayer):
                data_provider = layer.dataProvider().name()  # type: ignore
                if data_provider == "wms":
                    registry = QgsProviderRegistry.instance()
                    provider_metadata = registry.providerMetadata("wms")
                    parameters = provider_metadata.decodeUri(layer.source())
                    return (
                        "basemap_layer"
                        if parameters.get("type") == "xyz"
                        else "wmsclient_layer"
                    )
                return "raster_layer"
            if isinstance(layer, QgsPluginLayer):
                return "basemap_layer"
            return None

        def resource_type_for_node(
            node: QgsLayerTreeNode,
        ) -> List[Optional[str]]:
            if node.nodeType() == QgsLayerTreeNode.NodeType.NodeLayer:
                return [resource_type_for_layer(node)]

            layers_node: List[Optional[str]] = []
            for child in node.children():
                if child.nodeType() == QgsLayerTreeNode.NodeType.NodeLayer:
                    layers_node.append(resource_type_for_layer(child))
                else:
                    layers_node.extend(resource_type_for_node(child))
            return layers_node

        resources_type = []
        for node in self.qgs_layer_tree_nodes:
            resources_type.extend(resource_type_for_node(node))

        counter = Counter(resources_type)
        if len(self._value_relations) > 0:
            counter["lookup_table"] = len(self._value_relations)
        if add_map:
            counter["webmap"] = 1
        del counter[None]

        try:
            self.parent_group_resource.res_factory.connection.post(
                "/api/component/resource/check_quota", counter
            )
        except NgwError as error:
            if error.code == ErrorCode.NotFound:
                return

            raise NgwError(
                code=ErrorCode.QuotaExceeded,
                detail=error.log_message,
            ) from None

        except Exception as error:
            raise NgConnectError from error

    def _find_lookup_tables(self) -> None:
        def collect_value_relations(layer_node: QgsLayerTreeNode) -> None:
            layer_node = cast(QgsLayerTreeLayer, layer_node)
            layer = layer_node.layer()
            assert layer is not None
            if not isinstance(layer, QgsVectorLayer):
                return

            for attribute_index in layer.attributeList():
                editor_widget_setup = layer.editorWidgetSetup(attribute_index)
                if editor_widget_setup.type() != "ValueRelation":
                    continue

                config = editor_widget_setup.config().copy()
                related_layer = QgsValueRelationFieldFormatter.resolveLayer(
                    config, QgsProject.instance()
                )

                if related_layer is None:
                    related_layer_name = config.get("LayerName", "")
                    logger.warning(
                        f"Missing layer form dependency: layer '{layer.name()}' requires layer '{related_layer_name}'"
                    )
                    continue

                config["Layer"] = related_layer.id()
                self._value_relations.add(ValueRelation.from_config(config))

        for node in self.qgs_layer_tree_nodes:
            if isinstance(node, QgsLayerTreeGroup):
                for layer_node in node.findLayers():
                    collect_value_relations(layer_node)
            elif isinstance(node, QgsLayerTreeLayer):
                collect_value_relations(node)

    def process_one_level_of_layers_tree(
        self,
        qgs_layer_tree_nodes,
        ngw_resource_group,
        ngw_webmap_item,
        ngw_webmap_basemaps,
    ):
        for node in qgs_layer_tree_nodes:
            if isinstance(node, QgsLayerTreeLayer):
                if self.isSuitableLayer(node.layer()) != self.SUITABLE_LAYER:
                    continue
                layer = node.layer()
                assert layer is not None
                self.add_layer(
                    ngw_resource_group,
                    node,
                    ngw_webmap_item,
                    ngw_webmap_basemaps,
                )
            else:
                self.add_group(
                    ngw_resource_group,
                    node,
                    ngw_webmap_item,
                    ngw_webmap_basemaps,
                )

    def _add_group_tree(self) -> None:
        self.statusChanged.emit(
            QgsApplication.translate(
                "QGISResourceJob", "A group tree is being created"
            )
        )
        for node in self.qgs_layer_tree_nodes:
            if not QgsLayerTree.isGroup(node):
                continue
            self.__add_group_level(
                self.parent_group_resource, cast(QgsLayerTreeGroup, node)
            )

    def __add_group_level(
        self,
        parent_group_resource: NGWGroupResource,
        group_node: QgsLayerTreeGroup,
    ) -> None:
        group_name = self.unique_resource_name(
            group_node.name(), parent_group_resource
        )

        child_group_resource = ResourceCreator.create_group(
            parent_group_resource, group_name
        )
        self.putAddedResourceToResult(child_group_resource)
        self._groups[group_node] = child_group_resource

        for node in group_node.children():
            if not QgsLayerTree.isGroup(node):
                continue
            self.__add_group_level(
                child_group_resource, cast(QgsLayerTreeGroup, node)
            )

    def _add_lookup_tables(self) -> None:
        def extract_items(
            layer_node: QgsLayerTreeLayer, value_relation: ValueRelation
        ) -> Dict[str, str]:
            layer = layer_node.layer()
            assert layer is not None
            layer = cast(QgsVectorLayer, layer)
            request = QgsFeatureRequest()
            if len(value_relation.filter_expression) > 0:
                request.setFilterExpression(value_relation.filter_expression)
            result: Dict[str, str] = {}
            for feature in layer.getFeatures(request):  # type: ignore
                key = feature[value_relation.key_field]
                if key is None or isinstance(key, QVariant):
                    continue
                key = str(key)
                value = str(feature[value_relation.value_field])
                result[key] = value
            return result

        project = QgsProject.instance()
        assert project is not None
        root = project.layerTreeRoot()
        assert root is not None
        for value_relation in self._value_relations:
            layer_node = root.findLayer(value_relation.layer_id)
            assert layer_node is not None

            parent_node = cast(
                Optional[QgsLayerTreeGroup], layer_node.parent()
            )
            parent_group_resource = self._groups.get(
                parent_node,
                self.parent_group_resource,  # type: ignore
            )

            lookup_table_name = self.unique_resource_name(
                layer_node.name(), parent_group_resource
            )
            lookup_table = ResourceCreator.create_lookup_table(
                lookup_table_name,
                extract_items(layer_node, value_relation),
                parent_group_resource,
            )
            self._lookup_tables_id[value_relation] = lookup_table.resource_id
            self.putAddedResourceToResult(lookup_table)

    def add_layer(
        self,
        ngw_resource_group,
        layer_tree_item: QgsLayerTreeLayer,
        ngw_webmap_item,
        ngw_webmap_basemaps,
    ):
        try:
            ngw_resources = self.importQGISMapLayer(
                layer_tree_item.layer(), ngw_resource_group
            )
        except Exception as e:
            logger.exception("Exception during adding layer")

            has_several_elements = len(self.qgs_layer_tree_nodes) > 1
            group_selected = len(
                self.qgs_layer_tree_nodes
            ) == 1 and isinstance(
                self.qgs_layer_tree_nodes[0], QgsLayerTreeGroup
            )

            if has_several_elements or group_selected:
                self.warningOccurred.emit(
                    JobError(
                        f'Uploading layer "{layer_tree_item.layer().name()}" failed. Skipped.',
                        e,
                    )
                )
                return
            else:
                raise e

        for ngw_resource in ngw_resources:
            self.putAddedResourceToResult(ngw_resource)

            if ngw_resource.type_id in [
                NGWVectorLayer.type_id,
                NGWRasterLayer.type_id,
            ]:
                qgs_map_layer = layer_tree_item.layer()
                assert qgs_map_layer is not None
                style_manager = qgs_map_layer.styleManager()
                assert style_manager is not None
                current_style = style_manager.currentStyle()

                for style_name in style_manager.styles():
                    ngw_style = self.addStyle(
                        ngw_resource, qgs_map_layer, style_name
                    )
                    if ngw_style is None:
                        continue

                    self.putAddedResourceToResult(ngw_style)

                    if style_name == current_style:
                        ngw_webmap_item.appendChild(
                            NGWWebMapLayer(
                                ngw_style.resource_id,
                                layer_tree_item.layer().name(),
                                is_visible=layer_tree_item.itemVisibilityChecked(),
                                transparency=None,
                                legend=layer_tree_item.isExpanded(),
                            )
                        )

                # Add style to layer, therefore, it is necessary to upgrade layer resource for get children flag
                ngw_resource.update()

                # check and import attachments
                if ngw_resource.type_id == NGWVectorLayer.type_id:
                    self.importAttachments(
                        layer_tree_item.layer(), ngw_resource
                    )

            elif ngw_resource.type_id == NGWWmsLayer.type_id:
                transparency = None
                if layer_tree_item.layer().type() == LayerType.Raster:
                    transparency = (
                        100
                        - 100 * layer_tree_item.layer().renderer().opacity()
                    )

                ngw_webmap_item.appendChild(
                    NGWWebMapLayer(
                        ngw_resource.resource_id,
                        ngw_resource.display_name,
                        is_visible=layer_tree_item.itemVisibilityChecked(),
                        transparency=transparency,
                        legend=layer_tree_item.isExpanded(),
                    )
                )

            elif ngw_resource.type_id == NGWBaseMap.type_id:
                ngw_webmap_basemaps.append(ngw_resource)

    def update_layer(self, qgsLayerTreeItem, ngwVectorLayer):
        self.overwriteQGISMapLayer(qgsLayerTreeItem.layer(), ngwVectorLayer)
        self.putEditedResourceToResult(ngwVectorLayer)

        for child in ngwVectorLayer.get_children():
            if isinstance(child, NGWQGISVectorStyle):
                self.updateStyle(qgsLayerTreeItem.layer(), child)

    def add_group(
        self,
        ngw_resource_group,
        qgsLayerTreeGroup: QgsLayerTreeGroup,
        ngw_webmap_item,
        ngw_webmap_basemaps,
    ) -> None:
        ngw_resource_child_group = self._groups[qgsLayerTreeGroup]

        ngw_webmap_child_group = NGWWebMapGroup(
            ngw_resource_child_group.display_name,
            qgsLayerTreeGroup.isExpanded(),
            qgsLayerTreeGroup.isMutuallyExclusive(),
        )
        ngw_webmap_item.appendChild(ngw_webmap_child_group)

        self.process_one_level_of_layers_tree(
            qgsLayerTreeGroup.children(),
            ngw_resource_child_group,
            ngw_webmap_child_group,
            ngw_webmap_basemaps,
        )

        ngw_resource_child_group.update()  # in order to update group items: if they have children items they should become expandable


class QGISProjectUploader(QGISResourcesUploader):
    """
    if new_group_name is None  -- Update mode

    Update:
    1. Add new
    2. Rewrite current (vector only)
    3. Remove
    4. Update map

    Update Ext (future):
    Calculate mapping of qgislayer to ngw resource
    Show map for user to edit anf cofirm it
    """

    def __init__(
        self,
        new_group_name: str,
        parent_group_resource: NGWGroupResource,
        iface: QgisInterface,
        ngw_version,
    ) -> None:
        qgs_layer_tree_nodes = QgsProject.instance().layerTreeRoot().children()
        super().__init__(
            qgs_layer_tree_nodes, parent_group_resource, iface, ngw_version
        )
        self.new_group_name = new_group_name

    def _do(self):
        self._find_lookup_tables()
        self._check_quote(add_map=True)

        new_group_name = self.unique_resource_name(
            self.new_group_name, self.parent_group_resource
        )
        ngw_group_resource = ResourceCreator.create_group(
            self.parent_group_resource, new_group_name
        )
        self.putAddedResourceToResult(ngw_group_resource)
        self.parent_group_resource = ngw_group_resource

        self._add_group_tree()
        self._add_lookup_tables()

        ngw_webmap_root_group = NGWWebMapRoot()
        ngw_webmap_basemaps = []
        self.process_one_level_of_layers_tree(
            self.qgs_layer_tree_nodes,
            ngw_group_resource,
            ngw_webmap_root_group,
            ngw_webmap_basemaps,
        )

        ngw_webmap = self.create_webmap(
            ngw_group_resource,
            self.new_group_name + " — webmap",
            ngw_webmap_root_group.children,
            ngw_webmap_basemaps,
        )
        self.putAddedResourceToResult(ngw_webmap, is_main=True)

        # The group was attached resources,  therefore, it is necessary to upgrade for get children flag
        ngw_group_resource.update()
        self.parent_group_resource.update()

    def create_webmap(
        self,
        ngw_resource,
        ngw_webmap_name,
        ngw_webmap_items,
        ngw_webmap_basemaps,
    ):
        self._layer_status(
            ngw_webmap_name,
            QgsApplication.translate("QGISResourceJob", "creating"),
        )

        extent = QgsReferencedRectangle(
            self.iface.mapCanvas().extent(),
            self.iface.mapCanvas().mapSettings().destinationCrs(),
        )
        ngw_webmap_items_as_dicts = [
            item.toDict() for item in ngw_webmap_items
        ]
        if len(ngw_webmap_items) == 0 and len(ngw_webmap_basemaps) == 0:
            # fmt: off
            user_message = QgsApplication.translate(
                "QGISResourceJob",
                "Failed to load any resource to the NextGIS Web."
                " Webmap will not be created"
            )
            # fmt: on
            raise NgwError("Can't create webmap", user_message=user_message)

        return NGWWebMap.create_in_group(
            ngw_webmap_name,
            ngw_resource,
            ngw_webmap_items_as_dicts,
            ngw_webmap_basemaps,
            NGWWebMap.to_webmap_extent(extent),
        )


class MapForLayerCreater(QGISResourceJob):
    def __init__(self, ngw_layer, ngw_style_id):
        super().__init__()
        self.ngw_layer = ngw_layer
        self.ngw_style_id = ngw_style_id

    def _do(self):
        if self.ngw_layer.type_id == NGWWmsLayer.type_id:
            self.create4WmsLayer()
        else:
            self.create4VectorRasterLayer()

    def create4VectorRasterLayer(self):
        if self.ngw_style_id is None:
            if self.ngw_layer.type_id == NGWVectorLayer.type_id:
                ngw_style = self._defStyleForVector(self.ngw_layer)
                self.putAddedResourceToResult(ngw_style)
                self.ngw_style_id = ngw_style.resource_id

            if self.ngw_layer.type_id == NGWRasterLayer.type_id:
                ngw_style = self._defStyleForRaster(self.ngw_layer)
                self.putAddedResourceToResult(ngw_style)
                self.ngw_style_id = ngw_style.resource_id

        ngw_webmap_root_group = NGWWebMapRoot()
        ngw_webmap_root_group.appendChild(
            NGWWebMapLayer(
                self.ngw_style_id,
                self.ngw_layer.display_name,
                is_visible=True,
                transparency=None,
                legend=True,
            )
        )

        ngw_group = self.ngw_layer.get_parent()

        ngw_map_name = self.unique_resource_name(
            self.ngw_layer.display_name + "-map", ngw_group
        )
        ngw_resource = NGWWebMap.create_in_group(
            ngw_map_name,
            ngw_group,
            [item.toDict() for item in ngw_webmap_root_group.children],
            [],
            bbox=self.ngw_layer.extent(),
        )

        self.putAddedResourceToResult(ngw_resource, is_main=True)

    def create4WmsLayer(self):
        self.ngw_style_id = self.ngw_layer.resource_id

        ngw_webmap_root_group = NGWWebMapRoot()
        ngw_webmap_root_group.appendChild(
            NGWWebMapLayer(
                self.ngw_style_id,
                self.ngw_layer.display_name,
                is_visible=True,
                transparency=None,
                legend=True,
            )
        )

        ngw_group = self.ngw_layer.get_parent()

        ngw_map_name = self.unique_resource_name(
            self.ngw_layer.display_name + "-map", ngw_group
        )

        ngw_resource = NGWWebMap.create_in_group(
            ngw_map_name,
            ngw_group,
            [item.toDict() for item in ngw_webmap_root_group.children],
            [],
        )

        self.putAddedResourceToResult(ngw_resource, is_main=True)


class QGISStyleUpdater(QGISResourceJob):
    def __init__(self, qgs_map_layer, ngw_resource):
        super().__init__()
        self.qgs_map_layer = qgs_map_layer
        self.ngw_resource = ngw_resource

    def _do(self):
        # if self.ngw_resource.type_id == NGWVectorLayer.type_id:
        self.updateStyle(self.qgs_map_layer, self.ngw_resource)
        self.putEditedResourceToResult(self.ngw_resource)


class QGISStyleAdder(QGISResourceJob):
    def __init__(self, qgs_map_layer: QgsMapLayer, ngw_resource: NGWResource):
        super().__init__()
        self.qgs_map_layer = qgs_map_layer
        self.ngw_resource = ngw_resource

    def _do(self):
        style_manager = self.qgs_map_layer.styleManager()
        assert style_manager is not None

        ngw_style = self.addStyle(
            self.ngw_resource, self.qgs_map_layer, style_manager.currentStyle()
        )
        if ngw_style is None:
            return
        self.putAddedResourceToResult(ngw_style)


class NGWCreateWMSService(QGISResourceJob):
    def __init__(self, ngw_layer, ngw_group_resource, ngw_style_id):
        super().__init__()
        self.ngw_layer = ngw_layer
        self.ngw_group_resource = ngw_group_resource
        self.ngw_style_id = ngw_style_id

    def _do(self):
        if self.ngw_style_id is None:
            if self.ngw_layer.type_id == NGWVectorLayer.type_id:
                ngw_style = self._defStyleForVector(self.ngw_layer)
                self.putAddedResourceToResult(ngw_style)
                self.ngw_style_id = ngw_style.resource_id

            if self.ngw_layer.type_id == NGWRasterLayer.type_id:
                ngw_style = self._defStyleForRaster(self.ngw_layer)
                self.putAddedResourceToResult(ngw_style)
                self.ngw_style_id = ngw_style.resource_id

        ngw_wms_service_name = self.unique_resource_name(
            self.ngw_layer.display_name + " — WMS service",
            self.ngw_group_resource,
        )

        ngw_wfs_resource = NGWWmsService.create_in_group(
            ngw_wms_service_name,
            self.ngw_group_resource,
            [(self.ngw_layer, self.ngw_style_id)],
        )

        self.putAddedResourceToResult(ngw_wfs_resource, is_main=True)


class NGWUpdateVectorLayer(QGISResourceJob):
    def __init__(
        self, ngw_vector_layer: NGWVectorLayer, qgs_map_layer: QgsVectorLayer
    ):
        super().__init__()
        self.ngw_layer = ngw_vector_layer
        self.qgis_layer = qgs_map_layer

    def _do(self):
        logger.debug(
            f'<b>Replace "{self.ngw_layer.display_name}" layer features</b> from layer "{self.qgis_layer.name()}")'
        )

        def uploadFileCallback(total_size, readed_size, value=None):
            self._layer_status(
                self.qgis_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(
                    int(
                        readed_size * 100 / total_size
                        if value is None
                        else value
                    )
                ),
            )

        if (
            self.isSuitableLayer(self.qgis_layer)
            == self.SUITABLE_LAYER_BAD_GEOMETRY
        ):
            raise JobError(
                f"Vector layer '{self.qgis_layer.name()}' has no suitable geometry"
            )

        filepath, old_fid_name, _ = self.prepareImportVectorFile(
            self.qgis_layer
        )
        if filepath is None:
            raise JobError(f'Can\'t prepare layer "{self.qgis_layer.name()}"')

        connection = self.ngw_layer.res_factory.connection
        vector_file_desc = connection.tus_upload_file(
            filepath, uploadFileCallback
        )

        fid_fields = ["ngw_id", "id"]
        if old_fid_name is not None:
            fid_fields.append(old_fid_name)

        url = self.ngw_layer.get_absolute_api_url()
        params = dict(
            resource=dict(),
            vector_layer=dict(
                srs=dict(id=3857),
                source=vector_file_desc,
                fix_errors="LOSSY",
                skip_errors=True,
                skip_other_geometry_types=False,
                fid_source="AUTO",
                fid_field=",".join(fid_fields),
            ),
        )

        self._layer_status(
            self.ngw_layer.display_name,
            QgsApplication.translate("QGISResourceJob", "replacing features"),
        )

        connection.put(url, params=params, is_lunkwill=True)

        self.ngw_layer = self.ngw_layer.res_factory.get_resource(
            self.ngw_layer.resource_id
        )

        fields_aliases: Dict[str, Dict[str, str]] = {}
        for field in self.qgis_layer.fields():
            alias = field.alias()
            if len(alias) == 0:
                continue

            fields_aliases[field.name()] = dict(display_name=alias)

        if len(fields_aliases) > 0:
            self._layer_status(
                self.ngw_layer.display_name,
                QgsApplication.translate("QGISResourceJob", "adding aliases"),
            )

            try:
                self.ngw_layer.update_fields_params(fields_aliases)
            except Exception as error:
                self.warningOccurred.emit(error)

        self._layer_status(
            self.ngw_layer.display_name,
            QgsApplication.translate("QGISResourceJob", "finishing"),
        )
        os.remove(filepath)


class ResourcesDownloader(QGISResourceJob):
    __connection_id: str
    __resources_id: Iterable[int]

    def __init__(self, connection_id: str, resources_id: Iterable[int]):
        super().__init__()
        self.__connection_id = connection_id
        self.__resources_id = resources_id

    def _do(self):
        ngw_connection = QgsNgwConnection(self.__connection_id)
        resources_factory = NGWResourceFactory(ngw_connection)
        for resource_id in self.__resources_id:
            try:
                self.result.dangling_resources.append(
                    resources_factory.get_resource(resource_id)
                )
            except NgwError as error:
                if error.code not in (
                    ErrorCode.PermissionsError,
                    ErrorCode.AuthorizationError,
                ):
                    raise

                logger.warning(
                    "An permission error occurred during fetching resource"
                    f" (id={resource_id})"
                )

                self.result.not_permitted_resources.append(resource_id)


class NGWUpdateRasterLayer(QGISResourceJob):
    """
    Update NextGIS Web raster layer by replacing its source with a new file.

    :param ngw_raster_layer: NGW raster layer resource to be updated.
    :type ngw_raster_layer: NGWRasterLayer
    :param qgs_map_layer: QGIS raster layer providing new data.
    :type qgs_map_layer: QgsRasterLayer
    """

    def __init__(
        self, ngw_raster_layer: NGWRasterLayer, qgs_map_layer: QgsRasterLayer
    ) -> None:
        """
        Initialize update job for a raster layer.
        """
        super().__init__()
        self.ngw_layer = ngw_raster_layer
        self.qgis_layer = qgs_map_layer

    def _do(self) -> None:
        """
        Prepare raster file, upload it and instruct NGW to replace the layer.
        """
        logger.debug(
            f'<b>Replace "{self.ngw_layer.display_name}" layer</b> '
            f'from layer "{self.qgis_layer.name()}")'
        )

        def upload_file_callback(
            total_size: int, readed_size: int, value: Optional[int] = None
        ) -> None:
            percent = (
                int(readed_size * 100 / total_size)
                if value is None
                else value
            )
            self._layer_status(
                self.qgis_layer.name(),
                QgsApplication.translate(
                    "QGISResourceJob", "uploading ({}%)"
                ).format(percent),
            )

        if not self.qgis_layer.crs().isValid():
            raise JobError(
                f"Raster layer '{self.qgis_layer.name()}' has no spatial "
                "reference"
            )

        is_ok, file_path = self.prepareImportRasterFile(self.qgis_layer)
        if not is_ok:
            raise JobError(
                f'Can\'t prepare layer "{self.qgis_layer.name()}"'
            )

        connection = self.ngw_layer.res_factory.connection
        raster_file_desc = connection.tus_upload_file(
            file_path, upload_file_callback
        )

        url = self.ngw_layer.get_absolute_api_url()
        params = dict(
            resource=dict(
                cls=NGWRasterLayer.type_id,
            ),
            raster_layer=dict(
                source=raster_file_desc,
            ),
        )

        connection.put(url, params=params, is_lunkwill=True)

        self.ngw_layer = self.ngw_layer.res_factory.get_resource(
            self.ngw_layer.resource_id
        )

        self._layer_status(
            self.ngw_layer.display_name,
            QgsApplication.translate("QGISResourceJob", "finishing"),
        )

        # remove temporary file if it exists
        tmp_file = Path(file_path)
        if tmp_file.exists():
            tmp_file.unlink()
