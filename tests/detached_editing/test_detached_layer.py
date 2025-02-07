import json
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Set, Tuple
from unittest.mock import MagicMock, call, patch, sentinel

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, edit
from qgis.PyQt.QtCore import QObject, pyqtSlot

from nextgis_connect.compat import (
    QgsChangedAttributesMap,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)
from nextgis_connect.detached_editing.detached_layer import DetachedLayer
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.serialization import (
    deserialize_geometry,
    deserialize_value,
    simplify_value,
)
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
    make_connection,
)
from nextgis_connect.ngw_api.core import NGWVectorLayer
from tests.magic_qobject_mock import MagicQObjectMock
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestData,
)


def mock_layer_signals(layer: DetachedLayer) -> MagicMock:
    signals_mock = MagicMock()
    layer.editing_started = signals_mock.editing_started
    layer.editing_finished = signals_mock.editing_finished
    layer.layer_changed = signals_mock.layer_changed
    layer.settings_changed = signals_mock.settings_changed
    layer.error_occured = signals_mock.error_occured
    return signals_mock


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

    def assert_changes_equal(self, logger: LayerChangesLogger) -> None:
        assert self.added_is_equal(logger.added_fids)
        assert self.removed_is_equal(logger.removed_fids)
        assert self.updated_attributes_is_equal(logger.updated_attribute_fids)
        assert self.updated_geometries_is_equal(logger.updated_geometry_fids)


