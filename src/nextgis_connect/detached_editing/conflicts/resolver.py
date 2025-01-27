from contextlib import closing
from copy import deepcopy
from enum import Enum, auto
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, Iterable, List, Set, Tuple

from nextgis_connect.detached_editing.actions import (
    ActionType,
    FeatureAction,
    FeatureId,
    FeatureUpdateAction,
    FieldId,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)
from nextgis_connect.exceptions import DetachedEditingError
from nextgis_connect.logging import logger


class ConflictsResolver:
    __container_path: Path
    __metadata: DetachedContainerMetaData

    __new_actions: List[FeatureAction]
    __modified_actions: Dict[Tuple[FeatureId, ActionType], FeatureAction]
    __deleted_actions: Set[Tuple[FeatureId, ActionType]]

    __local_fields_changes_for_add: Dict[FeatureId, List[FieldId]]
    __local_fields_changes_for_delete: Dict[FeatureId, List[FieldId]]

    __local_geometry_changes_for_add: List[FeatureId]
    __local_geometry_changes_for_delete: List[FeatureId]

    class Status(Enum):
        NotResolved = auto()
        PartiallyResolved = auto()
        Resolved = auto()

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata

        self.__reset()

    def resolve(
        self,
        remote_actions: List[FeatureAction],
        resolutions: List[ConflictResolution],
    ) -> Tuple[Status, List[FeatureAction]]:
        try:
            status, result_actions = self.__resolve(
                remote_actions, resolutions
            )
        except Exception as error:
            logger.exception("Resolution failed")
            raise DetachedEditingError from error

        return status, result_actions

    def __reset(self) -> None:
        self.__new_actions = list()
        self.__modified_actions = dict()
        self.__deleted_actions = set()
        self.__local_fields_changes_for_add = dict()
        self.__local_fields_changes_for_delete = dict()
        self.__local_geometry_changes_for_add = list()
        self.__local_geometry_changes_for_delete = list()

    def __resolve(
        self,
        remote_actions: List[FeatureAction],
        resolutions: List[ConflictResolution],
    ) -> Tuple[Status, List[FeatureAction]]:
        self.__reset()

        has_resolved = False

        # Process resolutions
        for resolution in resolutions:
            if resolution.resolution_type == ResolutionType.NoResolution:
                return (
                    self.Status.PartiallyResolved
                    if has_resolved
                    else self.Status.NotResolved,
                    [],
                )

            has_resolved = True

            if resolution.resolution_type == ResolutionType.Local:
                self.__resolve_local(resolution)
            elif resolution.resolution_type == ResolutionType.Remote:
                self.__resolve_remote(resolution)
            elif resolution.resolution_type == ResolutionType.Custom:
                self.__resolve_custom(resolution)

        # Create actions list with updates
        updated_actions = self.__create_actions_list(remote_actions)

        # Apply changes to container
        self.__update_container()

        # Result
        return self.Status.Resolved, updated_actions

    def __resolve_local(self, resolution: ConflictResolution):
        local_action_type = resolution.conflict.local.action
        remote_action_type = resolution.conflict.remote.action

        if (
            local_action_type == ActionType.FEATURE_DELETE
            and remote_action_type == ActionType.FEATURE_UPDATE
        ):
            self.__prepare_remove_on_remote(resolution)

        elif (
            local_action_type == ActionType.FEATURE_UPDATE
            and remote_action_type == ActionType.FEATURE_DELETE
        ):
            self.__restore_remote(resolution)

        elif (
            local_action_type
            == remote_action_type
            == ActionType.FEATURE_UPDATE
        ):
            self.__resolve_local_update(resolution)

        else:
            # Only update and deletion can create a conflict
            raise NotImplementedError

    def __resolve_remote(self, resolution: ConflictResolution):
        local_action_type = resolution.conflict.local.action
        remote_action_type = resolution.conflict.remote.action

        if (
            local_action_type == ActionType.FEATURE_DELETE
            and remote_action_type == ActionType.FEATURE_UPDATE
        ):
            self.__restore_local(resolution)

        elif (
            local_action_type == ActionType.FEATURE_UPDATE
            and remote_action_type == ActionType.FEATURE_DELETE
        ):
            self.__remove_local_actions(resolution)

        elif (
            local_action_type
            == remote_action_type
            == ActionType.FEATURE_UPDATE
        ):
            self.__resolve_remote_update(resolution)

        else:
            # Only update and deletion can create a conflict
            raise NotImplementedError

    def __resolve_custom(self, resolution: ConflictResolution):
        local_action_type = resolution.conflict.local.action
        remote_action_type = resolution.conflict.local.action

        if (
            local_action_type
            == remote_action_type
            == ActionType.FEATURE_UPDATE
        ):
            self.__resolve_custom_update(resolution)

        else:
            # We can resolve custom type only when there are not deletions
            raise NotImplementedError

    def __resolve_local_update(self, resolution: ConflictResolution):
        fid = resolution.conflict.remote.fid

        local = resolution.conflict.local
        assert isinstance(local, FeatureUpdateAction)
        remote = resolution.conflict.remote
        assert isinstance(remote, FeatureUpdateAction)

        updated_action = deepcopy(remote)

        if len(local.fields) > 0 and len(remote.fields) > 0:
            # Apply only those field changes from the remote update that have
            # not been modified locally. This ensures that local changes are
            # preserved and only non-conflicting remote changes are applied.

            intersected = self.__intersected_fields(
                local.fields, remote.fields
            )
            updated_action.fields = [
                field_data
                for field_data in remote.fields
                if field_data[0] not in intersected
            ]

        if local.geom is not None and remote.geom is not None:
            # Geometry will not be updated, but the version ID (vid) will be.
            # We will send the locally changed geometry after applying.
            updated_action.geom = None

        self.__modified_actions[(fid, ActionType.FEATURE_UPDATE)] = (
            updated_action
        )

    def __resolve_remote_update(self, resolution: ConflictResolution):
        fid = resolution.conflict.remote.fid

        local = resolution.conflict.local
        assert isinstance(local, FeatureUpdateAction)
        remote = resolution.conflict.remote
        assert isinstance(remote, FeatureUpdateAction)

        if len(local.fields) > 0 and len(remote.fields) > 0:
            # Apply remote changes on all fields and then send only those local
            # ones that were not intersected with remote ones
            intersected = self.__intersected_fields(
                local.fields, remote.fields
            )
            if len(intersected) > 0:
                self.__local_fields_changes_for_delete[fid] = intersected

        if local.geom is not None and remote.geom is not None:
            # Remote version will be applied and local change will be deleted
            self.__local_geometry_changes_for_delete.append(fid)

    def __restore_local(self, resolution: ConflictResolution) -> None:
        raise NotImplementedError

    def __restore_remote(self, resolution: ConflictResolution) -> None:
        raise NotImplementedError

    def __remove_local_actions(self, resolution: ConflictResolution) -> None:
        local = resolution.conflict.local
        fid = local.fid
        assert isinstance(local, FeatureUpdateAction)

        if len(local.fields) > 0:
            self.__local_fields_changes_for_delete[fid] = list(
                local.fields_dict.keys()
            )

        if local.geom is not None:
            self.__local_geometry_changes_for_delete.append(fid)

    def __prepare_remove_on_remote(
        self, resolution: ConflictResolution
    ) -> None:
        remote = resolution.conflict.remote
        fid = remote.fid

        assert isinstance(remote, FeatureUpdateAction)
        updated_action = deepcopy(remote)
        updated_action.fields = []
        updated_action.geom = None

        self.__modified_actions[(fid, updated_action.action)] = updated_action

    def __resolve_custom_update(self, resolution: ConflictResolution):
        fid = resolution.conflict.remote.fid

        local = resolution.conflict.local
        assert isinstance(local, FeatureUpdateAction)
        remote = resolution.conflict.remote
        assert isinstance(remote, FeatureUpdateAction)

        updated_action = deepcopy(remote)
        updated_action.fields = resolution.custom_fields
        updated_action.geom = resolution.custom_geom

        # Check fields

        # Convert fields to dict for easier comparing
        local_changed_fields = local.fields_dict
        remote_changed_fields = remote.fields_dict
        custom_fields = updated_action.fields_dict
        assert set(custom_fields.keys()).issuperset(
            remote_changed_fields.keys()
        )

        updated_fields = []
        local_fields_changes_for_delete = []
        local_fields_changes_for_add = []
        for field_id, field_value in custom_fields.items():
            if (
                field_id in remote_changed_fields
                and remote_changed_fields[field_id] == field_value
                and field_id in local_changed_fields
            ):
                local_fields_changes_for_delete.append(field_id)

            elif field_id not in local_changed_fields:
                local_fields_changes_for_add.append(field_id)

            updated_fields.append((field_id, field_value))

        if len(local_fields_changes_for_delete) > 0:
            self.__local_fields_changes_for_delete[fid] = (
                local_fields_changes_for_delete
            )

        if len(local_fields_changes_for_add) > 0:
            self.__local_fields_changes_for_add[fid] = (
                local_fields_changes_for_add
            )

        updated_action.fields = updated_fields

        # Check geometry

        if local.geom is not None:
            if updated_action.geom == remote.geom:
                self.__local_geometry_changes_for_delete.append(fid)
            else:
                # If it's a local changed geometry or new one, we don't need
                # to do anything. Change will be sent
                pass

        elif remote.geom is not None:
            if updated_action.geom != remote.geom:
                self.__local_geometry_changes_for_add.append(fid)
            else:
                # No action is needed because the geometry wasn't changed
                # locally. Therefore, the remote geometry can be applied
                # directly without conflicts.
                pass

        elif updated_action.geom is not None:
            # local and remote is None but we changed in dialog
            self.__local_geometry_changes_for_add.append(fid)

        self.__modified_actions[(fid, updated_action.action)] = updated_action

    def __create_actions_list(
        self, remote_actions: List[FeatureAction]
    ) -> List[FeatureAction]:
        result = []
        for action in remote_actions:
            if action.action not in (
                ActionType.FEATURE_UPDATE,
                ActionType.FEATURE_DELETE,
            ):
                result.append(action)
                continue

            action_id = (action.fid, action.action)
            if action_id in self.__deleted_actions:
                continue

            if action_id in self.__modified_actions:
                result.append(self.__modified_actions[action_id])
                continue

            result.append(action)

        result.extend(self.__new_actions)

        return result

    def __update_container(self) -> None:
        script = ""

        fields = self.__metadata.fields

        if self.__local_fields_changes_for_add:
            ngw_fid_to_fid = self.__ngw_fid_to_fid_dict(
                self.__local_fields_changes_for_add.keys()
            )
            values = ",".join(
                f"({ngw_fid_to_fid[ngw_fid]},{fields.find_with(ngw_id=ngw_attribute).attribute})"
                for ngw_fid, ngw_attributes in self.__local_fields_changes_for_add.items()
                for ngw_attribute in ngw_attributes
            )
            script += dedent(f"""
                INSERT INTO ngw_updated_attributes (fid, attribute)
                VALUES {values};
            """)

        if self.__local_fields_changes_for_delete:
            ngw_fid_to_fid = self.__ngw_fid_to_fid_dict(
                self.__local_fields_changes_for_delete.keys()
            )
            where_clause = " OR ".join(
                f"(fid={ngw_fid_to_fid[ngw_fid]} AND attribute={fields.find_with(ngw_id=ngw_attribute).attribute})"
                for ngw_fid, ngw_attributes in self.__local_fields_changes_for_delete.items()
                for ngw_attribute in ngw_attributes
            )
            script += dedent(f"""
                DELETE FROM ngw_updated_attributes WHERE {where_clause};
            """)

        if self.__local_geometry_changes_for_add:
            ngw_fids = ",".join(
                map(str, self.__local_geometry_changes_for_add)
            )
            script += dedent(f"""
                INSERT INTO ngw_updated_geometries (fid)
                SELECT fid FROM ngw_features_metadata
                WHERE ngw_fid IN ({ngw_fids});
            """)

        if self.__local_geometry_changes_for_delete:
            ngw_fids = ",".join(
                map(str, self.__local_geometry_changes_for_delete)
            )
            script += dedent(f"""
                DELETE FROM ngw_updated_geometries
                WHERE fid IN (
                    SELECT fid FROM ngw_features_metadata
                    WHERE ngw_fid IN ({ngw_fids})
                );
            """)

        if len(script) == 0:
            return

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executescript(script)
            connection.commit()

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
                    SELECT ngw_fid, fid FROM ngw_features_metadata
                    WHERE ngw_fid IN ({ngw_fids_str});
                """)
            }

    def __intersected_fields(
        self,
        local: List[Tuple[FieldId, Any]],
        remote: List[Tuple[FieldId, Any]],
    ) -> List[FieldId]:
        local_fields_id = set(field_data[0] for field_data in local)
        return [
            field_data[0]
            for field_data in remote
            if field_data[0] in local_fields_id
        ]
