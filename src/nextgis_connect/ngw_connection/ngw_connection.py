import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from qgis.core import QgsApplication
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
