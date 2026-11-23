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


class _Watch(object):
    """Shows on the TV the progress of a MultiBoot job started outside the GUI
    (SSH, script): checked every 5 s, opened once while running and once when done."""

    def __init__(self, session):
        from enigma import eTimer
        self.session = session
        self.screen = None
        self.seen = set()
        self.hidden = set()
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.check)
        except AttributeError:
            self.conn = self.timer.timeout.connect(self.check)
        self.timer.start(5000, False)

    def check(self):
        try:
            if self.screen is not None:
                return
            from .core import foreign_jobs, RemoteJob
            for d in foreign_jobs():
                key = (d.get("pid"), d.get("started"))
                if d.get("done"):
                    if key in self.seen:
                        continue
                elif key in self.hidden:
                    continue
                self.open(RemoteJob(d), key)
                return
        except Exception:
            pass

    def open(self, job, key):
        from .ui import WMBProgress
        self.key = key
        self.screen = self.session.openWithCallback(self.closed, WMBProgress, job)

    def closed(self, job=None):
        try:
            self.screen = None
            if job is not None and job.done:
                self.seen.add(self.key)
                job.mark_seen()
            else:
                self.hidden.add(self.key)
        except Exception:
            pass


def sessionstart(reason, session=None, **kwargs):
    """After an update: tell once how the automatic plugin install went.
    Also follows on the TV the jobs started outside the GUI."""
    if reason != 0 or session is None:
        return
    try:
        _notice["watch"] = _Watch(session)
    except Exception:
        pass
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
