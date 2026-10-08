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

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, cast

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QPainter,
    QPalette,
    QPixmap,
)
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QLabel,
    QLineEdit,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from nextgis_connect.features.synchronization.presentation.attachments.attachment_display_state import (
    AttachmentDisplayState,
)
from nextgis_connect.features.synchronization.presentation.attachments.attachment_icon_painter import (
    AttachmentIconPainter,
)
from nextgis_connect.legacy.detached_editing.identification.attachments_model import (
    AttachmentsModel,
)
from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.ui_kit.delegates.widget_item_delegate import (
    WidgetItemDelegate,
)
from nextgis_connect.ui_kit.icons import material_icon, qgis_icon


@dataclass(frozen=True)
class _AttachmentMenuActionNames:
    open_attachment: str = "openAttachmentAction"
    cache_attachment: str = "cacheAttachmentAction"
    edit_attachment: str = "editAttachmentAction"
    show_in_folder: str = "showInFolderAttachmentAction"
    copy_attachment: str = "copyAttachmentAction"
    save_as: str = "saveAsAttachmentAction"
    delete_attachment: str = "deleteAttachmentAction"


@dataclass
class _AttachmentMenuActions:
    open_attachment: QAction
    cache_attachment: QAction
    edit_attachment: QAction
    show_in_folder: QAction
    copy_attachment: QAction
    save_as: QAction
    delete_attachment: QAction


