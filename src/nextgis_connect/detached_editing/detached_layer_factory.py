import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple, cast

from qgis.core import (
    QgsEditError,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    edit,
)

from nextgis_connect.compat import FieldType
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    detached_layer_uri,
)
from nextgis_connect.exceptions import (
    ContainerError,
    ErrorCode,
    LayerEditError,
    NgConnectError,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.settings import NgConnectSettings


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
            logger.debug(
                "Container successfully created and filled with metadata"
            )

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
            metadata = container_metadata(container_path)
            fid_field = metadata.fid_field
            self.__check_fields(ngw_layer, source_path, fid_field=fid_field)
            self.__check_fields(ngw_layer, container_path, fid_field=fid_field)

            self.__copy_features(source_path, container_path, metadata)

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
                f'Container for layer "{ngw_layer.display_name}" successfully '
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
            -- Main metadata table
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
                'is_auto_sync_enabled' BOOLEAN,
                PRIMARY KEY ('instance_id', 'resource_id')
            );

            -- Features metadata
            CREATE TABLE ngw_features_metadata (
                'fid' INTEGER PRIMARY KEY, -- Feature ID in GPKG
                'ngw_fid' INTEGER, -- Feature ID in NextGIS Web
                'version' INTEGER,
                'description' TEXT
            );

            -- Attachments metadata
            CREATE TABLE ngw_features_attachments (
                'fid' INTEGER,
                'aid' INTEGER PRIMARY KEY, -- Attachment ID in GPKG
                'ngw_aid' INTEGER, -- Attachment ID in NextGIS Web
                'name' TEXT,
                'keyname' TEXT,
                'description' TEXT,
                'file_meta' TEXT,
                'mime_type' TEXT,
                'size' INTEGER,
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Fields metadata
            CREATE TABLE ngw_fields_metadata (
                'attribute' INTEGER PRIMARY KEY, -- Field ID in QGIS
                'ngw_id' INTEGER, -- Field ID in NextGIS Web
                'datatype_name' TEXT,
                'keyname' TEXT,
                'display_name' TEXT,
                'is_label' BOOLEAN,
                'lookup_table' INTEGER
            );

            -- Added attributes
            CREATE TABLE ngw_added_attributes (
                'cid' INTEGER PRIMARY KEY,
                FOREIGN KEY (cid) REFERENCES ngw_fields_metadata(attribute) ON DELETE CASCADE
            );

            -- Removed attributes
            CREATE TABLE ngw_removed_attributes (
                'cid' INTEGER PRIMARY KEY,
                FOREIGN KEY (cid) REFERENCES ngw_fields_metadata(attribute) ON DELETE CASCADE
            );

            -- Added features
            CREATE TABLE ngw_added_features (
                'fid' INTEGER PRIMARY KEY,
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Removed features
            CREATE TABLE ngw_removed_features (
                'fid' INTEGER PRIMARY KEY, -- Unique removed feature ID
                'backup' TEXT, -- Backup information
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Restored features
            CREATE TABLE ngw_restored_features (
                'fid' INTEGER PRIMARY KEY, -- Unique restored feature ID
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Updated attributes
            CREATE TABLE ngw_updated_attributes (
                'fid' INTEGER, -- Feature ID
                'attribute' INTEGER, -- Attribute ID
                'backup' TEXT, -- Field state before changes
                PRIMARY KEY (fid, attribute),
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE,
                FOREIGN KEY (attribute) REFERENCES ngw_fields_metadata(attribute) ON DELETE CASCADE
            );

            -- Updated geometries
            CREATE TABLE ngw_updated_geometries (
                'fid' INTEGER PRIMARY KEY, -- Unique updated geometry ID
                'backup' TEXT, -- Geometry before update
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Added attachments
            CREATE TABLE ngw_added_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique added attachment ID
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Removed attachments
            CREATE TABLE ngw_removed_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique removed attachment ID
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Updated attachments
            CREATE TABLE ngw_updated_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique updated attachment ID
                'data_has_changed' BOOLEAN, -- Indicates if the data has changed
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Index to speed up searches by ngw_fid
            CREATE INDEX idx_features_ngw_fid ON ngw_features_metadata (ngw_fid);
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

        settings = NgConnectSettings()
        metadata = {
            "container_version": f"'{settings.supported_container_version}'",
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
        metadata: DetachedContainerMetaData,
    ) -> None:
        source_layer = QgsVectorLayer(
            detached_layer_uri(source_path), "", "ogr"
        )
        target_layer = QgsVectorLayer(
            detached_layer_uri(container_path), "", "ogr"
        )

        try:
            target_fields = target_layer.fields()
            fid_attribute = target_layer.fields().indexOf(metadata.fid_field)

            with edit(target_layer):
                for source_feature in cast(
                    Iterable[QgsFeature], source_layer.getFeatures()
                ):
                    source_atributes = source_feature.attributeMap()

                    # Create feature
                    target_feature = QgsFeature(target_fields)

                    # Set fid
                    ngw_fid = source_atributes[metadata.fid_field]
                    assert isinstance(ngw_fid, int)
                    target_feature.setId(ngw_fid)
                    target_feature.setAttribute(fid_attribute, ngw_fid)

                    # Set attributes
                    for field in metadata.fields:
                        target_feature.setAttribute(
                            field.attribute, source_atributes[field.keyname]
                        )

                    # Set geometry
                    target_feature.setGeometry(source_feature.geometry())

                    # Add feature
                    target_layer.addFeature(target_feature)

        except QgsEditError as error:
            raise LayerEditError.from_qgis_error(
                error, log_message="Features was not copied"
            ) from None

        except Exception as error:
            ng_error = ContainerError(log_message="Features was not copied")
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

        skip_fields = [
            layer.fields().at(layer.primaryKeyAttributes()[0]).name()
        ]
        if fid_field is not None:
            skip_fields.append(fid_field)

        skip_fields = [
            skip_field
            for skip_field in skip_fields
            if ngw_layer.fields.find_with(keyname=skip_field) is None
        ]

        if not ngw_layer.fields.is_compatible(
            layer.fields(), skip_fields=skip_fields
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
