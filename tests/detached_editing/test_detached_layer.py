import json
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Set, Tuple
from unittest.mock import MagicMock, call, patch, sentinel

from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsVectorLayer, edit
from qgis.PyQt.QtCore import QObject, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.compat import (
    FieldType,
    QgsChangedAttributesMap,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)
from nextgis_connect.detached_editing.detached_layer import DetachedLayer
from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
    serialize_value,
    simplify_value,
)
from nextgis_connect.detached_editing.utils import (
    make_connection,
)
from nextgis_connect.exceptions import ContainerError, DetachedEditingError
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestData,
)


def mock_layer_signals(layer: DetachedLayer) -> MagicMock:
    signals_mock = MagicMock()
    layer.editing_started = signals_mock.editing_started
    layer.editing_finished = signals_mock.editing_finished
    layer.layer_changed = signals_mock.layer_changed
    layer.structure_changed = signals_mock.structure_changed
    layer.settings_changed = signals_mock.settings_changed
    layer.error_occurred = signals_mock.error_occurred
    layer.description_updated = signals_mock.description_updated
    return signals_mock


def set_layer_error_assert(layer: DetachedLayer) -> None:
    def _error_assert(error: ContainerError) -> None:
        raise error

    layer.error_occurred.connect(_error_assert)


class LayerChangesLogger(QObject):
    added_fids: Set[int]
    removed_fids: Set[int]
    updated_attribute_fids: Set[Tuple[int, int]]
    updated_geometry_fids: Set[int]

    def __init__(self, layer: QgsVectorLayer) -> None:
        super().__init__(layer)

        self.added_fids = set()
        self.removed_fids = set()
        self.updated_attribute_fids = set()
        self.updated_geometry_fids = set()

        layer.committedFeaturesAdded.connect(self.__log_added_features)
        layer.committedFeaturesRemoved.connect(self.__log_removed_features)
        layer.committedAttributeValuesChanges.connect(
            self.__log_attribute_values_changes
        )
        layer.committedGeometriesChanges.connect(self.__log_geometry_changes)

    @pyqtSlot(str, "QgsFeatureList")
    def __log_added_features(self, _: str, features: QgsFeatureList) -> None:
        self.added_fids.update(feature.id() for feature in features)

    @pyqtSlot(str, "QgsFeatureIds")
    def __log_removed_features(
        self, _: str, feature_ids: QgsFeatureIds
    ) -> None:
        self.removed_fids.update(feature_ids)

    @pyqtSlot(str, "QgsChangedAttributesMap")
    def __log_attribute_values_changes(
        self, _: str, changed_attributes: QgsChangedAttributesMap
    ) -> None:
        self.updated_attribute_fids.update(
            (fid, aid)
            for fid, attributes in changed_attributes.items()
            for aid, _ in attributes.items()
        )

    @pyqtSlot(str, "QgsGeometryMap")
    def __log_geometry_changes(
        self, _: str, changed_geometries: QgsGeometryMap
    ) -> None:
        self.updated_geometry_fids.update(changed_geometries.keys())


class ChangesChecker:
    container_path: Path

    def __init__(self, container_path: Path) -> None:
        self.container_path = container_path

    def added_is_equal(self, added_fids: Iterable[int]) -> bool:
        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            fids_without_ngw_id = set(
                row[0]
                for row in cursor.execute(
                    "SELECT fid FROM ngw_features_metadata WHERE ngw_fid IS NULL"
                )
            )
            writed_fids = set(
                row[0]
                for row in cursor.execute("SELECT fid FROM ngw_added_features")
            )

        return fids_without_ngw_id == writed_fids == set(added_fids)

    def removed_is_equal(self, removed_fids: Iterable[int]) -> bool:
        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            writed_fids = set(
                row[0]
                for row in cursor.execute(
                    "SELECT fid FROM ngw_removed_features"
                )
            )

        return writed_fids == set(removed_fids)

    def updated_attributes_is_equal(
        self, updated: Iterable[Tuple[int, int]]
    ) -> bool:
        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_attributes = set(
                (row[0], row[1])
                for row in cursor.execute(
                    "SELECT fid, attribute FROM ngw_updated_attributes"
                )
            )

        return updated_attributes == set(updated)

    def updated_geometries_is_equal(self, updated_fids: Iterable[int]) -> bool:
        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            writed_fids = set(
                row[0]
                for row in cursor.execute(
                    "SELECT fid FROM ngw_updated_geometries"
                )
            )

        return writed_fids == set(updated_fids)

    def updated_descriptions_is_equal(
        self, updated_fids: Iterable[int]
    ) -> bool:
        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            writed_fids = set(
                row[0]
                for row in cursor.execute(
                    "SELECT fid FROM ngw_updated_descriptions"
                )
            )

        return writed_fids == set(updated_fids)

    def assert_changes_equal(self, logger: LayerChangesLogger) -> None:
        assert self.added_is_equal(logger.added_fids)
        assert self.removed_is_equal(logger.removed_fids)
        assert self.updated_attributes_is_equal(logger.updated_attribute_fids)
        assert self.updated_geometries_is_equal(logger.updated_geometry_fids)


