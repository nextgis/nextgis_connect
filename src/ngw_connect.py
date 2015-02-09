# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NGWConnectPlugin
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

from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from PyQt4.QtGui import QAction, QIcon

from settings_dialog import SettingsDialog
from plugin_settings import PluginSettings
from tree_panel import TreePanel


class NGWConnectPlugin:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = path.join(
            self.plugin_dir,
            'i18n',
            'ngw_connect_{}.qm'.format(locale))

        if path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&NGW Connect')
        self.toolbar = self.iface.addToolBar(self.tr(u'NGW Connect'))
        self.toolbar.setObjectName(u'NGWConnectPluginToolbar')



    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('NGWConnectPlugin', message)

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
        parent=None):
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

    def add_group_separator(self,
                            add_to_menu=True,
                            add_to_toolbar=True,
                            parent=None):

        sep_action = QAction(parent)
        sep_action.setSeparator(True)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, sep_action)

        if add_to_toolbar:
            self.toolbar.addAction(sep_action)

        self.actions.append(sep_action)


    def initGui(self):
        #import pydevd
        #pydevd.settrace('localhost', port=5566, stdoutToServer=True, stderrToServer=True, suspend=False)

        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        # Dock tree panel
        self.dockWidget = TreePanel(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(PluginSettings.dock_area(), self.dockWidget)
        self.dockWidget.setFloating(PluginSettings.dock_floating())
        self.dockWidget.resize(PluginSettings.dock_size())
        self.dockWidget.move(PluginSettings.dock_pos())
        self.dockWidget.setVisible(PluginSettings.dock_visibility())

        #Tools for NGW communicate
        icon_path = self.plugin_dir + '/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Show/Hide NGW panel'),
            checkable=True,
            is_checked=PluginSettings.dock_visibility(),
            callback=self.dockWidget.setVisible,
            parent=self.iface.mainWindow())


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&NGW Connect'),
                action)
            self.iface.removeToolBarIcon(action)

        mw = self.iface.mainWindow()
        PluginSettings.set_dock_area(mw.dockWidgetArea(self.dockWidget))
        PluginSettings.set_dock_floating(self.dockWidget.isFloating())
        PluginSettings.set_dock_pos(self.dockWidget.pos())
        PluginSettings.set_dock_size(self.dockWidget.size())
        PluginSettings.set_dock_visibility(self.dockWidget.isVisible())

        self.iface.removeDockWidget(self.dockWidget)
        del self.dockWidget