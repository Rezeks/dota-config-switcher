"""Dota 2 Config Switcher — перенос настроек Dota 2 с одного Steam-аккаунта на другой.

Настройки (управление, хоткеи, конфиги) лежат в:
    <Steam>\\userdata\\<AccountID>\\570\\remote
Программа копирует эту папку с аккаунта А на аккаунт Б (с резервной копией Б).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import tkinter as tk
import zipfile
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageOps
from tkinter import filedialog

APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
SETTINGS_FILE = os.path.join(APP_DIR, "switcher_settings.json")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
STEAM_ID_BASE = 76561197960265728
DOTA_APPID = "570"

# ---------- цвета ----------
BG = "#0f1115"
CARD = "#1a1e26"
CARD_HOVER = "#232a35"
FG = "#e6e9ee"
MUTED = "#8b94a3"
ACCENT = "#e0453a"      # красный Dota
SRC_COLOR = "#4aa3ff"
DST_COLOR = "#f0a93b"
OK = "#4cc38a"


# ---------- Steam ----------
def find_steam():
    try:
        import winreg
        for hive, key, val in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    p = os.path.normpath(winreg.QueryValueEx(k, val)[0])
                    if os.path.isdir(os.path.join(p, "userdata")):
                        return p
            except OSError:
                pass
    except ImportError:
        pass
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam", r"D:\Steam", r"E:\Steam"):
        if os.path.isdir(os.path.join(p, "userdata")):
            return p
    return ""


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def parse_login_users(steam):
    """{steamid64: {'account':..., 'persona':...}} из config/loginusers.vdf"""
    text = read_text(os.path.join(steam, "config", "loginusers.vdf"))
    res = {}
    for m in re.finditer(r'"(\d{17})"\s*\{(.*?)\}', text, re.S):
        body = m.group(2)
        acc = re.search(r'"AccountName"\s+"([^"]*)"', body)
        per = re.search(r'"PersonaName"\s+"([^"]*)"', body)
        res[int(m.group(1))] = {
            "account": acc.group(1) if acc else "",
            "persona": per.group(1) if per else "",
        }
    return res


def persona_from_localconfig(userdata_dir):
    text = read_text(os.path.join(userdata_dir, "config", "localconfig.vdf"))
    m = re.search(r'"PersonaName"\s+"([^"]*)"', text)
    return m.group(1) if m else ""


def dota_remote(steam, acc_id):
    return os.path.join(steam, "userdata", str(acc_id), DOTA_APPID, "remote")


def scan_accounts(steam, custom):
    users = parse_login_users(steam)
    ud = os.path.join(steam, "userdata")
    accounts = []
    if not os.path.isdir(ud):
        return accounts
    for name in sorted(os.listdir(ud)):
        if not name.isdigit() or name == "0":
            continue
        acc_id = int(name)
        sid64 = acc_id + STEAM_ID_BASE
        info = users.get(sid64, {})
        persona = (custom.get(name, {}).get("nick")
                   or info.get("persona")
                   or persona_from_localconfig(os.path.join(ud, name))
                   or f"Аккаунт {name}")
        avatar = os.path.join(steam, "config", "avatarcache", f"{sid64}.png")
        remote = dota_remote(steam, name)
        has_cfg = os.path.isdir(remote) and any(os.scandir(remote))
        accounts.append({
            "id": name,
            "sid64": sid64,
            "nick": persona,
            "login": info.get("account", ""),
            "avatar": avatar if os.path.isfile(avatar) else "",
            "has_cfg": has_cfg,
            "remote": remote,
        })
    return accounts


def running_processes():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout.lower()
    except Exception:
        return set()
    return {n for n in ("steam.exe", "dota2.exe") if n in out}


def copy_config(steam, src_id, dst_id):
    """Копирует 570/remote src -> dst. Возвращает путь резервной копии (или None)."""
    src = dota_remote(steam, src_id)
    dst = dota_remote(steam, dst_id)
    if not os.path.isdir(src):
        raise FileNotFoundError("У аккаунта-источника нет настроек Dota 2.")
    if src_id == dst_id:
        raise ValueError("Источник и получатель совпадают.")
    backup = None
    if os.path.isdir(dst):
        backup = os.path.join(BACKUP_DIR, f"{dst_id}_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copytree(dst, backup)
        shutil.rmtree(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst)
    return backup


def export_zip(steam, acc_id, zip_path):
    """Пакует 570/remote аккаунта в ZIP. Возвращает число файлов."""
    src = dota_remote(steam, acc_id)
    if not os.path.isdir(src):
        raise FileNotFoundError("У этого аккаунта нет настроек Dota 2.")
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, src))
                n += 1
    if n == 0:
        os.remove(zip_path)
        raise FileNotFoundError("Папка настроек пуста — нечего сохранять.")
    return n


def import_zip(steam, acc_id, zip_path):
    """Заменяет 570/remote аккаунта содержимым ZIP (с резервной копией). Возвращает путь копии."""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Это не ZIP-архив.")
    dst = dota_remote(steam, acc_id)
    tmp = tempfile.mkdtemp(prefix="dota_cfg_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            if z.testzip() is not None:
                raise ValueError("Архив повреждён.")
            names = [n for n in z.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError("Архив пустой.")
            root = os.path.realpath(tmp)
            for n in z.namelist():  # защита от выхода за пределы папки
                target = os.path.realpath(os.path.join(tmp, n))
                if target != root and not target.startswith(root + os.sep):
                    raise ValueError("В архиве небезопасные пути.")
            z.extractall(tmp)
        # если внутри одна общая папка (например "remote") — заходим в неё
        entries = os.listdir(tmp)
        content = tmp
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])) and entries[0].lower() in ("remote", "570"):
            content = os.path.join(tmp, entries[0])
            if entries[0].lower() == "570" and os.path.isdir(os.path.join(content, "remote")):
                content = os.path.join(content, "remote")
        backup = None
        if os.path.isdir(dst):
            backup = os.path.join(BACKUP_DIR, f"{acc_id}_{time.strftime('%Y%m%d_%H%M%S')}")
            shutil.copytree(dst, backup)
            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(content, dst)
        return backup
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- настройки приложения ----------
def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------- UI ----------
FONT = "Segoe UI"
AVATAR_PX = 128   # рисуем в большом размере, показываем меньше -> чётко на любом DPI
AVATAR_SHOW = 60

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def circle_avatar(path, nick, key):
    """Круглая аватарка со сглаживанием (PIL)."""
    S = AVATAR_PX
    if path:
        try:
            img = Image.open(path).convert("RGBA")
            img = ImageOps.fit(img, (S, S), Image.LANCZOS)
        except Exception:
            img = None
    else:
        img = None
    if img is None:
        palette = ["#3b82f6", "#e0453a", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"]
        img = Image.new("RGBA", (S, S), palette[int(key) % len(palette)] if key.isdigit() else palette[0])
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("segoeuib.ttf", int(S * 0.5))
        except OSError:
            font = ImageFont.load_default()
        ch = (nick[:1] or "?").upper()
        d.text((S / 2, S / 2), ch, fill="white", font=font, anchor="mm")
    # маска в 4x и уменьшение — гладкий край
    mask = Image.new("L", (S * 4, S * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, S * 4 - 1, S * 4 - 1), fill=255)
    mask = mask.resize((S, S), Image.LANCZOS)
    img.putalpha(mask)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(AVATAR_SHOW, AVATAR_SHOW))


class Dialog(ctk.CTkToplevel):
    """Простое окно в стиле приложения: сообщение + кнопки."""
    def __init__(self, master, title, message, buttons, accent=ACCENT, entry=None):
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.result = None
        ctk.CTkLabel(self, text=title, font=(FONT, 18, "bold"), text_color=FG).pack(
            anchor="w", padx=24, pady=(20, 6))
        ctk.CTkLabel(self, text=message, font=(FONT, 13), text_color=MUTED, justify="left",
                     wraplength=420).pack(anchor="w", padx=24, pady=(0, 12))
        self.entry = None
        if entry is not None:
            self.entry = ctk.CTkEntry(self, width=420, height=38, corner_radius=10,
                                      font=(FONT, 14), fg_color=CARD, border_width=0)
            self.entry.insert(0, entry)
            self.entry.pack(padx=24, pady=(0, 12))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(4, 20))
        for i, (text, value, primary) in enumerate(reversed(buttons)):
            ctk.CTkButton(
                row, text=text, height=38, corner_radius=10, font=(FONT, 13, "bold"),
                fg_color=accent if primary else CARD, hover_color="#c0392b" if primary else CARD_HOVER,
                command=lambda v=value: self._done(v)).pack(side="right", padx=(8, 0))
        self.bind("<Escape>", lambda e: self._done(None))
        self.after(10, self._show)

    def _show(self):
        self.transient(self.master)
        self.update_idletasks()
        m = self.master
        x = m.winfo_rootx() + (m.winfo_width() - self.winfo_width()) // 2
        y = m.winfo_rooty() + (m.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        (self.entry or self).focus_set()

    def _done(self, value):
        if self.entry is not None and value is True:
            value = self.entry.get()
        self.result = value
        self.grab_release()
        self.destroy()

    def ask(self):
        self.master.wait_window(self)
        return self.result


def ask_yes(master, title, message, yes="Да", no="Отмена"):
    return Dialog(master, title, message, [(yes, True, True), (no, False, False)]).ask() is True


def info(master, title, message):
    Dialog(master, title, message, [("OK", True, True)], accent=OK).ask()


class AccountCard(ctk.CTkFrame):
    def __init__(self, master, acc, side, on_click, on_rename):
        super().__init__(master, fg_color=CARD, corner_radius=16, border_width=2, border_color=CARD)
        self.acc = acc
        self.grid_columnconfigure(1, weight=1)
        self.avatar_img = circle_avatar(acc["avatar"], acc["nick"], acc["id"])
        self.av = ctk.CTkLabel(self, image=self.avatar_img, text="")
        self.av.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=12)
        self.nick = ctk.CTkLabel(self, text=acc["nick"], font=(FONT, 16, "bold"), text_color=FG, anchor="w")
        self.nick.grid(row=0, column=1, sticky="sw", pady=(12, 0))
        sub = f"ID {acc['id']}" + (f"  ·  {acc['login']}" if acc["login"] else "")
        self.sub = ctk.CTkLabel(self, text=sub, font=(FONT, 12), text_color=MUTED, anchor="w")
        self.sub.grid(row=1, column=1, sticky="nw", pady=(0, 12))
        self.badge = ctk.CTkLabel(
            self, text="  ● настройки Dota есть  " if acc["has_cfg"] else "  ○ настроек нет  ",
            font=(FONT, 11), text_color=OK if acc["has_cfg"] else MUTED,
            fg_color="#16301f" if acc["has_cfg"] else "#232830", corner_radius=10)
        self.badge.grid(row=0, column=2, rowspan=2, padx=14)
        self.selected = False
        for w in (self, self.av, self.nick, self.sub, self.badge):
            w.bind("<Button-1>", lambda e: on_click(acc))
            w.bind("<Button-3>", lambda e: on_rename(acc))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _hover(self, on):
        self.configure(fg_color=CARD_HOVER if on else CARD)

    def set_selected(self, color):
        self.configure(border_color=color or CARD)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("Dota 2 — перенос настроек между аккаунтами")
        self.geometry("1100x720")
        self.minsize(960, 600)
        self.settings = load_settings()
        self.steam = self.settings.get("steam") or find_steam()
        self.src = None
        self.dst = None
        self.cards = {"src": {}, "dst": {}}
        self.accounts = []
        self._build()
        self.refresh()

    def _btn(self, parent, text, cmd, **kw):
        opts = dict(height=34, corner_radius=10, font=(FONT, 13), fg_color=CARD, hover_color=CARD_HOVER,
                    text_color=FG)
        opts.update(kw)
        return ctk.CTkButton(parent, text=text, command=cmd, **opts)

    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(22, 0))
        ctk.CTkLabel(top, text="Перенос настроек Dota 2", font=(FONT, 26, "bold"), text_color=FG).pack(side="left")
        self._btn(top, "Папка Steam…", self.pick_steam, width=130).pack(side="right")
        self._btn(top, "☁  Steam Cloud", self.cloud_help, width=130).pack(side="right", padx=(0, 8))
        self._btn(top, "⟳  Обновить", self.refresh, width=120).pack(side="right", padx=8)
        self.path_lbl = ctk.CTkLabel(self, text="", font=(FONT, 12), text_color=MUTED, anchor="w")
        self.path_lbl.pack(fill="x", padx=28, pady=(2, 8))

        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="both", expand=True, padx=20, pady=0)
        cols.grid_columnconfigure(0, weight=1, uniform="c")
        cols.grid_columnconfigure(1, weight=0)
        cols.grid_columnconfigure(2, weight=1, uniform="c")
        cols.grid_rowconfigure(1, weight=1)
        for col, text, color, btn_text, cmd in (
                (0, "ОТКУДА  ·  аккаунт А", SRC_COLOR, "⬇  Скачать ZIP", self.export_selected),
                (2, "КУДА  ·  аккаунт Б", DST_COLOR, "⬆  Загрузить из ZIP", self.import_selected)):
            head = ctk.CTkFrame(cols, fg_color="transparent")
            head.grid(row=0, column=col, sticky="ew", padx=(10, 6), pady=(0, 4))
            ctk.CTkLabel(head, text=text, font=(FONT, 13, "bold"), text_color=color).pack(side="left")
            self._btn(head, btn_text, cmd, height=30, width=150, font=(FONT, 12)).pack(side="right")
        self.src_list = ctk.CTkScrollableFrame(cols, fg_color="transparent")
        self.src_list.grid(row=1, column=0, sticky="nsew")
        self.dst_list = ctk.CTkScrollableFrame(cols, fg_color="transparent")
        self.dst_list.grid(row=1, column=2, sticky="nsew")
        ctk.CTkLabel(cols, text="➜", font=(FONT, 34, "bold"), text_color=ACCENT, width=60
                     ).grid(row=1, column=1)

        bottom = ctk.CTkFrame(self, fg_color=CARD, corner_radius=18)
        bottom.pack(fill="x", padx=26, pady=(10, 8))
        self.avs = ctk.CTkLabel(bottom, text="")
        self.avs.pack(side="left", padx=(16, 4), pady=12)
        self.arrow = ctk.CTkLabel(bottom, text="", font=(FONT, 20, "bold"), text_color=ACCENT)
        self.arrow.pack(side="left")
        self.avd = ctk.CTkLabel(bottom, text="")
        self.avd.pack(side="left", padx=(4, 12))
        self.summary = ctk.CTkLabel(bottom, text="", font=(FONT, 15), text_color=FG, anchor="w")
        self.summary.pack(side="left", fill="x", expand=True)
        self.go_btn = ctk.CTkButton(bottom, text="Перенести  →", command=self.do_copy, state="disabled",
                                    height=48, width=190, corner_radius=14, font=(FONT, 16, "bold"),
                                    fg_color=ACCENT, hover_color="#c0392b", text_color_disabled="#8a7a7a")
        self.go_btn.pack(side="right", padx=16, pady=14)
        self._btn(bottom, "⇄  Поменять", self.swap, width=130, height=48, corner_radius=14,
                  fg_color=BG, hover_color=CARD_HOVER).pack(side="right", pady=14)
        ctk.CTkLabel(self, text="Правый клик по аккаунту — задать свой ник  ·  перед записью делается "
                                "резервная копия настроек получателя (папка backups)",
                     font=(FONT, 11), text_color=MUTED).pack(pady=(0, 12))

    # --- данные ---
    def refresh(self):
        self.path_lbl.configure(text=f"Steam: {self.steam or 'не найден — нажмите «Папка Steam…»'}")
        for fr in (self.src_list, self.dst_list):
            for w in fr.winfo_children():
                w.destroy()
        self.cards = {"src": {}, "dst": {}}
        self.accounts = scan_accounts(self.steam, self.settings.get("custom", {})) if self.steam else []
        ids = {a["id"] for a in self.accounts}
        if self.src not in ids:
            self.src = None
        if self.dst not in ids:
            self.dst = None
        for side, frame in (("src", self.src_list), ("dst", self.dst_list)):
            for acc in self.accounts:
                card = AccountCard(frame, acc, side, lambda a, s=side: self.select(s, a), self.rename)
                card.pack(fill="x", pady=5, padx=(0, 6))
                self.cards[side][acc["id"]] = card
        if not self.accounts:
            ctk.CTkLabel(self.src_list, text="Аккаунты не найдены.\nПроверьте папку Steam.",
                         font=(FONT, 14), text_color=MUTED).pack(pady=40)
        self.update_state()

    def acc_by_id(self, i):
        return next((a for a in self.accounts if a["id"] == i), None)

    def select(self, side, acc):
        if side == "src":
            self.src = None if self.src == acc["id"] else acc["id"]
        else:
            self.dst = None if self.dst == acc["id"] else acc["id"]
        self.update_state()

    def swap(self):
        self.src, self.dst = self.dst, self.src
        self.update_state()

    def _set_av(self, label, acc):
        if acc:
            img = circle_avatar(acc["avatar"], acc["nick"], acc["id"])
            small = ctk.CTkImage(img._light_image, img._dark_image, size=(44, 44))
            label.configure(image=small)
            label._keep = small
        else:
            label.configure(image=None)
            label._keep = None

    def update_state(self):
        for side, sel, color in (("src", self.src, SRC_COLOR), ("dst", self.dst, DST_COLOR)):
            for i, card in self.cards[side].items():
                card.set_selected(color if i == sel else None)
        s, d = self.acc_by_id(self.src), self.acc_by_id(self.dst)
        self._set_av(self.avs, s)
        self._set_av(self.avd, d)
        self.arrow.configure(text="➜" if (s or d) else "")
        ok = bool(s and d and s["id"] != d["id"] and s["has_cfg"])
        if s and d:
            if s["id"] == d["id"]:
                text = "Выберите разные аккаунты"
            elif not s["has_cfg"]:
                text = f"У «{s['nick']}» нет настроек Dota 2 для переноса"
            else:
                text = f"{s['nick']}  →  {d['nick']}"
        elif s or d:
            text = f"{(s or d)['nick']}  —  выберите второй аккаунт"
        else:
            text = "Выберите аккаунт «Откуда» и аккаунт «Куда»"
        self.summary.configure(text=text)
        self.go_btn.configure(state="normal" if ok else "disabled")

    def rename(self, acc):
        new = Dialog(self, "Свой ник", f"Ник для ID {acc['id']}. Пусто — вернуть стандартный.",
                     [("Сохранить", True, True), ("Отмена", None, False)], entry=acc["nick"]).ask()
        if new is None or new is False:
            return
        custom = self.settings.setdefault("custom", {})
        if str(new).strip():
            custom[acc["id"]] = {"nick": str(new).strip()}
        else:
            custom.pop(acc["id"], None)
        save_settings(self.settings)
        self.refresh()

    def pick_steam(self):
        p = filedialog.askdirectory(title="Выберите папку Steam (где лежит userdata)")
        if p:
            p = os.path.normpath(p)
            if not os.path.isdir(os.path.join(p, "userdata")):
                info(self, "Ошибка", "В этой папке нет подпапки userdata.")
                return
            self.steam = p
            self.settings["steam"] = p
            save_settings(self.settings)
            self.refresh()

    def do_copy(self):
        s, d = self.acc_by_id(self.src), self.acc_by_id(self.dst)
        if not (s and d):
            return
        running = running_processes()
        if running and not ask_yes(
                self, "Steam / Dota запущены",
                f"Запущено: {', '.join(sorted(running))}.\n\nSteam Cloud может перезаписать перенесённые "
                "настройки. Лучше закрыть Steam и Dota.\n\nПродолжить всё равно?", "Продолжить"):
            return
        if not ask_yes(
                self, "Подтверждение",
                f"Перенести настройки Dota 2\n\nиз:  {s['nick']} ({s['id']})\nна:  {d['nick']} ({d['id']})\n\n"
                "Текущие настройки получателя будут заменены (резервная копия сохранится).", "Перенести"):
            return
        try:
            backup = copy_config(self.steam, s["id"], d["id"])
        except Exception as e:
            info(self, "Ошибка", str(e))
            return
        msg = f"{s['nick']}  →  {d['nick']}"
        if backup:
            msg += f"\n\nРезервная копия:\n{backup}"
        info(self, "Готово", msg)
        self.refresh()

    def cloud_help(self):
        text = ("Steam Cloud может перезаписать перенесённые настройки.\n\n"
                "Чтобы отключить его для Dota 2:\n"
                "1. Нажмите «Открыть свойства Dota 2» (Steam должен быть запущен).\n"
                "2. Вкладка «Общие» → снимите галочку «Сохранять игровые данные в облаке Steam».\n"
                "3. Сделайте перенос, затем при желании включите обратно.\n\n"
                "Либо просто закройте Steam на время переноса.")
        while True:
            r = Dialog(self, "Steam Cloud", text, [
                ("Открыть свойства Dota 2", "props", True),
                ("Закрыть Steam", "exit", False),
                ("Закрыть окно", None, False)]).ask()
            if r == "props":
                try:
                    os.startfile("steam://gameproperties/570")
                except OSError:
                    info(self, "Ошибка", "Не удалось открыть Steam. Запущен ли он?")
            elif r == "exit":
                try:
                    os.startfile("steam://exit")
                except OSError:
                    info(self, "Ошибка", "Не удалось закрыть Steam.")
            else:
                return

    def export_selected(self):
        a = self.acc_by_id(self.src)
        if not a:
            info(self, "Скачать ZIP", "Сначала выберите аккаунт слева («Откуда»).")
            return
        if not a["has_cfg"]:
            info(self, "Скачать ZIP", f"У «{a['nick']}» нет настроек Dota 2.")
            return
        safe = re.sub(r'[\\/:*?"<>|]', "_", a["nick"]).strip() or a["id"]
        path = filedialog.asksaveasfilename(
            title="Сохранить конфиг в ZIP", defaultextension=".zip",
            initialfile=f"dota2_config_{safe}_{time.strftime('%Y%m%d')}.zip",
            filetypes=[("ZIP-архив", "*.zip")])
        if not path:
            return
        try:
            n = export_zip(self.steam, a["id"], path)
        except Exception as e:
            info(self, "Ошибка", str(e))
            return
        info(self, "Готово", f"Конфиг «{a['nick']}» сохранён ({n} файлов):\n{path}")

    def import_selected(self):
        a = self.acc_by_id(self.dst)
        if not a:
            info(self, "Загрузить из ZIP", "Сначала выберите аккаунт справа («Куда»).")
            return
        path = filedialog.askopenfilename(title="Выберите ZIP с конфигом",
                                          filetypes=[("ZIP-архив", "*.zip"), ("Все файлы", "*.*")])
        if not path:
            return
        running = running_processes()
        if running and not ask_yes(
                self, "Steam / Dota запущены",
                f"Запущено: {', '.join(sorted(running))}.\n\nSteam Cloud может перезаписать загруженные "
                "настройки. Лучше закрыть Steam и Dota.\n\nПродолжить всё равно?", "Продолжить"):
            return
        if not ask_yes(self, "Подтверждение",
                       f"Загрузить конфиг из\n{os.path.basename(path)}\n\nна аккаунт «{a['nick']}» ({a['id']})?\n\n"
                       "Текущие настройки будут заменены (резервная копия сохранится).", "Загрузить"):
            return
        try:
            backup = import_zip(self.steam, a["id"], path)
        except Exception as e:
            info(self, "Ошибка", str(e))
            return
        msg = f"Конфиг загружен на «{a['nick']}»."
        if backup:
            msg += f"\n\nРезервная копия:\n{backup}"
        info(self, "Готово", msg)
        self.refresh()


if __name__ == "__main__":
    App().mainloop()
