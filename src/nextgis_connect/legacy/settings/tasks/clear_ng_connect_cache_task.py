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

from nextgis_connect.features.synchronization.infrastructure.storage.cache_maintenance_service import (
    CacheMaintenanceService,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.tasks import NgConnectTask


class ClearNgConnectCacheTask(NgConnectTask):
    def __init__(self):
        super().__init__(flags=NgConnectTask.Flags())
        self.setDescription(self.tr("Clearing NextGIS Connect cache"))

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug("Clearing cache")

        try:
            cache_service = CacheMaintenanceService()
            return cache_service.clear_cache()
        except Exception as error:
            logger.exception("An error occurred while cache clearing")
            self._error = error
            return False
