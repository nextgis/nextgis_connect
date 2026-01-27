from abc import ABC
from typing import ClassVar, Dict, Optional

from osgeo import ogr
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFields,
    QgsWkbTypes,
)

from nextgis_connect.compat import GeometryType, WkbType
from nextgis_connect.ngw_api.core.ngw_qgis_style import NGWQGISVectorStyle
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.resources.ngw_fields import NgwFields

from .ngw_resource import NGWResource


class NGWAbstractVectorResource(ABC, NGWResource):
    UNKNOWN = 0
    POINT = 1
    MULTIPOINT = 2
    LINESTRING = 3
    MULTILINESTRING = 4
    POLYGON = 5
    MULTIPOLYGON = 6
    POINTZ = 7
    MULTIPOINTZ = 8
    LINESTRINGZ = 9
    MULTILINESTRINGZ = 10
    POLYGONZ = 11
    MULTIPOLYGONZ = 12

    __GEOMETRIES: ClassVar[Dict[str, int]] = {
        "POINT": POINT,
        "MULTIPOINT": MULTIPOINT,
        "LINESTRING": LINESTRING,
        "MULTILINESTRING": MULTILINESTRING,
        "POLYGON": POLYGON,
        "MULTIPOLYGON": MULTIPOLYGON,
        "POINTZ": POINTZ,
        "MULTIPOINTZ": MULTIPOINTZ,
        "LINESTRINGZ": LINESTRINGZ,
        "MULTILINESTRINGZ": MULTILINESTRINGZ,
        "POLYGONZ": POLYGONZ,
        "MULTIPOLYGONZ": MULTIPOLYGONZ,
    }

    (
        FieldTypeInteger,
        FieldTypeBigint,
        FieldTypeReal,
        FieldTypeString,
        FieldTypeDate,
        FieldTypeTime,
        FieldTypeDatetime,
    ) = ["INTEGER", "BIGINT", "REAL", "STRING", "DATE", "TIME", "DATETIME"]  # noqa: RUF012

    def __init__(self, resource_factory, resource_json):
        super().__init__(resource_factory, resource_json)

    @property
    def fields(self) -> NgwFields:
        return self.__fields

    def field(self, name: str) -> Optional[NgwField]:
        return self.__fields.find_with(keyname=name)

    @property
    def qgs_fields(self) -> QgsFields:
        return self.fields.qgs_fields

    @property
    def features_count(self) -> int:
        if self.__features_count is None:
            feature_count_url = (
                f"/api/resource/{self.resource_id}/feature_count"
            )
            result = self.connection.get(feature_count_url)
            self.__features_count = result["total_count"]

        return self.__features_count

    @property
    def geom_name(self) -> Optional[str]:
        return self._json[self.type_id].get("geometry_type")

    @property
    def wkb_geom_type(self) -> WkbType:
        wkb_mapping = {
            self.UNKNOWN: ogr.wkbNone,
            self.POINT: ogr.wkbPoint,
            self.POINTZ: ogr.wkbPoint25D,
            self.MULTIPOINT: ogr.wkbMultiPoint,
            self.MULTIPOINTZ: ogr.wkbMultiPoint25D,
            self.LINESTRING: ogr.wkbLineString,
            self.LINESTRINGZ: ogr.wkbLineString25D,
            self.MULTILINESTRING: ogr.wkbMultiLineString,
            self.MULTILINESTRINGZ: ogr.wkbMultiLineString25D,
            self.POLYGON: ogr.wkbPolygon,
            self.POLYGONZ: ogr.wkbPolygon25D,
            self.MULTIPOLYGON: ogr.wkbMultiPolygon,
            self.MULTIPOLYGONZ: ogr.wkbMultiPolygon25D,
        }

        geom_type = self.__GEOMETRIES.get(
            self._json.get(self.type_id, {}).get("geometry_type", self.UNKNOWN)
        )
        if geom_type is None:
            geom_type = self.UNKNOWN

        return WkbType(wkb_mapping[geom_type])

    @property
    def geometry_type(self) -> GeometryType:
        return QgsWkbTypes.geometryType(self.wkb_geom_type)

    def is_geom_multy(self) -> bool:
        return QgsWkbTypes.isMultiType(self.wkb_geom_type)

    def is_geom_with_z(self) -> bool:
        return QgsWkbTypes.hasZ(self.wkb_geom_type)

    def srs(self):
        return self._json.get(self.type_id, {}).get("srs", {}).get("id")

    @property
    def qgs_srs(self) -> QgsCoordinateReferenceSystem:
        srs_id = self.srs()
        if srs_id is None:
            return QgsCoordinateReferenceSystem()
        return QgsCoordinateReferenceSystem.fromEpsgId(srs_id)

    def create_qml_style(
        self, qml, callback, style_name=None
    ) -> NGWQGISVectorStyle:
        """Create QML style for this layer

        qml - full path to qml file
        callback - upload file callback
        """
        connection = self.res_factory.connection
        if not style_name:
            style_name = self.display_name
        style_name = self.generate_unique_child_name(style_name)

        style_file_desc = connection.upload_file(qml, callback)

        params = dict(
            resource=dict(
                cls=NGWQGISVectorStyle.type_id,
                parent=dict(id=self.resource_id),
                display_name=style_name,
            ),
        )
        params[NGWQGISVectorStyle.type_id] = dict(file_upload=style_file_desc)

        url = self.get_api_collection_url()
        result = connection.post(url, params=params)
        ngw_resource = NGWQGISVectorStyle(
            self.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )

        return ngw_resource

    def _construct(self):
        super()._construct()
        self.__features_count = None
        self.__fields = NgwFields.from_json(
            self._json.get("feature_layer", {}).get("fields", [])
        )
