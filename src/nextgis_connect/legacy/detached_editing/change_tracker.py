# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Set, Tuple, cast

from qgis.core import QgsFeature, QgsFeatureRequest, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, pyqtSlot

from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    serialize_geometry,
    serialize_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerMetaData,
)
from nextgis_connect.platform.qgis.compat import (
    QgsChangedAttributesMap,
    QgsFeatureIds,
    QgsFeatureList,
    QgsGeometryMap,
)


@dataclass
class ExtensionChanges:
    """Carry an edit-buffer snapshot to the journal without GUI dependencies."""

    descriptions: Dict[int, Optional[str]] = field(default_factory=dict)
    added_attachments: Dict[int, Dict[int, AttachmentMetadata]] = field(
        default_factory=dict
    )
    updated_attachments: Dict[int, Dict[int, AttachmentMetadata]] = field(
        default_factory=dict
    )
    removed_attachments: Dict[int, Set[int]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.descriptions
            or any(self.added_attachments.values())
            or any(self.updated_attachments.values())
            or any(self.removed_attachments.values())
        )


class DetachedChangeTracker(QObject):
    """Accumulate provider-confirmed changes across unsuccessful save attempts."""

    def __init__(
        self,
        metadata: DetachedContainerMetaData,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.metadata = metadata
        self.added: Set[int] = set()
        self.removed: Set[int] = set()
        self.attributes: Dict[int, Set[int]] = {}
        self.geometries: Set[int] = set()
        self.attribute_backups: Dict[Tuple[int, int], Any] = {}
        self.geometry_backups: Dict[int, Optional[str]] = {}
        self.deleted_features: Dict[int, QgsFeature] = {}

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added or self.removed or self.attributes or self.geometries
        )

    def clear(self) -> None:
        """Discard the completed batch and its pre-save snapshots."""
        self.added.clear()
        self.removed.clear()
        self.attributes.clear()
        self.geometries.clear()
        self.attribute_backups.clear()
        self.geometry_backups.clear()
        self.deleted_features.clear()

    @pyqtSlot(str, "QgsFeatureList")
    def added_features(self, _: str, features: QgsFeatureList) -> None:
        """Collect permanent IDs confirmed by the provider."""
        self.added.update(feature.id() for feature in features)

    @pyqtSlot(str, "QgsFeatureIds")
    def removed_features(self, _: str, feature_ids: QgsFeatureIds) -> None:
        """Collect deletions confirmed by the provider."""
        self.removed.update(feature_ids)

    @pyqtSlot(str, "QgsChangedAttributesMap")
    def changed_attributes(
        self, _: str, changes: QgsChangedAttributesMap
    ) -> None:
        """Collect confirmed changes to synchronized fields."""
        tracked = {field.attribute for field in self.metadata.fields}
        for fid, attributes in changes.items():
            attributes = tracked.intersection(attributes)
            if attributes:
                self.attributes.setdefault(fid, set()).update(attributes)

    @pyqtSlot(str, "QgsGeometryMap")
    def changed_geometries(self, _: str, changes: QgsGeometryMap) -> None:
        """Collect geometry changes confirmed by the provider."""
        self.geometries.update(changes)

    def capture_attributes(self, layer: QgsVectorLayer) -> None:
        """Keep the first field values across provider save retries."""
        changes = layer.editBuffer().changedAttributeValues()
        if not changes:
            return
        tracked = {field.attribute for field in self.metadata.fields}
        for feature in cast(
            Iterable[QgsFeature],
            layer.dataProvider().getFeatures(QgsFeatureRequest(list(changes))),
        ):
            for attribute in tracked.intersection(changes[feature.id()]):
                self.attribute_backups.setdefault(
                    (feature.id(), attribute),
                    serialize_value(feature.attribute(attribute)),
                )

    def capture_geometries(self, layer: QgsVectorLayer) -> None:
        """Keep the first geometries across provider save retries."""
        changes = layer.editBuffer().changedGeometries()
        if not changes:
            return
        for feature in cast(
            Iterable[QgsFeature],
            layer.dataProvider().getFeatures(QgsFeatureRequest(list(changes))),
        ):
            self.geometry_backups.setdefault(
                feature.id(),
                serialize_geometry(
                    feature.geometry(), self.metadata.is_versioning_enabled
                ),
            )

    def capture_deletions(self, layer: QgsVectorLayer) -> None:
        """Capture persisted feature values immediately before deletion."""
        deleted = layer.editBuffer().deletedFeatureIds()
        if not deleted:
            return
        # Keep snapshots for deletions confirmed in earlier, partial commits.
        for feature in cast(
            Iterable[QgsFeature],
            layer.dataProvider().getFeatures(QgsFeatureRequest(deleted)),
        ):
            self.deleted_features[feature.id()] = QgsFeature(feature)
