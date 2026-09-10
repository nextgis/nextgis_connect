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
from typing import Tuple

from qgis.PyQt.QtXml import QDomDocument


class PrimaryKeyQmlHandler:
    """Replace references to an OGR integer primary key with ``@id``."""

    def __init__(self, field_name: str) -> None:
        self._field_name = field_name
        self._field_pattern = re.compile(
            rf'"{re.escape(field_name)}"|(?<![@$])\b{re.escape(field_name)}\b'
        )
        self._quoted_text_pattern = re.compile(r"'(?:''|\\.|[^'\\])*'")

    def process(self, document: QDomDocument) -> bool:
        """Update labels, rule filters, and data-defined expressions."""
        has_changes = self._process_labels(document)
        has_changes = self._process_legacy_labels(document) or has_changes
        has_changes = self._process_rule_filters(document) or has_changes
        return self._process_data_defined_properties(document) or has_changes

    def _process_labels(self, document: QDomDocument) -> bool:
        has_changes = False
        labeling_nodes = document.elementsByTagName("text-style")
        for index in range(labeling_nodes.count()):
            labeling_node = labeling_nodes.at(index).toElement()
            if not labeling_node.hasAttribute("fieldName"):
                continue

            expression = labeling_node.attribute("fieldName")
            if expression == "@id":
                continue

            expression, changed = self._replace_field_reference(expression)
            if not changed:
                continue

            labeling_node.setAttribute("isExpression", "1")
            labeling_node.setAttribute("fieldName", expression)
            has_changes = True

        return has_changes

    def _process_legacy_labels(self, document: QDomDocument) -> bool:
        has_changes = False
        custom_properties = document.elementsByTagName("customproperties")
        for index in range(custom_properties.count()):
            custom_properties_node = custom_properties.at(index).toElement()
            properties = custom_properties_node.elementsByTagName("property")
            for property_index in range(properties.count()):
                property_node = properties.at(property_index).toElement()
                if property_node.attribute("key") != "labeling/fieldName":
                    continue

                expression, changed = self._replace_field_reference(
                    property_node.attribute("value")
                )
                if not changed:
                    continue

                property_node.setAttribute("value", expression)
                self._set_legacy_label_expression(
                    document,
                    custom_properties_node,
                )
                has_changes = True

        return has_changes

    def _process_rule_filters(self, document: QDomDocument) -> bool:
        has_changes = False
        renderers = document.elementsByTagName("renderer-v2")
        for index in range(renderers.count()):
            renderer_node = renderers.at(index).toElement()
            if renderer_node.attribute("type") != "RuleRenderer":
                continue

            rules_nodes = renderer_node.elementsByTagName("rules")
            if rules_nodes.count() == 0:
                continue

            rule_nodes = (
                rules_nodes.at(0).toElement().elementsByTagName("rule")
            )
            for rule_index in range(rule_nodes.count()):
                rule_node = rule_nodes.at(rule_index).toElement()
                expression = rule_node.attribute("filter")
                if not expression:
                    continue

                expression, changed = self._replace_field_reference(expression)
                if changed:
                    rule_node.setAttribute("filter", expression)
                    has_changes = True

        return has_changes

    def _process_data_defined_properties(self, document: QDomDocument) -> bool:
        has_changes = False
        for tag_name in ("data_defined_properties", "dd_properties"):
            property_nodes = document.elementsByTagName(tag_name)
            for index in range(property_nodes.count()):
                options = (
                    property_nodes.at(index)
                    .toElement()
                    .elementsByTagName("Option")
                )
                for option_index in range(options.count()):
                    option = options.at(option_index).toElement()
                    if option.attribute("name") != "expression":
                        continue

                    expression, changed = self._replace_field_reference(
                        option.attribute("value")
                    )
                    if changed:
                        option.setAttribute("value", expression)
                        has_changes = True

        legacy_property_nodes = document.elementsByTagName("data-defined")
        for index in range(legacy_property_nodes.count()):
            property_node = (
                legacy_property_nodes.at(index).toElement().firstChildElement()
            )
            while not property_node.isNull():
                if property_node.attribute("useExpr").lower() == "true":
                    expression, changed = self._replace_field_reference(
                        property_node.attribute("expr")
                    )
                    if changed:
                        property_node.setAttribute("expr", expression)
                        has_changes = True
                property_node = property_node.nextSiblingElement()

        return has_changes

    def _replace_field_reference(self, expression: str) -> Tuple[str, bool]:
        parts = []
        replacements = 0
        expression_end = 0
        for quoted_text in self._quoted_text_pattern.finditer(expression):
            unquoted_text, count = self._field_pattern.subn(
                "@id",
                expression[expression_end : quoted_text.start()],
            )
            parts.append(unquoted_text)
            parts.append(quoted_text.group(0))
            replacements += count
            expression_end = quoted_text.end()

        unquoted_text, count = self._field_pattern.subn(
            "@id",
            expression[expression_end:],
        )
        parts.append(unquoted_text)
        replacements += count
        return "".join(parts), replacements > 0

    def _set_legacy_label_expression(
        self,
        document: QDomDocument,
        custom_properties_node,
    ) -> None:
        properties = custom_properties_node.elementsByTagName("property")
        for index in range(properties.count()):
            property_node = properties.at(index).toElement()
            if property_node.attribute("key") == "labeling/isExpression":
                property_node.setAttribute("value", "true")
                return

        expression_property = document.createElement("property")
        expression_property.setAttribute("key", "labeling/isExpression")
        expression_property.setAttribute("value", "true")
        custom_properties_node.appendChild(expression_property)
