import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, List

from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from .detached_container import DetachedContainer


class DetachedLayer(QObject):
    __container: "DetachedContainer"
    __layer: QgsVectorLayer

    editing_started = pyqtSignal(name="editingStarted")
    editing_finished = pyqtSignal(name="editingFinished")
    layer_changed = pyqtSignal(name="layerChanged")

    settings_changed = pyqtSignal(name="settingsChanged")

    def __init__(
        self,
        container: "DetachedContainer",
        layer: QgsVectorLayer,
    ) -> None:
        super().__init__(container)

        self.__container = container
        self.__layer = layer

        self.fill_properties(self.__container.metadata)

        # TODO (PyQt6): remove type ignore
        self.__layer.editingStarted.connect(self.__start_listen_changes)  # type: ignore
        self.__layer.editingStopped.connect(self.__stop_listen_changes)  # type: ignore
        self.__layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )

        if layer.isEditable():
            self.__start_listen_changes()

    @property
    def layer(self) -> QgsVectorLayer:
        return self.__layer

    @property
    def is_edit_mode_enabled(self) -> bool:
        return self.__layer.isEditable()

    def fill_properties(self, metadata: DetachedContainerMetaData) -> None:
        if metadata is None:
            return

        properties = {
            "ngw_is_detached_layer": True,
            "ngw_connection_id": metadata.connection_id,
            "ngw_resource_id": metadata.resource_id,
        }

        custom_properties = self.__layer.customProperties()
        for name, value in properties.items():
            custom_properties.setValue(name, value)
        self.__layer.setCustomProperties(custom_properties)

    @pyqtSlot()
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

        self.__layer.committedAttributesAdded.connect(
            self.__on_attribute_added
        )
        self.__layer.committedAttributesDeleted.connect(
            self.__on_attribute_deleted
        )

        self.editing_started.emit()

    @pyqtSlot()
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

        self.__layer.committedAttributesAdded.disconnect(
            self.__on_attribute_added
        )
        self.__layer.committedAttributesDeleted.disconnect(
            self.__on_attribute_deleted
        )

        layer_name = self.__container.metadata.layer_name
        layer_id = self.__layer.id()
        logger.debug(
            f'Stop listening changes in layer "{layer_name}" ({layer_id})'
        )

        self.editing_finished.emit()

    @pyqtSlot(str, "QgsFeatureList")
    def __log_added_features(self, _: str, features: List[QgsFeature]) -> None:
        with closing(
            self.__container.make_connection()
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.executemany(
                "INSERT INTO ngw_added_features (fid) VALUES (?);",
                ((feature.id(),) for feature in features),
            )
            cursor.executemany(
                "INSERT INTO ngw_features_metadata (fid) VALUES (?)",
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
        with closing(
            self.__container.make_connection()
        ) as connection, closing(connection.cursor()) as cursor:
            # Delete added feature fids
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )

            joined_added_fids = ",".join(map(str, added_fids_intersection))
            delete_added_query = f"""
                DELETE FROM ngw_added_features
                    WHERE fid in ({joined_added_fids})
            """
            cursor.execute(delete_added_query)

            # Synchronized features
            removed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(removed_fids) == 0:
                connection.commit()
                self.layer_changed.emit()
                return

            # Delete other logs
            joined_removed_fids = ",".join(map(str, removed_fids))
            delete_updated_log_query = f"""
                DELETE FROM ngw_updated_attributes
                    WHERE fid in ({joined_removed_fids});

                DELETE FROM ngw_updated_geometries
                    WHERE fid in ({joined_removed_fids});
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
        with closing(
            self.__container.make_connection()
        ) as connection, closing(connection.cursor()) as cursor:
            feature_ids = list(changed_attributes.keys())
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )
            changed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(changed_fids) == 0:
                self.layer_changed.emit()
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
        with closing(
            self.__container.make_connection()
        ) as connection, closing(connection.cursor()) as cursor:
            feature_ids = list(changed_geometries.keys())
            added_fids_intersection = (
                self.__extract_intersection_with_added_fids(
                    cursor, feature_ids
                )
            )
            changed_fids = set(feature_ids) - set(added_fids_intersection)
            if len(changed_fids) == 0:
                self.layer_changed.emit()
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

    @pyqtSlot(str, "QList<QgsField>")
    def __on_attribute_added(
        self, layer_id: str, added_attributes: List[QgsField]
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Added {len(added_attributes)} attributes in layer {metadata}"
        )

        QMessageBox.warning(
            None,
            self.tr("Layer structure changed"),
            self.tr(
                "Added columns in QGIS will not be added to NextGIS Web layer."
                "\n\nIf you want to change the layer structure, please do so"
                " in the NextGIS Web interface and reset the layer in sync"
                " status window."
            ),
        )

    @pyqtSlot(str, "QgsAttributeList")
    def __on_attribute_deleted(
        self, layer_id, deleted_attributes: List[int]
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Removed {len(deleted_attributes)} attributes in layer {metadata}"
        )

        container_fields_name = set(
            field.name() for field in self.__layer.fields()
        )
        if all(
            ngw_field.keyname in container_fields_name
            for ngw_field in metadata.fields
        ):
            return

        QMessageBox.warning(
            None,
            self.tr("Layer structure changed"),
            self.tr(
                "Deleting a column is only possible from the NextGIS Web interface."
                "\n\nFurther work with the layer is possible only after the"
                " layer reset. You can do this from the sync status window."
            ),
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

    @pyqtSlot(str)
    def __on_custom_property_changed(self, name: str) -> None:
        update_state_name = "ngw_need_update_state"
        if name != update_state_name or not self.layer.customProperty(
            update_state_name
        ):
            return

        self.layer.setCustomProperty("ngw_need_update_state", False)
        self.settings_changed.emit()
