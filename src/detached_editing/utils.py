import sqlite3
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from typing import List

from qgis.core import QgsMapLayer, QgsVectorLayer

from ..utils import log_to_qgis


class DetachedLayerState(str, Enum):
    NotInitialized = "NotInitialized"
    Error = "Error"
    NotSynchronized = "NotSynchronized"
    Synchronization = "Synchronization"
    Synchronized = "Synchronized"

    def __str__(self):
        return str(self.value)


@dataclass
class DetachedLayerMetaData:
    connection_id: str
    resource_id: str
    table_name: str
    fields: List[str]


def container_path(layer: QgsMapLayer) -> str:
    return layer.source().split("|")[0]


def is_ngw_container(layer: QgsMapLayer) -> bool:
    def has_properties(layer: QgsMapLayer) -> bool:
        return "ngw_connection_id" in layer.customPropertyKeys()

    def has_metadata(layer: QgsMapLayer) -> bool:
        try:
            with closing(sqlite3.connect(container_path(layer))) as connection:
                with closing(connection.cursor()) as cursor:
                    cursor.execute(
                        """
                        SELECT count(name)
                        FROM sqlite_master
                        WHERE type='table' AND name='ngw_metadata';
                    """
                    )
                    return cursor.fetchone()[0] == 1
        except Exception as error:
            log_to_qgis(str(error))

        return False

    return (
        isinstance(layer, QgsVectorLayer)
        and layer.storageType() == "GPKG"
        and (has_properties(layer) or has_metadata(layer))
    )


def container_metadata(cursor: sqlite3.Cursor) -> DetachedLayerMetaData:
    cursor.execute(
        """
        SELECT connection_id, resource_id FROM ngw_metadata
    """
    )
    connection_id, resource_id = cursor.fetchone()

    cursor.execute(
        """
        SELECT table_name FROM gpkg_contents
        WHERE data_type='features'
    """
    )
    table_name = cursor.fetchone()[0]
    columns = [
        row[0]
        for row in cursor.execute(
            f"SELECT name FROM pragma_table_info('{table_name}') ORDER BY cid"
        )
        if row[0] != "geom"
    ]

    return DetachedLayerMetaData(
        connection_id, resource_id, table_name, columns
    )
