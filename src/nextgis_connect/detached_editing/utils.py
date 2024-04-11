import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum, auto
from functools import singledispatch
from pathlib import Path
from typing import List, Optional

from qgis.core import (
    QgsExpressionContext,
    QgsFeature,
    QgsMapLayer,
    QgsVectorLayer,
    qgsfunction,
)

from nextgis_connect.logging import logger
from nextgis_connect.resources.ngw_field import NgwField


class DetachedLayerState(Enum):
    NotInitialized = auto()
    Error = auto()
    NotSynchronized = auto()
    Synchronization = auto()
    Synchronized = auto()


class VersioningSynchronizationState(Enum):
    NotVersionedLayer = auto()
    NotInitialized = auto()
    NotSynchronized = auto()
    FetchingChanges = auto()
    ConflictSolving = auto()
    ChangesApplying = auto()
    UploadingChanges = auto()
    FetchingUploaded = auto()
    Synchronized = auto()


class DetachedLayerErrorType(IntEnum):
    NoError = 200

    SynchronizationError = 300
    NetworkError = auto()
    AuthError = auto()
    NotEnoughRights = auto()

    ContainerError = 400
    CreationError = auto()
    DeletedContainer = auto()
    NotCompletedFetch = auto()
    ConnectionNotExist = auto()
    EpochChanged = auto()
    StructureChanged = auto()
    NotVersionedContentChanged = auto()

    ResourceError = 500
    ResourceWasDeleted = auto()

    @property
    def is_sync_error(self) -> bool:
        return self.SynchronizationError <= self < self.ContainerError

    @property
    def is_container_error(self) -> bool:
        return self.ContainerError <= self < self.ResourceError

    @property
    def is_resource_error(self) -> bool:
        return self >= self.ResourceError

    @property
    def is_sync_allowed(self) -> bool:
        return self == self.NoError


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
    srs_id: int

    @property
    def is_stub(self) -> bool:
        return self.sync_date is None

    @property
    def is_versioning_enabled(self) -> bool:
        return self.epoch is not None and self.version is not None

    def __str__(self) -> str:
        return f'"{self.layer_name}" (id={self.resource_id})'


@dataclass
class DetachedContainerChangesInfo:
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
            with closing(
                sqlite3.connect(container_path(layer))
            ) as connection, closing(connection.cursor()) as cursor:
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
    with closing(sqlite3.connect(str(path))) as connection, closing(
        connection.cursor()
    ) as cursor:
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
        SELECT table_name, srs_id FROM gpkg_contents
        WHERE data_type='features'
        """
    )
    table_name, srs_id = cursor.fetchone()

    fields_query = """
        SELECT
            attribute,
            ngw_id,
            datatype_name,
            keyname,
            display_name,
            is_label,
            lookup_table
        FROM ngw_fields_metadata
    """
    fields = [NgwField(*row) for row in cursor.execute(fields_query)]

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
        srs_id,
    )


def container_changes(path: Path) -> DetachedContainerChangesInfo:
    with closing(sqlite3.connect(str(path))) as connection, closing(
        connection.cursor()
    ) as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM ngw_added_features) added,
              (SELECT COUNT(*) FROM ngw_removed_features) removed,
              (SELECT COUNT(DISTINCT fid) FROM ngw_updated_attributes) attributes,
              (SELECT COUNT(*) FROM ngw_updated_geometries) geometries
            """  # noqa: E501
        )
        result = cursor.fetchone()

        return DetachedContainerChangesInfo(*result)


def is_fields_compatible(lhs: List[NgwField], rhs: List[NgwField]) -> bool:
    if len(lhs) != len(rhs):
        return False

    for lhs_field, rhs_field in zip(lhs, rhs):
        if (
            lhs_field.ngw_id != rhs_field.ngw_id
            or lhs_field.datatype_name != rhs_field.datatype_name
            or lhs_field.keyname != rhs_field.keyname
        ):
            return False

    return True


@qgsfunction(group="NextGIS Connect", referenced_columns=["fid"])
def ngw_feature_id(
    feature: QgsFeature, context: QgsExpressionContext
) -> Optional[int]:
    """
    Returns NextGIS Web feature id
    <h2>Example usage:</h2>
    <ul>
      <li>ngw_feature_id()</li>
    </ul>
    """

    fid = feature.id()
    layer = context.variable("layer")
    if layer is None or not is_ngw_container(layer):
        return None

    path = container_path(layer)
    try:
        with closing(sqlite3.connect(str(path))) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                f"SELECT ngw_fid FROM ngw_features_metadata WHERE fid={fid}"
            )
            result = cursor.fetchone()
            if result is not None:
                return result[0]

    except Exception:
        logger.exception("Error occured while querying ngw_fid")

    return None


@qgsfunction(group="NextGIS Connect", referenced_columns=["fid"])
def ngw_feature_description(
    feature: QgsFeature, context: QgsExpressionContext
) -> Optional[str]:
    """
    Returns NextGIS Web feature description
    <h2>Example usage:</h2>
    <ul>
      <li>ngw_feature_description()</li>
    </ul>
    """

    fid = feature.id()
    layer = context.variable("layer")
    if layer is None or not is_ngw_container(layer):
        return None

    path = container_path(layer)
    try:
        with closing(sqlite3.connect(str(path))) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                "SELECT description FROM ngw_features_metadata"
                f" WHERE fid={fid}"
            )
            result = cursor.fetchone()
            if result is not None:
                return result[0]

    except Exception:
        logger.exception("Error occured while querying ngw_fid")

    return None