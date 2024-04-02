import itertools
import sqlite3
from base64 import b64encode
from typing import Any, Dict, List, Optional, Set

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
)
from nextgis_connect.resources.ngw_field import FieldId, NgwField

from .actions import (
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureId,
    FeatureUpdateAction,
    VersioningAction,
)


class ActionExtractor:
    __layer_metadata: DetachedContainerMetaData
    __fields: Dict[FieldId, NgwField]
    __attributes: Dict[int, NgwField]
    __cursor: sqlite3.Cursor

    def __init__(
        self, layer_metadata: DetachedContainerMetaData, cursor: sqlite3.Cursor
    ) -> None:
        self.__layer_metadata = layer_metadata
        self.__fields = {
            field.ngw_id: field for field in layer_metadata.fields
        }
        self.__attributes = {
            field.attribute: field for field in self.__layer_metadata.fields
        }
        self.__cursor = cursor

    def extract_all(self) -> List[VersioningAction]:
        added_features = self.extract_added_features()
        deleted_features = self.extract_deleted_features()
        updated_features = self.extract_updated_features()

        actions = itertools.chain(
            added_features, deleted_features, updated_features
        )
        return list(actions)

    def extract_added_features(self) -> List[FeatureCreateAction]:
        is_versioning_enabled = self.__layer_metadata.is_versioning_enabled
        columns = ", ".join(
            f"features.{field.keyname}" for field in self.__fields.values()
        )
        geom_function = (
            "ST_AsBinary(geom)" if is_versioning_enabled else "ST_AsText(geom)"
        )
        query = f"""
            SELECT features.fid, {columns}, {geom_function}
            FROM '{self.__layer_metadata.table_name}' features
            RIGHT JOIN ngw_added_features added_features
                ON features.fid = added_features.fid
            """

        create_actions = []
        for row in self.__cursor.execute(query):
            fid = row[0]
            geom = row[-1]
            if is_versioning_enabled and geom is not None:
                geom = b64encode(geom).decode("ascii")
            fields = [
                [field_id, value]
                for field_id, value in zip(self.__fields.keys(), row[1:-1])
                if value is not None
            ]
            create_actions.append(FeatureCreateAction(fid, None, geom, fields))

        return create_actions

    def extract_updated_features(self) -> List[FeatureUpdateAction]:
        # Collect information about updated features
        updated_attributes_for_all_features = set()
        updated_feature_attributes: Dict[FeatureId, Set[int]] = {}

        attributes_query = "SELECT fid, attribute from ngw_updated_attributes"
        for fid, attribute in self.__cursor.execute(attributes_query):
            if fid not in updated_feature_attributes:
                updated_feature_attributes[fid] = set()

            updated_attributes_for_all_features.add(attribute)
            updated_feature_attributes[fid].add(attribute)

        geoms_query = "SELECT fid from ngw_updated_geometries"
        updated_feature_geoms: Set[FeatureId] = set(
            row[0] for row in self.__cursor.execute(geoms_query)
        )

        all_updated_fids = (
            set(updated_feature_attributes.keys()) | updated_feature_geoms
        )
        if len(all_updated_fids) == 0:
            return []

        # Combine params for query
        updated_attributes_for_all_features = list(
            updated_attributes_for_all_features
        )
        all_updated_fids_joined = ", ".join(
            str(fid) for fid in all_updated_fids
        )

        is_versioning_enabled = self.__layer_metadata.is_versioning_enabled
        columns_name = (
            f"features.{self.__attributes[attribute].keyname}"
            for attribute in updated_attributes_for_all_features
        )
        geom_function = (
            "ST_AsBinary(geom)" if is_versioning_enabled else "ST_AsText(geom)"
        )
        geom_column = (
            ["NULL"] if len(updated_feature_geoms) == 0 else [geom_function]
        )
        columns = ", ".join(itertools.chain(columns_name, geom_column))

        select_updated_features_query = f"""
            SELECT
                feature_metadata.fid,
                feature_metadata.ngw_fid,
                feature_metadata.version,
                {columns}
            FROM '{self.__layer_metadata.table_name}' features
            LEFT JOIN ngw_features_metadata feature_metadata
                ON features.fid = feature_metadata.fid
            WHERE features.fid IN ({all_updated_fids_joined})
        """

        updated_actions: List[FeatureUpdateAction] = []
        for row in self.__cursor.execute(select_updated_features_query):
            fid = row[0]
            ngw_fid = row[1]
            vid = row[2]

            geom = None
            if fid in updated_feature_geoms:
                geom = row[-1]
                if is_versioning_enabled and geom is not None:
                    geom = b64encode(geom).decode("ascii")

            fields: Optional[List[List[Any]]] = None
            if fid in updated_feature_attributes:
                fields = []
                for attribute_id, value in zip(
                    updated_attributes_for_all_features, row[3:-1]
                ):
                    fields.append(
                        [self.__attributes[attribute_id].ngw_id, value]
                    )

            updated_actions.append(
                FeatureUpdateAction(ngw_fid, vid, geom, fields)
            )

        return updated_actions

    def extract_deleted_features(self) -> List[FeatureDeleteAction]:
        query = """
            SELECT ngw_fid FROM ngw_features_metadata feature_metadata
            RIGHT JOIN ngw_removed_features removed
                ON feature_metadata.fid = removed.fid
            """
        return [
            FeatureDeleteAction(row[0]) for row in self.__cursor.execute(query)
        ]
