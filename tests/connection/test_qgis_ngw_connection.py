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

from qgis.PyQt.QtCore import QByteArray
from qgis.PyQt.QtNetwork import QNetworkReply

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
