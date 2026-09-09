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
from unittest.mock import Mock, patch

from qgis.PyQt.QtCore import QByteArray, QTimer
from qgis.PyQt.QtNetwork import QNetworkReply, QSslError

from nextgis_connect.platform.qgis.errors import NgwError
from tests.ng_connect_testcase import NgConnectTestCase, TestConnection


class TestQgsNgwConnection(NgConnectTestCase):
    def setUp(self) -> None:
        super().setUp()

        from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
            NgwServerFeature,
            QgsNgwConnection,
        )

        self.ngw_feature_class = NgwServerFeature
        self.qgs_ngw_connection_class = QgsNgwConnection
        self.qgs_ngw_connection_class.clear_cached_ngw_components()

    def tearDown(self) -> None:
        self.qgs_ngw_connection_class.clear_cached_ngw_components()
        super().tearDown()

    def test_get_ngw_components_is_cached_by_connection_id(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        components = {"nextgisweb": "4.9.0.dev1", "auth": "1.0.0"}

        with patch.object(
            self.qgs_ngw_connection_class,
            "get",
            autospec=True,
            return_value=components,
        ) as mock_get:
            first_connection = self.qgs_ngw_connection_class(connection_id)
            second_connection = self.qgs_ngw_connection_class(connection_id)

            self.assertEqual(first_connection.get_ngw_components(), components)
            self.assertEqual(
                second_connection.get_ngw_components(), components
            )

        self.assertEqual(mock_get.call_count, 1)

    def test_invalidate_cached_ngw_components_forces_refetch(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        first_components = {"nextgisweb": "4.9.0.dev1"}
        second_components = {"nextgisweb": "5.0.0.dev1"}

        with patch.object(
            self.qgs_ngw_connection_class,
            "get",
            autospec=True,
            side_effect=[first_components, second_components],
        ) as mock_get:
            ngw_connection = self.qgs_ngw_connection_class(connection_id)

            self.assertEqual(
                ngw_connection.get_ngw_components(), first_components
            )

            ngw_connection.invalidate_cached_ngw_components()

            self.assertEqual(
                ngw_connection.get_ngw_components(), second_components
            )

        self.assertEqual(mock_get.call_count, 2)

    def test_request_error_contains_absolute_url(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        connection = self.qgs_ngw_connection_class(connection_id)
        request_path = "/api/resource/42"
        request_url = f"{connection.server_url.rstrip('/')}{request_path}"
        network_error = NgwError(
            "Connection error",
            is_network_problem=True,
        )

        method_name = "_QgsNgwConnection__request_and_decode"
        with patch.object(
            connection,
            method_name,
            side_effect=network_error,
        ), self.assertRaises(NgwError) as error_context:
            connection.get(request_path)

        error = error_context.exception
        error_notes = getattr(error, "__notes__", ())
        self.assertTrue(
            f"URL: {request_url}" in error_notes
            or f"URL: {request_url}" in str(error)
        )

    def test_get_reports_ssl_verification(self) -> None:
        from nextgis_connect.legacy.ngw.qgis import qgis_ngw_connection

        class _FinishedReply(QNetworkReply):
            def abort(self) -> None:
                pass

            def readData(self, maxlen):
                del maxlen
                return b""

        ssl_error = QSslError(QSslError.SslError.SelfSignedCertificate)
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        connection = self.qgs_ngw_connection_class(connection_id)
        verify_peer_method = "_QgsNgwConnection__verify_peer_certificate"
        verified_with_error = qgis_ngw_connection.SslCertificateVerification(
            (ssl_error,),
            was_performed=True,
        )
        verification_unavailable = (
            qgis_ngw_connection.SslCertificateVerification(
                (),
                was_performed=False,
            )
        )

        cases = (
            (
                "handshake signal",
                [ssl_error],
                verification_unavailable,
                verified_with_error,
            ),
            (
                "peer certificate chain",
                [],
                verified_with_error,
                verified_with_error,
            ),
            (
                "verification unavailable",
                [],
                verification_unavailable,
                verification_unavailable,
            ),
        )
        for source, emitted_errors, fallback, expected in cases:
            with self.subTest(source=source):
                reply = _FinishedReply()

                def finish_request(
                    reply=reply,
                    emitted_errors=emitted_errors,
                ) -> None:
                    if emitted_errors:
                        reply.sslErrors.emit(emitted_errors)
                    reply.setFinished(True)
                    reply.finished.emit()

                def start_request(
                    request,
                    reply=reply,
                    finish_request=finish_request,
                ):
                    del request
                    QTimer.singleShot(0, finish_request)
                    return reply

                network_manager = Mock()
                network_manager.get.side_effect = start_request
                ssl_verification_callback = Mock()

                with patch.object(
                    qgis_ngw_connection.QgsNetworkAccessManager,
                    "instance",
                    return_value=network_manager,
                ), patch.object(
                    qgis_ngw_connection.NgwConnection,
                    "update_network_request",
                    return_value=False,
                ), patch.object(
                    connection,
                    verify_peer_method,
                    return_value=fallback,
                ):
                    connection.get(
                        "/",
                        ssl_verification_callback=ssl_verification_callback,
                    )

                ssl_verification_callback.assert_called_once()
                verification = ssl_verification_callback.call_args.args[0]
                self.assertEqual(verification, expected)

                # The observer must not retain state after the request.
                reply.sslErrors.emit([ssl_error])
                ssl_verification_callback.assert_called_once()
                reply.deleteLater()

    def test_peer_certificate_verification_uses_hostname_and_excludes_root(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw.qgis import qgis_ngw_connection

        leaf_certificate = Mock()
        leaf_certificate.isSelfSigned.return_value = False
        root_certificate = Mock()
        root_certificate.isSelfSigned.return_value = True
        ssl_error = QSslError(QSslError.SslError.SelfSignedCertificate)
        reply = Mock(spec=QNetworkReply)
        reply.sslConfiguration.return_value.peerCertificateChain.return_value = [
            leaf_certificate,
            root_certificate,
        ]
        reply.url.return_value.host.return_value = "untrusted.example.com"
        verify_peer = vars(self.qgs_ngw_connection_class)[
            "_QgsNgwConnection__verify_peer_certificate"
        ]
        can_verify = "_QgsNgwConnection__can_verify_chain"

        with patch.object(
            self.qgs_ngw_connection_class,
            can_verify,
            return_value=True,
        ), patch.object(
            qgis_ngw_connection.QSslCertificate,
            "verify",
            return_value=[ssl_error],
        ) as verify:
            result = verify_peer(reply)

        verify.assert_called_once_with(
            [leaf_certificate],
            "untrusted.example.com",
        )
        self.assertEqual(result.errors, (ssl_error,))
        self.assertTrue(result.was_performed)

    def test_peer_certificate_verification_reports_unavailable_backend(
        self,
    ) -> None:
        reply = Mock(spec=QNetworkReply)
        reply.sslConfiguration.return_value.peerCertificateChain.return_value = [
            Mock()
        ]
        verify_peer = vars(self.qgs_ngw_connection_class)[
            "_QgsNgwConnection__verify_peer_certificate"
        ]
        can_verify = "_QgsNgwConnection__can_verify_chain"

        with patch.object(
            self.qgs_ngw_connection_class,
            can_verify,
            return_value=False,
        ):
            result = verify_peer(reply)

        self.assertEqual(result.errors, ())
        self.assertFalse(result.was_performed)

    def test_qt5_manual_certificate_verification_requires_openssl(
        self,
    ) -> None:
        from nextgis_connect.legacy.ngw.qgis import qgis_ngw_connection

        can_verify = vars(self.qgs_ngw_connection_class)[
            "_QgsNgwConnection__can_verify_chain"
        ]
        with patch.object(
            qgis_ngw_connection.QSslSocket,
            "supportedFeatures",
            None,
        ), patch.object(
            qgis_ngw_connection.QSslSocket,
            "sslLibraryVersionString",
            side_effect=("SecureTransport", "OpenSSL 1.1.1"),
        ):
            self.assertFalse(can_verify())
            self.assertTrue(can_verify())

    def test_upload_file_passes_declared_mime_type(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        connection = self.qgs_ngw_connection_class(connection_id)
        upload_callback = Mock()

        with patch.object(connection, "put") as mock_put:
            connection.upload_file(
                "/tmp/photo.png",
                upload_callback,
                mime_type="image/png",
            )

        mock_put.assert_called_once_with(
            "/api/component/file_upload/",
            file="/tmp/photo.png",
            headers={"Content-Type": "image/png"},
            feedback=None,
        )

    def test_tus_upload_file_uses_declared_upload_name(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)
        connection = self.qgs_ngw_connection_class(connection_id)
        upload_path = self.create_temp_file(".jpg")
        upload_path.write_bytes(b"jpeg")

        create_reply = Mock()
        create_reply.attribute.return_value = 201
        create_reply.rawHeader.return_value = QByteArray(
            b"/api/component/file_upload/upload-id"
        )
        chunk_reply = Mock()
        chunk_reply.attribute.return_value = 204
        chunk_reply.error.return_value = QNetworkReply.NetworkError.NoError
        request_method = "_QgsNgwConnection__request_rep"

        with patch.object(
            connection,
            request_method,
            side_effect=[(None, create_reply), (None, chunk_reply)],
        ) as mock_request, patch.object(
            connection,
            "get",
            return_value={"id": "upload-id"},
        ):
            connection.tus_upload_file(
                str(upload_path),
                Mock(),
                upload_name="max.jpg",
            )

        create_headers = mock_request.call_args_list[0].kwargs["headers"]
        self.assertEqual(
            create_headers["Upload-Metadata"],
            "name bWF4LmpwZw==",
        )

    def test_reset_model_invalidates_cached_versions(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)

        from nextgis_connect.legacy.tree_widget.model import (
            QNGWResourceTreeModel,
        )

        with patch.object(
            self.qgs_ngw_connection_class,
            "invalidate_cached_ngw_components",
            autospec=True,
        ) as mock_invalidate, patch.object(
            self.qgs_ngw_connection_class,
            "get_version",
            autospec=True,
            return_value="4.9.0.dev1",
        ):
            model = QNGWResourceTreeModel()
            model.resetModel(self.qgs_ngw_connection_class(connection_id))

        self.assertEqual(mock_invalidate.call_count, 1)

    def test_all_features_require_supported_ngw_version(self) -> None:
        from nextgis_connect.legacy.settings import NgConnectSettings
        from nextgis_connect.platform.qgis.utils import (
            SupportStatus,
            is_version_supported,
        )

        settings = NgConnectSettings()
        previous_developer_mode = settings.is_developer_mode
        settings.is_developer_mode = False
        self.addCleanup(
            setattr,
            settings,
            "is_developer_mode",
            previous_developer_mode,
        )

        for feature in self.ngw_feature_class:
            required_version = str(feature.required_version)
            with self.subTest(
                feature=feature.name,
                required_version=required_version,
            ):
                self.assertEqual(
                    is_version_supported(required_version),
                    SupportStatus.SUPPORTED,
                )

    def test_has_support_for_no_geometry_layers_requires_dev6(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)

        versions = {
            "5.4.9": False,
            "5.5.0": True,
        }

        for version, expected in versions.items():
            with self.subTest(version=version), patch.object(
                self.qgs_ngw_connection_class,
                "get",
                autospec=True,
                return_value={"nextgisweb": version},
            ):
                connection = self.qgs_ngw_connection_class(connection_id)

                self.assertEqual(
                    connection.has_support_for_feature(
                        self.ngw_feature_class.NO_GEOMETRY_LAYERS
                    ),
                    expected,
                )

                connection.invalidate_cached_ngw_components()

    def test_has_support_for_no_geometry_layer_versioning_requires_dev8(
        self,
    ) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)

        versions = {
            "5.5.0.dev7": False,
            "5.5.0.dev8": True,
            "5.5.0": True,
        }

        for version, expected in versions.items():
            with self.subTest(version=version), patch.object(
                self.qgs_ngw_connection_class,
                "get",
                autospec=True,
                return_value={"nextgisweb": version},
            ):
                connection = self.qgs_ngw_connection_class(connection_id)

                self.assertEqual(
                    connection.has_support_for_feature(
                        self.ngw_feature_class.NO_GEOMETRY_LAYER_VERSIONING
                    ),
                    expected,
                )

                connection.invalidate_cached_ngw_components()

    def test_has_support_for_required_fields_requires_550(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)

        versions = {
            "5.4.9": False,
            "5.5.0": True,
        }

        for version, expected in versions.items():
            with self.subTest(version=version), patch.object(
                self.qgs_ngw_connection_class,
                "get",
                autospec=True,
                return_value={"nextgisweb": version},
            ):
                connection = self.qgs_ngw_connection_class(connection_id)

                self.assertEqual(
                    connection.has_support_for_feature(
                        self.ngw_feature_class.REQUIRED_FIELDS
                    ),
                    expected,
                )

                connection.invalidate_cached_ngw_components()

    def test_has_support_for_type_requires_550(self) -> None:
        connection_id = self.connection_id(TestConnection.SandboxGuest)

        versions = {
            "5.4.9": False,
            "5.5.0.dev0": True,
        }

        for version, expected in versions.items():
            with self.subTest(version=version), patch.object(
                self.qgs_ngw_connection_class,
                "get",
                autospec=True,
                return_value={"nextgisweb": version},
            ):
                connection = self.qgs_ngw_connection_class(connection_id)

                self.assertEqual(
                    connection.has_support_for_feature(
                        self.ngw_feature_class.JSON_TYPE
                    ),
                    expected,
                )

                connection.invalidate_cached_ngw_components()


if __name__ == "__main__":
    unittest.main()
