from typing import Optional

from qgis.core import Qgis
from qgis.gui import QgsCodeEditorHTML, QgsColorButton, QgsRichTextEditor
from qgis.PyQt.QtCore import (
    QByteArray,
    QTextStream,
    QTimer,
    pyqtSlot,
)
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

from nextgis_connect.compat import QGIS_3_42, QT_VERSION_MAJOR
from nextgis_connect.ui.icon import material_icon

QStringConverter = None
if QT_VERSION_MAJOR == 6:
    from qgis.PyQt.QtCore import QStringConverter


class DescriptionTextEditor(QgsRichTextEditor):
    """A text editor for editing NextGIS Web descriptions.

    QgsRichTextEditor has some features that are not supported by NextGIS Web,
    such as support for tables, font sizes, and text colors. This class patches
    the editor to remove those features and ensure that the content is stored
    in a consistent format with styles converted to tags.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._collect_widgets()
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

    def _process_html_body(self, full_html: str) -> str:
        doc = QDomDocument()
        if not doc.setContent(full_html):
            return full_html

        bodies = doc.elementsByTagName("body")
        if bodies.isEmpty():
            return full_html

        body_node = bodies.item(0)

        self._convert_styles_to_tags(doc, body_node)
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

    def _convert_styles_to_tags(
        self, doc: QDomDocument, node: QDomNode
    ) -> None:
        # If node is element and has style, convert known styles to tags.
        had_style = False
        if node.isElement():
            element = node.toElement()
            had_style = element.hasAttribute("style")
            if had_style:
                style_map = self._parse_style_attr(element.attribute("style"))

                tags_to_apply = []

                font_weight = style_map.get("font-weight")
                if font_weight == "600":
                    tags_to_apply.append("b")

                font_style = style_map.get("font-style")
                if font_style == "italic":
                    tags_to_apply.append("i")

                text_decoration = style_map.get("text-decoration", "")
                if "underline" in text_decoration:
                    tags_to_apply.append("u")
                if "line-through" in text_decoration:
                    tags_to_apply.append("s")

                for tag in tags_to_apply:
                    self._wrap_children_with_tag(doc, node, tag)

        child = node.firstChild()
        while not child.isNull():
            next_sibling = child.nextSibling()
            self._convert_styles_to_tags(doc, child)
            child = next_sibling

        # Unwrap span elements that had inline styles so span does not remain.
        if node.isElement():
            element = node.toElement()
            if had_style and element.tagName().lower() == "span":
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
