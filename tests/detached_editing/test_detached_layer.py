# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import json
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Set, Tuple
from unittest.mock import MagicMock, call, patch, sentinel

from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsVectorLayer, edit
from qgis.PyQt.QtCore import QCoreApplication, QObject, pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.legacy.detached_editing.change_journal import (
    DetachedChangeJournal,
)
from nextgis_connect.legacy.detached_editing.change_tracker import (
    DetachedChangeTracker,
)
from nextgis_connect.legacy.detached_editing.detached_layer import (
    DetachedLayer,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    deserialize_geometry,
    deserialize_value,
    serialize_value,
    simplify_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    make_connection,
)
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.qgis.compat import (
    FieldType,
    QgsChangedAttributesMap,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    DetachedEditingError,
)
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

        module = "nextgis_connect.legacy.detached_editing.detached_layer"
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
                qgs_layer.customProperty("ngw_instance_id"),
                container_mock.metadata.instance_id,
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

    @mock_container(TestData.Points, descriptions={1: "<TEST_DESCRIPTION>"})
    def test_deletes_feature_and_stores_existing_description_backup(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        feature_id = 1

        _layer = DetachedLayer(container_mock, qgs_layer)

        with edit(qgs_layer):
            is_removed = qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            deleted_features = list(
                cursor.execute(
                    "SELECT fid, backup FROM ngw_removed_features WHERE fid = ?",
                    (feature_id,),
                )
            )

        self.assertEqual(len(deleted_features), 1)

        backup = json.loads(deleted_features[0][1])

        after_desc = backup["after_sync"]["description"]
        before_desc = backup["before_deletion"]["description"]

        self.assertEqual(
            after_desc,
            {"value": "<TEST_DESCRIPTION>", "version": 12345},
        )
        self.assertEqual(
            before_desc,
            {"value": "<TEST_DESCRIPTION>", "version": 12345},
        )

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
    @patch(
        "qgis.PyQt.QtWidgets.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    def test_ignores_local_attribute_and_tracks_ngw_attribute_and_geometry(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
        _message_box_mock: MagicMock,
    ) -> None:
        ngw_attribute = qgs_layer.fields().indexOf("STRING")
        feature_id = next(iter(sorted(qgs_layer.allFeatureIds())))

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.addAttribute(
                    QgsField("LOCAL_FIELD", FieldType.QString)
                )
            )
            local_attribute = qgs_layer.fields().indexOf("LOCAL_FIELD")
            self.assertGreaterEqual(local_attribute, 0)
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, ngw_attribute, "ngw value"
                )
            )
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id, local_attribute, "local value"
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
            )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(
            changes_checker.updated_attributes_is_equal(
                {(feature_id, ngw_attribute)}
            )
        )
        self.assertTrue(
            changes_checker.updated_geometries_is_equal({feature_id})
        )
        signals_mock.error_occurred.emit.assert_not_called()

    @mock_container(TestData.Points)
    def test_missing_feature_metadata_is_reported_without_partial_markers(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        feature_id = next(iter(sorted(qgs_layer.allFeatureIds())))
        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                "DELETE FROM ngw_features_metadata WHERE fid = ?",
                (feature_id,),
            )
            connection.commit()

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(feature_id, attribute, "value")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
            )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))

        signals_mock.layer_changed.emit.assert_not_called()
        signals_mock.error_occurred.emit.assert_called_once()
        error = signals_mock.error_occurred.emit.call_args[0][0]
        self.assertEqual(
            error.log_message,
            "Can't create feature changes records because required container "
            "metadata is missing.",
        )
        self.assertIn(
            f"feature IDs {feature_id} are missing in ngw_features_metadata",
            error.user_message,
        )
        self.assertIn("may not be synchronized", error.user_message)

    @mock_container(TestData.Points)
    def test_feature_update_markers_are_atomic(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        feature_id = next(iter(sorted(qgs_layer.allFeatureIds())))
        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                """
                CREATE TRIGGER fail_geometry_marker
                BEFORE INSERT ON ngw_updated_geometries
                BEGIN
                    SELECT RAISE(ABORT, 'Injected geometry marker failure');
                END;
                """
            )
            connection.commit()

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(feature_id, attribute, "value")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
            )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        signals_mock.layer_changed.emit.assert_not_called()
        signals_mock.error_occurred.emit.assert_called_once()
        error = signals_mock.error_occurred.emit.call_args[0][0]
        self.assertEqual(
            error.log_message, "Can't create feature changes records"
        )
        self.assertIn("may not be synchronized", error.user_message)

    @mock_container(TestData.Points, descriptions={1: "before"})
    def test_feature_update_failure_rolls_back_description_change(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        feature_id = 1
        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                """
                CREATE TRIGGER fail_geometry_marker
                BEFORE INSERT ON ngw_updated_geometries
                BEGIN
                    SELECT RAISE(ABORT, 'Injected geometry marker failure');
                END;
                """
            )
            connection.commit()

        layer = DetachedLayer(container_mock, qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(qgs_layer):
            layer.set_feature_description(feature_id, "after")
            self.assertTrue(
                qgs_layer.changeAttributeValue(feature_id, attribute, "value")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
            )

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))
        self.assertEqual(layer.feature_description(feature_id), "before")
        signals_mock.error_occurred.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_commit_failure_rolls_back_both_update_marker_types(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                "CREATE TABLE journal_commit_guard ("
                "fid INTEGER REFERENCES ngw_features_metadata(fid) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
            connection.execute(
                "CREATE TRIGGER fail_journal_commit AFTER INSERT ON ngw_updated_geometries "
                "BEGIN INSERT INTO journal_commit_guard VALUES (-999); END"
            )
            connection.commit()

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(1, attribute, "saved")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(1, QgsGeometry.fromWkt("POINT (1 1)"))
            )

        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.updated_attributes_is_equal({}))
        self.assertTrue(checker.updated_geometries_is_equal({}))
        with closing(make_connection(container_mock.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT * FROM journal_commit_guard"
                ).fetchall(),
                [],
            )
            connection.execute("DROP TRIGGER fail_journal_commit")
            connection.commit()
        signals.error_occurred.emit.assert_called_once()
        self.assertIn(
            "FOREIGN KEY constraint failed",
            str(signals.error_occurred.emit.call_args[0][0].__cause__),
        )
        signals.layer_changed.emit.assert_not_called()

        # The failed batch must not leak into a later, unrelated commit.
        signals.reset_mock()
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(2, attribute, "next")
            )
        self.assertTrue(checker.updated_attributes_is_equal({(2, attribute)}))
        self.assertTrue(checker.updated_geometries_is_equal({}))
        signals.error_occurred.emit.assert_not_called()
        signals.layer_changed.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_missing_backups_reject_entire_update_batch(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        for kind, message in (
            ("attributes", "attribute"),
            ("geometries", "geometry"),
        ):
            with self.subTest(kind=kind):
                signals.reset_mock()
                with patch.object(
                    DetachedChangeTracker, f"capture_{kind}"
                ), edit(qgs_layer):
                    self.assertTrue(
                        qgs_layer.changeAttributeValue(1, attribute, kind)
                    )
                    self.assertTrue(
                        qgs_layer.changeGeometry(
                            1, QgsGeometry.fromWkt("POINT (1 1)")
                        )
                    )
                checker = ChangesChecker(container_mock.path)
                self.assertTrue(checker.updated_attributes_is_equal({}))
                self.assertTrue(checker.updated_geometries_is_equal({}))
                signals.layer_changed.emit.assert_not_called()
                signals.error_occurred.emit.assert_called_once()
                error = signals.error_occurred.emit.call_args[0][0]
                self.assertEqual(
                    error.log_message,
                    f"Can't create feature changes records because {message} backups are missing.",
                )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_null_backups_are_valid_for_versioned_updates(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        self.assertTrue(
            qgs_layer.dataProvider().changeAttributeValues(
                {1: {attribute: None}}
            )
        )
        self.assertTrue(
            qgs_layer.dataProvider().changeGeometryValues({1: QgsGeometry()})
        )
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(1, attribute, "saved")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(1, QgsGeometry.fromWkt("POINT (1 1)"))
            )
        with closing(make_connection(container_mock.path)) as connection:
            attribute_backup = connection.execute(
                "SELECT backup FROM ngw_updated_attributes WHERE fid = 1 AND attribute = ?",
                (attribute,),
            ).fetchone()
            geometry_backup = connection.execute(
                "SELECT backup FROM ngw_updated_geometries WHERE fid = 1"
            ).fetchone()
        self.assertIsNotNone(attribute_backup)
        self.assertIsNone(deserialize_value(attribute_backup[0]))
        self.assertEqual(geometry_backup, (None,))
        signals.error_occurred.emit.assert_not_called()

    @mock_container(TestData.Points)
    def test_failed_update_batch_preserves_preexisting_journal_records(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(1, attribute, "first")
            )
        with closing(make_connection(container_mock.path)) as connection:
            original_records = connection.execute(
                "SELECT fid, attribute, backup FROM ngw_updated_attributes"
            ).fetchall()
            connection.execute(
                "CREATE TRIGGER fail_geometry_marker BEFORE INSERT ON ngw_updated_geometries "
                "BEGIN SELECT RAISE(ABORT, 'Injected geometry marker failure'); END"
            )
            connection.commit()
        signals.reset_mock()
        with edit(qgs_layer):
            for fid in (1, 2):
                self.assertTrue(
                    qgs_layer.changeAttributeValue(fid, attribute, "second")
                )
                self.assertTrue(
                    qgs_layer.changeGeometry(
                        fid, QgsGeometry.fromWkt("POINT (1 1)")
                    )
                )
        with closing(make_connection(container_mock.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT fid, attribute, backup FROM ngw_updated_attributes"
                ).fetchall(),
                original_records,
            )
        self.assertTrue(
            ChangesChecker(container_mock.path).updated_geometries_is_equal({})
        )
        # Journal atomicity does not roll back data already saved by QGIS.
        self.assertEqual(
            qgs_layer.getFeature(2).attribute(attribute), "second"
        )
        self.assertEqual(
            qgs_layer.getFeature(2).geometry().asWkt(), "Point (1 1)"
        )
        signals.error_occurred.emit.assert_called_once()
        signals.layer_changed.emit.assert_not_called()

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
    def test_add_marker_failure_rolls_back_existing_feature_updates(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                "CREATE TRIGGER fail_added_marker BEFORE INSERT ON ngw_added_features "
                "BEGIN SELECT RAISE(ABORT, 'Injected addition marker failure'); END"
            )
            connection.commit()
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(1, attribute, "updated")
            )
            self.assertTrue(
                qgs_layer.addFeature(QgsFeature(qgs_layer.fields()))
            )
        self.assertTrue(
            ChangesChecker(container_mock.path).updated_attributes_is_equal({})
        )
        signals.error_occurred.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_partial_commit_then_delete_preserves_original_backup(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        original = simplify_value(qgs_layer.getFeature(1).attribute(attribute))
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                f'CREATE TRIGGER fail_feature_insert BEFORE INSERT ON "{container_mock.metadata.table_name}" '
                "BEGIN SELECT RAISE(ABORT, 'Injected feature insertion failure'); END"
            )
            connection.commit()
        self.assertTrue(qgs_layer.startEditing())
        self.assertTrue(
            qgs_layer.changeAttributeValue(1, attribute, "updated")
        )
        feature = QgsFeature(qgs_layer.fields())
        self.assertTrue(qgs_layer.addFeature(feature))
        self.assertFalse(qgs_layer.commitChanges(False))
        self.assertEqual(
            next(
                feature
                for feature in qgs_layer.dataProvider().getFeatures()
                if feature.id() == 1
            ).attribute(attribute),
            "updated",
        )
        self.assertTrue(qgs_layer.deleteFeature(feature.id()))
        self.assertTrue(qgs_layer.deleteFeature(1))
        self.assertTrue(qgs_layer.commitChanges())
        with closing(make_connection(container_mock.path)) as connection:
            backup = json.loads(
                connection.execute(
                    "SELECT backup FROM ngw_removed_features WHERE fid = 1"
                ).fetchone()[0]
            )
        ngw_id = next(
            field.ngw_id
            for field in container_mock.metadata.fields
            if field.attribute == attribute
        )
        self.assertEqual(
            dict(backup["after_sync"]["fields"])[ngw_id], original
        )
        signals.error_occurred.emit.assert_not_called()

    @mock_container(TestData.Points, descriptions={1: "before"})
    def test_partial_commit_keeps_updates_in_memory_until_rollback(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        original = simplify_value(qgs_layer.getFeature(1).attribute(attribute))
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                f'CREATE TRIGGER fail_feature_insert BEFORE INSERT ON "{container_mock.metadata.table_name}" '
                "BEGIN SELECT RAISE(ABORT, 'Injected feature insertion failure'); END"
            )
            connection.commit()
        self.assertTrue(qgs_layer.startEditing())
        layer.set_feature_description(1, "unsaved")
        self.assertTrue(qgs_layer.changeAttributeValue(1, attribute, "saved"))
        self.assertTrue(
            qgs_layer.changeGeometry(1, QgsGeometry.fromWkt("POINT (1 1)"))
        )
        self.assertTrue(qgs_layer.addFeature(QgsFeature(qgs_layer.fields())))
        self.assertFalse(qgs_layer.commitChanges(False))

        # Returning to the event loop must not write a partial journal batch.
        QCoreApplication.processEvents()
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.updated_attributes_is_equal({}))
        self.assertTrue(checker.updated_geometries_is_equal({}))
        signals.layer_changed.emit.assert_not_called()
        self.assertTrue(qgs_layer.rollBack())
        self.assertTrue(checker.updated_attributes_is_equal({(1, attribute)}))
        self.assertTrue(checker.updated_geometries_is_equal({1}))
        self.assertTrue(checker.updated_descriptions_is_equal({}))
        with closing(make_connection(container_mock.path)) as connection:
            backup = connection.execute(
                "SELECT backup FROM ngw_updated_attributes WHERE fid = 1 AND attribute = ?",
                (attribute,),
            ).fetchone()
        self.assertEqual(deserialize_value(backup[0]), original)
        signals.layer_changed.emit.assert_called_once()
        signals.error_occurred.emit.assert_not_called()
        QCoreApplication.processEvents()
        signals.layer_changed.emit.assert_called_once()
        self.assertEqual(layer.feature_description(1), "before")

    @mock_container(TestData.Points, descriptions={1: "before"})
    def test_partial_commit_rollback_without_stopping_journals_only_saved_data(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                f'CREATE TRIGGER fail_feature_insert BEFORE INSERT ON "{container_mock.metadata.table_name}" '
                "BEGIN SELECT RAISE(ABORT, 'Injected feature insertion failure'); END"
            )
            connection.commit()
        self.assertTrue(qgs_layer.startEditing())
        layer.set_feature_description(1, "discarded")
        self.assertTrue(
            qgs_layer.changeAttributeValue(1, attribute, "updated")
        )
        self.assertTrue(
            qgs_layer.changeGeometry(1, QgsGeometry.fromWkt("POINT (1 1)"))
        )
        self.assertTrue(qgs_layer.addFeature(QgsFeature(qgs_layer.fields())))
        self.assertFalse(qgs_layer.commitChanges(False))
        self.assertTrue(qgs_layer.rollBack(False))
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.updated_attributes_is_equal({(1, attribute)}))
        self.assertTrue(checker.updated_geometries_is_equal({1}))
        self.assertTrue(checker.updated_descriptions_is_equal({}))
        self.assertEqual(layer.feature_description(1), "before")
        signals.error_occurred.emit.assert_not_called()
        signals.layer_changed.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_partial_commit_keeps_deletions_until_successful_retry(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                f'CREATE TRIGGER fail_feature_insert BEFORE INSERT ON "{container_mock.metadata.table_name}" '
                "BEGIN SELECT RAISE(ABORT, 'Injected feature insertion failure'); END"
            )
            connection.commit()
        self.assertTrue(qgs_layer.startEditing())
        self.assertTrue(qgs_layer.deleteFeature(1))
        added = QgsFeature(qgs_layer.fields())
        self.assertTrue(qgs_layer.addFeature(added))
        self.assertFalse(qgs_layer.commitChanges(False))
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.removed_is_equal({}))
        self.assertNotIn(
            1,
            {
                feature.id()
                for feature in qgs_layer.dataProvider().getFeatures()
            },
        )
        self.assertTrue(qgs_layer.deleteFeature(added.id()))
        self.assertTrue(qgs_layer.deleteFeature(2))
        self.assertTrue(qgs_layer.commitChanges())
        self.assertTrue(checker.removed_is_equal({1, 2}))
        signals.error_occurred.emit.assert_not_called()
        signals.layer_changed.emit.assert_called_once()

    @mock_container(TestData.Points)
    def test_failed_attachment_journal_retains_staged_original(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        source = self.create_temp_file(".txt")
        source.write_text("content")
        self.assertTrue(qgs_layer.startEditing())
        attachment = layer.add_attachment(1, source)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                "CREATE TRIGGER fail_attachment BEFORE INSERT ON ngw_added_attachments "
                "BEGIN SELECT RAISE(ABORT, 'Injected attachment failure'); END"
            )
            connection.commit()
        self.assertTrue(qgs_layer.commitChanges())
        self.assertEqual(attachment.file_path.read_text(), "content")
        with closing(make_connection(container_mock.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT * FROM ngw_features_attachments"
                ).fetchall(),
                [],
            )
        signals.error_occurred.emit.assert_called_once()
        signals.layer_changed.emit.assert_not_called()

    @mock_container(TestData.Points)
    def test_successful_commit_emits_one_journal_notification(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        self.assertTrue(qgs_layer.startEditing())
        for stop_editing in (False, True):
            with self.subTest(stop_editing=stop_editing):
                signals.reset_mock()
                self.assertTrue(
                    qgs_layer.changeAttributeValue(
                        1, attribute, str(stop_editing)
                    )
                )
                self.assertTrue(qgs_layer.commitChanges(stop_editing))
                QCoreApplication.processEvents()
                signals.layer_changed.emit.assert_called_once()
                signals.error_occurred.emit.assert_not_called()

    @mock_container(
        TestData.Points, extra_features_count=1000, empty_features=True
    )
    def test_missing_metadata_in_last_batch_rejects_all_updates(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        feature_ids = sorted(qgs_layer.allFeatureIds())
        self.assertGreater(
            len(feature_ids), DetachedChangeJournal.QUERY_BATCH_SIZE
        )
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                "DELETE FROM ngw_features_metadata WHERE fid = ?",
                (feature_ids[-1],),
            )
            connection.commit()
        with edit(qgs_layer):
            for fid in feature_ids:
                self.assertTrue(
                    qgs_layer.changeAttributeValue(fid, attribute, "saved")
                )
                self.assertTrue(
                    qgs_layer.changeGeometry(
                        fid, QgsGeometry.fromWkt("POINT (1 1)")
                    )
                )
        QCoreApplication.processEvents()
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.updated_attributes_is_equal({}))
        self.assertTrue(checker.updated_geometries_is_equal({}))
        signals.layer_changed.emit.assert_not_called()
        signals.error_occurred.emit.assert_called_once()
        self.assertIn(
            f"feature IDs {feature_ids[-1]} are missing",
            signals.error_occurred.emit.call_args[0][0].user_message,
        )

    @mock_container(TestData.Points)
    def test_missing_field_metadata_rejects_both_update_marker_types(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with closing(make_connection(container_mock.path)) as connection:
            connection.execute(
                "DELETE FROM ngw_fields_metadata WHERE attribute = ?",
                (attribute,),
            )
            connection.commit()
        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(1, attribute, "updated")
            )
            self.assertTrue(
                qgs_layer.changeGeometry(1, QgsGeometry.fromWkt("POINT (1 1)"))
            )
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(checker.updated_attributes_is_equal({}))
        self.assertTrue(checker.updated_geometries_is_equal({}))
        signals.error_occurred.emit.assert_called_once()
        self.assertIn(
            "ngw_fields_metadata",
            signals.error_occurred.emit.call_args[0][0].user_message,
        )

    @mock_container(TestData.Points, descriptions={1: "before"})
    def test_continue_editing_after_rollback_without_stopping(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        original = simplify_value(qgs_layer.getFeature(1).attribute(attribute))
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        self.assertTrue(qgs_layer.startEditing())
        layer.set_feature_description(1, "discarded")
        self.assertTrue(
            qgs_layer.changeAttributeValue(1, attribute, "discarded")
        )
        self.assertTrue(qgs_layer.rollBack(False))

        self.assertTrue(qgs_layer.isEditable())
        self.assertIsNotNone(layer.edit_buffer)
        signals.editing_finished.emit.assert_not_called()
        layer.set_feature_description(1, "saved")
        self.assertTrue(qgs_layer.changeAttributeValue(1, attribute, "saved"))
        self.assertTrue(qgs_layer.commitChanges())

        self.assertEqual(layer.feature_description(1), "saved")
        with closing(make_connection(container_mock.path)) as connection:
            backup = connection.execute(
                "SELECT backup FROM ngw_updated_attributes WHERE fid = 1 AND attribute = ?",
                (attribute,),
            ).fetchone()
        self.assertIsNotNone(backup)
        self.assertEqual(deserialize_value(backup[0]), original)
        signals.error_occurred.emit.assert_not_called()
        signals.layer_changed.emit.assert_called_once()
        signals.editing_finished.emit.assert_called_once()

    @mock_container(
        TestData.Points, extra_features_count=1000, empty_features=True
    )
    def test_update_validation_spans_multiple_query_batches(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        attribute = qgs_layer.fields().indexOf("STRING")
        feature_ids = set(qgs_layer.allFeatureIds())
        self.assertGreater(
            len(feature_ids), DetachedChangeJournal.QUERY_BATCH_SIZE
        )
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        with edit(qgs_layer):
            for fid in feature_ids:
                self.assertTrue(
                    qgs_layer.changeAttributeValue(fid, attribute, "updated")
                )
                self.assertTrue(
                    qgs_layer.changeGeometry(
                        fid, QgsGeometry.fromWkt("POINT (1 1)")
                    )
                )
        checker = ChangesChecker(container_mock.path)
        self.assertTrue(
            checker.updated_attributes_is_equal(
                {(fid, attribute) for fid in feature_ids}
            )
        )
        self.assertTrue(checker.updated_geometries_is_equal(feature_ids))
        signals.error_occurred.emit.assert_not_called()

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

        with self.subTest("Get description"):
            with self.assertRaises(DetachedEditingError):
                layer.feature_description(999)

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
    def test_rolls_back_description_without_creating_change_marker(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        self.assertTrue(qgs_layer.startEditing())
        layer.set_feature_description(
            self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
        )
        self.assertTrue(qgs_layer.rollBack())

        changes_checker = ChangesChecker(container_mock.path)
        self.assertTrue(changes_checker.updated_descriptions_is_equal({}))
        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_0,
        )

    @mock_container(
        TestData.Points,
        descriptions={1: TEST_DESCRIPTION_TEXT_0},
    )
    def test_redo_description_after_rollback_without_stopping(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        signals = mock_layer_signals(layer)
        self.assertTrue(qgs_layer.startEditing())
        layer.set_feature_description(
            self.FEATURE_1, self.TEST_DESCRIPTION_TEXT_1
        )
        self.assertTrue(qgs_layer.rollBack(False))
        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_0,
        )
        self.assertTrue(qgs_layer.undoStack().canRedo())
        qgs_layer.undoStack().redo()
        self.assertTrue(qgs_layer.commitChanges())
        self.assertEqual(
            layer.feature_description(self.FEATURE_1),
            self.TEST_DESCRIPTION_TEXT_1,
        )
        self.assertTrue(
            ChangesChecker(container_mock.path).updated_descriptions_is_equal(
                {self.FEATURE_1}
            )
        )
        signals.error_occurred.emit.assert_not_called()

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


class TestDetachedLayerAttachments(NgConnectTestCase):
    FEATURE_1 = 1
    FEATURE_2 = 2

    ATTACHMENT_1 = 1
    ATTACHMENT_2 = 2
    ATTACHMENT_3 = 3
    ATTACHMENT_4 = 4

    TEST_ATTACHMENT_1_CONTENT = "<TEST_1>"
    TEST_ATTACHMENT_2_CONTENT = "<TEST_2>"
    TEST_ATTACHMENT_3_CONTENT = "<TEST_3>"
    TEST_ATTACHMENT_4_CONTENT = "<TEST_4>"

    @mock_container(TestData.Points)
    def test_attachments_change_in_readmode_raises_error(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        with self.assertRaises(DetachedEditingError):
            layer.add_attachment(self.FEATURE_1, Path("attachment.txt"))

        with self.assertRaises(DetachedEditingError):
            layer.update_attachment(
                AttachmentMetadata(self.FEATURE_1, self.ATTACHMENT_1)
            )

        with self.assertRaises(DetachedEditingError):
            layer.remove_attachment(self.FEATURE_1, self.ATTACHMENT_1)

    @mock_container(TestData.Points)
    def test_access_attachments_of_nonexistent_feature(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        with self.subTest("Get attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.feature_attachment(999, self.ATTACHMENT_1)

        with self.subTest("Get attachments"):
            self.assertEqual(len(layer.feature_attachments(999)), 0)

        with self.subTest("Get attachments count"):
            self.assertEqual(layer.feature_attachments_count(999), 0)

        with self.subTest("Add attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.add_attachment(999, Path("attachment.txt"))

        with self.subTest("Update attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.update_attachment(
                    AttachmentMetadata(999, self.ATTACHMENT_1)
                )

        with self.subTest("Remove attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.remove_attachment(999, self.ATTACHMENT_1)

    @mock_container(TestData.Points)
    def test_access_nonexistent_feature_attachments(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        with self.subTest("Get nonexistent attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.feature_attachment(self.FEATURE_1, self.ATTACHMENT_1)

        with self.subTest(
            "Get attachments list for feature without attachments"
        ):
            attachments = layer.feature_attachments(self.FEATURE_1)
            self.assertEqual(attachments, [])

        with self.subTest(
            "Get attachments count for feature without attachments"
        ):
            count = layer.feature_attachments_count(self.FEATURE_1)
            self.assertEqual(count, 0)

        with self.subTest("Update nonexistent attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.update_attachment(
                    AttachmentMetadata(self.FEATURE_1, self.ATTACHMENT_1)
                )

        with self.subTest("Remove attachment"):
            with self.assertRaises(DetachedEditingError):
                layer.remove_attachment(self.FEATURE_1, self.ATTACHMENT_1)

    @mock_container(
        TestData.Points,
        attachments=[AttachmentMetadata(fid=FEATURE_1, aid=ATTACHMENT_1)],
    )
    def test_read_attachments(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        attachments = layer.feature_attachments(self.FEATURE_1)
        attachment = layer.feature_attachment(
            self.FEATURE_1, self.ATTACHMENT_1
        )
        self.assertTrue(
            len(attachments)
            == layer.feature_attachments_count(self.FEATURE_1)
            == 1
        )
        self.assertIsInstance(attachment, AttachmentMetadata)
        self.assertEqual(attachments[0], attachment)

    @mock_container(TestData.Points)
    def test_identification_refreshes_non_versioned_attachments(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)

        module = "nextgis_connect.legacy.detached_editing.detached_layer"
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            ngw_connection = connection_mock.return_value
            ngw_connection.get.side_effect = [
                [
                    {
                        "id": 101,
                        "name": "server-101",
                        "description": "description-101",
                        "mime_type": "image/png",
                        "size": 1001,
                        "fileobj": 501,
                        "file_meta": {
                            "panorama": {"ProjectionType": "equirectangular"}
                        },
                    },
                    {
                        "id": 102,
                        "name": "server-102",
                        "description": "description-102",
                        "mime_type": "text/plain",
                        "size": 1002,
                        "fileobj": 502,
                    },
                ],
                [
                    {
                        "id": 102,
                        "name": "server-102-updated",
                        "description": "description-102-updated",
                        "mime_type": "text/plain",
                        "size": 2002,
                        "fileobj": 602,
                    },
                    {
                        "id": 103,
                        "name": "server-103",
                        "description": "description-103",
                        "mime_type": "image/jpeg",
                        "size": 1003,
                        "fileobj": 503,
                    },
                ],
            ]

            first_attachments = layer.feature_attachments_for_identification(
                self.FEATURE_1
            )
            second_attachments = layer.feature_attachments_for_identification(
                self.FEATURE_1
            )

        self.assertEqual(
            [attachment.ngw_aid for attachment in first_attachments],
            [101, 102],
        )
        self.assertEqual(
            [attachment.ngw_aid for attachment in second_attachments],
            [102, 103],
        )
        self.assertEqual(
            first_attachments[0].file_meta,
            {"panorama": {"ProjectionType": "equirectangular"}},
        )

        second_by_ngw_aid = {
            attachment.ngw_aid: attachment for attachment in second_attachments
        }
        self.assertEqual(second_by_ngw_aid[102].name, "server-102-updated")
        self.assertEqual(
            second_by_ngw_aid[102].description, "description-102-updated"
        )
        self.assertEqual(second_by_ngw_aid[102].size, 2002)
        self.assertEqual(second_by_ngw_aid[102].fileobj, 602)

    @mock_container(TestData.Points)
    def test_identification_overlays_local_attachment_changes(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        local_file_path = self.create_temp_file(".txt")
        local_file_path.write_text("local attachment")

        module = "nextgis_connect.legacy.detached_editing.detached_layer"
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            ngw_connection = connection_mock.return_value
            ngw_connection.get.side_effect = [
                [
                    {
                        "id": 201,
                        "name": "server-201",
                        "description": "description-201",
                        "mime_type": "text/plain",
                        "size": 201,
                        "fileobj": 701,
                    },
                    {
                        "id": 202,
                        "name": "server-202",
                        "description": "description-202",
                        "mime_type": "text/plain",
                        "size": 202,
                        "fileobj": 702,
                    },
                ],
                [
                    {
                        "id": 201,
                        "name": "server-201-new",
                        "description": "description-201-new",
                        "mime_type": "text/plain",
                        "size": 1201,
                        "fileobj": 801,
                    },
                    {
                        "id": 202,
                        "name": "server-202-new",
                        "description": "description-202-new",
                        "mime_type": "text/plain",
                        "size": 1202,
                        "fileobj": 802,
                    },
                    {
                        "id": 203,
                        "name": "server-203",
                        "description": "description-203",
                        "mime_type": "image/jpeg",
                        "size": 203,
                        "fileobj": 703,
                    },
                ],
            ]

            server_attachments = layer.feature_attachments_for_identification(
                self.FEATURE_1
            )

            by_ngw_aid = {
                attachment.ngw_aid: attachment
                for attachment in server_attachments
            }

            self.assertTrue(qgs_layer.startEditing())
            try:
                layer.update_attachment(
                    replace(by_ngw_aid[201], name="local-201")
                )
                layer.remove_attachment(self.FEATURE_1, by_ngw_aid[202].aid)
                layer.add_attachment(self.FEATURE_1, local_file_path)

                attachments = layer.feature_attachments_for_identification(
                    self.FEATURE_1
                )
            finally:
                qgs_layer.rollBack()

        names_by_ngw_aid = {
            attachment.ngw_aid: attachment.name for attachment in attachments
        }

        self.assertEqual(names_by_ngw_aid[201], "local-201")
        self.assertNotIn(202, names_by_ngw_aid)
        self.assertEqual(names_by_ngw_aid[203], "server-203")
        self.assertIn(
            local_file_path.name,
            {attachment.name for attachment in attachments},
        )

    @mock_container(TestData.Points)
    def test_new_attachment_is_staged_in_storage_cache(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        local_file_path = self.create_temp_file(".txt")
        local_file_path.write_text("local attachment")

        self.assertTrue(qgs_layer.startEditing())
        storage_service = DetachedStorageServiceFactory.create()
        try:
            attachment = layer.add_attachment(self.FEATURE_1, local_file_path)

            assert attachment.file_path is not None
            assert attachment.file_path.exists()
            attachment.file_path.resolve().relative_to(
                storage_service.cache_root.resolve()
            )
        finally:
            qgs_layer.rollBack()

    @mock_container(TestData.Points)
    def test_new_attachment_uses_filename_mime_fallback(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        local_file_path = self.create_temp_file(".jpg")
        local_file_path.write_bytes(b"jpeg")

        content_mime_type = MagicMock()
        content_mime_type.isValid.return_value = False
        fallback_mime_type = MagicMock()
        fallback_mime_type.isValid.return_value = True
        fallback_mime_type.name.return_value = "image/jpeg"
        module = "nextgis_connect.legacy.detached_editing.detached_layer_edit_buffer"

        with patch(f"{module}.QMimeDatabase") as mime_database_class:
            mime_database = mime_database_class.return_value
            mime_database.mimeTypeForFileNameAndData.return_value = (
                content_mime_type
            )
            mime_database.mimeTypesForFileName.return_value = [
                fallback_mime_type
            ]

            self.assertTrue(qgs_layer.startEditing())
            try:
                attachment = layer.add_attachment(
                    self.FEATURE_1, local_file_path
                )
            finally:
                qgs_layer.rollBack()

        self.assertEqual(attachment.mime_type, "image/jpeg")

    @mock_container(TestData.Points)
    def test_rollback_removes_new_attachment_from_storage_cache(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        local_file_path = self.create_temp_file(".txt")
        local_file_path.write_text("local attachment")

        self.assertTrue(qgs_layer.startEditing())
        attachment = layer.add_attachment(self.FEATURE_1, local_file_path)

        assert attachment.file_path is not None
        assert attachment.file_path.exists()

        self.assertTrue(qgs_layer.rollBack())

        assert not attachment.file_path.exists()

    @mock_container(TestData.Points)
    def test_rollback_removes_undone_new_attachment_from_storage_cache(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        local_file_path = self.create_temp_file(".txt")
        local_file_path.write_text("local attachment")

        self.assertTrue(qgs_layer.startEditing())
        attachment = layer.add_attachment(self.FEATURE_1, local_file_path)

        assert attachment.file_path is not None
        assert attachment.file_path.exists()

        qgs_layer.undoStack().undo()

        assert attachment.file_path.exists()
        self.assertTrue(qgs_layer.rollBack())

        assert not attachment.file_path.exists()

    @mock_container(
        TestData.Points,
        descriptions={1: "initial-description"},
        attachments=[
            AttachmentMetadata(
                fid=FEATURE_1,
                aid=ATTACHMENT_1,
                ngw_aid=ATTACHMENT_1,
                version=11,
                name="initial-name-1",
                description="initial-description-1",
                mime_type="text/plain",
            ),
            AttachmentMetadata(
                fid=FEATURE_1,
                aid=ATTACHMENT_2,
                ngw_aid=ATTACHMENT_2,
                version=12,
                name="initial-name-2",
                description="initial-description-2",
                mime_type="text/plain",
            ),
        ],
    )
    def test_delete_feature_removes_attachment_and_description_storage(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        layer = DetachedLayer(container_mock, qgs_layer)
        set_layer_error_assert(layer)

        with edit(layer.qgs_layer):
            layer.set_feature_description(
                self.FEATURE_1,
                "updated-description",
            )
            attachment = layer.feature_attachment(
                self.FEATURE_1,
                self.ATTACHMENT_1,
            )
            assert attachment is not None
            layer.update_attachment(replace(attachment, name="updated-name-1"))
            layer.remove_attachment(self.FEATURE_1, self.ATTACHMENT_2)

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            feature_attachments = list(
                cursor.execute(
                    "SELECT aid FROM ngw_features_attachments WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )
            updated_attachments = list(
                cursor.execute("SELECT aid FROM ngw_updated_attachments")
            )
            removed_attachments = list(
                cursor.execute("SELECT aid FROM ngw_removed_attachments")
            )
            descriptions = list(
                cursor.execute(
                    "SELECT fid FROM ngw_features_descriptions WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid FROM ngw_updated_descriptions WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )

        self.assertEqual(
            feature_attachments,
            [(self.ATTACHMENT_1,), (self.ATTACHMENT_2,)],
        )
        self.assertEqual(updated_attachments, [(self.ATTACHMENT_1,)])
        self.assertEqual(removed_attachments, [(self.ATTACHMENT_2,)])
        self.assertEqual(descriptions, [(self.FEATURE_1,)])
        self.assertEqual(updated_descriptions, [(self.FEATURE_1,)])

        settings = NgConnectSettings()
        should_notify = settings.notify_when_deleting_features_with_attachments
        settings.notify_when_deleting_features_with_attachments = False
        try:
            with edit(layer.qgs_layer):
                self.assertTrue(layer.qgs_layer.deleteFeature(self.FEATURE_1))
        finally:
            settings.notify_when_deleting_features_with_attachments = (
                should_notify
            )

        with closing(
            make_connection(container_mock.path)
        ) as connection, closing(connection.cursor()) as cursor:
            feature_attachments = list(
                cursor.execute(
                    "SELECT aid FROM ngw_features_attachments WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )
            updated_attachments = list(
                cursor.execute("SELECT aid FROM ngw_updated_attachments")
            )
            removed_attachments = list(
                cursor.execute("SELECT aid FROM ngw_removed_attachments")
            )
            descriptions = list(
                cursor.execute(
                    "SELECT fid FROM ngw_features_descriptions WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )
            updated_descriptions = list(
                cursor.execute(
                    "SELECT fid FROM ngw_updated_descriptions WHERE fid = ?",
                    (self.FEATURE_1,),
                )
            )

        self.assertEqual(feature_attachments, [])
        self.assertEqual(updated_attachments, [])
        self.assertEqual(removed_attachments, [])
        self.assertEqual(descriptions, [])
        self.assertEqual(updated_descriptions, [])


if __name__ == "__main__":
    unittest.main()
