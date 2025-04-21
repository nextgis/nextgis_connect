from typing import TYPE_CHECKING, Optional, cast

from qgis.gui import QgsNewNameDialog
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QBrush, QKeyEvent, QPainter, QPalette, QPen
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.tree_widget.item import QNGWResourceItem
from nextgis_connect.tree_widget.model import QNGWResourceTreeModel
from nextgis_connect.utils import SupportStatus, utm_tags

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    assert isinstance(iface, QgisInterface)

__all__ = ["QNGWResourceTreeView"]


class QOverlay(QWidget):
    def __init__(
        self, parent: Optional[QWidget], *, draw_background: bool = True
    ):
        super().__init__(parent)

        self.draw_background = draw_background

        if draw_background:
            palette = QPalette(self.palette())
            self._overlay_color = palette.color(QPalette.ColorRole.Window)
            self._overlay_color.setAlpha(200)
            palette.setColor(
                QPalette.ColorRole.Window, Qt.GlobalColor.transparent
            )
            self.setPalette(palette)

    def paintEvent(self, a0):
        if not self.draw_background:
            return

        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(a0.rect(), QBrush(self._overlay_color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))


class QMessageOverlay(QOverlay):
    def __init__(
        self,
        parent: Optional[QWidget],
        text: str,
        *,
        draw_background: bool = True,
    ):
        super().__init__(parent, draw_background=draw_background)
        layout = QHBoxLayout(self)
        self.setLayout(layout)

        self.text = QLabel(text, self)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextBrowserInteraction
        )
        layout.addWidget(self.text)

    def set_text(self, text: str) -> None:
        self.text.setText(text)


class MigrationOverlay(QOverlay):
    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        spacer_before = QSpacerItem(
            20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        spacer_after = QSpacerItem(
            20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )

        self.text = QLabel(
            self.tr(
                "We are transitioning to the QGIS Authentication System to "
                "enhance security and streamline your experience. This change "
                "requires the conversion of existing connections.\n\nPlease be"
                " aware that your current connections will be converted to the"
                " new format automatically. This is a one-time process and "
                "should not affect your workflow.\n"
            ),
            self,
        )
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)

        full_migrate_button = QPushButton(self)
        button_size_policy = full_migrate_button.sizePolicy()
        button_size_policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        full_migrate_button.setSizePolicy(button_size_policy)

        migrate_label = QLabel(
            self.tr("Convert connections and authentication data"),
            full_migrate_button,
        )
        migrate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        migrate_label.setWordWrap(True)

        button_layout = QVBoxLayout(full_migrate_button)
        button_layout.addWidget(migrate_label)
        button_layout.setContentsMargins(6, 6, 6, 6)

        full_migrate_button.clicked.connect(self.__full_migrate)

        layout.addSpacerItem(spacer_before)
        layout.addWidget(self.text)
        layout.addWidget(full_migrate_button)
        layout.addSpacerItem(spacer_after)

    def __full_migrate(self):
        NgwConnectionsManager().convert_old_connections(convert_auth=True)
        self.__reinit()

    def __reinit(self):
        dock = iface.mainWindow().findChild(QWidget, "NGConnectDock")
        dock.reinit_tree(force=True)


class NoNgstdAuthOverlay(QOverlay):
    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        spacer_before = QSpacerItem(
            20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        spacer_after = QSpacerItem(
            20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )

        self.text = QLabel(
            self.tr(
                "Sign in with your NextGIS account to get access to your Web GIS\n"
            ),
            self,
        )
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)

        full_migrate_button = QPushButton(
            self.tr("Open NextGIS QGIS settings")
        )
        full_migrate_button.clicked.connect(self.__open_nextgis_settings)

        layout.addSpacerItem(spacer_before)
        layout.addWidget(self.text)
        layout.addWidget(full_migrate_button)
        layout.addSpacerItem(spacer_after)

    def __open_nextgis_settings(self):
        iface.showOptionsDialog(iface.mainWindow(), "NextGIS")


