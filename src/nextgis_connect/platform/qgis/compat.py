# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from enum import IntEnum
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set

from osgeo import gdal
from qgis import core as qgis_core
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsMapLayerType,
    QgsRasterFileWriter,  # noqa: F401
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QT_VERSION_STR, QMetaType, QVariant

QT_VERSION_MAJOR = int(QT_VERSION_STR.split(".")[0])

if TYPE_CHECKING:

    class UndoCommand:
        def __init__(self, text: str = "") -> None: ...

        def id(self) -> int: ...

        def mergeWith(self, other: Optional["UndoCommand"]) -> bool: ...

        def redo(self) -> None: ...

        def undo(self) -> None: ...

elif QT_VERSION_MAJOR == 5:
    from qgis.PyQt.QtWidgets import (
        QUndoCommand as UndoCommand,  # pyright: ignore[reportAttributeAccessIssue] # noqa: F401, RUF100
    )
elif QT_VERSION_MAJOR == 6:
    from qgis.PyQt.QtGui import (
        QUndoCommand as UndoCommand,  # pyright: ignore[reportAttributeAccessIssue] # noqa: F401, RUF100
    )

QGIS_3_30 = 33000
QGIS_3_32 = 33200
QGIS_3_34 = 33400
QGIS_3_36 = 33600
QGIS_3_38 = 33800
QGIS_3_40 = 34000
QGIS_3_42 = 34200
QGIS_3_42_2 = 34202


QgsFeatureId = int
QgsFeatureIds = Set[QgsFeatureId]
QgsFeatureList = List[QgsFeature]

QgsAttributeList = List[int]
QgsAttributeMap = Dict[int, Any]
QgsChangedAttributesMap = Dict[
    QgsFeatureId, Dict[QgsFeatureId, QgsAttributeMap]
]

QgsGeometryMap = Dict[QgsFeatureId, QgsGeometry]

_MISSING_VECTOR_TILE_LAYER_TYPE = object()


if Qgis.versionInt() >= QGIS_3_30 or TYPE_CHECKING:
    WkbType = Qgis.WkbType  # type: ignore

    GeometryType = Qgis.GeometryType  # type: ignore

    LayerType = Qgis.LayerType  # type: ignore

else:
    WkbType = QgsWkbTypes.Type  # type: ignore

    GeometryType = QgsWkbTypes.GeometryType  # type: ignore
    GeometryType.Point = GeometryType.PointGeometry  # type: ignore
    GeometryType.Point.is_monkey_patched = True
    GeometryType.Line = GeometryType.LineGeometry  # type: ignore
    GeometryType.Line.is_monkey_patched = True
    GeometryType.Polygon = GeometryType.PolygonGeometry  # type: ignore
    GeometryType.Polygon.is_monkey_patched = True
    GeometryType.Unknown = GeometryType.UnknownGeometry  # type: ignore
    GeometryType.Unknown.is_monkey_patched = True
    GeometryType.Null = GeometryType.NullGeometry  # type: ignore
    GeometryType.Null.is_monkey_patched = True

    LayerType = QgsMapLayerType
    LayerType.Vector = QgsMapLayerType.VectorLayer  # type: ignore
    LayerType.Vector.is_monkey_patched = True
    LayerType.Raster = QgsMapLayerType.RasterLayer  # type: ignore
    LayerType.Raster.is_monkey_patched = True
    LayerType.Plugin = QgsMapLayerType.PluginLayer  # type: ignore
    LayerType.Plugin.is_monkey_patched = True
    LayerType.Mesh = QgsMapLayerType.MeshLayer  # type: ignore
    LayerType.Mesh.is_monkey_patched = True
    LayerType.Annotation = QgsMapLayerType.AnnotationLayer  # type: ignore
    LayerType.Annotation.is_monkey_patched = True
    LayerType.PointCloud = QgsMapLayerType.PointCloudLayer  # type: ignore
    LayerType.PointCloud.is_monkey_patched = True


