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

import sys
import uuid
from enum import IntEnum, auto
from functools import lru_cache
from http import HTTPStatus
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

from qgis.core import QgsApplication, QgsEditError
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from nextgis_connect.platform.qgis.utils import locale, nextgis_domain


class ErrorCode(IntEnum):
    """Represent plugin error categories and concrete error codes.

    Group low-level errors into ranges used by logging, user messages,
    diagnostics, and recovery actions.
    """

    NoError = -1

    PluginError = 0
    BigUpdateWarning = 1

    DataPreparationError = 10
    NgStdError = 50

    NgwError = 100

    NgwConnectionError = 400
    AuthorizationError = 401
    PermissionsError = 403
    NotFound = 404
    SslHandshakeError = auto()
    QgisTimeoutError = auto()

    AddingError = 480
    QuotaExceeded = auto()
    SpatialReferenceError = auto()
    UnsupportedRasterType = auto()
    InvalidResource = auto()
    InvalidConnection = auto()

    ServerError = 500
    ResourcePermissionsError = 598
    IncorrectAnswer = 599

    DetachedEditingError = 1000

    ContainerError = 1100
    ContainerCreationError = auto()
    ContainerIsInvalid = auto()
    ContainerFieldsMismatch = auto()
    ContainerVersionIsOutdated = auto()
    DeletedContainer = auto()
    NotCompletedFetch = auto()
    LayerEditError = auto()
    FeatureNotFound = auto()
    AttachmentNotFound = auto()

    NetworkError = auto()

    SynchronizationError = 1200
    NotVersionedContentChanged = auto()
    DomainChanged = auto()
    StructureChanged = auto()
    EpochChanged = auto()
    VersioningEnabled = auto()
    VersioningDisabled = auto()
    ValueFormatError = auto()
    ConflictsNotResolved = auto()
    SerializationError = auto()

    PluginWarning = 10000

    @property
    def is_plugin_error(self) -> bool:
        """Return whether the code belongs to plugin lifecycle errors.

        :return: ``True`` for plugin lifecycle errors.
        """
        return self.PluginError <= self < self.NgStdError

    @property
    def is_connection_error(self) -> bool:
        """Return whether the code belongs to connection errors.

        :return: ``True`` for connection errors.
        """
        return self.NgwConnectionError <= self < self.ServerError

    @property
    def is_server_error(self) -> bool:
        """Return whether the code belongs to server-side errors.

        :return: ``True`` for server-side errors.
        """
        return self.ServerError <= self < self.DetachedEditingError

    @property
    def is_container_error(self) -> bool:
        """Return whether the code belongs to detached container errors.

        :return: ``True`` for detached container errors.
        """
        return self.DetachedEditingError <= self < self.SynchronizationError

    @property
    def is_synchronization_error(self) -> bool:
        """Return whether the code belongs to synchronization errors.

        :return: ``True`` for synchronization errors.
        """
        return self.SynchronizationError <= self

    @property
    def group(self) -> "ErrorCode":
        """Return the broad error group for this code.

        :return: Group-level error code.
        """
        if self.is_connection_error:
            return self.NgwConnectionError

        if self.is_server_error:
            return self.ServerError

        if self.is_container_error:
            return self.ContainerError

        if self.is_synchronization_error:
            return self.SynchronizationError

        return self.PluginError


