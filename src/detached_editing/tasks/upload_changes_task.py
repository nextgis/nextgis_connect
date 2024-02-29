import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import pyqtSignal
from qgis.utils import spatialite_connect

from ...ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from ...ngw_connection.ngw_connections_manager import NgwConnectionsManager
from ..utils import DetachedLayerMetaData, container_metadata


class UploadChangesTask(QgsTask):
    synchronization_finished = pyqtSignal(bool, name="synchronizationFinished")

    __container_path: str
    __error: Optional[Exception]

    def __init__(self, container_path: str) -> None:
        description = QgsApplication.translate(
            "NgConnectPlugin", "Detached layer synchronization"
        )
        flags = QgsTask.Flags()
        if hasattr(QgsTask.Flag, "Silent"):
            flags |= QgsTask.Flag.Silent
        super().__init__(description, flags)

        self.__container_path = container_path

    def run(self) -> bool:
        import debugpy

        if debugpy.is_client_connected():
            debugpy.debug_this_thread()

        container_path = self.__container_path
        try:
            with closing(spatialite_connect(container_path)) as connection:
                with closing(connection.cursor()) as cursor:
                    layer_metadata = container_metadata(cursor)

                    self.__upload_changes(layer_metadata, cursor)
                    self.__update_sync_date(cursor)
        except Exception as error:
            self.__error = error
            return False

        return True

    def finished(self, result: bool) -> None:
        self.synchronization_finished.emit(result)

        return super().finished(result)

    @property
    def error(self) -> Optional[Exception]:
        return self.__error

    def __update_sync_date(self, cursor: sqlite3.Cursor) -> None:
        now = datetime.now()
        sync_date = now.isoformat()
        cursor.execute(
            f"UPDATE ngw_metadata SET synchronization_date='{sync_date}'"
        )

    def __upload_changes(
        self, layer_metadata: DetachedLayerMetaData, cursor: sqlite3.Cursor
    ) -> None:
        connection_id = layer_metadata.connection_id

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None

        ngw_connection = QgsNgwConnection(connection_id)

        self.__upload_added(ngw_connection, layer_metadata, cursor)
        self.__upload_removed(ngw_connection, layer_metadata, cursor)
        self.__upload_updated(ngw_connection, layer_metadata, cursor)

    def __upload_added(
        self,
        connection: QgsNgwConnection,
        layer_metadata: DetachedLayerMetaData,
        cursor: sqlite3.Cursor,
    ) -> None:
        columns = ", ".join(
            f"features.{field}" for field in layer_metadata.fields
        )
        added_cursor = cursor.execute(
            f"""
            SELECT {columns}, ST_AsText(geom)
            FROM '{layer_metadata.table_name}' features
            RIGHT JOIN 'ngw_added_features' added
                ON features.fid = added.fid
        """
        )
        added_features = self.__cusor_to_ngw_features(
            layer_metadata, added_cursor
        )
        if len(added_features) == 0:
            return

        body: List[Dict[str, Any]] = []
        fids: List[int] = []
        for added_feature in added_features:
            fid = added_feature.pop("id")
            fids.append(fid)
            body.append(added_feature)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        assigned_fids = connection.patch(url, body)

        values = ", ".join(
            f'({fid}, {assigned_fids[i]["id"]})' for i, fid in enumerate(fids)
        )
        cursor.executescript(
            f"""
            BEGIN TRANSACTION;
            INSERT INTO ngw_features_id (fid, ngw_id) VALUES {values};
            DELETE FROM ngw_added_features;
            COMMIT;
        """
        )

    def __upload_removed(
        self,
        connection: QgsNgwConnection,
        layer_metadata: DetachedLayerMetaData,
        cursor: sqlite3.Cursor,
    ) -> None:
        feature_ids: List[Dict[str, int]] = [
            {"id": row[0]}
            for row in cursor.execute(
                """
                SELECT ngw_id from ngw_features_id fids
                RIGHT JOIN ngw_removed_features removed
                    ON fids.fid = removed.fid
            """
            )
        ]
        if len(feature_ids) == 0:
            return

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        connection.delete(url, feature_ids)

        cursor.executescript(
            """
            BEGIN TRANSACTION;
            DELETE FROM ngw_features_id
                WHERE fid in (SELECT fid FROM ngw_removed_features);
            DELETE FROM ngw_removed_features;
            COMMIT;
        """
        )

    def __upload_updated(
        self,
        connection: QgsNgwConnection,
        layer_metadata: DetachedLayerMetaData,
        cursor: sqlite3.Cursor,
    ) -> None:
        updated_fields: Dict[int, Set[str]] = {}
        updated_fields_values = cursor.execute(
            "SELECT fid, attribute from ngw_updated_attributes"
        )
        for fid, attribute_index in updated_fields_values:
            if fid not in updated_fields:
                updated_fields[fid] = set()
            updated_fields[fid].add(layer_metadata.fields[attribute_index])

        updated_geom_fids: Set[int] = set(
            row[0]
            for row in cursor.execute("SELECT fid from ngw_updated_geometries")
        )

        all_updated_fids = set(updated_fields.keys()).union(updated_geom_fids)
        if len(all_updated_fids) == 0:
            return

        all_updated_fids_joined = ", ".join(
            str(fid) for fid in all_updated_fids
        )
        columns = ", ".join(
            f"features.{field}" for field in layer_metadata.fields
        )
        updated_cursor = cursor.execute(
            f"""
            SELECT {columns}, ST_AsText(geom)
            FROM '{layer_metadata.table_name}' features
            WHERE features.fid IN ({all_updated_fids_joined})
        """
        )
        updated_features = self.__cusor_to_ngw_features(
            layer_metadata, updated_cursor
        )

        feautre_ids = {
            fid: ngw_id
            for fid, ngw_id in cursor.execute(
                f"""
                SELECT fid, ngw_id FROM ngw_features_id
                WHERE fid IN ({all_updated_fids_joined})
            """
            )
        }

        body: List[Dict[str, Any]] = []
        for ngw_feature in updated_features:
            fid = ngw_feature["id"]
            ngw_feature["id"] = feautre_ids[fid]
            if fid not in updated_fields:
                ngw_feature.pop("fields", None)
            else:
                all_fields = ngw_feature["fields"]
                only_updated_fields = {
                    name: all_fields[name] for name in updated_fields[fid]
                }
                ngw_feature["fields"] = only_updated_fields

            if fid not in updated_geom_fids:
                ngw_feature.pop("geom", None)

            body.append(ngw_feature)

        url = f"/api/resource/{layer_metadata.resource_id}/feature/"
        connection.patch(url, body)

        cursor.executescript(
            """
            BEGIN TRANSACTION;
            DELETE FROM ngw_updated_attributes;
            DELETE FROM ngw_updated_geometries;
            COMMIT;
        """
        )

    def __cusor_to_ngw_features(
        self,
        layer_metadata: DetachedLayerMetaData,
        cursor: sqlite3.Cursor,
    ) -> List[Dict[str, Any]]:
        ngw_features: List[Dict[str, Any]] = []

        for row in cursor:
            ngw_feature: Dict[str, Any] = {}
            ngw_feature["geom"] = row[-1]

            fields = {
                layer_metadata.fields[i]: value
                for i, value in enumerate(row[:-1])
                if value is not None
            }

            ngw_feature["id"] = fields["fid"]
            del fields["fid"]
            if len(fields) > 0:
                ngw_feature["fields"] = fields

            ngw_features.append(ngw_feature)

        return ngw_features
