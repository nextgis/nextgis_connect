from contextlib import closing
from datetime import datetime

import sqlite3

from ..ngw_api.core.ngw_vector_layer import NGWVectorLayer


class DetachedLayerFactory:
    def create(self, ngw_layer: NGWVectorLayer, container_path: str) -> bool:

        self.__prepare_container(ngw_layer, container_path)

        return True

    def __prepare_container(
        self, ngw_layer: NGWVectorLayer, path: str
    ) -> None:
        with closing(sqlite3.connect(path)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute('PRAGMA foreign_keys = 1')
                self.__initialize_spatial_metadata(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor)

            connection.commit()

    def __initialize_spatial_metadata(self, cursor: sqlite3.Cursor) -> None:
        pass

    def __create_container_tables(self, cursor: sqlite3.Cursor) -> None:
        # TODO add aliases
        cursor.executescript(
            """
            CREATE TABLE ngw_metadata (
                'container_version' TEXT,
                'connection_id' TEXT,
                'instance_id' TEXT,
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

    def __insert_metadata(
        self, ngw_layer: NGWVectorLayer, cursor: sqlite3.Cursor
    ) -> None:
        connection = ngw_layer.connection_id
        # instance = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxinstance'
        resource_id = ngw_layer.common.id
        date = datetime.now().isoformat()

        cursor.execute(f'''
            INSERT INTO ngw_metadata VALUES (
                '0.1.0', '{connection}', NULL, {resource_id}, '{date}', TRUE
            )
        ''')