class NgConnectExceptionInfoMixin:
    """Provide common exception metadata.

    Store diagnostic identifiers, internal codes, user-facing messages,
    detail text, retry callbacks, and recovery actions.

    :ivar _error_id: Unique diagnostic identifier.
    :ivar _code: Internal error code.
    :ivar _log_message: Message intended for logs.
    :ivar _user_message: Message intended for users.
    :ivar _detail: Additional diagnostic detail.
    :ivar _try_again: Retry callback for the failed operation.
    :ivar _actions: Named recovery actions.
    :ivar _need_logs: Whether logs should be shown to the user.
    """

    _error_id: str
    _code: ErrorCode
    _log_message: str
    _user_message: str
    _detail: Optional[str]
    _try_again: Optional[Callable[[], Any]]
    _actions: List[Tuple[str, Callable[[], Any]]]
    _need_logs: bool
    _diagnostic_context_keys: Set[str]
    _user_context_keys: Set[str]

    def __init__(
        self,
        base_class: Type[Exception] = Exception,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize exception metadata.

        :param base_class: Exception base class to initialize.
        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        :param try_again: Retry callback for the failed operation.
        """
        self._error_id = str(uuid.uuid4())
        self._code = code

        self._log_message = (
            log_message
            if log_message is not None
            else _default_log_message(self.code)
        ).strip()

        base_class.__init__(self, self._log_message)  # pyright: ignore[reportArgumentType]

        if self.code != ErrorCode.PluginError:
            self.add_note(f"Internal code: {self.code.name}")

        self._user_message = (
            user_message
            if user_message is not None
            else default_user_message(self.code)
        )
        if self._user_message is not None:
            self._user_message = self._user_message.strip()
            self.add_note("User message: " + self._user_message)

        self._detail = (
            detail if detail is not None else default_detail(self.code)
        )
        if self._detail is not None:
            self._detail = self._detail.strip()
            self.add_note("Detail: " + self._detail)

        self._try_again = try_again

        self._actions = []
        self._need_logs = True
        self._diagnostic_context_keys = set()
        self._user_context_keys = set()

    @property
    def error_id(self) -> str:
        """Return the unique error identifier.

        :return: Unique error identifier.
        """
        return self._error_id

    @property
    def code(self) -> ErrorCode:
        """Return the error code.

        :return: Internal error code.
        """
        return self._code

    @property
    def log_message(self) -> str:
        """Return the log message.

        :return: Message intended for logs.
        """
        return self._log_message

    @property
    def user_message(self) -> str:
        """Return the user-facing message.

        :return: Message intended for users.
        """
        return self._user_message

    @property
    def detail(self) -> Optional[str]:
        """Return additional error detail.

        :return: Additional detail or ``None``.
        """
        return self._detail

    @property
    def try_again(self) -> Optional[Callable[[], Any]]:
        """Return the retry callback.

        :return: Retry callback or ``None``.
        """
        return self._try_again

    @try_again.setter
    def try_again(self, try_again: Optional[Callable[[], Any]]) -> None:
        """Set the retry callback.

        :param try_again: Retry callback or ``None``.
        """
        self._try_again = try_again

    @property
    def actions(self) -> List[Tuple[str, Callable[[], Any]]]:
        """Return available recovery actions.

        :return: Recovery actions as name and callback pairs.
        """
        return self._actions

    def add_action(self, name: str, callback: Callable[[], Any]) -> None:
        """Add a recovery action.

        :param name: Action display name.
        :param callback: Action callback.
        """
        self._actions.append((name, callback))

    def add_diagnostic_context(self, key: str, note: str) -> None:
        """Add a diagnostic note identified by a stable context key.

        :param key: Context key, e.g. ``request_url``.
        :param note: Note text to add.
        """
        if key in self._diagnostic_context_keys:
            return

        self._diagnostic_context_keys.add(key)
        self.add_note(note)

    def add_user_context(
        self, context: str, *, key: Optional[str] = None
    ) -> None:
        """Append context to the user-facing message.

        :param context: Additional user-facing context.
        :param key: Optional stable context key.
        """
        if key is not None and self.has_user_context(key):
            return

        context = context.strip()
        if len(context) == 0:
            return

        user_message = f"{self._user_message.rstrip('.')}. {context}"
        self.set_user_message(user_message)
        if key is not None:
            self.mark_user_context(key)

    def has_user_context(self, key: str) -> bool:
        """Return whether a user-facing context was already added."""
        return key in self._user_context_keys

    def mark_user_context(self, key: str) -> None:
        """Mark a user-facing context as already represented."""
        self._user_context_keys.add(key)

    def set_user_message(self, message: str) -> None:
        """Replace the user-facing message.

        :param message: New user-facing message.
        """
        message = message.strip()
        if len(message) == 0:
            return

        old_note = "User message: " + self._user_message
        new_note = "User message: " + message
        notes = getattr(self, "__notes__", None)
        if notes is not None and old_note in notes:
            notes[notes.index(old_note)] = new_note
        elif len(self.args) > 0 and isinstance(self.args[0], str):
            self.args = (self.args[0].replace(old_note, new_note),)

        self._user_message = message

    @property
    def is_network_problem(self) -> bool:
        """Return whether the error was caused by network transport."""
        return False

    @property
    def is_server_unavailable(self) -> bool:
        """Return whether the server is temporarily unavailable."""
        return False

    @property
    def need_logs(self) -> bool:
        """Return whether logs should be shown.

        :return: ``True`` when logs are useful for this exception.
        """
        return self._need_logs

    if sys.version_info < (3, 11):

        def add_note(self, note: str) -> None:
            """Add a note to the exception message.

            :param note: Note text to add.
            :raises TypeError: If the note is not text.
            """
            if not isinstance(note, str):
                message = "Note must be a string"
                raise TypeError(message)

            message: str = self.args[0]
            self.args = (f"{message}\n{note}",)


class NgConnectException(NgConnectExceptionInfoMixin, Exception):
    """Represent a base plugin exception.

    Carry common diagnostic metadata while behaving like a standard
    exception.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize the plugin exception.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        :param try_again: Retry callback for the failed operation.
        """
        super().__init__(
            base_class=Exception,
            log_message=log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class NgConnectError(NgConnectException):
    """Represent a plugin error.

    Use this as the common base for recoverable and user-visible plugin
    errors.
    """


class DataPreparationError(NgConnectError):
    """Represent data preparation failures.

    Use this error for failures that happen while preparing local data
    for upload or conversion.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.DataPreparationError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize the data preparation error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        :param try_again: Retry callback for the failed operation.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class NgConnectWarning(NgConnectExceptionInfoMixin, UserWarning):
    """Represent a plugin warning.

    Carry common diagnostic metadata while behaving like a standard
    warning.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginWarning,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize the plugin warning.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        :param try_again: Retry callback for the failed operation.
        """
        super().__init__(
            base_class=UserWarning,
            log_message=log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class NgConnectReloadAfterUpdateWarning(NgConnectWarning):
    """Represent a reload-after-update warning.

    Signal that the plugin was updated and QGIS should be restarted
    before normal work continues.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
    ) -> None:
        """Initialize the reload-after-update warning.

        :param log_message: Message intended for logs.
        """
        super().__init__(
            log_message=log_message, code=ErrorCode.BigUpdateWarning
        )


class NgwError(NgConnectError):
    """Represent a NextGIS Web communication error.

    Store server-side error details, optional reconnect hints, and the
    original NGW exception class name when it is available.

    :ivar _try_reconnect: Whether reconnecting can be attempted.
    :ivar _ngw_exception_class: Original NGW exception class name.
    """

    _try_reconnect: bool
    _ngw_exception_class: Optional[str]
    _status_code: Optional[int]
    _is_network_problem: bool
    _is_server_unavailable: bool

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        try_reconnect: bool = False,
        ngw_exception_class: Optional[str] = None,
        status_code: Optional[int] = None,
        is_network_problem: Optional[bool] = None,
        is_server_unavailable: Optional[bool] = None,
        code: ErrorCode = ErrorCode.NgwError,
    ) -> None:
        """Initialize the NGW communication error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param try_reconnect: Whether reconnecting can be attempted.
        :param ngw_exception_class: Original NGW exception class name.
        :param status_code: HTTP status code returned by server.
        :param is_network_problem: Whether transport failed before a response.
        :param is_server_unavailable: Whether server returned a temporary
            failure.
        :param code: Internal error code.
        """
        network_problem = (
            is_network_problem
            if is_network_problem is not None
            else code
            in (
                ErrorCode.NetworkError,
                ErrorCode.NgwConnectionError,
                ErrorCode.QgisTimeoutError,
                ErrorCode.SslHandshakeError,
            )
        )
        server_unavailable = (
            is_server_unavailable
            if is_server_unavailable is not None
            else (
                (status_code is not None and status_code // 100 == 5)
                or code == ErrorCode.ServerError
            )
        )

        if user_message is None and server_unavailable:
            user_message = default_user_message(ErrorCode.ServerError)
        elif user_message is None and network_problem:
            user_message = default_user_message(ErrorCode.NetworkError)

        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )

        self._try_reconnect = try_reconnect
        self._ngw_exception_class = ngw_exception_class
        self._status_code = status_code
        self._is_network_problem = network_problem
        self._is_server_unavailable = server_unavailable

        if ngw_exception_class is not None:
            self.add_note(f"NGW exception: {ngw_exception_class}")

        if self._is_server_unavailable:
            button_label = QgsApplication.translate("Errors", "Contact us")
            contact_url = QUrl(f"{nextgis_domain()}/contact/")
            self.add_action(
                button_label,
                lambda: QDesktopServices.openUrl(contact_url),
            )

    @property
    def try_reconnect(self) -> bool:
        """Return whether reconnecting can be attempted.

        :return: ``True`` when reconnecting can be attempted.
        """
        return self._try_reconnect

    @property
    def ngw_exception_class(self) -> Optional[str]:
        """Return the original NGW exception class name.

        :return: Original NGW exception class name or ``None``.
        """
        return self._ngw_exception_class

    @property
    def status_code(self) -> Optional[int]:
        """Return the HTTP status code returned by server."""
        return self._status_code

    @property
    def is_network_problem(self) -> bool:
        """Return whether the error was caused by network transport."""
        return self._is_network_problem

    @property
    def is_server_unavailable(self) -> bool:
        """Return whether the server is temporarily unavailable."""
        return self._is_server_unavailable

    @staticmethod
    def from_json(json: Dict[str, Any]) -> "NgwError":
        """Create an NGW error from a server error payload.

        :param json: Server error payload.
        :return: Parsed NGW error.
        """
        status_code = json["status_code"]

        if status_code == HTTPStatus.UNAUTHORIZED:
            code = ErrorCode.AuthorizationError
        elif status_code == HTTPStatus.FORBIDDEN:
            code = ErrorCode.PermissionsError
        elif status_code == HTTPStatus.NOT_FOUND:
            code = ErrorCode.NotFound
        else:
            code = ErrorCode.NgwError

        server_error_prefix = 5
        try_reconnect = status_code // 100 == server_error_prefix
        is_server_unavailable = status_code // 100 == server_error_prefix

        user_message = None
        if not is_server_unavailable:
            user_message = json.get("title")
            if user_message is not None:
                user_message += "."

        detail = json.get("detail")
        server_detail = None
        if is_server_unavailable:
            server_detail = detail
            detail = None

        ngw_exception_class = json.get("exception")
        if (
            detail is None
            and ngw_exception_class is not None
            and ngw_exception_class.endswith(
                ("ResourceDisabled", "ValidationError")
            )
        ):
            detail = json.get("message")

        error = NgwError(
            log_message=json.get("message"),
            user_message=user_message,
            detail=detail,
            try_reconnect=try_reconnect,
            ngw_exception_class=ngw_exception_class,
            status_code=status_code,
            is_server_unavailable=is_server_unavailable,
            code=code,
        )

        error.add_note(f"Http status code: {status_code}")
        if server_detail is not None:
            error.add_note(f"Server detail: {server_detail}")
        if "guru_meditation" in json:
            error.add_note(f"Guru meditation: {json.get('guru_meditation')}")

        return error


class ResourcePermissionError(NgwError):
    """Represent missing permissions for a resource.

    Add a resource-opening recovery action when the resource URL is
    available.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        resource_url: Optional[str] = None,
    ) -> None:
        """Initialize the resource permission error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param resource_url: Resource URL for the recovery action.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=ErrorCode.ResourcePermissionsError,
        )

        if resource_url is not None:
            resource_id = resource_url.rstrip("/").split("/")[-1]
            self.add_note(f"Resource ID: {resource_id}")
            button_label = QgsApplication.translate(
                "Errors", "Open resource in Web GIS"
            )
            self.add_action(
                button_label,
                lambda: QDesktopServices.openUrl(QUrl(resource_url)),
            )
            self._need_logs = False


class NgwConnectionError(NgConnectError):
    """Represent a NextGIS Web connection error.

    Use this error for failures that prevent connection verification or
    communication setup.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.NgwConnectionError,
    ) -> None:
        """Initialize the connection error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class DetachedEditingError(NgConnectError):
    """Represent a detached editing error.

    Use this error for failures in detached layer synchronization,
    local editing state, or related data handling.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.DetachedEditingError,
    ) -> None:
        """Initialize the detached editing error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class ContainerError(DetachedEditingError):
    """Represent a detached container error.

    Use this error for local container creation, validation, schema, or
    lifecycle failures.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.ContainerError,
    ) -> None:
        """Initialize the container error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class LayerEditError(DetachedEditingError):
    """Represent a QGIS layer edit error.

    Convert QGIS edit failures into plugin errors with separated layer
    and provider diagnostic notes.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.LayerEditError,
    ) -> None:
        """Initialize the layer edit error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )

    @staticmethod
    def from_qgis_error(
        error: QgsEditError,
        *,
        log_message: Optional[str] = None,
    ) -> "LayerEditError":
        """Create a layer edit error from a QGIS edit error.

        :param error: QGIS edit error to convert.
        :param log_message: Message intended for logs.
        :return: Plugin layer edit error.
        """
        ng_error = LayerEditError(
            log_message="Layer edit error"
            if log_message is None
            else log_message
        )
        ng_error.__cause__ = error

        layer_errors = []
        provider_errors = []
        layer_errors_added = False

        ERROR_PREFIX = "ОШИБКА:" if locale() == "ru" else "ERROR:"
        PROVIDER_ERROR_PREFIX = (
            "Ошибки провайдера" if locale() == "ru" else "Provider errors"
        )

        for error_message in error.args[0]:
            if PROVIDER_ERROR_PREFIX in error_message:
                layer_errors_added = True
                continue

            error_message: str = error_message.strip()

            if error_message.startswith(ERROR_PREFIX):
                error_message = error_message[len(ERROR_PREFIX) :].strip()

            if layer_errors_added:
                provider_errors.append(error_message)
            else:
                layer_errors.append(error_message)

        if len(layer_errors) > 0:
            ng_error.add_note("Layer errors: " + "\n  - ".join(layer_errors))

        if len(provider_errors) > 0:
            ng_error.add_note(
                "Provider errors: " + "\n  - ".join(provider_errors)
            )

        return ng_error


class SynchronizationError(DetachedEditingError):
    """Represent a detached layer synchronization error.

    Use this error for failures that prevent local and remote layer
    state from being synchronized.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.SynchronizationError,
    ) -> None:
        """Initialize the synchronization error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class SerializationError(DetachedEditingError):
    """Represent a detached editing serialization error.

    Use this error when feature, geometry, attachment, or sync payload
    serialization fails.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.SerializationError,
    ) -> None:
        """Initialize the serialization error.

        :param log_message: Message intended for logs.
        :param user_message: Message intended for users.
        :param detail: Additional diagnostic detail.
        :param code: Internal error code.
        """
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


