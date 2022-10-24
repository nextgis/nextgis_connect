# This Python file uses the following encoding: utf-8
import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMenu, QTableWidgetItem
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor

from qgis.core import Qgis
from qgis.utils import iface


FORM_CLASS, _ = uic.loadUiType(os.path.join(
   os.path.dirname(__file__), 'metadata_dialog_base.ui'))


class MetadataDialog(QDialog, FORM_CLASS):
  
    def __init__(self, md_dict, parent=None):
        """
        :param metadata
        """

        super(MetadataDialog, self).__init__(parent)
        self.setupUi(self)

        self.itemTypes = {
            'int': self.tr('Integer'),
            'float': self.tr('Float'),
            'str': self.tr('String')
        }

        self.md = [
            [key, self.itemTypes[type(val).__name__], val]
            for key, val in md_dict.items()
        ]

        self.createTable()

        self.menu = QMenu()
        self.menu.addAction(self.itemTypes['int'], self.addInt)
        self.menu.addAction(self.itemTypes['float'], self.addFloat)
        self.menu.addAction(self.itemTypes['str'], self.addString)

        self.addButton.setMenu(self.menu)
        self.removeButton.clicked.connect(self.deleteRow)
        self.buttonBox.accepted.connect(self.acceptCheck)
        self.buttonBox.rejected.connect(self.reject)
        
        self.tableWidget.itemChanged.connect(self.checkItem) 

    def createTable(self):
        self.tableWidget.setRowCount(len(self.md))
        for i in range(len(self.md)):
            itemOne = QTableWidgetItem(str(self.md[i][0]))
            itemTwo = QTableWidgetItem(str(self.md[i][1]))
            itemThree = QTableWidgetItem(str(self.md[i][2]))

            itemOne.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            itemTwo.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            itemThree.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            
            self.tableWidget.setItem(i, 0, itemOne)
            self.tableWidget.setItem(i, 1, itemTwo)
            self.tableWidget.setItem(i, 2, itemThree)

    def checkItem(self, item):
        if item.column() == 2:
            
            itemType = self.tableWidget.item(item.row(), 1).text()
            itemType = list(self.itemTypes.keys())[list(self.itemTypes.values()).index(itemType)]
            try:
                item.setText(str(__builtins__[itemType](item.text())))
                item.setBackground(QBrush())
            except ValueError:
                brush = QBrush(QColor(255, 120, 100))
                brush.setStyle(Qt.SolidPattern)
                item.setBackground(brush)
            
    def deleteRow(self):
        if not self.tableWidget.rowCount():
            return
        row = self.tableWidget.currentRow()
        if not row:
            self.tableWidget.removeRow(self.tableWidget.rowCount())
        self.tableWidget.removeRow(row)

    def addRow(self):
        row = self.tableWidget.currentRow()
        if row >= 0:
            row = row + 1
        elif not self.tableWidget.rowCount():
            row = 0
        elif row < 0:
            row = self.tableWidget.rowCount()
        
        self.tableWidget.insertRow(row)
        return row

    def addInt(self):
        row = self.addRow()
        item = QTableWidgetItem(self.itemTypes['int'])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 1, item)

    def addFloat(self):
        row = self.addRow()
        item = QTableWidgetItem(self.itemTypes['float'])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 1, item)

    def addString(self):
        row = self.addRow()
        item = QTableWidgetItem(self.itemTypes['str'])
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 1, item)

    def acceptCheck(self):
        keys = []
        for i in range(self.tableWidget.rowCount()):
            keys.append(self.tableWidget.item(i, 0).text())
            item = self.tableWidget.item(i, 2)
            if item and item.background().color() == QColor(255, 120, 100):
                iface.messageBar().pushMessage("Error", "Wrong data types", level=Qgis.Critical)
                return

        if len(set(keys)) < len(keys):
            iface.messageBar().pushMessage("Error", "Keys duplication", level=Qgis.Critical)
            return
        print(self.getData())
        self.accept()

    def getData(self):
        res = {}
        for i in range(self.tableWidget.rowCount()):
            key = self.tableWidget.item(i, 0)
            val = self.tableWidget.item(i, 2)
            itemType = self.tableWidget.item(i, 1).text()
            itemType = list(self.itemTypes.keys())[list(self.itemTypes.values()).index(itemType)]
            res[key.text()] = __builtins__[itemType](val.text())
        print(res)
        return res
