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
from pathlib import Path

import pytest

from nextgis_connect.legacy.detached_editing.container.editing.container_sessions import (
    ContainerReadOnlySession,
    ContainerReadWriteSession,
)
from nextgis_connect.legacy.detached_editing.container.migrations import (
    ContainerMigration,
    ContainerMigrator,
)
from nextgis_connect.platform.qgis.errors import ContainerError


@pytest.fixture
def container_path(tmp_path):
    path = tmp_path / "container.gpkg"
    with ContainerReadWriteSession(path) as cursor:
        cursor.execute("CREATE TABLE ngw_metadata (container_version TEXT)")
        cursor.execute("INSERT INTO ngw_metadata VALUES ('3.0.0')")
        cursor.execute("CREATE TABLE local_edits (value TEXT)")
        cursor.execute("INSERT INTO local_edits VALUES ('pending change')")
    return path


def _add_next_schema(cursor: sqlite3.Cursor) -> None:
    assert cursor.execute(
        "SELECT container_version FROM ngw_metadata"
    ).fetchone() == ("3.1.0",)
    cursor.execute("CREATE TABLE next_schema (value TEXT)")


@pytest.mark.parametrize("starting_version", ["3.0.0", "3.1.0"])
def test_applies_remaining_chain_once(
    container_path: Path, starting_version: str
) -> None:
    if starting_version == "3.1.0":
        ContainerMigrator().migrate(container_path)
    migrator = ContainerMigrator(
        (ContainerMigration("3.1.0", "3.2.0", _add_next_schema),),
    )

    migrator.migrate(container_path)
    migrator.migrate(container_path)

    with ContainerReadOnlySession(container_path) as cursor:
        assert cursor.execute(
            "SELECT container_version, transaction_changes FROM ngw_metadata"
        ).fetchone() == ("3.2.0", None)
        assert cursor.execute("SELECT * FROM next_schema").fetchall() == []
        assert cursor.execute("SELECT * FROM local_edits").fetchall() == [
            ("pending change",)
        ]


def test_later_failure_rolls_back_entire_chain(container_path):
    def fail(cursor):
        _add_next_schema(cursor)
        raise sqlite3.OperationalError("Second migration failed")

    migrator = ContainerMigrator(
        (ContainerMigration("3.1.0", "3.2.0", fail),),
    )

    with pytest.raises(ContainerError) as raised:
        migrator.migrate(container_path)
    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)

    with ContainerReadOnlySession(container_path) as cursor:
        assert cursor.execute("SELECT * FROM ngw_metadata").fetchone() == (
            "3.0.0",
        )
        assert (
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE name='next_schema'"
            ).fetchone()
            is None
        )
        assert cursor.execute("SELECT * FROM local_edits").fetchall() == [
            ("pending change",)
        ]


@pytest.mark.parametrize("version", ["0.1.0", "3.1.0", "9.0.0"])
def test_versions_without_upgrade_path_are_untouched(container_path, version):
    with ContainerReadWriteSession(container_path) as cursor:
        cursor.execute(
            "UPDATE ngw_metadata SET container_version=?", (version,)
        )

    ContainerMigrator().migrate(container_path)

    with ContainerReadOnlySession(container_path) as cursor:
        assert cursor.execute("SELECT * FROM ngw_metadata").fetchone() == (
            version,
        )


def test_incomplete_chain_is_rejected_before_changes(container_path):
    migrator = ContainerMigrator(
        (ContainerMigration("3.2.0", "3.3.0", _add_next_schema),),
    )
    with pytest.raises(ContainerError, match="migration chain is incomplete"):
        migrator.migrate(container_path)

    with ContainerReadOnlySession(container_path) as cursor:
        assert cursor.execute("SELECT * FROM ngw_metadata").fetchone() == (
            "3.0.0",
        )
