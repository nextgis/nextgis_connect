import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Tuple, cast

from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.compat import (
    QgsAttributeList,
    QgsChangedAttributesMap,
    QgsFeatureId,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)
from nextgis_connect.detached_editing.serialization import (
    deserialize_value,
    serialize_geometry,
    serialize_value,
    simplify_value,
)
from nextgis_connect.detached_editing.utils import (
    make_connection,
)
from nextgis_connect.exceptions import ContainerError
from nextgis_connect.logging import logger
from nextgis_connect.resources.ngw_field import FieldId
from nextgis_connect.types import NgwFeatureId

if TYPE_CHECKING:
    from .detached_container import DetachedContainer


class DetachedLayer(QObject):
    """Class for tracking changes and writing them to a container"""

    UPDATE_STATE_PROPERTY = "ngw_need_update_state"

    __container: "DetachedContainer"
    __qgs_layer: QgsVectorLayer

    __updated_attributes: Dict[Tuple[QgsFeatureId, FieldId], Any]
    __updated_geometries: Dict[QgsFeatureId, str]
    __deleted_features: Dict[QgsFeatureId, QgsFeature]

    __is_layer_changed: bool = False

    editing_started = pyqtSignal(name="editingStarted")
    editing_finished = pyqtSignal(name="editingFinished")
    layer_changed = pyqtSignal(name="layerChanged")
    structure_changed = pyqtSignal(name="structureChanged")
    settings_changed = pyqtSignal(name="settingsChanged")

    error_occured = pyqtSignal(ContainerError, name="errorOccured")

    def __init__(
        self,
        container: "DetachedContainer",
        layer: QgsVectorLayer,
    ) -> None:
        super().__init__(container)

        self.__container = container
        self.__qgs_layer = layer

        self.__reset_backup()

        # TODO (PyQt6): remove type ignore
        self.__qgs_layer.editingStarted.connect(self.__start_listen_changes)  # type: ignore
        self.__qgs_layer.editingStopped.connect(self.__stop_listen_changes)  # type: ignore
        self.__qgs_layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )
        self.__qgs_layer.afterCommitChanges.connect(self.__on_commit_changes)

        self.update()

        if layer.isEditable():
            self.__start_listen_changes()

    @property
    def qgs_layer(self) -> QgsVectorLayer:
        return self.__qgs_layer

    @property
    def is_edit_mode_enabled(self) -> bool:
        return self.__qgs_layer.isEditable()

    @pyqtSlot()
    def update(self) -> None:
        """Update detached layer properties"""

        if self.__container.metadata is None:
            return

        properties = {
            "ngw_is_detached_layer": True,
            "ngw_connection_id": self.__container.metadata.connection_id,
            "ngw_resource_id": self.__container.metadata.resource_id,
        }

        custom_properties = self.__qgs_layer.customProperties()
        for name, value in properties.items():
            custom_properties.setValue(name, value)

        self.__qgs_layer.customPropertyChanged.disconnect(
            self.__on_custom_property_changed
        )
        self.__qgs_layer.setCustomProperties(custom_properties)
        self.__qgs_layer.customPropertyChanged.connect(
            self.__on_custom_property_changed
        )

    @pyqtSlot()
    def __start_listen_changes(self) -> None:
        metadata = self.__container.metadata
        logger.debug(f"Start listening changes in layer {metadata}")

        self.__qgs_layer.committedFeaturesAdded.connect(
            self.__log_added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.connect(
            self.__log_removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.connect(
            self.__log_attribute_values_changes
        )
        self.__qgs_layer.committedGeometriesChanges.connect(
            self.__log_geometry_changes
        )

        self.__qgs_layer.committedAttributesAdded.connect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.connect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.connect(self.__create_backup)

        self.editing_started.emit()

    @pyqtSlot()
    def __stop_listen_changes(self) -> None:
        self.__qgs_layer.committedFeaturesAdded.disconnect(
            self.__log_added_features
        )
        self.__qgs_layer.committedFeaturesRemoved.disconnect(
            self.__log_removed_features
        )
        self.__qgs_layer.committedAttributeValuesChanges.disconnect(
            self.__log_attribute_values_changes
        )
        self.__qgs_layer.committedGeometriesChanges.disconnect(
            self.__log_geometry_changes
        )

        self.__qgs_layer.committedAttributesAdded.disconnect(
            self.__on_attribute_added
        )
        self.__qgs_layer.committedAttributesDeleted.disconnect(
            self.__on_attribute_deleted
        )

        self.__qgs_layer.beforeCommitChanges.disconnect(self.__create_backup)

        self.__reset_backup()

        metadata = self.__container.metadata
        logger.debug(f"Stop listening changes in layer {metadata}")

        self.editing_finished.emit()

    @pyqtSlot(str, "QgsFeatureList")
    def __log_added_features(self, _: str, features: QgsFeatureList) -> None:
        ng_error = None
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                added_fids = ",".join(
                    map(lambda feature: f"({feature.id()})", features)
                )
                cursor.executescript(
                    f"""
                    INSERT INTO ngw_features_metadata (fid) VALUES {added_fids};
                    INSERT INTO ngw_added_features (fid) VALUES {added_fids};
                    """
                )

                connection.commit()

        except Exception as error:
            message = "Can't create adding changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.error_occured.emit(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(f"Added {len(features)} features in layer {metadata}")

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsFeatureIds")
    def __log_removed_features(
        self, _: str, removed_feature_ids: QgsFeatureIds
    ) -> None:
        ng_error = None

        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                # Delete added feature fids
                removed_not_uploaded_fids = (
                    self.__extract_intersection_with_added_fids(
                        cursor, removed_feature_ids
                    )
                )
                self.__remove_features_metadata(
                    cursor, removed_not_uploaded_fids
                )

                # Synchronized features
                removed_uploaded_fids = set(removed_feature_ids) - set(
                    removed_not_uploaded_fids
                )
                self.__add_remove_records(cursor, removed_uploaded_fids)

                connection.commit()

        except Exception as error:
            message = "Can't create deletion changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.error_occured.emit(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Removed {len(removed_feature_ids)} features in layer {metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsChangedAttributesMap")
    def __log_attribute_values_changes(
        self, _: str, changed_attributes: QgsChangedAttributesMap
    ) -> None:
        ng_error = None
        feature_ids = set()

        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                feature_ids = set(changed_attributes.keys())
                added_fids_intersection = (
                    self.__extract_intersection_with_added_fids(
                        cursor, feature_ids
                    )
                )
                changed_fids = set(feature_ids) - set(added_fids_intersection)
                if len(changed_fids) > 0:
                    cursor.executemany(
                        """
                        INSERT INTO ngw_updated_attributes (fid, attribute, backup)
                        VALUES (?, ?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            (
                                fid,
                                attribute,
                                self.__updated_attributes[(fid, attribute)],
                            )
                            for fid in changed_fids
                            for attribute in changed_attributes[fid]
                        ),
                    )
                    connection.commit()

        except Exception as error:
            message = "Can't create values changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.error_occured.emit(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated attributes for {len(feature_ids)} features in layer "
            f"{metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QgsGeometryMap")
    def __log_geometry_changes(
        self, _: str, changed_geometries: QgsGeometryMap
    ) -> None:
        ng_error = None

        feature_ids: QgsFeatureIds = set()
        try:
            with closing(
                make_connection(self.__qgs_layer)
            ) as connection, closing(connection.cursor()) as cursor:
                feature_ids = set(changed_geometries.keys())
                added_fids_intersection = (
                    self.__extract_intersection_with_added_fids(
                        cursor, feature_ids
                    )
                )
                changed_fids = set(feature_ids) - set(added_fids_intersection)
                if len(changed_fids) > 0:
                    cursor.executemany(
                        """
                        INSERT INTO ngw_updated_geometries (fid, backup)
                        VALUES (?, ?)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            (fid, self.__updated_geometries[fid])
                            for fid in changed_fids
                        ),
                    )
                    connection.commit()

        except Exception as error:
            message = "Can't create geometry changes records"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.error_occured.emit(ng_error)
            return

        metadata = self.__container.metadata
        logger.debug(
            f"Updated geometries for {len(feature_ids)} features in layer "
            f"{metadata}"
        )

        self.__is_layer_changed = True

    @pyqtSlot(str, "QList<QgsField>")
    def __on_attribute_added(
        self, layer_id: str, added_attributes: List[QgsField]
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Added {len(added_attributes)} attributes in layer {metadata}"
        )

        self.structure_changed.emit()

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
        self, layer_id, deleted_attributes: QgsAttributeList
    ) -> None:
        metadata = self.__container.metadata
        logger.debug(
            f"Removed {len(deleted_attributes)} attributes in layer {metadata}"
        )

        container_fields_name = set(
            field.name() for field in self.__qgs_layer.fields()
        )
        if all(
            ngw_field.keyname in container_fields_name
            for ngw_field in metadata.fields
        ):
            return

        self.structure_changed.emit()

        QMessageBox.warning(
            None,
            self.tr("Layer structure changed"),
            self.tr(
                "Deleting a column is only possible from the NextGIS Web interface."
                "\n\nFurther work with the layer is possible only after the"
                " layer reset. You can do this from the sync status window."
            ),
        )

    @pyqtSlot(str)
    def __on_custom_property_changed(self, name: str) -> None:
        need_emit = (
            name == self.UPDATE_STATE_PROPERTY
            and self.qgs_layer.customProperty(
                self.UPDATE_STATE_PROPERTY, defaultValue=False
            )
        )
        self.qgs_layer.removeCustomProperty(self.UPDATE_STATE_PROPERTY)

        if need_emit:
            self.settings_changed.emit()

    @pyqtSlot(bool)
    def __create_backup(self, stop_editing: bool) -> None:
        ng_error = None

        try:
            self.__create_backup_for_updated_fields()
            self.__create_backup_for_updated_geometries()
            self.__create_backup_for_deleted()
        except Exception as error:
            message = "Can't create backup before changes"
            ng_error = ContainerError(message)
            ng_error.__cause__ = deepcopy(error)

        if ng_error is not None:
            self.error_occured.emit(ng_error)

    def __extract_intersection_with_added_fids(
        self, cursor: sqlite3.Cursor, feature_ids: QgsFeatureIds
    ) -> QgsFeatureIds:
        fetch_added_query = """
            SELECT fid
            FROM ngw_added_features
            WHERE fid in ({placeholders})
        """.format(placeholders=",".join(map(str, feature_ids)))
        cursor.execute(fetch_added_query)
        return set(row[0] for row in cursor.fetchall())

    def __create_backup_for_updated_fields(self) -> None:
        changed_attributes_info: QgsChangedAttributesMap = (
            self.__qgs_layer.editBuffer().changedAttributeValues()
        )
        if len(changed_attributes_info) == 0:
            return

        features_before_change = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(list(changed_attributes_info.keys()))
            ),
        )
        self.__updated_attributes.update(
            (
                (feature.id(), attribute),
                serialize_value(feature.attribute(attribute)),
            )
            for feature in features_before_change
            for attribute in changed_attributes_info[feature.id()].keys()
        )

    def __create_backup_for_updated_geometries(self) -> None:
        changed_geometries_info: QgsGeometryMap = (
            self.__qgs_layer.editBuffer().changedGeometries()
        )
        if len(changed_geometries_info) == 0:
            return

        features_before_change = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(list(changed_geometries_info.keys()))
            ),
        )
        self.__updated_geometries.update(
            (
                feature.id(),
                serialize_geometry(
                    feature.geometry(),
                    self.__container.metadata.is_versioning_enabled,
                ),
            )
            for feature in features_before_change
        )

    def __create_backup_for_deleted(self) -> None:
        deleted_features_id: QgsFeatureIds = (
            self.__qgs_layer.editBuffer().deletedFeatureIds()
        )
        if len(deleted_features_id) == 0:
            return

        deleted_features = cast(
            Iterable[QgsFeature],
            self.__qgs_layer.dataProvider().getFeatures(
                QgsFeatureRequest(deleted_features_id)
            ),
        )
        self.__deleted_features = {
            feature.id(): feature for feature in deleted_features
        }

    def __reset_backup(self) -> None:
        self.__updated_attributes = dict()
        self.__updated_geometries = dict()
        self.__deleted_features = dict()

    def __remove_features_metadata(
        self, cursor: sqlite3.Cursor, fids: QgsFeatureIds
    ) -> None:
        if len(fids) == 0:
            return

        joined_fids = ",".join(map(str, fids))
        cursor.executescript(
            f"""
            DELETE FROM ngw_features_metadata WHERE fid in ({joined_fids});
            """
        )

    def __add_remove_records(
        self, cursor: sqlite3.Cursor, removed_fids: QgsFeatureIds
    ) -> None:
        if len(removed_fids) == 0:
            return

        joined_removed_fids = ",".join(map(str, removed_fids))
        fields_backups = self.__extract_fields_backups(
            cursor, joined_removed_fids
        )
        geometries_backups = self.__extract_geometries_backups(
            cursor, joined_removed_fids
        )

        features_backup = self.__serialize_deletion_backup(
            removed_fids, fields_backups, geometries_backups
        )

        # Update records
        removed_records = ",".join(
            map(
                lambda fid: f"({fid}, '{json.dumps(features_backup[fid])}')",
                removed_fids,
            )
        )
        script = f"""
            INSERT INTO ngw_removed_features (fid, backup)
                VALUES {removed_records};
        """

        if len(fields_backups) > 0:
            script += f"""
            DELETE FROM ngw_updated_attributes
                WHERE fid in ({joined_removed_fids});
            """
        if len(geometries_backups) > 0:
            script += f"""
            DELETE FROM ngw_updated_geometries
                WHERE fid in ({joined_removed_fids});
            """

        cursor.executescript(script)

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

    def __serialize_deletion_backup(
        self,
        fids: Iterable[NgwFeatureId],
        fields_backups: Dict[Tuple[QgsFeatureId, FieldId], str],
        geometries_backups: Dict[QgsFeatureId, str],
    ) -> Dict[NgwFeatureId, Dict[str, Any]]:
        result = {}

        for fid in fids:
            feature = self.__deleted_features[fid]

            fields_after_sync = []
            fields_before_deletion = []

            for field in self.__container.metadata.fields:
                value_before_deletion = simplify_value(
                    feature.attribute(field.attribute)
                )
                value_after_sync = fields_backups.get(
                    (fid, field.attribute), value_before_deletion
                )
                fields_after_sync.append([field.ngw_id, value_after_sync])
                fields_before_deletion.append(
                    [field.ngw_id, value_before_deletion]
                )

            serialized_geometry = serialize_geometry(
                feature.geometry(),
                self.__container.metadata.is_versioning_enabled,
            )
            feature_record = {
                "after_sync": {
                    "fields": fields_after_sync,
                    "geom": geometries_backups.get(fid, serialized_geometry),
                },
                "before_deletion": {
                    "fields": fields_before_deletion,
                    "geom": serialized_geometry,
                },
            }
            result[fid] = feature_record

        return result
    
    def __on_commit_changes(self) -> None:
        if self.__is_layer_changed:
            self.layer_changed.emit()
        self.__is_layer_changed = False
