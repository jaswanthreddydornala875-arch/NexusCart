"""NexusCart Tkinter theme and reusable ttk styling."""
import tkinter as tk
from tkinter import font as tkfont, ttk

# --- Theme: Amazon-inspired palette, flat and clean ---------------------------
NAVY, NAVY_2 = "#131921", "#232F3E"
BG, SURFACE = "#EAEDED", "#FFFFFF"
TEXT, MUTED = "#0F1111", "#565959"
LINK, LINK_HOVER = "#007185", "#C7511F"
LINE, HOVER, HEAD_BG = "#D5D9D9", "#F7FAFA", "#F0F2F2"
PRICE, RED, GREEN, WARN = "#B12704", "#B12704", "#007600", "#C45500"
STAR = "#FFA41C"
YELLOW, YELLOW_H = "#FFD814", "#F7CA00"
ORANGE, ORANGE_H = "#FFA41C", "#FA8900"

# Fonts: first installed one wins. Edit the lists to taste (Tkinter can only use
# fonts installed on the machine).
BODY_FONTS = ["Inter", "Nunito Sans", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "DejaVu Sans"]
HEADING_FONTS = ["Poppins", "Montserrat", "Inter", "Segoe UI Semibold", "Helvetica Neue", "DejaVu Sans"]
MONO_FONTS = ["JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono"]
FONT, HEAD, MONO = "Segoe UI", "Segoe UI", "Consolas"   # replaced at startup by pick_fonts()

def pick_fonts(root):
    global FONT, HEAD, MONO
    have = {f.lower() for f in tkfont.families(root)}

    def first(names):
        return next((n for n in names if n.lower() in have), names[-1])

    FONT, HEAD, MONO = first(BODY_FONTS), first(HEADING_FONTS), first(MONO_FONTS)


def button_style(s, name, bg, hover, fg, border=None):
    """Flat button whose face, border and bevel colours match in every state
    (the 'clam' theme otherwise draws mismatched light/dark edges)."""
    border = border or bg
    hb = border if border != bg else hover
    s.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg,
                darkcolor=bg, focuscolor=bg, borderwidth=1, padding=(14, 7), relief="flat")
    s.map(name,
          background=[("disabled", HEAD_BG), ("pressed", hover), ("active", hover)],
          foreground=[("disabled", MUTED), ("pressed", fg), ("active", fg)],
          bordercolor=[("disabled", LINE), ("pressed", hb), ("active", hb)],
          lightcolor=[("disabled", HEAD_BG), ("pressed", hover), ("active", hover)],
          darkcolor=[("disabled", HEAD_BG), ("pressed", hover), ("active", hover)],
          relief=[("pressed", "flat"), ("!pressed", "flat")])


def apply_style(root):
    pick_fonts(root)
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=(FONT, 10), borderwidth=0, focuscolor=BG)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", foreground=MUTED)

    button_style(s, "TButton", NAVY_2, "#37475A", "white")
    button_style(s, "Secondary.TButton", "#E3E6E6", LINE, TEXT)
    button_style(s, "Yellow.TButton", YELLOW, YELLOW_H, TEXT)
    button_style(s, "Orange.TButton", ORANGE, ORANGE_H, TEXT)

    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=5)
    s.map("TEntry", bordercolor=[("focus", STAR)], lightcolor=[("focus", STAR)],
          darkcolor=[("focus", STAR)])
    s.map("TCombobox", fieldbackground=[("readonly", SURFACE)], bordercolor=[("focus", STAR)],
          selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)])
    for w in ("Error.TEntry", "Error.TCombobox"):      # red outline for fields with a mistake
        s.configure(w, bordercolor=RED, lightcolor=RED, darkcolor=RED)
        s.map(w, bordercolor=[("focus", RED)], lightcolor=[("focus", RED)], darkcolor=[("focus", RED)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", HEAD_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    s.configure("Card.TRadiobutton", background=SURFACE, foreground=TEXT, focuscolor=SURFACE,
                indicatorcolor="white")
    s.map("Card.TRadiobutton", background=[("active", SURFACE)], indicatorcolor=[("selected", STAR)])

    s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                rowheight=32, borderwidth=0)
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.map("Treeview", background=[("selected", "#FFF3D6")], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=HEAD_BG, foreground=MUTED, font=(HEAD, 9, "bold"),
                relief="flat", padding=(8, 8))
    s.map("Treeview.Heading", background=[("active", HEAD_BG)])

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=0,
                bordercolor=BG, lightcolor=BG, darkcolor=BG)
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 10),
                bordercolor=BG, lightcolor=BG, darkcolor=BG)
    s.map("TNotebook.Tab", foreground=[("selected", TEXT)], background=[("selected", SURFACE)])

    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", background="#C4C8C8", troughcolor=BG, arrowsize=10,
                gripcount=0, bordercolor=BG, lightcolor="#C4C8C8", darkcolor="#C4C8C8")

    return FONT, HEAD, MONO


def get_fonts():
    return FONT, HEAD, MONO