@lru_cache(maxsize=128)
def _default_log_message(code: ErrorCode) -> str:
    messages = {
        ErrorCode.PluginError: "Internal plugin error",
        ErrorCode.DataPreparationError: "Data preparation error",
        ErrorCode.BigUpdateWarning: "Big update error",
        ErrorCode.NgStdError: "NgStd library error",
        ErrorCode.NgwError: "NGW communication error",
        ErrorCode.NetworkError: "Network error",
        ErrorCode.NgwConnectionError: "Connection error",
        ErrorCode.AuthorizationError: "Authorization error",
        ErrorCode.PermissionsError: "Permissions error",
        ErrorCode.NotFound: "Not found url error",
        ErrorCode.QuotaExceeded: "You have reached the limit of layers allowed",
        ErrorCode.InvalidConnection: "Invalid connection",
        ErrorCode.ServerError: "Server error",
        ErrorCode.ResourcePermissionsError: "Resource permissions error",
        ErrorCode.IncorrectAnswer: "Incorrect answer",
        ErrorCode.UnsupportedRasterType: "COG is disabled",
        ErrorCode.DetachedEditingError: "Detached editing error",
        ErrorCode.ContainerError: "Container error",
        ErrorCode.ContainerCreationError: "Container creation error",
        ErrorCode.ContainerVersionIsOutdated: "Container version is outdated",
        ErrorCode.DeletedContainer: "Container was deleted",
        ErrorCode.NotCompletedFetch: "Fetch was not completed",
        ErrorCode.SynchronizationError: "Synchronization error",
        ErrorCode.NotVersionedContentChanged: "Not versioned content changed on server",
        ErrorCode.DomainChanged: "Connection domain is wrong",
        ErrorCode.EpochChanged: "Layer epoch is different",
        ErrorCode.StructureChanged: "Layer structure is different",
        ErrorCode.VersioningEnabled: "Versioning state changed to enabled",
        ErrorCode.VersioningDisabled: "Versioning state changed to disabled",
    }

    code_message = messages.get(code)
    if code_message is not None:
        return code_message

    code_message = messages.get(code.group)
    if code_message is not None:
        return code_message

    return messages[ErrorCode.PluginError]


