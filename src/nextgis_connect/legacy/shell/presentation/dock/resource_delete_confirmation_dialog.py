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

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QModelIndex, QSize, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw.core.ngw_resource import (
    NGWResourceDeletePreview,
    NGWResourceDeleteSummary,
)
from nextgis_connect.legacy.tree_widget.model import (
    NGWResourceModelResponse,
    QNGWResourceTreeModel,
)
from nextgis_connect.ui_kit.buttons.loading import LoadingPushButton
from nextgis_connect.ui_kit.graphics import (
    NextgisDecorator,
)
from nextgis_connect.ui_kit.icons import (
    icon_with_disabled_pixmap,
    material_icon,
    ngw_resource_type_icon,
)


class ResourceDeleteConfirmationDialog(QDialog):
    _COUNTDOWN_SECONDS = 5
    _ICON_SIZE = 16
    _SUMMARY_VERTICAL_MARGIN = 8
    _RESOURCE_TYPE_ORDER = (
        "resource_group",
        "webmap",
        "vector_layer",
        "raster_layer",
        "qgis_vector_style",
        "qgis_raster_style",
        "raster_style",
        "mapserver_style",
        "basemap_layer",
    )

    def __init__(
        self,
        resource_model: QNGWResourceTreeModel,
        indexes: List[QModelIndex],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._resource_model = resource_model
        self._indexes = list(indexes)
        self._preview: Optional[NGWResourceDeletePreview] = None
        self._preview_response: Optional[NGWResourceModelResponse] = None
        self._seconds_left = self._COUNTDOWN_SECONDS
        self._is_delete_allowed = False

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

        self._setup_ui()
        self._set_loading_state()
        QTimer.singleShot(0, self._load_preview)

    def done(self, result: int) -> None:
        self._countdown_timer.stop()
        super().done(result)

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("Confirmation required"))
        self.setModal(True)

        main_layout = QVBoxLayout(self)
        main_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self._message_label = QLabel(self)
        self._message_label.setTextFormat(Qt.TextFormat.RichText)
        self._message_label.setWordWrap(True)
        self._message_label.setMinimumWidth(460)
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

        self._summary_widget = QWidget(self)
        self._summary_widget.setVisible(False)
        self._summary_widget.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.Fixed,
        )
        self._summary_layout = QGridLayout(self._summary_widget)
        self._summary_layout.setContentsMargins(
            0,
            self._SUMMARY_VERTICAL_MARGIN,
            0,
            self._SUMMARY_VERTICAL_MARGIN,
        )
        self._summary_layout.setHorizontalSpacing(8)
        self._summary_layout.setVerticalSpacing(6)
        self._summary_layout.setColumnStretch(1, 1)

        self._unaffected_label = QLabel(self)
        self._unaffected_label.setWordWrap(True)
        self._unaffected_label.setVisible(False)
        self._unaffected_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

        self._delete_button = LoadingPushButton(parent=self)
        self._delete_button.setAutoDefault(False)
        self._delete_button.setDefault(False)
        self._delete_button.setIconSize(
            QSize(self._ICON_SIZE, self._ICON_SIZE)
        )
        self._delete_button.clicked.connect(self._on_delete_clicked)

        self._button_box = QDialogButtonBox(self)
        self._button_box.addButton(
            self._delete_button,
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        cancel_button = self._button_box.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )
        cancel_button.setText(self.tr("Cancel"))
        self._button_box.rejected.connect(self.reject)

        main_layout.addWidget(self._message_label)
        main_layout.addWidget(self._summary_widget)
        main_layout.addWidget(self._unaffected_label)
        main_layout.addWidget(self._button_box)

    def _set_loading_state(self) -> None:
        self._message_label.setText(
            self.tr("Calculating resources that will be deleted...")
        )
        self._delete_button.setText(self.tr("Delete"))
        self._delete_button.setEnabled(True)
        self._delete_button.start()

    def _load_preview(self) -> None:
        response = self._resource_model.loadDeletePreview(self._indexes)
        if response is None:
            self._show_preview_error(self.tr("Failed to load delete summary"))
            return

        self._preview_response = response
        response.delete_preview_loaded.connect(self._on_preview_loaded)
        response.failed.connect(self._on_preview_failed)

    def _on_preview_loaded(
        self,
        preview: NGWResourceDeletePreview,
    ) -> None:
        self._preview = preview
        self._delete_button.stop()
        self._render_summary(preview.affected)
        self._render_unaffected_warning(preview.unaffected)

        affected_count = preview.affected.count
        # fmt: off
        message = self.tr(
            "Please confirm deleting the selected resource and all child "
            "resources. <b>%n resource(s)</b> will be deleted forever.",
            "",
            affected_count
        )
        # fmt: on
        self._message_label.setText(
            self._resource_plural_display_text(message, affected_count)
        )

        if affected_count <= 0:
            self._delete_button.setText(self.tr("Nothing to delete"))
            self._delete_button.setEnabled(False)
            return

        self._set_delete_icon()
        self._start_countdown()

    def _on_preview_failed(self, error: object) -> None:
        message = self.tr("Failed to load delete summary")
        error_text = str(error).strip()
        if error_text != "":
            message = f"{message}: {error_text}"

        self._show_preview_error(message)

    def _show_preview_error(self, message: str) -> None:
        self._countdown_timer.stop()
        self._delete_button.stop()
        self._delete_button.setText(self.tr("Delete"))
        self._delete_button.setEnabled(False)
        self._summary_widget.setVisible(False)
        self._unaffected_label.setVisible(False)
        self._message_label.setText(message)

    def _render_summary(self, summary: NGWResourceDeleteSummary) -> None:
        self._clear_summary()
        self._summary_widget.setVisible(True)
        resources = dict(summary.resources)
        if len(resources) == 0 and summary.count > 0:
            resources["resource"] = summary.count

        if len(resources) == 0:
            empty_label = QLabel(self.tr("Nothing to delete"), self)
            self._summary_layout.addWidget(empty_label, 0, 0, 1, 3)
            return

        for row, resource_class in enumerate(
            self._sorted_resource_classes(resources)
        ):
            icon_label = QLabel(self._summary_widget)
            icon_label.setPixmap(
                self._resource_icon(resource_class).pixmap(
                    QSize(self._ICON_SIZE, self._ICON_SIZE)
                )
            )
            icon_label.setFixedSize(self._ICON_SIZE, self._ICON_SIZE)

            title_label = QLabel(
                self._resource_type_title(resource_class),
                self._summary_widget,
            )

            count_label = QLabel(
                self._resource_count_text(resources[resource_class]),
                self._summary_widget,
            )
            count_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            self._summary_layout.addWidget(
                icon_label,
                row,
                0,
                alignment=Qt.AlignmentFlag.AlignTop,
            )
            self._summary_layout.addWidget(title_label, row, 1)
            self._summary_layout.addWidget(count_label, row, 2)

        self.adjustSize()

    def _clear_summary(self) -> None:
        while self._summary_layout.count() > 0:
            item = self._summary_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_unaffected_warning(
        self,
        summary: NGWResourceDeleteSummary,
    ) -> None:
        if summary.count <= 0:
            self._unaffected_label.setVisible(False)
            return

        # fmt: off
        message = self.tr(
            "Some resources cannot be deleted and will be skipped: "
            "%n resource(s)",
            "",
            summary.count
        )
        # fmt: on
        self._unaffected_label.setText(
            self._resource_plural_display_text(message, summary.count)
        )
        self._unaffected_label.setVisible(True)

    def _start_countdown(self) -> None:
        self._seconds_left = self._COUNTDOWN_SECONDS
        self._is_delete_allowed = False
        self._delete_button.setEnabled(False)
        self._update_delete_button_text()
        self._countdown_timer.start()

    def _on_countdown_tick(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left <= 0:
            self._countdown_timer.stop()
            self._is_delete_allowed = True
            self._delete_button.setEnabled(True)

        self._update_delete_button_text()

    def _update_delete_button_text(self) -> None:
        if self._preview is None:
            return

        text = self.tr("Delete")
        if not self._is_delete_allowed:
            text = f"{text} {self._seconds_left}"

        self._delete_button.setText(text)

    def _on_delete_clicked(self) -> None:
        if not self._is_delete_allowed:
            return

        if self._preview is None or self._preview.affected.count <= 0:
            return

        self.accept()

    def _set_delete_icon(self) -> None:
        icon = material_icon(
            "delete_forever",
            color=self._delete_icon_color(),
            size=self._ICON_SIZE,
        )
        self._delete_button.setIcon(
            icon_with_disabled_pixmap(
                icon,
                QSize(self._ICON_SIZE, self._ICON_SIZE),
            )
        )

    def _delete_icon_color(self) -> str:
        color_key = (
            "color.dark.danger"
            if NextgisDecorator.is_dark_theme(self.palette())
            else "color.light.danger"
        )
        return NextgisDecorator.theme().color(color_key, "#B8324A").name()

    def _resource_icon(self, resource_class: str):
        return ngw_resource_type_icon(resource_class=resource_class)

    def _sorted_resource_classes(
        self,
        resources: Dict[str, int],
    ) -> List[str]:
        order = {
            resource_class: i
            for i, resource_class in enumerate(self._RESOURCE_TYPE_ORDER)
        }

        return sorted(
            resources,
            key=lambda resource_class: (
                order.get(resource_class, len(order)),
                self._resource_type_title(resource_class).casefold(),
            ),
        )

    def _resource_type_title(self, resource_class: str) -> str:
        if self._preview is not None:
            resource_label = self._preview.resource_labels.get(resource_class)
            if resource_label is not None:
                return resource_label

        return resource_class.replace("_", " ")

    def _resource_count_text(self, count: int) -> str:
        text = self.tr("%n resource(s)", "", count)
        return self._resource_plural_display_text(text, count)

    def _resource_plural_display_text(self, text: str, count: int) -> str:
        resource_word = "resource" if count == 1 else "resources"
        return text.replace("resource(s)", resource_word)
