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

import pytest
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from qgis.PyQt.QtGui import QImage, QTextDocument
from qgis.PyQt.QtNetwork import QHostAddress, QTcpServer
from qgis.PyQt.QtTest import QTest

from nextgis_connect.ui_kit.widgets.description_text_editor import (
    DescriptionTextEditor,
)


def _first_image_format(editor: DescriptionTextEditor):
    document = editor.text_edit.document()
    assert document is not None

    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            char_format = iterator.fragment().charFormat()
            if char_format.isImageFormat():
                return char_format.toImageFormat()
            iterator += 1
        block = block.next()

    pytest.fail("The document does not contain an image")


def _png_data(width: int, height: int) -> QByteArray:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image_data = QByteArray()
    buffer = QBuffer(image_data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return image_data


def test_description_images_fit_viewport_without_changing_content(
    qgis_app,
) -> None:
    editor = DescriptionTextEditor()
    try:
        editor.resize(200, 200)
        editor.show()
        qgis_app.processEvents()

        editor.set_content('<img src="image">')
        document = editor.text_edit.document()
        assert document is not None
        image = QImage(600, 300, QImage.Format.Format_RGB32)
        image.setDevicePixelRatio(2)
        document.addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl("image"),
            image,
        )

        maximum_width = editor.text_edit.viewport().width()
        maximum_width -= int(document.documentMargin() * 2)
        image_format = _first_image_format(editor)
        size = editor._adaptive_image_handler.intrinsicSize(
            document, 0, image_format
        )
        assert size.width() == pytest.approx(maximum_width)
        assert size.height() == pytest.approx(maximum_width / 2)
        assert image_format.width() == 0
        assert image_format.height() == 0

        content = editor.content()
        assert "width=" not in content
        assert "height=" not in content

        editor.resize(800, 200)
        qgis_app.processEvents()
        size = editor._adaptive_image_handler.intrinsicSize(
            document, 0, image_format
        )
        assert size.width() == 300
        assert size.height() == 150
    finally:
        editor.close()
        sip.delete(editor)


def test_description_images_load_from_http(qgis_app) -> None:
    server = QTcpServer()
    assert server.listen(QHostAddress.SpecialAddress.LocalHost)
    image_data = _png_data(600, 300)
    connections = []

    def send_image() -> None:
        connection = server.nextPendingConnection()
        assert connection is not None
        connections.append(connection)
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: image/png\r\n"
            + f"Content-Length: {image_data.size()}\r\n\r\n".encode()
            + bytes(image_data)
        )
        connection.write(response)
        connection.disconnectFromHost()

    server.newConnection.connect(send_image)
    editor = DescriptionTextEditor()
    try:
        editor.resize(200, 200)
        editor.show()
        image_url = QUrl(f"http://127.0.0.1:{server.serverPort()}/image.png")
        editor.set_content(f'<img src="{image_url.toString()}">')
        document = editor.text_edit.document()
        assert document is not None

        for _ in range(100):
            qgis_app.processEvents()
            image_resource = document.resource(
                QTextDocument.ResourceType.ImageResource,
                image_url,
            )
            if isinstance(image_resource, QImage):
                break
            QTest.qWait(10)  # pyright: ignore[reportCallIssue]
        else:
            pytest.fail("The HTTP image was not added to the document")

        image_format = _first_image_format(editor)
        size = editor._adaptive_image_handler.intrinsicSize(
            document, 0, image_format
        )
        assert size.width() < 600
        assert size.height() == pytest.approx(size.width() / 2)
    finally:
        editor.close()
        sip.delete(editor)
        server.close()


def test_description_content_ignores_block_text_decoration(qgis_app) -> None:
    del qgis_app
    editor = DescriptionTextEditor()
    try:
        content = editor._process_html_body(
            "<html><body>"
            '<p style="text-decoration: underline;">First paragraph</p>'
            '<p><span style="text-decoration: underline;">'
            "Underlined text</span></p>"
            "</body></html>"
        )

        assert "<u>First paragraph</u>" not in content
        assert "<u>Underlined text</u>" in content
    finally:
        editor.close()
        sip.delete(editor)


def test_description_content_keeps_link_whitespace_without_underline(
    qgis_app,
) -> None:
    del qgis_app
    editor = DescriptionTextEditor()
    try:
        content = editor._process_html_body(
            "<html><body><p>"
            '<a href="https://example.test"><span '
            'style="text-decoration: underline;">Link</span></a>'
            '<a href="https://example.test"><u> </u></a>'
            "continues"
            "</p></body></html>"
        )

        assert "<u/>" not in content
        assert content.count('<a href="https://example.test">') == 1
        editor.set_content(content)
        assert editor.text_edit.toPlainText().replace("\xa0", " ") == (
            "Link continues"
        )
    finally:
        editor.close()
        sip.delete(editor)