@lru_cache(maxsize=128)
def default_user_message(code: ErrorCode) -> str:
    """Return the default user-facing message for an error code.

    :param code: Error code to describe.
    :return: Localized user-facing message.
    """
    # fmt: off
    messages = {
        ErrorCode.PluginError: QgsApplication.translate(
            "Errors", "Internal plugin error occurred."
        ),
        ErrorCode.BigUpdateWarning: QgsApplication.translate(
            "Errors",
            "The plugin has been updated successfully. "
            "To continue working, please restart QGIS."
        ),
        ErrorCode.UnsupportedRasterType: QgsApplication.translate(
            "Errors", "COG is disabled."
        ),
        ErrorCode.DataPreparationError: QgsApplication.translate(
            "Errors", "An error occurred while preparing the data for upload."
        ),
        ErrorCode.NgwError: QgsApplication.translate(
            "Errors", "Error occurred while communicating with Web GIS."
        ),
        ErrorCode.NetworkError: QgsApplication.translate(
            "Errors",
            "A network error occurred. Check your internet connection and try again."
        ),
        ErrorCode.ServerError: QgsApplication.translate(
            "Errors",
            "The server is temporarily unavailable. Please try again later."
        ),
        ErrorCode.QuotaExceeded: QgsApplication.translate(
            "Errors", "You have reached the limit of layers allowed."
        ),
        ErrorCode.InvalidConnection: QgsApplication.translate(
            "Errors", "Invalid NextGIS Web connection."
        ),
        ErrorCode.PermissionsError: QgsApplication.translate(
            "Errors", "Invalid permissions."
        ),
        ErrorCode.ResourcePermissionsError: QgsApplication.translate(
            "Errors", "You do not have the necessary permissions to access this resource."
        ),
        ErrorCode.DetachedEditingError: QgsApplication.translate(
            "Errors", "Detached editing error occurred."
        ),
        ErrorCode.ContainerError: QgsApplication.translate(
            "Errors", "Detached container error occurred."
        ),
        ErrorCode.ContainerCreationError: QgsApplication.translate(
            "Errors",
            "An error occurred while creating the container for the layer."
        ),
        ErrorCode.ContainerVersionIsOutdated: QgsApplication.translate(
            "Errors", "The container version is out of date."
        ),
        ErrorCode.DeletedContainer: QgsApplication.translate(
            "Errors",
            "The container could not be found. It may have been deleted."
        ),
        ErrorCode.SynchronizationError: QgsApplication.translate(
            "Errors", "An error occurred during layer synchronization."
        ),
        ErrorCode.NotVersionedContentChanged: QgsApplication.translate(
            "Errors", "Layer features have been modified outside of QGIS."
        ),
        ErrorCode.DomainChanged: QgsApplication.translate(
            "Errors",
            "Invalid NextGIS Web address."
        ),
        ErrorCode.StructureChanged: QgsApplication.translate(
            "Errors",
            "The layer structure is different from the structure on the server."
        ),
        ErrorCode.EpochChanged: QgsApplication.translate(
            "Errors",
            "Versioning state has been changed on ther server multiple times."
        ),
        ErrorCode.VersioningEnabled: QgsApplication.translate(
            "Errors", "Versioning has been enabled on the server."
        ),
        ErrorCode.VersioningDisabled: QgsApplication.translate(
            "Errors", "Versioning has been disabled on the server."
        ),
        ErrorCode.ConflictsNotResolved: QgsApplication.translate(
            "Errors", "Conflicts were not resolved. Synchronization is not possible."
        ),
    }
    # fmt: on

    code_message = messages.get(code)
    if code_message is not None:
        return code_message

    if code.group in (ErrorCode.NgwConnectionError, ErrorCode.ServerError):
        return messages[ErrorCode.NgwError]

    code_message = messages.get(code.group)
    if code_message is not None:
        return code_message

    return messages[ErrorCode.PluginError]


