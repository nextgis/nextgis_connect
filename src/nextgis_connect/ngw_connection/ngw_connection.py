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
    def domain_uuid(self) -> str:
        domain = urlparse(self.url).netloc
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, domain))

    def update_network_request(self, request: QNetworkRequest) -> bool:
        if self.auth_config_id is None:
            return False

        application = QgsApplication.instance()
        assert application is not None
        auth_manager = application.authManager()
        assert auth_manager is not None
        is_succeeded, _ = auth_manager.updateNetworkRequest(
            request, self.auth_config_id
        )

        return is_succeeded
