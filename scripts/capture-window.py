import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
from PIL import ImageGrab

parser = argparse.ArgumentParser()
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--title', required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user = ctypes.windll.user32
user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
found = []
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def callback(hwnd, _):
    pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == args.pid and user.IsWindowVisible(hwnd):
        text = ctypes.create_unicode_buffer(256); user.GetWindowTextW(hwnd, text, 256)
        if args.title in text.value:
            rect = wintypes.RECT(); user.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((rect.left, rect.top, rect.right, rect.bottom))
    return True
user.EnumWindows(callback, 0)
if len(found) != 1:
    raise RuntimeError(f'Expected one matching visible window, found {len(found)}')
ImageGrab.grab(bbox=found[0], all_screens=True).save(args.out)
print(found[0])
