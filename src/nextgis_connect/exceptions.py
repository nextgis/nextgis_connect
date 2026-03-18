import sys
import uuid
from enum import IntEnum, auto
from functools import lru_cache
from http import HTTPStatus
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from qgis.core import QgsApplication, QgsEditError
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from nextgis_connect.utils import locale, nextgis_domain


class ErrorCode(IntEnum):
    NoError = -1

    PluginError = 0
    BigUpdateWarning = 1

    NgStdError = 50

    NgwError = 100

    NgwConnectionError = 400
    AuthorizationError = 401
    PermissionsError = 403
    NotFound = 404
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
        return self.PluginError <= self < self.NgStdError

    @property
    def is_connection_error(self) -> bool:
        return self.NgwConnectionError <= self < self.ServerError

    @property
    def is_server_error(self) -> bool:
        return self.ServerError <= self < self.DetachedEditingError

    @property
    def is_container_error(self) -> bool:
        return self.DetachedEditingError <= self < self.SynchronizationError

    @property
    def is_synchronization_error(self) -> bool:
        return self.SynchronizationError <= self

    @property
    def group(self) -> "ErrorCode":
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
    """Mixin providing common fields and logic for NextGIS Connect errors and warnings."""

    _error_id: str
    _code: ErrorCode
    _log_message: str
    _user_message: str
    _detail: Optional[str]
    _try_again: Optional[Callable[[], Any]]
    _actions: List[Tuple[str, Callable[[], Any]]]
    _need_logs: bool

    def __init__(
        self,
        base_class: Type[Exception] = Exception,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
    ) -> None:
        self._error_id = str(uuid.uuid4())
        self._code = code

        self._log_message = (
            log_message
            if log_message is not None
            else _default_log_message(self.code)
        ).strip()

        base_class.__init__(self, f"<b>{self._log_message}</b>")  # pyright: ignore[reportArgumentType]

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

        self._try_again = None

        self._actions = []
        self._need_logs = True

    @property
    def error_id(self) -> str:
        """
        Get the unique error identifier.

        :returns: Unique error ID as a string.
        :rtype: str
        """
        return self._error_id

    @property
    def code(self) -> ErrorCode:
        """
        Get the error code.

        :returns: Error code as an instance of ErrorCode.
        """
        return self._code

    @property
    def log_message(self) -> str:
        """
        Get the log message for debugging.

        :returns: Log message.
        :rtype: str
        """
        return self._log_message

    @property
    def user_message(self) -> str:
        """
        Get the message intended for the user.

        :returns: User message.
        :rtype: str
        """
        return self._user_message

    @property
    def detail(self) -> Optional[str]:
        """
        Get additional details about the error.

        :returns: Error details or None.
        :rtype: Optional[str]
        """
        return self._detail

    @property
    def try_again(self) -> Optional[Callable[[], Any]]:
        """
        Get the callable to retry the failed operation.

        :returns: Callable or None.
        :rtype: Optional[Callable[[], Any]]
        """
        return self._try_again

    @try_again.setter
    def try_again(self, try_again: Optional[Callable[[], Any]]) -> None:
        """
        Set the callable to retry the failed operation.

        :param try_again: Callable to retry or None.
        :type try_again: Optional[Callable[[], Any]]
        """
        self._try_again = try_again

    @property
    def actions(self) -> List[Tuple[str, Callable[[], Any]]]:
        """
        Get the list of available actions for this exception.

        :returns: List of (action_name, action_callable) tuples.
        :rtype: List[Tuple[str, Callable[[], Any]]]
        """
        return self._actions

    def add_action(self, name: str, callback: Callable[[], Any]) -> None:
        """
        Add an action to the exception.

        :param name: Name of the action.
        :type name: str
        :param callback: Callable to execute for the action.
        :type callback: Callable[[], Any]
        """
        self._actions.append((name, callback))

    @property
    def need_logs(self) -> bool:
        """
        Indicate whether logs are needed for this exception.

        :returns: True if logs are needed, False otherwise.
        :rtype: bool
        """
        return self._need_logs

    if sys.version_info < (3, 11):

        def add_note(self, note: str) -> None:
            """
            Add a note to the exception message (for Python < 3.11).

            :param note: Note string to add.
            :type note: str
            :raises TypeError: If note is not a string.
            """
            if not isinstance(note, str):
                message = "Note must be a string"
                raise TypeError(message)

            message: str = self.args[0]
            self.args = (f"{message}\n{note}",)


class NgConnectError(NgConnectExceptionInfoMixin, Exception):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
    ) -> None:
        super().__init__(
            base_class=Exception,
            log_message=log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class NgConnectWarning(NgConnectExceptionInfoMixin, UserWarning):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginWarning,
    ) -> None:
        super().__init__(
            base_class=UserWarning,
            log_message=log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class NgConnectReloadAfterUpdateWarning(NgConnectWarning):
    """
    Warning raised when the plugin structure has changed after an update.

    This warning indicates that the plugin was successfully updated, but due to changes
    in its structure, it may fail to load properly until QGIS is restarted.
    """

    def __init__(
        self,
        log_message: Optional[str] = None,
    ) -> None:
        """Initialize the warning."""
        super().__init__(
            log_message=log_message, code=ErrorCode.BigUpdateWarning
        )


class NgwError(NgConnectError):
    _try_reconnect: bool
    _ngw_exception_class: Optional[str]

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        try_reconnect: bool = False,
        ngw_exception_class: Optional[str] = None,
        code: ErrorCode = ErrorCode.NgwError,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )

        self._try_reconnect = try_reconnect
        self._ngw_exception_class = ngw_exception_class

        if ngw_exception_class is not None:
            self.add_note(f"NGW exception: {ngw_exception_class}")

    @property
    def try_reconnect(self) -> bool:
        return self._try_reconnect

    @property
    def ngw_exception_class(self) -> Optional[str]:
        return self._ngw_exception_class

    @staticmethod
    def from_json(json: Dict[str, Any]) -> "NgwError":
        status_code = json["status_code"]

        if status_code == HTTPStatus.UNAUTHORIZED:
            code = ErrorCode.AuthorizationError
        elif status_code == HTTPStatus.FORBIDDEN:
            code = ErrorCode.PermissionsError
        elif status_code == HTTPStatus.NOT_FOUND:
            code = ErrorCode.NotFound
        elif status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            code = ErrorCode.ServerError
        else:
            code = ErrorCode.NgwError

        server_error_prefix = 5
        try_reconnect = status_code // 100 == server_error_prefix

        user_message = json.get("title")
        if user_message is not None:
            user_message += "."

        detail = json.get("detail")
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
            code=code,
        )

        error.add_note(f"Http status code: {status_code}")
        if "guru_meditation" in json:
            error.add_note(f"Guru meditation: {json.get('guru_meditation')}")

        return error


class ResourcePermissionError(NgwError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        resource_url: Optional[str] = None,
    ) -> None:
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
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.NgwConnectionError,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class DetachedEditingError(NgConnectError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.DetachedEditingError,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class ContainerError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.ContainerError,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class LayerEditError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.LayerEditError,
    ) -> None:
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
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.SynchronizationError,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
        )


class SerializationError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.SerializationError,
    ) -> None:
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
        ErrorCode.BigUpdateWarning: "Big update error",
        ErrorCode.NgStdError: "NgStd library error",
        ErrorCode.NgwError: "NGW communication error",
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
        ErrorCode.NgwError: QgsApplication.translate(
            "Errors", "Error occurred while communicating with Web GIS."
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
