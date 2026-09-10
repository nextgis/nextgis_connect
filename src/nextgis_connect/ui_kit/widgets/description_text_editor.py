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

from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from qgis.core import Qgis, QgsNetworkAccessManager
from qgis.gui import QgsCodeEditorHTML, QgsColorButton, QgsRichTextEditor
from qgis.PyQt.QtCore import (
    QByteArray,
    QObject,
    QRectF,
    QSizeF,
    QTextStream,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import (
    QImage,
    QPainter,
    QPixmap,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
    QTextLength,
    QTextObjectInterface,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtXml import QDomDocument, QDomNode

from nextgis_connect.platform.qgis.compat import QGIS_3_42, QT_VERSION_MAJOR
from nextgis_connect.ui_kit.icons.icon import material_icon

QStringConverter = None
if QT_VERSION_MAJOR == 6:
    from qgis.PyQt.QtCore import QStringConverter


class _AdaptiveImageHandler(QObject, QTextObjectInterface):
    """Draw image objects at their natural size or the document width."""

    def __init__(self, text_edit: QTextEdit) -> None:
        super().__init__(text_edit)
        self._text_edit = text_edit
        self._pending_image_requests: Dict[
            str, Tuple[QTextDocument, QUrl]
        ] = {}
        self._failed_image_urls: Set[str] = set()

    def intrinsicSize(
        self,
        doc: Optional[QTextDocument],
        posInDocument: int,
        format: QTextFormat,
    ) -> QSizeF:
        del posInDocument
        if doc is None:
            return QSizeF()
        image_format = format.toImageFormat()
        image_size = self._image_size(doc, image_format)
        if image_size is None:
            return QSizeF(
                image_format.width() or 16,
                image_format.height() or 16,
            )

        image_width, image_height = image_size
        maximum_width = doc.pageSize().width()
        if maximum_width <= 0:
            maximum_width = self._text_edit.viewport().width()
        maximum_width -= doc.documentMargin() * 2
        maximum_width = self._maximum_image_width(image_format, maximum_width)
        if maximum_width > 0 and image_width > maximum_width:
            image_height *= maximum_width / image_width
            image_width = maximum_width

        return QSizeF(image_width, image_height)

    def drawObject(
        self,
        painter: Optional[QPainter],
        rect: QRectF,
        doc: Optional[QTextDocument],
        posInDocument: int,
        format: QTextFormat,
    ) -> None:
        if painter is None or doc is None:
            return
        del posInDocument
        image_resource = self._image_resource(doc, format.toImageFormat())
        if isinstance(image_resource, QPixmap):
            painter.drawPixmap(
                rect,
                image_resource,
                QRectF(image_resource.rect()),
            )
        elif isinstance(image_resource, QImage):
            painter.drawImage(
                rect,
                image_resource,
                QRectF(image_resource.rect()),
            )
        else:
            painter.drawRect(rect)

    def _image_size(
        self, document: QTextDocument, image_format: QTextImageFormat
    ) -> Optional[Tuple[float, float]]:
        image_resource = self._image_resource(document, image_format)
        if not isinstance(image_resource, (QImage, QPixmap)):
            return None

        device_pixel_ratio = image_resource.devicePixelRatio()
        natural_width = image_resource.width() / device_pixel_ratio
        natural_height = image_resource.height() / device_pixel_ratio
        if natural_width <= 0 or natural_height <= 0:
            return None

        width = image_format.width() or natural_width
        height = image_format.height() or natural_height
        if image_format.width() and not image_format.height():
            height = natural_height * width / natural_width
        elif image_format.height() and not image_format.width():
            width = natural_width * height / natural_height

        return width, height

    def _image_resource(
        self, document: QTextDocument, image_format: QTextImageFormat
    ) -> Any:
        image_resource = document.resource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(image_format.name()),
        )
        if isinstance(image_resource, (QImage, QPixmap)):
            return image_resource

        image = QImage()
        if isinstance(image_resource, QByteArray):
            if image.loadFromData(image_resource):
                return image
            return None

        image_url = document.baseUrl().resolved(QUrl(image_format.name()))
        if image_url.isLocalFile():
            image_path = image_url.toLocalFile()
        elif image_url.scheme() == "qrc":
            image_path = f":{image_url.path()}"
        elif not image_url.scheme():
            image_path = image_url.path()
        else:
            if image_url.scheme() in ("http", "https"):
                self._request_remote_image(
                    document,
                    QUrl(image_format.name()),
                    image_url,
                )
            return None

        device_pixel_ratio = self._text_edit.devicePixelRatioF()
        image_pixel_ratio = 1
        if device_pixel_ratio > 1 and not image_path.startswith(":"):
            source_path = Path(image_path)
            pixel_ratio = ceil(device_pixel_ratio)
            high_dpi_path = source_path.with_name(
                f"{source_path.stem}@{pixel_ratio}x{source_path.suffix}"
            )
            if high_dpi_path.is_file():
                image_path = str(high_dpi_path)
                image_pixel_ratio = pixel_ratio

        if not image.load(image_path):
            return None
        image.setDevicePixelRatio(image_pixel_ratio)
        return image

    def _request_remote_image(
        self,
        document: QTextDocument,
        resource_url: QUrl,
        request_url: QUrl,
    ) -> None:
        request_key = request_url.toString()
        if (
            request_key in self._pending_image_requests
            or request_key in self._failed_image_urls
        ):
            return

        network_manager = QgsNetworkAccessManager.instance()
        reply = network_manager.get(QNetworkRequest(request_url))
        self._pending_image_requests[request_key] = (document, resource_url)
        reply.finished.connect(self._on_remote_image_finished)

    def _on_remote_image_finished(self) -> None:
        reply = self.sender()
        if not isinstance(reply, QNetworkReply):
            return

        request_key = reply.request().url().toString()
        request = self._pending_image_requests.pop(request_key, None)
        if request is None:
            reply.deleteLater()
            return

        document, resource_url = request
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._failed_image_urls.add(request_key)
            reply.deleteLater()
            return

        image = QImage()
        if not image.loadFromData(reply.readAll()):
            self._failed_image_urls.add(request_key)
            reply.deleteLater()
            return

        document.addResource(
            QTextDocument.ResourceType.ImageResource,
            resource_url,
            image,
        )
        document.markContentsDirty(0, document.characterCount())
        self._text_edit.viewport().update()
        reply.deleteLater()

    def _maximum_image_width(
        self, image_format: QTextImageFormat, available_width: float
    ) -> float:
        maximum_width_method = getattr(image_format, "maximumWidth", None)
        if not callable(maximum_width_method):
            return available_width

        maximum_width: Any = maximum_width_method()
        if maximum_width.type() not in (
            QTextLength.Type.PercentageLength,
            QTextLength.Type.FixedLength,
        ):
            return available_width
        return min(available_width, maximum_width.value(available_width))


class DescriptionTextEditor(QgsRichTextEditor):
    """Provide a text editor for NextGIS Web descriptions.

    QgsRichTextEditor has some features that are not supported by NextGIS Web,
    such as support for tables, font sizes, and text colors. This class patches
    the editor to remove those features and ensure that the content is stored
    in a consistent format with styles converted to tags.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the editor.

        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self._collect_widgets()
        self._install_adaptive_image_handler()
        self.set_read_only(True)

        QTimer.singleShot(0, self._patch)

    @property
    def text_edit(self) -> QTextEdit:
        """Get the internal QTextEdit widget of the rich text editor.

        :return: The QTextEdit widget used for editing the description.
        """
        return self._text_edit

    def set_read_only(self, read_only: bool) -> None:
        """Set the read-only state of the text editor.

        :param read_only: ``True`` to set the editor to read-only mode,
            ``False`` to make it editable.
        """

        self._text_edit.setReadOnly(read_only)
        self._tool_bar.setDisabled(read_only)

    def set_content(self, content: str) -> None:
        """Set the editor content.

        :param content: HTML content to display in the editor.
        """
        if Qgis.versionInt() < QGIS_3_42:
            # Old QgsRichTextEditor had issues with leading whitespace, so we
            # need to strip it.
            content = content.lstrip()

        self.setText(content)

    def content(self) -> str:
        """Get the HTML body content of the text editor.

        :return: The HTML body content as a string.
        """
        return self._process_html_body(self.toHtml())

    def _install_adaptive_image_handler(self) -> None:
        document = self._text_edit.document()
        if document is None:
            return
        layout = document.documentLayout()
        if layout is None:
            return

        self._adaptive_image_handler = _AdaptiveImageHandler(self._text_edit)
        layout.unregisterHandler(QTextFormat.ObjectTypes.ImageObject)
        layout.registerHandler(
            QTextFormat.ObjectTypes.ImageObject,
            self._adaptive_image_handler,
        )

    def _process_html_body(self, full_html: str) -> str:
        doc = QDomDocument()
        if not doc.setContent(full_html):
            return full_html

        bodies = doc.elementsByTagName("body")
        if bodies.isEmpty():
            return full_html

        body_node = bodies.item(0)

        self._convert_styles_to_tags(doc, body_node)
        self._move_trailing_link_whitespace(doc, body_node)
        self._remove_style_attr(body_node)

        result_container = QByteArray()
        text_stream = QTextStream(result_container)
        if hasattr(text_stream, "setEncoding"):
            text_stream.setEncoding(QStringConverter.Encoding.Utf8)
        elif hasattr(text_stream, "setCodec"):
            text_stream.setCodec("UTF-8")  # pyright: ignore[reportAttributeAccessIssue]
        body_node.save(text_stream, 0)

        result_data = result_container.data()
        result = (
            result_data
            if isinstance(result_data, str)
            else result_data.decode()
        )

        return f"<html>{result}</html>"

    def _parse_style_attr(self, style_value: str) -> dict:
        # Parse CSS style string into dict of lowercased properties/values.
        result: dict = {}
        if not style_value:
            return result
        for part in style_value.split(";"):
            if ":" not in part:
                continue
            name, value = part.split(":", 1)
            name_clean = name.strip().lower()
            value_clean = " ".join(value.strip().lower().split())
            if name_clean:
                result[name_clean] = value_clean
        return result

    def _wrap_children_with_tag(
        self, doc: QDomDocument, node: QDomNode, tag_name: str
    ) -> None:
        # Wrap all children of element into a new tag.
        if not node.isElement():
            return
        element = node.toElement()
        wrapper = doc.createElement(tag_name)
        while not element.firstChild().isNull():
            child = element.firstChild()
            element.removeChild(child)
            wrapper.appendChild(child)
        element.appendChild(wrapper)

    def _contains_non_whitespace_text(self, node: QDomNode) -> bool:
        if node.isText():
            return bool(node.nodeValue().strip())

        child = node.firstChild()
        while not child.isNull():
            if self._contains_non_whitespace_text(child):
                return True
            child = child.nextSibling()
        return False

    def _take_text_nodes(self, node: QDomNode) -> List[QDomNode]:
        text_nodes = []
        child = node.firstChild()
        while not child.isNull():
            next_sibling = child.nextSibling()
            node.removeChild(child)
            if child.isText():
                text_nodes.append(child)
            else:
                text_nodes.extend(self._take_text_nodes(child))
            child = next_sibling
        return text_nodes

    def _take_trailing_link_text(
        self, doc: QDomDocument, link: QDomNode, text_node: QDomNode
    ) -> Optional[List[QDomNode]]:
        text = text_node.nodeValue()
        text_without_trailing_whitespace = text.rstrip()
        if text_without_trailing_whitespace == text:
            return None

        if text_without_trailing_whitespace:
            text_node.setNodeValue(text_without_trailing_whitespace)
            trailing_whitespace = text[len(text_without_trailing_whitespace) :]
            return [doc.createTextNode(trailing_whitespace)]

        link.removeChild(text_node)
        return [text_node]

    def _take_trailing_link_node(
        self, doc: QDomDocument, link: QDomNode
    ) -> Optional[List[QDomNode]]:
        last_child = link.lastChild()
        if last_child.isNull():
            return None

        if last_child.isText():
            return self._take_trailing_link_text(doc, link, last_child)

        if not last_child.isElement() or self._contains_non_whitespace_text(
            last_child
        ):
            return None

        link.removeChild(last_child)
        return self._take_text_nodes(last_child)

    def _insert_after_link(
        self,
        parent: QDomNode,
        link: QDomNode,
        whitespace_nodes: List[QDomNode],
    ) -> None:
        reference_node = link
        for whitespace_node in reversed(whitespace_nodes):
            whitespace_node.setNodeValue(
                "\xa0" * len(whitespace_node.nodeValue())
            )
            parent.insertAfter(whitespace_node, reference_node)
            reference_node = whitespace_node

    def _move_trailing_link_whitespace(
        self, doc: QDomDocument, node: QDomNode
    ) -> None:
        child = node.firstChild()
        while not child.isNull():
            next_sibling = child.nextSibling()
            self._move_trailing_link_whitespace(doc, child)
            child = next_sibling

        if not node.isElement() or node.toElement().tagName().lower() != "a":
            return

        parent = node.parentNode()
        if parent.isNull():
            return

        whitespace_nodes = []
        while True:
            trailing_nodes = self._take_trailing_link_node(doc, node)
            if trailing_nodes is None:
                break
            whitespace_nodes.extend(trailing_nodes)

        self._insert_after_link(parent, node, whitespace_nodes)

        if node.firstChild().isNull():
            parent.removeChild(node)

    def _has_inline_style(self, node: QDomNode) -> bool:
        return (
            node.isElement()
            and node.toElement().tagName().lower() == "span"
            and node.toElement().hasAttribute("style")
        )

    def _formatting_tags(self, node: QDomNode) -> List[str]:
        if not self._has_inline_style(node):
            return []

        style_map = self._parse_style_attr(node.toElement().attribute("style"))
        tags = []
        if style_map.get("font-weight") == "600":
            tags.append("b")
        if style_map.get("font-style") == "italic":
            tags.append("i")

        text_decoration = style_map.get("text-decoration", "")
        if "underline" in text_decoration:
            tags.append("u")
        if "line-through" in text_decoration:
            tags.append("s")
        return tags

    def _convert_styles_to_tags(
        self, doc: QDomDocument, node: QDomNode
    ) -> None:
        # QTextDocument uses block styles for layout, so only convert inline
        # styles to character tags.
        has_inline_style = self._has_inline_style(node)
        if has_inline_style and self._contains_non_whitespace_text(node):
            for tag in self._formatting_tags(node):
                self._wrap_children_with_tag(doc, node, tag)

        child = node.firstChild()
        while not child.isNull():
            next_sibling = child.nextSibling()
            self._convert_styles_to_tags(doc, child)
            child = next_sibling

        # Unwrap span elements that had inline styles so span does not remain.
        if has_inline_style:
            self._unwrap_element(node)

    def _unwrap_element(self, node: QDomNode) -> None:
        # Replace the element with its children, removing the element itself.
        if not node.isElement():
            return
        parent = node.parentNode()
        if parent.isNull():
            return
        ref = node.nextSibling()
        # Move children before the reference (or append at end).
        while not node.firstChild().isNull():
            child = node.firstChild()
            node.removeChild(child)
            if ref.isNull():
                parent.appendChild(child)
            else:
                parent.insertBefore(child, ref)
        parent.removeChild(node)

    def _remove_style_attr(self, node: QDomNode) -> None:
        # Remove style attribute if this node is an element.
        if node.isElement():
            element = node.toElement()
            if element.hasAttribute("style"):
                element.removeAttribute("style")

        child = node.firstChild()
        while not child.isNull():
            self._remove_style_attr(child)
            child = child.nextSibling()

    def _collect_widgets(self) -> None:
        self._text_edit = self.findChild(QTextEdit, "mTextEdit")
        self._action_undo = self.findChild(QAction, "mActionUndo")
        self._action_redo = self.findChild(QAction, "mActionRedo")
        self._action_cut = self.findChild(QAction, "mActionCut")
        self._action_copy = self.findChild(QAction, "mActionCopy")
        self._action_paste = self.findChild(QAction, "mActionPaste")
        self._action_insert_link = self.findChild(QAction, "mActionInsertLink")
        self._action_bold = self.findChild(QAction, "mActionBold")
        self._action_italic = self.findChild(QAction, "mActionItalic")
        self._action_underline = self.findChild(QAction, "mActionUnderline")
        self._action_strike_out = self.findChild(QAction, "mActionStrikeOut")
        self._action_bullet_list = self.findChild(QAction, "mActionBulletList")
        self._action_ordered_list = self.findChild(
            QAction, "mActionOrderedList"
        )
        self._action_decrease_indent = self.findChild(
            QAction, "mActionDecreaseIndent"
        )
        self._action_increase_indent = self.findChild(
            QAction, "mActionIncreaseIndent"
        )
        self._action_insert_image = self.findChild(
            QAction, "mActionInsertImage"
        )
        self._action_edit_source = self.findChild(QAction, "mActionEditSource")
        self._vertical_layout = self.findChild(QVBoxLayout, "verticalLayout")
        self._tool_bar = self.findChild(QToolBar, "mToolBar")
        self._stacked_widget = self.findChild(QStackedWidget, "mStackedWidget")
        self._page_rich_edit = self.findChild(QWidget, "mPageRichEdit")
        self._vertical_layout_2 = self.findChild(
            QVBoxLayout, "verticalLayout_2"
        )
        self._source_edit = self.findChild(QgsCodeEditorHTML)
        self._page_source_edit = self.findChild(QWidget, "mPageSourceEdit")

        for combo_box in self.findChildren(QComboBox):
            if combo_box.count() == 6:
                self._paragraph_style_combo_box = combo_box
            else:
                self._font_size_combo_box = combo_box

    @pyqtSlot()
    def _patch(self) -> None:
        # Patch paragraph combobox
        self._paragraph_style_combo_box.removeItem(5)
        self._paragraph_style_combo_box.removeItem(4)
        self._paragraph_style_combo_box.setItemIcon(
            0, material_icon("format_paragraph")
        )
        self._paragraph_style_combo_box.setItemIcon(
            1, material_icon("format_h1")
        )
        self._paragraph_style_combo_box.setItemIcon(
            2, material_icon("format_h2")
        )
        self._paragraph_style_combo_box.setItemIcon(
            3, material_icon("format_h3")
        )
        font_metrics = self._font_size_combo_box.fontMetrics()
        max_text_width = max(
            [
                font_metrics.horizontalAdvance(
                    self._paragraph_style_combo_box.itemText(i)
                )
                for i in range(self._paragraph_style_combo_box.count())
            ]
        )
        icon_width = self._paragraph_style_combo_box.iconSize().width()
        extra_space = 40
        self._paragraph_style_combo_box.view().setMinimumWidth(
            max_text_width + icon_width + extra_space
        )

        # Add missing icons
        self._action_bullet_list.setIcon(material_icon("format_list_bulleted"))
        self._action_ordered_list.setIcon(
            material_icon("format_list_numbered")
        )

        # Replace existing icons with material icons
        self._action_bold.setIcon(material_icon("format_bold"))
        self._action_italic.setIcon(material_icon("format_italic"))
        self._action_underline.setIcon(material_icon("format_underlined"))
        self._action_strike_out.setIcon(material_icon("format_strikethrough"))
        self._action_insert_link.setIcon(material_icon("add_link"))
        self._action_insert_image.setIcon(material_icon("add_photo_alternate"))

        hidden_actions = (
            self._action_undo,
            self._action_redo,
            self._action_cut,
            self._action_copy,
            self._action_paste,
            self._action_increase_indent,
            self._action_decrease_indent,
            self._action_edit_source,
        )
        hidden_widgets = (self._font_size_combo_box,)
        for action in self._tool_bar.actions():
            if action in hidden_actions:
                action.setVisible(False)
                continue

            widget = self._tool_bar.widgetForAction(action)
            if isinstance(widget, QgsColorButton) or widget in hidden_widgets:
                action.setVisible(False)
