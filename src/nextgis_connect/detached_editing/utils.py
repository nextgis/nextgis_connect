import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from functools import singledispatch
from pathlib import Path
from typing import Optional, Union

from qgis.core import (
    QgsExpressionContext,
    QgsFeature,
    QgsMapLayer,
    QgsVectorLayer,
    qgsfunction,
)

from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgConnectError,
)
from nextgis_connect.logging import logger
from nextgis_connect.resources.ngw_field import NgwField, NgwFields


class DetachedLayerState(Enum):
    NotInitialized = auto()
    Error = auto()
    NotSynchronized = auto()
    Synchronization = auto()
    Synchronized = auto()


class VersioningSynchronizationState(Enum):
    NotVersionedLayer = auto()
    NotInitialized = auto()
    Error = auto()
    NotSynchronized = auto()
    FetchingChanges = auto()
    ConflictDetection = auto()
    ConflictSolving = auto()
    ChangesApplying = auto()
    UploadingChanges = auto()
    Synchronized = auto()


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
    is_auto_sync_enabled: bool
    fields: NgwFields
    fid_field: str
    geom_field: str
    features_count: int
    has_changes: bool
    srs_id: int

    @property
    def is_not_initialized(self) -> bool:
        return self.sync_date is None

    @property
    def is_versioning_enabled(self) -> bool:
        return self.epoch is not None and self.version is not None

    def __str__(self) -> str:
        return f'"{self.layer_name}" (id={self.resource_id})'


@dataclass(frozen=True)
class DetachedContainerChangesInfo:
    added_features_count: int = 0
    removed_features_count: int = 0
    updated_attributes_count: int = 0
    updated_geometries_count: int = 0

    @property
    def updated_features_count(self) -> int:
        return self.updated_attributes_count + self.updated_geometries_count


@dataclass(frozen=True)
class FeatureMetaData:
    fid: Optional[int] = None
    ngw_fid: Optional[int] = None
    version: Optional[int] = None
    description: Optional[str] = None


def container_path(layer: Union[QgsMapLayer, Path]) -> Path:
    path = Path()
    if isinstance(layer, QgsMapLayer):
        path = Path(layer.source().split("|")[0])
    elif isinstance(layer, Path):
        path = layer
    else:
        raise TypeError

    if path.suffix != ".gpkg":
        raise ContainerError

    return path


def make_connection(layer: Union[QgsMapLayer, Path]) -> sqlite3.Connection:
    path = container_path(layer)
    return sqlite3.connect(str(path))


def detached_layer_uri(path: Path) -> str:
    try:
        with closing(sqlite3.connect(str(path))) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                SELECT table_name FROM gpkg_contents
                WHERE data_type='features'
                """
            )
            return f"{path}|layername={cursor.fetchone()[0]}"
    except Exception as error:
        raise ContainerError from error


def is_ngw_container(
    layer: Union[QgsMapLayer, Path], *, check_metadata: bool = False
) -> bool:
    def has_properties(layer: QgsMapLayer) -> bool:
        return layer.customProperty(
            "ngw_is_detached_layer", defaultValue=False
        )

    def has_metadata(layer: Union[QgsMapLayer, Path]) -> bool:
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

    if isinstance(layer, QgsVectorLayer):
        if layer.storageType() != "GPKG":
            return False

        if check_metadata:
            return has_metadata(layer)

        return has_properties(layer) or has_metadata(layer)

    elif isinstance(layer, Path):
        return (
            layer.is_file()
            and layer.suffix.lower() == ".gpkg"
            and has_metadata(layer)
        )

    return False


def reset_container_properties(layer: QgsMapLayer) -> None:
    layer.removeCustomProperty("ngw_is_detached_layer")
    layer.removeCustomProperty("ngw_connection_id")
    layer.removeCustomProperty("ngw_resource_id")


@singledispatch
def container_metadata(path_or_cursor) -> DetachedContainerMetaData:
    message = f"Can't fetch metatadata from {type(path_or_cursor)}"
    raise NgConnectError(message)


@container_metadata.register
def _(path: str) -> DetachedContainerMetaData:
    return container_metadata(Path(path))


@container_metadata.register
def _(path: Path) -> DetachedContainerMetaData:
    if not path.exists():
        error = ContainerError(code=ErrorCode.DeletedContainer)
        error.add_note(f"Path: {path}")
        raise error

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
        error_code,
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
    fields = NgwFields(
        NgwField(
            attribute=row[0],
            ngw_id=row[1],
            datatype_name=row[2],
            keyname=row[3],
            display_name=row[4],
            is_label=bool(row[5]),
            lookup_table=row[6],
        )
        for row in cursor.execute(fields_query)
    )

    cursor.execute(
        f"SELECT name from pragma_table_info('{table_name}') WHERE pk = 1"
    )
    fid_field = cursor.fetchone()[0]

    cursor.execute("SELECT column_name from gpkg_geometry_columns")
    geom_field = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM '{table_name}'")
    features_count = cursor.fetchone()[0]
    if features_count is None:
        features_count = 0

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
        container_version=container_version,
        connection_id=connection_id,
        instance_id=instance_id,
        resource_id=resource_id,
        table_name=table_name,
        layer_name=layer_name,
        description=description,
        geometry_name=geometry_name,
        transaction_id=transaction_id,
        epoch=epoch,
        version=version,
        sync_date=sync_date,
        is_auto_sync_enabled=is_auto_sync_enabled,
        fields=fields,
        fid_field=fid_field,
        geom_field=geom_field,
        features_count=features_count,
        has_changes=has_changes,
        srs_id=srs_id,
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
            """
        )
        result = cursor.fetchone()

        return DetachedContainerChangesInfo(*result)


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


# @qgsfunction(group="NextGIS Connect", referenced_columns=["fid"])
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