if not hasattr(LayerType, "VectorTile"):
    LayerType.VectorTile = getattr(  # type: ignore
        QgsMapLayerType,
        "VectorTileLayer",
        _MISSING_VECTOR_TILE_LAYER_TYPE,
    )
    if LayerType.VectorTile is not _MISSING_VECTOR_TILE_LAYER_TYPE:
        LayerType.VectorTile.is_monkey_patched = True


def is_mvt_supported() -> bool:
    """Return whether this QGIS build can create MVT layers."""
    if LayerType.VectorTile is _MISSING_VECTOR_TILE_LAYER_TYPE:
        return False

    if getattr(qgis_core, "QgsVectorTileLayer", None) is None:
        return False

    provider_registry_class = getattr(
        qgis_core,
        "QgsProviderRegistry",
        None,
    )
    if provider_registry_class is None:
        return False

    provider_registry = provider_registry_class.instance()
    return (
        provider_registry is not None
        and provider_registry.providerMetadata("vectortile") is not None
    )


if Qgis.versionInt() >= QGIS_3_34 or TYPE_CHECKING:
    LayerFilter = Qgis.LayerFilter
    LayerFilters = Qgis.LayerFilters

else:
    LayerFilter = QgsMapLayerProxyModel.Filter
    LayerFilters = QgsMapLayerProxyModel.Filters

if Qgis.versionInt() >= QGIS_3_36 or TYPE_CHECKING:
    FeatureRequestFlag = Qgis.FeatureRequestFlag
    FeatureRequestFlags = Qgis.FeatureRequestFlags

else:
    FeatureRequestFlag = QgsFeatureRequest.Flag
    FeatureRequestFlags = QgsFeatureRequest.Flags


if Qgis.versionInt() >= QGIS_3_38 or TYPE_CHECKING:
    FieldType = QMetaType.Type
else:
    FieldType = getattr(QVariant, "Type", QVariant)
    FieldType.QString = FieldType.String
    FieldType.QString.is_monkey_patched = True
    FieldType.QDate = FieldType.Date
    FieldType.QDate.is_monkey_patched = True
    FieldType.QTime = FieldType.Time
    FieldType.QTime.is_monkey_patched = True
    FieldType.QDateTime = FieldType.DateTime
    FieldType.QDateTime.is_monkey_patched = True
    FieldType.Bool = FieldType.Bool
    FieldType.Bool.is_monkey_patched = True
    FieldType.QVariantMap = FieldType.Map
    FieldType.QVariantMap.is_monkey_patched = True
    FieldType.QJsonValue = FieldType.Map
    FieldType.QJsonValue.is_monkey_patched = True
    FieldType.QJsonObject = FieldType.Map
    FieldType.QJsonObject.is_monkey_patched = True
    FieldType.QJsonArray = FieldType.Map
    FieldType.QJsonArray.is_monkey_patched = True

try:
    from packaging import version

    parse_version = version.parse

except Exception:
    import pkg_resources

    parse_version = pkg_resources.parse_version  # type: ignore


