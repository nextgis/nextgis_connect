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

from typing import Optional

from nextgis_connect.exceptions import NgConnectError


class NGWResourceModelJobError(NgConnectError):
    """Common error"""

    def __init__(self, msg, *, user_message=None):
        super().__init__(msg, user_message=user_message)

    @property
    def user_msg(self) -> Optional[str]:
        return self.user_message


class JobError(NGWResourceModelJobError):
    """Specific job error"""

    def __init__(self, msg, wrapped_exception=None):
        super().__init__(msg)
        self.wrapped_exception = wrapped_exception


class JobWarning(NGWResourceModelJobError):
    """Specific job warning"""


class JobServerRequestError(NGWResourceModelJobError):
    """Something wrong with request to NGW like  no connection, 502, ngw error"""

    def __init__(self, msg, url, user_msg=None, need_reconnect=True):
        super().__init__(msg, user_message=user_msg)
        self.url = url
        self.need_reconnect = need_reconnect


class JobNGWError(JobServerRequestError):
    """NGW answer is received, but NGW can't execute request for perform the job"""

    def __init__(self, msg, url):
        super().__init__(msg, url)
