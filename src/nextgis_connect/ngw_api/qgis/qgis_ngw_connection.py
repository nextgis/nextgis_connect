"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2014-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import contextlib
import json
import time
import urllib.parse
from base64 import b64encode
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import (
    QBuffer,
    QByteArray,
    QEventLoop,
    QFile,
    QIODevice,
    QObject,
    QTimer,
    QUrl,
)
from qgis.PyQt.QtNetwork import QNetworkRequest

from nextgis_connect.exceptions import (
    ErrorCode,
    NgConnectError,
    NgwConnectionError,
    NgwError,
)
from nextgis_connect.logging import escape_html, format_container_data, logger
from nextgis_connect.network.qt_network_error import QtNetworkError
from nextgis_connect.ngw_api.core.ngw_error import NGWError
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.settings import NgConnectSettings

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


def is_lunkwill_reply(reply: QNetworkReply) -> bool:
    header_name = QNetworkRequest.KnownHeaders.ContentTypeHeader
    lunkwill_type = "application/vnd.lunkwill.request-summary+json"
    header = reply.header(header_name)
    if not isinstance(header, str):
        return False
    return header.startswith(lunkwill_type)


class QgsNgwConnection(QObject):
    """NextGIS Web API connection"""

    __connection_id: str
    __log_network: bool

    __ngw_components: Optional[Dict]

    def __init__(
        self, connection_id: str, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.__connection_id = connection_id
        self.__log_network = NgConnectSettings().is_network_debug_enabled

        connections_manager = NgwConnectionsManager()
        if not connections_manager.is_valid(connection_id):
            raise NgwConnectionError(code=ErrorCode.InvalidConnection)

        self.__ngw_components = None

    @property
    def server_url(self) -> str:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None
        return connection.url

    @property
    def connection_id(self) -> str:
        return self.__connection_id

    def get(
        self, sub_url: str, params=None, *, is_lunkwill: bool = False, **kwargs
    ) -> Any:
        return self.__request(
            sub_url, "GET", params, is_lunkwill=is_lunkwill, **kwargs
        )

    def post(
        self, sub_url: str, params=None, *, is_lunkwill: bool = False, **kwargs
    ) -> Any:
        return self.__request(
            sub_url, "POST", params, is_lunkwill=is_lunkwill, **kwargs
        )

    def put(
        self, sub_url: str, params=None, *, is_lunkwill: bool = False, **kwargs
    ) -> Any:
        return self.__request(
            sub_url, "PUT", params, is_lunkwill=is_lunkwill, **kwargs
        )

    def patch(
        self, sub_url: str, params=None, *, is_lunkwill: bool = False, **kwargs
    ) -> Any:
        return self.__request(
            sub_url, "PATCH", params, is_lunkwill=is_lunkwill, **kwargs
        )

    def delete(
        self, sub_url: str, params=None, *, is_lunkwill: bool = False, **kwargs
    ) -> Any:
        return self.__request(
            sub_url, "DELETE", params, is_lunkwill=is_lunkwill, **kwargs
        )

    def download(
        self,
        sub_url: str,
        path: str,
        **kwargs,
    ) -> None:
        data = self.get(sub_url, is_lunkwill=True, **kwargs)

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
        **kwargs,
    ):
        headers = None
        if is_lunkwill:
            headers = {"X-Lunkwill": "suggest"}

        reply, result = self.__request_and_decode(
            sub_url,
            method,
            params=params,
            headers=headers,
            **kwargs,
        )

        is_lunkwill_supported = is_lunkwill and is_lunkwill_reply(reply)
        reply.deleteLater()
        del reply

        if is_lunkwill_supported:
            result = self.__wait_for_answer(result)

        if self.__log_network and isinstance(result, (dict, list)):
            escaped_result = escape_html(format_container_data(result))
            logger.debug(f"\nReply:\n{escaped_result}\n")

        return result

    def __request_rep(
        self,
        sub_url: str,
        method: str,
        *,
        badata: Optional[QByteArray] = None,
        params: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Tuple[QNetworkRequest, QNetworkReply]:
        """
        Send a network request to the NGW server and return the request and reply objects.

        :param sub_url: The sub-URL to send the request to.
        :type sub_url: str
        :param method: HTTP method (GET, POST, PATCH, DELETE, etc.).
        :type method: str
        :param badata: Optional raw byte data to send in the request body.
        :type badata: Optional[QByteArray]
        :param params: Optional parameters to include in the request.
        :type params: Optional[Any]
        :param headers: Optional dictionary of HTTP headers.
        :type headers: Optional[Dict[str, str]]
        :param kwargs: Additional keyword arguments.

        :return: Tuple of QNetworkRequest and QNetworkReply.
        :rtype: Tuple[QNetworkRequest, QNetworkReply]

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

        url = urllib.parse.urljoin(self.server_url, sub_url)

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

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.__connection_id)
        assert connection is not None
        connection.update_network_request(request)

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

        loop = QEventLoop()  # loop = QEventLoop(self)
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

        reply.finished.connect(loop.quit)
        if filename is not None:
            reply.uploadProgress.connect(self.sendUploadProgress)

        # In our current approach we use QEventLoop to wait QNetworkReply finished() signal. This could lead to infinite loop
        # in the case when finished() signal 1) is not fired at all or 2) fired right after isFinished() method but before loop.exec_().
        # We need some kind of guard for that OR we need to use another approach to wait for network replies (e.g. fully asynchronous
        # approach which is actually should be used when dealing with QNetworkAccessManager).
        # NOTE: actualy this is also our client timeout for any single request to NGW. We are able to set it to some not-large value because
        # we use tus uplod for large files => we do not warry that large files will not be uploaded this way.
        if not reply.isFinished():  # isFinished() checks that finished() is emmited before, but not after this method
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(CLIENT_TIMEOUT)

            loop.exec()
        del loop

        if iodevice is not None:
            iodevice.close()

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
            )
            error.add_note(f"URL: {request.url().toString()}")
            qt_error_info.add_exception_notes(error)
            raise error

        # Network-related errors indicating connection issues, timeouts, or system/network-level failures.
        elif reply.error() in {
            QNetworkReply.NetworkError.ConnectionRefusedError,
            QNetworkReply.NetworkError.RemoteHostClosedError,
            QNetworkReply.NetworkError.HostNotFoundError,
            QNetworkReply.NetworkError.TimeoutError,
            QNetworkReply.NetworkError.SslHandshakeFailedError,
            QNetworkReply.NetworkError.TemporaryNetworkFailureError,
            QNetworkReply.NetworkError.NetworkSessionFailedError,
            QNetworkReply.NetworkError.BackgroundRequestNotAllowedError,
        }:
            qt_error_info = QtNetworkError.from_qt(reply.error()).value
            error = NgwError("Connection error")
            error.add_note(f"URL: {request.url().toString()}")
            qt_error_info.add_exception_notes(error)
            raise error

        return request, reply

    def __request_and_decode(
        self, sub_url, method, params=None, headers=None, **kwargs
    ):
        request, reply = self.__request_rep(
            sub_url,
            method,
            badata=None,
            params=params,
            headers=headers,
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
                    escaped_data = escape_html(format_container_data(data))
                    logger.debug(f"\nReply:\n{escaped_data}\n")

            if isinstance(data, dict):
                if "status_code" not in data:
                    data["status_code"] = status_code

                raise NgwError.from_json(data)

            codes = {
                HTTPStatus.UNAUTHORIZED: ErrorCode.AuthorizationError,
                HTTPStatus.FORBIDDEN: ErrorCode.PermissionsError,
                HTTPStatus.NOT_FOUND: ErrorCode.NotFound,
            }
            error = NgwError(code=codes.get(status_code, ErrorCode.NgwError))
            error.add_note(f"URL: {request.url().toString()}")
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

    def upload_file(self, filename, callback):
        self.uploadProgressCallback = callback
        return self.put(UPLOAD_FILE_URL, file=filename)

    def tus_upload_file(self, filename: str, callback: Any) -> Any:
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
        encoded_filename = b64encode(file.fileName().encode()).decode()
        create_hdrs = {
            "Tus-Resumable": TUS_VERSION,
            "Content-Length": "0",
            #'Upload-Defer-Length': ,
            "Upload-Length": str(file_size),
            "Upload-Metadata": f"name {encoded_filename}",
        }
        create_req, create_rep = self.__request_rep(
            TUS_UPLOAD_FILE_URL, "POST", headers=create_hdrs
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
        location = bytes(create_rep.rawHeader(location_hdr)).decode()
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
                    logger.debug(f"Retrying. Attempt №{retries}")

                chunk_request, chunk_reply = self.__request_rep(
                    file_upload_url,
                    "PATCH",
                    badata=badata,
                    headers=chunk_hdrs,
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
        return self.get(file_upload_url)

    def sendUploadProgress(self, sent, total):
        # For Qt 5 the uploadProgress signal is sometimes emited when
        # sent and total are 0.
        # TODO: understand why. For now prevent calling uploadProgressCallback
        # so not to allow zero devision in according callbacks.
        if sent != 0 and total != 0:
            self.uploadProgressCallback(total, sent)

    def get_ngw_components(self):
        if self.__ngw_components is None:
            logger.debug("↓ Get versions")
            result = self.get(GET_VERSION_URL)
            if not isinstance(result, dict):
                raise NgwConnectionError("Unexpected versions result")

            self.__ngw_components = result
            domain = urllib.parse.urlparse(self.server_url).hostname
            version = self.__ngw_components.get("nextgisweb")
            logger.debug(
                f"<b>↔ Connected</b> to {domain} (NGW version: {version})"
            )

        return self.__ngw_components

    def get_version(self):
        ngw_components = self.get_ngw_components()
        return ngw_components.get("nextgisweb")

    def __wait_for_answer(self, lunkwill_summary: Dict[str, Any]) -> Any:
        # Send "summary" requests periodically to check long request's status.
        # Make final "response" request with usual NGW json response after
        # receiving "ready" status.

        default_wait_ms = 2000
        max_failed_attempts = 3

        summary_failed = 0
        request_id = lunkwill_summary["id"]

        while True:
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
                    answer = self.get(sub_url)
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
                lunkwill_summary = self.get(sub_url)
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
        return QgsNgwConnection(str(self.__connection_id))
