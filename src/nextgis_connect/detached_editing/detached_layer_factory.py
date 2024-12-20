import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

# isort: off
from qgis.core import QgsVectorFileWriter, QgsProject
# isort: on

from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgConnectError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_connection import NgwConnectionsManager

# TODO (ivanbarsukov): rename in v3.0


class DetachedLayerFactory:
    def create_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> None:
        container_type = (
            "initial" if ngw_layer.is_versioning_enabled else "stub"
        )
        logger.debug(
            f"<b>Start creating {container_type} container</b> for layer "
            f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )
        try:
            self.__create_container(ngw_layer, container_path)

            with closing(
                sqlite3.connect(str(container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor)

                connection.commit()

        except NgConnectError:
            raise

        except Exception as error:
            container_path.unlink(missing_ok=True)
            message = "Failed to create container"
            code = ErrorCode.ContainerCreationError
            raise ContainerError(message, code=code) from error

        else:
            logger.debug("Container successfuly created")

    def update_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> None:
        logger.debug(
            f"<b>Start updating container</b> for layer "
            f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )

        try:
            with closing(
                sqlite3.connect(str(container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor, is_update=True)
                self.__insert_ngw_ids(cursor)

                connection.commit()

        except NgConnectError:
            raise

        except Exception as error:
            message = "Failed to update container"
            code = ErrorCode.ContainerCreationError
            raise ContainerError(message, code=code) from error

        else:
            logger.debug(
                f'Container for layer "{ngw_layer.display_name}" successfuly '
                "updated"
            )

    def __create_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> bool:
        project = QgsProject.instance()
        assert project is not None

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = ngw_layer.display_name
        options.fileEncoding = "UTF-8"

        writer = QgsVectorFileWriter.create(
            fileName=str(container_path),
            fields=ngw_layer.qgs_fields,
            geometryType=ngw_layer.wkb_geom_type,
            transformContext=project.transformContext(),
            srs=ngw_layer.qgs_srs,
            options=options,
        )
        assert writer is not None

        is_success = False
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            logger.error(
                f"Failed to create GPKG container: {writer.errorMessage()}"
            )
        else:
            logger.debug("Empty container successfully created")
            is_success = True

        writer = None

        return is_success

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
                'display_name' TEXT,
                'description' TEXT,
                'geometry_type' TEXT,
                'transaction_id' INTEGER,
                'epoch' INTEGER,
                'version' INTEGER,
                'sync_date' DATETIME,
                'error_code' INTEGER,
                'is_auto_sync_enabled' BOOLEAN
            );
            CREATE TABLE ngw_features_metadata (
                'fid' INTEGER,
                'ngw_fid' INTEGER,
                'version' INTEGER,
                'description' TEXT
            );
            CREATE INDEX idx_features_fid ON ngw_features_metadata (fid);
            CREATE TABLE ngw_features_attachments (
                'fid' INTEGER,
                'aid' INTEGER,
                'ngw_aid' INTEGER,
                'name' TEXT,
                'keyname' TEXT,
                'description' TEXT,
                'file_meta' TEXT,
                'mime_type' TEXT,
                'size' INTEGER
            );
            CREATE TABLE ngw_fields_metadata (
                'attribute' INTEGER,
                'ngw_id' INTEGER,
                'datatype_name' TEXT,
                'keyname' TEXT,
                'display_name' TEXT,
                'is_label' BOOLEAN,
                'lookup_table' INTEGER
            );

            CREATE TABLE ngw_added_attributes (
                'cid' INTEGER
            );
            CREATE TABLE ngw_removed_attributes (
                'cid' INTEGER
            );

            CREATE TABLE ngw_added_features (
                'fid' INTEGER
            );
            CREATE TABLE ngw_removed_features (
                'fid' INTEGER
            );
            CREATE TABLE ngw_restored_features (
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

    def __insert_metadata(
        self,
        ngw_layer: NGWVectorLayer,
        cursor: sqlite3.Cursor,
        *,
        is_update: bool = False,
    ) -> None:
        if ngw_layer.geom_name is None:
            pass

        connection = NgwConnectionsManager().connection(
            ngw_layer.connection_id
        )
        assert connection is not None

        metadata = {
            "container_version": "'1.0.0'",
            "instance_id": f"'{connection.domain_uuid}'",
            "connection_id": f"'{ngw_layer.connection_id}'",
            "resource_id": str(ngw_layer.resource_id),
            "display_name": f"'{ngw_layer.display_name}'",
            "description": f"'{ngw_layer.description}'"
            if ngw_layer.description is not None
            else "NULL",
            "geometry_type": f"'{ngw_layer.geom_name}'",
            "error_code": "NULL",
            "is_auto_sync_enabled": "true",
        }

        if ngw_layer.is_versioning_enabled:
            metadata["epoch"] = str(ngw_layer.epoch)
            metadata["version"] = str(ngw_layer.version)
        elif is_update:
            metadata["sync_date"] = f"'{datetime.now().isoformat()}'"

        fields_name = ", ".join(metadata.keys())
        values = ", ".join(metadata.values())
        cursor.execute(
            f"INSERT INTO ngw_metadata ({fields_name}) VALUES ({values})"
        )

        fields_tuple_generator = (
            (
                field.attribute + 1,
                field.ngw_id,
                field.datatype_name,
                field.keyname,
                field.display_name,
                field.is_label,
                field.lookup_table,
            )
            for field in ngw_layer.fields
        )
        cursor.executemany(
            """
            INSERT INTO ngw_fields_metadata (
                attribute,
                ngw_id,
                datatype_name,
                keyname,
                display_name,
                is_label,
                lookup_table
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fields_tuple_generator,
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
