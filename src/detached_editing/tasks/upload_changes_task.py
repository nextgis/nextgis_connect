import sqlite3
from contextlib import closing
from typing import Optional, Tuple, List, Dict, Any, Set
from datetime import datetime

from qgis.PyQt.QtCore import QVariant, pyqtSignal

from qgis.core import QgsApplication, QgsTask, QgsVectorLayer, QgsFeature

from ...ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection

from ...ngw_connection.ngw_connection import NgwConnection
from ...ngw_connection.ngw_connections_manager import NgwConnectionsManager

from .. import utils


class UploadChangesTask(QgsTask):
    synchronization_finished = pyqtSignal(bool, name='synchronizationFinished')

    def __init__(
        self, layer: QgsVectorLayer
    ) -> None:
        description = QgsApplication.translate(
            'NGConnectPlugin', 'Detached layer synchronization'
        )
        flags = QgsTask.Flags()
        if hasattr(QgsTask.Flag, 'Silent'):
            flags |= QgsTask.Flag.Silent
        super().__init__(description, flags)

        self.setDependentLayers([layer])
        self.__layer = layer.clone()
        assert self.__layer is not None

    def run(self) -> bool:
        try:
            container_path = utils.container_path(self.__layer)
            with closing(sqlite3.connect(container_path)) as connection:
                with closing(connection.cursor()) as cursor:
                    connection_id, resource_id = self.__layer_metadata(cursor)

                    self.__upload_changes(connection_id, resource_id, cursor)

                    self.__update_sync_date(cursor)
                    self.__clear_log_tables(cursor)
        except Exception:
            return False

        return True

    def finished(self, result: bool) -> None:
        self.synchronization_finished.emit(result)

        return super().finished(result)

    def __layer_metadata(self, cursor: sqlite3.Cursor) -> Tuple[str, int]:
        cursor.execute('''
            SELECT connection_id, resource_id FROM ngw_metadata
        ''')
        return cursor.fetchone()

    def __clear_log_tables(self, cursor: sqlite3.Cursor) -> None:
        cursor.executescript(
            '''
            DELETE FROM ngw_added_features;
            DELETE FROM ngw_removed_features;
            DELETE FROM ngw_updated_attributes;
            DELETE FROM ngw_updated_geometries;
            '''
        )

    def __update_sync_date(self, cursor: sqlite3.Cursor) -> None:
        now = datetime.now()
        sync_date = now.isoformat()
        cursor.execute(
            f"UPDATE ngw_metadata SET synchronization_date='{sync_date}'"
        )
        self.__layer.setCustomProperty('ngw_synchronization_date', now)

    def __upload_changes(
        self,
        connection_id: str,
        resource_id: int,
        cursor: sqlite3.Cursor
    ) -> None:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None

        ngw_connection = QgsNgwConnection(connection_id)

        self.__upload_added(ngw_connection, resource_id, cursor)
        self.__upload_removed(ngw_connection, resource_id, cursor)
        self.__upload_updated(ngw_connection, resource_id, cursor)

    def __upload_added(
        self,
        connection: QgsNgwConnection,
        resource_id: int,
        cursor: sqlite3.Cursor
    ) -> None:
        feature_ids: List[int] = [
            row[0]
            for row in cursor.execute(
                'SELECT fid from ngw_added_features'
            )
        ]
        if len(feature_ids) == 0:
            return

        body: List[Dict[str, Any]] = []
        for feature_id in feature_ids:
            qgs_feature = self.__layer.getFeature(feature_id)
            ngw_feature = self.__qgs_feature_to_ngw_feature(qgs_feature)
            del ngw_feature['id']
            body.append(ngw_feature)

        url = f'/api/resource/{resource_id}/feature/'
        connection.patch(url, body)
        # TODO save new fid

    def __upload_removed(
        self,
        connection: QgsNgwConnection,
        resource_id: int,
        cursor: sqlite3.Cursor
    ) -> None:
        feature_ids: List[Dict[str, int]] = [
            {'id': row[0]}
            for row in cursor.execute(
                'SELECT fid from ngw_removed_features'
            )
        ]
        if len(feature_ids) == 0:
            return

        url = f'/api/resource/{resource_id}/feature/'
        connection.delete(url, feature_ids)

    def __upload_updated(
        self,
        connection: QgsNgwConnection,
        resource_id: int,
        cursor: sqlite3.Cursor
    ) -> None:
        updated_fields_values = cursor.execute(
            'SELECT fid, attribute from ngw_updated_attributes'
        )
        updated_fields: Dict[int, Set[str]] = {}
        fields = self.__layer.fields()
        for fid, attribute in updated_fields_values:
            if fid not in updated_fields:
                updated_fields[fid] = set()
            updated_fields[fid].add(fields[attribute].name())

        updated_geom_feature_ids: Set[int] = set(
            row[0]
            for row in cursor.execute(
                'SELECT fid from ngw_updated_geometries'
            )
        )

        all_updated_fids = set(updated_fields.keys()).union(updated_geom_feature_ids)
        if len(all_updated_fids) == 0:
            return

        body: List[Dict[str, Any]] = []
        for feature_id in all_updated_fids:
            qgs_feature = self.__layer.getFeature(feature_id)
            ngw_feature = self.__qgs_feature_to_ngw_feature(qgs_feature)

            if feature_id not in updated_fields:
                ngw_feature.pop('fields', None)
            else:
                all_fields = ngw_feature['fields']
                only_updated_fields = {
                    name: all_fields[name]
                    for name in updated_fields[feature_id]
                }
                ngw_feature['fields'] = only_updated_fields

            if feature_id not in updated_geom_feature_ids:
                ngw_feature.pop('geom', None)

            body.append(ngw_feature)

        url = f'/api/resource/{resource_id}/feature/'
        connection.patch(url, body)

    def __qgs_feature_to_ngw_feature(
        self, feature: QgsFeature
    ) -> Dict[str, Any]:
        ngw_feature: Dict[str, Any] = {}
        ngw_feature['geom'] = feature.geometry().asWkt()

        fields = {
            field.name(): feature.attribute(field.name())
            for field in feature.fields()
        }
        fields = {
            name: value
            for name, value in fields.items()
            if (
                value is not None
                and (
                    (isinstance(value, QVariant) and not value.isNull())
                    or not isinstance(value, QVariant)
                )
            )
        }
        ngw_feature['id'] = fields['fid']
        del fields['fid']
        if len(fields) > 0:
            ngw_feature['fields'] = fields

        return ngw_feature
