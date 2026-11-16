import os
# Force WebView2 software compositing so Win32 LWA_COLORKEY punches out #010101 cleanly
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--disable-gpu-compositing"

import ctypes
import threading
import time
import tkinter as tk
import webview
from app import app

def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

def make_window_transparent(window):
    time.sleep(0.7)
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "AURA")
        if hwnd:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            LWA_COLORKEY = 0x00000001
            COLOR_KEY = 0x00010101  # RGB(1, 1, 1) -> #010101

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, LWA_COLORKEY)
    except Exception as e:
        print("Transparency hook warning:", e)

if __name__ == "__main__":
    root = tk.Tk()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.destroy()

    widget_w = 380
    widget_h = 540
    pos_x = screen_w - widget_w - 25
    pos_y = screen_h - widget_h - 50

    t = threading.Thread(target=start_flask, daemon=True)
    t.start()

    window = webview.create_window(
        "AURA",
        "http://127.0.0.1:5000",
        width=widget_w,
        height=widget_h,
        x=pos_x,
        y=pos_y,
        frameless=True,
        resizable=True,
        on_top=True,
        transparent=True,
        background_color="#010101"
    )
    webview.start(make_window_transparent, window)
