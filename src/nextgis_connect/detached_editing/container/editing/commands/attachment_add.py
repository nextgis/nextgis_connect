from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtWidgets import QUndoCommand

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.container.editing.commands.base import (
    DetachedLayerBaseCommand,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_layer import DetachedLayer


class AttachmentAddCommand(DetachedLayerBaseCommand):
    """Command to create and manage an attachment addition in the edit buffer.

    This command creates an attachment in the edit buffer's temporary
    storage for a given feature and file path. It supports undo/redo
    operations and is intended to be pushed to a vector layer QUndoStack.

    :ivar _attachment: Metadata object describing the created attachment.
    :vartype _attachment: AttachmentMetadata
    """

    _attachment: AttachmentMetadata

    def __init__(
        self,
        detached_layer: "DetachedLayer",
        feature_id: QgsFeatureId,
        file_path: Path,
    ) -> None:
        """Initialize the command and create attachment in temporary storage.

        :param detached_layer: Detached layer the command will operate on.
        :type detached_layer: DetachedLayer
        :param feature_id: ID of the feature to attach the file to.
        :type feature_id: QgsFeatureId
        :param file_path: Path to the file being attached.
        :type file_path: Path
        """

        super().__init__(detached_layer)

        edit_buffer = self._detached_layer.edit_buffer
        self._attachment = edit_buffer._create_attachment_in_temporary_storage(
            feature_id, file_path
        )

    @property
    def attachment(self) -> AttachmentMetadata:
        """Return attachment metadata.

        :return: Attachment metadata.
        :rtype: AttachmentMetadata
        """

        return self._attachment

    def undo(self) -> None:
        """Revert the attachment addition.

        Revert the attachment creation performed by this command.
        """
        edit_buffer = self._detached_layer.edit_buffer

        edit_buffer._added_attachments[self._attachment.fid].pop(
            self._attachment.aid, None
        )

        edit_buffer.attachment_removed.emit(
            self._attachment.fid, self._attachment.aid
        )

        logger.debug(
            "Reverted attachment %s add command for feature %s",
            self._attachment.fid,
            self._attachment.aid,
        )

    def redo(self) -> None:
        """Apply the attachment addition.

        Perform the attachment creation performed by this command.
        """
        edit_buffer = self._detached_layer.edit_buffer

        edit_buffer._added_attachments[self._attachment.fid][
            self._attachment.aid
        ] = self._attachment

        edit_buffer.attachment_added.emit(
            self._attachment.fid, self._attachment.aid
        )

        logger.debug(
            "Added attachment %s command for feature %s",
            self._attachment.fid,
            self._attachment.aid,
        )

    def id(self) -> int:
        """Returns the ID of this command.

        A command ID is used in command compression.

        :return: Command ID.
        """
        return -1  # int(UndoCommandType.ATTACHMENT_REMOVE)

    def mergeWith(self, other: Optional[QUndoCommand]) -> bool:
        """Attempts to merge this command with another command.

        :param other: The other command to merge with.
        :type other: Optional[QUndoCommand]
        :return: True if the commands were merged, False otherwise.
        :rtype: bool
        """
        return False
