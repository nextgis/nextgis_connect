from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtWidgets import QUndoCommand

from nextgis_connect.detached_editing.container.editing.commands.base import (
    DetachedLayerBaseCommand,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    is_attachment_new,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_layer import DetachedLayer


class AttachmentRemoveCommand(DetachedLayerBaseCommand):
    """Command to remove an attachment from the edit buffer.

    It supports undo/redo operations and is intended to be pushed to a vector
    layer QUndoStack.

    :ivar _attachment: Metadata describing the attachment that will be
        removed or restored.
    :vartype _attachment: AttachmentMetadata
    """

    _attachment: AttachmentMetadata

    def __init__(
        self,
        detached_layer: "DetachedLayer",
        attachment: AttachmentMetadata,
    ) -> None:
        """Initialize the remove command and capture pre-change state.

        The command records whether the attachment has been updated before
        the removal so that ``undo()`` can restore it into the correct
        edit_buffer collection.

        :param detached_layer: Target detached layer instance.
        :type detached_layer: DetachedLayer
        :param attachment: Attachment metadata to remove.
        :type attachment: AttachmentMetadata
        """

        super().__init__(detached_layer)
        self._attachment = attachment

        # remember whether the attachment had been changed before removal
        # (used to decide whether to restore it into `updated_attachments`)
        self._has_changed_previously = (
            self._detached_layer.edit_buffer.updated_attachments[
                self._attachment.fid
            ].get(self._attachment.aid)
            is not None
        )

    def undo(self) -> None:
        """Revert the attachment removal.

        Restores the attachment into the edit buffer. Behavior differs
        depending on whether the attachment was created during the current
        edit session or already existed prior to this removal:

        - If the attachment is new (its AID indicates a temporary/new
          attachment), it is re-inserted into ``_added_attachments``.
        - Otherwise, if the attachment had staged updates prior to removal,
          those updates are restored into ``_updated_attachments`` and the
          attachment id is removed from ``_removed_attachments``.
        """

        edit_buffer = self._detached_layer.edit_buffer

        # If attachment was newly created in this edit session, restore it
        # into the `_added_attachments` collection so it appears as new.
        if is_attachment_new(self._attachment.aid):
            edit_buffer._added_attachments[self._attachment.fid][
                self._attachment.aid
            ] = self._attachment
        else:
            # If the attachment had prior updates, restore those updates.
            if self._has_changed_previously:
                edit_buffer._updated_attachments[self._attachment.fid][
                    self._attachment.aid
                ] = self._attachment

            # Remove the attachment id from the removed set to mark it present
            edit_buffer._removed_attachments[self._attachment.fid].remove(
                self._attachment.aid
            )

        # Notify listeners that the attachment is present again
        edit_buffer.attachment_added.emit(
            self._attachment.fid, self._attachment.aid
        )

        logger.debug(
            "Reverted attachment %s removal command for feature %s",
            self._attachment.fid,
            self._attachment.aid,
        )

    def redo(self) -> None:
        """Apply the attachment removal.

        Performs the removal operation recorded by this command. Depending on
        whether the attachment originated within the current edit session the
        operation will either drop the temporary entry or mark the attachment
        id as removed so it will be deleted on commit.

        - If the attachment is new, it is removed from ``_added_attachments``.
        - Otherwise, any staged updates are discarded and the id is added to
          ``_removed_attachments``.
        """

        edit_buffer = self._detached_layer.edit_buffer

        # If the attachment was new in this session, drop it from added map.
        if is_attachment_new(self._attachment.fid):
            edit_buffer._added_attachments[self._attachment.fid].pop(
                self._attachment.aid, None
            )
        else:
            # Remove any staged updates for this attachment if present.
            if self._has_changed_previously:
                edit_buffer._updated_attachments[self._attachment.fid].pop(
                    self._attachment.aid, None
                )

            # Mark the attachment id as removed in the removed set.
            edit_buffer._removed_attachments[self._attachment.fid].add(
                self._attachment.aid
            )

        # Notify listeners that the attachment was removed
        edit_buffer.attachment_removed.emit(
            self._attachment.fid, self._attachment.aid
        )

        logger.debug(
            "Applied attachment %s removal command for feature %s",
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
