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

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from qgis.PyQt.QtCore import QObject

from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.platform.qgis.errors import ErrorCode


class DetachedLayerIndicatorStateSource(Protocol):
    """Provide synchronization state for a detached layer indicator."""

    @property
    def state(self) -> DetachedLayerState:
        """Return current detached layer state."""
        ...

    @property
    def sync_date(self) -> Optional[datetime]:
        """Return last successful synchronization date."""
        ...

    @property
    def check_date(self) -> Optional[datetime]:
        """Return last synchronization check date."""
        ...

    @property
    def error_code(self) -> ErrorCode:
        """Return current detached layer error code."""
        ...

    @property
    def is_auto_sync_enabled(self) -> bool:
        """Return whether automatic synchronization is enabled."""
        ...


@dataclass(frozen=True)
class DetachedLayerIndicatorState:
    """Store presentation state for a detached layer indicator.

    :ivar icon_path: Icon shown when animation is disabled.
    :ivar animation_icon_path: Icon used for normal animation frames.
    :ivar animation_blink_icon_path: Icon used for blink animation frames.
    :ivar tooltip: User-facing tooltip text.
    :ivar is_animation_enabled: Whether rotation animation should run.
    """

    icon_path: str
    tooltip: str
    animation_icon_path: str = ""
    animation_blink_icon_path: str = ""
    is_animation_enabled: bool = False


class DetachedLayerIndicatorStateResolver(QObject):
    """Resolve detached layer state into indicator presentation data."""

    NOT_SYNCHRONIZED_ICON_PATH = "synchronization/not_synchronized.svg"
    SYNCHRONIZED_ICON_PATH = "synchronization/synchronized.svg"
    SYNCHRONIZATION_ICON_PATH = "synchronization/synchronization.svg"
    SYNCHRONIZATION_BLINK_ICON_PATH = "synchronization/empty.svg"
    ERROR_ICON_PATH = "synchronization/error.svg"
    MANUAL_ICON_PATH = "synchronization/manual.svg"

    def resolve(
        self,
        source: DetachedLayerIndicatorStateSource,
    ) -> DetachedLayerIndicatorState:
        """Return indicator presentation state for a detached layer source.

        :param source: Source object with detached layer state data.
        :return: Presentation state for the indicator.
        """
        date_tooltip = self._date_tooltip(source)
        state = source.state

        if state in (
            DetachedLayerState.NotInitialized,
            DetachedLayerState.NotSynchronized,
        ):
            status_tooltip = self.tr("Layer is not synchronized!")
            return DetachedLayerIndicatorState(
                icon_path=self.NOT_SYNCHRONIZED_ICON_PATH,
                tooltip=f"{status_tooltip}{date_tooltip}",
            )

        if state == DetachedLayerState.Synchronized:
            status_tooltip = self.tr("Layer is synchronized")
            return DetachedLayerIndicatorState(
                icon_path=self._synchronized_icon_path(source),
                tooltip=f"{status_tooltip}{date_tooltip}",
            )

        if state == DetachedLayerState.Synchronization:
            return DetachedLayerIndicatorState(
                icon_path=self.SYNCHRONIZATION_ICON_PATH,
                animation_icon_path=self.SYNCHRONIZATION_ICON_PATH,
                animation_blink_icon_path=self.SYNCHRONIZATION_BLINK_ICON_PATH,
                tooltip=self.tr("Layer is syncing"),
                is_animation_enabled=True,
            )

        if state == DetachedLayerState.Error:
            status_tooltip = self._error_tooltip(source.error_code)
            spoiler = self.tr("Click to see more details")
            return DetachedLayerIndicatorState(
                icon_path=self.ERROR_ICON_PATH,
                tooltip=f"{status_tooltip}{date_tooltip}\n\n{spoiler}",
            )

        return DetachedLayerIndicatorState(
            icon_path=self.NOT_SYNCHRONIZED_ICON_PATH,
            tooltip=self.tr("NextGIS Web Layer"),
        )

    def _synchronized_icon_path(
        self,
        source: DetachedLayerIndicatorStateSource,
    ) -> str:
        if not source.is_auto_sync_enabled:
            return self.MANUAL_ICON_PATH

        return self.SYNCHRONIZED_ICON_PATH

    def _date_tooltip(
        self,
        source: DetachedLayerIndicatorStateSource,
    ) -> str:
        date_tooltip = ""

        sync_date = source.sync_date
        if sync_date is not None:
            sync_datetime = sync_date.strftime("%c")
            sync_date_label = self.tr("Synchronization date")
            date_tooltip += f"\n{sync_date_label}: {sync_datetime}"

        check_date = source.check_date
        if check_date is not None:
            check_datetime = check_date.strftime("%c")
            check_date_label = self.tr("Check date")
            date_tooltip += f"\n{check_date_label}: {check_datetime}"

        return date_tooltip

    def _error_tooltip(self, error_code: ErrorCode) -> str:
        if error_code.is_synchronization_error:
            return self.tr("Synchronization error!")

        if error_code.is_container_error:
            return self.tr("Layer error!")

        return self.tr("Unknown error!")
