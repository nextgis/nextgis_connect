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

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from functools import singledispatch
from pathlib import Path
from typing import Any, Dict, Optional, Set, Union

from qgis.core import (
    QgsExpressionContext,
    QgsFeature,
    QgsMapLayer,
    QgsVectorLayer,
    qgsfunction,
)

from nextgis_connect.legacy.ngw.resources.ngw_field import NgwField
from nextgis_connect.legacy.ngw.resources.ngw_fields import NgwFields
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import QgsFeatureId
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    ErrorCode,
    NgConnectError,
)
from nextgis_connect.platform.qgis.utils import (
    wrap_sql_table_name,
    wrap_sql_value,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.types import (
    AttachmentId,
    FeatureId,
    FileObjectId,
    NgwAttachmentId,
    NgwFeatureId,
    Unset,
    UnsetType,
    VersionId,
)

_REQUIRED_CONTAINER_TABLES = (
    "ngw_metadata",
    "ngw_fields_metadata",
    "ngw_features_metadata",
    "ngw_features_descriptions",
    "ngw_features_attachments",
    "ngw_added_attributes",
    "ngw_removed_attributes",
    "ngw_added_features",
    "ngw_removed_features",
    "ngw_restored_features",
    "ngw_updated_attributes",
    "ngw_updated_geometries",
    "ngw_updated_descriptions",
    "ngw_added_attachments",
    "ngw_removed_attachments",
    "ngw_updated_attachments",
    "ngw_restored_attachments",
)

_CHANGE_TABLES = (
    "ngw_added_features",
    "ngw_removed_features",
    "ngw_restored_features",
    "ngw_updated_attributes",
    "ngw_updated_geometries",
    "ngw_updated_descriptions",
    "ngw_added_attachments",
    "ngw_removed_attachments",
    "ngw_updated_attachments",
    "ngw_restored_attachments",
)

_FEATURE_UPDATE_TABLES = (
    "ngw_updated_attributes",
    "ngw_updated_geometries",
    "ngw_updated_descriptions",
)

_ATTACHMENT_UPDATE_TABLES = (
    "ngw_added_attachments",
    "ngw_removed_attachments",
    "ngw_updated_attachments",
    "ngw_restored_attachments",
)

_METADATA_COLUMN_DEFAULTS = {
    "container_version": "'0.0.0'",
    "connection_id": "NULL",
    "instance_id": "NULL",
    "resource_id": "0",
    "display_name": "''",
    "description": "NULL",
    "geometry_type": "NULL",
    "transaction_id": "NULL",
    "epoch": "NULL",
    "version": "NULL",
    "sync_date": "NULL",
    "error_code": "NULL",
    "is_auto_sync_enabled": "0",
}


def _table_names(cursor: sqlite3.Cursor) -> Set[str]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in cursor.fetchall()}


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> Set[str]:
    cursor.execute(f"PRAGMA table_info({wrap_sql_table_name(table_name)})")
    return {row[1] for row in cursor.fetchall()}


def _has_current_container_schema(table_names: Set[str]) -> bool:
    return all(
        table_name in table_names for table_name in _REQUIRED_CONTAINER_TABLES
    )


def _metadata_column_expression(
    column_name: str,
    existing_columns: Set[str],
) -> str:
    wrapped_column_name = wrap_sql_table_name(column_name)
    if column_name in existing_columns:
        return wrapped_column_name

    default_value = _METADATA_COLUMN_DEFAULTS[column_name]
    return f"{default_value} AS {wrapped_column_name}"


def _table_row_count(
    cursor: sqlite3.Cursor,
    table_names: Set[str],
    table_name: str,
) -> int:
    if table_name not in table_names:
        return 0

    cursor.execute(
        f"SELECT COUNT(*) FROM {wrap_sql_table_name(table_name)}",
    )
    result = cursor.fetchone()[0]
    return int(result or 0)


def _table_has_rows(
    cursor: sqlite3.Cursor,
    table_names: Set[str],
    table_name: str,
) -> bool:
    if table_name not in table_names:
        return False

    cursor.execute(
        f"""
        SELECT EXISTS(
            SELECT 1 FROM {wrap_sql_table_name(table_name)} LIMIT 1
        )
        """,
    )
    return bool(cursor.fetchone()[0])


def _feature_ids_from_table(
    cursor: sqlite3.Cursor,
    table_names: Set[str],
    table_name: str,
) -> Set[FeatureId]:
    if table_name not in table_names:
        return set()

    cursor.execute(f"SELECT fid FROM {wrap_sql_table_name(table_name)}")
    return {row[0] for row in cursor.fetchall() if row[0] is not None}


def _attachment_feature_ids_from_table(
    cursor: sqlite3.Cursor,
    table_names: Set[str],
    table_name: str,
) -> Set[FeatureId]:
    if (
        table_name not in table_names
        or "ngw_features_attachments" not in table_names
    ):
        return set()

    cursor.execute(
        f"""
        SELECT fid FROM ngw_features_attachments
        WHERE aid IN (
            SELECT aid FROM {wrap_sql_table_name(table_name)}
        )
        """,
    )
    return {row[0] for row in cursor.fetchall() if row[0] is not None}


