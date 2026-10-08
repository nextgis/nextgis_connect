# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from qgis.PyQt.QtCore import QCoreApplication

from nextgis_connect.legacy.detached_editing.attachment_files import (
    AttachmentFiles,
)
from nextgis_connect.legacy.detached_editing.change_tracker import (
    DetachedChangeTracker,
    ExtensionChanges,
)
from nextgis_connect.legacy.detached_editing.sync.common.serialization import (
    deserialize_value,
    serialize_geometry,
    serialize_value,
    simplify_value,
)
from nextgis_connect.legacy.detached_editing.utils import (
    DetachedContainerMetaData,
    make_connection,
)
from nextgis_connect.platform.qgis.errors import ContainerError


class DetachedChangeJournal:
    """Write one batch of container metadata using one SQLite transaction."""

    QUERY_BATCH_SIZE = 900

    def __init__(
        self,
        path: Path,
        metadata: DetachedContainerMetaData,
        files: Optional[AttachmentFiles] = None,
    ) -> None:
        self.path = path
        self.metadata = metadata
        self.files = files if files is not None else AttachmentFiles(metadata)

    def write(
        self,
        changes: DetachedChangeTracker,
        extensions: Optional[ExtensionChanges] = None,
    ) -> bool:
        """Commit the whole batch or propagate an error after rollback.

        Provider data is already saved and is not part of this transaction.
        Pass no extensions when finalizing a provider rollback. The caller
        owns the batch and decides when to clear it.

        :return: Whether the batch contained changes.
        """
        has_extensions = extensions is not None and extensions.has_changes
        if not changes.has_changes and not has_extensions:
            return False
        try:
            with closing(make_connection(self.path)) as connection:
                with connection, closing(connection.cursor()) as cursor:
                    connection.execute("BEGIN IMMEDIATE")
                    self._add_features(cursor, changes.added)
                    self._update_features(cursor, changes)
                    self._remove_features(cursor, changes)
                    if extensions is not None:
                        self._write_descriptions(
                            cursor, extensions, changes.removed
                        )
                        self._write_attachments(
                            cursor, extensions, changes.removed
                        )
        except Exception:
            self.files.rollback()
            raise
        self.files.register()
        return True

    def _rows(
        self,
        cursor: sqlite3.Cursor,
        table: str,
        column: str,
        identifiers: Iterable[int],
        select: str = "*",
    ) -> List[Tuple[Any, ...]]:
        result = []
        identifiers = sorted(set(identifiers))
        for offset in range(0, len(identifiers), self.QUERY_BATCH_SIZE):
            batch = identifiers[offset : offset + self.QUERY_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            result.extend(
                cursor.execute(
                    f"SELECT {select} FROM {table} WHERE {column} IN ({placeholders})",
                    batch,
                )
            )
        return result

    def _ids(
        self,
        cursor: sqlite3.Cursor,
        table: str,
        column: str,
        identifiers: Iterable[int],
    ) -> Set[int]:
        return {
            row[0]
            for row in self._rows(cursor, table, column, identifiers, column)
        }

    def _add_features(
        self, cursor: sqlite3.Cursor, feature_ids: Set[int]
    ) -> None:
        for table in ("ngw_features_metadata", "ngw_added_features"):
            cursor.executemany(
                f"INSERT INTO {table} (fid) VALUES (?)",
                ((fid,) for fid in feature_ids),
            )

    def _update_features(
        self, cursor: sqlite3.Cursor, changes: DetachedChangeTracker
    ) -> None:
        feature_ids = set(changes.attributes) | changes.geometries
        feature_ids -= self._ids(
            cursor, "ngw_added_features", "fid", feature_ids
        )
        feature_ids -= self._ids(
            cursor, "ngw_removed_features", "fid", feature_ids
        )
        attributes = [
            (fid, attribute)
            for fid in feature_ids
            for attribute in changes.attributes.get(fid, ())
        ]
        geometries = feature_ids & changes.geometries
        self._require_metadata(
            cursor, "ngw_features_metadata", "fid", feature_ids, "feature IDs"
        )
        self._require_metadata(
            cursor,
            "ngw_fields_metadata",
            "attribute",
            {attribute for _, attribute in attributes},
            "attribute IDs",
        )
        for kind, missing in (
            ("attribute", set(attributes) - set(changes.attribute_backups)),
            ("geometry", geometries - set(changes.geometry_backups)),
        ):
            if missing:
                error = ContainerError(
                    f"Can't create feature changes records because {kind} backups are missing.",
                    user_message=QCoreApplication.translate(
                        "DetachedLayer",
                        "The changes could not be recorded in the synchronization "
                        "journal. Unrecorded changes may not be synchronized.",
                    ),
                )
                error.add_note(f"Missing {kind} backups: {sorted(missing)}")
                raise error
        cursor.executemany(
            "INSERT INTO ngw_updated_attributes (fid, attribute, backup) "
            "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (
                (fid, attribute, changes.attribute_backups[(fid, attribute)])
                for fid, attribute in attributes
            ),
        )
        cursor.executemany(
            "INSERT INTO ngw_updated_geometries (fid, backup) "
            "VALUES (?, ?) ON CONFLICT DO NOTHING",
            ((fid, changes.geometry_backups[fid]) for fid in geometries),
        )

    def _require_metadata(
        self,
        cursor: sqlite3.Cursor,
        table: str,
        column: str,
        identifiers: Set[int],
        label: str,
    ) -> None:
        missing = identifiers - self._ids(cursor, table, column, identifiers)
        if missing:
            details = f"{label} {', '.join(map(str, sorted(missing)))} are missing in {table}"
            error = ContainerError(
                "Can't create feature changes records because required container "
                "metadata is missing.",
                user_message=QCoreApplication.translate(
                    "DetachedLayer",
                    "The detached layer metadata is incomplete: {details}. "
                    "Unrecorded changes may not be synchronized.",
                ).format(details=details),
            )
            error.add_note(details)
            raise error

    def _attachment_rows(
        self, cursor: sqlite3.Cursor, column: str, identifiers: Iterable[int]
    ) -> List[Tuple[Any, ...]]:
        return self._rows(
            cursor,
            "ngw_features_attachments AS a "
            "LEFT JOIN ngw_features_metadata AS f ON a.fid = f.fid "
            "LEFT JOIN ngw_updated_attachments AS u ON a.aid = u.aid "
            "LEFT JOIN ngw_removed_attachments AS r ON a.aid = r.aid",
            column,
            identifiers,
            "a.fid, f.ngw_fid, a.aid, a.ngw_aid, a.version, a.keyname, "
            "a.name, a.description, a.fileobj, a.mime_type, u.backup, r.backup",
        )

    def _attachment_backup(self, row: Tuple[Any, ...]) -> Dict[str, Any]:
        result: Dict[str, Any] = dict(
            zip(
                (
                    "fid",
                    "ngw_fid",
                    "aid",
                    "ngw_aid",
                    "version",
                    "keyname",
                    "name",
                    "description",
                    "fileobj",
                    "mime_type",
                ),
                row[:10],
            )
        )
        result["version"] = serialize_value(result["version"])
        result["fileobj"] = serialize_value(result["fileobj"])
        return result

    def _remove_features(
        self, cursor: sqlite3.Cursor, changes: DetachedChangeTracker
    ) -> None:
        added = self._ids(cursor, "ngw_added_features", "fid", changes.removed)
        cursor.executemany(
            "DELETE FROM ngw_features_metadata WHERE fid = ? AND ngw_fid IS NULL",
            ((fid,) for fid in added),
        )
        removed = changes.removed - added
        fields = {
            (fid, attribute): deserialize_value(backup)
            for fid, attribute, backup in self._rows(
                cursor, "ngw_updated_attributes", "fid", removed
            )
        }
        geometries = dict(
            self._rows(cursor, "ngw_updated_geometries", "fid", removed)
        )
        descriptions = {
            row[0]: row[1:]
            for row in self._rows(
                cursor,
                "ngw_features_descriptions AS d "
                "LEFT JOIN ngw_updated_descriptions AS u ON d.fid = u.fid",
                "d.fid",
                removed,
                "d.fid, d.description, d.version, u.backup",
            )
        }
        attachments: Dict[
            int, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
        ] = {}
        for row in self._attachment_rows(cursor, "a.fid", removed):
            after_sync, before_delete = attachments.setdefault(
                row[0], ([], [])
            )
            if row[11] is not None:
                after_sync.append(json.loads(row[11])["after_sync"])
            else:
                backup = self._attachment_backup(row)
                after_sync.append(
                    json.loads(row[10]) if row[10] is not None else backup
                )
                before_delete.append(backup)
        for fid in sorted(removed):
            feature = changes.deleted_features[fid]
            before_fields = [
                [
                    field.ngw_id,
                    simplify_value(feature.attribute(field.attribute)),
                ]
                for field in self.metadata.fields
            ]
            after_fields = [
                [field.ngw_id, fields.get((fid, field.attribute), value[1])]
                for field, value in zip(self.metadata.fields, before_fields)
            ]
            before_geom = serialize_geometry(
                feature.geometry(), self.metadata.is_versioning_enabled
            )
            after_description = {}
            before_description = {}
            if fid in descriptions:
                value, version, backup = descriptions[fid]
                before_description = {"value": value, "version": version}
                after_description = (
                    json.loads(backup) if backup else before_description
                )
            after_attachments, before_attachments = attachments.get(
                fid, ([], [])
            )
            backup = {
                "after_sync": {
                    "fields": after_fields,
                    "geom": geometries.get(fid, before_geom),
                    "description": after_description,
                    "attachments": sorted(
                        after_attachments, key=lambda item: item["aid"]
                    ),
                },
                "before_deletion": {
                    "fields": before_fields,
                    "geom": before_geom,
                    "description": before_description,
                    "attachments": sorted(
                        before_attachments, key=lambda item: item["aid"]
                    ),
                },
            }
            cursor.execute(
                "INSERT INTO ngw_removed_features (fid, backup) VALUES (?, ?)",
                (fid, json.dumps(backup)),
            )
        for table in (
            "ngw_updated_attributes",
            "ngw_updated_geometries",
            "ngw_features_attachments",
            "ngw_features_descriptions",
        ):
            cursor.executemany(
                f"DELETE FROM {table} WHERE fid = ?",
                ((fid,) for fid in removed),
            )

    def _write_descriptions(
        self,
        cursor: sqlite3.Cursor,
        extensions: ExtensionChanges,
        removed: Set[int],
    ) -> None:
        descriptions = {
            fid: value
            for fid, value in extensions.descriptions.items()
            if fid not in removed
        }
        backups = {
            fid: serialize_value({"value": value, "version": version})
            for fid, value, version in self._rows(
                cursor,
                "ngw_features_descriptions",
                "fid",
                descriptions,
                "fid, description, version",
            )
        }
        cursor.executemany(
            "INSERT INTO ngw_features_descriptions (fid, description) "
            "VALUES (?, ?) ON CONFLICT(fid) DO UPDATE "
            "SET description = excluded.description",
            descriptions.items(),
        )
        cursor.executemany(
            "INSERT INTO ngw_updated_descriptions (fid, backup) "
            "VALUES (?, ?) ON CONFLICT DO NOTHING",
            ((fid, backups.get(fid)) for fid in descriptions),
        )

    def _write_attachments(
        self,
        cursor: sqlite3.Cursor,
        extensions: ExtensionChanges,
        removed: Set[int],
    ) -> None:
        for fid, attachments in extensions.added_attachments.items():
            if fid in removed:
                continue
            for attachment in attachments.values():
                cursor.execute(
                    "INSERT INTO ngw_features_attachments "
                    "(fid, name, description, mime_type) VALUES (?, ?, ?, ?)",
                    (
                        fid,
                        attachment.name,
                        attachment.description,
                        attachment.mime_type,
                    ),
                )
                aid = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO ngw_added_attachments (aid) VALUES (?)",
                    (aid,),
                )
                self.files.prepare(replace(attachment, aid=aid))
        removed_aids = {
            aid
            for fid, aids in extensions.removed_attachments.items()
            if fid not in removed
            for aid in aids
        }
        for row in self._attachment_rows(cursor, "a.aid", removed_aids):
            before_delete = self._attachment_backup(row)
            after_sync = (
                json.loads(row[10]) if row[10] is not None else before_delete
            )
            cursor.execute(
                "INSERT INTO ngw_removed_attachments (aid, backup) "
                "VALUES (?, ?) ON CONFLICT DO NOTHING",
                (
                    row[2],
                    json.dumps(
                        {
                            "after_sync": after_sync,
                            "before_deletion": before_delete,
                        }
                    ),
                ),
            )
            cursor.execute(
                "DELETE FROM ngw_updated_attachments WHERE aid = ?", (row[2],)
            )
        updated = {
            aid: attachment
            for fid, attachments in extensions.updated_attachments.items()
            if fid not in removed
            for aid, attachment in attachments.items()
            if aid not in removed_aids
        }
        for row in self._attachment_rows(cursor, "a.aid", updated):
            attachment = updated[row[2]]
            cursor.execute(
                "UPDATE ngw_features_attachments "
                "SET name = ?, description = ? WHERE aid = ?",
                (attachment.name, attachment.description, attachment.aid),
            )
            cursor.execute(
                "INSERT INTO ngw_updated_attachments (aid, backup) "
                "VALUES (?, ?) ON CONFLICT DO NOTHING",
                (attachment.aid, json.dumps(self._attachment_backup(row))),
            )