class TestDetachedLayer(NgConnectTestCase):
    def setUp(self):
        super().setUp()

        ngw_layer = self.resource(TestData.Points)
        assert isinstance(ngw_layer, NGWVectorLayer)
        qgs_layer = self.layer(TestData.Points)
        assert isinstance(qgs_layer, QgsVectorLayer)

        self.container_path = self.create_temp_file(".gpkg")

        factory = DetachedLayerFactory()
        factory.create_initial_container(ngw_layer, self.container_path)
        factory.fill_container(
            ngw_layer,
            source_path=self.data_path(TestData.Points),
            container_path=self.container_path,
        )

        self.container_metadata = container_metadata(self.container_path)

        self.container_mock = MagicQObjectMock()
        self.container_mock.metadata = self.container_metadata

        self.qgs_layer = QgsVectorLayer(
            detached_layer_uri(self.container_path, self.container_metadata),
            self.container_metadata.layer_name,
            "ogr",
        )

    def tearDown(self) -> None:
        self.container_mock.deleteLater()
        super().tearDown()

    def test_start_stop_signals(self) -> None:
        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        self.assertTrue(self.qgs_layer.startEditing())
        self.assertTrue(layer.is_edit_mode_enabled)
        self.assertTrue(self.qgs_layer.rollBack())

        self.assertTrue(self.qgs_layer.startEditing())
        self.assertTrue(layer.is_edit_mode_enabled)
        self.assertTrue(self.qgs_layer.commitChanges())

        self.assertEqual(
            signals_mock.mock_calls,
            2 * [call.editing_started.emit(), call.editing_finished.emit()],
        )

    def test_start_stop_signals_with_started_editing(self) -> None:
        signals_mock = MagicMock()

        self.qgs_layer.startEditing()

        module = "nextgis_connect.detached_editing.detached_layer"
        with patch(
            f"{module}.DetachedLayer.editing_started"
        ) as editing_started_mock, patch(
            f"{module}.DetachedLayer.editing_finished"
        ) as editing_finished_mock:
            signals_mock.attach_mock(editing_started_mock, "editing_started")
            signals_mock.attach_mock(editing_finished_mock, "editing_finished")

            layer = DetachedLayer(self.container_mock, self.qgs_layer)
            self.assertTrue(layer.is_edit_mode_enabled)

            self.qgs_layer.commitChanges()

        self.assertEqual(
            signals_mock.mock_calls,
            [call.editing_started.emit(), call.editing_finished.emit()],
        )

    def test_ngw_properties(self) -> None:
        self.qgs_layer.setCustomProperty("not_ngw_property_is_same", True)

        def check_properties():
            self.assertTrue(
                self.qgs_layer.customProperty("not_ngw_property_is_same")
            )
            self.assertTrue(
                self.qgs_layer.customProperty("ngw_is_detached_layer")
            )
            self.assertEqual(
                self.qgs_layer.customProperty("ngw_connection_id"),
                self.container_mock.metadata.connection_id,
            )
            self.assertEqual(
                self.qgs_layer.customProperty("ngw_resource_id"),
                self.container_mock.metadata.resource_id,
            )

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        check_properties()

        self.container_mock.metadata = replace(
            self.container_mock.metadata,
            connection_id=sentinel.NGW_CONNECTION_ID,
        )

        layer.update()
        check_properties()

    def test_settings_changed_signal(self) -> None:
        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        # Check not emmitted when not ngw properties set
        self.qgs_layer.setCustomProperty("not_ngw_property", True)
        signals_mock.assert_not_called()

        # Check not emmitted when ngw properties set
        self.container_mock.metadata = replace(
            self.container_mock.metadata,
            connection_id=sentinel.NGW_CONNECTION_ID,
        )
        layer.update()

        signals_mock.assert_not_called()

        self.qgs_layer.setCustomProperty(
            DetachedLayer.UPDATE_STATE_PROPERTY, True
        )
        signals_mock.settings_changed.emit.assert_called_once()

    def test_adding_features(self) -> None:
        changes_logger = LayerChangesLogger(self.qgs_layer)

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
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
        changes_checker = ChangesChecker(self.container_path)
        changes_checker.assert_changes_equal(changes_logger)

    def test_deleting_features(self) -> None:
        STRING_FIELD = self.qgs_layer.fields().indexOf("STRING")
        INITIAL_STRING_VALUE = "TEST"
        INITIAL_GEOMETRY = QgsGeometry.fromWkt("POINT (0 0)")
        self.assertFalse(INITIAL_GEOMETRY.isNull())

        feature_id = next(iter(sorted(self.qgs_layer.allFeatureIds())))
        self.assertTrue(
            self.qgs_layer.dataProvider().changeGeometryValues(
                {feature_id: INITIAL_GEOMETRY}
            )
        )
        self.assertTrue(
            self.qgs_layer.dataProvider().changeAttributeValues(
                {feature_id: {STRING_FIELD: INITIAL_STRING_VALUE}}
            )
        )

        feature = self.qgs_layer.getFeature(feature_id)

        changes_logger = LayerChangesLogger(self.qgs_layer)

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        NEW_STRING_VALUE = INITIAL_STRING_VALUE + "_1"
        NEW_GEOMETRY = QgsGeometry.fromWkt("POINT (1 1)")
        with edit(self.qgs_layer):
            self.assertTrue(
                self.qgs_layer.changeAttributeValue(
                    feature_id, STRING_FIELD, NEW_STRING_VALUE
                )
            )
            self.assertTrue(
                self.qgs_layer.changeGeometry(feature_id, NEW_GEOMETRY)
            )

        edited_feature = self.qgs_layer.getFeature(feature_id)

        with edit(self.qgs_layer):
            is_removed = self.qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        self.assertTrue(len(changes_logger.removed_fids) == 1)
        changes_checker = ChangesChecker(self.container_path)
        self.assertTrue(
            changes_checker.added_is_equal(changes_logger.added_fids)
        )
        self.assertTrue(
            changes_checker.removed_is_equal(changes_logger.removed_fids)
        )
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))

        with closing(
            make_connection(self.container_path)
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
        for field in self.container_metadata.fields:
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
                self.container_metadata.is_versioning_enabled,
            ).asWkt(),
        )
        self.assertEqual(
            NEW_GEOMETRY.asWkt(),
            deserialize_geometry(
                backup["before_deletion"]["geom"],
                self.container_metadata.is_versioning_enabled,
            ).asWkt(),
        )

    def test_updating_fields(self) -> None:
        INTEGER_FIELD = self.qgs_layer.fields().indexOf("INTEGER")
        INITIAL_INTEGER_VALUE = 123
        STRING_FIELD = self.qgs_layer.fields().indexOf("STRING")
        INITIAL_STRING_VALUE = "TEST"

        feature_id = list(sorted(self.qgs_layer.allFeatureIds()))[1]
        self.assertTrue(
            self.qgs_layer.dataProvider().changeAttributeValues(
                {
                    feature_id: {
                        STRING_FIELD: INITIAL_STRING_VALUE,
                        INTEGER_FIELD: INITIAL_INTEGER_VALUE,
                    },
                }
            )
        )

        changes_logger = LayerChangesLogger(self.qgs_layer)

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        NEW_INTEGER_VALUE = INITIAL_INTEGER_VALUE + 1
        NEW_STRING_VALUE = INITIAL_STRING_VALUE + "_1"
        with edit(self.qgs_layer):
            self.assertTrue(
                self.qgs_layer.changeAttributeValue(
                    feature_id, INTEGER_FIELD, NEW_INTEGER_VALUE
                )
            )
            self.assertTrue(
                self.qgs_layer.changeAttributeValue(
                    feature_id, STRING_FIELD, NEW_STRING_VALUE
                )
            )

        VERY_NEW_INTEGER_VALUE = NEW_INTEGER_VALUE + 1
        with edit(self.qgs_layer):
            # Check PK constraints
            self.assertTrue(
                self.qgs_layer.changeAttributeValue(
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
        changes_checker = ChangesChecker(self.container_path)
        changes_checker.assert_changes_equal(changes_logger)

        with closing(
            make_connection(self.container_path)
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

    def test_updating_geometry(self) -> None:
        INITIAL_GEOMETRY = QgsGeometry.fromWkt("POINT (0 0)")
        self.assertFalse(INITIAL_GEOMETRY.isNull())

        feature_id = next(iter(sorted(self.qgs_layer.allFeatureIds())))
        self.qgs_layer.dataProvider().changeGeometryValues(
            {feature_id: INITIAL_GEOMETRY}
        )

        changes_logger = LayerChangesLogger(self.qgs_layer)

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(self.qgs_layer):
            is_changed = self.qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)

        with edit(self.qgs_layer):
            # Check PK constraints
            is_changed = self.qgs_layer.changeGeometry(
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
        changes_checker = ChangesChecker(self.container_path)
        changes_checker.assert_changes_equal(changes_logger)

        with closing(
            make_connection(self.container_path)
        ) as connection, closing(connection.cursor()) as cursor:
            backup = {
                row[0]: deserialize_geometry(
                    row[1], self.container_mock.metadata.is_versioning_enabled
                )
                for row in cursor.execute(
                    f"""
                    SELECT fid, backup FROM ngw_updated_geometries
                    WHERE fid = {feature_id};
                    """
                )
            }

        self.assertEqual(backup[feature_id].asWkt(), INITIAL_GEOMETRY.asWkt())

    def test_updating_new_feature(self) -> None:
        attribute_index = self.qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        changes_logger = LayerChangesLogger(self.qgs_layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        with edit(layer.qgs_layer):
            # Add feature
            is_added = layer.qgs_layer.addFeature(new_feature)
            self.assertTrue(is_added)
            self.qgs_layer.commitChanges(stopEditing=False)

            feature_id = next(iter(changes_logger.added_fids))

            # Update fields
            is_changed = self.qgs_layer.changeAttributeValue(
                feature_id, attribute_index, "b"
            )
            self.assertTrue(is_changed)
            self.qgs_layer.commitChanges(stopEditing=False)

            # Change geometry
            is_changed = self.qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)
            self.qgs_layer.commitChanges(stopEditing=False)

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

        changes_checker = ChangesChecker(self.container_path)
        self.assertTrue(changes_checker.added_is_equal({feature_id}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))

    def test_rollback(self) -> None:
        attribute_index = self.qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        try:
            with edit(layer.qgs_layer):
                # Add feature
                is_added = layer.qgs_layer.addFeature(new_feature)
                self.assertTrue(is_added)

                feature_id = self.qgs_layer.allFeatureIds()[0]

                # Update fields
                is_changed = self.qgs_layer.changeAttributeValue(
                    feature_id, attribute_index, "b"
                )
                self.assertTrue(is_changed)

                # Change geometry
                is_changed = self.qgs_layer.changeGeometry(
                    feature_id, QgsGeometry.fromWkt("POINT (1 1)")
                )
                self.assertTrue(is_changed)

                feature_id = self.qgs_layer.allFeatureIds()[1]

                # Remove feature
                is_removed = self.qgs_layer.deleteFeature(feature_id)
                self.assertTrue(is_removed)

                raise RuntimeError

        except Exception:
            pass

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(self.container_path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))

    def test_deleting_new_feature(self) -> None:
        attribute_index = self.qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        changes_logger = LayerChangesLogger(self.qgs_layer)

        new_feature = QgsFeature(layer.qgs_layer.fields())
        new_feature.setAttribute(attribute_index, "a")
        new_feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))

        with edit(layer.qgs_layer):
            # Add feature
            is_added = layer.qgs_layer.addFeature(new_feature)
            self.assertTrue(is_added)
            self.qgs_layer.commitChanges(stopEditing=False)

            feature_id = next(iter(changes_logger.added_fids))

            is_removed = self.qgs_layer.deleteFeature(feature_id)
            self.assertTrue(is_removed)

            self.qgs_layer.commitChanges(stopEditing=False)

        self.assertEqual(
            signals_mock.mock_calls,
            [
                call.editing_started.emit(),
                call.layer_changed.emit(),
                call.layer_changed.emit(),
                call.editing_finished.emit(),
            ],
        )

        changes_checker = ChangesChecker(self.container_path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))

    def test_deleting_updated_feature(self) -> None:
        attribute_index = self.qgs_layer.fields().indexOf("STRING")

        layer = DetachedLayer(self.container_mock, self.qgs_layer)
        signals_mock = mock_layer_signals(layer)

        with edit(layer.qgs_layer):
            feature_id = self.qgs_layer.allFeatureIds()[0]

            # Update fields
            is_changed = self.qgs_layer.changeAttributeValue(
                feature_id, attribute_index, "b"
            )
            self.assertTrue(is_changed)
            self.qgs_layer.commitChanges(stopEditing=False)

            # Change geometry
            is_changed = self.qgs_layer.changeGeometry(
                feature_id, QgsGeometry.fromWkt("POINT (1 1)")
            )
            self.assertTrue(is_changed)
            self.qgs_layer.commitChanges(stopEditing=False)

            is_removed = self.qgs_layer.deleteFeature(feature_id)
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

        changes_checker = ChangesChecker(self.container_path)
        self.assertTrue(changes_checker.added_is_equal({}))
        self.assertTrue(changes_checker.removed_is_equal({feature_id}))
        self.assertTrue(changes_checker.updated_attributes_is_equal({}))
        self.assertTrue(changes_checker.updated_geometries_is_equal({}))


if __name__ == "__main__":
    unittest.main()
