#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# source: https://github.com/zeittresor/compile-c-
r"""
CSC GUI Builder (Windows 10)

A small Tkinter GUI (stdlib only) that compiles a single .cs file to a Windows .exe.

Backends
- csc:   Uses legacy .NET Framework csc.exe (typically: %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe)
- dotnet Uses .NET SDK (dotnet publish) for modern .NET (WinForms/WPF, .NET 6+, modern C#)
"""

import os
import sys
import shutil
import tempfile
import threading
import queue
import subprocess
import platform
import re
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_ID = "CSC GUI Builder"
DEFAULT_TFM = "net8.0"

PROGRESS_SPINNER_RE = re.compile(r"^\s*[-\\|/]\s*$")
PROGRESS_BAR_RE = re.compile(
    r"(?:\b\d{1,3}\s*%|\b\d+(?:\.\d+)?\s*(?:KB|MB|GB)\s*/\s*\d+(?:\.\d+)?\s*(?:KB|MB|GB))",
    re.IGNORECASE
)

LANGS = [
    ("de", "Deutsch"),
    ("en", "English"),
    ("fr", "Français"),
    ("es", "Español"),
    ("zh-Hans", "简体中文"),
    ("ru", "Русский"),
]

T = {
    "title": {
        "de": "CSC GUI Builder",
        "en": "CSC GUI Builder",
        "fr": "CSC GUI Builder",
        "es": "CSC GUI Builder",
        "zh-Hans": "CSC GUI 编译器",
        "ru": "CSC GUI Builder",
    },
    "compiler": {"de": "Compiler:", "en": "Compiler:", "fr": "Compilateur :", "es": "Compilador:", "zh-Hans": "编译器：", "ru": "Компилятор:"},
    "recheck": {"de": "Neu prüfen", "en": "Recheck", "fr": "Rechercher", "es": "Volver a buscar", "zh-Hans": "重新检测", "ru": "Проверить снова"},
    "install_auto": {"de": "Compiler installieren (Auto)", "en": "Install compiler (Auto)", "fr": "Installer le compilateur (Auto)", "es": "Instalar compilador (Auto)", "zh-Hans": "安装编译器（自动）", "ru": "Установить компилятор (авто)"},
    "backend": {"de": "Backend:", "en": "Backend:", "fr": "Backend :", "es": "Backend:", "zh-Hans": "后端：", "ru": "Бэкенд:"},
    "backend_hint": {
        "de": "(auto=smart, csc=.NET Framework, dotnet=SDK)",
        "en": "(auto=smart, csc=.NET Framework, dotnet=SDK)",
        "fr": "(auto=intelligent, csc=.NET Framework, dotnet=SDK)",
        "es": "(auto=inteligente, csc=.NET Framework, dotnet=SDK)",
        "zh-Hans": "（auto=智能，csc=.NET Framework，dotnet=SDK）",
        "ru": "(auto=умно, csc=.NET Framework, dotnet=SDK)",
    },
    "language": {"de": "Sprache:", "en": "Language:", "fr": "Langue :", "es": "Idioma:", "zh-Hans": "语言：", "ru": "Язык:"},
    "files": {"de": "Dateien", "en": "Files", "fr": "Fichiers", "es": "Archivos", "zh-Hans": "文件", "ru": "Файлы"},
    "source": {"de": "C#-Source (.cs):", "en": "C# source (.cs):", "fr": "Source C# (.cs) :", "es": "Código C# (.cs):", "zh-Hans": "C# 源码（.cs）：", "ru": "Исходник C# (.cs):"},
    "output": {"de": "Output EXE:", "en": "Output EXE:", "fr": "EXE de sortie :", "es": "EXE de salida:", "zh-Hans": "输出 EXE：", "ru": "Выходной EXE:"},
    "choose": {"de": "Auswählen…", "en": "Browse…", "fr": "Choisir…", "es": "Elegir…", "zh-Hans": "选择…", "ru": "Выбрать…"},
    "save_as": {"de": "Speichern als…", "en": "Save as…", "fr": "Enregistrer sous…", "es": "Guardar como…", "zh-Hans": "另存为…", "ru": "Сохранить как…"},
    "options": {"de": "Optionen", "en": "Options", "fr": "Options", "es": "Opciones", "zh-Hans": "选项", "ru": "Параметры"},
    "target_type": {"de": "Zieltyp:", "en": "Target type:", "fr": "Type de cible :", "es": "Tipo de destino:", "zh-Hans": "目标类型：", "ru": "Тип:"},
    "console_exe": {"de": "Console EXE", "en": "Console EXE", "fr": "EXE Console", "es": "EXE de consola", "zh-Hans": "控制台 EXE", "ru": "Консольный EXE"},
    "windows_exe": {"de": "Windows GUI EXE (kein Console-Fenster)", "en": "Windows GUI EXE (no console)", "fr": "EXE GUI Windows (sans console)", "es": "EXE GUI Windows (sin consola)", "zh-Hans": "Windows 图形 EXE（无控制台）", "ru": "GUI EXE (без консоли)"},
    "dotnet_fallback": {"de": "dotnet Fallback:", "en": "dotnet fallback:", "fr": "Repli dotnet :", "es": "Alternativa dotnet:", "zh-Hans": "dotnet 备用：", "ru": "dotnet (резерв):"},
    "self_contained": {"de": "Self-contained (Standalone, größer)", "en": "Self-contained (standalone, larger)", "fr": "Autonome (plus volumineux)", "es": "Autocontenido (más grande)", "zh-Hans": "自包含（独立运行，更大）", "ru": "Self-contained (больше)"},
    "single_file": {"de": "Single-file (eine EXE)", "en": "Single-file (one EXE)", "fr": "Fichier unique (un EXE)", "es": "Archivo único (un EXE)", "zh-Hans": "单文件（一个 EXE）", "ru": "Single-file (один EXE)"},
    "compile": {"de": "Kompilieren", "en": "Compile", "fr": "Compiler", "es": "Compilar", "zh-Hans": "编译", "ru": "Скомпилировать"},
    "log": {"de": "Ausgabe / Log", "en": "Output / Log", "fr": "Sortie / Log", "es": "Salida / Log", "zh-Hans": "输出 / 日志", "ru": "Вывод / Лог"},
    "status_ready": {"de": "Bereit.", "en": "Ready.", "fr": "Prêt.", "es": "Listo.", "zh-Hans": "就绪。", "ru": "Готово."},
    "status_searching": {"de": "Suche nach csc.exe / dotnet ...", "en": "Searching for csc.exe / dotnet ...", "fr": "Recherche de csc.exe / dotnet ...", "es": "Buscando csc.exe / dotnet ...", "zh-Hans": "正在查找 csc.exe / dotnet ...", "ru": "Поиск csc.exe / dotnet ..."},
    "status_missing": {"de": "Compiler fehlt – bitte installieren.", "en": "Compiler missing – please install.", "fr": "Compilateur manquant – veuillez installer.", "es": "Falta el compilador: instálalo.", "zh-Hans": "缺少编译器——请安装。", "ru": "Компилятор не найден — установите."},
    "status_installing": {"de": "Installiere Compiler (auto) ...", "en": "Installing compiler (auto) ...", "fr": "Installation du compilateur (auto) ...", "es": "Instalando compilador (auto) ...", "zh-Hans": "正在安装编译器（自动）...", "ru": "Установка компилятора (авто) ..."},
    "status_compiling": {"de": "Kompiliere ...", "en": "Compiling ...", "fr": "Compilation ...", "es": "Compilando ...", "zh-Hans": "正在编译 ...", "ru": "Компиляция ..."},
    "status_done": {"de": "Fertig.", "en": "Done.", "fr": "Terminé.", "es": "Hecho.", "zh-Hans": "完成。", "ru": "Готово."},
    "status_failed": {"de": "Fehlgeschlagen.", "en": "Failed.", "fr": "Échec.", "es": "Falló.", "zh-Hans": "失败。", "ru": "Ошибка."},
    "err": {"de": "Fehler", "en": "Error", "fr": "Erreur", "es": "Error", "zh-Hans": "错误", "ru": "Ошибка"},
    "err_need_source": {
        "de": "Bitte eine gültige C#-Source-Datei auswählen (.cs).",
        "en": "Please select a valid C# source file (.cs).",
        "fr": "Veuillez sélectionner un fichier source C# valide (.cs).",
        "es": "Selecciona un archivo C# válido (.cs).",
        "zh-Hans": "请选择有效的 C# 源文件（.cs）。",
        "ru": "Выберите корректный файл исходника C# (.cs).",
    },
    "err_need_output": {
        "de": "Bitte einen Output-Pfad für die EXE auswählen.",
        "en": "Please choose an output path for the EXE.",
        "fr": "Veuillez choisir un chemin de sortie pour l'EXE.",
        "es": "Elige una ruta de salida para el EXE.",
        "zh-Hans": "请选择 EXE 输出路径。",
        "ru": "Выберите путь для выходного EXE.",
    },
    # log messages (short + helpful)
    "log_detect": {"de": "== Compiler-Erkennung ==", "en": "== Compiler detection ==", "fr": "== Détection du compilateur ==", "es": "== Detección del compilador ==", "zh-Hans": "== 编译器检测 ==", "ru": "== Обнаружение компилятора =="},
    "log_found_csc": {"de": "Gefunden: csc.exe -> {path}", "en": "Found: csc.exe -> {path}", "fr": "Trouvé : csc.exe -> {path}", "es": "Encontrado: csc.exe -> {path}", "zh-Hans": "已找到：csc.exe -> {path}", "ru": "Найден: csc.exe -> {path}"},
    "log_found_dotnet": {"de": "dotnet gefunden: {path}", "en": "dotnet found: {path}", "fr": "dotnet trouvé : {path}", "es": "dotnet encontrado: {path}", "zh-Hans": "已找到 dotnet：{path}", "ru": "dotnet найден: {path}"},
    "log_neither": {
        "de": "Weder csc.exe noch dotnet.exe gefunden.",
        "en": "Neither csc.exe nor dotnet.exe found.",
        "fr": "Ni csc.exe ni dotnet.exe trouvés.",
        "es": "No se encontró csc.exe ni dotnet.exe.",
        "zh-Hans": "未找到 csc.exe 或 dotnet.exe。",
        "ru": "Не найдено ни csc.exe, ни dotnet.exe.",
    },
    "log_install_started": {"de": "== Installation gestartet ==", "en": "== Installation started ==", "fr": "== Installation démarrée ==", "es": "== Instalación iniciada ==", "zh-Hans": "== 开始安装 ==", "ru": "== Установка началась =="},
    "log_compile_started": {"de": "== Kompilierung gestartet ==", "en": "== Compilation started ==", "fr": "== Compilation démarrée ==", "es": "== Compilación iniciada ==", "zh-Hans": "== 开始编译 ==", "ru": "== Компиляция началась =="},
    "log_source": {"de": "Source: {path}", "en": "Source: {path}", "fr": "Source : {path}", "es": "Fuente: {path}", "zh-Hans": "源码：{path}", "ru": "Исходник: {path}"},
    "log_output": {"de": "Output: {path}", "en": "Output: {path}", "fr": "Sortie : {path}", "es": "Salida: {path}", "zh-Hans": "输出：{path}", "ru": "Вывод: {path}"},
    "log_saved_raw": {
        "de": "[{phase}] Vollständiges Log gespeichert: {path}",
        "en": "[{phase}] Full log saved: {path}",
        "fr": "[{phase}] Log complet enregistré : {path}",
        "es": "[{phase}] Log completo guardado: {path}",
        "zh-Hans": "[{phase}] 完整日志已保存：{path}",
        "ru": "[{phase}] Полный лог сохранён: {path}",
    },
    "log_success_csc": {"de": "✅ Kompilierung erfolgreich (csc).", "en": "✅ Compilation succeeded (csc).", "fr": "✅ Compilation réussie (csc).", "es": "✅ Compilación exitosa (csc).", "zh-Hans": "✅ 编译成功（csc）。", "ru": "✅ Компиляция успешна (csc)."},
    "log_fail_csc": {"de": "❌ Kompilierung fehlgeschlagen (csc), code {code}.", "en": "❌ Compilation failed (csc), code {code}.", "fr": "❌ Échec de compilation (csc), code {code}.", "es": "❌ Falló la compilación (csc), código {code}.", "zh-Hans": "❌ 编译失败（csc），代码 {code}。", "ru": "❌ Ошибка компиляции (csc), код {code}."},
    "log_hint_old_csc": {
        "de": "Hinweis: Der .NET Framework csc.exe ist oft zu alt für .NET 6+ / moderne C# Syntax. Dann Backend=dotnet wählen.",
        "en": "Tip: The .NET Framework csc.exe is often too old for .NET 6+ / modern C#. Choose Backend=dotnet.",
        "fr": "Astuce : csc.exe (.NET Framework) est souvent trop ancien pour .NET 6+ / C# moderne. Choisissez Backend=dotnet.",
        "es": "Consejo: csc.exe (.NET Framework) suele ser demasiado antiguo para .NET 6+ / C# moderno. Usa Backend=dotnet.",
        "zh-Hans": "提示：.NET Framework 的 csc.exe 往往不支持 .NET 6+ / 现代 C#，请选择后端 dotnet。",
        "ru": "Совет: csc.exe (.NET Framework) часто слишком стар для .NET 6+ / современного C#. Выберите Backend=dotnet.",
    },
    "log_success_dotnet": {"de": "✅ Kompilierung erfolgreich (dotnet). EXE kopiert nach: {path}", "en": "✅ Compilation succeeded (dotnet). EXE copied to: {path}", "fr": "✅ Compilation réussie (dotnet). EXE copiée vers : {path}", "es": "✅ Compilación exitosa (dotnet). EXE copiado a: {path}", "zh-Hans": "✅ 编译成功（dotnet）。EXE 已复制到：{path}", "ru": "✅ Компиляция успешна (dotnet). EXE скопирован в: {path}"},
}

