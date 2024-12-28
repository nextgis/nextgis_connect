import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from qgis.core import (
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    edit,
)

from nextgis_connect.compat import FieldType
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
)
from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    NgConnectError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_connection import NgwConnectionsManager


class DetachedLayerFactory:
    def create_initial_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> None:
        container_type = (
            "with versioning"
            if ngw_layer.is_versioning_enabled
            else "without versioning"
        )
        logger.debug(
            "<b>Start creating initial container</b> for layer "
            + container_type
            + f' "{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )
        try:
            self.__create_container(ngw_layer, container_path)
            self.__check_fields(ngw_layer, container_path)

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

    def fill_container(
        self,
        ngw_layer: NGWVectorLayer,
        *,
        source_path: Path,
        container_path: Path,
    ) -> None:
        logger.debug(
            f"<b>Start filling container</b> for layer "
            f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )

        try:
            fid_field = container_metadata(container_path).fid_field
            self.__check_fields(ngw_layer, source_path, fid_field=fid_field)
            self.__check_fields(ngw_layer, container_path, fid_field=fid_field)

            self.__copy_features(source_path, container_path)

            with closing(
                sqlite3.connect(str(container_path))
            ) as connection, closing(connection.cursor()) as cursor:
                self.__insert_ngw_ids(cursor)
                self.__update_sync_date(cursor)

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
        fid_field, fields = self.__prepare_fields(ngw_layer.qgs_fields)
        options.layerOptions = [
            *QgsVectorFileWriter.defaultDatasetOptions("GPKG"),
            f"FID={fid_field}",
        ]

        writer = QgsVectorFileWriter.create(
            fileName=str(container_path),
            fields=fields,
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

    def __copy_features(
        self,
        source_path: Path,
        container_path: Path,
    ) -> None:
        source_layer = QgsVectorLayer(
            detached_layer_uri(source_path), "", "ogr"
        )
        target_layer = QgsVectorLayer(
            detached_layer_uri(container_path), "", "ogr"
        )

        try:
            with edit(target_layer):
                for feature in source_layer.getFeatures():  # type: ignore
                    feature.setId(-1)
                    target_layer.addFeature(feature)

        except Exception as error:
            ng_error = ContainerError(log_message="Features was not copied")
            ng_error.add_note("Layer error: " + target_layer.lastError())
            raise ng_error from error

    def __insert_ngw_ids(self, cursor: sqlite3.Cursor) -> None:
        metadata = container_metadata(cursor)
        table_name = metadata.table_name
        fid_field = metadata.fid_field
        cursor.execute(
            f"""
            INSERT INTO ngw_features_metadata
                SELECT {fid_field}, {fid_field}, NULL, NULL FROM '{table_name}'
            """
        )

    def __update_sync_date(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            f"UPDATE ngw_metadata SET sync_date='{datetime.now().isoformat()}'"
        )

    def __check_fields(
        self,
        ngw_layer: NGWVectorLayer,
        container_path: Path,
        *,
        fid_field: Optional[str] = None,
    ) -> None:
        layer = QgsVectorLayer(detached_layer_uri(container_path), "", "ogr")
        if not layer.isValid():
            message = "Container is not valid"
            code = ErrorCode.ContainerIsInvalid
            raise ContainerError(message, code=code)

        if fid_field is None:
            fid_field = (
                layer.fields().at(layer.primaryKeyAttributes()[0]).name()
            )

        if not ngw_layer.fields.is_compatible(
            layer.fields(), fid_field=fid_field
        ):
            code = ErrorCode.ContainerFieldsMismatch
            raise ContainerError(code=code)

    def __prepare_fields(self, fields: QgsFields) -> Tuple[str, QgsFields]:
        FID_PREFIX = "fid"
        fid_field = FID_PREFIX
        index = 0

        result_fields = QgsFields()
        while fields.indexOf(fid_field) != -1:
            index += 1
            fid_field = f"{FID_PREFIX}_{index}"

        result_fields.append(QgsField(fid_field, FieldType.LongLong))

        for field in fields.toList():
            result_fields.append(field)

        return fid_field, result_fields
