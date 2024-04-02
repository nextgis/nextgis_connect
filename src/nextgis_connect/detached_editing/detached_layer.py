import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, List

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from .detached_container import DetachedContainer


class DetachedLayer(QObject):
    __container: "DetachedContainer"
    __layer: QgsVectorLayer

    layer_changed = pyqtSignal(name="layerChanged")
    editing_finished = pyqtSignal(name="editingFinished")

    def __init__(
        self,
        container: "DetachedContainer",
        layer: QgsVectorLayer,
    ) -> None:
        super().__init__(container)

        self.__container = container
        self.__layer = layer

        # TODO (PyQt6): remove type ignore
        self.__layer.editingStarted.connect(self.__start_listen_changes)  # type: ignore
        self.__layer.editingStopped.connect(self.__stop_listen_changes)  # type: ignore

    @property
    def layer(self) -> QgsVectorLayer:
        return self.__layer

    def fill_properties(self, metadata: DetachedContainerMetaData) -> None:
        properties = {
            "ngw_is_detached_layer": True,
            "ngw_connection_id": metadata.connection_id,
            "ngw_resource_id": metadata.resource_id,
            "ngw_sync_date": metadata.sync_date,
        }
        for name, value in properties.items():
            self.__layer.setCustomProperty(name, value)

    @pyqtSlot(name="startListenChanges")
    def __start_listen_changes(self) -> None:
        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f'Start listening changes in layer "{layer_name}" ({layer_id})'
        )

        self.__layer.committedFeaturesAdded.connect(self.__log_added_features)
        self.__layer.committedFeaturesRemoved.connect(
            self.__log_removed_features
        )
        self.__layer.committedAttributeValuesChanges.connect(
            self.__log_attribute_values_changes
        )
        self.__layer.committedGeometriesChanges.connect(
            self.__log_geometry_changes
        )

    @pyqtSlot(name="stopListenChanges")
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

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f'Stop listening changes in layer "{layer_name}" ({layer_id})'
        )

        self.editing_finished.emit()

    @pyqtSlot(str, "QgsFeatureList")
    def __log_added_features(self, _: str, features: List[QgsFeature]) -> None:
        with (
            closing(self.__container.make_connection()) as connection,
            closing(connection.cursor()) as cursor,
        ):
            cursor.executemany(
                "INSERT INTO ngw_added_features VALUES (?);",
                ((feature.id(),) for feature in features),
            )
            cursor.executemany(
                """
                INSERT INTO ngw_features_metadata
                VALUES (?, NULL, NULL, NULL);
                """,
                ((feature.id(),) for feature in features),
            )

            connection.commit()

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f'Added {len(features)} features in layer "{layer_name}" '
            f"({layer_id})"
        )

        self.layer_changed.emit()

    @pyqtSlot(str, "QgsFeatureIds")
    def __log_removed_features(self, _: str, feature_ids: List[int]) -> None:
        with (
            closing(self.__container.make_connection()) as connection,
            closing(connection.cursor()) as cursor,
        ):
            # Delete added feature fids
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )
            delete_added_query = """
                DELETE
                FROM ngw_added_features
                WHERE fid in ({fids})
            """.format(fids=",".join(["?"] * len(added_fids_intersection)))
            cursor.execute(delete_added_query, added_fids_intersection)

            # Synchronized features
            removed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(removed_fids) == 0:
                return

            # Delete other logs
            fids_placeholder = ", ".join(str(fid) for fid in removed_fids)
            delete_updated_log_query = f"""
                DELETE
                FROM ngw_updated_attributes
                WHERE fid in ({fids_placeholder});

                DELETE
                FROM ngw_updated_geometries
                WHERE fid in ({fids_placeholder});
            """
            cursor.executescript(delete_updated_log_query)

            # Log removed features
            cursor.executemany(
                "INSERT INTO ngw_removed_features VALUES (?)",
                ((fid,) for fid in removed_fids),
            )

            connection.commit()

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f'Removed {len(feature_ids)} features in layer "{layer_name}" '
            f"({layer_id})"
        )

        self.layer_changed.emit()

    @pyqtSlot(str, "QgsChangedAttributesMap")
    def __log_attribute_values_changes(
        self, _: str, changed_attributes: Dict[int, Dict[int, Any]]
    ) -> None:
        with (
            closing(self.__container.make_connection()) as connection,
            closing(connection.cursor()) as cursor,
        ):
            feature_ids = list(changed_attributes.keys())
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )
            changed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(changed_fids) == 0:
                return

            attributes = [
                (fid, attribute)
                for fid in changed_fids
                for attribute in changed_attributes[fid]
            ]
            cursor.executemany(
                "INSERT INTO ngw_updated_attributes VALUES (?, ?);",
                attributes,
            )

            connection.commit()

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f"Updated attributes for {len(feature_ids)} features in layer "
            f'"{layer_name}" ({layer_id})'
        )

        self.layer_changed.emit()

    @pyqtSlot(str, "QgsGeometryMap")
    def __log_geometry_changes(
        self, _: str, changed_geometries: Dict[int, QgsGeometry]
    ) -> None:
        with (
            closing(self.__container.make_connection()) as connection,
            closing(connection.cursor()) as cursor,
        ):
            feature_ids = list(changed_geometries.keys())
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )
            changed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(changed_fids) == 0:
                return

            cursor.executemany(
                "INSERT INTO ngw_updated_geometries VALUES (?);",
                list((fid,) for fid in changed_fids),
            )

            connection.commit()

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f"Updated geometries for {len(feature_ids)} features in layer "
            f'"{layer_name}" ({layer_id})'
        )

        self.layer_changed.emit()

    def __extract_intersection_with_added_fids(
        self, cursor: sqlite3.Cursor, feature_ids: List[int]
    ) -> List[int]:
        fetch_added_query = """
            SELECT fid
            FROM ngw_added_features
            WHERE fid in ({placeholders})
        """.format(placeholders=",".join(["?"] * len(feature_ids)))
        cursor.execute(fetch_added_query, feature_ids)
        return [row[0] for row in cursor.fetchall()]
