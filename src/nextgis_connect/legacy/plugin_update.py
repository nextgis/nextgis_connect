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

import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

from qgis.core import Qgis, QgsFeedback, QgsNetworkAccessManager, QgsSettings
from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from nextgis_connect.legacy.ngw_connection.application.diagnostics.parsers import (
    PluginVersionProvider,
    QgisPluginRepositoryParser,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    update_user_agent_suffix,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import parse_version
from nextgis_connect.platform.tasks import NgConnectTask
from nextgis_connect.platform.xml_utils import XmlParseError

PLUGIN_REPOSITORIES_GROUP = "app/plugin_repositories"
OFFICIAL_REPOSITORY_NAME = "QGIS Official Plugin Repository"
OFFICIAL_REPOSITORY_URL = "https://plugins.qgis.org/plugins/plugins.xml"


@dataclass(frozen=True)
class PluginRepository:
    name: str
    url: str
    authcfg: str = ""
    enabled: bool = True
    valid: bool = True

    @property
    def can_check(self) -> bool:
        return self.enabled and self.valid and self.url != ""


@dataclass(frozen=True)
class PluginUpdate:
    installed_version: str
    available_version: str
    repository_name: str
    repository_url: str

    @property
    def skip_id(self) -> str:
        return self.available_version


@dataclass(frozen=True)
class PluginUpdateCheckResult:
    update: Optional[PluginUpdate]
    checked_repositories: int
    errors: Sequence[str]


FetchRepositoryPayload = Callable[[PluginRepository, QgsFeedback], bytes]


class PluginRepositoryUrlBuilder:
    _QGIS_QUERY_PARAMETER_PATTERN = re.compile(r"(^|[?&])qgis=")

    def query_parameters(self) -> str:
        version = Qgis.versionInt()
        major = version // 10000
        minor = (version % 10000) // 100
        return f"?qgis={major}.{minor}"

    def build(self, url: str) -> str:
        if self._QGIS_QUERY_PARAMETER_PATTERN.search(url):
            return url

        separator = "&" if "?" in url else "?"
        query = self.query_parameters().lstrip("?")
        return f"{url}{separator}{query}"


class QgisPluginRepositorySettingsReader:
    def __init__(self, settings: Optional[QgsSettings] = None) -> None:
        self._settings = QgsSettings() if settings is None else settings

    def read(self) -> List[PluginRepository]:
        self._settings.beginGroup(PLUGIN_REPOSITORIES_GROUP)
        try:
            repositories = {}
            for key in self._settings.childGroups():
                repository = PluginRepository(
                    name=key,
                    url=self._settings.value(f"{key}/url", "", type=str),
                    authcfg=self._settings.value(
                        f"{key}/authcfg",
                        "",
                        type=str,
                    ),
                    enabled=self._settings.value(
                        f"{key}/enabled",
                        True,
                        type=bool,
                    ),
                    valid=self._settings.value(
                        f"{key}/valid",
                        True,
                        type=bool,
                    ),
                )
                repositories[repository.url] = repository

            repositories.setdefault(
                OFFICIAL_REPOSITORY_URL,
                PluginRepository(
                    name=OFFICIAL_REPOSITORY_NAME,
                    url=OFFICIAL_REPOSITORY_URL,
                ),
            )

            return list(repositories.values())
        finally:
            self._settings.endGroup()


class QgisPluginRepositoryPayloadFetcher:
    def __init__(
        self,
        url_builder: Optional[PluginRepositoryUrlBuilder] = None,
    ) -> None:
        self._url_builder = url_builder or PluginRepositoryUrlBuilder()

    def fetch(
        self,
        repository: PluginRepository,
        feedback: QgsFeedback,
    ) -> bytes:
        request = QNetworkRequest(
            QUrl(self._url_builder.build(repository.url))
        )
        update_user_agent_suffix(request)
        response = QgsNetworkAccessManager.blockingGet(
            request,
            repository.authcfg,
            False,
            feedback,
        )
        if response.error() != QNetworkReply.NetworkError.NoError:
            raise RuntimeError(response.errorString())

        return bytes(response.content())


class PluginUpdateChecker:
    def __init__(
        self,
        fetch_payload: Optional[FetchRepositoryPayload] = None,
    ) -> None:
        self._fetch_payload = (
            fetch_payload or QgisPluginRepositoryPayloadFetcher().fetch
        )

    def check(
        self,
        repositories: Iterable[PluginRepository],
        installed_version: str,
        feedback: QgsFeedback,
    ) -> PluginUpdateCheckResult:
        parsed_installed_version = parse_version(installed_version)
        latest_update: Optional[PluginUpdate] = None
        latest_parsed_version = None
        checked_repositories = 0
        errors = []

        for repository in repositories:
            if feedback.isCanceled():
                break

            if not repository.can_check:
                continue

            checked_repositories += 1
            try:
                latest_version = QgisPluginRepositoryParser.latest_version(
                    self._fetch_payload(repository, feedback)
                )
            except (XmlParseError, ValueError, RuntimeError) as error:
                errors.append(f"{repository.name}: {error}")
                continue

            if latest_version is None:
                continue

            parsed_latest_version = parse_version(latest_version)
            if parsed_latest_version <= parsed_installed_version:
                continue

            if (
                latest_parsed_version is not None
                and parsed_latest_version <= latest_parsed_version
            ):
                continue

            latest_update = PluginUpdate(
                installed_version=installed_version,
                available_version=latest_version,
                repository_name=repository.name,
                repository_url=repository.url,
            )
            latest_parsed_version = parsed_latest_version

        return PluginUpdateCheckResult(
            update=latest_update,
            checked_repositories=checked_repositories,
            errors=tuple(errors),
        )


class PluginUpdateCheckTaskSignals(QObject):
    finished = pyqtSignal(object)


class PluginUpdateCheckTask(NgConnectTask):
    def __init__(
        self,
        repositories: Optional[Sequence[PluginRepository]] = None,
        fetch_payload: Optional[FetchRepositoryPayload] = None,
        repository_reader: Optional[QgisPluginRepositorySettingsReader] = None,
    ) -> None:
        super().__init__(flags=NgConnectTask.Flags())
        self._repositories = repositories
        self._repository_reader = (
            repository_reader or QgisPluginRepositorySettingsReader()
        )
        self._update_checker = PluginUpdateChecker(fetch_payload)
        self._feedback = QgsFeedback()
        self._result = PluginUpdateCheckResult(None, 0, tuple())
        self.signals = PluginUpdateCheckTaskSignals()
        self.setDescription(self.tr("Checking NextGIS Connect updates"))

    @property
    def result(self) -> PluginUpdateCheckResult:
        return self._result

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    def run(self) -> bool:
        if not super().run():
            return False

        try:
            repositories = (
                self._repository_reader.read()
                if self._repositories is None
                else list(self._repositories)
            )
            self._result = self._update_checker.check(
                repositories,
                PluginVersionProvider.current_version(),
                self._feedback,
            )
            return True
        except Exception as error:
            logger.exception("Plugin update check failed")
            self._error = error
            return False

    def finished(self, result: bool) -> None:
        if not result:
            self.signals.finished.emit(
                PluginUpdateCheckResult(None, 0, tuple())
            )
            return

        self.signals.finished.emit(self._result)
