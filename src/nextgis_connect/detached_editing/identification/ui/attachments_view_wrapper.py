from enum import Enum, auto
from typing import List, Optional

from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
)
from qgis.PyQt.QtWidgets import (
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.detached_editing.identification.attachments_model import (
    AttachmentsModel,
)
from nextgis_connect.detached_editing.identification.ui.attachments_view import (
    AttachmentsView,
)
from nextgis_connect.logging import logger
from nextgis_connect.ui.icon import draw_icon, material_icon


class AttachmentsViewWrapper(QWidget):
    """Wrap the attachments view with overlay and drag-and-drop handling.

    Host the attachments list view and show contextual overlay messages for
    an empty list, drag-and-drop targets, and read-only restrictions.
    Forward dropped local file paths so higher-level widgets can attach them.

    :ivar files_dropped: Emit local file paths dropped onto the wrapper.
    """

    class OverlayMode(Enum):
        HIDDEN = auto()
        EMPTY_LIST = auto()
        DRAG_AND_DROP = auto()
        DRAG_AND_DROP_MULTIPLE = auto()

    OVERLAY_ICON_SIZE = 32

    files_dropped = pyqtSignal(list)  # List[str]

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize the attachments view wrapper.

        :param parent: Parent widget owning the wrapper.
        """
        super().__init__(parent)
        self._is_read_only = True
        self._overlay_mode = self.OverlayMode.HIDDEN
        self._model: Optional[QAbstractItemModel] = None
        self._init_styles()
        self._load_ui()

    @property
    def view(self) -> AttachmentsView:
        """Return the wrapped attachments view.

        :return: The attachments view instance.
        """
        return self._view

    def set_read_only(self, read_only: bool) -> None:
        """Set the read-only state of the attachments view.

        :param read_only: ``True`` to set the view to read-only mode,
            ``False`` to make it editable.
        """
        self._is_read_only = read_only
        self._view.set_read_only(read_only)
        self._refresh_overlay()

    def _load_ui(self) -> None:
        # Allow dropping files onto the wrapper. Dropping in view is disabled
        self.setAcceptDrops(True)

        self._view = AttachmentsView(self)
        self._view.model_changed.connect(self._set_model)

        # Layout with view
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self.setLayout(layout)

        # Overlay container with icon + text
        self._overlay = QWidget(self)
        self._overlay.setObjectName("dragOverlay")
        self._overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._overlay.setStyleSheet(self._empty_list_overlay_style)
        overlay_layout = QVBoxLayout()
        overlay_layout.setContentsMargins(12, 12, 12, 12)
        overlay_layout.setSpacing(2)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._overlay_icon_label = QLabel(self._overlay)
        self._overlay_icon_label.setObjectName("overlayIcon")
        self._overlay_icon_label.setFixedSize(
            self.OVERLAY_ICON_SIZE, self.OVERLAY_ICON_SIZE
        )
        self._overlay_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._overlay_text_label = QLabel(self._overlay)
        self._overlay_text_label.setObjectName("overlayText")
        self._overlay_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_text_label.setWordWrap(True)

        # Keep label from shrinking unpredictably
        self._overlay_text_label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            self._overlay_text_label.sizePolicy().verticalPolicy(),
        )

        overlay_layout.addWidget(
            self._overlay_icon_label, alignment=Qt.AlignmentFlag.AlignCenter
        )
        overlay_layout.addWidget(
            self._overlay_text_label, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self._overlay.setLayout(overlay_layout)
        self._overlay.hide()
        self._overlay.setMinimumWidth(200)

        self._refresh_overlay()

    def _init_styles(self) -> None:
        palette = self.palette()
        disabled_group = palette.ColorGroup.Disabled

        base_style = """
            QWidget#dragOverlay {{
                background-color: {background_color};
            }}
            QLabel#overlayText {{
                color: {text_color};
                font-size: 14px;
                padding: 0 8px 4px 8px;
            }}
        """

        empty_list_text_color = palette.color(
            disabled_group, palette.ColorRole.Text
        ).name()
        self._empty_list_overlay_style = base_style.format(
            background_color="transparent",
            text_color=empty_list_text_color,
        )
        self._empty_list_icon = material_icon(
            "inbox",
            color=empty_list_text_color,
            size=self.OVERLAY_ICON_SIZE,
        )

        drag_and_drop_text_color = "#ffffff"
        self._drag_and_drop_overlay_style = base_style.format(
            background_color="rgba(0, 0, 0, 0.5)",
            text_color=drag_and_drop_text_color,
        )
        self._attach_file_add_icon = material_icon(
            "attach_file_add",
            color=drag_and_drop_text_color,
            size=self.OVERLAY_ICON_SIZE,
        )
        self._attach_file_off_icon = material_icon(
            "attach_file_off",
            color=drag_and_drop_text_color,
            size=self.OVERLAY_ICON_SIZE,
        )

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Resize the overlay to keep it aligned with the embedded view.

        :param event: Resize event dispatched to the wrapper.
        """
        super().resizeEvent(event)
        if not self._view:
            return
        self._overlay.resize(self._view.size())
        self._overlay.move(self._view.pos())
        self._update_overlay_label_width()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        """Validate an incoming drag and update overlay state.

        :param event: Drag enter event dispatched to the wrapper.
        """
        self._init_drag_and_drop(event)
        self._refresh_overlay()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        """Track drag movement and keep the overlay synchronized.

        :param event: Drag move event dispatched to the wrapper.
        """
        if self._overlay_mode in (
            self.OverlayMode.DRAG_AND_DROP,
            self.OverlayMode.DRAG_AND_DROP_MULTIPLE,
        ):
            event.acceptProposedAction()
        else:
            self._init_drag_and_drop(event)

        self._refresh_overlay()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        """Hide the overlay when the drag operation leaves the wrapper.

        :param event: Drag leave event dispatched to the wrapper.
        """
        self._overlay_mode = self.OverlayMode.HIDDEN
        self._refresh_overlay()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        """Emit dropped local file paths when dropping is currently allowed.

        :param event: Drop event dispatched to the wrapper.
        """
        if self._is_read_only or self._overlay_mode not in (
            self.OverlayMode.DRAG_AND_DROP,
            self.OverlayMode.DRAG_AND_DROP_MULTIPLE,
        ):
            self._overlay_mode = self.OverlayMode.HIDDEN
            self._refresh_overlay()
            event.ignore()
            return

        urls = event.mimeData().urls()
        paths: List[str] = []
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                if path:
                    paths.append(path)

        if paths:
            logger.debug(f"Dropped files: {paths}")
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

        self._overlay_mode = self.OverlayMode.HIDDEN
        self._refresh_overlay()

    def _init_drag_and_drop(self, event: QDropEvent) -> None:
        """Prepare drag-and-drop state for events containing local files.

        :param event: Drag or drop event carrying MIME data.
        """
        local_files_count = self._local_files_count(event)
        if local_files_count == 0:
            self._overlay_mode = self.OverlayMode.HIDDEN
            event.ignore()
            return

        self._overlay_mode = (
            self.OverlayMode.DRAG_AND_DROP
            if local_files_count == 1
            else self.OverlayMode.DRAG_AND_DROP_MULTIPLE
        )
        event.acceptProposedAction()

    def _render_drag_and_drop_overlay(self) -> None:
        self._overlay.setStyleSheet(self._drag_and_drop_overlay_style)

        if self._is_read_only:
            draw_icon(
                self._overlay_icon_label,
                self._attach_file_off_icon,
                size=self.OVERLAY_ICON_SIZE,
            )
            self._overlay_text_label.setText(
                self.tr(
                    "Cannot add attachments when layer is not in edit mode"
                )
            )

        else:
            draw_icon(
                self._overlay_icon_label,
                self._attach_file_add_icon,
                size=self.OVERLAY_ICON_SIZE,
            )
            if self._overlay_mode == self.OverlayMode.DRAG_AND_DROP:
                self._overlay_text_label.setText(
                    self.tr("Drop a file here to attach")
                )
            else:
                self._overlay_text_label.setText(
                    self.tr("Drop files here to attach")
                )

        self._show_overlay()

    def _render_empty_overlay(self) -> None:
        self._overlay.setStyleSheet(self._empty_list_overlay_style)
        draw_icon(
            self._overlay_icon_label,
            self._empty_list_icon,
            size=self.OVERLAY_ICON_SIZE,
        )
        self._overlay_text_label.setText(self.tr("No attachments yet"))
        self._show_overlay()

    def _show_overlay(self) -> None:
        self._update_overlay_label_width()
        self._overlay.show()

    def _refresh_overlay(self) -> None:
        if self._overlay_mode in (
            self.OverlayMode.DRAG_AND_DROP,
            self.OverlayMode.DRAG_AND_DROP_MULTIPLE,
        ):
            self._render_drag_and_drop_overlay()
            return

        if self._is_model_initialized() and not self._has_attachments():
            self._overlay_mode = self.OverlayMode.EMPTY_LIST
            self._render_empty_overlay()
            return

        self._overlay_mode = self.OverlayMode.HIDDEN
        self._overlay.hide()

    def _set_model(self, model: Optional[QAbstractItemModel]) -> None:
        """Attach a model and refresh overlay tracking for its changes.

        :param model: Model backing the attachments view.
        """
        if self._model is model:
            self._refresh_overlay()
            return

        if self._model is not None:
            self._disconnect_model_signals(self._model)

        self._model = model

        if self._model is not None:
            self._connect_model_signals(self._model)

        self._refresh_overlay()

    def _connect_model_signals(self, model: QAbstractItemModel) -> None:
        model.modelReset.connect(self._refresh_overlay)
        model.layoutChanged.connect(self._refresh_overlay)
        model.rowsInserted.connect(self._refresh_overlay)
        model.rowsRemoved.connect(self._refresh_overlay)

    def _disconnect_model_signals(self, model: QAbstractItemModel) -> None:
        for signal in (
            model.modelReset,
            model.layoutChanged,
            model.rowsInserted,
            model.rowsRemoved,
        ):
            try:
                signal.disconnect(self._refresh_overlay)
            except TypeError:
                pass

    def _has_attachments(self) -> bool:
        model = self._base_model()
        if model is None:
            return False

        return model.rowCount() > 0

    def _is_model_initialized(self) -> bool:
        model = self._base_model()
        if model is None:
            return False

        if isinstance(model, AttachmentsModel):
            return model.is_initialized

        return True

    def _base_model(self) -> Optional[QAbstractItemModel]:
        model = self._model
        while isinstance(model, QSortFilterProxyModel):
            model = model.sourceModel()

        return model

    def _local_files_count(self, event: QDropEvent) -> int:
        """Count local file URLs carried by a drag or drop event.

        :param event: Drag or drop event carrying MIME data.
        :return: Number of local file URLs, capped once the count exceeds one.
        """
        mime_data = event.mimeData()
        if not mime_data or not mime_data.hasUrls():
            return 0

        local_file_count = 0
        for url in mime_data.urls():
            if url.isLocalFile():
                local_file_count += 1
            if local_file_count > 1:
                # We just want to know if it's more than one
                break

        return local_file_count

    def _update_overlay_label_width(self) -> None:
        if not self._overlay or not self._overlay_text_label:
            return
        margin: int = 32
        available: int = max(0, self._overlay.width() - margin)
        self._overlay_text_label.setFixedWidth(available)
