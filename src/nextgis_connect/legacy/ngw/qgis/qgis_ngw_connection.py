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

import contextlib
import json
import time
import urllib.parse
from base64 import b64encode
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from nextgis_connect.legacy.ngw.core.ngw_error import NGWError
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.logging import (
    format_container_data,
    logger,
)
from nextgis_connect.platform.qgis.compat import parse_version
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgwConnectionError,
    NgwError,
)
from nextgis_connect.platform.qt import QtNetworkError
from qgis.core import QgsFeedback, QgsNetworkAccessManager
from qgis.PyQt.QtCore import (
    QBuffer,
    QByteArray,
    QEventLoop,
    QFile,
    QFileInfo,
    QIODevice,
    QObject,
    QTimer,
    QUrl,
)
from qgis.PyQt.QtNetwork import (
    QNetworkRequest,
    QSsl,
    QSslCertificate,
    QSslError,
    QSslSocket,
)

from .compat_qgis import CompatQt

if TYPE_CHECKING:
    from qgis.PyQt.QtNetwork import QNetworkReply as _QNetworkReply

    class QNetworkReply(_QNetworkReply):
        def error(self) -> _QNetworkReply.NetworkError: ...  # type: ignore

else:
    from qgis.PyQt.QtNetwork import QNetworkReply

UPLOAD_FILE_URL = "/api/component/file_upload/"
GET_VERSION_URL = "/api/component/pyramid/pkg_version"
TUS_UPLOAD_FILE_URL = "/api/component/file_upload/"
TUS_VERSION = "1.0.0"
TUS_CHUNK_SIZE = 16777216
CLIENT_TIMEOUT = 3 * 60 * 1000


@dataclass(frozen=True)
class SslCertificateVerification:
    errors: Tuple[QSslError, ...]
    was_performed: bool


def is_lunkwill_reply(reply: QNetworkReply) -> bool:
    header_name = QNetworkRequest.KnownHeaders.ContentTypeHeader
    lunkwill_type = "application/vnd.lunkwill.request-summary+json"
    header = reply.header(header_name)
    if not isinstance(header, str):
        return False
    return header.startswith(lunkwill_type)


class NgwServerFeature(Enum):
    BOOLEAN_TYPE = ("boolean_type", "nextgisweb", parse_version("5.5.0.dev0"))
    NO_GEOMETRY_LAYERS = (
        "no_geometry_layers",
        "nextgisweb",
        parse_version("5.5.0.dev0"),
    )
    NO_GEOMETRY_LAYER_VERSIONING = (
        "no_geometry_layer_versioning",
        "nextgisweb",
        parse_version("5.5.0.dev8"),
    )
    REQUIRED_FIELDS = (
        "required_fields",
        "nextgisweb",
        parse_version("5.5.0.dev0"),
    )
    JSON_TYPE = ("json_type", "nextgisweb", parse_version("5.5.0.dev0"))

    @property
    def component(self):
        return self.value[1]

    @property
    def required_version(self):
        return self.value[2]


