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

from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QColor, QImage
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

from nextgis_connect.platform.qgis.opengl import panorama_renderer_available
from nextgis_connect.ui_kit.widgets.image_preview import (
    ImagePreviewDialog,
    ImagePreviewItem,
    ImagePreviewMode,
)
from nextgis_connect.ui_kit.widgets.panorama import PanoramaWidget


def _write_png(path: Path, width: int, height: int) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6bb2"))

    assert image.save(str(path))


def _delete_dialog(dialog: ImagePreviewDialog) -> None:
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(
        dialog,
        QEvent.Type.DeferredDelete,
    )


def test_image_preview_dialog_has_no_brand_suffix_by_default(
    qgis_app,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.png"
    _write_png(image_path, 12, 8)

    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)],
        0,
    )
    try:
        assert dialog.window_title_suffix == ""
        assert dialog.windowTitle() == "photo.png - 12x8"
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_uses_configured_window_title_suffix(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    image_path = tmp_path / "photo.png"
    _write_png(image_path, 12, 8)

    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)],
        0,
        window_title_suffix="Host Plugin",
    )
    try:
        assert dialog.window_title_suffix == "Host Plugin"
        assert dialog.windowTitle() == "photo.png - 12x8 - Host Plugin"

        dialog.window_title_suffix = ""

        assert dialog.windowTitle() == "photo.png - 12x8"
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_handles_empty_items(qgis_app) -> None:
    del qgis_app

    dialog = ImagePreviewDialog([], 0, window_title_suffix="Host Plugin")
    try:
        assert dialog.windowTitle() == "Image preview - Host Plugin"
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_uses_configured_background(qgis_app) -> None:
    del qgis_app

    dialog = ImagePreviewDialog([ImagePreviewItem(None, "photo.png")], 0)
    try:
        background_color = ImagePreviewDialog.BACKGROUND_COLOR

        assert background_color == "#202326"
        assert dialog.objectName() == "imagePreviewDialog"
        assert background_color in dialog.styleSheet()
        assert background_color in dialog._scroll_area.styleSheet()
        assert background_color in dialog._scroll_area.viewport().styleSheet()
        assert background_color in dialog._image_label.styleSheet()
        assert background_color in dialog._loading_overlay.styleSheet()
        assert background_color not in dialog._panel.styleSheet()
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_counter_fits_two_digit_values(qgis_app) -> None:
    items = [
        ImagePreviewItem(None, f"photo-{index}.png") for index in range(22)
    ]

    dialog = ImagePreviewDialog(items, 0)
    try:
        dialog.show()
        qgis_app.processEvents()

        counter_label = dialog._counter_label
        reserved_text = "22 / 22"

        assert counter_label.text() == "1 / 22"
        assert counter_label.alignment() == Qt.AlignmentFlag.AlignCenter
        assert dialog._previous_button.property("navUnavailable") is True
        assert dialog._next_button.property("navUnavailable") is False
        assert (
            counter_label.fontMetrics().horizontalAdvance(reserved_text)
            <= counter_label.width()
        )
        assert dialog._navigation_widget.width() == (
            dialog._previous_button.width()
            + counter_label.width()
            + dialog._next_button.width()
            + dialog.NAVIGATION_SPACING * 2
        )

        left_gap = (
            counter_label.geometry().left()
            - dialog._previous_button.geometry().right()
            - 1
        )
        right_gap = (
            dialog._next_button.geometry().left()
            - counter_label.geometry().right()
            - 1
        )

        assert left_gap >= dialog.NAVIGATION_SPACING
        assert right_gap >= dialog.NAVIGATION_SPACING
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_boundary_buttons_show_status(qgis_app) -> None:
    del qgis_app

    dialog = ImagePreviewDialog([ImagePreviewItem(None, "photo.png")], 0)
    try:
        assert dialog._previous_button.isEnabled()
        assert dialog._next_button.isEnabled()
        assert dialog._previous_button.property("navUnavailable") is True
        assert dialog._next_button.property("navUnavailable") is True

        dialog._previous_button.click()

        assert dialog._zoom_label_text.text() == "First image"

        dialog._next_button.click()

        assert dialog._zoom_label_text.text() == "Last image"
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_prefetches_adjacent_items(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    requested_indices = []
    items = [
        ImagePreviewItem(tmp_path / f"photo-{index}.png", f"photo-{index}.png")
        for index in range(5)
    ]

    def ensure_item_ready(index: int) -> bool:
        requested_indices.append(index)
        return True

    dialog = ImagePreviewDialog(
        items,
        2,
        ensure_item_ready=ensure_item_ready,
        prefetch_radius=1,
    )
    try:
        assert requested_indices == [2, 3, 1]
        assert dialog._image_ready_check_timer.isActive()
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_loads_file_when_async_request_finishes(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    image_path = tmp_path / "photo.png"

    def ensure_item_ready(index: int) -> bool:
        del index
        return True

    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)],
        0,
        ensure_item_ready=ensure_item_ready,
    )
    try:
        assert dialog._source_pixmap.isNull()

        _write_png(image_path, 12, 8)
        dialog._try_load_current_item()

        assert not dialog._source_pixmap.isNull()
        assert dialog.windowTitle() == "photo.png - 12x8"
        assert not dialog._image_ready_check_timer.isActive()
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_keeps_panel_visible_under_cursor(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    dialog = ImagePreviewDialog([ImagePreviewItem(None, "photo.png")], 0)
    try:
        dialog._panel_opacity.setOpacity(dialog.ACTIVE_PANEL_OPACITY)
        monkeypatch.setattr(dialog, "_is_cursor_over_panel", lambda: True)

        dialog._set_idle_panel_opacity()

        assert dialog._panel_opacity.opacity() == dialog.ACTIVE_PANEL_OPACITY
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_exposes_panorama_mode_for_metadata(
    qgis_app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "panorama.png"
    _write_png(image_path, 12, 8)
    mode_changes = []
    dialog = ImagePreviewDialog(
        [
            ImagePreviewItem(
                image_path,
                image_path.name,
                projection_type="equirectangular",
            )
        ],
        0,
        initial_mode=ImagePreviewMode.FLAT,
        preview_mode_changed=mode_changes.append,
    )
    try:
        assert dialog._panorama_widget is None
        dialog.show()
        for _ in range(3):
            qgis_app.processEvents()

        assert dialog._is_panorama_available
        assert dialog._preview_mode == ImagePreviewMode.FLAT
        assert not dialog._view_mode_button.isHidden()
        if dialog._is_panorama_renderer_available:
            QTest.mouseClick(
                dialog._view_mode_button,
                Qt.MouseButton.LeftButton,
            )

            assert dialog._preview_mode == ImagePreviewMode.PANORAMA
            assert mode_changes == [ImagePreviewMode.PANORAMA]
        else:
            warning_messages = []
            monkeypatch.setattr(
                QMessageBox,
                "warning",
                lambda *_arguments: warning_messages.append(_arguments),
            )
            dialog._toggle_preview_mode()

            assert dialog._panorama_widget is None
            assert dialog._preview_mode == ImagePreviewMode.FLAT
            assert len(warning_messages) == 1
    finally:
        _delete_dialog(dialog)


def test_panorama_blank_frame_check() -> None:
    white_frame = QImage(3, 3, QImage.Format.Format_RGBA8888)
    white_frame.fill(QColor("white"))
    assert PanoramaWidget._is_blank_frame(white_frame)

    background_frame = QImage(3, 3, QImage.Format.Format_RGBA8888)
    background_frame.fill(QColor(32, 35, 38))
    assert PanoramaWidget._is_blank_frame(background_frame)

    rendered_frame = QImage(3, 3, QImage.Format.Format_RGBA8888)
    rendered_frame.fill(QColor("blue"))
    assert not PanoramaWidget._is_blank_frame(rendered_frame)


def test_panorama_drag_cancels_interaction_hint(qgis_app) -> None:
    del qgis_app

    panorama_widget = PanoramaWidget()
    try:
        panorama_widget._has_shown_interaction_hint = True
        panorama_widget._set_interaction_hint_yaw(6.0)

        panorama_widget.start_drag(QPoint())

        assert panorama_widget._has_shown_interaction_hint
        assert panorama_widget._yaw == 6.0
    finally:
        panorama_widget.deleteLater()


def test_panorama_image_resets_interaction_hint(qgis_app) -> None:
    del qgis_app

    panorama_widget = PanoramaWidget()
    try:
        panorama_widget._has_shown_interaction_hint = True
        image = QImage(2, 2, QImage.Format.Format_RGB32)

        panorama_widget.set_image(image)

        assert not panorama_widget._has_shown_interaction_hint
        assert not panorama_widget._interaction_hint_timer.isActive()
    finally:
        panorama_widget.deleteLater()


def test_image_preview_dialog_preserves_view_state_between_modes(
    qgis_app,
    tmp_path: Path,
) -> None:
    if not panorama_renderer_available():
        return

    image_path = tmp_path / "panorama.png"
    _write_png(image_path, 120, 80)
    dialog = ImagePreviewDialog(
        [
            ImagePreviewItem(
                image_path,
                image_path.name,
                projection_type="equirectangular",
            ),
            ImagePreviewItem(
                image_path,
                image_path.name,
                projection_type="equirectangular",
            ),
        ],
        0,
    )
    try:
        dialog.show()
        qgis_app.processEvents()
        panorama_widget = dialog._panorama_widget
        assert panorama_widget is not None
        assert dialog._preview_mode == ImagePreviewMode.PANORAMA
        assert dialog.cursor().shape() == Qt.CursorShape.OpenHandCursor

        panorama_widget.start_drag(QPoint())
        panorama_widget.drag_to(QPoint(20, 10))
        panorama_widget.end_drag()
        assert panorama_widget._yaw == 3.0
        assert panorama_widget._pitch == 1.5
        panorama_widget.zoom_in()
        panorama_state = (
            panorama_widget._yaw,
            panorama_widget._pitch,
            panorama_widget.fov,
        )
        dialog._toggle_preview_mode()

        assert dialog._preview_mode == ImagePreviewMode.FLAT
        assert not dialog._image_label.pixmap().isNull()
        dialog._zoom = 4.0
        dialog._rotation = 90
        dialog._is_fit_to_window = False
        dialog._temporary_pan_offset = QPoint(8, 4)
        dialog._update_image()

        dialog._toggle_preview_mode()

        assert dialog._preview_mode == ImagePreviewMode.PANORAMA
        assert (
            panorama_widget._yaw,
            panorama_widget._pitch,
            panorama_widget.fov,
        ) == panorama_state

        dialog._toggle_preview_mode()

        assert dialog._preview_mode == ImagePreviewMode.FLAT
        assert dialog._zoom == 4.0
        assert dialog._rotation == 90
        assert not dialog._is_fit_to_window
        assert dialog._temporary_pan_offset == QPoint(8, 4)

        dialog._show_next_item()

        assert dialog._rotation == 0
        assert dialog._is_fit_to_window
        assert dialog._temporary_pan_offset.isNull()
        dialog._toggle_preview_mode()

        assert dialog._preview_mode == ImagePreviewMode.PANORAMA
        assert panorama_widget._yaw == 0.0
        assert panorama_widget._pitch == 0.0
        assert panorama_widget.fov == panorama_widget.DEFAULT_FOV
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_places_panorama_toggle_in_toolbar_layout(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    image_path = tmp_path / "panorama.png"
    _write_png(image_path, 12, 8)
    dialog = ImagePreviewDialog(
        [
            ImagePreviewItem(
                image_path,
                image_path.name,
                projection_type="equirectangular",
            )
        ],
        0,
    )
    try:
        toolbar_layout = dialog._panel.layout().itemAt(1).layout()

        assert dialog._view_mode_button.parent() is dialog._panel
        assert toolbar_layout.indexOf(dialog._view_mode_button) == (
            toolbar_layout.count() - 1
        )
        assert toolbar_layout.indexOf(dialog._fullscreen_button) == (
            toolbar_layout.indexOf(dialog._view_mode_button) - 1
        )
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_expands_panorama_toolbar_to_the_right(
    qgis_app,
    tmp_path: Path,
) -> None:
    if not panorama_renderer_available():
        return

    image_path = tmp_path / "panorama.png"
    _write_png(image_path, 12, 8)
    flat_dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)], 0
    )
    dialog = ImagePreviewDialog(
        [
            ImagePreviewItem(
                image_path,
                image_path.name,
                projection_type="equirectangular",
            )
        ],
        0,
    )
    try:
        flat_dialog.show()
        dialog.show()
        for _ in range(3):
            qgis_app.processEvents()

        assert dialog._panel.width() > flat_dialog._panel.width()
        assert dialog._base_panel_width == flat_dialog._panel.width()
        assert (
            dialog._panel.mapTo(dialog, QPoint()).x()
            == flat_dialog._panel.mapTo(
                flat_dialog,
                QPoint(),
            ).x()
        )
        panel_geometry = dialog._panel.geometry()
        for _ in range(5):
            qgis_app.processEvents()
        assert dialog._panel.geometry() == panel_geometry
        assert (
            QApplication.widgetAt(
                dialog._zoom_in_button.mapToGlobal(
                    dialog._zoom_in_button.rect().center()
                )
            )
            is dialog._zoom_in_button
        )

        buttons = (
            dialog._previous_button,
            dialog._next_button,
            dialog._zoom_in_button,
            dialog._zoom_out_button,
            dialog._rotate_left_button,
            dialog._rotate_right_button,
            dialog._view_mode_button,
        )
        for left_button, right_button in zip(buttons, buttons[1:]):
            left = left_button.mapTo(dialog._panel, QPoint()).x()
            right = right_button.mapTo(dialog._panel, QPoint()).x()
            assert left < right
    finally:
        _delete_dialog(flat_dialog)
        _delete_dialog(dialog)


