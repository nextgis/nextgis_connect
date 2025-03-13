from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.actions import (
    ActionType,
    DataChangeAction,
    FeatureAction,
    FeatureId,
    VersioningAction,
)
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)
from nextgis_connect.resources.ngw_field import FieldId


class ConflictsDeduplicator:
    __container_path: Path
    __metadata: DetachedContainerMetaData
    __both_deleted: List[FeatureId]
    __both_updated_fields: Dict[QgsFeatureId, List[FieldId]]
    __both_updated_geometries: List[FeatureId]

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata
        self.__both_deleted = []
        self.__both_updated_fields = {}
        self.__both_updated_geometries = []

    def deduplicate(
        self,
        remote_actions: List[VersioningAction],
        conflicts: List[VersioningConflict],
    ) -> Tuple[bool, List[FeatureAction], List[VersioningConflict]]:
        self.__both_deleted = []
        self.__both_updated_fields = {}
        self.__both_updated_geometries = []

        # Process conflicts and collect info for container and actions changes
        updated_conflicts = self.__process_conflicts(conflicts)
        updated_remote_actions = self.__process_actons(remote_actions)

        # Apply changes
        self.__apply_changes_to_container()

        # If local container changed we need to update state
        need_update_state = len(self.__both_deleted) > 0 or len(conflicts) > 0

        return need_update_state, updated_remote_actions, updated_conflicts

    def __process_conflicts(
        self, conflicts: List[VersioningConflict]
    ) -> List[VersioningConflict]:
        result = []

        for conlict in conflicts:
            processed = self.__process_conflict(conlict)
            if processed is None:
                continue
            result.append(processed)

        return result

    def __process_conflict(
        self, conflict: VersioningConflict
    ) -> Optional[VersioningConflict]:
        if (
            conflict.local_action.action
            == conflict.remote_action.action
            == ActionType.FEATURE_DELETE
        ):
            return self.__prorcess_deletion(conflict)

        if (
            conflict.local_action.action
            == conflict.remote_action.action
            == ActionType.FEATURE_UPDATE
        ):
            return self.__prorcess_updated(conflict)

        return conflict

    def __prorcess_deletion(self, conflict: VersioningConflict) -> None:
        self.__both_deleted.append(conflict.local_action.fid)
        return None

    def __prorcess_updated(
        self, conflict: VersioningConflict
    ) -> Optional[VersioningConflict]:
        assert isinstance(conflict.local_action, DataChangeAction)
        assert isinstance(conflict.remote_action, DataChangeAction)

        local_fields = conflict.local_action.fields_dict
        remote_fields = conflict.remote_action.fields_dict

        local_geometry = conflict.local_action.geom
        remote_geometry = conflict.remote_action.geom

        if local_fields != remote_fields or local_geometry != remote_geometry:
            return conflict

        if len(local_fields) > 0:
            self.__both_updated_fields[conflict.fid] = list(
                local_fields.keys()
            )

        if local_geometry is not None:
            self.__both_updated_geometries.append(conflict.fid)

        return None

    def __process_actons(
        self, remote_actions: List[VersioningAction]
    ) -> List[FeatureAction]:
        return [
            action
            for action in remote_actions
            if isinstance(action, FeatureAction)
            and action.fid not in self.__both_deleted
        ]

    def __apply_changes_to_container(self) -> None:
        if len(self.__both_deleted) + len(self.__both_updated_fields) == 0:
            return

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            if len(self.__both_deleted) > 0:
                deleted_ngw_fids = ",".join(map(str, self.__both_deleted))
                cursor.executescript(f"""
                    DELETE FROM ngw_removed_features
                    WHERE fid IN (
                        SELECT fid FROM ngw_features_metadata
                        WHERE ngw_fid IN ({deleted_ngw_fids})
                    );
                    DELETE FROM ngw_features_metadata
                    WHERE ngw_fid IN ({deleted_ngw_fids});
                """)

            if len(self.__both_updated_fields) > 0:
                ngw_fids_str = ",".join(
                    map(str, self.__both_updated_fields.keys())
                )
                ngw_fid_to_fid = {
                    row[0]: row[1]
                    for row in cursor.execute(f"""
                        SELECT ngw_fid, fid
                        FROM ngw_features_metadata
                        WHERE ngw_fid IN ({ngw_fids_str});
                    """)
                }

                fields = self.__metadata.fields
                pk_pairs = []
                for ngw_fid, attributes in self.__both_updated_fields.items():
                    fid = ngw_fid_to_fid[ngw_fid]
                    attributes = ",".join(
                        map(
                            lambda attribute: str(
                                fields.get_with(ngw_id=attribute).attribute
                            ),
                            attributes,
                        )
                    )

                    pk_pairs.append(
                        f"(fid={fid} AND attribute IN ({attributes}))"
                    )

                where_clause = " OR ".join(pk_pairs)
                cursor.execute(f"""
                    DELETE FROM ngw_updated_attributes
                    WHERE {where_clause};
                """)

            if len(self.__both_updated_geometries) > 0:
                deleted_ngw_fids = ",".join(
                    map(str, self.__both_updated_geometries)
                )
                cursor.executescript(f"""
                    DELETE FROM ngw_updated_geometries
                    WHERE fid IN (
                        SELECT fid FROM ngw_features_metadata
                        WHERE ngw_fid IN ({deleted_ngw_fids})
                    );
                """)

            connection.commit()