class AttachmentDelegate(WidgetItemDelegate):
    SPACING: int = 12
    OUTER_MARGIN_H: int = 8
    OUTER_MARGIN_V: int = 6
    TOOL_TEXT: str = "..."
    LOADING_INDICATOR_DELAY_MS = 250.0
    LOADING_TIMER_INTERVAL_MS = 50
    LOADING_ROTATION_DEGREES_PER_SECOND = 240.0
    LOADING_MAX_FRAME_SECONDS = 0.25
    MENU_ACTION_NAMES = _AttachmentMenuActionNames()

    open_attachment = pyqtSignal(QModelIndex)
    cache_attachment = pyqtSignal(QModelIndex)
    show_in_folder = pyqtSignal(QModelIndex)
    save_as = pyqtSignal(QModelIndex)
    copy_attachment = pyqtSignal(QModelIndex)
    delete_attachment = pyqtSignal(QModelIndex)

    @dataclass
    class _Layout:
        """Hold calculated rectangles for painting."""

        rect: QRect
        icon_rect: QRect
        middle_rect: QRect
        tool_rect: QRect
        title_rect: QRect
        desc_rect: QRect
        tool_rect_inner: QRect
        title_metrics: QFontMetrics
        desc_metrics: QFontMetrics
        tool_metrics: QFontMetrics
        title_font: QFont
        desc_font: QFont
        tool_font: QFont
        title_text: str
        desc_text: str
        elided_title: str
        elided_desc: str
        line_spacing: int

    def __init__(
        self, item_view: QAbstractItemView, parent: Optional[QWidget] = None
    ):
        super().__init__(item_view, parent)
        # Track currently opened editor widget
        self._current_editor: Optional[QWidget] = None
        settings = IdentificationSettings()
        self._thumbnail_size = QSize(
            settings.attachment_thumbnail_size,
            settings.attachment_thumbnail_size,
        )
        self._icon_painter = AttachmentIconPainter(self._thumbnail_size)
        self._loading_angle = 0.0
        self._loading_last_frame_time: Optional[float] = None
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(self.LOADING_TIMER_INTERVAL_MS)
        self._loading_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._loading_timer.timeout.connect(self._advance_loading_animation)
        self._loading_started_at_by_attachment_identity: Dict[
            Tuple[int, int], float
        ] = {}

    def paint(
        self,
        painter: Optional[QPainter],
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Paint item contents by delegating to helper methods."""
        if painter is None:
            return
        painter.save()
        self._draw_background(painter, option)
        _, text_color, secondary_text_color = self._resolve_colors(option)
        state = AttachmentDisplayState.from_index(index)
        layout = self._compute_layout(
            option,
            state.icon_value,
            state.title,
            state.description,
        )
        self._draw_icon(painter, option, state, layout)
        self._draw_text_blocks(
            painter, layout, text_color, secondary_text_color
        )
        painter.restore()

    def edit(self, index: QModelIndex) -> None:
        if not self._has_valid_item_view():
            return

        self.close_current_editor()
        self._item_view.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        self._item_view.edit(index)

    def _create_item_widgets(self, index: QModelIndex) -> List[QWidget]:
        attachment_actions_button = QToolButton()
        attachment_actions_button.setIcon(material_icon("more_vert"))
        attachment_actions_button.setAutoRaise(True)
        attachment_actions_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        attachment_actions_button.setStyleSheet(
            """
            QToolButton::menu-indicator {
                image: none;
            }
            """
        )
        self._set_blocked_event_types(
            attachment_actions_button,
            [
                QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            ],
        )
        attachment_menu = self._build_attachment_menu(
            attachment_actions_button, index
        )
        edit_action = self._menu_actions(attachment_menu).edit_attachment
        # Use current model index stored on the button, not the stale one
        edit_action.triggered.connect(
            lambda _=False, btn=attachment_actions_button: (
                self._trigger_edit_from_button(btn)
            )
        )
        attachment_actions_button.setMenu(attachment_menu)

        return [attachment_actions_button]

    def _update_item_widgets(
        self,
        widgets: List[QWidget],
        option: QStyleOptionViewItem,
        index: QPersistentModelIndex,
    ) -> None:
        button = widgets[0]
        state = AttachmentDisplayState.from_index(QModelIndex(index))
        layout = self._compute_layout(
            option,
            state.icon_value,
            state.title,
            state.description,
            tool_size=button.sizeHint(),
        )

        self._update_attachment_menu_state(button.menu(), index)

        # Position the button in item-local coordinates (centered vertically).
        # Pool will later offset by option.rect's top-left; avoid double shift.
        local_x = layout.tool_rect.left() - option.rect.left()
        local_y = layout.tool_rect.top() - option.rect.top()
        button.move(local_x, local_y)
        # Keep current index on the button to use on action trigger
        try:
            button.setProperty("modelIndex", QPersistentModelIndex(index))
        except Exception:
            button.setProperty("modelIndex", index)

    def _trigger_edit_from_button(self, button: QToolButton) -> None:
        # Fetch current persistent index from the button
        idx = button.property("modelIndex")
        model_index: QModelIndex
        try:
            if isinstance(idx, QPersistentModelIndex):
                model_index = QModelIndex(idx)
            elif isinstance(idx, QModelIndex):
                model_index = idx
            else:
                model_index = QModelIndex()
        except Exception:
            model_index = QModelIndex()

        if model_index.isValid():
            self.edit(model_index)

    def _delete_attachment(self, index: QModelIndex) -> None:
        if not index.isValid():
            return

        self.delete_attachment.emit(index)

    def build_context_menu(self, parent: QWidget, index: QModelIndex) -> QMenu:
        """Build a context menu for the current attachment item."""
        attachment_menu = self._build_attachment_menu(parent, index)
        self._update_attachment_menu_state(attachment_menu, index)

        edit_action = self._menu_actions(attachment_menu).edit_attachment
        edit_action.triggered.connect(
            lambda _=False, current_index=index: self.edit(current_index)
        )

        return attachment_menu

    def _build_attachment_menu(
        self, parent: QWidget, index: QModelIndex
    ) -> QMenu:
        """
        Build actions menu for attachments. Reusable in item and editor.
        """
        attachment_menu = QMenu(parent)

        open_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.open_attachment,
            material_icon("file_open"),
            QCoreApplication.translate(
                "AttachmentDelegate", "Download and Open"
            ),
            lambda index=index: self.open_attachment.emit(index),
        )
        cache_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.cache_attachment,
            material_icon("download_for_offline"),
            QCoreApplication.translate("AttachmentDelegate", "Download"),
            lambda index=index: self.cache_attachment.emit(index),
        )
        edit_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.edit_attachment,
            qgis_icon("mActionEditTable.svg"),
            QCoreApplication.translate("AttachmentDelegate", "Edit"),
        )
        show_in_folder_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.show_in_folder,
            qgis_icon("mIconFolderLink.svg"),
            QCoreApplication.translate("AttachmentDelegate", "Show in Folder"),
            lambda index=index: self.show_in_folder.emit(index),
        )
        copy_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.copy_attachment,
            qgis_icon("mActionEditCopy.svg"),
            QCoreApplication.translate("AttachmentDelegate", "Copy"),
            lambda index=index: self.copy_attachment.emit(index),
        )
        save_as_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.save_as,
            qgis_icon("mActionFileSaveAs.svg"),
            QCoreApplication.translate("AttachmentDelegate", "Save As…"),
            lambda index=index: self.save_as.emit(index),
        )
        delete_action = self._add_menu_action(
            attachment_menu,
            self.MENU_ACTION_NAMES.delete_attachment,
            qgis_icon("mActionDeleteSelected.svg"),
            QCoreApplication.translate("AttachmentDelegate", "Delete"),
            lambda index=index: self._delete_attachment(index),
        )

        attachment_menu.setProperty(
            "attachmentActions",
            _AttachmentMenuActions(
                open_attachment=open_action,
                cache_attachment=cache_action,
                edit_attachment=edit_action,
                show_in_folder=show_in_folder_action,
                copy_attachment=copy_action,
                save_as=save_as_action,
                delete_attachment=delete_action,
            ),
        )

        persistent_index = QPersistentModelIndex(index)
        attachment_menu.aboutToShow.connect(
            lambda menu=attachment_menu, index=persistent_index: (
                self._update_attachment_menu_state(menu, QModelIndex(index))
            )
        )

        return attachment_menu

    def _add_menu_action(
        self,
        menu: QMenu,
        object_name: str,
        icon: QIcon,
        text: str,
        slot=None,
    ) -> QAction:
        action = (
            menu.addAction(icon, text, slot)
            if slot
            else menu.addAction(
                icon,
                text,
            )
        )
        action.setObjectName(object_name)
        return action

    def _menu_actions(self, menu: QMenu) -> _AttachmentMenuActions:
        actions = menu.property("attachmentActions")
        if isinstance(actions, _AttachmentMenuActions):
            return actions

        return _AttachmentMenuActions(
            open_attachment=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.open_attachment,
            ),
            cache_attachment=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.cache_attachment,
            ),
            edit_attachment=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.edit_attachment,
            ),
            show_in_folder=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.show_in_folder,
            ),
            copy_attachment=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.copy_attachment,
            ),
            save_as=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.save_as,
            ),
            delete_attachment=self._required_menu_action(
                menu,
                self.MENU_ACTION_NAMES.delete_attachment,
            ),
        )

    def _required_menu_action(self, menu: QMenu, object_name: str) -> QAction:
        action = menu.findChild(QAction, object_name)
        if action is None:
            message = f"Attachment menu action is missing: {object_name}"
            raise RuntimeError(message)

        return action

    def _update_attachment_menu_state(
        self, menu: QMenu, index: QModelIndex
    ) -> None:
        """
        Update actions visibility/text based on model state.
        """
        is_cached = bool(index.data(AttachmentsModel.Roles.IS_CACHED))
        is_editable = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
        mime_type = str(index.data(AttachmentsModel.Roles.MIME_TYPE) or "")
        actions = self._menu_actions(menu)

        actions.open_attachment.setText(
            QCoreApplication.translate("AttachmentDelegate", "Open")
            if is_cached
            else QCoreApplication.translate(
                "AttachmentDelegate", "Download and Open"
            )
        )
        actions.cache_attachment.setVisible(not is_cached)
        actions.edit_attachment.setEnabled(is_editable)
        actions.show_in_folder.setVisible(is_cached)
        actions.copy_attachment.setEnabled(
            is_cached and mime_type.startswith("image/")
        )
        actions.delete_attachment.setEnabled(is_editable)

    def _fetch_values(
        self, index: QModelIndex, is_edit: bool = False
    ) -> Tuple[object, str, str]:
        state = AttachmentDisplayState.from_index(index, for_editor=is_edit)
        return state.icon_value, state.title, state.description

    def _resolve_colors(
        self, option: QStyleOptionViewItem
    ) -> Tuple[QPalette, QColor, QColor]:
        palette: QPalette = option.palette
        text_color = (
            palette.color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText
            )
            if option.state & QStyle.StateFlag.State_Selected
            else palette.color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.Text
            )
        )
        return palette, text_color, text_color

    def _compute_layout(
        self,
        option: QStyleOptionViewItem,
        icon_value: object,
        title: str,
        description: str,
        tool_size: Optional[QSize] = None,
    ) -> "AttachmentDelegate._Layout":
        rect = option.rect.adjusted(
            self.OUTER_MARGIN_H,
            self.OUTER_MARGIN_V,
            -self.OUTER_MARGIN_H,
            -self.OUTER_MARGIN_V,
        )
        icon_rect = QRect(
            rect.left(),
            rect.top(),
            self._thumbnail_size.width(),
            self._thumbnail_size.height(),
        )
        middle_left = icon_rect.right() + 1 + self.SPACING
        tool_font = QFont(option.font)
        tool_metrics = QFontMetrics(tool_font)

        # Determine tool button size from widget when available
        if tool_size is None:
            # Fallback: approximate minimal size so text area can reserve space
            tool_w = tool_metrics.horizontalAdvance(self.TOOL_TEXT) + 20
            tool_h = max(24, tool_metrics.height() + 8)
        else:
            tool_w = tool_size.width()
            tool_h = tool_size.height()

        # Right-align the tool rect and center it vertically within the item
        tool_rect = QRect(
            rect.right() - tool_w,
            rect.top() + max(0, (rect.height() - tool_h) // 2),
            tool_w,
            tool_h,
        )
        middle_rect = QRect(
            middle_left,
            rect.top(),
            max(0, tool_rect.left() - middle_left - self.SPACING),
            rect.height(),
        )
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_metrics = QFontMetrics(title_font)
        desc_font = QFont(option.font)
        desc_metrics = QFontMetrics(desc_font)
        line_spacing = 2
        available_h = middle_rect.height()
        title_h = title_metrics.height()
        desc_h = desc_metrics.height()
        total_h = title_h + line_spacing + desc_h
        base_y = middle_rect.y() + (available_h - total_h) // 2
        title_rect = QRect(
            middle_rect.x(), base_y, middle_rect.width(), title_h
        )
        desc_rect = QRect(
            middle_rect.x(),
            title_rect.bottom() + 1 + line_spacing,
            middle_rect.width(),
            desc_h,
        )
        elided_title = title_metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, middle_rect.width()
        )
        elided_desc = desc_metrics.elidedText(
            description, Qt.TextElideMode.ElideRight, middle_rect.width()
        )
        # When sizing comes from the widget, inner equals the actual rect
        tool_rect_inner = QRect(tool_rect)
        return self._Layout(
            rect=rect,
            icon_rect=icon_rect,
            middle_rect=middle_rect,
            tool_rect=tool_rect,
            title_rect=title_rect,
            desc_rect=desc_rect,
            tool_rect_inner=tool_rect_inner,
            title_metrics=title_metrics,
            desc_metrics=desc_metrics,
            tool_metrics=tool_metrics,
            title_font=title_font,
            desc_font=desc_font,
            tool_font=tool_font,
            title_text=title,
            desc_text=description,
            elided_title=elided_title,
            elided_desc=elided_desc,
            line_spacing=line_spacing,
        )

    def _draw_background(
        self, painter: QPainter, option: QStyleOptionViewItem
    ) -> None:
        style = (
            option.widget.style() if option.widget else QgsApplication.style()
        )
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            option,
            painter,
            option.widget,
        )

    def _draw_icon(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        state: AttachmentDisplayState,
        layout: "AttachmentDelegate._Layout",
    ) -> None:
        if state.is_loading:
            self._ensure_loading_animation_running()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        self._icon_painter.paint(
            painter,
            layout.icon_rect,
            state,
            palette=option.palette,
            selected=selected,
            loading_angle=self._loading_angle,
            show_loading_progress=self._is_loading_progress_visible(state),
        )
        if state.is_loading or isinstance(state.icon_value, (QIcon, QPixmap)):
            return

        palette = option.palette
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawRect(layout.icon_rect)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        placeholder_font = QFont(layout.title_font)
        placeholder_font.setItalic(True)
        painter.setFont(placeholder_font)
        painter.drawText(
            layout.icon_rect, Qt.AlignmentFlag.AlignCenter, "{icon}"
        )

    def _ensure_loading_animation_running(self) -> None:
        if self._loading_timer.isActive():
            return

        self._loading_last_frame_time = time.monotonic()
        self._loading_timer.start()

    def _is_loading_progress_visible(
        self,
        state: AttachmentDisplayState,
    ) -> bool:
        if not state.is_loading:
            if state.attachment_identity is not None:
                self._loading_started_at_by_attachment_identity.pop(
                    state.attachment_identity,
                    None,
                )
            return False

        if state.attachment_identity is None:
            return True

        current_time = time.monotonic()
        started_at = self._loading_started_at_by_attachment_identity.get(
            state.attachment_identity
        )
        if started_at is None:
            self._loading_started_at_by_attachment_identity[
                state.attachment_identity
            ] = current_time
            return False

        elapsed_ms = (current_time - started_at) * 1000.0
        return elapsed_ms >= self.LOADING_INDICATOR_DELAY_MS

    def _advance_loading_animation(self) -> None:
        if not self._has_loading_items():
            self._loading_timer.stop()
            self._loading_angle = 0.0
            self._loading_last_frame_time = None
            return

        current_time = time.monotonic()
        previous_time = self._loading_last_frame_time or current_time
        elapsed_seconds = max(
            0.0,
            min(
                self.LOADING_MAX_FRAME_SECONDS,
                current_time - previous_time,
            ),
        )
        self._loading_last_frame_time = current_time
        self._loading_angle = (
            self._loading_angle
            + elapsed_seconds * self.LOADING_ROTATION_DEGREES_PER_SECOND
        ) % 360.0
        if not self._has_valid_item_view():
            return

        self._item_view.viewport().update()

    def _has_loading_items(self) -> bool:
        if not self._has_valid_item_view():
            self._loading_started_at_by_attachment_identity.clear()
            return False

        model = self._item_view.model()
        if model is None:
            self._loading_started_at_by_attachment_identity.clear()
            return False

        has_loading_items = False
        loading_attachment_identities: Set[Tuple[int, int]] = set()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            state = AttachmentDisplayState.from_index(index)
            if state.is_loading:
                has_loading_items = True
                if state.attachment_identity is not None:
                    loading_attachment_identities.add(
                        state.attachment_identity
                    )

        if not has_loading_items:
            self._loading_started_at_by_attachment_identity.clear()
            return False

        self._remove_finished_loading_items(loading_attachment_identities)
        return True

    def _remove_finished_loading_items(
        self,
        loading_attachment_identities: Set[Tuple[int, int]],
    ) -> None:
        for attachment_identity in list(
            self._loading_started_at_by_attachment_identity
        ):
            if attachment_identity not in loading_attachment_identities:
                self._loading_started_at_by_attachment_identity.pop(
                    attachment_identity,
                    None,
                )

    def _draw_text_blocks(
        self,
        painter: QPainter,
        layout: "AttachmentDelegate._Layout",
        text_color: QColor,
        secondary_text_color: QColor,
    ) -> None:
        painter.setFont(layout.title_font)
        painter.setPen(text_color)
        painter.drawText(
            layout.title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            layout.elided_title,
        )
        painter.setFont(layout.desc_font)
        painter.setPen(secondary_text_color)
        painter.drawText(
            layout.desc_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            layout.elided_desc,
        )

    # Editor API
    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        """
        Create a composite editor that mirrors the display layout:
        - Left icon placeholder (QLabel) paints icon/pixmap
        - Middle column: two QLineEdit widgets for title and description
        - Right: QToolButton with the same menu as display widgets
        """
        self.close_current_editor()

        # Compute initial layout using current option and model data
        state = AttachmentDisplayState.from_index(index, for_editor=True)
        icon_value = state.icon_value
        title = state.title
        description = state.description
        layout = self._compute_layout(
            option,
            icon_value,
            title,
            description,
        )

        container = QWidget(parent)
        container.setContentsMargins(0, 0, 0, 0)

        # Icon label
        icon_label = QLabel(container)
        icon_label.setObjectName("editorIconLabel")
        icon_label.setAutoFillBackground(False)
        pixmap = self._editor_icon_pixmap(state, option.palette)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)
        else:
            # Fallback: empty label with border via style sheet
            icon_label.setStyleSheet("border: 1px solid palette(mid);")

        # Title and description editors
        title_edit = QLineEdit(container)
        title_edit.setObjectName("editorTitle")
        title_edit.setText(title)
        title_edit.setPlaceholderText(
            QCoreApplication.translate("AttachmentDelegate", "Attachment name")
        )
        title_edit.setContentsMargins(0, 0, 0, 0)
        # Align text vertically centered like painted labels
        title_edit.setAlignment(
            cast(
                Qt.Alignment,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        )
        # Remove extra inner text margins for precise alignment
        try:
            title_edit.setTextMargins(0, 0, 0, 0)
        except AttributeError:
            logger.debug("QLineEdit.setTextMargins is unavailable")

        title_edit.textEdited.connect(
            lambda _: self.commitData.emit(container)
        )
        title_edit.returnPressed.connect(self.close_current_editor)
        title_edit.installEventFilter(self)

        # Keep default frame/padding to indicate edit mode
        # Use bold font to match display
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_edit.setFont(title_font)

        desc_edit = QLineEdit(container)
        desc_edit.setObjectName("editorDescription")
        desc_edit.setText(description)
        desc_edit.setPlaceholderText(
            QCoreApplication.translate(
                "AttachmentDelegate", "Attachment description"
            )
        )
        desc_edit.setContentsMargins(0, 0, 0, 0)
        desc_edit.setAlignment(
            cast(
                Qt.Alignment,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        )
        try:
            desc_edit.setTextMargins(0, 0, 0, 0)
        except AttributeError:
            logger.debug("QLineEdit.setTextMargins is unavailable")
        # Keep default frame/padding to indicate edit mode
        desc_edit.setFont(QFont(option.font))
        desc_edit.textEdited.connect(lambda _: self.commitData.emit(container))
        desc_edit.returnPressed.connect(self.close_current_editor)
        desc_edit.installEventFilter(self)

        # Tool button with actions menu
        tool_button = QToolButton(container)
        tool_button.setObjectName("editorToolButton")
        tool_button.setIcon(material_icon("more_vert"))
        tool_button.setAutoRaise(True)
        tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tool_button.setStyleSheet(
            """
            QToolButton::menu-indicator { image: none; }
            """
        )

        # Build the same actions as in item widgets
        attachment_menu = self._build_attachment_menu(tool_button, index)
        tool_button.setMenu(attachment_menu)

        # Apply cached/visibility states consistent with display
        self._update_attachment_menu_state(attachment_menu, index)

        # Editor mode specifics: keep Edit action checked and close editor
        edit_menu_action = attachment_menu.findChild(
            QAction, "editAttachmentAction"
        )
        if edit_menu_action is not None:
            edit_menu_action.setCheckable(True)
            edit_menu_action.setChecked(True)
            # Close the editor on click
            try:
                edit_menu_action.triggered.connect(self.close_current_editor)
            except RuntimeError:
                logger.debug("Cannot connect destroyed edit action")

        # Recompute layout with actual tool button size to avoid mismatch
        layout = self._compute_layout(
            option,
            icon_value,
            title,
            description,
            tool_size=tool_button.sizeHint(),
        )

        # Position editor in option rect; children in local coords
        container.setGeometry(option.rect)

        def _to_local(r: QRect) -> QRect:
            return QRect(
                r.left() - option.rect.left(),
                r.top() - option.rect.top(),
                r.width(),
                r.height(),
            )

        icon_label.setGeometry(_to_local(layout.icon_rect))
        tool_button.setGeometry(_to_local(layout.tool_rect))
        tool_button.setFixedSize(layout.tool_rect.size())
        title_edit.setGeometry(_to_local(layout.title_rect))
        desc_edit.setGeometry(_to_local(layout.desc_rect))

        def set_title_focus():
            title_edit.setFocus()

        QTimer.singleShot(0, set_title_focus)

        # Store reference to the opened editor
        self._current_editor = container
        return container

    def destroyEditor(self, editor: QWidget, index: QModelIndex) -> None:  # type: ignore[override]
        # Clear tracked editor when it is being destroyed
        if getattr(self, "_current_editor", None) is editor:
            self._current_editor = None

        super().destroyEditor(editor, index)

    def _editor_icon_pixmap(
        self,
        state: AttachmentDisplayState,
        palette: QPalette,
    ) -> QPixmap:
        if not isinstance(state.icon_value, (QIcon, QPixmap)):
            return QPixmap()

        pixmap = QPixmap(self._thumbnail_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        self._icon_painter.paint(
            painter,
            QRect(
                0,
                0,
                self._thumbnail_size.width(),
                self._thumbnail_size.height(),
            ),
            state,
            palette=palette,
            selected=False,
            loading_angle=self._loading_angle,
        )
        painter.end()
        return pixmap

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        """Populate editor widgets from the model index."""
        title_value = index.data(AttachmentsModel.Roles.NAME)
        desc_value = index.data(AttachmentsModel.Roles.DESCRIPTION)
        title = title_value if isinstance(title_value, str) else ""
        description = desc_value if isinstance(desc_value, str) else ""

        title_edit = editor.findChild(QLineEdit, "editorTitle")
        desc_edit = editor.findChild(QLineEdit, "editorDescription")
        if title_edit is not None:
            self._set_line_edit_text_preserving_cursor(title_edit, title)
        if desc_edit is not None:
            self._set_line_edit_text_preserving_cursor(
                desc_edit,
                description,
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if self._is_editor_return_key_event(watched, event):
            editor = cast(QLineEdit, watched).parentWidget()
            if editor is not None:
                self.commitData.emit(editor)

            self.close_current_editor()
            event.accept()
            return True

        return super().eventFilter(watched, event)

    @staticmethod
    def _set_line_edit_text_preserving_cursor(
        line_edit: QLineEdit,
        text: str,
    ) -> None:
        if line_edit.text() == text:
            return

        cursor_position = line_edit.cursorPosition()
        selection_start = line_edit.selectionStart()
        selected_text_length = len(line_edit.selectedText())
        was_modified = line_edit.isModified()

        line_edit.setText(text)

        if selection_start >= 0 and selected_text_length > 0:
            safe_selection_start = min(selection_start, len(text))
            line_edit.setSelection(
                safe_selection_start,
                min(selected_text_length, len(text) - safe_selection_start),
            )
        else:
            line_edit.setCursorPosition(min(cursor_position, len(text)))

        line_edit.setModified(was_modified)

    @staticmethod
    def _is_editor_return_key_event(
        watched: QObject,
        event: QEvent,
    ) -> bool:
        if not isinstance(watched, QLineEdit):
            return False

        if watched.objectName() not in {"editorTitle", "editorDescription"}:
            return False

        if event.type() != QEvent.Type.KeyPress:
            return False

        key_event = cast(QKeyEvent, event)
        return key_event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        )

    def setModelData(self, editor: QWidget, model, index: QModelIndex) -> None:
        """Store edited values back to the model.

        When a proxy model is used for sorting, map the index to the
        source model before setting data to avoid editing wrong rows.
        """
        title_edit = editor.findChild(QLineEdit, "editorTitle")
        title_text = title_edit.text() if title_edit is not None else ""
        desc_edit = editor.findChild(QLineEdit, "editorDescription")
        desc_text = desc_edit.text() if desc_edit is not None else ""

        # Map through proxy if needed
        source_index = index
        source_model = model
        if isinstance(model, QSortFilterProxyModel):
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()

        if source_model is None or not source_index.isValid():
            return

        # Update name and description in the source model
        source_model.setData(
            source_index, title_text, int(AttachmentsModel.Roles.NAME)
        )
        source_model.setData(
            source_index, desc_text, int(AttachmentsModel.Roles.DESCRIPTION)
        )

    def updateEditorGeometry(
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        """Keep editor aligned with the delegate's display layout."""
        icon_value, title, description = self._fetch_values(
            index,
            is_edit=True,
        )
        tool_button = editor.findChild(QToolButton, "editorToolButton")
        layout = self._compute_layout(
            option,
            icon_value,
            title,
            description,
            tool_size=tool_button.sizeHint() if tool_button else None,
        )
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setGeometry(option.rect)
        icon_label = editor.findChild(QLabel, "editorIconLabel")
        tool_button = editor.findChild(QToolButton, "editorToolButton")
        title_edit = editor.findChild(QLineEdit, "editorTitle")
        desc_edit = editor.findChild(QLineEdit, "editorDescription")

        def _to_local(r: QRect) -> QRect:
            return QRect(
                r.left() - option.rect.left(),
                r.top() - option.rect.top(),
                r.width(),
                r.height(),
            )

        if icon_label is not None:
            icon_label.setGeometry(_to_local(layout.icon_rect))
        if tool_button is not None:
            tool_button.setGeometry(_to_local(layout.tool_rect))
            tool_button.setFixedSize(layout.tool_rect.size())
        if title_edit is not None:
            title_edit.setGeometry(_to_local(layout.title_rect))
            title_edit.setFixedHeight(layout.title_rect.height())
        if desc_edit is not None:
            desc_edit.setGeometry(_to_local(layout.desc_rect))
            desc_edit.setFixedHeight(layout.desc_rect.height())

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QSize:
        """
        Return preferred item size similar to the attached .ui layout.

        Compute minimal size as follows:

        - Height: respect outer vertical margins and ensure at least the
          size of the icon (48) or the combined height of title + spacing +
          description, and enforce a minimum of 62px as in the .ui file.
                - Width: minimal — icon block (48) + spacing + outer horizontal
                    margins. Text width is not included to avoid imposing a minimum
                    width; content will be elided to fit the available viewport.

        The text column width depends on available content; since sizeHint
        is content-dependent, we estimate by measuring current strings.
        """
        # Fonts and metrics
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_metrics = QFontMetrics(title_font)

        desc_font = QFont(option.font)
        desc_metrics = QFontMetrics(desc_font)

        # Text heights
        line_spacing = 2
        title_h = title_metrics.height()
        desc_h = desc_metrics.height()
        text_block_h = title_h + line_spacing + desc_h

        # Width composition (no text width to avoid minimum width)
        width = (
            self.OUTER_MARGIN_H
            + self._thumbnail_size.width()
            + self.SPACING
            + self.OUTER_MARGIN_H
        )

        # Height composition and minimum from .ui (62)
        inner_h = max(self._thumbnail_size.height(), text_block_h)
        height = self.OUTER_MARGIN_V + inner_h + self.OUTER_MARGIN_V
        if height < 62:
            height = 62

        return QSize(int(width), int(height))

    def has_current_editor(self) -> bool:
        """Check if there is a currently opened editor."""
        return self._current_editor is not None

    def close_current_editor(self) -> None:
        """Close the currently opened editor, if any."""
        if self._current_editor is None:
            return

        try:
            self.closeEditor.emit(
                self._current_editor,
                AttachmentDelegate.EndEditHint.NoHint,
            )
        except RuntimeError:
            logger.debug("Cannot close an already destroyed editor")

        if self._has_valid_item_view():
            self.item_view().setFocus()

        self._current_editor = None