class QgsNgwConnection(QObject):
    """NextGIS Web API connection"""

    _cached_ngw_components_by_connection_id: ClassVar[
        Dict[str, Dict[str, Any]]
    ] = {}

    __connection_id: str
    __connection: Optional[NgwConnection]
    __log_network: bool

    __ngw_components: Optional[Dict[str, Any]]

    def __init__(
        self,
        connection: Union[str, NgwConnection],
        log_network: Optional[bool] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.__log_network = (
            NgConnectSettings().is_network_debug_enabled
            if log_network is None
            else log_network
        )
        self.__connection = None

        if isinstance(connection, NgwConnection):
            self.__connection_id = connection.id
            self.__connection = connection
        else:
            self.__connection_id = connection
            connections_manager = NgwConnectionsManager()
            if not connections_manager.is_valid(connection):
                raise NgwConnectionError(code=ErrorCode.InvalidConnection)

        self.__ngw_components = None

    @property
    def connection(self) -> NgwConnection:
        if self.__connection is not None:
            return self.__connection

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None
        return connection

    @property
    def server_url(self) -> str:
        return self.connection.url

    @property
    def connection_id(self) -> str:
        return self.__connection_id

    @classmethod
    def clear_cached_ngw_components(
        cls, connection_id: Optional[str] = None
    ) -> None:
        if connection_id is None:
            cls._cached_ngw_components_by_connection_id.clear()
            return

        cls._cached_ngw_components_by_connection_id.pop(connection_id, None)

    def invalidate_cached_ngw_components(self) -> None:
        self.__ngw_components = None
        self.clear_cached_ngw_components(self.connection_id)

    def has_support_for_feature(self, feature: NgwServerFeature) -> bool:
        ngw_components = self.get_ngw_components()
        component_version = ngw_components.get(feature.component)
        if not component_version:
            raise NgwConnectionError(
                f"Component {feature.component} version is not available in NGW versions response"
            )

        logger.debug(
            f"NGW component {feature.component} version is {component_version}"
        )

        ngw_version = parse_version(component_version)
        required_version = feature.required_version
        result = ngw_version >= required_version
        if not result:
            logger.debug(
                f"Feature {feature.name} requires version {required_version} "
                f"of component {feature.component} but actual version is {ngw_version}"
            )

        return result

    def get(
        self,
        sub_url: str,
        params=None,
        *,
        is_lunkwill: bool = False,
        feedback: Optional[QgsFeedback] = None,
        ssl_verification_callback: Optional[
            Callable[[SslCertificateVerification], None]
        ] = None,
        **kwargs,
    ) -> Any:
        return self.__request(
            sub_url,
            "GET",
            params,
            is_lunkwill=is_lunkwill,
            feedback=feedback,
            ssl_verification_callback=ssl_verification_callback,
            **kwargs,
        )

    def post(
        self,
        sub_url: str,
        params=None,
        *,
        is_lunkwill: bool = False,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> Any:
        return self.__request(
            sub_url,
            "POST",
            params,
            is_lunkwill=is_lunkwill,
            feedback=feedback,
            **kwargs,
        )

    def put(
        self,
        sub_url: str,
        params=None,
        *,
        is_lunkwill: bool = False,
        headers: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> Any:
        return self.__request(
            sub_url,
            "PUT",
            params,
            is_lunkwill=is_lunkwill,
            headers=headers,
            feedback=feedback,
            **kwargs,
        )

    def patch(
        self,
        sub_url: str,
        params=None,
        *,
        is_lunkwill: bool = False,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> Any:
        return self.__request(
            sub_url,
            "PATCH",
            params,
            is_lunkwill=is_lunkwill,
            feedback=feedback,
            **kwargs,
        )

    def delete(
        self,
        sub_url: str,
        params=None,
        *,
        is_lunkwill: bool = False,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> Any:
        return self.__request(
            sub_url,
            "DELETE",
            params,
            is_lunkwill=is_lunkwill,
            feedback=feedback,
            **kwargs,
        )

    def download(
        self,
        sub_url: str,
        path: str,
        *,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> None:
        data = self.get(
            sub_url,
            is_lunkwill=True,
            feedback=feedback,
            **kwargs,
        )

        file = QFile(path)
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            message = "Failed to open file for downloading into it"
            raise RuntimeError(message)

        file.write(data)
        file.close()

    def __request(
        self,
        sub_url,
        method,
        params=None,
        *,
        is_lunkwill: bool = False,
        headers: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ):
        request_url = self.__absolute_url(sub_url)
        try:
            return self.__execute_request(
                sub_url,
                method,
                params,
                is_lunkwill=is_lunkwill,
                headers=headers,
                feedback=feedback,
                **kwargs,
            )
        except NgConnectError as error:
            error.add_diagnostic_context("request_url", f"URL: {request_url}")
            raise
        except Exception as error:
            request_error = NgwError(
                "Network request failed",
                is_network_problem=True,
            )
            request_error.add_diagnostic_context(
                "request_url",
                f"URL: {request_url}",
            )
            raise request_error from error

    def __execute_request(
        self,
        sub_url: str,
        method: str,
        params: Optional[Any] = None,
        *,
        is_lunkwill: bool = False,
        headers: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ) -> Any:
        if is_lunkwill:
            headers = dict(headers or {}, **{"X-Lunkwill": "suggest"})

        reply, result = self.__request_and_decode(
            sub_url,
            method,
            params=params,
            headers=headers,
            feedback=feedback,
            **kwargs,
        )

        is_lunkwill_supported = is_lunkwill and is_lunkwill_reply(reply)
        reply.deleteLater()
        del reply

        if is_lunkwill_supported:
            if not isinstance(result, dict):
                raise NgwConnectionError("Unexpected lunkwill summary reply")
            result = self.__wait_for_answer(result, feedback=feedback)

        if self.__log_network and isinstance(result, (dict, list)):
            formatted_result = format_container_data(result)
            logger.debug(f"\nReply:\n{formatted_result}\n")

        return result

    def __absolute_url(self, sub_url: str) -> str:
        parsed_url = urllib.parse.urlparse(sub_url)
        if parsed_url.scheme and parsed_url.netloc:
            return sub_url

        return urllib.parse.urljoin(self.server_url, sub_url)

    def __request_rep(
        self,
        sub_url: str,
        method: str,
        *,
        badata: Optional[QByteArray] = None,
        params: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
        ssl_verification_callback: Optional[
            Callable[[SslCertificateVerification], None]
        ] = None,
        **kwargs,
    ) -> Tuple[QNetworkRequest, QNetworkReply]:
        """
        Send a network request to the NGW server and return the request and reply objects.

        :param sub_url: The sub-URL to send the request to.
        :param method: HTTP method (GET, POST, PATCH, DELETE, etc.).
        :param badata: Optional raw byte data to send in the request body.
        :param params: Optional parameters to include in the request.
        :param headers: Optional dictionary of HTTP headers.
        :param kwargs: Additional keyword arguments.

        :return: Tuple of QNetworkRequest and QNetworkReply.

        :raises NgwError: On network or server error.
        """
        json_data = None
        if params:
            if isinstance(params, str):
                json_data = params
            else:
                json_data = json.dumps(params)
        if "json" in kwargs:
            json_data = json.dumps(kwargs["json"])

        filename = kwargs.get("file")

        url = self.__absolute_url(sub_url)

        if self.__log_network:
            logger.debug(
                "\nRequest\nmethod: {}\nurl: {}\njson: {}\nheaders: {}\nfile: {}\nbyte data size: {}".format(
                    method,
                    url,
                    # type(json_data),
                    json_data,
                    headers,
                    filename if filename else "-",
                    badata.size() if badata else "-",
                )
            )

        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.CacheSaveControlAttribute, False
        )
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )

        self.connection.update_network_request(request)

        if headers is not None:  # add custom headers
            for name, value in list(headers.items()):
                request.setRawHeader(name.encode(), value.encode())

        iodevice = None  # default to None, not to "QBuffer(QByteArray())" - otherwise random crashes at post() in QGIS 3
        if badata is not None:
            iodevice = QBuffer(badata)
        elif filename is not None:
            iodevice = QFile(filename)
        elif json_data is not None:
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "application/json",
            )
            json_data = QByteArray(json_data.encode())
            iodevice = QBuffer(json_data)

        if iodevice is not None:
            iodevice.open(QIODevice.OpenModeFlag.ReadOnly)

        nam = QgsNetworkAccessManager.instance()

        if CompatQt.has_redirect_policy():
            nam.setRedirectPolicy(
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
            )

        if method == "GET":
            reply = nam.get(request)
        elif method == "POST":
            reply = nam.post(request, iodevice)
        elif method == "DELETE":
            if iodevice is not None:
                reply = nam.sendCustomRequest(request, b"DELETE", iodevice)
            else:
                reply = nam.deleteResource(request)
        else:
            reply = nam.sendCustomRequest(request, method.encode(), iodevice)

        assert isinstance(reply, QNetworkReply)

        observed_ssl_errors: List[QSslError] = []
        ssl_error_observer: Optional[Callable[[List[QSslError]], None]] = None
        if ssl_verification_callback is not None:
            ssl_error_observer = observed_ssl_errors.extend
            reply.sslErrors.connect(ssl_error_observer)

        if feedback is not None:
            feedback.canceled.connect(reply.abort)
            reply.downloadProgress.connect(
                lambda received, total: self.__update_feedback_progress(
                    feedback,
                    received,
                    total,
                )
            )
            reply.uploadProgress.connect(
                lambda sent, total: self.__update_feedback_progress(
                    feedback,
                    sent,
                    total,
                )
            )

        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        if feedback is not None:
            feedback.canceled.connect(loop.quit)

        if filename is not None:
            reply.uploadProgress.connect(self.sendUploadProgress)

        # In our current approach we use QEventLoop to wait QNetworkReply finished() signal. This could lead to infinite loop
        # in the case when finished() signal 1) is not fired at all or 2) fired right after isFinished() method but before loop.exec_().
        # We need some kind of guard for that OR we need to use another approach to wait for network replies (e.g. fully asynchronous
        # approach which is actually should be used when dealing with QNetworkAccessManager).
        # NOTE: actualy this is also our client timeout for any single request to NGW. We are able to set it to some not-large value because
        # we use tus uplod for large files => we do not warry that large files will not be uploaded this way.
        is_feedback_canceled = feedback is not None and feedback.isCanceled()
        if is_feedback_canceled:
            reply.abort()

        # isFinished() checks that finished() is emitted before this point,
        # but not after this check.
        if not reply.isFinished() and not is_feedback_canceled:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(CLIENT_TIMEOUT)

            loop.exec()
        del loop

        if iodevice is not None:
            iodevice.close()

        if ssl_error_observer is not None:
            with contextlib.suppress(TypeError, RuntimeError):
                reply.sslErrors.disconnect(ssl_error_observer)

            assert ssl_verification_callback is not None
            if observed_ssl_errors:
                verification = SslCertificateVerification(
                    tuple(observed_ssl_errors),
                    was_performed=True,
                )
            else:
                verification = self.__verify_peer_certificate(reply)
            ssl_verification_callback(verification)

        if feedback is not None and feedback.isCanceled():
            raise NgConnectError("Request was canceled")

        status_code = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )

        # Indicate that request has been timed out by QGIS.
        # TODO: maybe use QgsNetworkAccessManager::requestTimedOut()?
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            qt_error_info = QtNetworkError.from_qt(reply.error()).value  # type: ignore
            error = NgwError(
                "Connection has been aborted or closed",
                code=ErrorCode.QgisTimeoutError,
                detail=self.tr(
                    "Connection was closed by QGIS. Please check your internet"
                    " connection or increase timeout"
                    " (Settings -> Options -> Network) and retry."
                ),
                is_network_problem=True,
            )
            error.add_diagnostic_context(
                "request_url",
                f"URL: {request.url().toString()}",
            )
            qt_error_info.add_exception_notes(error)
            raise error

        # Network-related errors indicating connection issues, timeouts, or system/network-level failures.
        elif (
            reply.error() == QNetworkReply.NetworkError.SslHandshakeFailedError
        ):
            qt_error_info = QtNetworkError.from_qt(reply.error()).value
            error = NgwError(
                "SSL/TLS handshake failed",
                user_message=self.tr(
                    "The SSL/TLS handshake failed and the encrypted channel could not be established."
                ),
                detail=qt_error_info.description,
                code=ErrorCode.SslHandshakeError,
                is_network_problem=True,
            )
            error.add_diagnostic_context(
                "request_url",
                f"URL: {request.url().toString()}",
            )
            qt_error_info.add_exception_notes(error)
            raise error

        elif status_code is not None and status_code // 100 != 2:
            return request, reply

        elif reply.error() != QNetworkReply.NetworkError.NoError:
            qt_error_info = QtNetworkError.from_qt(reply.error()).value
            error = NgwError(
                "Connection error",
                is_network_problem=True,
            )
            error.add_diagnostic_context(
                "request_url",
                f"URL: {request.url().toString()}",
            )
            qt_error_info.add_exception_notes(error)
            raise error

        return request, reply

    @staticmethod
    def __verify_peer_certificate(
        reply: QNetworkReply,
    ) -> SslCertificateVerification:
        certificate_chain = reply.sslConfiguration().peerCertificateChain()
        if not certificate_chain or not QgsNgwConnection.__can_verify_chain():
            return SslCertificateVerification((), was_performed=False)

        if len(certificate_chain) > 1 and certificate_chain[-1].isSelfSigned():
            certificate_chain = certificate_chain[:-1]

        errors = QSslCertificate.verify(certificate_chain, reply.url().host())
        return SslCertificateVerification(tuple(errors), was_performed=True)

    @staticmethod
    def __can_verify_chain() -> bool:
        supported_features = getattr(QSslSocket, "supportedFeatures", None)
        feature_enum = getattr(QSsl, "SupportedFeature", None)
        if supported_features is None or feature_enum is None:
            ssl_library = QSslSocket.sslLibraryVersionString().lower()
            return "openssl" in ssl_library

        return feature_enum.CertificateVerification in supported_features()

    def __request_and_decode(
        self,
        sub_url,
        method,
        params=None,
        headers=None,
        feedback: Optional[QgsFeedback] = None,
        **kwargs,
    ):
        request, reply = self.__request_rep(
            sub_url,
            method,
            badata=None,
            params=params,
            headers=headers,
            feedback=feedback,
            **kwargs,
        )

        status_code = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        if (
            reply.error() != QNetworkReply.NetworkError.NoError  # type: ignore
            or (status_code is not None and status_code // 100 != 2)
        ):
            data = None
            with contextlib.suppress(Exception):
                data = self.__extract_data(reply)

            if self.__log_network:
                logger.debug(f"Response error\nstatus_code {status_code}")
                if isinstance(data, (dict, list)):
                    formatted_data = format_container_data(data)
                    logger.debug(f"\nReply:\n{formatted_data}\n")

            if isinstance(data, dict):
                if "status_code" not in data:
                    data["status_code"] = status_code

                raise NgwError.from_json(data)

            codes: Dict[Optional[int], ErrorCode] = {
                HTTPStatus.UNAUTHORIZED: ErrorCode.AuthorizationError,
                HTTPStatus.FORBIDDEN: ErrorCode.PermissionsError,
                HTTPStatus.NOT_FOUND: ErrorCode.NotFound,
            }
            is_server_unavailable = (
                status_code is not None and status_code // 100 == 5
            )
            error = NgwError(
                code=codes.get(status_code, ErrorCode.NgwError),
                status_code=status_code,
                is_server_unavailable=is_server_unavailable,
            )
            error.add_diagnostic_context(
                "request_url",
                f"URL: {request.url().toString()}",
            )
            error.add_note(f"HTTP status code: {status_code}")
            raise error

        try:
            response_data = self.__extract_data(reply)

        except NgConnectError:
            raise
        except Exception as error:
            message = "Extracting data error"
            raise NgConnectError(message) from error

        return reply, response_data

    def upload_file(
        self,
        filename: str,
        callback: Any,
        *,
        mime_type: Optional[str] = None,
        feedback: Optional[QgsFeedback] = None,
    ) -> Any:
        self.uploadProgressCallback = callback
        headers = {"Content-Type": mime_type} if mime_type else None
        return self.put(
            UPLOAD_FILE_URL,
            file=filename,
            headers=headers,
            feedback=feedback,
        )

    def tus_upload_file(
        self,
        filename: str,
        callback: Any,
        *,
        upload_name: Optional[str] = None,
        feedback: Optional[QgsFeedback] = None,
    ) -> Any:
        """
        Implements tus protocol to upload a file to NGW.
        Note: This method internally uses self methods to send synchronous
        HTTP requests (which internally use QgsNetworkAccessManager) so we
        cannot put it to some separate class or module.

        This method uploads a file in chunks using the TUS protocol, providing
        progress updates via the callback. Raises an exception if the upload fails.

        :param filename: Path to the file to upload.
        :type filename: str
        :param callback: Callback function for upload progress.
        :type callback: Any
        :param upload_name: File name to store in the upload metadata.
        :type upload_name: Optional[str]

        :return: NGW server response after successful upload.
        :rtype: Any

        :raises Exception: If file cannot be opened or upload fails.
        :raises NGWError: If the server returns an error.
        """
        callback(
            0, 0, 0
        )  # show in the progress bar that 0% is loaded currently
        self.uploadProgressCallback = callback

        file = QFile(filename)
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise Exception("Failed to open file for tus upload")
        file_size = file.size()

        # Initiate upload process by sending specific "create" request with a
        # void body.
        upload_name = upload_name or QFileInfo(filename).fileName()
        encoded_filename = b64encode(upload_name.encode()).decode()
        create_hdrs = {
            "Tus-Resumable": TUS_VERSION,
            "Content-Length": "0",
            #'Upload-Defer-Length': ,
            "Upload-Length": str(file_size),
            "Upload-Metadata": f"name {encoded_filename}",
        }
        _, create_rep = self.__request_rep(
            TUS_UPLOAD_FILE_URL,
            "POST",
            headers=create_hdrs,
            feedback=feedback,
        )
        create_rep_code = create_rep.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        if create_rep_code == 413:
            raise NGWError(
                NGWError.TypeRequestError,
                "HTTP 413: Payload is too large",
                TUS_UPLOAD_FILE_URL,
                self.tr("File is too large for uploading"),
                need_reconnect=False,
            )
        if create_rep_code != 201:
            raise Exception("Failed to start tus uploading")
        location_hdr = b"Location"
        location = create_rep.rawHeader(location_hdr).data().decode()
        create_rep.deleteLater()
        del create_rep

        file_guid = location.split("/")[-1]
        file_upload_url = TUS_UPLOAD_FILE_URL + file_guid
        max_retry_count = 3
        bytes_sent = 0

        is_file_large = (file_size / TUS_CHUNK_SIZE) > 10

        # Allow to skip logging of PATCH requests. Helpful when a large file is being uploaded.
        # Note: QGIS 3 has a hardcoded limit of log messages.
        if self.__log_network and is_file_large:
            logger.debug(
                f'Skip PATCH requests logging during uploading of file "{file_guid}"'
            )

        # Upload file chunk-by-chunk.
        while True:
            if feedback is not None and feedback.isCanceled():
                raise NgConnectError("Request was canceled")

            badata = QByteArray(file.read(TUS_CHUNK_SIZE))
            if badata.isEmpty():  # end of data OR some error
                break
            bytes_read = badata.size()

            if self.__log_network and not is_file_large:
                logger.debug(f"Upload {bytes_sent} from {file_size}")
            self.sendUploadProgress(bytes_sent, file_size)

            chunk_hdrs = {
                "Tus-Resumable": TUS_VERSION,
                "Content-Type": "application/offset+octet-stream",
                "Content-Length": str(bytes_read),
                "Upload-Offset": str(bytes_sent),
            }
            retries = 0
            while retries < max_retry_count:
                if retries > 0:
                    logger.debug(f"Retrying. Attempt #{retries}")

                _, chunk_reply = self.__request_rep(
                    file_upload_url,
                    "PATCH",
                    badata=badata,
                    headers=chunk_hdrs,
                    feedback=feedback,
                )
                chunk_rep_code = chunk_reply.attribute(
                    QNetworkRequest.Attribute.HttpStatusCodeAttribute
                )
                if chunk_reply.error() != QNetworkReply.NetworkError.NoError:
                    logger.warning("An error occurred during uploading file")
                    qt_error_info = QtNetworkError.from_qt(
                        chunk_reply.error()
                    ).value
                    logger.debug(f"HTTP Status code: {chunk_rep_code}\n")
                    logger.debug(f"Network error: {qt_error_info.constant}")
                    logger.debug(
                        f"Error description: {qt_error_info.description}"
                    )

                chunk_reply.deleteLater()
                del chunk_reply
                if chunk_rep_code == 204:
                    break
                retries += 1

            if retries == max_retry_count:
                logger.error(
                    "Maximum number of attempts reached. TUS uploading is cancelled."
                )
                break

            bytes_sent += bytes_read
            if self.__log_network and not is_file_large:
                logger.debug(
                    f"Tus-uploaded chunk of {bytes_read} bytes. Now "
                    f"{bytes_sent} of overall {file_size} bytes are uploaded"
                )

        file.close()

        if bytes_sent < file_size:
            raise Exception("Failed to upload file via tus")

        callback(1, 1, 100)  # show in the progress bar that 100% is loaded

        # Finally GET and return NGW result of uploaded file.
        return self.get(file_upload_url, feedback=feedback)

    def __update_feedback_progress(
        self,
        feedback: QgsFeedback,
        current: int,
        total: int,
    ) -> None:
        if total <= 0:
            return

        feedback.setProgress(current * 100 / total)

    def sendUploadProgress(self, sent, total):
        # For Qt 5 the uploadProgress signal is sometimes emited when
        # sent and total are 0.
        # TODO: understand why. For now prevent calling uploadProgressCallback
        # so not to allow zero devision in according callbacks.
        if sent != 0 and total != 0:
            self.uploadProgressCallback(total, sent)

    def get_ngw_components(
        self,
        *,
        feedback: Optional[QgsFeedback] = None,
    ):
        if self.__ngw_components is not None:
            return self.__ngw_components

        cached_components = self._cached_ngw_components_by_connection_id.get(
            self.connection_id
        )
        if cached_components is not None:
            self.__ngw_components = cached_components
            return self.__ngw_components

        logger.debug("↓ Get versions")
        result = self.get(GET_VERSION_URL, feedback=feedback)
        if not isinstance(result, dict):
            raise NgwConnectionError("Unexpected versions result")

        self.__ngw_components = result
        self._cached_ngw_components_by_connection_id[self.connection_id] = (
            self.__ngw_components
        )

        domain = urllib.parse.urlparse(self.server_url).hostname
        version = self.__ngw_components.get("nextgisweb")
        logger.debug(f"↔ Connected to {domain} (NGW version: {version})")

        return self.__ngw_components

    def get_version(
        self,
        *,
        feedback: Optional[QgsFeedback] = None,
    ):
        ngw_components = self.get_ngw_components(feedback=feedback)
        return ngw_components.get("nextgisweb")

    def __wait_for_answer(
        self,
        lunkwill_summary: Dict[str, Any],
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> Any:
        # Send "summary" requests periodically to check long request's status.
        # Make final "response" request with usual NGW json response after
        # receiving "ready" status.

        default_wait_ms = 2000
        max_failed_attempts = 3

        summary_failed = 0
        request_id = lunkwill_summary["id"]

        while True:
            if feedback is not None and feedback.isCanceled():
                raise NgConnectError("Request was canceled")

            status = lunkwill_summary["status"]
            delay_ms = lunkwill_summary.get("delay_ms", default_wait_ms)
            retry_ms = lunkwill_summary.get("retry_ms", default_wait_ms)

            if summary_failed == 0:
                wait_ms = delay_ms / 1000
            elif summary_failed <= max_failed_attempts:
                wait_ms = retry_ms / 1000
            else:
                message = "Lunkwill request aborted: failed summary requests count exceeds maximum"
                raise RuntimeError(message)

            if status in ("processing", "spooled", "buffering"):
                time.sleep(wait_ms)
                try:
                    sub_url = f"/api/lunkwill/{request_id}/summary"
                    answer = self.get(sub_url, feedback=feedback)
                    summary_failed = 0

                    if not isinstance(answer, dict):
                        error = NgwConnectionError("Unexpected summary answer")
                        raise error

                    lunkwill_summary = answer

                except Exception:
                    if self.__log_network:
                        logger.debug(
                            "Lunkwill summary request failed. Try again"
                        )
                    summary_failed += 1

            elif status == "ready":
                sub_url = f"/api/lunkwill/{request_id}/response"
                lunkwill_summary = self.get(sub_url, feedback=feedback)
                break

            else:
                message = f"Lunkwill request failed on server. Reply: {lunkwill_summary!s}"
                raise RuntimeError(message)

        return lunkwill_summary

    def __extract_data(
        self, reply: QNetworkReply
    ) -> Union[QByteArray, Dict[str, Any], None]:
        status_code = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        if status_code == HTTPStatus.NO_CONTENT:
            return None

        is_lunkwill_summary = is_lunkwill_reply(reply)
        header_name = QNetworkRequest.KnownHeaders.ContentTypeHeader
        is_json = reply.header(header_name) == "application/json"

        data = reply.readAll()

        if not is_lunkwill_summary and not is_json:
            return data

        json_string = ""
        try:
            json_string = data.data().decode()
            json_response = json.loads(json_string)
        except json.decoder.JSONDecodeError:
            message = "JSON parsing error"
            logger.debug(f"{message}. Wrong data:\n{json_string}\n")
            raise NgwError(message, code=ErrorCode.IncorrectAnswer) from None
        else:
            return json_response

    def __deepcopy__(self, memo):
        if self.__connection is not None:
            return QgsNgwConnection(
                self.__connection,
                log_network=self.__log_network,
            )

        return QgsNgwConnection(
            str(self.__connection_id),
            log_network=self.__log_network,
        )