def _has_container_changes(
    cursor: sqlite3.Cursor,
    table_names: Set[str],
) -> bool:
    return any(
        _table_has_rows(cursor, table_names, table_name)
        for table_name in _CHANGE_TABLES
    )


def has_required_fields_metadata(cursor: sqlite3.Cursor) -> bool:
    cursor.execute("PRAGMA table_info(ngw_fields_metadata)")
    return any(row[1] == "is_required" for row in cursor.fetchall())


def ensure_required_fields_metadata(cursor: sqlite3.Cursor) -> None:
    if has_required_fields_metadata(cursor):
        return

    cursor.execute(
        """
        ALTER TABLE ngw_fields_metadata
        ADD COLUMN is_required BOOLEAN DEFAULT 0
        """
    )


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
    instance_id: str
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
    geom_field: Optional[str]
    features_count: int
    has_changes: bool
    srs_id: int
    is_schema_complete: bool = True

    @property
    def is_not_initialized(self) -> bool:
        return self.sync_date is None

    @property
    def is_versioning_enabled(self) -> bool:
        return self.epoch is not None and self.version is not None

    def __str__(self) -> str:
        return f'"{self.layer_name}" (id={self.resource_id})'


@dataclass(frozen=True)
class DetachedContainerContext:
    path: Path
    metadata: DetachedContainerMetaData


@dataclass(frozen=True)
class DetachedContainerChangesInfo:
    added_features_count: int = 0
    removed_features_count: int = 0
    restored_features_count: int = 0
    updated_features_count: int = 0


@dataclass(frozen=True)
class FeatureMetadata:
    fid: FeatureId
    ngw_fid: Optional[NgwFeatureId] = None
    version: Optional[VersionId] = None


def container_path(layer: Union[QgsMapLayer, Path, str]) -> Path:
    path = Path()
    if isinstance(layer, QgsMapLayer):
        path = Path(layer.source().split("|")[0])
    elif isinstance(layer, Path):
        path = layer
    elif isinstance(layer, str):
        path = Path(layer.split("|")[0])
    else:
        raise TypeError

    if path.suffix != ".gpkg":
        raise ContainerError

    return path


@dataclass(frozen=True)
class AttachmentMetadata:
    """Metadata for an attachment."""

    fid: FeatureId
    aid: AttachmentId
    ngw_fid: Optional[NgwFeatureId] = None
    ngw_aid: Optional[NgwAttachmentId] = None
    version: Union[VersionId, UnsetType] = Unset
    keyname: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    fileobj: Union[FileObjectId, UnsetType, None] = Unset
    mime_type: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    file_meta: Optional[Dict[str, Any]] = None
    file_path: Optional[Path] = None
    thumbnail_path: Optional[Path] = None


