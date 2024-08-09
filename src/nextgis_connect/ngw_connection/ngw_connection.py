import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt.QtNetwork import QNetworkRequest


@dataclass(unsafe_hash=True)
class NgwConnection:
    id: str
    name: str
    url: str
    auth_config_id: Optional[str]

    @property
    def method(self) -> str:
        if self.auth_config_id is None:
            return ""

        return QgsApplication.authManager().configAuthMethodKey(
            self.auth_config_id
        )

    @property
    def domain_uuid(self) -> str:
        domain = urlparse(self.url).netloc
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, domain))

    def update_network_request(self, request: QNetworkRequest) -> bool:
        if self.auth_config_id is None:
            return False

        auth_manager = QgsApplication.authManager()
        is_succeeded, _ = auth_manager.updateNetworkRequest(
            request, self.auth_config_id
        )

        return is_succeeded

    def update_uri_config(
        self, params: Dict[str, Any], *, workaround: bool = False
    ) -> bool:
        if self.auth_config_id is None or (
            self.url not in params.get("url", params.get("path", ""))
        ):
            return True

        if not workaround or self.method != "Basic":
            params["authcfg"] = self.auth_config_id
            return True

        config = QgsAuthMethodConfig()

        is_loaded = QgsApplication.authManager().loadAuthenticationConfig(
            self.auth_config_id, config, full=True
        )[0]

        if not is_loaded:
            return False

        username = config.config("username")
        if "@" not in username:
            params["authcfg"] = self.auth_config_id
            return True

        username = quote(username)
        password = quote(config.config("password"))

        params["path"] = params["path"].replace(
            "://", f"://{username}:{password}@"
        )

        return True
