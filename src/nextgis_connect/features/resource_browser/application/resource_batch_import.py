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
from typing import Hashable, Optional, Protocol, Tuple

LARGE_BATCH_IMPORT_WARNING_THRESHOLD = 30


class ResourceImportCancelledError(Exception):
    """Stop batch resource import after an explicit user cancellation."""


@dataclass(frozen=True)
class ResourceAddingErrorContext:
    """Describe a resource that failed during a batch import."""

    display_name: str
    insertion_id: Optional[Hashable] = None
    resource_ids: Tuple[int, ...] = ()
    resource_url: Optional[str] = None


class ResourceBatchImportInteraction(Protocol):
    """Define user decisions required by the batch import workflow."""

    def confirm_large_import(self, layer_count: int) -> bool:
        """Return whether the user accepts importing a large layer batch."""

    def select_default_style(
        self,
        title: str,
        index: object,
        resource_model: object,
    ) -> int:
        """Return the selected style resource ID or cancel the import."""

    def should_skip_wfs_with_z(self) -> bool:
        """Return whether WFS layers with Z geometry must be skipped."""

    def should_skip_after_error(
        self,
        error: Exception,
        context: ResourceAddingErrorContext,
        can_skip: bool,
    ) -> bool:
        """Return whether a failed resource must be skipped."""
