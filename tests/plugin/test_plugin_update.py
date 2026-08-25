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

from qgis.core import QgsFeedback, QgsSettings
from qgis.PyQt.QtNetwork import QNetworkReply

from nextgis_connect.legacy.plugin_update import (
    OFFICIAL_REPOSITORY_URL,
    PLUGIN_REPOSITORIES_GROUP,
    PluginRepository,
    PluginRepositoryUrlBuilder,
    PluginUpdateChecker,
    PluginUpdateCheckResult,
    PluginUpdateCheckTask,
    QgisPluginRepositoryPayloadFetcher,
    QgisPluginRepositorySettingsReader,
)


def plugin_payload(version: str) -> bytes:
    return f"""
    <plugins>
        <pyqgis_plugin name="NextGIS Connect" version="{version}">
            <file_name>nextgis_connect</file_name>
        </pyqgis_plugin>
    </plugins>
    """.encode()


def test_update_check_uses_latest_enabled_repository_version(qgis_app) -> None:
    del qgis_app

    repositories = [
        PluginRepository("Stable", "https://stable.example.com/plugins.xml"),
        PluginRepository("Beta", "https://beta.example.com/plugins.xml"),
        PluginRepository(
            "Disabled",
            "https://disabled.example.com/plugins.xml",
            enabled=False,
        ),
    ]
    payloads = {
        "Stable": plugin_payload("3.1.0"),
        "Beta": plugin_payload("3.2.0"),
    }
    fetched_repositories = []

    def fetch(repository: PluginRepository, feedback: QgsFeedback) -> bytes:
        del feedback
        fetched_repositories.append(repository.name)
        return payloads[repository.name]

    result = PluginUpdateChecker(fetch).check(
        repositories,
        "3.0.0",
        QgsFeedback(),
    )

    assert result.update is not None
    assert result.update.available_version == "3.2.0"
    assert result.update.repository_name == "Beta"
    assert result.checked_repositories == 2
    assert fetched_repositories == ["Stable", "Beta"]


def test_update_check_returns_latest_update(qgis_app) -> None:
    del qgis_app

    repositories = [
        PluginRepository("Stable", "https://stable.example.com/plugins.xml"),
        PluginRepository("Beta", "https://beta.example.com/plugins.xml"),
    ]
    payloads = {
        "Stable": plugin_payload("3.1.0"),
        "Beta": plugin_payload("3.2.0"),
    }

    def fetch(repository: PluginRepository, feedback: QgsFeedback) -> bytes:
        del feedback
        return payloads[repository.name]

    result = PluginUpdateChecker(fetch).check(
        repositories,
        "3.0.0",
        QgsFeedback(),
    )

    assert result.update is not None
    assert result.update.available_version == "3.2.0"


def test_update_check_ignores_installed_or_missing_versions(qgis_app) -> None:
    del qgis_app

    repositories = [
        PluginRepository("Current", "https://current.example.com/plugins.xml"),
        PluginRepository("Other", "https://other.example.com/plugins.xml"),
    ]
    payloads = {
        "Current": plugin_payload("3.0.0"),
        "Other": b"""
        <plugins>
            <pyqgis_plugin name="Other plugin" version="9.9.9">
                <file_name>other_plugin</file_name>
            </pyqgis_plugin>
        </plugins>
        """,
    }

    def fetch(repository: PluginRepository, feedback: QgsFeedback) -> bytes:
        del feedback
        return payloads[repository.name]

    result = PluginUpdateChecker(fetch).check(
        repositories,
        "3.0.0",
        QgsFeedback(),
    )

    assert result.update is None
    assert result.errors == tuple()


def test_plugin_repository_url_adds_qgis_version_once(qgis_app) -> None:
    del qgis_app

    builder = PluginRepositoryUrlBuilder()
    url = builder.build("https://example.com/plugins.xml?stable=true")

    assert "stable=true" in url
    assert "&qgis=" in url
    assert builder.build(url) == url


def test_plugin_repository_fetcher_updates_user_agent_suffix(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    updated_requests = []

    class FakeResponse:
        def error(self):
            return QNetworkReply.NetworkError.NoError

        def content(self) -> bytes:
            return b"<plugins />"

    def fake_update_user_agent_suffix(request) -> None:
        updated_requests.append(request)

    monkeypatch.setattr(
        "nextgis_connect.legacy.plugin_update.update_user_agent_suffix",
        fake_update_user_agent_suffix,
    )
    monkeypatch.setattr(
        "nextgis_connect.legacy.plugin_update."
        "QgsNetworkAccessManager.blockingGet",
        lambda *args: FakeResponse(),
    )

    QgisPluginRepositoryPayloadFetcher().fetch(
        PluginRepository("Repository", "https://example.com/plugins.xml"),
        QgsFeedback(),
    )

    assert len(updated_requests) == 1


def test_read_plugin_repositories_uses_settings_and_official_fallback(
    qgis_app,
    reset_qgis_settings,
) -> None:
    del qgis_app, reset_qgis_settings

    settings = QgsSettings()
    settings.beginGroup(PLUGIN_REPOSITORIES_GROUP)
    try:
        settings.setValue("Custom/url", "https://custom.example.com/repo.xml")
        settings.setValue("Custom/enabled", True)
        settings.setValue(
            "Disabled/url", "https://disabled.example.com/repo.xml"
        )
        settings.setValue("Disabled/enabled", False)
    finally:
        settings.endGroup()

    repositories = QgisPluginRepositorySettingsReader(settings).read()
    by_url = {repository.url: repository for repository in repositories}

    assert by_url["https://custom.example.com/repo.xml"].can_check is True
    assert by_url["https://disabled.example.com/repo.xml"].can_check is False
    assert by_url[OFFICIAL_REPOSITORY_URL].can_check is True


def test_update_task_uses_repository_reader(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    checked_repositories = []

    def check(repositories, installed_version, feedback):
        del installed_version, feedback
        checked_repositories.extend(repositories)
        return PluginUpdateCheckResult(None, 1, tuple())

    class RepositoryReader(QgisPluginRepositorySettingsReader):
        def read(self):
            return [
                PluginRepository(
                    "Custom",
                    "https://custom.example.com/repo.xml",
                )
            ]

    task = PluginUpdateCheckTask(repository_reader=RepositoryReader())
    monkeypatch.setattr(task._update_checker, "check", check)
    monkeypatch.setattr(
        "nextgis_connect.legacy.plugin_update.PluginVersionProvider"
        ".current_version",
        lambda: "1.0.0",
    )

    assert task.run()
    assert [repository.url for repository in checked_repositories] == [
        "https://custom.example.com/repo.xml"
    ]
