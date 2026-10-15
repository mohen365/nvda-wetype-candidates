# SPDX-License-Identifier: GPL-2.0-or-later
"""Read WeType's actual selected candidate from Windows TSF, without OCR."""
import ctypes
from ctypes import wintypes
import appModuleHandler
import characterProcessing
import globalPluginHandler
import inputCore
import NVDAHelper
import speech
import wx
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from .tsfReader import TsfReader, u, focused_window

u.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
u.FindWindowW.restype = wintypes.HWND
u.IsWindowVisible.argtypes = (wintypes.HWND,)
u.IsWindowVisible.restype = wintypes.BOOL

def candidate_window():
    hwnd = u.FindWindowW("wetype.flutter.setting", "wetype_candidate")
    if not hwnd or not u.IsWindowVisible(hwnd):
        return 0
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        if appModuleHandler.getAppModuleFromProcessID(pid.value).appName.lower() != "wetype_renderer":
            return 0
    except Exception:
        return 0
    return hwnd

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "微信输入法候选朗读"

    def __init__(self):
        super().__init__()
        self.reader = TsfReader()
        self.timer = None
        self.token = 0
        self.dead = False
        self.last = None
        inputCore.decide_executeGesture.register(self.on_gesture)
        log.info("WETYPE_BRIDGE loaded 0.3.2 (compact TSF selection, focused editor thread, expanded guarded, no OCR)")

    def terminate(self):
        self.dead = True
        self.token += 1
        inputCore.decide_executeGesture.unregister(self.on_gesture)
        if self.timer:
            self.timer.Stop()
        self.reader.close()
        super().terminate()

    def on_gesture(self, gesture):
        if not self.dead and isinstance(gesture, KeyboardInputGesture) and not gesture.isModifier:
            # Navigation may move only the pinyin caret; reread the actual
            # candidate even when unchanged, rather than speaking "blank".
            wx.CallAfter(self.queue_read, gesture.vkCode in (33, 34, 37, 38, 39, 40))
        return True

    def queue_read(self, repeat=False):
        if self.dead:
            return
        self.token += 1
        if self.timer:
            self.timer.Stop()
        self.timer = wx.CallLater(45, self.request_read, self.token, repeat)

    def request_read(self, token, repeat):
        self.timer = None
        if self.dead or token != self.token:
            return
        hwnd = candidate_window()
        if not hwnd:
            self.last = None
            self.reader.close()
            return
        try:
            if self.reader.request():
                self.timer = wx.CallLater(15, self.accept_read, token, hwnd, 0, repeat)
        except Exception:
            log.warning("WETYPE_BRIDGE TSF query unavailable", exc_info=True)
            self.reader.close()

    def accept_read(self, token, hwnd, attempt, repeat):
        self.timer = None
        if self.dead or token != self.token:
            return
        focus = focused_window()
        if hwnd != candidate_window() or not focus or u.GetWindowThreadProcessId(focus, None) != self.reader.tid:
            self.last = None
            self.reader.close()
            return
        result = self.reader.result()
        if result is None:
            if attempt < 9:
                self.timer = wx.CallLater(15, self.accept_read, token, hwnd, attempt + 1, repeat)
            else:
                self.reader.close()
                log.debug("WETYPE_BRIDGE TSF response timed out")
            return
        if not result:
            self.last = None
            return
        count, selected, candidate = result
        # WeType 3.0.0.32 returns a wrong selection/string in the expanded grid.
        # Never speak that mismatched candidate. Compact lists expose <=9 items.
        if count > 9:
            self.last = None
            return
        actual = (self.reader.tid, selected, candidate)
        if actual == self.last and not repeat:
            return
        self.last = actual
        handler = NVDAHelper.handleInputCandidateListUpdate
        owner = getattr(handler, "__self__", None)
        if owner is not None and owner.__class__.__module__ == "globalPlugins.ime_expressive":
            from globalPlugins.ime_expressive import settings
            from globalPlugins.ime_expressive.describer import CandidateDescriber
            describer = CandidateDescriber(settings.getDescriptionMode(), settings.getReportThreshold())
            prefix, description, unused = describer.buildSpeechParts(candidate)
            text = "，".join(part for part in (prefix, description) if part) or candidate
        else:
            text = candidate
            if len(text) == 1:
                descriptions = characterProcessing.getCharacterDescription("zh_CN", text)
                if descriptions:
                    text = descriptions[0]
        speech.cancelSpeech()
        speech.speakText(text)
        log.info("WETYPE_BRIDGE TSF count=%d selected=%d speechRequested=True", count, selected)
