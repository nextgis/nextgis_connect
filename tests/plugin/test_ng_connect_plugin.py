from nextgis_connect.utils import SupportStatus, is_version_supported
from tests.ng_connect_testcase import NgConnectTestCase


class TestNgConnectPlugin(NgConnectTestCase):
    def test_deprecated(self) -> None:
        self.assertEqual(
            is_version_supported("5.0.0"),
            SupportStatus.SUPPORTED,
            "The old search API needs to be removed",
        )
