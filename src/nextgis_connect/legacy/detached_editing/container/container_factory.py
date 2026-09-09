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

from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerMetaData,
    container_metadata,
    detached_layer_uri,
    make_connection,
)
from nextgis_connect.legacy.ngw.core.ngw_resource import API_LAYER_EXTENT
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    NgwServerFeature,
)
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import FieldType
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    ErrorCode,
    LayerEditError,
    NgConnectError,
)
from nextgis_connect.platform.qgis.extent_calculator import ExtentCalculator
from nextgis_connect.platform.qgis.utils import (
    wrap_sql_table_name,
    wrap_sql_value,
)


class DetachedContainerFactory:
    def create_initial_container(
        self, ngw_layer: NGWVectorLayer, container_path: Path
    ) -> None:
        container_type = (
            "with versioning"
            if ngw_layer.is_versioning_enabled
            else "without versioning"
        )
        logger.debug(
            "Start creating initial container for layer "
            + container_type
            + f' "{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )
        try:
            self.__ensure_no_geometry_supported(ngw_layer)
            self.__create_container(ngw_layer, container_path)
            self.__check_fields(ngw_layer, container_path)

            with closing(
                make_connection(container_path)
            ) as connection, closing(connection.cursor()) as cursor:
                self.__update_container_extent(ngw_layer, cursor)
                self.__initialize_container_settings(cursor)
                self.__create_container_tables(cursor)
                self.__insert_metadata(ngw_layer, cursor)

                connection.commit()

        except NgConnectError:
            self.__remove_container_files(container_path)
            raise

        except Exception as error:
            self.__remove_container_files(container_path)
            message = "Failed to create container"
            code = ErrorCode.ContainerCreationError
            raise ContainerError(message, code=code) from error

        else:
            logger.debug(
                "Container successfully created and filled with metadata"
            )

    def __remove_container_files(self, container_path: Path) -> None:
        try:
            for service_file in container_path.parent.glob(
                f"{container_path.name}-*"
            ):
                service_file.unlink(missing_ok=True)
            container_path.unlink(missing_ok=True)
        except Exception:
            logger.exception(
                f"Could not remove broken detached container {container_path}"
            )

    def __ensure_no_geometry_supported(
        self, ngw_layer: NGWVectorLayer
    ) -> None:
        if ngw_layer.geom_name != "NONE":
            return

        connection = ngw_layer.res_factory.connection
        required_feature = NgwServerFeature.NO_GEOMETRY_LAYERS
        if ngw_layer.is_versioning_enabled:
            required_feature = NgwServerFeature.NO_GEOMETRY_LAYER_VERSIONING

        if connection.has_support_for_feature(required_feature):
            return

        required_version = required_feature.required_version
        user_message = (
            "The connected NextGIS Web version does not support "
            "layers without geometry."
        )
        if ngw_layer.is_versioning_enabled:
            user_message = (
                "The connected NextGIS Web version does not support "
                "versioning for layers without geometry."
            )

        message = (
            f'Layer "{ngw_layer.display_name}" without geometry '
            f"requires NextGIS Web {required_version} or newer"
        )
        raise ContainerError(
            message,
            user_message=user_message,
            detail=(
                f'Layer "{ngw_layer.display_name}" requires '
                f"NextGIS Web {required_version} or newer."
            ),
            code=ErrorCode.ContainerCreationError,
        )

    def fill_container(
        self,
        ngw_layer: NGWVectorLayer,
        *,
        source_path: Path,
        container_path: Path,
    ) -> None:
        logger.debug(
            f"Start filling container for layer "
            f'"{ngw_layer.display_name}" (id={ngw_layer.resource_id})'
        )

        try:
            metadata = container_metadata(container_path)
            fid_field = metadata.fid_field
            self.__check_fields(ngw_layer, source_path, fid_field=fid_field)
            self.__check_fields(ngw_layer, container_path, fid_field=fid_field)

            self.__copy_features(source_path, container_path, metadata)

            with closing(
                make_connection(container_path)
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
    ) -> None:
        project = QgsProject.instance()
        assert project is not None

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = f"vector_layer_{ngw_layer.resource_id}"
        options.fileEncoding = "UTF-8"
        fid_field, fields = self.__prepare_fields(ngw_layer.qgs_fields)
        options.layerOptions = [
            *QgsVectorFileWriter.defaultDatasetOptions("GPKG"),
            f"FID={fid_field}",
        ]

        container_path.parent.mkdir(parents=True, exist_ok=True)

        writer = QgsVectorFileWriter.create(
            fileName=str(container_path),
            fields=fields,
            geometryType=ngw_layer.wkb_geom_type,
            transformContext=project.transformContext(),
            srs=ngw_layer.qgs_srs,
            options=options,
        )
        assert writer is not None

        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            error_message = writer.errorMessage()
            logger.error(f"Failed to create GPKG container: {error_message}")
            writer = None
            raise ContainerError(
                "Failed to create GPKG container",
                detail=error_message,
                code=ErrorCode.ContainerCreationError,
            )

        writer = None
        logger.debug("Empty container successfully created")

    def __update_container_extent(
        self,
        ngw_layer: NGWVectorLayer,
        cursor: sqlite3.Cursor,
    ) -> None:
        if ngw_layer.geom_name in (None, "NONE"):
            return

        target_crs = ngw_layer.qgs_srs
        if not target_crs.isValid():
            return

        try:
            response = ngw_layer.connection.get(
                API_LAYER_EXTENT(ngw_layer.resource_id)
            )
            extent = ExtentCalculator.from_ngw_extent_dict(response)
            if extent is None:
                return

            extent = ExtentCalculator.transform(extent, target_crs)
            if extent is None:
                return

            cursor.execute(
                """
                UPDATE gpkg_contents
                SET min_x = ?, min_y = ?, max_x = ?, max_y = ?
                WHERE table_name = ?
                """,
                (
                    extent.xMinimum(),
                    extent.yMinimum(),
                    extent.xMaximum(),
                    extent.yMaximum(),
                    f"vector_layer_{ngw_layer.resource_id}",
                ),
            )
        except Exception:
            logger.exception(
                f"Could not set extent for detached container "
                f"{ngw_layer.resource_id}"
            )

    def __initialize_container_settings(self, cursor: sqlite3.Cursor) -> None:
        pass

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

            -- Fields metadata
            CREATE TABLE ngw_fields_metadata (
                'attribute' INTEGER PRIMARY KEY, -- Field ID in QGIS
                'ngw_id' INTEGER, -- Field ID in NextGIS Web
                'datatype_name' TEXT,
                'keyname' TEXT,
                'display_name' TEXT,
                'is_label' BOOLEAN,
                'is_required' BOOLEAN,
                'lookup_table' INTEGER
            );

            -- Features metadata
            CREATE TABLE ngw_features_metadata (
                'fid' INTEGER PRIMARY KEY, -- Feature ID in GPKG
                'ngw_fid' INTEGER, -- Feature ID in NextGIS Web
                'version' INTEGER
            );

            -- Features descriptions
            CREATE TABLE ngw_features_descriptions (
                'fid' INTEGER PRIMARY KEY, -- Feature ID in GPKG
                'version' INTEGER,
                'description' TEXT,
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Attachments metadata
            CREATE TABLE ngw_features_attachments (
                'fid' INTEGER,
                'aid' INTEGER PRIMARY KEY AUTOINCREMENT, -- Attachment ID in GPKG
                'ngw_aid' INTEGER UNIQUE, -- Attachment ID in NextGIS Web
                'version' INTEGER,
                'keyname' TEXT,
                'name' TEXT,
                'description' TEXT,
                'fileobj' INTEGER,
                'mime_type' TEXT,
                'size' INTEGER,
                'sha256' TEXT,
                FOREIGN KEY (fid) REFERENCES ngw_features_metadata(fid) ON DELETE CASCADE
            );

            -- Added attributes
            CREATE TABLE ngw_added_attributes (
                'attribute' INTEGER PRIMARY KEY,
                FOREIGN KEY (attribute) REFERENCES ngw_fields_metadata(attribute) ON DELETE CASCADE
            );

            -- Removed attributes
            CREATE TABLE ngw_removed_attributes (
                'attribute' INTEGER PRIMARY KEY,
                'backup' TEXT, -- Backup information
                FOREIGN KEY (attribute) REFERENCES ngw_fields_metadata(attribute) ON DELETE CASCADE
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
                'backup' TEXT, -- Backup information
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

            -- Updated descriptions
            CREATE TABLE ngw_updated_descriptions (
                'fid' INTEGER PRIMARY KEY, -- Unique updated description ID
                'backup' TEXT, -- Description before update
                FOREIGN KEY (fid) REFERENCES ngw_features_descriptions(fid) ON DELETE CASCADE
            );

            -- Added attachments
            CREATE TABLE ngw_added_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique added attachment ID
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Removed attachments
            CREATE TABLE ngw_removed_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique removed attachment ID
                'backup' TEXT, -- Backup information
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Updated attachments
            CREATE TABLE ngw_updated_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique updated attachment ID
                'backup' TEXT, -- Backup information
                FOREIGN KEY (aid) REFERENCES ngw_features_attachments(aid) ON DELETE CASCADE
            );

            -- Restored attachments
            CREATE TABLE ngw_restored_attachments (
                'aid' INTEGER PRIMARY KEY, -- Unique restored attachment ID
                'backup' TEXT, -- Backup information
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
            "container_version": settings.supported_container_version,
            "instance_id": connection.domain_uuid,
            "connection_id": ngw_layer.connection_id,
            "resource_id": ngw_layer.resource_id,
            "display_name": ngw_layer.display_name,
            "description": ngw_layer.description,
            "geometry_type": ngw_layer.geom_name,
            "error_code": None,
            "is_auto_sync_enabled": True,
        }
        metadata = {
            key: wrap_sql_value(value) for key, value in metadata.items()
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
                field.datatype.name,
                field.keyname,
                field.display_name,
                field.is_label,
                field.is_required,
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
                is_required,
                lookup_table
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            fid_attribute = self._index_of_field_with_keyname(
                target_layer.fields(), metadata.fid_field
            )
            assert fid_attribute is not None

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
            INSERT INTO ngw_features_metadata (fid, ngw_fid)
                SELECT {fid_field}, {fid_field}
                FROM {wrap_sql_table_name(table_name)}
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
            layer.fields(),
            skip_fields=skip_fields,
            layer=layer,
            compare_required=False,
        ):
            code = ErrorCode.ContainerFieldsMismatch
            raise ContainerError(code=code)

    def __prepare_fields(self, fields: QgsFields) -> Tuple[str, QgsFields]:
        FID_PREFIX = "fid"
        fid_field = FID_PREFIX
        index = 0

        result_fields = QgsFields()
        while self._index_of_field_with_keyname(fields, fid_field) is not None:
            index += 1
            fid_field = f"{FID_PREFIX}_{index}"

        result_fields.append(QgsField(fid_field, FieldType.LongLong))

        for field in fields.toList():
            result_fields.append(field)

        return fid_field, result_fields

    def _index_of_field_with_keyname(
        self, fields: QgsFields, keyname: str
    ) -> Optional[int]:
        for index, field in enumerate(fields.toList()):
            if field.name().lower() == keyname.lower():
                return index
        return None
