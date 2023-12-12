import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from qgis.core import (
    QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer, QgsLayerTreeLayer,
    QgsTask, QgsApplication
)

from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.utils import iface

from .detached_layer_indicator import DetachedLayerIndicator
from .tasks.upload_changes_task import UploadChangesTask
from . import utils
from .utils import DetachedLayerState


class DetachedLayer(QObject):
    @dataclass
    class Status:
        added_features: int = 0
        removed_features: int = 0
        updated_attributes: int = 0
        updated_geometries: int = 0

    __layer: QgsVectorLayer
    __state: DetachedLayerState
    __indicator: Optional[DetachedLayerIndicator]
    __sync_task: Optional[QgsTask]

    state_changed = pyqtSignal(DetachedLayerState, name='stateChanged')

    def __init__(
        self, layer: QgsVectorLayer, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)

        self.__layer = layer
        self.__state = DetachedLayerState.NotInitialized
        self.__indicator = None
        self.__sync_task = None

        self.__fill_properties()

        # TODO check rights on edit etc

        # TODO datasourcechanged

        # TODO timer for update

        # TODO (PyQt6): remove type ignore
        self.__layer.editingStarted.connect(self.__start_listen_changes)  # type: ignore  # NOQA: E501
        self.__layer.editingStopped.connect(self.__stop_listen_changes)  # type: ignore  # NOQA: E501

    @property
    def container_path(self) -> str:
        return utils.container_path(self.__layer)

    @property
    def layer(self) -> QgsVectorLayer:
        return self.__layer

    @property
    def state(self) -> DetachedLayerState:
        return self.__state

    def synchronize(self) -> None:
        if self.state == DetachedLayerState.Synchronized:
            return

        self.__state = DetachedLayerState.Synchronization
        self.__layer.setCustomProperty('ngw_layer_state', str(self.__state))
        self.__layer.setReadOnly(True)
        self.__sync_task = UploadChangesTask(
            utils.container_path(self.__layer)
        )
        self.__sync_task.synchronization_finished.connect(
            self.__on_task_finished
        )

        task_manager = QgsApplication.taskManager()
        assert task_manager is not None
        task_manager.addTask(self.__sync_task)

    def force_synchronize(self) -> None:
        self.__state = DetachedLayerState.Synchronization
        self.__layer.setCustomProperty('ngw_layer_state', str(self.__state))

    def add_indicator(self, node: QgsLayerTreeLayer) -> None:
        assert isinstance(iface, QgisInterface)
        view = iface.layerTreeView()
        assert view is not None

        if self.__indicator is None:
            self.__create_indicator()

        if self.__indicator in view.indicators(node):
            return

        view.addIndicator(node, self.__indicator)

    def remove_indicator(self, node: Optional[QgsLayerTreeLayer] = None):
        if node is None:
            project = QgsProject.instance()
            assert project is not None
            root = project.layerTreeRoot()
            assert root is not None
            node = root.findLayer(self.__layer)

        assert isinstance(iface, QgisInterface)
        view = iface.layerTreeView()
        assert view is not None

        if self.__indicator not in view.indicators(node):
            return

        view.removeIndicator(node, self.__indicator)

    def __fill_properties(self) -> None:
        result = (None, None, None, None)
        with closing(sqlite3.connect(self.container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute('''
                    SELECT
                        connection_id, resource_id, synchronization_date,
                        auto_synchronization
                    FROM ngw_metadata
                ''')
                result = cursor.fetchone()

                self.__update_state(cursor)

        self.__layer.setCustomProperty('ngw_connection_id', result[0])
        self.__layer.setCustomProperty('ngw_resource_id', int(result[1]))
        self.__layer.setCustomProperty(
            'ngw_synchronization_date', datetime.fromisoformat(result[2])
        )
        self.__layer.setCustomProperty(
            'ngw_auto_synchronization', bool(result[3])
        )

    def __create_indicator(self) -> None:
        assert isinstance(iface, QgisInterface)

        project = QgsProject.instance()
        assert project is not None
        root = project.layerTreeRoot()
        assert root is not None

        node = root.findLayer(self.__layer.id())
        if node is None:
            raise RuntimeError('Detached layer is not found')

        view = iface.layerTreeView()
        assert view is not None
        self.__indicator = DetachedLayerIndicator(self.__layer, view)

    @pyqtSlot(name='startListenChanges')
    def __start_listen_changes(self) -> None:
        self.__layer.committedFeaturesAdded.connect(
            self.__log_added_features
        )
        self.__layer.committedFeaturesRemoved.connect(
            self.__log_removed_features
        )
        self.__layer.committedAttributeValuesChanges.connect(
            self.__log_attribute_values_changes
        )
        self.__layer.committedGeometriesChanges.connect(
            self.__log_geometry_changes
        )

    @pyqtSlot(name='stopListenChanges')
    def __stop_listen_changes(self) -> None:
        self.__layer.committedFeaturesAdded.disconnect(
            self.__log_added_features
        )
        self.__layer.committedFeaturesRemoved.disconnect(
            self.__log_removed_features
        )
        self.__layer.committedAttributeValuesChanges.disconnect(
            self.__log_attribute_values_changes
        )
        self.__layer.committedGeometriesChanges.disconnect(
            self.__log_geometry_changes
        )

        if self.__state == DetachedLayerState.NotSynchronized:
            self.synchronize()

    def __log_added_features(
        self, layer_id: str, features: List[QgsFeature]
    ) -> None:
        with closing(sqlite3.connect(self.container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.executemany(
                    'INSERT INTO ngw_added_features VALUES (?);',
                    list((feature.id(),) for feature in features)
                )
                self.__update_state(cursor)

            connection.commit()

    def __log_removed_features(
        self, layer_id: str, feature_ids: List[int]
    ) -> None:
        with closing(sqlite3.connect(self.container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                # Delete added feature fids
                added_fids = self.__extract_added_fids(cursor, feature_ids)
                delete_added_query = """
                    DELETE
                    FROM ngw_added_features
                    WHERE fid in ({fids})
                """.format(fids=','.join(['?'] * len(added_fids)))
                cursor.execute(delete_added_query, added_fids)

                # Synchronized features
                removed_fids = list(set(feature_ids) - set(added_fids))

                # Delete other logs
                fids_placeholder = ','.join(['?'] * len(removed_fids))
                delete_attributes_log_query = f"""
                    DELETE
                    FROM ngw_updated_attributes
                    WHERE fid in ({fids_placeholder});
                """
                cursor.execute(delete_attributes_log_query, removed_fids)
                delete_geometries_log_query = f"""
                    DELETE
                    FROM ngw_updated_geometries
                    WHERE fid in ({fids_placeholder});
                """
                cursor.execute(delete_geometries_log_query, removed_fids)

                # Log removed features
                cursor.executemany(
                    'INSERT INTO ngw_removed_features VALUES (?);',
                    list((fid,) for fid in removed_fids)
                )

                self.__update_state(cursor)

            connection.commit()

    def __log_attribute_values_changes(
        self, layer_id: str, changed_attributes: Dict[int, Dict[int, Any]]
    ) -> None:
        with closing(sqlite3.connect(self.container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                feature_ids = list(changed_attributes.keys())
                added_fids = self.__extract_added_fids(cursor, feature_ids)
                if len(feature_ids) == len(added_fids):
                    return
                changed_fids = list(set(feature_ids) - set(added_fids))
                attributes = []
                for fid in changed_fids:
                    for attribute in changed_attributes[fid]:
                        attributes.append((fid, attribute))
                cursor.executemany(
                    'INSERT INTO ngw_updated_attributes VALUES (?, ?);',
                    attributes
                )

                self.__update_state(cursor)

            connection.commit()

    def __log_geometry_changes(
        self, layer_id: str, changed_geometries: Dict[int, QgsGeometry]
    ) -> None:
        with closing(sqlite3.connect(self.container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                feature_ids = list(changed_geometries.keys())
                added_fids = self.__extract_added_fids(cursor, feature_ids)
                if len(feature_ids) == len(added_fids):
                    return
                changed_fids = list(set(feature_ids) - set(added_fids))
                cursor.executemany(
                    'INSERT INTO ngw_updated_geometries VALUES (?);',
                    list((fid,) for fid in changed_fids)
                )

                self.__update_state(cursor)

            connection.commit()

    def __extract_added_fids(
        self, cursor: sqlite3.Cursor, feature_ids: List[int]
    ) -> List[int]:
        fetch_added_query = """
            SELECT fid
            FROM ngw_added_features
            WHERE fid in ({placeholders})
        """.format(placeholders=','.join(['?'] * len(feature_ids)))
        cursor.execute(fetch_added_query, feature_ids)
        return [row[0] for row in cursor.fetchall()]

    def __has_changes(self, cursor: sqlite3.Cursor) -> bool:
        cursor.execute('''
            SELECT
                EXISTS(SELECT 1 FROM ngw_added_features)
                OR EXISTS(SELECT 1 FROM ngw_removed_features)
                OR EXISTS(SELECT 1 FROM ngw_updated_attributes)
                OR EXISTS(SELECT 1 FROM ngw_updated_geometries)
        ''')
        return bool(cursor.fetchone()[0])

    def __update_state(self, cursor: sqlite3.Cursor) -> None:
        state = DetachedLayerState.NotInitialized

        if (
            self.__sync_task is not None
            and self.__sync_task.status() not in (
                QgsTask.TaskStatus.Complete, QgsTask.TaskStatus.Terminated
            )
        ):
            state = DetachedLayerState.Synchronization
        else:
            state = (
                DetachedLayerState.NotSynchronized
                if self.__has_changes(cursor)
                else DetachedLayerState.Synchronized
            )

        self.__state = state
        self.__layer.setCustomProperty('ngw_layer_state', str(self.__state))

    def __on_task_finished(self, result: bool) -> None:
        if result:
            self.__state = DetachedLayerState.Synchronized
        else:
            self.__state = DetachedLayerState.Error
        self.__layer.setCustomProperty('ngw_layer_state', str(self.__state))

        self.__sync_task = None
        self.__layer.setReadOnly(False)
