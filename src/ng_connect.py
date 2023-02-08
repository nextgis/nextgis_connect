"""
/***************************************************************************
 NGConnectPlugin
                                 A QGIS plugin
 NGW Connect
                              -------------------
        begin                : 2015-01-30
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
from os import path

from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import QgsMapLayer, QgsMessageLog

from .plugin_settings import PluginSettings
from .tree_panel import TreePanel

from .ngw_api import qgis
from .ngw_api.utils import setDebugEnabled

from .ngw_api.compat_py import CompatPy
from .ngw_api.qgis.compat_qgis import CompatQgis, CompatQgisMsgLogLevel


class NGConnectPlugin:
    """QGIS Plugin Implementation.

        Utils:

from qgis.utils import plugins
plugins['nextgis_connect'].info()
plugins['nextgis_connect'].enableDebug(True)
plugins['nextgis_connect'].enableDebug(False)
    """

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = CompatPy.get_dirname(__file__)

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = path.join(
            self.plugin_dir,
            'i18n',
            'nextgis_connect_{}.qm'.format(locale))

        if path.exists(locale_path):
            self.plugin_translator = QTranslator()
            self.plugin_translator.load(locale_path)

            self.ngw_translator = QTranslator()
            self.ngw_translator.load(
                path.join(
                    path.dirname(qgis.__file__),
                    "i18n",
                    "qgis_ngw_api_{}.qm".format(locale)
                )
            )

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.plugin_translator)
                QCoreApplication.installTranslator(self.ngw_translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr('&NextGIS Connect')
        self.toolbar = self.iface.addToolBar(self.tr('NextGIS Connect'))
        self.toolbar.setObjectName('NextGISConnectPluginToolbar')

        # Enable debug mode.
        debug_mode = PluginSettings.debug_mode()
        PluginSettings.set_debug_mode(debug_mode) # create at first time
        if debug_mode:
            setDebugEnabled(True)
            QgsMessageLog.logMessage('Debug messages are enabled', PluginSettings._product, level=CompatQgisMsgLogLevel.Info)
        else:
            setDebugEnabled(False)
            QgsMessageLog.logMessage('Debug messages are disabled', PluginSettings._product, level=CompatQgisMsgLogLevel.Info)

    def tr(self, message):
        return QCoreApplication.translate('NGConnectPlugin', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        checkable=False,
        is_checked=False,
        status_tip=None,
        whats_this=None,
        parent=None
    ):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.setEnabled(enabled_flag)
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(is_checked)

        if not checkable:
            action.triggered.connect(callback)
        else:
            action.toggled.connect(callback)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def add_group_separator(self, add_to_menu=True, add_to_toolbar=True, parent=None):
        sep_action = QAction(parent)
        sep_action.setSeparator(True)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, sep_action)

        if add_to_toolbar:
            self.toolbar.addAction(sep_action)

        self.actions.append(sep_action)

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        # Dock tree panel
        self.dockWidget = TreePanel(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(PluginSettings.dock_area(), self.dockWidget)
        self.dockWidget.setFloating(PluginSettings.dock_floating())
        self.dockWidget.resize(PluginSettings.dock_size())
        self.dockWidget.move(PluginSettings.dock_pos())
        self.dockWidget.setVisible(PluginSettings.dock_visibility())

        # Tools for NGW communicate
        icon_path = self.plugin_dir + '/icon.png'
        self.add_action(
            icon_path,
            text=self.tr('Show/Hide NextGIS Connect panel'),
            checkable=True,
            is_checked=PluginSettings.dock_visibility(),
            callback=self.dockWidget.setVisible,
            parent=self.iface.mainWindow())

        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionImportQGISResource,
            self.tr("NextGIS Connect"),
            QgsMapLayer.VectorLayer,
            True
        )
        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionUpdateStyle,
            self.tr("NextGIS Connect"),
            QgsMapLayer.VectorLayer,
            True
        )
        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionAddStyle,
            self.tr("NextGIS Connect"),
            QgsMapLayer.VectorLayer,
            True
        )

        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionImportQGISResource,
            self.tr("NextGIS Connect"),
            QgsMapLayer.RasterLayer,
            True
        )
        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionUpdateStyle,
            self.tr("NextGIS Connect"),
            QgsMapLayer.RasterLayer,
            True
        )
        CompatQgis.add_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionAddStyle,
            self.tr("NextGIS Connect"),
            QgsMapLayer.RasterLayer,
            True
        )

    def unload(self):
        CompatQgis.remove_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionImportQGISResource
        )
        CompatQgis.remove_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionUpdateStyle
        )
        CompatQgis.remove_legend_action(
            self.iface,
            self.dockWidget.inner_control.actionAddStyle
        )

        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr('&NextGIS Connect'),
                action)
            self.iface.removeToolBarIcon(action)

        mw = self.iface.mainWindow()
        PluginSettings.set_dock_area(mw.dockWidgetArea(self.dockWidget))
        PluginSettings.set_dock_floating(self.dockWidget.isFloating())
        PluginSettings.set_dock_pos(self.dockWidget.pos())
        PluginSettings.set_dock_size(self.dockWidget.size())
        PluginSettings.set_dock_visibility(self.dockWidget.isVisible())

        self.iface.removeDockWidget(self.dockWidget)

        self.dockWidget.close()

    @staticmethod
    def info():
        print("Plugin NextGIS Connect.")

        from . import ngw_api
        print(("NGW API v. %s" % (ngw_api.__version__) ))

        print(("NGW API log %s" % ("ON" if ngw_api.utils.debug else "OFF") ))

    @staticmethod
    def enableDebug(flag):
        from . import ngw_api
        ngw_api.utils.debug = flag

        print(("NGW API log %s" % ("ON" if ngw_api.utils.debug else "OFF") ))
