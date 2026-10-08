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
from typing import Optional

from qgis.PyQt.QtCore import QModelIndex

from nextgis_connect.features.synchronization.presentation import (
    DetachedLayerIndicatorPresenter,
    DetachedLayerIndicatorStateResolver,
    DetachedLayerTreeIndicator,
)
from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.platform.qgis.errors import ErrorCode


@dataclass(frozen=True)
class _Source:
    state: DetachedLayerState
    sync_date: Optional[datetime] = None
    check_date: Optional[datetime] = None
    error_code: ErrorCode = ErrorCode.NoError
    is_auto_sync_enabled: bool = True


class TestDetachedLayerIndicatorStateResolver:
    def test_resolves_synchronized_state(self, qgis_app) -> None:
        del qgis_app

        resolver = DetachedLayerIndicatorStateResolver()
        state = resolver.resolve(
            _Source(
                state=DetachedLayerState.Synchronized,
                sync_date=datetime(2026, 7, 29, 12, 30, 0),
            )
        )

        assert state.icon_path == "synchronization/synchronized.svg"
        assert state.is_animation_enabled is False
        assert state.tooltip.startswith("Layer is synchronized")
        assert "Synchronization date" in state.tooltip

    def test_resolves_synchronization_animation_state(self, qgis_app) -> None:
        del qgis_app

        resolver = DetachedLayerIndicatorStateResolver()
        state = resolver.resolve(
            _Source(state=DetachedLayerState.Synchronization)
        )

        assert state.icon_path == "synchronization/synchronization.svg"
        assert (
            state.animation_icon_path == "synchronization/synchronization.svg"
        )
        assert state.animation_blink_icon_path == "synchronization/empty.svg"
        assert state.is_animation_enabled is True
        assert state.tooltip == "Layer is syncing"

    def test_resolves_synchronization_error(self, qgis_app) -> None:
        del qgis_app

        resolver = DetachedLayerIndicatorStateResolver()
        state = resolver.resolve(
            _Source(
                state=DetachedLayerState.Error,
                error_code=ErrorCode.SynchronizationError,
            )
        )

        assert state.icon_path == "synchronization/error.svg"
        assert state.is_animation_enabled is False
        assert state.tooltip.startswith("Synchronization error!")
        assert "Click to see more details" in state.tooltip

    def test_resolves_manual_icon_when_auto_sync_is_disabled(
        self,
        qgis_app,
    ) -> None:
        del qgis_app

        resolver = DetachedLayerIndicatorStateResolver()
        state = resolver.resolve(
            _Source(
                state=DetachedLayerState.Synchronized,
                is_auto_sync_enabled=False,
            )
        )

        assert state.icon_path == "synchronization/manual.svg"
        assert state.is_animation_enabled is False

    def test_keeps_not_synchronized_icon_when_auto_sync_is_disabled(
        self,
        qgis_app,
    ) -> None:
        del qgis_app

        resolver = DetachedLayerIndicatorStateResolver()
        state = resolver.resolve(
            _Source(
                state=DetachedLayerState.NotSynchronized,
                is_auto_sync_enabled=False,
            )
        )

        assert state.icon_path == "synchronization/not_synchronized.svg"


class TestDetachedLayerIndicatorPresenter:
    def test_exposes_ready_to_display_state(self, qgis_app) -> None:
        presenter = DetachedLayerIndicatorPresenter(
            _Source(state=DetachedLayerState.Synchronized),
            qgis_app,
        )

        assert not presenter.current_icon.isNull()
        assert presenter.current_tooltip == "Layer is synchronized"

    def test_sync_animation_uses_reverse_rotation(self, qgis_app) -> None:
        presenter = DetachedLayerIndicatorPresenter(
            _Source(state=DetachedLayerState.Synchronization),
            qgis_app,
        )

        presenter._sync_tick()

        assert presenter._angle == -presenter._ROTATION_STEP_DEGREES


class TestDetachedLayerTreeIndicator:
    def test_uses_presenter_state_and_emits_details_request(
        self,
        qgis_app,
    ) -> None:
        presenter = DetachedLayerIndicatorPresenter(
            _Source(state=DetachedLayerState.Synchronized),
            qgis_app,
        )
        details_request_count = 0

        def count_details_request() -> None:
            nonlocal details_request_count

            details_request_count += 1

        indicator = DetachedLayerTreeIndicator(
            qgis_app,
            presenter,
        )
        indicator.details_requested.connect(count_details_request)

        indicator.clicked.emit(QModelIndex())

        assert details_request_count == 1
        assert not indicator.icon().isNull()
        assert indicator.toolTip() == "Layer is synchronized"
