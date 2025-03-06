import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple, cast

from qgis.core import QgsFeature, QgsFeatureRequest, QgsVectorLayer

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.actions import (
    ActionType,
    DataChangeAction,
    FeatureAction,
    FeatureId,
)
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    ConflictResolvingItem,
)
from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    detached_layer_uri,
    make_connection,
)
from nextgis_connect.resources.ngw_field import FieldId


class ConflictResolvingItemExtractor:
    __container_path: Path
    __metadata: DetachedContainerMetaData

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata

    def extract(
        self, conflicts: List[VersioningConflict]
    ) -> List[ConflictResolvingItem]:
        # Extaract ngw fids from conflicts
        all_ngw_fids = set()
        locally_changed_ngw_ids = set()
        locally_deleted_ngw_ids = set()

        for conflict in conflicts:
            all_ngw_fids.add(conflict.fid)

            if conflict.local_action.action == ActionType.FEATURE_UPDATE:
                locally_changed_ngw_ids.add(conflict.fid)
            elif conflict.local_action.action == ActionType.FEATURE_DELETE:
                locally_deleted_ngw_ids.add(conflict.fid)

        # Select fids for ngw fids
        ngw_fids_to_fids = self.__ngw_fid_to_fid_dict(all_ngw_fids)

        actual_features = self.__extract_existed_features(
            list(ngw_fids_to_fids.values())
        )
        deleted_features = self.__extract_deleted_features(
            list(
                fid
                for ngw_fid, fid in ngw_fids_to_fids.items()
                if ngw_fid in locally_deleted_ngw_ids
            )
        )
        fields_backups, geometries_backups = self.__extract_backups(
            list(
                fid
                for ngw_fid, fid in ngw_fids_to_fids.items()
                if ngw_fid in locally_changed_ngw_ids
            )
        )

        conflict_items = []
        for conflict in conflicts:
            if (
                conflict.local_action.action == ActionType.FEATURE_UPDATE
                and conflict.remote_action.action == ActionType.FEATURE_UPDATE
            ):
                local_feature = actual_features[ngw_fids_to_fids[conflict.fid]]
                feature_after_sync = self.__restore_feature(
                    local_feature, fields_backups, geometries_backups
                )
                remote_feature = self.__feature_with_changes(
                    feature_after_sync, conflict.remote_action
                )
                result_feature = self.__feature_both_with_changes(
                    local_feature, conflict
                )

            elif (
                conflict.local_action.action == ActionType.FEATURE_DELETE
                and conflict.remote_action.action == ActionType.FEATURE_UPDATE
            ):
                feature_after_sync = deleted_features[
                    ngw_fids_to_fids[conflict.fid]
                ]

                local_feature = None
                remote_feature = self.__feature_with_changes(
                    feature_after_sync, conflict.remote_action
                )
                result_feature = None

            elif (
                conflict.local_action.action == ActionType.FEATURE_UPDATE
                and conflict.remote_action.action == ActionType.FEATURE_DELETE
            ):
                local_feature = actual_features[ngw_fids_to_fids[conflict.fid]]
                remote_feature = None
                result_feature = None

            else:
                raise NotImplementedError

            conflict_item = ConflictResolvingItem(
                conflict=conflict,
                local_feature=local_feature,
                remote_feature=remote_feature,
                result_feature=result_feature,
            )
            conflict_items.append(conflict_item)

        return conflict_items

    def __restore_feature(
        self,
        feature: QgsFeature,
        fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str],
        geometries_backups: Dict[QgsFeatureId, str],
    ) -> QgsFeature:
        result_feature = QgsFeature(feature)
        for field in self.__metadata.fields:
            key = (feature.id(), field.ngw_id)
            if key not in fields_backups:
                continue
            feature.setAttribute(field.attribute, fields_backups[key])
        if feature.id() in geometries_backups:
            feature.setGeometry(
                deserialize_geometry(
                    geometries_backups[feature.id()],
                    self.__metadata.is_versioning_enabled,
                )
            )
        return result_feature

    def __feature_with_changes(
        self,
        feature: QgsFeature,
        action: FeatureAction,
    ) -> QgsFeature:
        assert isinstance(action, DataChangeAction)

        fields = self.__metadata.fields

        result_feature = QgsFeature(feature)
        if action.fields:
            for field_id, value in action.fields:
                feature.setAttribute(
                    fields.find_with(ngw_id=field_id).attribute, value
                )

        if action.geom is not None:
            feature.setGeometry(
                deserialize_geometry(
                    action.geom,
                    self.__metadata.is_versioning_enabled,
                )
            )

        return result_feature

    def __feature_both_with_changes(
        self,
        feature: QgsFeature,
        conflict: VersioningConflict,
    ) -> QgsFeature:
        assert isinstance(conflict.local_action, DataChangeAction)
        assert isinstance(conflict.remote_action, DataChangeAction)

        result_feature = self.__feature_with_changes(
            feature, conflict.remote_action
        )

        if len(conflict.conflicting_fields) > 0:
            fields = self.__metadata.fields
            for field_id in conflict.conflicting_fields:
                result_feature.setAttribute(
                    fields.find_with(ngw_id=field_id).attribute, None
                )

        if (
            conflict.local_action.geom is not None
            and conflict.remote_action.geom is not None
        ):
            result_feature.setGeometry(None)

        return result_feature

    def __extract_existed_features(
        self, fids: Sequence
    ) -> Dict[FeatureId, QgsFeature]:
        layer = QgsVectorLayer(
            detached_layer_uri(self.__container_path, self.__metadata),
            "",
            "ogr",
        )
        if not layer.isValid():
            raise ValueError("Invalid layer")

        request = QgsFeatureRequest(fids)
        return {
            feature.id(): feature
            for feature in cast(
                Iterable[QgsFeature], layer.getFeatures(request)
            )
        }

    def __extract_deleted_features(
        self, fids: Sequence
    ) -> Dict[FeatureId, QgsFeature]:
        fids_str = ",".join(map(str, fids))
        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            backups = {
                row[0]: row[1]
                for row in cursor.execute(f"""
                    SELECT fid, backup FROM ngw_removed_features
                    WHERE fid IN ({fids_str});
                """)
            }

        fields = QgsVectorLayer(
            detached_layer_uri(self.__container_path, self.__metadata),
            "",
            "ogr",
        ).fields()

        deleted_features = {}
        for fid in fids:
            backup = json.loads(backups[fid])
            attributes_after_sync = backup["after_sync"]["fields"]
            feature = QgsFeature(fields, fid)
            for field_id, value in attributes_after_sync:
                feature.setAttribute(
                    self.__metadata.fields.get_with(ngw_id=field_id).attribute,
                    value,
                )
            feature.setGeometry(
                deserialize_geometry(
                    backup["after_sync"]["geom"],
                    self.__metadata.is_versioning_enabled,
                )
            )
            deleted_features[feature.id()] = feature

        return deleted_features

    def __extract_backups(
        self, locally_changed_fids: List[QgsFeatureId]
    ) -> Tuple[
        Dict[Tuple[QgsFeatureId, FieldId], str], Dict[QgsFeatureId, str]
    ]:
        joined_locally_changed_fids = ",".join(map(str, locally_changed_fids))
        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            fields_backups = self.__extract_fields_backups(
                cursor, joined_locally_changed_fids
            )
            geometries_backups = self.__extract_geometries_backups(
                cursor, joined_locally_changed_fids
            )
        return fields_backups, geometries_backups

    def __extract_fields_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[Tuple[QgsFeatureId, FieldId], str]:
        return {
            (row[0], row[1]): deserialize_value(row[2])
            for row in cursor.execute(
                f"""
                SELECT fid, attribute, backup
                FROM ngw_updated_attributes
                WHERE fid IN ({joined_fids})
                """
            )
        }

    def __extract_geometries_backups(
        self, cursor: sqlite3.Cursor, joined_fids: str
    ) -> Dict[QgsFeatureId, str]:
        return {
            row[0]: row[1]
            for row in cursor.execute(
                f"""
                SELECT fid, backup
                FROM ngw_updated_geometries
                WHERE fid IN ({joined_fids})
                """
            )
        }

    def __ngw_fid_to_fid_dict(
        self, ngw_fids: Iterable[FeatureId]
    ) -> Dict[FeatureId, FeatureId]:
        ngw_fids_str = ",".join(map(str, ngw_fids))

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            return {
                row[0]: row[1]
                for row in cursor.execute(f"""
                    SELECT ngw_fid, fid
                    FROM ngw_features_metadata
                    WHERE ngw_fid IN ({ngw_fids_str});
                """)
            }
