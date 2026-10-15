# SPDX-License-Identifier: GPL-2.0-or-later
"""Query the actual TSF candidate on the current foreground editor thread."""
import ctypes
from ctypes import wintypes
import mmap
import os
from pathlib import Path
import secrets
import struct

u = ctypes.WinDLL("user32", use_last_error=True)
u.GetForegroundWindow.restype = wintypes.HWND
u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
u.GetWindowThreadProcessId.restype = wintypes.DWORD
u.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
u.RegisterWindowMessageW.restype = wintypes.UINT
u.SetWindowsHookExW.argtypes = (ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD)
u.SetWindowsHookExW.restype = wintypes.HANDLE
u.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
u.PostMessageW.restype = wintypes.BOOL
class GuiThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]
u.GetGUIThreadInfo.argtypes = (wintypes.DWORD, ctypes.POINTER(GuiThreadInfo))
u.GetGUIThreadInfo.restype = wintypes.BOOL
def focused_window():
    info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
    return info.hwndFocus if u.GetGUIThreadInfo(0, ctypes.byref(info)) else None


class TsfReader:
    def __init__(self, dll_path=None):
        self.dll = ctypes.WinDLL(str(dll_path or Path(__file__).with_name("wetypeTsfBridge64.dll")))
        self.hook = None
        self.tid = 0
        self.mapping = None
        self.nonce = 0
        self.query = u.RegisterWindowMessageW("NVDA.WeType.TSF.Query.v1")

    def request(self):
        hwnd = focused_window()
        tid = u.GetWindowThreadProcessId(hwnd, None)
        if not hwnd or not tid:
            return False
        if self.tid != tid:
            self.close()
            self.hook = u.SetWindowsHookExW(3, ctypes.cast(self.dll.candidateQueryHook, ctypes.c_void_p), self.dll._handle, tid)
            if not self.hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self.tid = tid
        if self.mapping:
            self.mapping.close()
        self.nonce = secrets.randbelow(0x7ffffffe) + 1
        self.mapping = mmap.mmap(-1, 2336, tagname=f"Local\\NVDAWeType_{os.getpid()}_{self.nonce}")
        return bool(u.PostMessageW(hwnd, self.query, os.getpid(), self.nonce))

    def result(self):
        if not self.mapping:
            return None
        data = self.mapping[:]
        sequence, tid, status, count, selected, length = struct.unpack_from("<IIiIII", data)
        if sequence != self.nonce:
            return None
        if tid != self.tid or status != 0 or not 0 < count <= 4096 or selected >= count or not 0 < length < 1024:
            return ()
        return count, selected, data[24:24 + length * 2].decode("utf-16-le")

    def close(self):
        if self.hook:
            u.UnhookWindowsHookEx(self.hook)
            self.hook = None
        if self.mapping:
            self.mapping.close()
            self.mapping = None
        self.tid = 0


if __name__ == "__main__":
    import time
    reader = TsfReader()
    try:
        print("QUERY_POSTED", reader.request())
        for unused in range(20):
            answer = reader.result()
            if answer is not None:
                print("COUNT_SELECTED_TEXT", (answer[0],answer[1],answer[2].encode('unicode_escape').decode()) if answer else answer)
                print("PAGE_DATA", struct.unpack_from("<66I",reader.mapping[:],2072))
                break
            time.sleep(.025)
        else:
            print("NO_RESPONSE")
    finally:
        reader.close()
