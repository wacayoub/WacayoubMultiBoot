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


_notice = {}


def _show_notice():
    try:
        from Screens.MessageBox import MessageBox
        _notice["session"].open(MessageBox, _notice["text"], MessageBox.TYPE_INFO, timeout=30)
    except Exception:
        pass


def sessionstart(reason, session=None, **kwargs):
    """After an update: tell once how the automatic plugin install went."""
    if reason != 0 or session is None:
        return
    try:
        from .core import firstboot_result
        text = firstboot_result("/")
        if not text:
            return
        from enigma import eTimer
        _notice.update(session=session, text=text, timer=eTimer())
        try:
            _notice["timer"].callback.append(_show_notice)
        except AttributeError:
            _notice["conn"] = _notice["timer"].timeout.connect(_show_notice)
        _notice["timer"].start(15000, True)
    except Exception:
        pass


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
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart),
    ]
