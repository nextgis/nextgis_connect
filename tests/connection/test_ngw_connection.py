import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch, sentinel
from urllib.parse import quote

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from nextgis_connect.ngw_connection import NgwConnection
from tests.ng_connect_testcase import NgConnectTestCase, TestConnection


class TestNgwConnection(NgConnectTestCase):
    def setUp(self) -> None:
        self.ngw_connection = NgwConnection(
            id=sentinel.CONNECTION_ID,
            name=sentinel.CONNECTION_NAME,
            url=sentinel.NGW_URL,
            auth_config_id=sentinel.AUTH_CONFIG_ID,
        )

    @patch.object(QgsApplication, "authManager")
    def test_method_with_auth_config(self, mock_auth_manager):
        mock_auth_manager.return_value.configAuthMethodKey.return_value = (
            "OAuth2"
        )
        self.assertEqual(self.ngw_connection.method, "OAuth2")

    def test_method_without_auth_config(self):
        connection = replace(self.ngw_connection, auth_config_id=None)
        self.assertEqual(connection.method, "")

    def test_domain_uuid(self):
        netloc = "demo.nextgis.com"
        http_connection = replace(self.ngw_connection, url=f"http://{netloc}")
        https_connection = replace(
            self.ngw_connection, url=f"https://{netloc}"
        )
        self.assertEqual(
            http_connection.domain_uuid, https_connection.domain_uuid
        )

    def test_update_network_request_guest(self):
        connection = self.connection(TestConnection.SandboxGuest)
        url = f"{connection.url}/api/component/auth/current_user"
        request_before = QNetworkRequest(QUrl(url))
        request_after = QNetworkRequest(QUrl(url))
        is_updated = connection.update_network_request(request_after)
        self.assertFalse(is_updated)
        self.assertEqual(request_before, request_after)

    def test_update_network_request_login(self):
        connection = self.connection(TestConnection.SandboxWithLogin)
        url = f"{connection.url}/api/component/auth/current_user"
        request_before = QNetworkRequest(QUrl(url))
        request = QNetworkRequest(QUrl(url))
        is_updated = connection.update_network_request(request)
        self.assertTrue(is_updated)
        self.assertNotEqual(request_before, request)
        self.assertTrue(
            request.rawHeader(b"Authorization").startsWith(b"Basic")
        )

    def test_update_uri_config_for_another_domain(self):
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        for key in ("path", "url"):
            config_original = {key: "http://example.com"}
            config = config_original.copy()
            is_updated = connection.update_uri_config(config)
            self.assertFalse(is_updated)
            self.assertEqual(config, config_original)

    @patch.object(QgsApplication, "authManager")
    def test_update_uri_config_without_expand_oauth(self, mock_auth_manager):
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        url = f"{connection.url}/api/component/auth/current_user"

        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "OAuth2"

        for key in ("path", "url"):
            config_original = {key: url}
            config = config_original.copy()
            is_updated = connection.update_uri_config(
                config, workaround_for_email=True
            )
            self.assertTrue(is_updated)
            self.assertNotEqual(config, config_original)
            self.assertIn("authcfg", config)
            self.assertEqual(config[key], config_original[key])
            self.assertEqual(config["authcfg"], connection.auth_config_id)

    @patch.object(QgsApplication, "authManager")
    def test_update_uri_config_without_expand_basic(self, mock_auth_manager):
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        url = f"{connection.url}/api/component/auth/current_user"
        username = "username"
        password = "password"

        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"

        mock_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            mock_config,
        )
        mock_config.config.side_effect = (
            lambda key: username if key == "username" else password
        )
        for key in ("path", "url"):
            config_original = {key: url}
            config = config_original.copy()
            is_updated = connection.update_uri_config(
                config, workaround_for_email=True
            )
            self.assertTrue(is_updated)
            self.assertNotEqual(config, config_original)
            self.assertIn("authcfg", config)
            self.assertEqual(config[key], config_original[key])
            self.assertEqual(config["authcfg"], connection.auth_config_id)

    @patch.object(QgsApplication, "authManager")
    def test_update_uri_config_with_expand_login(self, mock_auth_manager):
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        url = f"{connection.url}/api/component/auth/current_user"
        username = "username@example.com"
        password = "password"

        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"

        mock_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            mock_config,
        )
        mock_config.config.side_effect = (
            lambda key: username if key == "username" else password
        )

        for key in ("path", "url"):
            config_original = {key: url}
            config = config_original.copy()
            is_updated = connection.update_uri_config(
                config, workaround_for_email=True
            )
            self.assertTrue(is_updated)
            self.assertNotEqual(config, config_original)
            self.assertNotIn("authcfg", config)
            encoded_username = quote(username)
            encoded_password = quote(password)
            self.assertEqual(
                config[key],
                url.replace(
                    "://", f"://{encoded_username}:{encoded_password}@"
                ),
            )

    @patch.object(QgsApplication, "authManager")
    def test_update_uri_config_with_expand_password(self, mock_auth_manager):
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        url = f"{connection.url}/api/component/auth/current_user"
        username = "username"

        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"

        mock_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            mock_config,
        )
        mock_config.config.side_effect = (
            lambda key: username if key == "username" else password
        )

        for key in ("path", "url"):
            for password in ("p@ssword", "pass word", "p***word"):
                config_original = {key: url}
                config = config_original.copy()
                is_updated = connection.update_uri_config(
                    config, workaround_for_email=True
                )
                self.assertTrue(is_updated)
                self.assertNotEqual(config, config_original)
                self.assertNotIn("authcfg", config)
                encoded_username = quote(username)
                encoded_password = quote(password)
                self.assertEqual(
                    config[key],
                    url.replace(
                        "://", f"://{encoded_username}:{encoded_password}@"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
