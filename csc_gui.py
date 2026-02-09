#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# source: github.com/zeittresor
r"""
CSC GUI Builder (Windows 10)

Primary: uses .NET Framework csc.exe (typically under %WINDIR%\Microsoft.NET\Framework(64)\v4.0.30319\csc.exe)
Fallback: uses dotnet SDK (dotnet publish)

Hotfix 2:
- Fixes compiling modern WinForms (.NET 6+) sources like ones using ApplicationConfiguration.Initialize().
  -> dotnet fallback now generates a Windows-targeted project:
     TargetFramework: net8.0-windows
     UseWindowsForms: true
- Adds a Backend selector:
  Auto (smart) / Force csc.exe / Force dotnet SDK
- Auto mode prefers dotnet for "modern" syntax or WinForms/WPF usage.
- csc mode now auto-adds WinForms references when it detects System.Windows.Forms / System.Drawing.
- Keeps Hotfix 1 improvements: progress spam filtering + robust decoding + raw logs saved in ./logs
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

APP_TITLE = "CSC GUI Builder"
DEFAULT_TFM = "net8.0"  # base TFM; WinForms/WPF become net8.0-windows automatically

PROGRESS_SPINNER_RE = re.compile(r"^\s*[-\\|/]\s*$")
PROGRESS_BAR_RE = re.compile(r"(?:\b\d{1,3}\s*%|\b\d+(?:\.\d+)?\s*(?:KB|MB|GB)\s*/\s*\d+(?:\.\d+)?\s*(?:KB|MB|GB))", re.IGNORECASE)

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
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out_b, _ = p.communicate()
        out = _decode_output(out_b or b"")
        return p.returncode, out
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
    candidates = []
    candidates.append(str(Path(windir) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"))
    candidates.append(str(Path(windir) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"))

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
            # keep meaningful lines with URLs / package ids / installer
            if "http" in raw.lower() or "Microsoft.DotNet" in raw or "Paket" in raw or "Installer" in raw:
                cleaned.append(raw)
            continue

        cleaned.append(raw)
    return cleaned

def read_text_guess(path: str) -> str:
    p = Path(path)
    data = p.read_bytes()
    # try utf-8 with BOM, then utf-8, then mbcs
    for enc in ("utf-8-sig", "utf-8", "mbcs"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8", errors="replace")

def analyze_source(code: str) -> dict:
    """Heuristics to decide whether we should prefer dotnet and which WindowsDesktop flags are needed."""
    c = code
    uses_winforms = ("System.Windows.Forms" in c) or ("using System.Windows.Forms" in c) or ("Form" in c and "Application." in c)
    uses_wpf = ("UseWPF" in c) or ("PresentationFramework" in c) or ("System.Windows" in c and "Window" in c)

    # modern template / APIs
    has_appconfig_init = "ApplicationConfiguration.Initialize" in c

    # modern language hints (not exhaustive)
    modern_markers = [
        "using var ",      # C# 8
        "record ",         # C# 9
        "init;",           # C# 9
        "MathF.",          # newer .NET
        "object?",         # nullable
        "string?",         # nullable
        "Span<",           # often newer code
        "async Task Main", # C# 7.1+
    ]
    seems_modern = has_appconfig_init or any(m in c for m in modern_markers)

    prefer_dotnet = seems_modern or uses_winforms or uses_wpf
    return {
        "uses_winforms": uses_winforms,
        "uses_wpf": uses_wpf,
        "prefer_dotnet": prefer_dotnet,
        "has_appconfig_init": has_appconfig_init,
    }

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(940, 610)

        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.source_path = tk.StringVar(value="")
        self.output_path = tk.StringVar(value="")
        self.compiler_path = tk.StringVar(value="(suche ...)")

        # Backend selection
        self.backend_choice = tk.StringVar(value="auto")  # auto|csc|dotnet

        self.target_type = tk.StringVar(value="winexe")  # exe|winexe (WinForms default: winexe)
        self.dotnet_selfcontained = tk.BooleanVar(value=True)
        self.dotnet_singlefile = tk.BooleanVar(value=True)

        self.status_text = tk.StringVar(value="Bereit.")
        self._build_ui()

        self.after(80, self.detect_compiler)
        self.after(80, self._drain_log_queue)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Compiler:").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.compiler_path).grid(row=0, column=1, sticky="w")

        ttk.Button(top, text="Neu prüfen", command=self.detect_compiler).grid(row=0, column=3, sticky="e")
        ttk.Button(top, text="Compiler installieren (Auto)", command=self.install_compiler).grid(row=0, column=4, sticky="e")

        ttk.Label(top, text="Backend:").grid(row=1, column=0, sticky="w")
        backend = ttk.Combobox(
            top,
            textvariable=self.backend_choice,
            state="readonly",
            values=[
                "auto",
                "csc",
                "dotnet"
            ],
            width=10
        )
        backend.grid(row=1, column=1, sticky="w")

        ttk.Label(top, text="(auto=smart, csc=.NET Framework, dotnet=SDK)").grid(row=1, column=2, sticky="w")

        top.columnconfigure(1, weight=1)
        top.columnconfigure(2, weight=1)

        io = ttk.LabelFrame(self, text="Dateien")
        io.pack(fill="x", **pad)

        ttk.Label(io, text="C#-Source (.cs):").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(io, textvariable=self.source_path).grid(row=0, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(io, text="Auswählen…", command=self.pick_source).grid(row=0, column=2, padx=10, pady=6)

        ttk.Label(io, text="Output EXE:").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(io, textvariable=self.output_path).grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(io, text="Speichern als…", command=self.pick_output).grid(row=1, column=2, padx=10, pady=6)

        io.columnconfigure(1, weight=1)

        opts = ttk.LabelFrame(self, text="Optionen")
        opts.pack(fill="x", **pad)

        ttk.Label(opts, text="Zieltyp:").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        ttk.Radiobutton(opts, text="Console EXE", variable=self.target_type, value="exe").grid(row=0, column=1, sticky="w", padx=10, pady=6)
        ttk.Radiobutton(opts, text="Windows GUI EXE (kein Console-Fenster)", variable=self.target_type, value="winexe").grid(row=0, column=2, sticky="w", padx=10, pady=6)

        ttk.Separator(opts, orient="horizontal").grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=6)

        ttk.Label(opts, text="dotnet Fallback:").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        ttk.Checkbutton(opts, text="Self-contained (Standalone, größer)", variable=self.dotnet_selfcontained).grid(row=2, column=1, sticky="w", padx=10, pady=6)
        ttk.Checkbutton(opts, text="Single-file (eine EXE)", variable=self.dotnet_singlefile).grid(row=2, column=2, sticky="w", padx=10, pady=6)

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.compile_btn = ttk.Button(btns, text="Kompilieren", command=self.compile_clicked)
        self.compile_btn.pack(side="left")

        self.pb = ttk.Progressbar(btns, mode="indeterminate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        ttk.Label(btns, textvariable=self.status_text).pack(side="right")

        log_frame = ttk.LabelFrame(self, text="Ausgabe / Log")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log = tk.Text(log_frame, wrap="word", height=18)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

        try:
            self.log.configure(font=("Consolas", 10))
        except Exception:
            pass

    def _enqueue_log(self, kind: str, text: str):
        self.log_q.put((kind, text))

    def log_line(self, s: str):
        self._enqueue_log("log", s)

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

    def set_busy(self, busy: bool, status: str | None = None):
        if status is not None:
            self.after(0, lambda: self.status_text.set(status))
        if busy:
            self.after(0, lambda: self.compile_btn.configure(state="disabled"))
            self.after(0, lambda: self.pb.start(12))
        else:
            self.after(0, lambda: self.compile_btn.configure(state="normal"))
            self.after(0, lambda: self.pb.stop())

    def pick_source(self):
        fp = filedialog.askopenfilename(
            title="C#-Datei auswählen",
            filetypes=[("C# Source", "*.cs"), ("Alle Dateien", "*.*")]
        )
        if fp:
            self.source_path.set(fp)
            if not self.output_path.get():
                self.output_path.set(str(Path(fp).with_suffix(".exe")))

            # Heuristic: if it's WinForms/WPF, default to winexe
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
            title="EXE speichern als",
            defaultextension=".exe",
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=[("Windows Executable", "*.exe")]
        )
        if fp:
            self.output_path.set(fp)

    def detect_compiler(self):
        self.compiler_path.set("(suche ...)")
        self.status_text.set("Suche nach csc.exe / dotnet ...")
        self.log_line("== Compiler-Erkennung ==")

        csc = pick_existing(find_csc_candidates())
        dotnet = detect_dotnet()
        local_dotnet = Path(__file__).resolve().parent / "tools" / "dotnet" / "dotnet.exe"
        if not dotnet and local_dotnet.exists():
            dotnet = str(local_dotnet)

        if csc and dotnet:
            self.compiler_path.set(f"csc: {csc} | dotnet: {dotnet}")
            self.status_text.set("csc + dotnet gefunden.")
            return
        if csc:
            self.compiler_path.set(csc)
            self.status_text.set("csc.exe gefunden.")
            return
        if dotnet:
            self.compiler_path.set(dotnet + " (dotnet publish)")
            self.status_text.set("dotnet gefunden.")
            return

        self.compiler_path.set("Nicht gefunden (csc.exe / dotnet)")
        self.status_text.set("Compiler fehlt – bitte installieren.")

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

        self.log_line(f"[{phase}] Vollständiges Log gespeichert: {raw_path}")
        for ln in filtered:
            if ln.strip():
                self.log_line(ln)

    def install_compiler(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.worker_thread = threading.Thread(target=self._install_compiler_worker, daemon=True)
        self.worker_thread.start()

    def _install_compiler_worker(self):
        self.set_busy(True, "Installiere Compiler (auto) ...")
        self.log_line("== Installation gestartet ==")

        if not is_windows():
            self.log_line("Dieses Tool ist für Windows gedacht.")
            self.set_busy(False, "Nicht unterstützt.")
            return

        winget = where("winget.exe")
        if winget:
            self.log_line(f"winget gefunden: {winget}")
            cmd = [
                winget, "install", "-e", "--id", "Microsoft.DotNet.SDK.8",
                "--accept-package-agreements", "--accept-source-agreements",
                "--silent"
            ]
            self.log_line("Versuche Installation via winget: Microsoft.DotNet.SDK.8")
            rc, out = run_capture(cmd)
            self._log_command_output("winget", out, "winget_install.log")
            if rc == 0:
                self.log_line("winget: Installation fertig.")
                self.after(0, self.detect_compiler)
                self.set_busy(False, "Installation beendet.")
                return
            else:
                self.log_line(f"winget: Installation fehlgeschlagen (code {rc}). Fallback folgt.")

        script_dir = Path(__file__).resolve().parent
        tools_dir = script_dir / "tools" / "dotnet"
        tools_dir.mkdir(parents=True, exist_ok=True)

        ps = where("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        dotnet_install = script_dir / "tools" / "dotnet-install.ps1"

        self.log_line("Lade dotnet-install.ps1 (offiziell von dot.net) ...")
        url = "https://dot.net/v1/dotnet-install.ps1"
        dl_cmd = [
            ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command",
            f"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile '{dotnet_install}'"
        ]
        rc, out = run_capture(dl_cmd)
        self._log_command_output("download", out, "dotnet_install_download.log")
        if rc != 0 or not dotnet_install.exists():
            self.log_line("Download fehlgeschlagen. Prüfe Internet/Proxy/Policy.")
            self.set_busy(False, "Installation fehlgeschlagen.")
            return

        self.log_line("Installiere .NET SDK (LTS) in ./tools/dotnet ...")
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
            self.log_line(f"dotnet-install: fehlgeschlagen (code {rc}).")
            self.set_busy(False, "Installation fehlgeschlagen.")
            return

        local_dotnet = tools_dir / "dotnet.exe"
        if local_dotnet.exists():
            self.log_line(f"Lokales dotnet installiert: {local_dotnet}")
            self.after(0, self.detect_compiler)
            self.set_busy(False, "Installation beendet.")
            return

        self.log_line("Installation abgeschlossen, aber dotnet.exe nicht gefunden.")
        self.set_busy(False, "Installation unklar.")

    def compile_clicked(self):
        src = self.source_path.get().strip('" ')
        outp = self.output_path.get().strip('" ')
        if not src or not os.path.isfile(src):
            messagebox.showerror("Fehler", "Bitte eine gültige C#-Source-Datei auswählen (.cs).")
            return
        if not outp:
            messagebox.showerror("Fehler", "Bitte einen Output-Pfad für die EXE auswählen.")
            return

        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.worker_thread = threading.Thread(target=self._compile_worker, args=(src, outp), daemon=True)
        self.worker_thread.start()

    def _compile_worker(self, src: str, outp: str):
        self.set_busy(True, "Kompiliere ...")
        self.log_line("== Kompilierung gestartet ==")
        self.log_line(f"Source: {src}")
        self.log_line(f"Output: {outp}")

        code = ""
        info = {"prefer_dotnet": False, "uses_winforms": False, "uses_wpf": False, "has_appconfig_init": False}
        try:
            code = read_text_guess(src)
            info = analyze_source(code)
            self.log_line(f"Analyse: prefer_dotnet={info['prefer_dotnet']} winforms={info['uses_winforms']} wpf={info['uses_wpf']} appcfgInit={info['has_appconfig_init']}")
        except Exception as e:
            self.log_line(f"Analyse nicht möglich: {type(e).__name__}: {e}")

        csc = pick_existing(find_csc_candidates())
        dotnet = detect_dotnet()
        local_dotnet = Path(__file__).resolve().parent / "tools" / "dotnet" / "dotnet.exe"
        if not dotnet and local_dotnet.exists():
            dotnet = str(local_dotnet)

        choice = self.backend_choice.get().strip().lower()  # auto|csc|dotnet

        def need_install_dotnet() -> bool:
            return not dotnet

        # Decide backend
        backend = None
        if choice == "csc":
            backend = "csc"
        elif choice == "dotnet":
            backend = "dotnet"
        else:
            # auto
            if dotnet and info.get("prefer_dotnet", False):
                backend = "dotnet"
            elif csc:
                backend = "csc"
            elif dotnet:
                backend = "dotnet"
            else:
                backend = None

        if backend is None:
            self.log_line("Kein Compiler verfügbar. Starte Auto-Installation ...")
            self._install_compiler_worker()
            csc = pick_existing(find_csc_candidates())
            dotnet = detect_dotnet()
            if not dotnet and local_dotnet.exists():
                dotnet = str(local_dotnet)
            # re-decide
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

        if backend == "csc":
            if not csc:
                self.log_line("❌ Backend=csc gewählt, aber csc.exe nicht gefunden.")
                self.set_busy(False, "Fehlgeschlagen.")
                return
            self.log_line(f"Backend: csc.exe -> {csc}")
            ok = self._compile_with_csc(csc, src, outp, code)
            self.set_busy(False, "Fertig." if ok else "Fehlgeschlagen.")
            return

        if backend == "dotnet":
            if not dotnet:
                self.log_line("dotnet fehlt. Starte Auto-Installation ...")
                self._install_compiler_worker()
                dotnet = detect_dotnet()
                if not dotnet and local_dotnet.exists():
                    dotnet = str(local_dotnet)
            if not dotnet:
                self.log_line("❌ Backend=dotnet gewählt, aber dotnet.exe nicht verfügbar.")
                self.set_busy(False, "Fehlgeschlagen.")
                return

            self.log_line(f"Backend: dotnet -> {dotnet}")
            ok = self._compile_with_dotnet_publish(dotnet, src, outp, code, info)
            self.set_busy(False, "Fertig." if ok else "Fehlgeschlagen.")
            return

        self.log_line("❌ Kein Backend verfügbar (Installation/Erkennung fehlgeschlagen).")
        self.set_busy(False, "Fehlgeschlagen.")

    def _compile_with_csc(self, csc: str, src: str, outp: str, code: str) -> bool:
        out_dir = str(Path(outp).parent)
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        target = self.target_type.get().strip()
        if target not in ("exe", "winexe"):
            target = "exe"

        refs = []
        if "System.Windows.Forms" in code:
            refs += ["System.Windows.Forms.dll"]
        if "System.Drawing" in code:
            refs += ["System.Drawing.dll"]

        cmd = [csc, "/nologo", f"/target:{target}", f"/out:{outp}"]
        for r in refs:
            cmd.append(f"/r:{r}")
        cmd.append(src)

        self.log_line("Command: " + " ".join(f'"{x}"' if " " in x else x for x in cmd))
        rc, out = run_capture(cmd)
        self._log_command_output("csc", out, "csc_compile.log")

        if rc == 0 and os.path.isfile(outp):
            self.log_line("✅ Kompilierung erfolgreich (csc).")
            return True
        self.log_line(f"❌ Kompilierung fehlgeschlagen (csc), code {rc}.")
        self.log_line("Hinweis: Der .NET Framework csc.exe ist oft zu alt für .NET 6+ / moderne C# Syntax. Dann Backend=dotnet wählen.")
        return False

    def _compile_with_dotnet_publish(self, dotnet: str, src: str, outp: str, code: str, info: dict) -> bool:
        tmp = Path(tempfile.mkdtemp(prefix="csc_gui_dotnet_"))
        try:
            proj = tmp / "App.csproj"
            program = tmp / "Program.cs"
            shutil.copy2(src, program)

            out_dir = str(Path(outp).parent)
            Path(out_dir).mkdir(parents=True, exist_ok=True)

            # Determine framework / windows desktop
            tfm = DEFAULT_TFM
            use_winforms = bool(info.get("uses_winforms", False))
            use_wpf = bool(info.get("uses_wpf", False))

            if use_winforms or use_wpf:
                tfm = f"{DEFAULT_TFM}-windows"

            output_type = "WinExe" if self.target_type.get() == "winexe" else "Exe"

            # Build csproj
            extra_props = ""
            if use_winforms:
                extra_props += "\n    <UseWindowsForms>true</UseWindowsForms>"
            if use_wpf:
                extra_props += "\n    <UseWPF>true</UseWPF>"

            # If the code explicitly uses ApplicationConfiguration.Initialize(), that's WinForms template-ish; ensure WinForms.
            if info.get("has_appconfig_init", False):
                extra_props += "\n    <UseWindowsForms>true</UseWindowsForms>"
                if "-windows" not in tfm:
                    tfm = f"{DEFAULT_TFM}-windows"

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
            ]
            args += ["--self-contained", "true" if sc else "false"]
            if sf:
                args += ["-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true"]

            args += ["-p:DebugType=none", "-p:DebugSymbols=false"]

            self.log_line(f"dotnet TargetFramework: {tfm} (winforms={use_winforms} wpf={use_wpf})")
            self.log_line("dotnet publish command: " + " ".join(f'"{x}"' if " " in x else x for x in args))

            rc, out = run_capture(args, cwd=str(tmp))
            self._log_command_output("dotnet", out, "dotnet_publish.log")

            if rc != 0:
                self.log_line(f"❌ dotnet publish fehlgeschlagen (code {rc}).")
                return False

            produced = None
            for p in publish_dir.glob("*.exe"):
                produced = p
                break
            if not produced or not produced.exists():
                self.log_line("❌ Publish fertig, aber keine .exe im publish-Ordner gefunden.")
                return False

            shutil.copy2(produced, outp)
            self.log_line(f"✅ Kompilierung erfolgreich (dotnet). EXE kopiert nach: {outp}")
            return True
        finally:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

def main():
    if not is_windows():
        print("Dieses Tool ist für Windows gedacht.")
        sys.exit(1)
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
