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

from dataclasses import replace
from typing import TYPE_CHECKING, List, Optional, Sequence
from urllib.parse import urlparse

from qgis.core import QgsApplication, QgsFeedback
from qgis.PyQt.QtNetwork import QSslError, QSslSocket

from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
    SslCertificateVerification,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckId,
    ConnectionCheckResult,
    ConnectionDiagnosticContext,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import (
    NgConnectError,
    NgConnectException,
    NgwError,
)

from .base import BaseConnectionCheck, UpdateReporter

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )


class CertificateCheck(BaseConnectionCheck):
    check_id = ConnectionCheckId.CERTIFICATE
    is_blocking = True

    @property
    def title(self) -> str:
        return self.tr("Certificate")

    @property
    def initial_description(self) -> str:
        return self.tr("Checking the server certificate.")

    def run_check(
        self,
        context: ConnectionDiagnosticContext,
        ngw_connection: "QgsNgwConnection",
        feedback: QgsFeedback,
        report_update: UpdateReporter,
    ) -> ConnectionCheckResult:
        host_port = self._host_port()
        ssl_verifications: List[SslCertificateVerification] = []
        request_failure = self._request_server(feedback, ssl_verifications)
        if request_failure is not None:
            return request_failure

        ssl_config = QgsApplication.authManager().sslCertCustomConfigByHost(
            host_port
        )
        ignored_errors = ssl_config.sslIgnoredErrorEnums()
        peer_verify_mode = ssl_config.sslPeerVerifyMode()

        logger_message = self.tr(
            "SSL configuration for {host}: config_exists={exists}, ignored_errors={ignored_errors}, peer_verify_mode={peer_verify_mode}"
        ).format(
            host=host_port,
            exists=not ssl_config.isNull(),
            ignored_errors=len(ignored_errors),
            peer_verify_mode=self._peer_verify_mode_label(peer_verify_mode),
        )
        logger.debug(logger_message)

        verification = ssl_verifications[-1] if ssl_verifications else None
        ssl_errors = verification.errors if verification is not None else ()
        if ssl_errors:
            return self._ignored_ssl_errors_warning(ssl_errors)

        if not ssl_config.isNull() and (
            len(ignored_errors) > 0
            or peer_verify_mode != QSslSocket.PeerVerifyMode.VerifyPeer
        ):
            return self._warning(
                self.tr(
                    "The Web GIS certificate is accepted by QGIS with custom SSL exceptions."
                ),
                issue=self._client_issue(
                    self.tr(
                        "The Web GIS is reachable, but QGIS stores SSL exceptions for this host."
                    ),
                    self.tr(
                        "Review the accepted certificate and ignored SSL errors in the QGIS network settings."
                    ),
                ),
            )

        if verification is None or not verification.was_performed:
            return self._verification_unavailable_warning()

        return self._success(
            self.tr(
                "The Web GIS certificate was accepted without custom SSL exceptions."
            )
        )

    def _request_server(
        self,
        feedback: QgsFeedback,
        ssl_verifications: List[SslCertificateVerification],
    ) -> Optional[ConnectionCheckResult]:
        certificate_connection = QgsNgwConnection(
            replace(self._connection, auth_config_id=None),
            log_network=True,
        )
        try:
            certificate_connection.get(
                self._connection.url,
                feedback=feedback,
                ssl_verification_callback=ssl_verifications.append,
            )
        except NgwError as error:
            self._raise_if_canceled(feedback, error)
            logger.debug(
                f"Certificate check request failed: status_code={error.status_code} code={error.code.name} network_problem={error.is_network_problem} detail={error.detail or '-'}"
            )
            # Authentication is intentionally omitted, so an HTTP error such
            # as 401 still proves that TLS validation completed successfully.
            if error.status_code is not None:
                return None
            if self._is_ssl_error(error):
                ssl_errors = (
                    ssl_verifications[-1].errors if ssl_verifications else ()
                )
                return self._ssl_failure(error, ssl_errors)
            if self._is_network_error(error):
                return self._network_failure(error)
            return self._unreachable_failure(error)
        except NgConnectError as error:
            self._raise_if_canceled(feedback, error)
            logger.debug(
                f"Certificate check request failed: code={error.code.name} detail={error.detail or '-'}"
            )
            return self._network_failure(error)

        return None

    def _ssl_failure(
        self,
        error: NgwError,
        ssl_errors: Sequence[QSslError],
    ) -> ConnectionCheckResult:
        technical_details = self._ssl_error_details(ssl_errors) or error.detail
        return self._failure(
            self.tr("The Web GIS certificate was not accepted by QGIS."),
            issue=self._server_issue(
                self.tr(
                    "The SSL/TLS certificate validation failed before the Web GIS could be reached."
                ),
                self.tr(
                    "Check the server certificate chain and accept or trust the certificate in QGIS if it is expected."
                ),
                technical_details=technical_details,
            ),
        )

    def _ignored_ssl_errors_warning(
        self,
        ssl_errors: Sequence[QSslError],
    ) -> ConnectionCheckResult:
        technical_details = self._ssl_error_details(ssl_errors)
        logger.debug(
            f"Certificate validation reported ignored SSL errors: {technical_details}"
        )
        return self._warning(
            self.tr(
                "The Web GIS certificate was accepted after SSL errors were ignored."
            ),
            issue=self._client_issue(
                self.tr(
                    "The Web GIS is reachable, but certificate validation reported SSL errors."
                ),
                self.tr(
                    "Review the server certificate chain and ignore SSL errors only if you trust this certificate."
                ),
                technical_details=technical_details,
            ),
        )

    def _verification_unavailable_warning(self) -> ConnectionCheckResult:
        return self._warning(
            self.tr(
                "The server certificate could not be independently verified."
            ),
            issue=self._client_issue(
                self.tr(
                    "The TLS backend did not provide enough information to verify the server certificate."
                ),
                self.tr(
                    "Restart QGIS and retry the check, or inspect the server certificate with system tools."
                ),
            ),
        )

    def _network_failure(
        self,
        error: NgConnectException,
    ) -> ConnectionCheckResult:
        return self._failure(
            self.tr("Unable to verify the server certificate."),
            issue=self._network_issue(
                error,
                self.tr(
                    "Check the network path to the Web GIS and retry the checks."
                ),
            ),
        )

    def _unreachable_failure(self, error: NgwError) -> ConnectionCheckResult:
        return self._failure(
            self.tr("The certificate check could not reach the Web GIS."),
            issue=self._server_issue(
                self.tr(
                    "The Web GIS did not respond while the certificate check was running."
                ),
                self.tr(
                    "Check the Web GIS availability and retry the checks."
                ),
                technical_details=error.detail,
            ),
        )

    def _ssl_error_details(
        self,
        ssl_errors: Sequence[QSslError],
    ) -> str:
        return "; ".join(
            f"{self._enum_label(error.error())}: {error.errorString()}"
            for error in ssl_errors
        )

    def _host_port(self) -> str:
        parsed_url = urlparse(self._connection.url)
        host = parsed_url.hostname or ""
        port = parsed_url.port
        if port is not None:
            return f"{host}:{port}"

        if parsed_url.scheme == "https":
            return f"{host}:443"

        return f"{host}:80"

    def _peer_verify_mode_label(self, peer_verify_mode) -> str:
        return self._enum_label(peer_verify_mode)

    def _enum_label(self, enum_value) -> str:
        name = getattr(enum_value, "name", None)
        value = getattr(enum_value, "value", None)
        if name is not None and value is not None:
            return f"{name} ({value})"

        return str(enum_value)
