import itertools
import sqlite3
from base64 import b64encode
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
)
from nextgis_connect.exceptions import ContainerError, NgConnectError
from nextgis_connect.resources.ngw_field import FieldId, NgwField

from .actions import (
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureId,
    FeatureUpdateAction,
    VersioningAction,
)


class ActionExtractor:
    __container_path: Path
    __metadata: DetachedContainerMetaData
    __layer: QgsVectorLayer
    __fields: Dict[FieldId, NgwField]
    __attributes: Dict[int, NgwField]

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata
        layer_path = f"{container_path}|layername={metadata.table_name}"
        self.__layer = QgsVectorLayer(layer_path)

        self.__fields = {field.ngw_id: field for field in metadata.fields}
        self.__attributes = {
            field.attribute: field for field in self.__metadata.fields
        }

    def extract_all(self) -> List[VersioningAction]:
        added_features = self.extract_added_features()
        deleted_features = self.extract_deleted_features()
        updated_features = self.extract_updated_features()

        actions = itertools.chain(
            added_features, deleted_features, updated_features
        )
        return list(actions)

    def extract_added_features(self) -> List[FeatureCreateAction]:
        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                added_features_id = [
                    row[0]
                    for row in cursor.execute(
                        "SELECT fid from ngw_added_features"
                    )
                ]
        except Exception as error:
            raise ContainerError from error

        create_actions = []
        request = QgsFeatureRequest(added_features_id)
        for feature in self.__layer.getFeatures(request):  # type: ignore
            fid = feature.id()
            geom = self.__serialize_geometry(feature.geometry())
            fields = []
            for field_id, field in self.__fields.items():
                value = self.__serialize_value(
                    feature.attribute(field.attribute)
                )
                if value is None:
                    continue
                fields.append([field_id, value])

            create_actions.append(FeatureCreateAction(fid, None, geom, fields))

        return create_actions

    def extract_updated_features(self) -> List[FeatureUpdateAction]:
        # Collect information about updated features

        attributes_query = "SELECT fid, attribute from ngw_updated_attributes"
        geoms_query = "SELECT fid from ngw_updated_geometries"

        updated_feature_attributes: Dict[FeatureId, Set[int]] = {}
        updated_feature_geoms: Set[FeatureId] = set()

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                for fid, attribute in cursor.execute(attributes_query):
                    if fid not in updated_feature_attributes:
                        updated_feature_attributes[fid] = set()
                    updated_feature_attributes[fid].add(attribute)

                updated_feature_geoms = set(
                    row[0] for row in cursor.execute(geoms_query)
                )

                all_updated_fids = list(
                    set(updated_feature_attributes.keys())
                    | updated_feature_geoms
                )
                if len(all_updated_fids) == 0:
                    return []

                all_updated_fids_joined = ", ".join(
                    str(fid) for fid in all_updated_fids
                )

                features_metadata = {
                    row[0]: FeatureMetaData(
                        fid=row[0], ngw_fid=row[1], version=row[2]
                    )
                    for row in cursor.execute(
                        f"""
                            SELECT fid, ngw_fid, version
                            FROM ngw_features_metadata
                            WHERE fid IN ({all_updated_fids_joined})
                        """
                    )
                }

        except Exception as error:
            raise ContainerError from error

        updated_actions: List[FeatureUpdateAction] = []

        request = QgsFeatureRequest(all_updated_fids)
        for feature in self.__layer.getFeatures(request):  # type: ignore
            feature_metadata = features_metadata[feature.id()]
            ngw_fid = feature_metadata.ngw_fid
            assert ngw_fid is not None
            vid = feature_metadata.version

            geom = (
                self.__serialize_geometry(feature.geometry())
                if feature_metadata.fid in updated_feature_geoms
                else None
            )

            fields = []
            for attribute_id in updated_feature_attributes.get(
                feature.id(), set()
            ):
                fields.append(
                    [
                        self.__attributes[attribute_id].ngw_id,
                        self.__serialize_value(
                            feature.attribute(attribute_id)
                        ),
                    ]
                )

            updated_actions.append(
                FeatureUpdateAction(ngw_fid, vid, geom, fields)
            )

        return updated_actions

    def extract_deleted_features(self) -> List[FeatureDeleteAction]:
        query = """
            SELECT feature_metadata.ngw_fid
            FROM ngw_removed_features removed
            LEFT JOIN ngw_features_metadata feature_metadata
                ON feature_metadata.fid = removed.fid
            """

        try:
            with closing(
                sqlite3.connect(str(self.__container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                return [
                    FeatureDeleteAction(row[0])
                    for row in cursor.execute(query)
                ]

        except Exception as error:
            raise ContainerError from error

    def __serialize_geometry(self, geometry: Optional[QgsGeometry]) -> str:
        if geometry is None or geometry.isEmpty():
            return ""

        def as_wkt(geometry: QgsGeometry) -> str:
            wkt = geometry.asWkt()

            if not QgsWkbTypes.hasZ(geometry.wkbType()):
                return wkt

            geometry_type = geometry.type()
            if geometry_type == GeometryType.Point:
                replacement = ("tZ", "t Z")
            elif geometry_type == GeometryType.Line:
                replacement = ("gZ", "g Z")
            elif geometry_type == GeometryType.Polygon:
                replacement = ("nZ", "n Z")
            else:
                raise NgConnectError("Unknown geometry")

            return wkt.replace(*replacement)

        def as_wkb64(geometry: QgsGeometry) -> str:
            return b64encode(geometry.asWkb().data()).decode("ascii")

        return (
            as_wkb64(geometry)
            if self.__metadata.is_versioning_enabled
            else as_wkt(geometry)
        )

    def __serialize_value(self, value: Any) -> Any:
        if isinstance(value, QVariant) and value.isNull():
            return None
        return value
