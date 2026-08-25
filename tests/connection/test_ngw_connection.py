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
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, sentinel
from urllib.parse import quote

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsNetworkRequestParameters,
)
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from nextgis_connect.legacy.ngw_connection import NgwConnection
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

    def test_url_with_credentials_without_auth_config(self):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
            auth_config_id=None,
        )

        self.assertEqual(
            connection.url_with_credentials(),
            "https://demo.nextgis.com",
        )

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_for_basic_auth(self, mock_auth_manager):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"
        auth_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_config.config.side_effect = {
            "username": "user@example.com",
            "password": "p/a:ss word",
        }.__getitem__
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            auth_config,
        )

        authenticated_url = connection.url_with_credentials(
            "https://demo.nextgis.com/resource/7155?example=true"
        )

        self.assertEqual(
            authenticated_url,
            "https://user%40example.com:p%2Fa%3Ass%20word@"
            "demo.nextgis.com/resource/7155?example=true",
        )

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_replaces_existing_userinfo(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"
        auth_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_config.config.side_effect = {
            "username": "new-user",
            "password": "new-password",
        }.__getitem__
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            auth_config,
        )

        authenticated_url = connection.url_with_credentials(
            "https://old:secret@demo.nextgis.com/resource/7155"
        )

        self.assertEqual(
            authenticated_url,
            "https://new-user:new-password@demo.nextgis.com/resource/7155",
        )

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_ignores_other_domain(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"

        authenticated_url = connection.url_with_credentials(
            "https://example.com/resource/7155"
        )

        self.assertEqual(
            authenticated_url,
            "https://example.com/resource/7155",
        )
        auth_manager.loadAuthenticationConfig.assert_not_called()

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_ignores_scheme_downgrade(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"
        target_url = "http://demo.nextgis.com/resource/7155"

        authenticated_url = connection.url_with_credentials(target_url)

        self.assertEqual(authenticated_url, target_url)
        auth_manager.loadAuthenticationConfig.assert_not_called()

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_accepts_explicit_default_port(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"
        auth_config = MagicMock(spec=QgsAuthMethodConfig)
        auth_config.config.side_effect = {
            "username": "user",
            "password": "password",
        }.__getitem__
        auth_manager.loadAuthenticationConfig.return_value = (
            True,
            auth_config,
        )

        authenticated_url = connection.url_with_credentials(
            "https://demo.nextgis.com:443/resource/7155"
        )

        self.assertEqual(
            authenticated_url,
            "https://user:password@demo.nextgis.com:443/resource/7155",
        )

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_ignores_other_port(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "Basic"
        target_url = "https://demo.nextgis.com:444/resource/7155"

        authenticated_url = connection.url_with_credentials(target_url)

        self.assertEqual(authenticated_url, target_url)
        auth_manager.loadAuthenticationConfig.assert_not_called()

    @patch.object(QgsApplication, "authManager")
    def test_url_with_credentials_ignores_non_basic_auth(
        self,
        mock_auth_manager,
    ):
        connection = replace(
            self.ngw_connection,
            url="https://demo.nextgis.com",
        )
        auth_manager = mock_auth_manager.return_value
        auth_manager.configAuthMethodKey.return_value = "OAuth2"

        authenticated_url = connection.url_with_credentials()

        self.assertEqual(authenticated_url, connection.url)
        auth_manager.loadAuthenticationConfig.assert_not_called()

    def test_domain_uuid(self):
        netloc = "demo.nextgis.com"
        http_connection = replace(self.ngw_connection, url=f"http://{netloc}")
        https_connection = replace(
            self.ngw_connection, url=f"https://{netloc}"
        )
        self.assertEqual(
            http_connection.domain_uuid, https_connection.domain_uuid
        )

    def test_suggested_id_for_url_uses_domain_uuid(self):
        url = "https://demo.nextgis.com/resource/1"

        self.assertEqual(
            NgwConnection.suggested_id_for_url(url, []),
            NgwConnection.domain_uuid_for_url(url),
        )

    def test_suggested_id_for_url_uses_fallback_on_domain_collision(self):
        url = "https://demo.nextgis.com/"
        domain_uuid = NgwConnection.domain_uuid_for_url(url)

        self.assertEqual(
            NgwConnection.suggested_id_for_url(
                url,
                [domain_uuid],
                fallback_id="existing-random-id",
            ),
            "existing-random-id",
        )

    def test_suggested_id_for_url_generates_uuid_on_full_collision(self):
        url = "https://demo.nextgis.com/"
        domain_uuid = NgwConnection.domain_uuid_for_url(url)

        connection_id = NgwConnection.suggested_id_for_url(
            url,
            [domain_uuid, "existing-random-id"],
            fallback_id="existing-random-id",
        )

        self.assertNotIn(connection_id, [domain_uuid, "existing-random-id"])
        uuid.UUID(connection_id)

    @patch(
        "nextgis_connect.legacy.ngw_connection.domain.connection."
        "_plugin_version",
        return_value="4.0.0",
    )
    def test_update_network_request_guest(self, mock_plugin_version):
        connection = self.connection(TestConnection.SandboxGuest)
        url = f"{connection.url}/api/component/auth/current_user"
        request_after = QNetworkRequest(QUrl(url))
        with patch(
            "nextgis_connect.legacy.ngw_connection.domain.connection."
            "QgsNetworkAccessManager.instance"
        ) as mock_network_access_manager:
            cookie_jar = (
                mock_network_access_manager.return_value.cookieJar.return_value
            )
            is_updated = connection.update_network_request(request_after)

        self.assertFalse(is_updated)
        self._assert_qgis_locale(request_after, cookie_jar, url)
        user_agent_suffix_attribute = self._user_agent_suffix_attribute()
        if user_agent_suffix_attribute is not None:
            self.assertEqual(
                request_after.attribute(user_agent_suffix_attribute),
                "NextGIS-Connect/4.0.0",
            )

    @patch(
        "nextgis_connect.legacy.ngw_connection.domain.connection."
        "_plugin_version",
        return_value="4.0.0",
    )
    def test_update_network_request_login(self, mock_plugin_version):
        connection = self.connection(TestConnection.SandboxWithLogin)
        url = f"{connection.url}/api/component/auth/current_user"
        request_before = QNetworkRequest(QUrl(url))
        request = QNetworkRequest(QUrl(url))
        with patch(
            "nextgis_connect.legacy.ngw_connection.domain.connection."
            "QgsNetworkAccessManager.instance"
        ) as mock_network_access_manager:
            cookie_jar = (
                mock_network_access_manager.return_value.cookieJar.return_value
            )
            is_updated = connection.update_network_request(request)
        self.assertTrue(is_updated)
        self.assertNotEqual(request_before, request)
        self.assertTrue(
            request.rawHeader(b"Authorization").startsWith(b"Basic")
        )
        self._assert_qgis_locale(request, cookie_jar, url)
        user_agent_suffix_attribute = self._user_agent_suffix_attribute()
        if user_agent_suffix_attribute is not None:
            self.assertEqual(
                request.attribute(user_agent_suffix_attribute),
                "NextGIS-Connect/4.0.0",
            )

    def test_update_network_request_skips_user_agent_suffix_for_another_domain(
        self,
    ) -> None:
        connection = replace(
            self.ngw_connection, url="http://demo.nextgis.com"
        )
        request = QNetworkRequest(QUrl("http://example.com"))
        is_updated = connection.update_network_request(request)
        self.assertFalse(is_updated)

        user_agent_suffix_attribute = self._user_agent_suffix_attribute()
        if user_agent_suffix_attribute is not None:
            self.assertIsNone(request.attribute(user_agent_suffix_attribute))

    def test_update_user_agent_suffix_uses_plugin_version(self) -> None:
        from nextgis_connect.legacy.ngw_connection.domain import (
            connection as connection_module,
        )

        class FakeRequest:
            attribute = None
            value = None

            def setAttribute(self, attribute, value) -> None:
                self.attribute = attribute
                self.value = value

        fake_attribute = getattr(
            QNetworkRequest.Attribute.UserMax,
            "value",
            QNetworkRequest.Attribute.UserMax,
        )
        fake_request_attributes = SimpleNamespace(
            AttributeUserAgentSuffix=fake_attribute
        )
        fake_request = FakeRequest()

        fake_request_parameters = SimpleNamespace(
            RequestAttributes=fake_request_attributes
        )
        with patch.object(
            connection_module,
            "QgsNetworkRequestParameters",
            fake_request_parameters,
        ):
            with patch.object(
                connection_module,
                "_plugin_version",
                return_value="4.0.0",
            ):
                connection_module.update_user_agent_suffix(fake_request)

        self.assertEqual(
            fake_request.attribute,
            QNetworkRequest.Attribute(fake_attribute),
        )
        self.assertEqual(fake_request.value, "NextGIS-Connect/4.0.0")

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

    @staticmethod
    def _user_agent_suffix_attribute():
        request_attributes = getattr(
            QgsNetworkRequestParameters, "RequestAttributes", None
        )
        if request_attributes is None:
            return None

        user_agent_suffix_flag = getattr(
            request_attributes,
            "AttributeUserAgentSuffix",
            None,
        )
        if user_agent_suffix_flag is None:
            return None

        return QNetworkRequest.Attribute(user_agent_suffix_flag)

    def _assert_qgis_locale(self, request, cookie_jar, url: str) -> None:
        application = QgsApplication.instance()
        assert application is not None
        language = application.locale().replace("-", "_").split("_", 1)[0]
        language = (
            language.lower() if language.lower() not in ("", "c") else "en"
        )

        self.assertEqual(
            request.rawHeader(b"Accept-Language"), language.encode()
        )
        cookie_jar.setCookiesFromUrl.assert_called_once()
        cookies, cookie_url = cookie_jar.setCookiesFromUrl.call_args.args
        self.assertEqual(cookie_url, QUrl(url))
        self.assertEqual(len(cookies), 1)
        self.assertEqual(bytes(cookies[0].name()), b"ngw_slg")
        self.assertEqual(bytes(cookies[0].value()), language.encode())
        self.assertEqual(cookies[0].path(), "/")

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
        mock_config.config.side_effect = lambda key: (
            username if key == "username" else password
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
        mock_config.config.side_effect = lambda key: (
            username if key == "username" else password
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
        mock_config.config.side_effect = lambda key: (
            username if key == "username" else password
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
