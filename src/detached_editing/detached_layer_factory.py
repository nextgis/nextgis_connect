import sqlite3
from contextlib import closing
from datetime import datetime

from ..ngw_api.core.ngw_vector_layer import NGWVectorLayer


class DetachedLayerFactory:
    def create(self, ngw_layer: NGWVectorLayer, container_path: str) -> bool:
        with closing(sqlite3.connect(container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__fill_tables(ngw_layer, cursor)

            connection.commit()

        return True

    def __initialize_container_settings(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA foreign_keys = 1")

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
            CREATE TABLE ngw_features_id (
                'fid' INTEGER,
                'ngw_id' INTEGER
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

    def __fill_tables(
        self, ngw_layer: NGWVectorLayer, cursor: sqlite3.Cursor
    ) -> None:
        self.__insert_metadata(ngw_layer, cursor)
        self.__insert_ngw_ids(cursor)

    def __insert_metadata(
        self, ngw_layer: NGWVectorLayer, cursor: sqlite3.Cursor
    ) -> None:
        connection = ngw_layer.connection_id
        # instance = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxinstance'
        resource_id = ngw_layer.common.id
        date = datetime.now().isoformat()

        cursor.execute(
            f"""
            INSERT INTO ngw_metadata VALUES (
                '0.2.0', '{connection}', NULL, {resource_id}, '{date}', TRUE
            )
        """
        )

    def __insert_ngw_ids(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            SELECT table_name FROM gpkg_contents
            WHERE data_type='features'
        """
        )
        table_name = cursor.fetchone()[0]
        cursor.execute(
            f"INSERT INTO ngw_features_id SELECT fid, fid FROM '{table_name}'"
        )
