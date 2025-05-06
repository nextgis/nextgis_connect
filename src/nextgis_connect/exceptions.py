import sys
import uuid
from enum import IntEnum, auto
from functools import lru_cache
from http import HTTPStatus
from typing import Any, Callable, Dict, Optional

from qgis.core import QgsApplication, QgsEditError

from nextgis_connect.utils import locale, nextgis_domain


class ErrorCode(IntEnum):
    NoError = -1

    PluginError = 0
    BigUpdateError = 1

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


class NgConnectException(Exception):
    __error_id: str
    __log_message: str
    __user_message: str
    __detail: Optional[str]
    __code: ErrorCode
    __try_again: Optional[Callable[[], Any]]

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.__error_id = str(uuid.uuid4())
        self.__code = code
        self.__log_message = (
            log_message
            if log_message is not None
            else _default_log_message(self.code)
        ).strip()

        super().__init__(f"<b>{self.__log_message}</b>")

        if self.code != ErrorCode.PluginError:
            self.add_note(f"Internal code: {self.code.name}")

        self.__user_message = (
            user_message
            if user_message is not None
            else default_user_message(self.code)
        )
        if self.__user_message is not None:
            self.__user_message = self.__user_message.strip()
            self.add_note("User message: " + self.__user_message)

        self.__detail = (
            detail if detail is not None else default_detail(self.code)
        )
        if self.__detail is not None:
            self.__detail = self.__detail.strip()
            self.add_note("Detail: " + self.__detail)

        self.__try_again = try_again

    @property
    def error_id(self) -> str:
        return self.__error_id

    @property
    def log_message(self) -> str:
        return self.__log_message

    @property
    def user_message(self) -> str:
        return self.__user_message

    @property
    def detail(self) -> Optional[str]:
        return self.__detail

    @property
    def code(self) -> ErrorCode:
        return self.__code

    @property
    def try_again(self) -> Optional[Callable[[], Any]]:
        return self.__try_again

    @try_again.setter
    def try_again(self, try_again: Optional[Callable[[], Any]]) -> None:
        self.__try_again = try_again

    if sys.version_info < (3, 11):

        def add_note(self, note: str) -> None:
            if not isinstance(note, str):
                message = "Note must be a string"
                raise TypeError(message)

            message: str = self.args[0]
            self.args = (f"{message}\n{note}",)


class NgConnectError(NgConnectException):
    pass


class NgConnectWarning(NgConnectException):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginWarning,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class NgwError(NgConnectError):
    _try_reconnect: bool

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        try_reconnect: bool = False,
        code: ErrorCode = ErrorCode.NgwError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )

        self._try_reconnect = try_reconnect

    @property
    def try_reconnect(self) -> bool:
        return self._try_reconnect

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
        ngw_exception_name = json.get("exception")
        if (
            detail is None
            and ngw_exception_name is not None
            and ngw_exception_name.endswith(
                ("ResourceDisabled", "ValidationError")
            )
        ):
            detail = json.get("message")

        error = NgwError(
            log_message=json.get("message"),
            user_message=user_message,
            detail=detail,
            try_reconnect=try_reconnect,
            code=code,
        )

        error.add_note(f"Http status code: {status_code}")

        if ngw_exception_name is not None:
            error.add_note(f"NGW exception: {json.get('exception')}")
        if "guru_meditation" in json:
            error.add_note(f"Guru meditation: {json.get('guru_meditation')}")

        return error


class NgwConnectionError(NgConnectError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.NgwConnectionError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class DetachedEditingError(NgConnectError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.DetachedEditingError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class ContainerError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.ContainerError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class LayerEditError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.LayerEditError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
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
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


class SerializationError(DetachedEditingError):
    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.SerializationError,
        try_again: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            log_message,
            user_message=user_message,
            detail=detail,
            code=code,
            try_again=try_again,
        )


@lru_cache(maxsize=128)
def _default_log_message(code: ErrorCode) -> str:
    messages = {
        ErrorCode.PluginError: "Internal plugin error",
        ErrorCode.BigUpdateError: "Big update error",
        ErrorCode.NgStdError: "NgStd library error",
        ErrorCode.NgwError: "NGW communication error",
        ErrorCode.NgwConnectionError: "Connection error",
        ErrorCode.AuthorizationError: "Authorization error",
        ErrorCode.PermissionsError: "Permissions error",
        ErrorCode.NotFound: "Not found url error",
        ErrorCode.QuotaExceeded: "You have reached the limit of layers allowed",
        ErrorCode.InvalidConnection: "Invalid connection",
        ErrorCode.ServerError: "Server error",
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
        ErrorCode.BigUpdateError: QgsApplication.translate(
            "Errors",
            "The plugin has been updated successfully. "
            "To continue working, please restart QGIS."
        ),
        ErrorCode.UnsupportedRasterType: QgsApplication.translate(
            "Errors", "Resource can't be added to the map."
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