@lru_cache(maxsize=128)
def default_detail(code: ErrorCode) -> Optional[str]:
    """Return the default detail text for an error code.

    :param code: Error code to describe.
    :return: Localized detail text or ``None``.
    """
    # fmt: off
    layer_reset_detail = QgsApplication.translate(
        "Errors",
        "Changes in the structure of the layer and some of its settings lead"
        " to the fact that further synchronization becomes impossible.\n\n"
        "To continue working with the layer, you need to reset the layer to"
        " its state in NextGIS Web. This can be done from the sync status"
        " window by clicking on the layer indicator.\n\n"
        "If a layer contains important changes that were not sent to the"
        " server, they will be lost. Create a backup if necessary."
    )
    unsupported_cog_detail = (
        """
        {}. <a href="{}/docs_ngcom/source/data_upload.html#ngcom-raster-layer"><span style=" text-decoration: underline; color:#0000ff;">{}</span></a>
        """
    ).format(
        QgsApplication.translate("Errors", "This type of raster is not supported anymore"),
        nextgis_domain("docs"),
        QgsApplication.translate("Errors", "Please add COG support"),
    )
    # fmt: on

    detail = {
        ErrorCode.ContainerVersionIsOutdated: layer_reset_detail,
        ErrorCode.NotVersionedContentChanged: layer_reset_detail,
        ErrorCode.EpochChanged: layer_reset_detail,
        ErrorCode.StructureChanged: layer_reset_detail,
        ErrorCode.VersioningEnabled: layer_reset_detail,
        ErrorCode.VersioningDisabled: layer_reset_detail,
        ErrorCode.UnsupportedRasterType: unsupported_cog_detail,
    }
    return detail.get(code)
