import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

# isort: off
from qgis.core import QgsVectorFileWriter, QgsProject
from qgis.utils import spatialite_connect
# isort: on

from nextgis_connect.compat import WkbType
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer


class DetachedLayerFactory:
    def create_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> bool:
        container_type = (
            "initial" if ngw_layer.is_versioning_enabled else "stub"
        )
        logger.debug(
            f"<b>Start creating {container_type} container</b> for layer "
            f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )
        is_created = self.__create_container(ngw_layer, container_path)
        if not is_created:
            return False

        try:
            with (
                closing(spatialite_connect(str(container_path))) as connection,
                closing(connection.cursor()) as cursor,
            ):
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor)

                connection.commit()
        except Exception:
            logger.exception("Failed to update container")
            return False
        else:
            logger.debug("Container metadata successfuly updated")
            return True

    def update_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> bool:
        try:
            with (
                closing(spatialite_connect(str(container_path))) as connection,
                closing(connection.cursor()) as cursor,
            ):
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor, is_update=True)
                self.__insert_ngw_ids(cursor)

                connection.commit()
        except Exception:
            logger.exception(
                "Failed to update NGW container for layer "
                f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
            )
            return False
        else:
            logger.debug(
                f'Container for layer "{ngw_layer.display_name}" successfuly '
                "updated"
            )
            return True

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
            geometryType=WkbType(ngw_layer.wkb_geom_type),
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
                'is_broken' BOOLEAN,
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
                'datatype_name' TEXT,
                'lookup_table' INTEGER
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

    def __insert_metadata(
        self,
        ngw_layer: NGWVectorLayer,
        cursor: sqlite3.Cursor,
        *,
        is_update: bool = False,
    ) -> None:
        metadata = {
            "container_version": "'1.0.0'",
            "connection_id": f"'{ngw_layer.connection_id}'",
            "resource_id": str(ngw_layer.resource_id),
            "display_name": f"'{ngw_layer.display_name}'",
            "description": f"'{ngw_layer.common.description}'",
            "geometry_type": f"'{ngw_layer.geom_name}'",
            "is_broken": "false",
            "is_auto_sync_enabled": "true",
        }

        if ngw_layer.is_versioning_enabled:
            metadata["epoch"] = str(ngw_layer.epoch)
            metadata["version"] = str(ngw_layer.latest_version)
        elif is_update:
            metadata["sync_date"] = f"'{datetime.now().isoformat()}'"

        fields_name = ", ".join(metadata.keys())
        values = ", ".join(metadata.values())
        cursor.execute(
            f"INSERT INTO ngw_metadata ({fields_name}) VALUES ({values})"
        )

        # raise RuntimeError

        def get_lookup_table(field):
            table = field.get("lookup_table")
            if table is None:
                return None
            return table.get("id")

        fields = [
            (
                field.get("id"),
                field.get("keyname"),
                field.get("display_name"),
                field.get("datatype_name"),
                get_lookup_table(field),
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
