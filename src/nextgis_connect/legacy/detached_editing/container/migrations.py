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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, Tuple

from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.platform.qgis.errors import ContainerError


@dataclass(frozen=True)
class ContainerMigration:
    source_version: str
    target_version: str
    apply: Callable[[sqlite3.Cursor], None]


class ContainerMigrator:
    def __init__(
        self, additional_migrations: Sequence[ContainerMigration] = ()
    ) -> None:
        self._migrations = (
            ContainerMigration(
                "3.0.0", "3.1.0", self._add_transaction_recovery
            ),
            *additional_migrations,
        )

    def migrate(self, path: Path) -> None:
        with ContainerReadWriteSession(path) as cursor:
            version = self._read_version(cursor)
            if not self._migration_plan(version):
                return

            # Re-read under the write lock: another session may have upgraded it.
            cursor.execute("BEGIN IMMEDIATE")
            version = self._read_version(cursor)
            for migration in self._migration_plan(version):
                # Steps must not commit or call executescript: the entire
                # upgrade, including version updates, is one transaction.
                migration.apply(cursor)
                cursor.execute(
                    "UPDATE ngw_metadata SET container_version=?",
                    (migration.target_version,),
                )

    def _migration_plan(self, version: str) -> Tuple[ContainerMigration, ...]:
        for index, migration in enumerate(self._migrations):
            if migration.source_version != version:
                continue
            plan = self._migrations[index:]
            for step in plan:
                if step.source_version != version:
                    raise ContainerError(
                        "Container migration chain is incomplete"
                    )
                version = step.target_version
            return plan
        return ()

    @staticmethod
    def _read_version(cursor: sqlite3.Cursor) -> str:
        return cursor.execute(
            "SELECT container_version FROM ngw_metadata"
        ).fetchone()[0]

    @staticmethod
    def _add_transaction_recovery(cursor: sqlite3.Cursor) -> None:
        columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(ngw_metadata)")
        }
        if "transaction_changes" not in columns:
            cursor.execute(
                "ALTER TABLE ngw_metadata ADD COLUMN transaction_changes TEXT"
            )
