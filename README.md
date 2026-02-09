# CSC GUI Builder (Windows 10)

Kleines **Tkinter-GUI** (nur Python-Stdlib), das eine einzelne **C#-Datei (`.cs`)** zu einer **Windows-EXE (`.exe`)** kompiliert.

Es versucht zuerst den **klassischen .NET Framework `csc.exe`** zu nutzen. Wenn das nicht passt (z. B. moderne .NET 6+/WinForms Codes), kann es automatisch auf **.NET SDK (`dotnet publish`)** wechseln – inkl. optionaler Auto-Installation.

<img width="1208" height="711" alt="compile-c#" src="https://github.com/user-attachments/assets/11741e7a-5e1c-4de1-9939-8475f1abe23a" />

![testcode](https://github.com/user-attachments/assets/d663a76c-bed5-4907-94fa-47bb47e2fb19)

---

## Features

- ✅ **Source auswählen** (`.cs`) + **Output-EXE** speichern
- ✅ **Backend-Auswahl**:
  - `auto` (smart)
  - `csc` (klassischer .NET Framework Compiler)
  - `dotnet` (.NET SDK / modern)
- ✅ **Auto-Mode** erkennt WinForms/WPF und moderne Syntax und bevorzugt dann **dotnet**
- ✅ **WinForms/.NET 6+ Support** (z. B. `ApplicationConfiguration.Initialize()`), da das Tool im dotnet-Modus ein Windows-Targeting-Projekt erzeugt
- ✅ Fortschrittsbalken (GUI) + **lesbares Log**
- ✅ Vollständige Raw-Logs unter `./logs/*.log` (für Debugging)

---

## Voraussetzungen

- **Windows 10**
- **Python 3.x** (für das GUI)
- Optional/je nach Backend:
  - `csc.exe` aus .NET Framework (oft bereits vorhanden)
  - **.NET SDK** (`dotnet`) für moderne Projekte / WinForms / WPF

---

## Installation

Clone oder ZIP-Download vom Repo, dann:

```bat
python csc_gui.py
