import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum, auto
from functools import singledispatch
from pathlib import Path
from typing import List, Optional

from qgis.core import QgsMapLayer, QgsVectorLayer

from nextgis_connect.logging import logger
from nextgis_connect.resources.ngw_field import NgwField


class DetachedLayerState(str, Enum):
    NotInitialized = "NotInitialized"
    Error = "Error"
    NotSynchronized = "NotSynchronized"
    Synchronization = "Synchronization"
    Synchronized = "Synchronized"

    def __str__(self):
        return str(self.value)


class VersioningSynchronizationState(str, Enum):
    NotVersionedLayer = "NotVersionedLayer"
    NotInitialized = "NotInitialized"
    FetchingChanges = "FetchingChanges"
    ConflictSolving = "ConflictSolving"
    UploadingChanges = "UploadingChanges"
    FetchingUploaded = "FetchingUploaded"
    Synchronized = "Synchronized"

    def __str__(self):
        return str(self.value)


class DetachedLayerErrorType(IntEnum):
    NoError = auto()

    SynchronizationError = auto()
    NotEnoughRights = auto()

    ContainerError = auto()
    CreationError = auto()
    DeletedContainer = auto()

    @property
    def is_sync_error(self) -> bool:
        return self.SynchronizationError <= self < self.ContainerError

    @property
    def is_container_error(self) -> bool:
        return self >= self.ContainerError


@dataclass
class DetachedContainerMetaData:
    container_version: str
    connection_id: str
    instance_id: Optional[str]
    resource_id: int
    table_name: str
    layer_name: str
    description: Optional[str]
    geometry_name: Optional[str]
    transaction_id: Optional[str]
    epoch: Optional[int]
    version: Optional[int]
    sync_date: Optional[datetime]
    is_broken: bool
    is_auto_sync_enabled: bool
    fields: List[NgwField]
    has_changes: bool
    srs_id: int = 3857

    @property
    def is_stub(self) -> bool:
        return self.sync_date is None

    @property
    def is_versioning_enabled(self) -> bool:
        return self.epoch is not None and self.version is not None

    def __str__(self) -> str:
        return f'"{self.layer_name}" (id={self.resource_id})'


@dataclass
class DetachedContainerChanges:
    added_features: int = 0
    removed_features: int = 0
    updated_attributes: int = 0
    updated_geometries: int = 0

    @property
    def updated_features(self) -> int:
        return self.updated_attributes + self.updated_geometries


@dataclass
class FeatureMetaData:
    fid: int
    ngw_fid: Optional[int] = None
    version: Optional[int] = None
    description: Optional[str] = None


def container_path(layer: QgsMapLayer) -> Path:
    return Path(layer.source().split("|")[0])


def is_ngw_container(layer: QgsMapLayer) -> bool:
    def has_properties(layer: QgsMapLayer) -> bool:
        return "ngw_connection_id" in layer.customPropertyKeys()

    def has_metadata(layer: QgsMapLayer) -> bool:
        try:
            with (
                closing(sqlite3.connect(container_path(layer))) as connection,
                closing(connection.cursor()) as cursor,
            ):
                cursor.execute(
                    """
                    SELECT count(name)
                    FROM sqlite_master
                    WHERE type='table' AND name='ngw_metadata';
                    """
                )
                return cursor.fetchone()[0] == 1
        except Exception:
            logger.exception("Could not get the layer metadata")

        return False

    return (
        isinstance(layer, QgsVectorLayer)
        and layer.storageType() == "GPKG"
        and (has_properties(layer) or has_metadata(layer))
    )


@singledispatch
def container_metadata(path_or_cursor) -> DetachedContainerMetaData:
    message = f"Unsupported type: {type(path_or_cursor)}"
    raise TypeError(message)


@container_metadata.register
def _(path: Path) -> DetachedContainerMetaData:
    with (
        closing(sqlite3.connect(str(path))) as connection,
        closing(connection.cursor()) as cursor,
    ):
        return container_metadata(cursor)


@container_metadata.register
def _(cursor: sqlite3.Cursor) -> DetachedContainerMetaData:
    cursor.execute("SELECT * FROM ngw_metadata")
    (
        container_version,
        connection_id,
        instance_id,
        resource_id,
        layer_name,
        description,
        geometry_name,
        transaction_id,
        epoch,
        version,
        sync_date,
        is_broken,
        is_auto_sync_enabled,
    ) = cursor.fetchone()

    if sync_date is not None:
        sync_date = datetime.fromisoformat(sync_date)

    cursor.execute(
        """
        SELECT table_name FROM gpkg_contents
        WHERE data_type='features'
        """
    )
    table_name = cursor.fetchone()[0]

    fields = [
        NgwField(*row)
        for row in cursor.execute("SELECT * FROM ngw_fields_metadata")
    ]

    cursor.execute(
        """
        SELECT
            EXISTS(SELECT 1 FROM ngw_added_features)
            OR EXISTS(SELECT 1 FROM ngw_removed_features)
            OR EXISTS(SELECT 1 FROM ngw_updated_attributes)
            OR EXISTS(SELECT 1 FROM ngw_updated_geometries)
    """
    )
    has_changes = bool(cursor.fetchone()[0])

    return DetachedContainerMetaData(
        container_version,
        connection_id,
        instance_id,
        resource_id,
        table_name,
        layer_name,
        description,
        geometry_name,
        transaction_id,
        epoch,
        version,
        sync_date,
        is_broken,
        is_auto_sync_enabled,
        fields,
        has_changes,
    )


def container_changes(path: Path) -> DetachedContainerChanges:
    with (
        closing(sqlite3.connect(str(path))) as connection,
        closing(connection.cursor()) as cursor,
    ):
        cursor.execute(
            """
                SELECT
                  (SELECT COUNT(*) from ngw_added_features) added,
                  (SELECT COUNT(*) from ngw_removed_features) removed,
                  (SELECT COUNT(*) from ngw_updated_attributes) attributes,
                  (SELECT COUNT(*) from ngw_updated_geometries) geometries
                """
        )
        result = cursor.fetchone()

        return DetachedContainerChanges(*result)
