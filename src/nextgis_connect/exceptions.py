import sys
from enum import IntEnum, auto
from functools import lru_cache
from http import HTTPStatus
from typing import Any, Dict, Optional

from qgis.core import QgsApplication


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
    InvalidResource = 498
    InvalidConnection = 499

    ServerError = 500
    IncorrectAnswer = 599

    DetachedEditingError = 1000

    ContainerError = 1100
    ContainerCreationError = auto()
    ContainerVersionIsOutdated = auto()
    DeletedContainer = auto()
    NotCompletedFetch = auto()

    SynchronizationError = 1200
    NotVersionedContentChanged = auto()
    DomainChanged = auto()
    StructureChanged = auto()
    EpochChanged = auto()
    VersioningEnabled = auto()
    VersioningDisabled = auto()

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


class NgConnectError(Exception):
    __log_message: str
    __user_message: str
    __detail: Optional[str]
    __code: ErrorCode

    def __init__(
        self,
        log_message: Optional[str] = None,
        *,
        user_message: Optional[str] = None,
        detail: Optional[str] = None,
        code: ErrorCode = ErrorCode.PluginError,
    ) -> None:
        self.__code = code
        self.__log_message = (
            log_message
            if log_message is not None
            else _default_log_message(self.code)
        ).strip()

        super().__init__(f"<b>{self.__log_message}</b>")

        self.__user_message = (
            user_message
            if user_message is not None
            else default_user_message(self.code)
        )
        if self.__user_message is not None:
            self.__user_message = self.__user_message.strip()

        self.__detail = (
            detail if detail is not None else default_detail(self.code)
        )
        if self.__detail is not None:
            self.__detail = self.__detail.strip()

        if self.code != ErrorCode.PluginError:
            self.add_note(f"Error code: {self.code.name}")

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

    if sys.version_info < (3, 11):

        def add_note(self, note: str) -> None:
            if not isinstance(note, str):
                message = "Note must be a string"
                raise TypeError(message)

            message: str = self.args[0]
            self.args = (f"{message}\n{note}",)


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
    ) -> None:
        super().__init__(
            log_message, user_message=user_message, detail=detail, code=code
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

        error.add_note(f"Status code: {status_code}")

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
    ) -> None:
        super().__init__(
            log_message, user_message=user_message, detail=detail, code=code
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
            log_message, user_message=user_message, detail=detail, code=code
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
            log_message, user_message=user_message, detail=detail, code=code
        )


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
            log_message, user_message=user_message, detail=detail, code=code
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
        ErrorCode.InvalidConnection: "Invalid connection",
        ErrorCode.ServerError: "Server error",
        ErrorCode.IncorrectAnswer: "Incorrect answer",
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
        ErrorCode.NgwError: QgsApplication.translate(
            "Errors", "Error occurred while communicating with Web GIS."
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
            "Errors", "An error occured while layer synchronization."
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
    # fmt: on

    detail = {
        ErrorCode.ContainerVersionIsOutdated: layer_reset_detail,
        ErrorCode.NotVersionedContentChanged: layer_reset_detail,
        ErrorCode.EpochChanged: layer_reset_detail,
        ErrorCode.StructureChanged: layer_reset_detail,
        ErrorCode.VersioningEnabled: layer_reset_detail,
        ErrorCode.VersioningDisabled: layer_reset_detail,
    }
    return detail.get(code)
