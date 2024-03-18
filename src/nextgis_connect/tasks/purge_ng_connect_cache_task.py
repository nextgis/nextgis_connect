from nextgis_connect import utils
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings import NgConnectCacheManager
from nextgis_connect.tasks.ng_connect_task import NgConnectTask
from qgis.core import QgsApplication


class PurgeNgConnectCacheTask(NgConnectTask):
    def __init__(self):
        description = QgsApplication.translate(
            NgConnectInterface.TRANSLATE_CONTEXT,
            "Clearing NextGIS Connect cache",
        )
        super().__init__(description, NgConnectTask.Flags())

    def run(self) -> bool:
        try:
            cache_manager = NgConnectCacheManager()
            cache_manager.purge_cache()
        except Exception as error:
            self.error = error
            return False

        return True

    def finished(self, successful: bool):  # noqa: FBT001
        if successful:
            return

        utils.log_to_qgis(
            f"An error occured while clearing cache: {self.error}",
        )
