from nextgis_connect.core.tasks.ng_connect_task import NgConnectTask
from nextgis_connect.logging import logger
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)


class PurgeNgConnectCacheTask(NgConnectTask):
    def __init__(self):
        super().__init__(flags=NgConnectTask.Flags())
        self.setDescription(self.tr("Clearing NextGIS Connect cache"))

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug("<b>Purging cache</b>")

        try:
            cache_manager = NgConnectCacheManager()
            cache_manager.purge_cache()
        except Exception:
            logger.exception("An error occurred while cache purging")
            return False

        return True
