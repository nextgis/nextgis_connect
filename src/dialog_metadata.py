import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QDialog, QMenu, QTableWidgetItem, QComboBox,
    QMessageBox, QProgressDialog, QApplication
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor

from qgis.core import Qgis, QgsMessageLog


FORM_CLASS, _ = uic.loadUiType(os.path.join(
   os.path.dirname(__file__), 'metadata_dialog_base.ui'))


class MetadataDialog(QDialog, FORM_CLASS):
  
    def __init__(self, ngw_res, parent=None):
        super(MetadataDialog, self).__init__(parent)
        self.setupUi(self)

        self.itemTypes = {
            'NoneType': self.tr('Empty'),  
            'bool': self.tr('Boolean'),
            'int': self.tr('Integer'),
            'float': self.tr('Float'),
            'str': self.tr('String')
        }

        self.boolVals = [self.tr('True'), self.tr('False')]

        self.ngw_res = ngw_res

        md_dict = self.ngw_res.metadata.__dict__['items']
        try:
            self.md = [
                [key, self.itemTypes[type(val).__name__], val]
                for key, val in md_dict.items()
            ]
        except:
            QMessageBox.about(self, self.tr("Error"), self.tr("Unexpected metadata type found"))
            self.reject()

        self.createTable()

        self.menu = QMenu()
        self.menu.addAction(self.itemTypes['int'], self.addInt)
        self.menu.addAction(self.itemTypes['float'], self.addFloat)
        self.menu.addAction(self.itemTypes['str'], self.addString)
        self.menu.addAction(self.itemTypes['bool'], self.addBool)
        self.menu.addAction(self.itemTypes['NoneType'], self.addNone)

        self.addButton.setMenu(self.menu)
        self.removeButton.clicked.connect(self.deleteRow)
        self.buttonBox.accepted.connect(self.checkSendAndAccept)
        self.buttonBox.rejected.connect(self.reject)

        self.tableWidget.itemChanged.connect(self.checkItem) 

    def createTable(self):
        self.tableWidget.setRowCount(len(self.md))
        for i in range(len(self.md)):
            itemOne = QTableWidgetItem(str(self.md[i][0]))
            itemOne.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)

            itemTwo = QTableWidgetItem(str(self.md[i][1]))
            itemTwo.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            itemThree = QTableWidgetItem(str(self.md[i][2]))
            itemThree.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            if str(self.md[i][1]) == self.itemTypes['bool']:
                combo = QComboBox(self)
                combo.addItems(self.boolVals)
                if not self.md[i][2]:
                    combo.setCurrentIndex(1)
                self.tableWidget.setCellWidget(i, 2, combo)
            elif str(self.md[i][1]) == self.itemTypes['NoneType']:
                itemThree.setText('')
                itemThree.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            self.tableWidget.setItem(i, 0, itemOne)
            self.tableWidget.setItem(i, 1, itemTwo)
            self.tableWidget.setItem(i, 2, itemThree)

    def checkItem(self, item):
        if item.column() == 2:
            
            itemType = self.tableWidget.item(item.row(), 1).text()
            itemType = list(self.itemTypes.keys())[list(self.itemTypes.values()).index(itemType)]
            if itemType == 'NoneType':
                return
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
        if row is None or row < 0:
            return
        self.tableWidget.removeRow(row)
        self.tableWidget.setCurrentCell(-1, -1)

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

    def addBool(self):
        row = self.addRow()
        typeItem = QTableWidgetItem(self.itemTypes['bool'])
        typeItem.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 1, typeItem)

        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 2, item)

        combo = QComboBox(self)
        combo.addItems(self.boolVals)
        self.tableWidget.setCellWidget(row, 2, combo)

    def addNone(self):
        row = self.addRow()
        typeItem = QTableWidgetItem(self.itemTypes['NoneType'])
        typeItem.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 1, typeItem)

        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tableWidget.setItem(row, 2, item)

    def checkSendAndAccept(self):
        self.setWindowModality(Qt.WindowModal)
        if not self.checkTable():
            return
        md = self.getData()

        progress = QProgressDialog(self.tr("Sending metadata..."), None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        progress.setValue(0)
        QApplication.processEvents()
        try:
            self.ngw_res.update_metadata(md)
            self.ngw_res.metadata.__dict__['items'] = md
            progress.cancel()
        except Exception as ex:
            progress.cancel()
            err_txt = '{} {}'.format(self.tr('Error sending metadata update:'), ex)

            QMessageBox.about(self, self.tr("Error"), err_txt)
            QgsMessageLog.logMessage(err_txt, "NGW API", Qgis.Critical)

            qm = QMessageBox()
            qm.setIcon(QMessageBox.Question)
            qm.setText(self.tr("Error sending metadata update. Continue editing or exit?"))
            qm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            buttonY = qm.button(QMessageBox.Yes)
            buttonY.setText(self.tr('Continue'))
            qm.exec_()

            if qm.clickedButton() == buttonY:
                return
            else:
                self.reject()
                return

        self.accept()

    def checkTable(self):
        keys = []
        for i in range(self.tableWidget.rowCount()):
            key = self.tableWidget.item(i, 0)
            if not key:
                QMessageBox.about(self, self.tr("Error"), self.tr("Empty key field"))
                return False
            keys.append(self.tableWidget.item(i, 0).text())
            item = self.tableWidget.item(i, 2)
            if not item:
                QMessageBox.about(self, self.tr("Error"), self.tr("Empty value field"))
                return False
            if item.background().color() == QColor(255, 120, 100):
                QMessageBox.about(self, self.tr("Error"), self.tr("Wrong data types"))
                return False

        if len(set(keys)) < len(keys):
            QMessageBox.about(self, self.tr("Error"), self.tr("Keys duplication"))
            return False

        return True

    def getData(self):
        res = {}
        for i in range(self.tableWidget.rowCount()):
            key = self.tableWidget.item(i, 0).text()
            val = self.tableWidget.item(i, 2).text()
            itemType = self.tableWidget.item(i, 1).text()
            itemType = list(self.itemTypes.keys())[list(self.itemTypes.values()).index(itemType)]
            if itemType == 'bool':
                combo = self.tableWidget.cellWidget(i, 2)
                if combo.currentText() == self.boolVals[1]:
                    val = ''
            elif itemType == 'NoneType':
                res[key] = None
                continue

            res[key] = __builtins__[itemType](val)
        return res
