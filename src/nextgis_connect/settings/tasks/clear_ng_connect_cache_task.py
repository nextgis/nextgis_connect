from nextgis_connect.core.tasks.ng_connect_task import NgConnectTask
from nextgis_connect.logging import logger
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)


class ClearNgConnectCacheTask(NgConnectTask):
    def __init__(self):
        super().__init__(flags=NgConnectTask.Flags())
        self.setDescription(self.tr("Clearing NextGIS Connect cache"))

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug("<b>Clearing cache</b>")

        try:
            cache_manager = NgConnectCacheManager()
            cache_manager.clear_cache()
        except Exception as error:
            logger.exception("An error occurred while cache clearing")
            self._error = error
            return False

        return True
