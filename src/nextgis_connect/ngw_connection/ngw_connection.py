from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtNetwork import QNetworkRequest

HAS_NGSTD = True
try:
    from ngstd.core import NGRequest
    from ngstd.framework import NGAccess
except ImportError:
    HAS_NGSTD = False


@dataclass(unsafe_hash=True)
class NgwConnection:
    id: str
    name: str
    url: str
    auth_config_id: Optional[str]

    def update_network_request(self, request: QNetworkRequest) -> bool:
        if self.auth_config_id is None:
            return False

        is_succeeded = False
        if HAS_NGSTD and self.auth_config_id == "NextGIS":
            ngaccess = NGAccess.instance()
            if not ngaccess.isUserAuthorized():
                raise Exception

            header_string: str = NGRequest.getAuthHeader(ngaccess.endPoint())
            if not header_string:
                raise Exception

            name, value = header_string.split(": ")
            request.setRawHeader(name.encode(), value.encode())

            is_succeeded = True
        else:
            application = QgsApplication.instance()
            assert application is not None
            auth_manager = application.authManager()
            assert auth_manager is not None
            is_succeeded, _ = auth_manager.updateNetworkRequest(
                request, self.auth_config_id
            )

        return is_succeeded