def test_image_preview_dialog_sizes_zoom_label_for_percentage(
    qgis_app,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.png"
    _write_png(image_path, 12, 8)
    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)], 0
    )
    try:
        dialog._zoom = 8.0
        dialog._show_zoom_label()
        qgis_app.processEvents()

        assert dialog._zoom_label_text.text() == "800%"
        assert dialog._zoom_label.width() >= (
            20
            + dialog.TOOL_ICON_SIZE
            + 6
            + dialog._zoom_label_text.fontMetrics().horizontalAdvance("800%")
        )
        assert dialog._zoom_label.y() == (
            dialog._panel.mapTo(dialog, QPoint()).y()
            + (dialog._panel.height() - dialog._zoom_label.height()) // 2
        )
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_toggles_fullscreen_for_loaded_image(
    qgis_app,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.png"
    _write_png(image_path, 12, 8)
    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)], 0
    )
    try:
        dialog.show()
        qgis_app.processEvents()

        dialog._fullscreen_button.click()
        qgis_app.processEvents()

        assert dialog.isFullScreen()
        assert dialog._fullscreen_button.toolTip() == "Exit full screen"
        assert (
            QApplication.widgetAt(
                dialog._zoom_in_button.mapToGlobal(
                    dialog._zoom_in_button.rect().center()
                )
            )
            is dialog._zoom_in_button
        )

        dialog._fullscreen_button.click()

        assert not dialog.isFullScreen()
        assert dialog._fullscreen_button.toolTip() == "Show full screen"
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_keeps_toolbar_buttons_interactive(
    qgis_app,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "photo.png"
    _write_png(image_path, 12, 8)
    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)], 0
    )
    try:
        dialog.show()
        qgis_app.processEvents()

        QTest.mouseClick(
            dialog._rotate_right_button, Qt.MouseButton.LeftButton
        )
        QTest.mouseClick(
            dialog._rotate_right_button, Qt.MouseButton.LeftButton
        )

        assert dialog._rotation == 180
        assert not dialog._rotate_right_button.isDown()
    finally:
        _delete_dialog(dialog)


def test_image_preview_dialog_does_not_cover_flat_scrollbars(
    qgis_app,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "large.png"
    _write_png(image_path, 1000, 1000)
    dialog = ImagePreviewDialog(
        [ImagePreviewItem(image_path, image_path.name)], 0
    )
    try:
        dialog.resize(200, 200)
        dialog.show()
        qgis_app.processEvents()
        dialog._zoom = 2.0
        dialog._is_fit_to_window = False
        dialog._update_image()
        qgis_app.processEvents()

        vertical_scroll_bar = dialog._scroll_area.verticalScrollBar()
        assert vertical_scroll_bar.isVisible()
        assert not dialog._overlay.geometry().contains(
            vertical_scroll_bar.mapTo(
                dialog, vertical_scroll_bar.rect().center()
            )
        )
    finally:
        _delete_dialog(dialog)
