import os
from contextlib import closing
from typing import Optional
from datetime import datetime

import sqlite3
from osgeo import ogr

from qgis.PyQt.QtCore import QFile

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsReadWriteContext, QgsProject,
    QgsMapLayerStyle
)

from ..ng_connect_cache_manager import NgConnectCacheManager


class DetachedLayerFactory:
    def create(self, container_path: str) -> bool:

        self.__prepare_container(container_path)

        return True

    def __prepare_container(self, path: str) -> None:
        with closing(sqlite3.connect(path)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute('PRAGMA foreign_keys = 1')
                self.__initialize_spatial_metadata(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(cursor)

            connection.commit()

    def __initialize_spatial_metadata(self, cursor: sqlite3.Cursor) -> None:
        pass

    def __create_container_tables(self, cursor: sqlite3.Cursor) -> None:
        # TODO add aliases
        cursor.executescript(
            """
            CREATE TABLE ngw_metadata (
                'connection' TEXT,
                'instance_uuid' TEXT,
                'resource_id' INTEGER,
                'synchronization_date' TEXT,
                'auto_synchronization' INTEGER
            );
            CREATE TABLE ngw_added_features (
                'fid' INTEGER
            );
            CREATE TABLE ngw_removed_features (
                'fid' INTEGER
            );
            CREATE TABLE ngw_updated_attributes (
                'fid' INTEGER,
                'attribute' INTEGER
            );
            CREATE TABLE ngw_updated_geometries (
                'fid' INTEGER
            );
            """
        )

    def __insert_metadata(self, cursor: sqlite3.Cursor) -> None:
        connection = 'xxxxxxxx-xxxx-xxxx-xxxx-xxconnection'
        instance = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxinstance'
        resource_id = 1377
        date = datetime.now().isoformat()

        cursor.execute(f'''
            INSERT INTO ngw_metadata VALUES (
                '{connection}', '{instance}', {resource_id}, '{date}', TRUE
            )
        ''')
