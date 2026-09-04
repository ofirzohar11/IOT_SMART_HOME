"""Make sure Qt can locate its platform plugins before any window is created.

Some PyQt5 wheels (notably on macOS) do not export the plugin directory, and Qt
then aborts with:

    qt.qpa.plugin: Could not find the Qt platform plugin "cocoa" in ""

Pointing QT_QPA_PLATFORM_PLUGIN_PATH at the directory that ships inside the
installed PyQt5 package fixes it without the user having to set anything.
Call ``ensure_qt_plugin_path()`` before importing PyQt5.QtWidgets.
"""

import os


def ensure_qt_plugin_path():
    if os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH'):
        return  # the user already chose a location, do not override it

    try:
        import PyQt5
    except ImportError:
        return

    package_dir = os.path.dirname(os.path.abspath(PyQt5.__file__))
    for qt_dir in ('Qt5', 'Qt'):
        plugins = os.path.join(package_dir, qt_dir, 'plugins')
        if os.path.isdir(os.path.join(plugins, 'platforms')):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(plugins, 'platforms')
            os.environ.setdefault('QT_PLUGIN_PATH', plugins)
            return
