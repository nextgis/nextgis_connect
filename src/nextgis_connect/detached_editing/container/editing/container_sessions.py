"""Container session helpers for detached container sqlite access.

This module provides context-manager classes that open an sqlite3
connection and cursor for a detached container (GeoPackage) and ensure
resources are properly closed. Use :class:`ContainerReadOnlySession`
when no changes should be committed, and :class:`ContainerReadWriteSession`
when the session should commit on successful exit.
"""

import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Optional, Type, Union

from qgis.core import QgsMapLayer

from nextgis_connect.detached_editing.utils import (
    DetachedContainerContext,
    container_path,
)
from nextgis_connect.exceptions import (
    ContainerError,
    DetachedEditingError,
    NgConnectExceptionInfoMixin,
)


class ContainerSession:
    """Manage a sqlite3 cursor session for a detached container.

    Open an sqlite3 connection and cursor for the provided container
    (a ``Path``, ``QgsMapLayer`` or ``DetachedContainerContext``) and ensure
    resources are closed on exit. Subclasses may override commit
    behavior by implementing ``_commit``.

    :ivar _container: Path-like object, QgsMapLayer or DetachedContainerContext.
    :ivar _connection: Active sqlite3.Connection or None.
    :ivar _cursor: Active sqlite3.Cursor or None.
    """

    def __init__(
        self, container: Union[QgsMapLayer, Path, DetachedContainerContext]
    ) -> None:
        """Initialize the session with a container reference.

        :param container: Path, QgsMapLayer or DetachedContainerContext.
        """

        self._container = container
        self._connection: Optional[sqlite3.Connection] = None
        self._cursor: Optional[sqlite3.Cursor] = None

    def __enter__(self) -> sqlite3.Cursor:
        """Enter the context and return an sqlite3 cursor.

        The container reference is resolved to a filesystem path and an
        sqlite3 connection is opened with foreign keys enabled.

        :return: sqlite3 cursor bound to the opened connection.
        """

        container = self._container
        if isinstance(container, DetachedContainerContext):
            container = container.path

        container = container_path(container)
        self._connection = sqlite3.connect(str(container))
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._cursor = self._connection.cursor()
        return self._cursor

    def __exit__(
        self,
        error_type: Optional[Type[BaseException]],
        error: Optional[BaseException],
        error_traceback: Optional[TracebackType],
    ) -> bool:
        """Exit the context, commit if no exception and close resources.

        :param error_type: Exception type if raised, otherwise None.
        :param error: Exception instance if raised, otherwise None.
        :param error_traceback: Traceback object if exception raised, otherwise None.
        :return: Always return False to propagate exceptions.
        """

        try:
            if error_type is not None:
                if not isinstance(error, NgConnectExceptionInfoMixin):
                    raise ContainerError("Container session error") from error
                raise

            try:
                self._commit()
            except Exception as commit_error:
                if isinstance(commit_error, NgConnectExceptionInfoMixin):
                    raise DetachedEditingError(
                        "Failed to commit container session"
                    ) from commit_error
                raise

        finally:
            self._close()

        return False

    def _commit(self) -> None:
        """Hook for subclasses to perform commit actions on successful exit.

        The base implementation does nothing.
        """

        return None

    def _close(self) -> None:
        """Close cursor and connection if they are open."""

        cursor = self._cursor
        if cursor is not None:
            cursor.close()

        connection = self._connection
        if connection is not None:
            connection.close()

        self._cursor = None
        self._connection = None


class ContainerReadOnlySession(ContainerSession):
    """Read-only session that does not commit on exit.

    Use this context manager when no modifications should be persisted.
    """


class ContainerReadWriteSession(ContainerSession):
    """Read-write session that commits changes on successful exit.

    The session will call ``connection.commit()`` if no exception was
    raised inside the context.
    """

    def _commit(self) -> None:
        """Commit the active sqlite3 connection if present."""

        connection = self._connection
        if connection is None:
            return

        connection.commit()