class TestDetachedLayer(NgConnectTestCase):
    @mock_container(TestData.Points)
    def test_emits_signals_on_start_and_stop_editing(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        # Start editing, then rollback; signals should be emitted
        self.assertTrue(qgs_layer.startEditing())
        self.assertTrue(layer.is_edit_mode_enabled)
        self.assertTrue(qgs_layer.rollBack())

        # Start editing again, then commit; signals should be emitted
        self.assertTrue(qgs_layer.startEditing())
        self.assertTrue(layer.is_edit_mode_enabled)
        self.assertTrue(qgs_layer.commitChanges())

        self.assertEqual(
            signals_mock.mock_calls,
            2 * [call.editing_started.emit(), call.editing_finished.emit()],
        )

    @mock_container(TestData.Points)
    def test_emits_signals_when_already_in_edit_mode(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        signals_mock = MagicMock()

        # Pre-enable editing to check signal behavior on instantiation
        qgs_layer.startEditing()

        module = "nextgis_connect.detached_editing.detached_layer"
        with patch(
            f"{module}.DetachedLayer.editing_started"
        ) as editing_started_mock, patch(
            f"{module}.DetachedLayer.editing_finished"
        ) as editing_finished_mock:
            signals_mock.attach_mock(editing_started_mock, "editing_started")
            signals_mock.attach_mock(editing_finished_mock, "editing_finished")

            layer = DetachedLayer(container_mock, qgs_layer)
            self.assertTrue(layer.is_edit_mode_enabled)

            qgs_layer.commitChanges()

        self.assertEqual(
            signals_mock.mock_calls,
            [call.editing_started.emit(), call.editing_finished.emit()],
        )

    @mock_container(TestData.Points)
    def test_sets_and_updates_ngw_properties(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        qgs_layer.setCustomProperty("not_ngw_property_is_same", True)

        def check_properties():
            self.assertTrue(
                qgs_layer.customProperty("not_ngw_property_is_same")
            )
            self.assertTrue(qgs_layer.customProperty("ngw_is_detached_layer"))
            self.assertEqual(
                qgs_layer.customProperty("ngw_connection_id"),
                container_mock.metadata.connection_id,
            )
            self.assertEqual(
                qgs_layer.customProperty("ngw_resource_id"),
                container_mock.metadata.resource_id,
            )

        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)
        check_properties()

        container_mock.metadata = replace(
            container_mock.metadata,
            connection_id=sentinel.NGW_CONNECTION_ID,
        )

        layer.update()
        check_properties()

    @mock_container(TestData.Points)
    def test_emits_settings_changed_on_update_state_property(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        # Should NOT emit when unrelated property changes
        qgs_layer.setCustomProperty("not_ngw_property", True)
        signals_mock.assert_not_called()

        # Should NOT emit on metadata update alone
        container_mock.metadata = replace(
            container_mock.metadata,
            connection_id=sentinel.NGW_CONNECTION_ID,
        )
        layer.update()

        signals_mock.assert_not_called()

        # Should emit when explicit update state flag is set
        qgs_layer.setCustomProperty(DetachedLayer.UPDATE_STATE_PROPERTY, True)
        signals_mock.settings_changed.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_tracks_added_features_and_commits(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        changes_logger = LayerChangesLogger(qgs_layer)

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())

        with edit(layer.qgs_layer):
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))

        with edit(layer.qgs_layer):
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))

        self.assertEqual(
            signals_mock.mock_calls,
            2
            * [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertTrue(len(changes_logger.added_fids) == 3)
        changes_checker = ChangesChecker(container_mock.path)
        changes_checker.assert_changes_equal(changes_logger)

    @mock_container(TestData.Points, descriptions={1: "<TEST_BEFORE>"})
    def test_deletes_feature_and_stores_backups(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        STRING_FIELD = qgs_layer.fields().indexOf("STRING")
        INITIAL_STRING_VALUE = "'WRAPPED VALUE\""
        INITIAL_GEOMETRY = QgsGeometry.fromWkt("POINT (0 0)")
        self.assertFalse(INITIAL_GEOMETRY.isNull())

        # Prepare initial feature state (geometry + attribute)
        feature_id = 1
        self.assertTrue(
            qgs_layer.dataProvider().changeGeometryValues(
                {feature_id: INITIAL_GEOMETRY}
            )
        )
        self.assertTrue(
            qgs_layer.dataProvider().changeAttributeValues(
                {feature_id: {STRING_FIELD: INITIAL_STRING_VALUE}}
            )
        )

        feature = qgs_layer.getFeature(feature_id)

        changes_logger = LayerChangesLogger(qgs_layer)

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        NEW_STRING_VALUE = INITIAL_STRING_VALUE + "_1"
        NEW_GEOMETRY = QgsGeometry.fromWkt("POINT (1 1)")
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, STRING_FIELD, NEW_STRING_VALUE
                )
            )
            self.assertTrue(qgs_layer.changeGeometry(feature_id, NEW_GEOMETRY))
            layer.set_feature_description(feature_id, "<TEST_AFTER>")

        edited_feature = qgs_layer.getFeature(feature_id)

        with edit(qgs_layer):
            is_removed = qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(feature_id, "<TEST_AFTER>"),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertTrue(len(changes_logger.removed_fids) == 1)
        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(
            changes_checker.added_is_equal(changes_logger.added_fids)
        )
        self.assertTrue(
            changes_checker.removed_is_equal(changes_logger.removed_fids)
        )
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            deleted_features = list(
                cursor.execute("SELECT fid, backup FROM ngw_removed_features")
            )

        deleted_feature = deleted_features[0]
        self.assertEqual(deleted_feature[0], feature.id())

        backup = json.loads(deleted_feature[1])

        # Check fields backups

        after_sync_fields = {
            field[0]: field[1] for field in backup["after_sync"]["fields"]
        }
        before_deletion_fields = {
            field[0]: field[1] for field in backup["before_deletion"]["fields"]
        }
        for field in container_mock.metadata.fields:
            self.assertEqual(
                simplify_value(feature.attribute(field.attribute)),
                after_sync_fields.get(field.ngw_id),
            )
            self.assertEqual(
                simplify_value(edited_feature.attribute(field.attribute)),
                before_deletion_fields.get(field.ngw_id),
            )

        # Check geometries backups

        self.assertEqual(
            INITIAL_GEOMETRY.asWkt(),
            deserialize_geometry(
                backup["after_sync"]["geom"],
                container_mock.metadata.is_versioning_enabled,
            ).asWkt(),
        )
        self.assertEqual(
            NEW_GEOMETRY.asWkt(),
            deserialize_geometry(
                backup["before_deletion"]["geom"],
                container_mock.metadata.is_versioning_enabled,
            ).asWkt(),
        )

        # Check descriptions backups
        after_desc = backup["after_sync"]["description"]
        before_desc = backup["before_deletion"]["description"]

        self.assertIsInstance(after_desc, dict)
        self.assertEqual("<TEST_BEFORE>", after_desc.get("value"))
        self.assertEqual(12345, after_desc.get("version"))

        self.assertIsInstance(before_desc, dict)
        self.assertEqual("<TEST_AFTER>", before_desc.get("value"))
        self.assertEqual(12345, before_desc.get("version"))

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        extra_features_count=10000,
        empty_features=True,
    )
    def test_mass_delete_features_is_tracked_and_committed(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        changes_logger = LayerChangesLogger(qgs_layer)

        with edit(layer.qgs_layer):
            feature_ids = qgs_layer.allFeatureIds()
            self.assertTrue(layer.qgs_layer.deleteFeatures(feature_ids))

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(container_mock.path)
        changes_checker.assert_changes_equal(changes_logger)

    @mock_container(TestData.Points)
    def test_updates_attributes_and_stores_original_backups(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        INTEGER_FIELD = qgs_layer.fields().indexOf("INTEGER")
        INITIAL_INTEGER_VALUE = 123
        STRING_FIELD = qgs_layer.fields().indexOf("STRING")
        INITIAL_STRING_VALUE = "'WRAPPED VALUE\""

        feature_id = list(sorted(qgs_layer.allFeatureIds()))[1]
        self.assertTrue(
            qgs_layer.dataProvider().changeAttributeValues(
                {
                    feature_id: {
                        STRING_FIELD: INITIAL_STRING_VALUE,
                        INTEGER_FIELD: INITIAL_INTEGER_VALUE,
                    },
                }
            )
        )

        changes_logger = LayerChangesLogger(qgs_layer)

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        NEW_INTEGER_VALUE = INITIAL_INTEGER_VALUE + 1
        NEW_STRING_VALUE = INITIAL_STRING_VALUE + "_1"
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, INTEGER_FIELD, NEW_INTEGER_VALUE
                )
            )
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, STRING_FIELD, NEW_STRING_VALUE
                )
            )

        VERY_NEW_INTEGER_VALUE = NEW_INTEGER_VALUE + 1
        with edit(qgs_layer):
            # Check PK constraints
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, STRING_FIELD, VERY_NEW_INTEGER_VALUE
                )
            )

        self.assertEqual(
            signals_mock.mock_calls,
            2
            * [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertTrue(len(changes_logger.updated_attribute_fids) == 2)
        changes_checker = ChangesChecker(container_mock.path)
        changes_checker.assert_changes_equal(changes_logger)

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            backup = {
                (row[0], row[1]): deserialize_value(row[2])
                for row in cursor.execute(
                    f"""
                    SELECT fid, attribute, backup FROM ngw_updated_attributes
                    WHERE fid = {feature_id};
                    """
                )
            }

        self.assertEqual(
            backup[(feature_id, INTEGER_FIELD)], INITIAL_INTEGER_VALUE
        )
        self.assertEqual(
            backup[(feature_id, STRING_FIELD)], INITIAL_STRING_VALUE
        )

    @mock_container(TestData.Points)
    def test_updates_geometry_and_stores_backup(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        INITIAL_GEOMETRY = QgsGeometry.fromWkt("POINT (0 0)")
        self.assertFalse(INITIAL_GEOMETRY.isNull())

        feature_id = next(iter(sorted(qgs_layer.allFeatureIds())))
        qgs_layer.dataProvider().changeGeometryValues(
            {feature_id: INITIAL_GEOMETRY}
        )

        changes_logger = LayerChangesLogger(qgs_layer)

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(qgs_layer):
            is_changed = qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)

        with edit(qgs_layer):
            # Check PK constraints
            is_changed = qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (2 2)")
            )
            self.assertTrue(is_changed)

        self.assertEqual(
            signals_mock.mock_calls,
            2
            * [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertTrue(len(changes_logger.updated_geometry_fids) == 1)
        changes_checker = ChangesChecker(container_mock.path)
        changes_checker.assert_changes_equal(changes_logger)

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            backup = {
                row[0]: deserialize_geometry(
                    row[1], container_mock.metadata.is_versioning_enabled
                )
                for row in cursor.execute(
                    f"""
                    SELECT fid, backup FROM ngw_updated_geometries
                    WHERE fid = {feature_id};
                    """
                )
            }

        self.assertEqual(backup[feature_id].asWkt(), INITIAL_GEOMETRY.asWkt())

    @mock_container(TestData.Points)
    def test_new_feature_attribute_and_geometry_changes_not_logged_as_updates(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        changes_logger = LayerChangesLogger(qgs_layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        with edit(layer.qgs_layer):
            # Add feature
            is_added = layer.qgs_layer.addFeature(new_feature)
            self.assertTrue(is_added)
            qgs_layer.commitChanges(stopEditing=False)

            feature_id = next(iter(changes_logger.added_fids))

            # Update fields
            is_changed = qgs_layer.changeAttributeValue(
                feature_id, attribute_index, "b"
            )
            self.assertTrue(is_changed)
            qgs_layer.commitChanges(stopEditing=False)

            # Change geometry
            is_changed = qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)
            qgs_layer.commitChanges(stopEditing=False)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.added_is_equal({feature_id}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))

    @mock_container(TestData.Points)
    def test_rollback_clears_all_uncommitted_changes(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        try:
            with edit(layer.qgs_layer):
                # Add feature
                is_added = layer.qgs_layer.addFeature(new_feature)
                self.assertTrue(is_added)

                feature_id = qgs_layer.allFeatureIds()[0]

                # Update fields
                is_changed = qgs_layer.changeAttributeValue(
                    feature_id, attribute_index, "b"
                )
                self.assertTrue(is_changed)

                # Change geometry
                is_changed = qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
                self.assertTrue(is_changed)

                feature_id = qgs_layer.allFeatureIds()[1]

                # Remove feature
                is_removed = qgs_layer.deleteFeature(feature_id)
                self.assertTrue(is_removed)

                layer.set_feature_description(feature_id, "<TEST_DESCRIPTION>")

                raise RuntimeError  # Force rollback via exception

        except Exception:
            pass

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))

    @mock_container(TestData.Points)
    def test_add_then_delete_new_feature_has_no_persisted_changes(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        changes_logger = LayerChangesLogger(qgs_layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        with edit(layer.qgs_layer):
            # Add feature
            is_added = layer.qgs_layer.addFeature(new_feature)
            self.assertTrue(is_added)
            qgs_layer.commitChanges(stopEditing=False)

            feature_id = next(iter(changes_logger.added_fids))

            is_removed = qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

            qgs_layer.commitChanges(stopEditing=False)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))

    @mock_container(TestData.Points)
    def test_delete_existing_feature_after_updates_resets_update_logs(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            feature_id = qgs_layer.allFeatureIds()[0]

            # Update fields
            is_changed = qgs_layer.changeAttributeValue(
                feature_id, attribute_index, "b"
            )
            self.assertTrue(is_changed)
            qgs_layer.commitChanges(stopEditing=False)

            # Change geometry
            is_changed = qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)
            qgs_layer.commitChanges(stopEditing=False)

            is_removed = qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({feature_id}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))

    # todo: add and remove without sync, remove and add with same name, virtual field

    @mock_container(TestData.Points)
    @patch(
        "qgis.PyQt.QtWidgets.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    def test_add_attribute_on_non_versioned_layer_warns_and_emits_structure_changed(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
        message_box_mock: MagicMock,
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            field = QgsField("NEW_FIELD", FieldType.QString)
            field.setAlias("NEW FIELD")
            self.assertTrue(layer.qgs_layer.addAttribute(field))

        self.assertEqual(len(message_box_mock.mock_calls), 1)
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.structure_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

    @mock_container(TestData.Points)
    @patch(
        "qgis.PyQt.QtWidgets.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    def test_remove_attribute_on_non_versioned_layer_warns_and_emits_structure_changed(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
        message_box_mock: MagicMock,
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            self.assertTrue(layer.qgs_layer.deleteAttribute(attribute_index))

        self.assertEqual(len(message_box_mock.mock_calls), 1)
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.structure_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    @patch(
        "qgis.PyQt.QtWidgets.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    def test_add_attribute_on_versioned_layer_warns_and_emits_structure_changed(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
        message_box_mock: MagicMock,
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            field = QgsField("NEW_FIELD", FieldType.QString)
            field.setAlias("NEW FIELD")
            self.assertTrue(layer.qgs_layer.addAttribute(field))

        self.assertEqual(len(message_box_mock.mock_calls), 1)
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.structure_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    @patch(
        "qgis.PyQt.QtWidgets.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    def test_remove_attribute_on_versioned_layer_warns_and_emits_structure_changed(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
        message_box_mock: MagicMock,
    ) -> None:
        attribute_index = qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            self.assertTrue(layer.qgs_layer.deleteAttribute(attribute_index))

        self.assertEqual(len(message_box_mock.mock_calls), 1)
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.structure_changed.emit(),
                call.editing_finished.emit(),
            ],
        )


class TestDetachedLayerDescriptions(NgConnectTestCase):
    FEATURE_1 = 1
    FEATURE_2 = 2

    TEST_DESCRIPTION_TEXT_0 = "<TEST_0>"
    TEST_DESCRIPTION_TEXT_1 = "<TEST_1>"
    TEST_DESCRIPTION_TEXT_2 = "<TEST_2>"
    TEST_DESCRIPTION_TEXT_3 = "<TEST_3>"

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_read_feature_description_and_missing_returns_none(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)
        with self.subTest("Set description"):
            self.assertEqual(
                layer.feature_description(self.FEATURE_1),
                self.TEST_DESCRIPTION_TEXT_0,
            )
        with self.subTest("No description"):
            self.assertEqual(layer.feature_description(2), None)

    @mock_container(TestData.Points)
    def test_set_description_in_read_mode_raises_error(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with self.assertRaises(DetachedEditingError):
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
            )

    @mock_container(TestData.Points)
    def test_access_description_of_nonexistent_feature_raises_error(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with self.subTest("Get description"):
            with self.assertRaises(DetachedEditingError):
                self.assertEqual(layer.feature_description(999), None)

        with self.subTest("Set description"):
            with self.assertRaises(DetachedEditingError):
                layer.set_feature_description(
                    999, self.TEST_DESCRIPTION_TEXT_1
                )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_update_description_on_existing_feature_emits_and_stores_backup(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
            )
            self.assertTrue(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(
                layer.feature_description(self.FEATURE_1),
                self.TEST_DESCRIPTION_TEXT_1,
            )
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                ),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_1,
        )
        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            descriptions = list(
                cursor.execute(
                    "SELECT fid, description FROM ngw_features_descriptions"
                )
            )

        self.assertEqual(
            descriptions, [(self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1)]
        )

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid, backup FROM ngw_updated_descriptions"
                )
            )
        self.assertEqual(
            updated_descriptions,
            [
                (
                    self.FEATURE_1,
                    serialize_value(
                        {
                            "value": self.TEST_DESCRIPTION_TEXT_0,
                            "version": 12345,
                        }
                    ),
                )
            ],
        )

        # Update again should not duplicate backup entries
        with edit(layer.qgs_layer):
            layer.set_feature_description(1, self.TEST_DESCRIPTION_TEXT_2)

        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_2,
        )

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid, backup FROM ngw_updated_descriptions"
                )
            )
        self.assertEqual(
            updated_descriptions,
            [
                (
                    self.FEATURE_1,
                    serialize_value(
                        {
                            "value": self.TEST_DESCRIPTION_TEXT_0,
                            "version": 12345,
                        }
                    ),
                )
            ],
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_save_description_in_edit_mode(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
            )
            self.assertTrue(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(
                layer.feature_description(self.FEATURE_1),
                self.TEST_DESCRIPTION_TEXT_1,
            )
            layer.qgs_layer.commitChanges(stopEditing=False)
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
            )

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                ),
                call.layer_changed.emit(),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_update_description_on_newly_added_features(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            new_feature = QgsFeature(layer.qgs_layer.fields())
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))

            added_fids = list(
                layer.qgs_layer.editBuffer().addedFeatures().keys()
            )
            added_fids.sort(reverse=True)
            feature_1_id = added_fids[0]
            feature_2_id = added_fids[1]

            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                feature_1_id, self.TEST_DESCRIPTION_TEXT_1
            )
            layer.set_feature_description(
                feature_2_id, self.TEST_DESCRIPTION_TEXT_2
            )
            self.assertTrue(layer.edit_buffer.has_updated_descriptions)

            self.assertEqual(
                layer.feature_description(feature_1_id),
                self.TEST_DESCRIPTION_TEXT_1,
            )
            self.assertEqual(
                layer.feature_description(feature_2_id),
                self.TEST_DESCRIPTION_TEXT_2,
            )

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    feature_1_id, self.TEST_DESCRIPTION_TEXT_1
                ),
                call.description_updated(
                    feature_2_id, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )
        feature_1_id, feature_2_id = list(
            sorted(layer.qgs_layer.allFeatureIds())
        )[-2:]
        self.assertEqual(
            layer.feature_description(feature_1_id),
            self.TEST_DESCRIPTION_TEXT_1,
        )
        self.assertEqual(
            layer.feature_description(feature_2_id),
            self.TEST_DESCRIPTION_TEXT_2,
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_update_description_undo_restores_original_and_clears_flags(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
            )
            self.assertTrue(layer.edit_buffer.has_updated_descriptions)
            layer.qgs_layer.undoStack().undo()
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(
                layer.feature_description(self.FEATURE_1),
                self.TEST_DESCRIPTION_TEXT_0,
            )

        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_0,
        )
        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                ),
                call.editing_finished.emit(),
            ],
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_update_description_redo_reapplies_change_and_emits_signals(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            layer.set_feature_description(
                self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
            )
            layer.qgs_layer.undoStack().undo()
            layer.qgs_layer.undoStack().redo()

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                ),
                call.description_updated(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )
        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_2,
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_merge_update_description_commands_in_undo_stack(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with self.subTest("Simple merge"):
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                )
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                )
                self.assertEqual(layer.qgs_layer.undoStack().count(), 1)
                self.assertEqual(
                    len(layer.edit_buffer.updated_descriptions), 1
                )

        with self.subTest("No merge between different features"):
            # Restore state
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                )

            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                )
                layer.set_feature_description(
                    self.FEATURE_2, self.TEST_DESCRIPTION_TEXT_2
                )
                self.assertEqual(layer.qgs_layer.undoStack().count(), 2)
                self.assertEqual(
                    len(layer.edit_buffer.updated_descriptions), 2
                )

        with self.subTest("Merge with return to original"):
            # Restore state
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                )

            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                )
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                )
                self.assertFalse(layer.edit_buffer.has_updated_descriptions)
                self.assertEqual(layer.qgs_layer.undoStack().count(), 0)

        with self.subTest("Merge with return to previous"):
            # Restore state
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_0
                )

            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                )

                # For splitting undo commands
                layer.set_feature_description(
                    self.FEATURE_2, self.TEST_DESCRIPTION_TEXT_0
                )

                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                )
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
                )

                self.assertEqual(layer.qgs_layer.undoStack().count(), 2)
                self.assertEqual(
                    len(layer.edit_buffer.updated_descriptions), 2
                )
                self.assertEqual(
                    layer.feature_description(self.FEATURE_1),
                    self.TEST_DESCRIPTION_TEXT_1,
                )
                self.assertEqual(
                    layer.feature_description(self.FEATURE_2),
                    self.TEST_DESCRIPTION_TEXT_0,
                )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_delete_new_feature_with_description_clears_update_buffer(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        signals_mock = mock_layer_signals(layer)
        with edit(layer.qgs_layer):
            new_feature = QgsFeature(layer.qgs_layer.fields())
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))

            added_fids = list(
                layer.qgs_layer.editBuffer().addedFeatures().keys()
            )
            added_fids.sort(reverse=True)
            feature_1_id = added_fids[0]
            feature_2_id = added_fids[1]

            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            layer.set_feature_description(
                feature_1_id, self.TEST_DESCRIPTION_TEXT_1
            )
            layer.qgs_layer.deleteFeature(feature_1_id)
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(len(layer.edit_buffer.updated_descriptions), 0)

            layer.set_feature_description(
                feature_2_id, self.TEST_DESCRIPTION_TEXT_2
            )
            self.assertTrue(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(len(layer.edit_buffer.updated_descriptions), 1)

            self.assertEqual(
                layer.feature_description(feature_2_id),
                self.TEST_DESCRIPTION_TEXT_2,
            )

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.description_updated(
                    feature_1_id, self.TEST_DESCRIPTION_TEXT_1
                ),
                call.description_updated(
                    feature_2_id, self.TEST_DESCRIPTION_TEXT_2
                ),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )
        feature_2_id = list(sorted(layer.qgs_layer.allFeatureIds()))[-1]
        self.assertEqual(
            layer.feature_description(feature_2_id),
            self.TEST_DESCRIPTION_TEXT_2,
        )

    @mock_container(TestData.Points)
    def test_delete_persisted_new_feature_with_description_removes_storage_entry(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with edit(layer.qgs_layer):
            new_feature = QgsFeature(layer.qgs_layer.fields())
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))

            added_fids = list(
                layer.qgs_layer.editBuffer().addedFeatures().keys()
            )
            added_fids.sort(reverse=True)
            feature_id = added_fids[0]
            layer.set_feature_description(
                feature_id, self.TEST_DESCRIPTION_TEXT_1
            )

        feature_id = list(sorted(layer.qgs_layer.allFeatureIds()))[-1]
        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid, backup FROM ngw_updated_descriptions"
                )
            )
        self.assertEqual(updated_descriptions, [(feature_id, None)])

        with edit(layer.qgs_layer):
            self.assertTrue(layer.qgs_layer.deleteFeature(feature_id))

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid, backup FROM ngw_updated_descriptions"
                )
            )
        self.assertEqual(updated_descriptions, [])

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM ngw_features_descriptions",
            )
            self.assertEqual(0, cursor.fetchone()[0])

    @mock_container(TestData.Points)
    def test_delete_feature_with_updated_description_removes_updates(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with self.subTest("Read from buffer"):
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_2
                )
                self.assertTrue(layer.edit_buffer.has_updated_descriptions)
                layer.qgs_layer.deleteFeature(self.FEATURE_1)
                self.assertFalse(layer.edit_buffer.has_updated_descriptions)
                self.assertFalse(
                    self.FEATURE_1 in layer.edit_buffer.updated_descriptions
                )

        with self.subTest("Read from storage"):
            with edit(layer.qgs_layer):
                layer.set_feature_description(
                    self.FEATURE_2, self.TEST_DESCRIPTION_TEXT_2
                )

            with edit(layer.qgs_layer):
                layer.qgs_layer.deleteFeature(self.FEATURE_2)

            with self.assertRaises(DetachedEditingError):
                layer.feature_description(self.FEATURE_2)

            with closing(
                make_connection(container_mock.path)
            ) as connection, closing(connection.cursor()) as cursor:
                updated_descriptions = list(
                    cursor.execute(
                        "SELECT fid, backup FROM ngw_updated_descriptions"
                    )
                )
            self.assertEqual(updated_descriptions, [])

    @mock_container(TestData.Points)
    def test_undo_delete_restores_description_update_for_feature(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with edit(layer.qgs_layer):
            new_feature = QgsFeature(layer.qgs_layer.fields())
            self.assertTrue(layer.qgs_layer.addFeature(new_feature))
            feature_1_fid = list(
                sorted(layer.qgs_layer.editBuffer().addedFeatures().keys())
            )[-1]
            layer.set_feature_description(
                feature_1_fid, self.TEST_DESCRIPTION_TEXT_1
            )
            self.assertTrue(layer.qgs_layer.deleteFeature(feature_1_fid))
            self.assertFalse(layer.edit_buffer.has_updated_descriptions)

            self.assertTrue(layer.qgs_layer.addFeature(new_feature))
            feature_2_fid = list(
                sorted(layer.qgs_layer.editBuffer().addedFeatures().keys())
            )[-1]
            self.assertEqual(layer.feature_description(feature_2_fid), None)

            layer.qgs_layer.undoStack().undo()  # Undo add
            layer.qgs_layer.undoStack().undo()  # Undo delete

            self.assertTrue(layer.edit_buffer.has_updated_descriptions)
            self.assertEqual(
                layer.feature_description(feature_1_fid),
                self.TEST_DESCRIPTION_TEXT_1,
            )


if __name__ == "__main__":
    unittest.main()
