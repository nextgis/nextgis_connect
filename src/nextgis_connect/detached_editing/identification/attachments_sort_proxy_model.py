from pathlib import Path
from typing import Any, Optional

from qgis.PyQt.QtCore import QModelIndex, QObject, QSortFilterProxyModel, Qt

from nextgis_connect.detached_editing.identification.attachments_model import (
    AttachmentsModel,
)
from nextgis_connect.detached_editing.identification.types import (
    AttachmentsSortMode,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata


class AttachmentsSortProxyModel(QSortFilterProxyModel):
    """Sort attachment items by selected attachment attributes.

    Proxy attachment data from :class:`AttachmentsModel` and provide stable
    ordering by name, MIME type, or size, with name-based fallback when
    primary sort values are equal.

    :ivar sort_key: Active sort mode used for comparisons.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Initialize the proxy model with default name sorting.

        :param parent: Optional parent object owning the proxy model.
        """
        super().__init__(parent)
        self._sort_key = AttachmentsSortMode.BY_NAME
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        # self.setSortRole(int(AttachmentsModel.Roles.NAME))

    @property
    def sort_key(self) -> AttachmentsSortMode:
        """Return the active attachment sort mode.

        :return: Current sort mode used for item comparison.
        """
        return self._sort_key

    @sort_key.setter
    def sort_key(self, sort_key: AttachmentsSortMode) -> None:
        """Update the active sort mode and re-run proxy sorting.

        :param sort_key: New sort mode to apply.
        """
        if sort_key == self._sort_key:
            return
        self._sort_key = sort_key
        self.invalidate()
        self.sort(0, self.sortOrder())

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # type: ignore[override]
        """Compare two source items according to the active sort mode.

        :param left: Left source model index.
        :param right: Right source model index.
        :return: ``True`` when the left item should be ordered first.
        """
        source_model = self.sourceModel()
        if source_model is None:
            return False

        left_attachment = source_model.data(
            left, int(AttachmentsModel.Roles.ATTACHMENT)
        )
        right_attachment = source_model.data(
            right, int(AttachmentsModel.Roles.ATTACHMENT)
        )

        if not isinstance(
            left_attachment, AttachmentMetadata
        ) or not isinstance(right_attachment, AttachmentMetadata):
            return super().lessThan(left, right)

        left_value = self._value_for_sort(left_attachment)
        right_value = self._value_for_sort(right_attachment)

        if (
            left_value == right_value
            and self._sort_key != AttachmentsSortMode.BY_NAME
        ):
            # Fallback to name sorting to ensure consistent order
            left_value = (left_attachment.name or "").lower()
            right_value = (right_attachment.name or "").lower()

        return left_value < right_value

    def _value_for_sort(self, attachment: AttachmentMetadata) -> Any:
        """Extract a comparable value for the configured sort mode.

        :param attachment: Attachment metadata to inspect.
        :return: Value used during item comparison.
        """
        attachment_name = attachment.name.lower() if attachment.name else ""

        if self._sort_key == AttachmentsSortMode.BY_NAME:
            return attachment_name
        if self._sort_key == AttachmentsSortMode.BY_TYPE:
            return (
                attachment.mime_type.lower()
                or Path(attachment_name).suffix.lower()
            )
        if self._sort_key == AttachmentsSortMode.BY_SIZE:
            return attachment.size

        return attachment_name