def is_windows() -> bool:
    return os.name == "nt"

def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("mbcs", errors="replace")

def run_capture(cmd, cwd=None, env=None) -> tuple[int, str]:
    try:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out_b, _ = p.communicate()
        return p.returncode, _decode_output(out_b or b"")
    except FileNotFoundError as e:
        return 127, str(e)
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"

def where(exe_name: str) -> str | None:
    if not is_windows():
        return None
    rc, out = run_capture(["where", exe_name])
    if rc == 0 and out.strip():
        return out.strip().splitlines()[0].strip()
    return None

def find_csc_candidates() -> list[str]:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        str(Path(windir) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"),
        str(Path(windir) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"),
    ]
    for root in [Path(windir) / "Microsoft.NET" / "Framework64", Path(windir) / "Microsoft.NET" / "Framework"]:
        if root.exists():
            for v in sorted(root.glob("v*"), reverse=True):
                exe = v / "csc.exe"
                if exe.exists():
                    candidates.append(str(exe))
    p = where("csc.exe")
    if p:
        candidates.insert(0, p)

    uniq, seen = [], set()
    for c in candidates:
        c_norm = os.path.normcase(os.path.abspath(c))
        if c_norm not in seen:
            seen.add(c_norm)
            uniq.append(c)
    return uniq

def pick_existing(paths: list[str]) -> str | None:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None

def detect_dotnet() -> str | None:
    p = where("dotnet.exe")
    if p:
        return p
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    p2 = Path(pf) / "dotnet" / "dotnet.exe"
    return str(p2) if p2.exists() else None

def arch_rid() -> str:
    m = platform.machine().lower()
    if "arm" in m:
        return "win-arm64" if "64" in m else "win-arm"
    if m in ("amd64", "x86_64") or "64" in m:
        return "win-x64"
    return "win-x86"

def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def filter_noisy_progress(lines: list[str]) -> list[str]:
    cleaned, blank_run = [], 0
    for ln in lines:
        raw = ln.rstrip("\n")
        if not raw.strip():
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        if PROGRESS_SPINNER_RE.match(raw):
            continue
        if ("█" in raw) or ("▒" in raw) or ("░" in raw) or ("â–" in raw) or PROGRESS_BAR_RE.search(raw):
            if "http" in raw.lower() or "Microsoft.DotNet" in raw or "Paket" in raw or "Installer" in raw:
                cleaned.append(raw)
            continue
        cleaned.append(raw)
    return cleaned

def read_text_guess(path: str) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "mbcs"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8", errors="replace")

def analyze_source(code: str) -> dict:
    uses_winforms = ("System.Windows.Forms" in code) or ("using System.Windows.Forms" in code)
    uses_wpf = ("UseWPF" in code) or ("PresentationFramework" in code)
    has_appconfig_init = "ApplicationConfiguration.Initialize" in code

    modern_markers = [
        "using var ",
        "record ",
        "object?",
        "string?",
        "init;",
        "Span<",
        "async Task Main",
    ]
    seems_modern = has_appconfig_init or any(m in code for m in modern_markers)
    prefer_dotnet = seems_modern or uses_winforms or uses_wpf
    return {
        "uses_winforms": uses_winforms,
        "uses_wpf": uses_wpf,
        "has_appconfig_init": has_appconfig_init,
        "prefer_dotnet": prefer_dotnet,
    }

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        # language state
        self.lang_code = "de"
        self.lang_display_var = tk.StringVar(value=dict(LANGS).get("de", "Deutsch"))
        self._status_key = "status_ready"

        # threading / IO
        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        # state vars
        self.source_path = tk.StringVar(value="")
        self.output_path = tk.StringVar(value="")
        self.compiler_path = tk.StringVar(value="(suche ...)")
        self.backend_choice = tk.StringVar(value="auto")  # auto|csc|dotnet
        self.target_type = tk.StringVar(value="winexe")   # exe|winexe
        self.dotnet_selfcontained = tk.BooleanVar(value=True)
        self.dotnet_singlefile = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="")

        # build UI
        self._build_ui()
        self.apply_language()

        self.after(80, self.detect_compiler)
        self.after(80, self._drain_log_queue)

    # ---------- i18n ----------
    def tr(self, key: str, **fmt) -> str:
        d = T.get(key, {})
        s = d.get(self.lang_code) or d.get("en") or d.get("de") or key
        try:
            return s.format(**fmt)
        except Exception:
            return s

    def set_status(self, key: str):
        self._status_key = key
        self.status_text.set(self.tr(key))

    def on_language_changed(self, *_):
        disp = self.lang_display_var.get()
        inv = {name: code for code, name in LANGS}
        self.lang_code = inv.get(disp, "en")
        self.apply_language()

    def apply_language(self):
        self.title(self.tr("title"))
        # top
        self.lbl_compiler.configure(text=self.tr("compiler"))
        self.btn_recheck.configure(text=self.tr("recheck"))
        self.btn_install.configure(text=self.tr("install_auto"))
        self.lbl_backend.configure(text=self.tr("backend"))
        self.lbl_backend_hint.configure(text=self.tr("backend_hint"))
        self.lbl_language.configure(text=self.tr("language"))

        # frames
        self.frame_files.configure(text=self.tr("files"))
        self.frame_opts.configure(text=self.tr("options"))
        self.frame_log.configure(text=self.tr("log"))

        # IO
        self.lbl_source.configure(text=self.tr("source"))
        self.btn_choose_source.configure(text=self.tr("choose"))
        self.lbl_output.configure(text=self.tr("output"))
        self.btn_choose_output.configure(text=self.tr("save_as"))

        # options
        self.lbl_target.configure(text=self.tr("target_type"))
        self.rb_console.configure(text=self.tr("console_exe"))
        self.rb_winexe.configure(text=self.tr("windows_exe"))
        self.lbl_dotnet.configure(text=self.tr("dotnet_fallback"))
        self.cb_self.configure(text=self.tr("self_contained"))
        self.cb_single.configure(text=self.tr("single_file"))

        # actions
        self.compile_btn.configure(text=self.tr("compile"))

        # status
        self.status_text.set(self.tr(self._status_key))

    # ---------- UI ----------
    def _build_ui(self):
        self.minsize(980, 640)
        pad = {"padx": 10, "pady": 8}

        # TOP
        self.top = ttk.Frame(self)
        self.top.pack(fill="x", **pad)

        self.lbl_compiler = ttk.Label(self.top, text="")
        self.lbl_compiler.grid(row=0, column=0, sticky="w")
        self.val_compiler = ttk.Label(self.top, textvariable=self.compiler_path)
        self.val_compiler.grid(row=0, column=1, sticky="w")

        self.btn_recheck = ttk.Button(self.top, text="", command=self.detect_compiler)
        self.btn_recheck.grid(row=0, column=4, sticky="e")
        self.btn_install = ttk.Button(self.top, text="", command=self.install_compiler)
        self.btn_install.grid(row=0, column=5, sticky="e")

        self.lbl_backend = ttk.Label(self.top, text="")
        self.lbl_backend.grid(row=1, column=0, sticky="w")

        self.backend_box = ttk.Combobox(
            self.top,
            textvariable=self.backend_choice,
            state="readonly",
            values=["auto", "csc", "dotnet"],
            width=10
        )
        self.backend_box.grid(row=1, column=1, sticky="w")

        self.lbl_backend_hint = ttk.Label(self.top, text="")
        self.lbl_backend_hint.grid(row=1, column=2, sticky="w")

        self.lbl_language = ttk.Label(self.top, text="")
        self.lbl_language.grid(row=1, column=3, sticky="e")

        self.lang_box = ttk.Combobox(
            self.top,
            textvariable=self.lang_display_var,
            state="readonly",
            values=[name for _, name in LANGS],
            width=14
        )
        self.lang_box.grid(row=1, column=4, sticky="e", padx=(6, 0))
        self.lang_box.bind("<<ComboboxSelected>>", self.on_language_changed)

        self.top.columnconfigure(1, weight=1)
        self.top.columnconfigure(2, weight=1)
        self.top.columnconfigure(3, weight=1)

        # FILES
        self.frame_files = ttk.LabelFrame(self, text="")
        self.frame_files.pack(fill="x", **pad)

        self.lbl_source = ttk.Label(self.frame_files, text="")
        self.lbl_source.grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.entry_source = ttk.Entry(self.frame_files, textvariable=self.source_path)
        self.entry_source.grid(row=0, column=1, sticky="ew", padx=10, pady=6)
        self.btn_choose_source = ttk.Button(self.frame_files, text="", command=self.pick_source)
        self.btn_choose_source.grid(row=0, column=2, padx=10, pady=6)

        self.lbl_output = ttk.Label(self.frame_files, text="")
        self.lbl_output.grid(row=1, column=0, sticky="w", padx=10, pady=6)
        self.entry_output = ttk.Entry(self.frame_files, textvariable=self.output_path)
        self.entry_output.grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        self.btn_choose_output = ttk.Button(self.frame_files, text="", command=self.pick_output)
        self.btn_choose_output.grid(row=1, column=2, padx=10, pady=6)

        self.frame_files.columnconfigure(1, weight=1)

        # OPTIONS
        self.frame_opts = ttk.LabelFrame(self, text="")
        self.frame_opts.pack(fill="x", **pad)

        self.lbl_target = ttk.Label(self.frame_opts, text="")
        self.lbl_target.grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.rb_console = ttk.Radiobutton(self.frame_opts, text="", variable=self.target_type, value="exe")
        self.rb_console.grid(row=0, column=1, sticky="w", padx=10, pady=6)
        self.rb_winexe = ttk.Radiobutton(self.frame_opts, text="", variable=self.target_type, value="winexe")
        self.rb_winexe.grid(row=0, column=2, sticky="w", padx=10, pady=6)

        ttk.Separator(self.frame_opts, orient="horizontal").grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=6)

        self.lbl_dotnet = ttk.Label(self.frame_opts, text="")
        self.lbl_dotnet.grid(row=2, column=0, sticky="w", padx=10, pady=6)
        self.cb_self = ttk.Checkbutton(self.frame_opts, text="", variable=self.dotnet_selfcontained)
        self.cb_self.grid(row=2, column=1, sticky="w", padx=10, pady=6)
        self.cb_single = ttk.Checkbutton(self.frame_opts, text="", variable=self.dotnet_singlefile)
        self.cb_single.grid(row=2, column=2, sticky="w", padx=10, pady=6)

        # ACTIONS + STATUS
        self.btns = ttk.Frame(self)
        self.btns.pack(fill="x", **pad)

        self.compile_btn = ttk.Button(self.btns, text="", command=self.compile_clicked)
        self.compile_btn.pack(side="left")

        self.pb = ttk.Progressbar(self.btns, mode="indeterminate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        self.status_lbl = ttk.Label(self.btns, textvariable=self.status_text)
        self.status_lbl.pack(side="right")

        # LOG
        self.frame_log = ttk.LabelFrame(self, text="")
        self.frame_log.pack(fill="both", expand=True, **pad)

        self.log = tk.Text(self.frame_log, wrap="word", height=18)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        try:
            self.log.configure(font=("Consolas", 10))
        except Exception:
            pass

    # ---------- logging ----------
    def _enqueue_log(self, text: str):
        self.log_q.put(("log", text))

    def log_line(self, s: str):
        self._enqueue_log(s)

    def _drain_log_queue(self):
        try:
            while True:
                kind, s = self.log_q.get_nowait()
                if kind == "log":
                    self.log.insert("end", s + "\n")
                    self.log.see("end")
        except queue.Empty:
            pass
        self.after(80, self._drain_log_queue)

    def _ensure_logs_dir(self) -> Path:
        d = Path(__file__).resolve().parent / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _log_command_output(self, phase: str, out: str, raw_filename: str):
        logs_dir = self._ensure_logs_dir()
        raw_path = logs_dir / raw_filename
        raw_path.write_text(out, encoding="utf-8", errors="replace")

        lines = normalize_newlines(out).split("\n")
        filtered = filter_noisy_progress(lines)

        self.log_line(self.tr("log_saved_raw", phase=phase, path=raw_path))
        for ln in filtered:
            if ln.strip():
                self.log_line(ln)

    # ---------- UX ----------
    def set_busy(self, busy: bool, status_key: str | None = None):
        if status_key is not None:
            self.after(0, lambda: self.set_status(status_key))
        if busy:
            self.after(0, lambda: self.compile_btn.configure(state="disabled"))
            self.after(0, lambda: self.pb.start(12))
        else:
            self.after(0, lambda: self.compile_btn.configure(state="normal"))
            self.after(0, lambda: self.pb.stop())

    # ---------- File picking ----------
    def pick_source(self):
        fp = filedialog.askopenfilename(
            title=self.tr("source"),
            filetypes=[("C# Source", "*.cs"), ("All files", "*.*")]
        )
        if fp:
            self.source_path.set(fp)
            if not self.output_path.get():
                self.output_path.set(str(Path(fp).with_suffix(".exe")))
            # Heuristic: default winexe for WinForms/WPF
            try:
                code = read_text_guess(fp)
                info = analyze_source(code)
                if info["uses_winforms"] or info["uses_wpf"]:
                    self.target_type.set("winexe")
            except Exception:
                pass

    def pick_output(self):
        initial = self.output_path.get() or ""
        initialdir = str(Path(initial).parent) if initial else None
        initialfile = Path(initial).name if initial else "output.exe"
        fp = filedialog.asksaveasfilename(
            title=self.tr("output"),
            defaultextension=".exe",
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=[("Windows Executable", "*.exe")]
        )
        if fp:
            self.output_path.set(fp)

    # ---------- detection ----------
    def detect_compiler(self):
        self.compiler_path.set("(...)")
        self.set_status("status_searching")
        self.log_line(self.tr("log_detect"))

        csc = pick_existing(find_csc_candidates())
        dotnet = detect_dotnet()
        local_dotnet = Path(__file__).resolve().parent / "tools" / "dotnet" / "dotnet.exe"
        if not dotnet and local_dotnet.exists():
            dotnet = str(local_dotnet)

        if csc:
            self.log_line(self.tr("log_found_csc", path=csc))
        if dotnet:
            self.log_line(self.tr("log_found_dotnet", path=dotnet))

        if csc and dotnet:
            self.compiler_path.set(f"csc: {csc} | dotnet: {dotnet}")
            self.set_status("status_ready")
            return
        if csc:
            self.compiler_path.set(csc)
            self.set_status("status_ready")
            return
        if dotnet:
            self.compiler_path.set(dotnet + " (dotnet publish)")
            self.set_status("status_ready")
            return

        self.compiler_path.set(self.tr("status_missing"))
        self.log_line(self.tr("log_neither"))
        self.set_status("status_missing")

    # ---------- install ----------
    def install_compiler(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.worker_thread = threading.Thread(target=self._install_compiler_worker, daemon=True)
        self.worker_thread.start()

    def _install_compiler_worker(self):
        self.set_busy(True, "status_installing")
        self.log_line(self.tr("log_install_started"))

        if not is_windows():
            self.log_line("This tool is for Windows.")
            self.set_busy(False, "status_failed")
            return

        winget = where("winget.exe")
        if winget:
            cmd = [
                winget, "install", "-e", "--id", "Microsoft.DotNet.SDK.8",
                "--accept-package-agreements", "--accept-source-agreements",
                "--silent"
            ]
            rc, out = run_capture(cmd)
            self._log_command_output("winget", out, "winget_install.log")
            if rc == 0:
                self.after(0, self.detect_compiler)
                self.set_busy(False, "status_done")
                return

        # fallback: dotnet-install.ps1
        script_dir = Path(__file__).resolve().parent
        tools_dir = script_dir / "tools" / "dotnet"
        tools_dir.mkdir(parents=True, exist_ok=True)

        ps = where("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        dotnet_install = script_dir / "tools" / "dotnet-install.ps1"

        url = "https://dot.net/v1/dotnet-install.ps1"
        dl_cmd = [
            ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command",
            f"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile '{dotnet_install}'"
        ]
        rc, out = run_capture(dl_cmd)
        self._log_command_output("download", out, "dotnet_install_download.log")
        if rc != 0 or not dotnet_install.exists():
            self.set_busy(False, "status_failed")
            return

        install_cmd = [
            ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(dotnet_install),
            "-Channel", "LTS",
            "-InstallDir", str(tools_dir),
            "-NoPath"
        ]
        rc, out = run_capture(install_cmd)
        self._log_command_output("dotnet-install", out, "dotnet_install.log")
        if rc != 0:
            self.set_busy(False, "status_failed")
            return

        self.after(0, self.detect_compiler)
        self.set_busy(False, "status_done")

    # ---------- compile ----------
    def compile_clicked(self):
        src = self.source_path.get().strip('" ')
        outp = self.output_path.get().strip('" ')
        if not src or not os.path.isfile(src):
            messagebox.showerror(self.tr("err"), self.tr("err_need_source"))
            return
        if not outp:
            messagebox.showerror(self.tr("err"), self.tr("err_need_output"))
            return
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.worker_thread = threading.Thread(target=self._compile_worker, args=(src, outp), daemon=True)
        self.worker_thread.start()

    def _compile_worker(self, src: str, outp: str):
        self.set_busy(True, "status_compiling")
        self.log_line(self.tr("log_compile_started"))
        self.log_line(self.tr("log_source", path=src))
        self.log_line(self.tr("log_output", path=outp))

        code = ""
        info = {"prefer_dotnet": False, "uses_winforms": False, "uses_wpf": False, "has_appconfig_init": False}
        try:
            code = read_text_guess(src)
            info = analyze_source(code)
        except Exception:
            pass

        csc = pick_existing(find_csc_candidates())
        dotnet = detect_dotnet()
        local_dotnet = Path(__file__).resolve().parent / "tools" / "dotnet" / "dotnet.exe"
        if not dotnet and local_dotnet.exists():
            dotnet = str(local_dotnet)

        choice = (self.backend_choice.get() or "auto").strip().lower()
        backend = None

        if choice == "csc":
            backend = "csc"
        elif choice == "dotnet":
            backend = "dotnet"
        else:
            if dotnet and info.get("prefer_dotnet", False):
                backend = "dotnet"
            elif csc:
                backend = "csc"
            elif dotnet:
                backend = "dotnet"
            else:
                backend = None

        if backend is None:
            self._install_compiler_worker()
            csc = pick_existing(find_csc_candidates())
            dotnet = detect_dotnet()
            if not dotnet and local_dotnet.exists():
                dotnet = str(local_dotnet)

            if choice == "dotnet":
                backend = "dotnet" if dotnet else None
            elif choice == "csc":
                backend = "csc" if csc else None
            else:
                if dotnet and info.get("prefer_dotnet", False):
                    backend = "dotnet"
                elif csc:
                    backend = "csc"
                elif dotnet:
                    backend = "dotnet"
                else:
                    backend = None

        ok = False
        if backend == "csc":
            if not csc:
                ok = False
            else:
                ok = self._compile_with_csc(csc, src, outp, code)
        elif backend == "dotnet":
            if not dotnet:
                self._install_compiler_worker()
                dotnet = detect_dotnet()
                if not dotnet and local_dotnet.exists():
                    dotnet = str(local_dotnet)
            if dotnet:
                ok = self._compile_with_dotnet(dotnet, src, outp, info)
        else:
            ok = False

        self.set_busy(False, "status_done" if ok else "status_failed")

    def _compile_with_csc(self, csc: str, src: str, outp: str, code: str) -> bool:
        Path(Path(outp).parent).mkdir(parents=True, exist_ok=True)
        target = self.target_type.get().strip()
        if target not in ("exe", "winexe"):
            target = "exe"

        refs = []
        if "System.Windows.Forms" in code:
            refs.append("System.Windows.Forms.dll")
        if "System.Drawing" in code:
            refs.append("System.Drawing.dll")

        cmd = [csc, "/nologo", f"/target:{target}", f"/out:{outp}"]
        for r in refs:
            cmd.append(f"/r:{r}")
        cmd.append(src)

        rc, out = run_capture(cmd)
        self._log_command_output("csc", out, "csc_compile.log")

        if rc == 0 and os.path.isfile(outp):
            self.log_line(self.tr("log_success_csc"))
            return True
        self.log_line(self.tr("log_fail_csc", code=rc))
        self.log_line(self.tr("log_hint_old_csc"))
        return False

    def _compile_with_dotnet(self, dotnet: str, src: str, outp: str, info: dict) -> bool:
        tmp = Path(tempfile.mkdtemp(prefix="csc_gui_dotnet_"))
        try:
            proj = tmp / "App.csproj"
            program = tmp / "Program.cs"
            shutil.copy2(src, program)
            Path(Path(outp).parent).mkdir(parents=True, exist_ok=True)

            tfm = DEFAULT_TFM
            use_winforms = bool(info.get("uses_winforms", False)) or bool(info.get("has_appconfig_init", False))
            use_wpf = bool(info.get("uses_wpf", False))
            if use_winforms or use_wpf:
                tfm = f"{DEFAULT_TFM}-windows"

            output_type = "WinExe" if self.target_type.get() == "winexe" else "Exe"

            extra_props = ""
            if use_winforms:
                extra_props += "\n    <UseWindowsForms>true</UseWindowsForms>"
            if use_wpf:
                extra_props += "\n    <UseWPF>true</UseWPF>"

            proj.write_text(f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>{output_type}</OutputType>
    <TargetFramework>{tfm}</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>{extra_props}
  </PropertyGroup>
</Project>
""", encoding="utf-8")

            rid = arch_rid()
            sc = self.dotnet_selfcontained.get()
            sf = self.dotnet_singlefile.get()

            publish_dir = tmp / "publish"
            args = [
                dotnet, "publish", str(proj),
                "-c", "Release",
                "-o", str(publish_dir),
                "-r", rid,
                "--self-contained", "true" if sc else "false",
                "-p:DebugType=none",
                "-p:DebugSymbols=false",
            ]
            if sf:
                args += ["-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true"]

            rc, out = run_capture(args, cwd=str(tmp))
            self._log_command_output("dotnet", out, "dotnet_publish.log")
            if rc != 0:
                return False

            produced = None
            for p in publish_dir.glob("*.exe"):
                produced = p
                break
            if not produced or not produced.exists():
                return False

            shutil.copy2(produced, outp)
            self.log_line(self.tr("log_success_dotnet", path=outp))
            return True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

def main():
    if not is_windows():
        print("This tool is for Windows.")
        sys.exit(1)
    app = App()
    app.set_status("status_ready")
    app.mainloop()

if __name__ == "__main__":
    main()