class DataType(IntEnum):
    """Represent QGIS raster data types across supported versions.

    Provide conversion helpers between QGIS data type enum values and
    GDAL integer data type identifiers.
    """

    UnknownDataType = Qgis.DataType.UnknownDataType
    Byte = Qgis.DataType.Byte
    Int8 = Qgis.DataType.Int8
    UInt16 = Qgis.DataType.UInt16
    Int16 = Qgis.DataType.Int16
    UInt32 = Qgis.DataType.UInt32
    Int32 = Qgis.DataType.Int32
    Float32 = Qgis.DataType.Float32
    Float64 = Qgis.DataType.Float64
    CInt16 = Qgis.DataType.CInt16
    CInt32 = Qgis.DataType.CInt32
    CFloat32 = Qgis.DataType.CFloat32
    CFloat64 = Qgis.DataType.CFloat64
    ARGB32 = Qgis.DataType.ARGB32
    ARGB32_Premultiplied = Qgis.DataType.ARGB32_Premultiplied

    @classmethod
    def from_qgis(cls, qgis_data_type: Any) -> "DataType":
        """Return the matching data type or ``UnknownDataType``."""
        try:
            return cls(qgis_data_type)
        except (TypeError, ValueError):
            return cls.UnknownDataType

    def to_gdal(self) -> int:
        """Return the corresponding GDAL data type.

        :return: GDAL data type identifier.
        """
        mapping = {
            DataType.UnknownDataType: int(gdal.GDT_Unknown),
            DataType.Byte: int(gdal.GDT_Byte),
            DataType.UInt16: int(gdal.GDT_UInt16),
            DataType.Int16: int(gdal.GDT_Int16),
            DataType.UInt32: int(gdal.GDT_UInt32),
            DataType.Int32: int(gdal.GDT_Int32),
            DataType.Float32: int(gdal.GDT_Float32),
            DataType.Float64: int(gdal.GDT_Float64),
            DataType.CInt16: int(gdal.GDT_CInt16),
            DataType.CInt32: int(gdal.GDT_CInt32),
            DataType.CFloat32: int(gdal.GDT_CFloat32),
            DataType.CFloat64: int(gdal.GDT_CFloat64),
            DataType.ARGB32: int(gdal.GDT_Unknown),
            DataType.ARGB32_Premultiplied: int(gdal.GDT_Unknown),
        }

        int8 = self._optional_gdal_type("GDT_Int8")
        if int8 is not None:
            mapping[DataType.Int8] = int8
        else:
            mapping[DataType.Int8] = int(gdal.GDT_Unknown)

        return mapping.get(self, int(gdal.GDT_Unknown))

    @classmethod
    def from_gdal(cls, gdal_data_type: int) -> "DataType":
        """Return the corresponding QGIS data type.

        :param gdal_data_type: GDAL data type identifier.
        :return: Matching QGIS data type.
        """
        mapping: Dict[int, DataType] = {
            int(gdal.GDT_Unknown): cls.UnknownDataType,
            int(gdal.GDT_Byte): cls.Byte,
            int(gdal.GDT_UInt16): cls.UInt16,
            int(gdal.GDT_Int16): cls.Int16,
            int(gdal.GDT_UInt32): cls.UInt32,
            int(gdal.GDT_Int32): cls.Int32,
            int(gdal.GDT_Float32): cls.Float32,
            int(gdal.GDT_Float64): cls.Float64,
            int(gdal.GDT_CInt16): cls.CInt16,
            int(gdal.GDT_CInt32): cls.CInt32,
            int(gdal.GDT_CFloat32): cls.CFloat32,
            int(gdal.GDT_CFloat64): cls.CFloat64,
        }

        optional_mapping = {
            "GDT_Int8": cls.Int8,
            "GDT_Float16": cls.Float32,
            "GDT_CFloat16": cls.CFloat32,
            "GDT_Int64": cls.Float64,
            "GDT_UInt64": cls.Float64,
            "GDT_TypeCount": cls.UnknownDataType,
        }

        for gdal_name, data_type in optional_mapping.items():
            value = cls._optional_gdal_type(gdal_name)
            if value is None:
                continue

            mapping[value] = data_type

        return mapping.get(int(gdal_data_type), cls.UnknownDataType)

    @staticmethod
    def _optional_gdal_type(name: str) -> Optional[int]:
        value = getattr(gdal, name, None)

        if value is None:
            return None

        return int(value)


def enum_integer(value: object) -> int:
    """Return a Qt 5 integer enum or Qt 6 scoped enum numeric value."""
    numeric_value = getattr(value, "value", value)
    if not isinstance(numeric_value, int):
        raise TypeError("Qt enum does not provide an integer value")
    return numeric_value


def combine_flags(
    owner: object, singular_name: str, flags: Iterable[object]
) -> Any:
    """Combine a Qt 5/6 ``Flag``/``Flags`` enum collection."""
    flag_value = 0
    for flag in flags:
        flag_value |= enum_integer(flag)
    flags_type = getattr(owner, format(singular_name) + "s", None)
    if flags_type is None:
        flags_type = getattr(owner, singular_name)
    return flags_type(flag_value)
