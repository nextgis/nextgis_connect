import re
from typing import List, Tuple

from qgis.core import QgsMapLayer
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect.compat import FieldType


class QMLProcessor:
    """
    Process QML style XML for NGW layers, fixing boolean and PK field issues.

    This class modifies QML XML strings to workaround NGW limitations with
    boolean fields and primary key handling in style expressions. It updates
    categories, rules, labels, and user-defined properties as needed.

    :param qml_xml_string: QML style XML as string.
    :type qml_xml_string: str
    :param qgs_map_layer: QGIS map layer instance.
    :type qgs_map_layer: QgsMapLayer
    """

    def __init__(
        self, qml_xml_string: str, qgs_map_layer: QgsMapLayer
    ) -> None:
        """
        Initialize QMLProcessor with QML XML and QGIS layer.

        :param qml_xml_string: QML style XML as string.
        :type qml_xml_string: str
        :param qgs_map_layer: QGIS map layer instance.
        :type qgs_map_layer: QgsMapLayer
        """
        self._qml = qml_xml_string
        self._layer = qgs_map_layer
        self._has_change = False

        self._doc = QDomDocument()
        self._doc.setContent(qml_xml_string)

        self._bool_fields_name: List[str] = [
            field.name()
            for field in self._layer.fields()
            if field is not None and field.type() == FieldType.Bool
        ]

        self._pk_field_name = ""
        self._need_check_pk = self._layer.providerType() == "ogr"
        pk_attrs_indicies = self._layer.primaryKeyAttributes()
        if self._need_check_pk and pk_attrs_indicies:
            pk_field = self._layer.fields()[pk_attrs_indicies[0]]
            if pk_field.type() == FieldType.LongLong:
                self._pk_field_name = pk_field.name()
            else:
                self._need_check_pk = False
        else:
            self._need_check_pk = False

    def _erase_simple_text(self, expression: str) -> Tuple[str, List[str]]:
        """
        Replace quoted text in expression with placeholders.

        :param expression: Expression string.
        :type expression: str
        :return: Tuple of modified expression and list of replaced parts.
        :rtype: Tuple[str, list[str]]
        """
        parts: List[str] = []

        def replacer(match) -> str:
            parts.append(match.group(0))
            return f"$${len(parts) - 1}$$"

        expression = re.sub(r"'[^']*'", replacer, expression)
        return expression, parts

    def _restore_simple_text(self, expression: str, parts: List[str]) -> str:
        """
        Restore quoted text in expression from placeholders.

        :param expression: Expression string with placeholders.
        :type expression: str
        :param parts: List of replaced parts.
        :type parts: list[str]
        :return: Restored expression string.
        :rtype: str
        """
        for i, part in enumerate(parts):
            expression = expression.replace(f"$${i}$$", part, 1)
        return expression

    def _process_label(self) -> None:
        """
        Update label expressions for boolean and PK fields.
        """
        labeling_nodes = self._doc.elementsByTagName("text-style")
        for i in range(labeling_nodes.count()):
            labeling_node = labeling_nodes.at(i).toElement()
            if not labeling_node.hasAttribute("fieldName"):
                continue

            label_expression = labeling_node.attribute("fieldName")

            if label_expression == "@id":
                continue

            expression, parts = self._erase_simple_text(label_expression)

            if self._need_check_pk:
                expression, has_change = self._pk_to_id(expression)
                self._has_change = self._has_change or has_change
                if has_change:
                    labeling_node.setAttribute("isExpression", "1")
                    labeling_node.setAttribute("fieldName", expression)

            for field_name in self._bool_fields_name:
                expression, has_change = self._bool_to_int(
                    field_name, expression
                )
                if has_change:
                    labeling_node.setAttribute("isExpression", "1")
                    labeling_node.setAttribute("fieldName", expression)
                    self._has_change = self._has_change or has_change

            expression = self._restore_simple_text(expression, parts)

    def _process_rules(self, renderer_node: QDomDocument) -> None:
        """
        Update rule filter expressions for PK fields.

        :param renderer_node: Renderer XML node.
        :type renderer_node: QDomDocument
        """
        rules_nodes = renderer_node.elementsByTagName("rules")
        if rules_nodes.count() == 0:
            return

        rules_node = rules_nodes.at(0).toElement()
        rule_nodes = rules_node.elementsByTagName("rule")
        for j in range(rule_nodes.count()):
            rule_node = rule_nodes.at(j).toElement()
            filter_expr = rule_node.attribute("filter")
            if not filter_expr:
                continue

            if not self._need_check_pk:
                continue

            expression, parts = self._erase_simple_text(filter_expr)
            expression, has_change = self._pk_to_id(expression)
            self._has_change = self._has_change or has_change
            expression = self._restore_simple_text(expression, parts)

            rule_node.setAttribute("filter", expression)

    def _process_categories(self, renderer_node: QDomDocument) -> None:
        """
        Update category types and values for boolean fields.

        :param renderer_node: Renderer XML node.
        :type renderer_node: QDomDocument
        """
        categories = renderer_node.elementsByTagName("category")
        for j in range(categories.count()):
            category = categories.at(j).toElement()
            if category.attribute("type") != "bool":
                continue

            category.setAttribute("type", "integer")
            value = category.attribute("value")
            if value.lower() == "true":
                category.setAttribute("value", "1")
            elif value.lower() == "false":
                category.setAttribute("value", "0")
            self._has_change = True

    def _process_user_defines(self) -> None:
        """
        Update user-defined property expressions for PK fields.
        """
        if not self._need_check_pk:
            return

        data_defined_properties = self._doc.elementsByTagName(
            "data_defined_properties"
        )
        for i in range(data_defined_properties.count()):
            data_node = data_defined_properties.at(i).toElement()

            options = data_node.elementsByTagName("Option")
            for j in range(options.count()):
                option = options.at(j).toElement()
                if (
                    not option.hasAttribute("name")
                    or option.attribute("name") != "expression"
                ):
                    continue

                option_expression = option.attribute("value")

                option_expression, parts = self._erase_simple_text(
                    option_expression
                )
                option_expression, has_change = self._pk_to_id(
                    option_expression
                )
                self._has_change = self._has_change or has_change
                option.setAttribute("value", option_expression)

                option_expression = self._restore_simple_text(
                    option_expression, parts
                )

    def _pk_to_id(self, expression: str) -> Tuple[str, bool]:
        """
        Replace PK field name with '@id' in expression.

        :param expression: Expression string.
        :type expression: str
        :return: Tuple of modified expression and change flag.
        :rtype: Tuple[str, bool]
        """
        pattern = rf'"{re.escape(self._pk_field_name)}"|\b{re.escape(self._pk_field_name)}\b'
        expression, count = re.subn(pattern, "@id", expression)
        return expression, count > 0

    def _bool_to_int(
        self, field_name: str, expression: str
    ) -> Tuple[str, bool]:
        """
        Replace boolean field name with integer expression.

        :param field_name: Boolean field name.
        :type field_name: str
        :param expression: Expression string.
        :type expression: str
        :return: Tuple of modified expression and change flag.
        :rtype: Tuple[str, bool]
        """
        pattern = rf'"{re.escape(field_name)}"|\b{re.escape(field_name)}\b'
        label_expression, count = re.subn(
            pattern, f'if("{field_name}", true, false)', expression
        )
        return label_expression, count > 0

    def process(self) -> str:
        """
        Process QML XML and return updated style string.

        :return: Modified QML XML string if changes were made, else original.
        :rtype: str
        """
        renderers = self._doc.elementsByTagName("renderer-v2")
        for i in range(renderers.count()):
            renderer_node = renderers.at(i).toElement()

            if renderer_node.hasAttribute("type"):
                if renderer_node.attribute("type") == "categorizedSymbol":
                    self._process_categories(renderer_node)
                elif renderer_node.attribute("type") == "RuleRenderer":
                    self._process_rules(renderer_node)

            self._process_label()
            self._process_user_defines()

        return self._qml if not self._has_change else self._doc.toString()
