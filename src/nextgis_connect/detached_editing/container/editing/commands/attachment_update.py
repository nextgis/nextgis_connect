from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtWidgets import QUndoCommand

from nextgis_connect.detached_editing.container.editing.commands.base import (
    DetachedLayerBaseCommand,
    UndoCommandType,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    is_attachment_new,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_layer import DetachedLayer


class AttachmentUpdateCommand(DetachedLayerBaseCommand):
    """Command to update an attachment content or metadata in the edit buffer.

    This command stores old and new attachment metadata and applies
    changes to the detached layer edit buffer. It supports undo/redo
    operations and is intended to be pushed to a vector layer QUndoStack.
    Also it can be merged with subsequent update commands for the same
    attachment.

    :ivar _old_attachment: Previous attachment metadata (before change).
    :vartype _old_attachment: AttachmentMetadata
    :ivar _new_attachment: New attachment metadata (after change).
    :vartype _new_attachment: AttachmentMetadata
    :ivar _is_first_change: True if this is the first update applied to
        the attachment in the current edit buffer session.
    :vartype _is_first_change: bool
    """

    _old_attachment: AttachmentMetadata
    _new_attachment: AttachmentMetadata
    _is_first_change: bool

    def __init__(
        self,
        detached_layer: "DetachedLayer",
        old_attachment: AttachmentMetadata,
        new_attachment: AttachmentMetadata,
    ) -> None:
        """Initialize the command and record attachment states.

        :param detached_layer: Detached layer the command will operate on.
        :type detached_layer: DetachedLayer
        :param old_attachment: Attachment metadata before the update.
        :type old_attachment: AttachmentMetadata
        :param new_attachment: Attachment metadata after the update.
        :type new_attachment: AttachmentMetadata
        """

        super().__init__(detached_layer)
        self._old_attachment = old_attachment
        self._new_attachment = new_attachment
        # Determine whether this attachment was already registered as
        # updated in the edit buffer prior to creating this command.
        self._is_first_change = (
            self._detached_layer.edit_buffer.updated_attachments.get(
                self._old_attachment.fid, {}
            ).get(self._old_attachment.aid)
            is None
        )

    def undo(self) -> None:
        """Revert the attachment update.

        Restore the attachment metadata to the stored old state. If the
        attachment was newly created in the temporary storage, restore it
        to the `_added_attachments` mapping; otherwise put it back to
        `_updated_attachments`. Emit the `attachment_updated` signal so
        UI and other listeners can react to the revert.
        """

        edit_buffer = self._detached_layer.edit_buffer

        # If the attachment belongs to a newly added feature, keep it in
        # the added attachments mapping; otherwise restore into updates.
        if is_attachment_new(self._old_attachment.fid):
            edit_buffer._added_attachments[self._old_attachment.fid][
                self._old_attachment.aid
            ] = self._old_attachment
        else:
            edit_buffer._updated_attachments[self._old_attachment.fid][
                self._old_attachment.aid
            ] = self._old_attachment

        # Notify listeners about the change.
        edit_buffer.attachment_updated.emit(
            self._old_attachment.fid, self._old_attachment.aid
        )

        logger.debug(
            "Reverted attachment %s update command for feature %s",
            self._old_attachment.fid,
            self._old_attachment.aid,
        )

    def redo(self) -> None:
        """Apply the attachment update.

        Replace stored attachment metadata with the new metadata in the
        appropriate edit buffer mapping and emit `attachment_updated` so
        UI and other components reflect the change.
        """

        edit_buffer = self._detached_layer.edit_buffer

        if is_attachment_new(self._old_attachment.fid):
            edit_buffer._added_attachments[self._old_attachment.fid][
                self._old_attachment.aid
            ] = self._new_attachment
        else:
            edit_buffer._updated_attachments[self._old_attachment.fid][
                self._old_attachment.aid
            ] = self._new_attachment

        # Notify listeners about the applied update.
        edit_buffer.attachment_updated.emit(
            self._old_attachment.fid, self._old_attachment.aid
        )

        logger.debug(
            "Applied attachment %s update command for feature %s",
            self._old_attachment.fid,
            self._old_attachment.aid,
        )

    def id(self) -> int:
        """Returns the ID of this command.

        A command ID is used in command compression.

        :return: Command ID.
        """
        return int(UndoCommandType.ATTACHMENT_UPDATE)

    def mergeWith(self, other: Optional[QUndoCommand]) -> bool:
        """Attempts to merge this command with another command.

        :param other: The other command to merge with.
        :type other: Optional[QUndoCommand]
        :return: True if the commands were merged, False otherwise.
        :rtype: bool
        """
        assert other is not None
        if self.id() != other.id():
            return False

        assert isinstance(other, AttachmentUpdateCommand)
        if (
            self._old_attachment.fid != other._old_attachment.fid
            or self._old_attachment.aid != other._old_attachment.aid
        ):
            return False

        # Keep the original _old_attachment but accept the newer
        # _new_attachment from the subsequent command so that multiple
        # consecutive updates compress into a single undoable action.
        self._new_attachment = other._new_attachment

        # If the net effect is no change, mark this command obsolete and
        # remove any recorded update if this was the first change.
        if self._old_attachment == self._new_attachment:
            self.setObsolete(True)

            if self._is_first_change:
                edit_buffer = self._detached_layer.edit_buffer
                edit_buffer._updated_attachments.pop(
                    self._old_attachment.fid, None
                )

        return True
