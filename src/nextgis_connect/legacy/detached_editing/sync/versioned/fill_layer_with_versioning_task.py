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

import urllib.parse
from contextlib import closing
from pathlib import Path

from nextgis_connect.legacy.detached_editing.sync.common.detached_editing_task import (
    DetachedEditingTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions_applier import (
    ActionApplier,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.actions_serializer import (
    ActionSerializer,
)
from nextgis_connect.legacy.detached_editing.utils import (
    make_connection,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import NgwError, SynchronizationError


class FillLayerWithVersioningTask(DetachedEditingTask):
    def __init__(self, stub_path: Path) -> None:
        super().__init__(stub_path)
        if self._error is not None:
            return

        description = self.tr('Downloading layer "{layer_name}"').format(
            layer_name=self._metadata.layer_name
        )
        self.setDescription(description)

    def run(self) -> bool:
        if not super().run():
            return False

        logger.debug(f"Start filling layer{self._metadata}")

        connection_id = self._metadata.connection_id
        resource_id = self._metadata.resource_id

        try:
            ngw_connection = QgsNgwConnection(connection_id)

            # Check structure etc
            self._get_layer(ngw_connection)

            check_params = urllib.parse.urlencode(
                {
                    "extensions": "attachment,description",
                }
            )
            check_result = ngw_connection.get(
                f"/api/resource/{resource_id}/feature/changes/check?{check_params}"
            )
            fetch_url = check_result["fetch"]

            actions = []
            fetched_actions = ngw_connection.get(fetch_url)
            while len(fetched_actions) > 0:
                actions.extend(fetched_actions)
                continue_action = fetched_actions[-1]
                assert "url" in continue_action
                fetched_actions = ngw_connection.get(continue_action["url"])

            serializer = ActionSerializer(self._metadata)
            applier = ActionApplier(self._container_path, self._metadata)
            applier.apply(serializer.from_json(actions))

            sync_date = check_result["tstamp"]
            with closing(
                make_connection(self._container_path)
            ) as connection, closing(connection.cursor()) as cursor:
                cursor.execute(
                    f"UPDATE ngw_metadata SET sync_date='{sync_date}'"
                )
                connection.commit()

        except SynchronizationError as error:
            self._error = error
            return False

        except NgwError as error:
            self._error = error
            return False

        except Exception as error:
            message = (
                f"An error occurred while downloading layer {self._metadata}"
            )
            self._error = SynchronizationError(message)
            self._error.__cause__ = error
            return False

        return True
