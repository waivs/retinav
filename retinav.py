#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct  7 17:47:49 2026

@author: J.D. Rogers jeremy.rogers@wisc.edu

A dynamic fixation target for naigating the retina with with a SLO or similar instrument

The plan is to use Claude or similar AI code building tools and refine it manually

"""

"""
Crosshair overlay: draws a crosshair on a chosen monitor (default: a secondary one)
and lets you move it from a control window.
 
Install:  pip install screeninfo
Run:      python crosshair.py
 
Controls window shortcuts: arrow keys move by the step size (hold Shift for 10x).
"""
import sys
import tkinter as tk
from tkinter import ttk, colorchooser
 
from screeninfo import get_monitors
 
# Make coordinates match real pixels on high-DPI Windows displays
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
 
KEY = "#ff00ff"  # background color treated as transparent
 
 
class Overlay(tk.Toplevel):
    """Borderless, always-on-top, transparent, click-through window covering one monitor."""
 
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.canvas = tk.Canvas(self, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._setup_transparency()
 
    def _setup_transparency(self):
        if sys.platform == "win32":
            self.attributes("-transparentcolor", KEY)
        elif sys.platform == "darwin":
            self.attributes("-transparent", True)
            self.canvas.config(bg="systemTransparent")
            self.config(bg="systemTransparent")
        else:
            try:  # needs a compositing window manager
                self.attributes("-transparentcolor", KEY)
            except tk.TclError:
                self.attributes("-alpha", 0.6)
 
    def make_click_through(self):
        if sys.platform != "win32":
            return
        import ctypes
        self.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = -20, 0x80000, 0x20, 0x80
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
 
    def place_on(self, mon):
        self.geometry(f"{mon.width}x{mon.height}{mon.x:+d}{mon.y:+d}")
        self.update_idletasks()
        self.make_click_through()
 
 
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crosshair Controller")
        self.resizable(False, False)
 
        self.monitors = get_monitors()
        self.mon = self._default_monitor()
 
        self.x = tk.IntVar(value=self.mon.width // 2)
        self.y = tk.IntVar(value=self.mon.height // 2)
        self.step = tk.IntVar(value=5)
        self.size = tk.IntVar(value=40)       # arm length (px)
        self.gap = tk.IntVar(value=6)         # gap around center (px)
        self.thick = tk.IntVar(value=2)
        self.full = tk.BooleanVar(value=False)  # full-screen lines
        self.dot = tk.BooleanVar(value=True)
        self.color = "#00ff00"
        self.visible = tk.BooleanVar(value=True)
 
        self.overlay = Overlay(self)
        self.overlay.place_on(self.mon)
 
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.draw()
 
        # Put the controller on the primary monitor
        primary = next((m for m in self.monitors if m.is_primary), self.monitors[0])
        self.geometry(f"+{primary.x + 80}+{primary.y + 80}")
 
    # ---------- setup ----------
    def _default_monitor(self):
        for m in self.monitors:
            if not m.is_primary:
                return m
        return self.monitors[0]  # only one monitor available
 
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        f = ttk.Frame(self, padding=10)
        f.grid()
 
        # Monitor picker
        ttk.Label(f, text="Monitor").grid(row=0, column=0, sticky="w", **pad)
        names = [f"{i}: {m.width}x{m.height} @ ({m.x},{m.y})"
                 + (" [primary]" if m.is_primary else "")
                 for i, m in enumerate(self.monitors)]
        self.mon_box = ttk.Combobox(f, values=names, state="readonly", width=32)
        self.mon_box.current(self.monitors.index(self.mon))
        self.mon_box.grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        self.mon_box.bind("<<ComboboxSelected>>", self._on_monitor)
 
        # Position sliders
        self.x_scale = self._slider(f, 1, "X", self.x, 0, self.mon.width - 1)
        self.y_scale = self._slider(f, 2, "Y", self.y, 0, self.mon.height - 1)
 
        # D-pad
        pad_f = ttk.Frame(f)
        pad_f.grid(row=3, column=0, columnspan=4, pady=8)
        ttk.Button(pad_f, text="▲", width=4, command=lambda: self.nudge(0, -1)).grid(row=0, column=1)
        ttk.Button(pad_f, text="◀", width=4, command=lambda: self.nudge(-1, 0)).grid(row=1, column=0)
        ttk.Button(pad_f, text="●", width=4, command=self.center).grid(row=1, column=1)
        ttk.Button(pad_f, text="▶", width=4, command=lambda: self.nudge(1, 0)).grid(row=1, column=2)
        ttk.Button(pad_f, text="▼", width=4, command=lambda: self.nudge(0, 1)).grid(row=2, column=1)
 
        # Appearance
        self._slider(f, 4, "Step", self.step, 1, 100, redraw=False)
        self._slider(f, 5, "Arm length", self.size, 5, 1000)
        self._slider(f, 6, "Center gap", self.gap, 0, 100)
        self._slider(f, 7, "Thickness", self.thick, 1, 20)
 
        ttk.Checkbutton(f, text="Full-screen lines", variable=self.full,
                        command=self.draw).grid(row=8, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(f, text="Center dot", variable=self.dot,
                        command=self.draw).grid(row=8, column=2, columnspan=2, sticky="w", **pad)
 
        self.color_btn = tk.Button(f, text="Color…", bg=self.color, width=10,
                                   command=self.pick_color)
        self.color_btn.grid(row=9, column=0, columnspan=2, **pad)
        ttk.Checkbutton(f, text="Show crosshair", variable=self.visible,
                        command=self.draw).grid(row=9, column=2, columnspan=2, sticky="w", **pad)
 
        self.status = ttk.Label(f, text="")
        self.status.grid(row=10, column=0, columnspan=4, sticky="w", **pad)
 
    def _slider(self, parent, row, label, var, lo, hi, redraw=True):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal",
                          length=220, command=(lambda _=None: self.draw()) if redraw else None)
        scale.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=2)
        ttk.Label(parent, textvariable=var, width=5).grid(row=row, column=3)
        # keep IntVar integral
        var.trace_add("write", lambda *_: None)
        return scale
 
    def _bind_keys(self):
        for key, (dx, dy) in {"<Left>": (-1, 0), "<Right>": (1, 0),
                              "<Up>": (0, -1), "<Down>": (0, 1)}.items():
            self.bind(key, lambda e, dx=dx, dy=dy: self.nudge(dx, dy))
            self.bind(f"<Shift-{key[1:-1]}>", lambda e, dx=dx, dy=dy: self.nudge(dx * 10, dy * 10))
 
    # ---------- actions ----------
    def _on_monitor(self, _=None):
        self.mon = self.monitors[self.mon_box.current()]
        self.overlay.place_on(self.mon)
        self.x_scale.config(to=self.mon.width - 1)
        self.y_scale.config(to=self.mon.height - 1)
        self.center()
 
    def center(self):
        self.x.set(self.mon.width // 2)
        self.y.set(self.mon.height // 2)
        self.draw()
 
    def nudge(self, dx, dy):
        s = self.step.get()
        self.x.set(max(0, min(self.mon.width - 1, self._i(self.x) + dx * s)))
        self.y.set(max(0, min(self.mon.height - 1, self._i(self.y) + dy * s)))
        self.draw()
 
    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self)[1]
        if c and c.lower() != KEY:
            self.color = c
            self.color_btn.config(bg=c)
            self.draw()
 
    @staticmethod
    def _i(var):
        return int(round(float(var.get())))
 
    # ---------- drawing ----------
    def draw(self):
        c = self.overlay.canvas
        c.delete("all")
        x, y = self._i(self.x), self._i(self.y)
        self.status.config(text=f"Position on monitor: ({x}, {y})   "
                                f"Absolute: ({self.mon.x + x}, {self.mon.y + y})")
        if not self.visible.get():
            return
        L, g, t = self._i(self.size), self._i(self.gap), self._i(self.thick)
        W, H = self.mon.width, self.mon.height
        if self.full.get():
            L = max(W, H)
        kw = dict(fill=self.color, width=t)
        c.create_line(x - L, y, x - g, y, **kw)
        c.create_line(x + g, y, x + L, y, **kw)
        c.create_line(x, y - L, x, y - g, **kw)
        c.create_line(x, y + g, x, y + L, **kw)
        if self.dot.get():
            r = max(1, t)
            c.create_oval(x - r, y - r, x + r, y + r, fill=self.color, outline=self.color)
 
 
if __name__ == "__main__":
    App().mainloop()