class QProcessOverlay(QOverlay):
    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        self.setLayout(layout)

        spacer_before = QSpacerItem(
            20, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        layout.addItem(spacer_before)

        self.progress = QProgressBar(self)
        self.progress.setMinimum(0)
        self.progress.setMaximum(0)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.text = QLabel(self)
        self.text.setAlignment(
            Qt.AlignmentFlag(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        )
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        layout.addWidget(self.text)

        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.status_text = QLabel(self)
        self.status_text.setText("")
        self.status_text.setAlignment(
            Qt.AlignmentFlag(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        )
        self.status_text.setOpenExternalLinks(True)
        self.status_text.setWordWrap(True)

        bottom_layout.addWidget(self.status_text)

        spacer_after = QSpacerItem(
            20, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        bottom_layout.addItem(spacer_after)

        layout.addLayout(bottom_layout)

    def write(self, jobs):
        text = ""
        status_text = ""

        if len(jobs) > 0:
            job_name, job_status = list(jobs.items())[-1]
            text += f"<strong>{job_name}</strong>".strip()
            if job_status != "":
                status_text += job_status.replace("\n", "<br/>").strip()

        self.text.setText(text)
        self.status_text.setText(status_text)


class UnsupportedVersionOverlay(QMessageOverlay):
    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent, "")

    def set_status(
        self, status: SupportStatus, ngc_version: str, ngw_version: str
    ) -> None:
        text = ""
        if status == SupportStatus.OLD_CONNECT:
            text = self.tr(
                "NextGIS Connect version is outdated. Please update the "
                "plugin via Plugins - Manage and install plugins menu."
            )
        elif status == SupportStatus.OLD_NGW:
            text = self.tr(
                "NextGIS Web service version is outdated and not supported by "
                "NextGIS Connect. Please contact your server administrator"
                " for further assistance."
            )

        text += "\n\n" + self.tr(
            "NextGIS Connect version: {}\nNextGIS Web version: {}"
        ).format(ngc_version, ngw_version)

        self.set_text(text)


class QNGWResourceTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(QModelIndex)

    def __init__(self, parent: Optional[QWidget]):
        super().__init__(parent)

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)

        header = self.header()
        assert header is not None
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # no ngw connectiond message
        self.no_ngw_connections_overlay = QMessageOverlay(
            self,
            self.tr(
                "No connections to nextgis.com. Please create a connection. "
                "You can get your free Web GIS at "
                '<a href="https://my.nextgis.com/?{}">nextgis.com</a>!'
            ).format(utm_tags("start")),
        )
        self.no_ngw_connections_overlay.hide()

        self.unsupported_version_overlay = UnsupportedVersionOverlay(self)
        self.unsupported_version_overlay.hide()
        self.migration_overlay = MigrationOverlay(self)
        self.migration_overlay.hide()

        self.no_oauth_auth_overlay = NoNgstdAuthOverlay(self)
        self.no_oauth_auth_overlay.hide()

        self.ngw_job_block_overlay = QProcessOverlay(self)
        self.ngw_job_block_overlay.hide()

        self.not_found_overlay = QMessageOverlay(
            self,
            self.tr("No resources were found matching your search query"),
            draw_background=False,
        )
        self.not_found_overlay.text.setEnabled(False)
        self.not_found_overlay.hide()

        self.jobs = {}

    def setModel(self, model: Optional[QAbstractItemModel]) -> None:
        model = cast(QSortFilterProxyModel, model)
        self._source_model = cast(QNGWResourceTreeModel, model.sourceModel())
        self._proxy_model = model
        self._proxy_model.rowsInserted.connect(self.__insertRowsProcess)
        self._proxy_model.layoutChanged.connect(self.__expand_filtered)

        super().setModel(self._proxy_model)

    def __insertRowsProcess(self, parent: QModelIndex):
        if not parent.isValid():
            self.expandToDepth(0)
            return

    def __expand_filtered(self) -> None:
        for resource_id in self._proxy_model.expanded_resources:  # type: ignore
            index = self._source_model.index_from_id(resource_id)
            self.expand(self._proxy_model.mapFromSource(index))

    def resizeEvent(self, e):
        self.no_ngw_connections_overlay.resize(e.size())
        self.ngw_job_block_overlay.resize(e.size())
        self.unsupported_version_overlay.resize(e.size())
        self.migration_overlay.resize(e.size())
        self.no_oauth_auth_overlay.resize(e.size())
        self.not_found_overlay.resize(e.size())

        super().resizeEvent(e)

    def mouseDoubleClickEvent(self, e):
        index = self.indexAt(e.pos())
        if index.isValid():
            self.itemDoubleClicked.emit(index)

        super().mouseDoubleClickEvent(e)

    def showWelcomeMessage(self):
        self.no_ngw_connections_overlay.show()

    def hideWelcomeMessage(self):
        self.no_ngw_connections_overlay.hide()

    def addBlockedJob(self, job_name):
        self.jobs.update({job_name: ""})
        self.ngw_job_block_overlay.write(self.jobs)

        self.ngw_job_block_overlay.show()

    def addJobStatus(self, job_name, status):
        if job_name in self.jobs:
            self.jobs[job_name] = status
            self.ngw_job_block_overlay.write(self.jobs)

    def removeBlockedJob(self, job_name, check_overlay=True):
        if job_name in self.jobs:
            self.jobs.pop(job_name)
            self.ngw_job_block_overlay.write(self.jobs)

        if check_overlay:
            self.check_overlay()

    def check_overlay(self):
        if len(self.jobs) == 0:
            self.ngw_job_block_overlay.hide()

    def keyPressEvent(self, event: Optional[QKeyEvent]) -> None:
        is_f2 = event.key() == Qt.Key.Key_F2
        index = self.currentIndex()
        if is_f2 and index.isValid():
            self.rename_resource(index)
        else:
            super().keyPressEvent(event)

    def rename_resource(self, index: QModelIndex):
        # Get current resource name. This name can differ from display
        # text of tree item (see style resources).

        index = self._proxy_model.mapToSource(index)

        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        current_name = ngw_resource.display_name

        # Get existing names
        existing_names = []
        parent = index.parent()
        if parent.isValid():
            model = self._source_model
            assert model is not None
            for i in range(model.rowCount(parent)):
                if i == index.row():
                    continue

                sibling_index = model.index(i, 0, parent)
                sibling_resource = sibling_index.data(
                    QNGWResourceItem.NGWResourceRole
                )
                existing_names.append(sibling_resource.display_name)

        dialog = QgsNewNameDialog(
            initial=current_name,
            existing=existing_names,
            cs=Qt.CaseSensitivity.CaseSensitive,
            parent=iface.mainWindow(),
        )
        dialog.setWindowTitle(self.tr("Change resource name"))
        dialog.setOverwriteEnabled(False)
        dialog.setAllowEmptyName(False)
        dialog.setHintString(self.tr("Enter new name for selected resource"))
        dialog.setConflictingNameWarning(self.tr("Resource already exists"))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = dialog.name()

        if new_name == current_name:
            return

        self.__rename_resource_resp = self._source_model.renameResource(
            index, new_name
        )
        self.__rename_resource_resp.done.connect(  # type: ignore
            lambda index: self.setCurrentIndex(
                self._proxy_model.mapFromSource(index)
            )
        )
