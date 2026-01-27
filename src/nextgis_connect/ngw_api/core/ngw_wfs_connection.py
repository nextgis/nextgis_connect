"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2044-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2024 by NextGIS
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

from typing import Any, Dict

from .ngw_resource import NGWResource, dict_to_object


class NGWWfsConnection(NGWResource):
    type_id = "wfsclient_connection"

    def _construct(self):
        super()._construct()
        self.wfs = dict_to_object(self._json[self.type_id])

    @property
    def connection_info(self) -> Dict[str, Any]:
        return self._json[self.type_id]
