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

import ast
import subprocess
import tokenize
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qgis.PyQt.QtCore import QCoreApplication, QTranslator

from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.base import (
    BaseConnectionCheck,
)
from nextgis_connect.legacy.ngw_connection.application.diagnostics.checks.root_resource import (
    RootResourceAccessCheck,
)
from nextgis_connect.plugin.plugin import NgConnectPlugin


@pytest.mark.parametrize("language", ["ru", "es"])
def test_active_translations_are_complete(language):
    source_root = Path(__file__).resolve().parents[2] / "src"
    ts_path = (
        source_root
        / "nextgis_connect"
        / "i18n"
        / f"nextgis_connect_{language}.ts"
    )
    for context in ET.parse(ts_path).getroot().findall("context"):
        for message in context.findall("message"):
            translation = message.find("translation")
            assert translation is not None
            if translation.get("type") in ("obsolete", "vanished"):
                continue
            source = message.findtext("source")
            key = (context.findtext("name"), source)
            assert translation.get("type") != "unfinished", key
            for form in translation.findall("numerusform") or [translation]:
                assert "".join(form.itertext()).strip(), key
            assert "u00a0" not in source, key
            assert context.findtext("name") not in ("dock", "self._plugin"), (
                key
            )


@pytest.mark.parametrize("language", ["ru", "es"])
def test_inherited_translation_contexts(qgis_app, tmp_path, language):
    source_root = Path(__file__).resolve().parents[2] / "src"
    ts_path = (
        source_root
        / "nextgis_connect"
        / "i18n"
        / f"nextgis_connect_{language}.ts"
    )
    qm_path = tmp_path / "translations.qm"
    subprocess.run(
        ["lrelease", str(ts_path), "-qm", str(qm_path)],
        check=True,
        capture_output=True,
    )
    translator = QTranslator()
    assert translator.load(str(qm_path))
    assert qgis_app.installTranslator(translator)
    try:
        check = RootResourceAccessCheck(MagicMock())
        expected = translator.translate(
            "BaseConnectionCheck", "The check is running."
        )
        assert expected and expected != "The check is running."
        assert BaseConnectionCheck.initial_description.fget(check) == expected
        plugin = NgConnectPlugin(MagicMock())
        for source in (
            "NextGIS Connect Toolbar",
            "Show/Hide NextGIS Connect panel",
            "About plugin...",
        ):
            expected = translator.translate("NgConnectPlugin", source)
            assert expected and expected != source
            assert plugin.tr(source) == expected
            assert (
                QCoreApplication.translate("NgConnectPlugin", source)
                == expected
            )
        plugin.deleteLater()
    finally:
        qgis_app.removeTranslator(translator)


def test_translation_calls_have_no_trailing_comma():
    source_root = Path(__file__).resolve().parents[2] / "src"
    violations = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = text.splitlines()
        tokens = list(
            tokenize.generate_tokens(iter(text.splitlines(True)).__next__)
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name not in ("tr", "translate") or not node.args:
                continue
            if not isinstance(node.args[0], ast.Constant) or not isinstance(
                node.args[0].value, str
            ):
                continue
            end_column = len(
                lines[node.end_lineno - 1]
                .encode("utf-8")[: node.end_col_offset]
                .decode("utf-8")
            )
            call_tokens = [
                token
                for token in tokens
                if (node.lineno, node.col_offset) <= token.start
                and token.end <= (node.end_lineno, end_column)
                and token.type
                not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT)
            ]
            if call_tokens[-2].string == ",":
                violations.append(f"{path}:{node.lineno}")
    assert not violations, (
        "pylupdate cannot parse trailing commas: " + ", ".join(violations)
    )
