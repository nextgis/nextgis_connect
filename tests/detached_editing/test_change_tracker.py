# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

from types import SimpleNamespace
from unittest.mock import MagicMock

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject

from nextgis_connect.legacy.detached_editing.change_tracker import (
    DetachedChangeTracker,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    deserialize_geometry,
    deserialize_value,
)


def test_retry_preserves_first_backups_and_only_confirmed_changes(qgis_app):
    layer = QgsVectorLayer(
        "Point?field=tracked:string&field=local:string", "test", "memory"
    )
    feature = QgsFeature(layer.fields())
    feature.setAttributes(["original", "local"])
    feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))
    success, features = layer.dataProvider().addFeatures([feature])
    assert success
    fid = features[0].id()
    tracker = DetachedChangeTracker(
        MagicMock(
            fields=[SimpleNamespace(attribute=0)], is_versioning_enabled=False
        )
    )
    assert layer.startEditing()
    assert layer.changeAttributeValue(fid, 0, "first")
    assert layer.changeAttributeValue(fid, 1, "local change")
    assert layer.changeGeometry(fid, QgsGeometry.fromWkt("POINT (1 1)"))
    tracker.capture_attributes(layer)
    tracker.capture_geometries(layer)
    assert not tracker.has_changes
    assert layer.commitChanges(False)
    tracker.changed_attributes(
        layer.id(), {fid: {0: "first", 1: "local change"}}
    )
    tracker.changed_geometries(
        layer.id(), {fid: QgsGeometry.fromWkt("POINT (1 1)")}
    )

    assert layer.changeAttributeValue(fid, 0, "second")
    assert layer.changeGeometry(fid, QgsGeometry.fromWkt("POINT (2 2)"))
    tracker.capture_attributes(layer)
    tracker.capture_geometries(layer)
    assert tracker.attributes == {fid: {0}}
    assert set(tracker.attribute_backups) == {(fid, 0)}
    assert deserialize_value(tracker.attribute_backups[(fid, 0)]) == "original"
    assert (
        deserialize_geometry(tracker.geometry_backups[fid], False).asWkt()
        == "Point (0 0)"
    )
    assert layer.rollBack()
    tracker.clear()
    assert not tracker.has_changes
    assert not tracker.attribute_backups
    assert not tracker.geometry_backups


def test_owner_deletion_disconnects_provider_signals(qgis_app):
    layer = QgsVectorLayer("Point", "test", "memory")
    owner = QObject()
    tracker = DetachedChangeTracker(MagicMock(), owner)
    connections = (
        (layer.committedFeaturesAdded, tracker.added_features),
        (layer.committedFeaturesRemoved, tracker.removed_features),
        (layer.committedAttributeValuesChanges, tracker.changed_attributes),
        (layer.committedGeometriesChanges, tracker.changed_geometries),
    )
    for signal, slot in connections:
        signal.connect(slot)
        assert layer.receivers(signal) == 1
    sip.delete(owner)
    assert sip.isdeleted(tracker)
    for signal, _ in connections:
        assert layer.receivers(signal) == 0
