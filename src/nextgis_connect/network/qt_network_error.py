from dataclasses import dataclass
from enum import Enum
from typing import Optional

from nextgis_connect.exceptions import NgConnectException


@dataclass
class QtNetworkErrorInfo:
    code: int
    constant: str
    description: str

    def add_exception_notes(self, error: NgConnectException) -> None:
        error.add_note(f"Network error: {self.constant}")
        error.add_note(f"Error description: {self.description}")


class QtNetworkError(Enum):
    NO_ERROR = QtNetworkErrorInfo(
        0,
        "NoError",
        "no error condition",
    )
    CONNECTION_REFUSED_ERROR = QtNetworkErrorInfo(
        1,
        "ConnectionRefusedError",
        "the remote server refused the connection (the server is not accepting requests)",
    )
    REMOTE_HOST_CLOSED_ERROR = QtNetworkErrorInfo(
        2,
        "RemoteHostClosedError",
        "the remote server closed the connection prematurely, before the entire reply was received and processed",
    )
    HOST_NOT_FOUND_ERROR = QtNetworkErrorInfo(
        3,
        "HostNotFoundError",
        "the remote host name was not found (invalid hostname)",
    )
    TIMEOUT_ERROR = QtNetworkErrorInfo(
        4,
        "TimeoutError",
        "the connection to the remote server timed out",
    )
    OPERATION_CANCELED_ERROR = QtNetworkErrorInfo(
        5,
        "OperationCanceledError",
        "the operation was canceled via calls to abort() or close() before it was finished.",
    )
    SSL_HANDSHAKE_FAILED_ERROR = QtNetworkErrorInfo(
        6,
        "SslHandshakeFailedError",
        "the SSL/TLS handshake failed and the encrypted channel could not be established. The sslErrors() signal should have been emitted.",
    )
    TEMPORARY_NETWORK_FAILURE_ERROR = QtNetworkErrorInfo(
        7,
        "TemporaryNetworkFailureError",
        "the connection was broken due to disconnection from the network, however the system has initiated roaming to another access point.",
    )
    NETWORK_SESSION_FAILED_ERROR = QtNetworkErrorInfo(
        8,
        "NetworkSessionFailedError",
        "the connection was broken due to disconnection from the network or failure to start the network.",
    )
    BACKGROUND_REQUEST_NOT_ALLOWED_ERROR = QtNetworkErrorInfo(
        9,
        "BackgroundRequestNotAllowedError",
        "the background request is not currently allowed due to platform policy.",
    )
    TOO_MANY_REDIRECTS_ERROR = QtNetworkErrorInfo(
        10,
        "TooManyRedirectsError",
        "while following redirects, the maximum limit was reached.",
    )
    INSECURE_REDIRECT_ERROR = QtNetworkErrorInfo(
        11,
        "InsecureRedirectError",
        "while following redirects, the network detected a redirect from HTTPS to HTTP.",
    )
    PROXY_CONNECTION_REFUSED_ERROR = QtNetworkErrorInfo(
        101,
        "ProxyConnectionRefusedError",
        "the connection to the proxy server was refused.",
    )
    PROXY_CONNECTION_CLOSED_ERROR = QtNetworkErrorInfo(
        102,
        "ProxyConnectionClosedError",
        "the proxy server closed the connection prematurely.",
    )
    PROXY_NOT_FOUND_ERROR = QtNetworkErrorInfo(
        103,
        "ProxyNotFoundError",
        "the proxy host name was not found.",
    )
    PROXY_TIMEOUT_ERROR = QtNetworkErrorInfo(
        104,
        "ProxyTimeoutError",
        "the connection to the proxy timed out.",
    )
    PROXY_AUTHENTICATION_REQUIRED_ERROR = QtNetworkErrorInfo(
        105,
        "ProxyAuthenticationRequiredError",
        "the proxy requires authentication but the provided credentials were not accepted.",
    )
    CONTENT_ACCESS_DENIED = QtNetworkErrorInfo(
        201,
        "ContentAccessDenied",
        "the access to the remote content was denied (HTTP error 403).",
    )
    CONTENT_OPERATION_NOT_PERMITTED_ERROR = QtNetworkErrorInfo(
        202,
        "ContentOperationNotPermittedError",
        "the operation requested on the remote content is not permitted.",
    )
    CONTENT_NOT_FOUND_ERROR = QtNetworkErrorInfo(
        203,
        "ContentNotFoundError",
        "the remote content was not found (HTTP error 404).",
    )
    AUTHENTICATION_REQUIRED_ERROR = QtNetworkErrorInfo(
        204,
        "AuthenticationRequiredError",
        "the server requires authentication but did not accept any credentials.",
    )
    CONTENT_RESEND_ERROR = QtNetworkErrorInfo(
        205,
        "ContentReSendError",
        "the request needed to be sent again but failed.",
    )
    CONTENT_CONFLICT_ERROR = QtNetworkErrorInfo(
        206,
        "ContentConflictError",
        "the request could not be completed due to a conflict with the resource state.",
    )
    CONTENT_GONE_ERROR = QtNetworkErrorInfo(
        207,
        "ContentGoneError",
        "the requested resource is no longer available.",
    )
    INTERNAL_SERVER_ERROR = QtNetworkErrorInfo(
        401,
        "InternalServerError",
        "the server encountered an unexpected condition.",
    )
    OPERATION_NOT_IMPLEMENTED_ERROR = QtNetworkErrorInfo(
        402,
        "OperationNotImplementedError",
        "the server does not support the requested functionality.",
    )
    SERVICE_UNAVAILABLE_ERROR = QtNetworkErrorInfo(
        403,
        "ServiceUnavailableError",
        "the server is unable to handle the request at this time.",
    )
    PROTOCOL_UNKNOWN_ERROR = QtNetworkErrorInfo(
        301,
        "ProtocolUnknownError",
        "the protocol is not known.",
    )
    PROTOCOL_INVALID_OPERATION_ERROR = QtNetworkErrorInfo(
        302,
        "ProtocolInvalidOperationError",
        "the requested operation is invalid for this protocol.",
    )
    UNKNOWN_NETWORK_ERROR = QtNetworkErrorInfo(
        99,
        "UnknownNetworkError",
        "an unknown network-related error was detected.",
    )
    UNKNOWN_PROXY_ERROR = QtNetworkErrorInfo(
        199,
        "UnknownProxyError",
        "an unknown proxy-related error was detected.",
    )
    UNKNOWN_CONTENT_ERROR = QtNetworkErrorInfo(
        299,
        "UnknownContentError",
        "an unknown error related to the remote content was detected.",
    )
    PROTOCOL_FAILURE = QtNetworkErrorInfo(
        399,
        "ProtocolFailure",
        "a breakdown in protocol was detected (parsing error, invalid or unexpected responses, etc.).",
    )
    UNKNOWN_SERVER_ERROR = QtNetworkErrorInfo(
        499,
        "UnknownServerError",
        "an unknown error related to the server response was detected.",
    )

    @classmethod
    def from_int(cls, value: int) -> Optional["QtNetworkError"]:
        for error in cls:
            if error.value.code == value:
                return error
        return None
