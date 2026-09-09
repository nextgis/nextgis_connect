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

import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from qgis.core import QgsFeedback

from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.current_user import (
    CurrentUserExpectation,
)
from nextgis_connect.legacy.ngw_connection.application.diagnostics.parsers import (
    QgisPluginRepositoryParser,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckState,
    ConnectionDiagnosticContext,
)
from nextgis_connect.legacy.ngw_connection.domain.parsers import (
    NgwServerTitleParser,
    suggested_connection_name,
)

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )


class _FakeSignal:
    def connect(self, callback) -> None:
        del callback


class _FakeDiagnosticsController:
    def __init__(self, connection, parent) -> None:
        del connection, parent
        self.check_updated = _FakeSignal()
        self.finished = _FakeSignal()
        self.is_started = False

    def initial_updates(self):
        return []

    def start(self) -> None:
        self.is_started = True


class _NullSslConfig:
    def isNull(self) -> bool:
        return True

    def sslIgnoredErrorEnums(self):
        return []

    def sslPeerVerifyMode(self):
        return None


class _AuthManager:
    def sslCertCustomConfigByHost(self, host):
        del host
        return _NullSslConfig()


class _Application:
    @staticmethod
    def authManager():
        return _AuthManager()


class TestConnectionDiagnosticsHelpers(unittest.TestCase):
    def test_certificate_check_accepts_http_unauthorized_response(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks import (
            certificate,
        )
        from nextgis_connect.platform.qgis.errors import NgwError

        network_logging = []

        class _UnauthorizedConnection:
            def __init__(self, connection, *, log_network) -> None:
                del connection
                network_logging.append(log_network)

            def get(
                self,
                url,
                *,
                feedback,
                ssl_verification_callback,
            ) -> None:
                del url, feedback
                ssl_verification_callback(
                    SimpleNamespace(errors=(), was_performed=True)
                )
                raise NgwError(status_code=401)

        with patch.object(
            certificate, "QgsNgwConnection", _UnauthorizedConnection
        ), patch.object(certificate, "QgsApplication", _Application):
            connection = NgwConnection(
                id="protected-id",
                name="Protected",
                url="https://protected.example.com",
                auth_config_id="auth-id",
            )
            result = certificate.CertificateCheck(connection).execute(
                ConnectionDiagnosticContext(connection),
                cast("QgsNgwConnection", None),
                QgsFeedback(),
                lambda update: None,
            )

        self.assertEqual(result.state, ConnectionCheckState.SUCCESS)
        self.assertEqual(network_logging, [True])

    def test_certificate_check_rejects_error_without_http_response(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks import (
            certificate,
        )
        from nextgis_connect.platform.qgis.errors import NgwError

        class _NetworkErrorConnection:
            def __init__(self, connection, *, log_network) -> None:
                del connection, log_network

            def get(
                self,
                url,
                *,
                feedback,
                ssl_verification_callback,
            ) -> None:
                del url, feedback, ssl_verification_callback
                raise NgwError(is_network_problem=True)

        with patch.object(
            certificate,
            "QgsNgwConnection",
            _NetworkErrorConnection,
        ):
            connection = NgwConnection(
                id="unreachable-id",
                name="Unreachable",
                url="https://unreachable.example.com",
                auth_config_id=None,
            )
            context = ConnectionDiagnosticContext(connection)
            check = certificate.CertificateCheck(connection)
            result = check.execute(
                context,
                cast("QgsNgwConnection", None),
                QgsFeedback(),
                lambda update: None,
            )

        self.assertEqual(result.state, ConnectionCheckState.FAILURE)

    def test_certificate_check_reports_ignored_ssl_errors(self) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks import (
            certificate,
        )

        ssl_error = SimpleNamespace(
            error=lambda: SimpleNamespace(
                name="SelfSignedCertificate",
                value=9,
            ),
            errorString=lambda: "The certificate is self-signed",
        )

        class _IgnoredSslConnection:
            def __init__(self, connection, *, log_network) -> None:
                del connection, log_network

            def get(
                self,
                url,
                *,
                feedback,
                ssl_verification_callback,
            ) -> None:
                del url, feedback
                ssl_verification_callback(
                    SimpleNamespace(
                        errors=(ssl_error,),
                        was_performed=True,
                    )
                )

        with patch.object(
            certificate,
            "QgsNgwConnection",
            _IgnoredSslConnection,
        ), patch.object(certificate, "QgsApplication", _Application):
            connection = NgwConnection(
                id="ignored-ssl-id",
                name="Ignored SSL",
                url="https://untrusted.example.com",
                auth_config_id=None,
            )
            result = certificate.CertificateCheck(connection).execute(
                ConnectionDiagnosticContext(connection),
                cast("QgsNgwConnection", None),
                QgsFeedback(),
                lambda update: None,
            )

        self.assertEqual(result.state, ConnectionCheckState.WARNING)
        self.assertIsNotNone(result.issue)
        assert result.issue is not None
        self.assertIn(
            "SelfSignedCertificate (9): The certificate is self-signed",
            result.issue.technical_details or "",
        )

    def test_certificate_check_rejects_ssl_handshake_errors(self) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks import (
            certificate,
        )
        from nextgis_connect.platform.qgis.errors import ErrorCode, NgwError

        ssl_error = SimpleNamespace(
            error=lambda: SimpleNamespace(
                name="CertificateUntrusted",
                value=10,
            ),
            errorString=lambda: "The root certificate is untrusted",
        )

        class _RejectedSslConnection:
            def __init__(self, connection, *, log_network) -> None:
                del connection, log_network

            def get(
                self,
                url,
                *,
                feedback,
                ssl_verification_callback,
            ) -> None:
                del url, feedback
                ssl_verification_callback(
                    SimpleNamespace(
                        errors=(ssl_error,),
                        was_performed=True,
                    )
                )
                raise NgwError(
                    code=ErrorCode.SslHandshakeError,
                    detail="SSL handshake failed",
                )

        with patch.object(
            certificate,
            "QgsNgwConnection",
            _RejectedSslConnection,
        ):
            connection = NgwConnection(
                id="rejected-ssl-id",
                name="Rejected SSL",
                url="https://untrusted.example.com",
                auth_config_id=None,
            )
            result = certificate.CertificateCheck(connection).execute(
                ConnectionDiagnosticContext(connection),
                cast("QgsNgwConnection", None),
                QgsFeedback(),
                lambda update: None,
            )

        self.assertEqual(result.state, ConnectionCheckState.FAILURE)
        self.assertIsNotNone(result.issue)
        assert result.issue is not None
        self.assertIn(
            "CertificateUntrusted (10): The root certificate is untrusted",
            result.issue.technical_details or "",
        )

    def test_certificate_check_warns_when_verification_is_unavailable(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks import (
            certificate,
        )

        class _UnverifiedConnection:
            def __init__(self, connection, *, log_network) -> None:
                del connection, log_network

            def get(
                self,
                url,
                *,
                feedback,
                ssl_verification_callback,
            ) -> None:
                del url, feedback
                ssl_verification_callback(
                    SimpleNamespace(errors=(), was_performed=False)
                )

        with patch.object(
            certificate,
            "QgsNgwConnection",
            _UnverifiedConnection,
        ), patch.object(certificate, "QgsApplication", _Application):
            connection = NgwConnection(
                id="unverified-ssl-id",
                name="Unverified SSL",
                url="https://unverified.example.com",
                auth_config_id=None,
            )
            result = certificate.CertificateCheck(connection).execute(
                ConnectionDiagnosticContext(connection),
                cast("QgsNgwConnection", None),
                QgsFeedback(),
                lambda update: None,
            )

        self.assertEqual(result.state, ConnectionCheckState.WARNING)
        self.assertEqual(
            result.description,
            "The server certificate could not be independently verified.",
        )

    def test_proxy_settings_are_formatted_as_single_log_message(self) -> None:
        from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
            ProxySettings,
        )

        proxy_settings = ProxySettings(
            enabled=True,
            host="proxy.example.com",
            port="3128",
            proxy_type="HttpProxy",
            user="demo",
            auth_config_id="auth-1",
            no_proxy_urls="localhost,127.0.0.1",
            has_password=True,
        )

        self.assertEqual(
            proxy_settings.to_debug_message(),
            "QGIS proxy: enabled=True type=HttpProxy host=proxy.example.com port=3128 user=demo authcfg=auth-1 password_set=True no_proxy=localhost,127.0.0.1",
        )

    def test_title_parser_extracts_ngw_header_title(self) -> None:
        html = """
        <html>
            <body>
                <div class="ngw-pyramid-layout-header">
                    <div class="text">Demo Web GIS</div>
                </div>
            </body>
        </html>
        """

        self.assertEqual(
            NgwServerTitleParser.extract_title(html),
            "Demo Web GIS",
        )

    def test_title_parser_extracts_og_site_name(self) -> None:
        html = """
        <html>
            <head>
                <title>Main resource group | Answer is 42!</title>
                <meta property="og:site_name" content="Answer is 42!" />
            </head>
        </html>
        """

        self.assertEqual(
            NgwServerTitleParser.extract_title(html),
            "Answer is 42!",
        )

    def test_title_parser_returns_none_without_header(self) -> None:
        self.assertIsNone(
            NgwServerTitleParser.extract_title(
                "<html><body><div class='content'>No title</div></body></html>"
            )
        )

    def test_plugin_repository_parser_returns_latest_plugin_version(
        self,
    ) -> None:
        payload = b"""
        <plugins>
            <pyqgis_plugin name="NextGIS Connect" version="3.5.0">
                <file_name>nextgis_connect</file_name>
            </pyqgis_plugin>
            <pyqgis_plugin name="NextGIS Connect" version="3.6.1">
                <file_name>nextgis_connect</file_name>
            </pyqgis_plugin>
            <pyqgis_plugin name="Other plugin" version="9.9.9">
                <file_name>other_plugin</file_name>
            </pyqgis_plugin>
        </plugins>
        """

        self.assertEqual(
            QgisPluginRepositoryParser.latest_version(payload),
            "3.6.1",
        )

    def test_suggested_connection_name_uses_expected_fallbacks(self) -> None:
        self.assertEqual(
            suggested_connection_name("https://demo.nextgis.com"),
            "demo",
        )
        self.assertEqual(
            suggested_connection_name("https://example.com"),
            "example.com",
        )

    def test_current_user_expectation_requires_guest_without_auth(
        self,
    ) -> None:
        expectation = CurrentUserExpectation.from_connection(
            NgwConnection(
                id="guest-id",
                name="Guest",
                url="https://demo.nextgis.com",
                auth_config_id=None,
            )
        )

        self.assertTrue(expectation.expects_guest)
        self.assertEqual(expectation.expected_keyname, "guest")
        self.assertTrue(expectation.matches("guest"))
        self.assertFalse(expectation.matches("admin"))

    def test_current_user_expectation_requires_non_guest_with_auth(
        self,
    ) -> None:
        expectation = CurrentUserExpectation(
            expects_guest=False,
            expected_keyname="administrator",
        )

        self.assertFalse(expectation.matches("guest"))
        self.assertTrue(expectation.matches("administrator"))
        self.assertTrue(expectation.matches("another_user"))

    def test_root_resource_check_explains_missing_web_gis_address(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.root_resource import (
            RootResourceAccessCheck,
        )
        from nextgis_connect.platform.qgis.errors import ErrorCode, NgwError

        class _NotFoundConnection:
            def get(self, url, *, feedback):
                del url, feedback
                raise NgwError(code=ErrorCode.NotFound)

        connection = NgwConnection(
            id="not-found-id",
            name="Missing Web GIS",
            url="https://missing.example.com",
            auth_config_id=None,
        )
        result = RootResourceAccessCheck(connection).execute(
            ConnectionDiagnosticContext(connection),
            cast("QgsNgwConnection", _NotFoundConnection()),
            QgsFeedback(),
            lambda update: None,
        )

        self.assertEqual(result.state, ConnectionCheckState.FAILURE)
        self.assertIsNotNone(result.issue)
        assert result.issue is not None
        self.assertEqual(
            result.issue.details,
            "Web GIS was not found at the specified address.",
        )
        self.assertEqual(
            result.issue.resolution,
            "Check the Web GIS URL and run the verification again.",
        )

    def test_download_check_reports_enabled_lunkwill_setting(self) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.download import (
            DownloadCheck,
        )

        class _Connection:
            def get(self, url, *, feedback):
                del url, feedback
                return {"lunkwill.enabled": True}

        connection = NgwConnection(
            id="test-id",
            name="Test",
            url="https://example.com",
            auth_config_id=None,
        )
        result = DownloadCheck(connection).execute(
            ConnectionDiagnosticContext(connection),
            cast("QgsNgwConnection", _Connection()),
            QgsFeedback(),
            lambda update: None,
        )

        self.assertEqual(result.state, ConnectionCheckState.SUCCESS)
        self.assertEqual(
            result.description,
            "Lunkwill is enabled in the server settings.",
        )

    def test_download_check_reports_disabled_lunkwill_setting(self) -> None:
        from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.download import (
            DownloadCheck,
        )

        class _Connection:
            def get(self, url, *, feedback):
                del url, feedback
                return {"lunkwill": {"enabled": False}}

        connection = NgwConnection(
            id="test-id",
            name="Test",
            url="https://example.com",
            auth_config_id=None,
        )
        result = DownloadCheck(connection).execute(
            ConnectionDiagnosticContext(connection),
            cast("QgsNgwConnection", _Connection()),
            QgsFeedback(),
            lambda update: None,
        )

        self.assertEqual(result.state, ConnectionCheckState.WARNING)
        self.assertEqual(
            result.description,
            "Lunkwill is disabled or missing in the server settings.",
        )
        self.assertEqual(
            result.issue.details,
            "Long-running server operations may be processed synchronously.",
        )

    def test_qgs_ngw_connection_accepts_connection_object(self) -> None:
        try:
            from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
                QgsNgwConnection,
            )
        except ImportError as error:
            self.skipTest(str(error))

        connection = NgwConnection(
            id="temp-id",
            name="Temporary",
            url="https://sandbox.nextgis.com",
            auth_config_id=None,
        )

        ngw_connection = QgsNgwConnection(connection)

        self.assertEqual(ngw_connection.connection, connection)
        self.assertEqual(ngw_connection.server_url, connection.url)
        self.assertEqual(ngw_connection.connection_id, connection.id)


def test_diagnostics_dialog_starts_when_requested(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    from nextgis_connect.legacy.ngw_connection.presentation.diagnostics import (
        dialog as diagnostics_dialog,
    )

    monkeypatch.setattr(
        diagnostics_dialog,
        "NgwConnectionDiagnostics",
        _FakeDiagnosticsController,
    )
    dialog = diagnostics_dialog.NgwConnectionDiagnosticsDialog(
        SimpleNamespace(name="Demo Web GIS"),
        start_immediately=True,
    )

    controller = cast(_FakeDiagnosticsController, dialog._controller)
    assert controller.is_started
    dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
