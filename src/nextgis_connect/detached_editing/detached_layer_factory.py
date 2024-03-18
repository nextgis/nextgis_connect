import sqlite3
from contextlib import closing
from datetime import datetime

from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from qgis.utils import spatialite_connect


class DetachedLayerFactory:
    def update_container(
        self, ngw_layer: NGWVectorLayer, container_path: str
    ) -> bool:
        with closing(spatialite_connect(container_path)) as connection:
            with closing(connection.cursor()) as cursor:
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__fill_tables(ngw_layer, cursor)

            connection.commit()

        return True

    def __initialize_container_settings(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA foreign_keys = 1")

    def __create_container_tables(self, cursor: sqlite3.Cursor) -> None:
        cursor.executescript(
            """
            CREATE TABLE ngw_metadata (
                'container_version' TEXT,
                'connection_id' TEXT,
                'instance_id' TEXT,
                'resource_id' INTEGER,
                'geometry_type' INTEGER,
                'transaction_id' INTEGER,
                'epoch' INTEGER,
                'sync_date' DATETIME,
                'is_broken' BOOLEAN,
                'is_auto_sync_enabled' BOOLEAN
            );
            CREATE TABLE ngw_features_metadata (
                'fid' INTEGER,
                'ngw_fid' INTEGER,
                'version' INTEGER,
                'description' TEXT
            );
            CREATE TABLE ngw_features_attachments (
                'fid' INTEGER,
                'aid' INTEGER,
                'ngw_aid' INTEGER,
                'data' BLOB,
                'mime_type' TEXT,
                'name' TEXT,
                'description' TEXT
            );
            CREATE TABLE ngw_fields_metadata (
                'attribute' INTEGER,
                'ngw_id' INTEGER,
                'keyname' TEXT,
                'display_name' TEXT,
                'lookup_table' INTEGER,
                'datatype' TEXT
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

            CREATE TABLE ngw_added_attachments (
                'aid' INTEGER
            );
            CREATE TABLE ngw_removed_attachments (
                'aid' INTEGER
            );
            CREATE TABLE ngw_updated_attachments (
                'aid' INTEGER,
                'data_has_changed' BOOLEAN
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
        resource_id = ngw_layer.common.id
        date = datetime.now().isoformat()

        cursor.execute(
            f"""
            INSERT INTO ngw_metadata (
                container_version, connection_id, resource_id, sync_date
            ) VALUES (
                '1.0.0', '{connection}', {resource_id}, '{date}'
            )
        """
        )

        fields = [
            (
                field.get("id"),
                field.get("keyname"),
                field.get("display_name"),
                field.get("lookup_table"),
                field.get("datatype"),
            )
            for field in ngw_layer.field_defs.values()
        ]
        cursor.executemany(
            "INSERT INTO ngw_fields_metadata VALUES (?, ?, ?, ?, ?, ?)",
            ((i, *field) for i, field in enumerate(fields, start=1)),
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
            f"""
            INSERT INTO ngw_features_metadata
                SELECT fid, fid, NULL, NULL FROM '{table_name}'
        """
        )
