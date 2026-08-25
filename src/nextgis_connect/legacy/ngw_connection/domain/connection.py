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

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import quote, urlparse

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsNetworkAccessManager,
    QgsNetworkRequestParameters,
)
from qgis.PyQt.QtNetwork import QNetworkCookie, QNetworkRequest

from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.constants import PLUGIN_NAME


def _plugin_version() -> str:
    return NgConnectInterface.instance().version


def update_user_agent_suffix(request: QNetworkRequest) -> None:
    request_attributes = getattr(
        QgsNetworkRequestParameters, "RequestAttributes", None
    )
    if request_attributes is None:
        return

    user_agent_suffix_flag = getattr(
        request_attributes,
        "AttributeUserAgentSuffix",
        None,
    )
    if user_agent_suffix_flag is None:
        return

    user_agent_suffix_attribute = QNetworkRequest.Attribute(
        user_agent_suffix_flag
    )

    version = _plugin_version()
    if version == "":
        return

    plugin_user_agent = PLUGIN_NAME.replace(" ", "-") + "/" + version
    request.setAttribute(user_agent_suffix_attribute, plugin_user_agent)


def update_qgis_locale(request: QNetworkRequest) -> None:
    """Make NGW localize this request using the active QGIS language."""
    application = QgsApplication.instance()
    locale = application.locale() if application is not None else "en"
    language = locale.replace("-", "_").split("_", maxsplit=1)[0].lower()
    if language in ("", "c"):
        language = "en"

    request.setRawHeader(b"Accept-Language", language.encode("ascii"))

    # NGW gives this cookie precedence over Accept-Language and user language.
    locale_cookie = QNetworkCookie(b"ngw_slg", language.encode("ascii"))
    locale_cookie.setPath("/")
    cookie_jar = QgsNetworkAccessManager.instance().cookieJar()
    cookie_jar.setCookiesFromUrl([locale_cookie], request.url())


@dataclass(frozen=True)
class NgwConnection:
    NEXTGIS_DOMAIN = ".nextgis.com"

    id: str
    name: str
    url: str
    auth_config_id: Optional[str]
    old_connection_ids: Tuple[str, ...] = ()

    @property
    def method(self) -> str:
        if self.auth_config_id is None:
            return ""

        return QgsApplication.authManager().configAuthMethodKey(
            self.auth_config_id
        )

    @property
    def domain_uuid(self) -> str:
        return self.domain_uuid_for_url(self.url)

    def update_network_request(self, request: QNetworkRequest) -> bool:
        request_host = urlparse(request.url().toString()).netloc
        connection_host = urlparse(self.normalize_url(self.url)).netloc
        if request_host != connection_host:
            return False

        update_user_agent_suffix(request)
        update_qgis_locale(request)

        if self.auth_config_id is None:
            return False

        auth_manager = QgsApplication.authManager()
        is_succeeded, _ = auth_manager.updateNetworkRequest(
            request, self.auth_config_id
        )

        return is_succeeded

    def update_uri_config(
        self,
        params: Dict[Optional[str], Any],
        *,
        workaround_for_email: bool = False,
    ) -> bool:
        if self.auth_config_id is None or (
            self.url not in params.get("url", params.get("path", ""))
        ):
            return False

        if not workaround_for_email or self.method != "Basic":
            params["authcfg"] = self.auth_config_id
            return True

        is_loaded, config = (
            QgsApplication.authManager().loadAuthenticationConfig(
                self.auth_config_id,
                QgsAuthMethodConfig(),
                full=True,
            )
        )

        if not is_loaded:
            return False

        username = config.config("username")
        password = config.config("password")
        quoted_username = quote(username)
        quoted_password = quote(password)

        if username == quoted_username and password == quoted_password:
            params["authcfg"] = self.auth_config_id
            return True

        key = "path" if "path" in params else "url"
        params[key] = params[key].replace(
            "://", f"://{quoted_username}:{quoted_password}@"
        )

        return True

    def url_with_credentials(self, url: Optional[str] = None) -> str:
        """Embed Basic credentials into a URL handled by this connection."""
        target_url = self.url if url is None else url
        if (
            self.auth_config_id is None
            or self.method != "Basic"
            or not self._handles_url(target_url)
        ):
            return target_url

        is_loaded, config = (
            QgsApplication.authManager().loadAuthenticationConfig(
                self.auth_config_id,
                QgsAuthMethodConfig(),
                full=True,
            )
        )
        if not is_loaded:
            return target_url

        username = quote(config.config("username"), safe="")
        password = quote(config.config("password"), safe="")
        parse_result = urlparse(target_url)
        host = parse_result.netloc.rsplit("@", maxsplit=1)[-1]
        authenticated_host = f"{username}:{password}@{host}"
        return parse_result._replace(netloc=authenticated_host).geturl()

    def _handles_url(self, url: str) -> bool:
        target = urlparse(url)
        connection = urlparse(self.normalize_url(self.url))
        try:
            target_port = target.port
            connection_port = connection.port
        except ValueError:
            return False

        if target_port is None:
            target_port = self._default_port(target.scheme)
        if connection_port is None:
            connection_port = self._default_port(connection.scheme)

        return (
            target.scheme.lower() == connection.scheme.lower()
            and target.hostname == connection.hostname
            and target_port == connection_port
        )

    @staticmethod
    def _default_port(scheme: str) -> Optional[int]:
        return {
            "http": 80,
            "https": 443,
        }.get(scheme.lower())

    @classmethod
    def normalize_url(cls, url: str) -> str:
        parse_result = urlparse(url)
        if parse_result.scheme == "":
            parse_result = urlparse("https://" + url)

        scheme = parse_result.scheme
        base_url = parse_result.netloc

        # Force https regardless of what user has selected, but only for cloud
        # connections.
        if base_url.endswith(cls.NEXTGIS_DOMAIN) and scheme != "https":
            scheme = "https"

        if not scheme or not base_url:
            return url

        return f"{scheme}://{base_url}"

    @classmethod
    def domain_uuid_for_url(cls, url: str) -> str:
        domain = urlparse(cls.normalize_url(url)).netloc
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, domain))

    def matches_id(self, connection_id: str) -> bool:
        return (
            connection_id == self.id
            or connection_id in self.old_connection_ids
        )

    @classmethod
    def suggested_id_for_url(
        cls,
        url: str,
        existing_connection_ids: Iterable[str],
        *,
        fallback_id: Optional[str] = None,
    ) -> str:
        existing_ids = set(existing_connection_ids)
        connection_id = cls.domain_uuid_for_url(url)
        if connection_id not in existing_ids:
            return connection_id

        if fallback_id is not None and fallback_id not in existing_ids:
            return fallback_id

        while True:
            connection_id = str(uuid.uuid4())
            if connection_id not in existing_ids:
                return connection_id
