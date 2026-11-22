# -*- coding: utf-8 -*-
from __future__ import absolute_import

from Plugins.Plugin import PluginDescriptor

NAME = "Wacayoub MultiBoot"
DESC = "Gestion multiboot : slots, démarrage, installation, sauvegarde"


def main(session, **kwargs):
    try:
        from .ui import WMBMain
        session.open(WMBMain)
    except Exception as e:
        import traceback
        try:
            from .core import log
            log("open failed: %s" % traceback.format_exc())
        except Exception:
            pass
        from Screens.MessageBox import MessageBox
        session.open(MessageBox, "%s : impossible d'ouvrir le plugin.\n%s" % (NAME, e), MessageBox.TYPE_ERROR)


def menu(menuid, **kwargs):
    if menuid == "system":
        return [(NAME, main, "wacayoub_multiboot", 45)]
    return []


def Plugins(**kwargs):
    return [
        PluginDescriptor(name=NAME, description=DESC, where=PluginDescriptor.WHERE_PLUGINMENU,
                         icon="plugin.png", fnc=main),
        PluginDescriptor(name=NAME, description=DESC, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
        PluginDescriptor(name=NAME, description=DESC, where=PluginDescriptor.WHERE_MENU, fnc=menu),
    ]
