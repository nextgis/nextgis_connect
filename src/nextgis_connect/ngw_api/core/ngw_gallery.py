"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2014-11-19
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

from .ngw_resource import NGWResource


class NGWGallery(NGWResource):
    type_id = "gallery"
    type_title = "NGW Gallery"

    def __init__(self, resource_factory, resource_json):
        super().__init__(resource_factory, resource_json)
        self.__root = None

    @property
    def preview_url(self):
        return f"{self.get_absolute_url()}/gallery"
