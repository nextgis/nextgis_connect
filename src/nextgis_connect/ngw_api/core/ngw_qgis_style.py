"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2016-06-02
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from pathlib import Path
from typing import Optional

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from nextgis_connect.exceptions import NgwError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)

from .ngw_resource import NGWResource


class NGWQGISStyle(NGWResource):
    def __init__(self, resource_factory, resource_json):
        super().__init__(resource_factory, resource_json)
        self.__qml = None

    @property
    def is_qml_populated(self) -> bool:
        return self.__qml is not None

    def populate_qml(self) -> None:
        """
        Download and populate the QML style content for this resource.

        If the QML content is already populated, the method does nothing.
        Downloads the QML style from the server using the resource's connection
        and stores it in the internal attribute.

        :raises NgwError: If the QML style could not be downloaded.
        """
        if self.__qml is not None:
            return

        logger.debug(f"Download qml style with id={self.resource_id}")

        qml_url = self.download_qml_url()
        qml_req = QNetworkRequest(QUrl(qml_url))

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(self.connection_id)
        connection.update_network_request(qml_req)

        dwn_qml_manager = QgsNetworkAccessManager()
        reply_content = dwn_qml_manager.blockingGet(qml_req, forceRefresh=True)

        if reply_content.error() != QNetworkReply.NetworkError.NoError:
            raise NgwError(
                f"Failed to download QML: {reply_content.errorString()}"
            )

        self.__qml = reply_content.content().data().decode()

    @property
    def qml(self) -> Optional[str]:
        return self.__qml

    def download_qml_url(self):
        return self.get_absolute_api_url() + "/qml"

    def update_qml(self, qml, callback):
        connection = self.res_factory.connection

        style_file_desc = connection.upload_file(qml, callback)

        params = dict(
            resource=dict(
                display_name=self.display_name,
            ),
        )
        params[self.type_id] = dict(file_upload=style_file_desc)

        url = self.get_relative_api_url()
        connection.put(url, params=params)
        self.__qml = Path(qml).read_text()
        self.update()


class NGWQGISVectorStyle(NGWQGISStyle):
    type_id = "qgis_vector_style"
    type_title = "NGW QGIS Vector Style"


class NGWQGISRasterStyle(NGWQGISStyle):
    type_id = "qgis_raster_style"
    type_title = "NGW QGIS Raster Style"