def make_connection(layer: Union[QgsMapLayer, Path]) -> sqlite3.Connection:
    connection = sqlite3.connect(str(container_path(layer)))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def detached_layer_uri(
    path_or_context: Union[Path, DetachedContainerContext],
    metadata: Optional[DetachedContainerMetaData] = None,
) -> str:
    """
    Build a layer URI for a detached container.

    Accepts either:
    - `path_or_context` as a `Path` and optional `metadata`, or
    - `path_or_context` as a `DetachedContainerContext` (metadata is
      taken from the context in this case).
    """
    if isinstance(path_or_context, DetachedContainerContext):
        context = path_or_context
        path = context.path
        metadata = context.metadata
    else:
        path = path_or_context

    if metadata is not None:
        return f"{path}|layername={metadata.table_name}"

    try:
        with closing(make_connection(path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                """
                SELECT table_name FROM gpkg_contents
                WHERE data_type IN ('features', 'attributes')
                ORDER BY CASE data_type
                    WHEN 'features' THEN 0
                    WHEN 'attributes' THEN 1
                    ELSE 2
                END
                LIMIT 1
                """
            )
            layer_name = cursor.fetchone()[0]
            return f"{path}|layername={layer_name}"
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
                make_connection(container_path(layer))
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
        if not layer.source().split("|")[0].endswith(".gpkg"):
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
    layer.removeCustomProperty("ngw_instance_id")
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

    with closing(make_connection(path)) as connection, closing(
        connection.cursor()
    ) as cursor:
        return container_metadata(cursor)


@container_metadata.register
def _(cursor: sqlite3.Cursor) -> DetachedContainerMetaData:
    table_names = _table_names(cursor)
    metadata_table_columns = _table_columns(cursor, "ngw_metadata")
    metadata_columns = [
        "container_version",
        "connection_id",
        "instance_id",
        "resource_id",
        "display_name",
        "description",
        "geometry_type",
        "transaction_id",
        "epoch",
        "version",
        "sync_date",
        "error_code",
        "is_auto_sync_enabled",
    ]
    metadata_column_expressions = [
        _metadata_column_expression(column_name, metadata_table_columns)
        for column_name in metadata_columns
    ]

    cursor.execute(
        f"""
        SELECT {", ".join(metadata_column_expressions)}
        FROM ngw_metadata
        """
    )
    row = cursor.fetchone()

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
        _error_code,
        is_auto_sync_enabled,
    ) = row

    if sync_date is not None:
        sync_date = datetime.fromisoformat(sync_date)

    cursor.execute(
        """
        SELECT table_name, srs_id FROM gpkg_contents
        WHERE data_type IN ('features', 'attributes')
        ORDER BY CASE data_type
            WHEN 'features' THEN 0
            WHEN 'attributes' THEN 1
            ELSE 2
        END
        LIMIT 1
        """
    )
    table_name, srs_id = cursor.fetchone()

    has_required_metadata = has_required_fields_metadata(cursor)
    fields_columns = [
        "attribute",
        "ngw_id",
        "datatype_name",
        "keyname",
        "display_name",
        "is_label",
    ]
    if has_required_metadata:
        fields_columns.append("is_required")
    fields_columns.append("lookup_table")

    fields_query = """
        SELECT
            {fields_columns}
        FROM ngw_fields_metadata
    """.format(fields_columns=",\n            ".join(fields_columns))
    fields = NgwFields(
        NgwField(
            attribute=row[0],
            ngw_id=row[1],
            datatype=row[2],
            keyname=row[3],
            display_name=row[4],
            is_label=bool(row[5]),
            is_required=bool(row[6]) if has_required_metadata else False,
            lookup_table=row[7] if has_required_metadata else row[6],
        )
        for row in cursor.execute(fields_query)
    )

    cursor.execute(
        f"""
        SELECT name FROM pragma_table_info({wrap_sql_value(table_name)})
        WHERE pk = 1
        """
    )
    fid_field = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT column_name FROM gpkg_geometry_columns
        WHERE table_name = ?
        """,
        (table_name,),
    )
    row = cursor.fetchone()
    geom_field = row[0] if row is not None else None

    cursor.execute(
        f"SELECT COUNT(*) FROM {wrap_sql_table_name(table_name)}",
    )
    features_count = cursor.fetchone()[0]
    if features_count is None:
        features_count = 0

    has_changes = _has_container_changes(cursor, table_names)

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
        is_schema_complete=_has_current_container_schema(table_names),
    )


def container_changes(path: Path) -> DetachedContainerChangesInfo:
    with closing(make_connection(path)) as connection, closing(
        connection.cursor()
    ) as cursor:
        table_names = _table_names(cursor)
        added_feature_ids = _feature_ids_from_table(
            cursor,
            table_names,
            "ngw_added_features",
        )
        updated_feature_ids = set()
        for table_name in _FEATURE_UPDATE_TABLES:
            updated_feature_ids.update(
                _feature_ids_from_table(cursor, table_names, table_name)
            )
        for table_name in _ATTACHMENT_UPDATE_TABLES:
            updated_feature_ids.update(
                _attachment_feature_ids_from_table(
                    cursor,
                    table_names,
                    table_name,
                )
            )

        return DetachedContainerChangesInfo(
            added_features_count=len(added_feature_ids),
            removed_features_count=_table_row_count(
                cursor,
                table_names,
                "ngw_removed_features",
            ),
            restored_features_count=_table_row_count(
                cursor,
                table_names,
                "ngw_restored_features",
            ),
            updated_features_count=len(
                updated_feature_ids - added_feature_ids
            ),
        )


def is_feature_new(feature_id: QgsFeatureId) -> bool:
    return feature_id < 0


def is_attachment_new(attachment_id: AttachmentId) -> bool:
    return attachment_id < 0


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
        with closing(make_connection(path)) as connection, closing(
            connection.cursor()
        ) as cursor:
            cursor.execute(
                f"SELECT ngw_fid FROM ngw_features_metadata WHERE fid={fid}"
            )
            result = cursor.fetchone()
            if result is not None:
                return result[0]

    except Exception:
        logger.exception("Error occurred while querying ngw_fid")

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

    layer = context.variable("layer")
    if layer is None:
        return None

    try:
        detached_editing = NgConnectInterface.instance().detached_editing
        detached_layer = detached_editing.layer(layer)
        if (
            detached_layer is None
            or not detached_layer.container.metadata.is_versioning_enabled
        ):
            return None
        return detached_layer.feature_description(feature)

    except Exception:
        logger.exception("Error occurred while querying feature description")

    return None


@qgsfunction(group="NextGIS Connect", referenced_columns=["fid"])
def ngw_feature_attachments_count(
    feature: QgsFeature, context: QgsExpressionContext
) -> Optional[int]:
    """
    Returns NextGIS Web feature attachments count
    <h2>Example usage:</h2>
    <ul>
      <li>ngw_feature_attachments_count()</li>
    </ul>
    """

    layer = context.variable("layer")
    if layer is None:
        return None

    try:
        detached_editing = NgConnectInterface.instance().detached_editing
        detached_layer = detached_editing.layer(layer)
        if (
            detached_layer is None
            or not detached_layer.container.metadata.is_versioning_enabled
        ):
            return None
        return detached_layer.feature_attachments_count(feature)

    except Exception:
        logger.exception(
            "Error occurred while querying feature attachments count"
        )

    return None
