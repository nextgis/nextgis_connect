from contextlib import closing
from pathlib import Path
from typing import List, Optional, Sequence, cast

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    FeatureMetaData,
    make_connection,
)
from nextgis_connect.exceptions import SynchronizationError

from .actions import (
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
    VersioningAction,
)


class TransactionApplier:
    __container_path: Path
    __metadata: DetachedContainerMetaData

    def __init__(
        self, container_path: Path, metadata: DetachedContainerMetaData
    ) -> None:
        self.__container_path = container_path
        self.__metadata = metadata

    def apply(
        self,
        actions: Sequence[VersioningAction],
        operation_result: Optional[List] = None,
    ) -> None:
        if len(actions) == 0:
            return

        if self.__metadata.is_versioning_enabled:
            self.__apply_versioned(actions, operation_result)
        else:
            self.__apply_not_versioned(actions, operation_result)

    def __apply_versioned(
        self,
        actions: Sequence[VersioningAction],
        operation_result: Optional[List],
    ) -> None:
        if not operation_result:
            raise SynchronizationError("Empty operation result")

        if len(actions) != len(operation_result):
            raise SynchronizationError("Result length is not equal")

        added_features = []
        updated_features = []

        delete_actions = []
        restore_actions = []

        for action, (_, action_result) in zip(actions, operation_result):
            if str(action.action) != action_result["action"]:
                raise SynchronizationError("Different action and result type")

            if isinstance(action, FeatureCreateAction):
                added_features.append(
                    FeatureMetaData(
                        fid=cast(int, action.fid), ngw_fid=action_result["fid"]
                    )
                )

            elif isinstance(action, FeatureDeleteAction):
                delete_actions.append(action)

            elif isinstance(action, FeatureRestoreAction):
                restore_actions.append(action)

            elif isinstance(action, FeatureUpdateAction):
                updated_features.append(
                    FeatureMetaData(ngw_fid=cast(int, action.fid))
                )

        if len(added_features) > 0:
            self.__process_added(added_features)

        if len(updated_features) > 0:
            self.__process_updated(updated_features)

        if len(delete_actions) > 0:
            self.__process_deleted(delete_actions)

        if len(restore_actions) > 0:
            self.__process_restored(restore_actions)

    def __apply_not_versioned(
        self,
        actions: Sequence[VersioningAction],
        operation_result: Optional[List],
    ) -> None:
        first_action_type = type(actions[0])
        if not all(
            isinstance(action, first_action_type) for action in actions
        ):
            raise SynchronizationError("Action types should be the same")

        if first_action_type == FeatureCreateAction:
            assert operation_result is not None
            create_actions = cast(List[FeatureCreateAction], actions)
            added_features = [
                FeatureMetaData(
                    fid=cast(int, action.fid),
                    ngw_fid=operation_result[i]["id"],
                )
                for i, action in enumerate(create_actions)
            ]
            self.__process_added(added_features)

        elif first_action_type == FeatureDeleteAction:
            delete_actions = cast(List[FeatureDeleteAction], actions)
            self.__process_deleted(delete_actions)

        elif first_action_type == FeatureUpdateAction:
            update_actions = cast(List[FeatureUpdateAction], actions)
            updated_features = [
                FeatureMetaData(ngw_fid=cast(int, action.fid))
                for action in update_actions
            ]
            self.__process_updated(updated_features)

    def __process_added(
        self, features_metadata: List[FeatureMetaData]
    ) -> None:
        added_fids = ",".join(str(action.fid) for action in features_metadata)

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executemany(
                "UPDATE ngw_features_metadata SET ngw_fid=? WHERE fid=?",
                (
                    (feature.ngw_fid, feature.fid)
                    for feature in features_metadata
                ),
            )
            cursor.execute(
                f"DELETE FROM ngw_added_features WHERE fid in ({added_fids})"
            )

            connection.commit()

    def __process_deleted(
        self, actions: Sequence[FeatureDeleteAction]
    ) -> None:
        batch_ngw_fids = ",".join(str(action.fid) for action in actions)

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executescript(
                f"""
                WITH removed_fids AS (
                    SELECT fid FROM ngw_features_metadata
                        WHERE ngw_fid IN ({batch_ngw_fids})
                )
                DELETE FROM ngw_removed_features
                    WHERE fid IN removed_fids;
                DELETE FROM ngw_features_metadata
                    WHERE ngw_fid IN ({batch_ngw_fids});
                """
            )
            connection.commit()

    def __process_restored(
        self, actions: Sequence[FeatureRestoreAction]
    ) -> None:
        batch_ngw_fids = ",".join(str(action.fid) for action in actions)

        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executescript(
                f"""
                DELETE FROM ngw_restored_features
                WHERE fid IN (
                    SELECT fid FROM ngw_features_metadata
                    WHERE ngw_fid IN ({batch_ngw_fids})
                );
                """
            )
            connection.commit()

    def __process_updated(
        self, features_metadata: List[FeatureMetaData]
    ) -> None:
        ngw_fids = ",".join(
            str(feature.ngw_fid) for feature in features_metadata
        )
        with closing(
            make_connection(self.__container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_fids = ",".join(
                str(row[0])
                for row in cursor.execute(
                    f"""
                    SELECT fid FROM ngw_features_metadata
                        WHERE ngw_fid IN ({ngw_fids});
                    """
                )
            )
            cursor.executescript(
                f"""
                DELETE FROM ngw_updated_attributes
                    WHERE fid in ({updated_fids});
                DELETE FROM ngw_updated_geometries
                    WHERE fid in ({updated_fids});
                """
            )
            connection.commit()
