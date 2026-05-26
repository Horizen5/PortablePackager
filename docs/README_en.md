<h1 align="center">
  <img src="../PortablePackager.png" alt="PortablePackager" width="96" />
</h1>

<h3 align="center">Universal EXE Portable Packager</h3>

<p align="center">
  Languages:
  <a href="../README.md">简体中文</a> ·
  <a href="./README_en.md">English</a>
</p>

---

**Version: 1.2.0.0**

Package any EXE program and its associated folders into a single portable EXE. Double-click to run — no installation required.

## Features

- **One-Click Packaging**: Drag and drop a software folder onto `PortablePackager.exe` to generate a portable version
- **Auto Detection**: Automatically identifies the main program, extracts icons and version information
- **UAC Elevation**: Auto-generates VBS elevation scripts to support programs requiring admin privileges
- **Auto Cleanup**: Extracts to a temp directory and auto-deletes when the program closes (WMI process monitoring)
- **Fast Compression**: Uses `-mx=1` fast compression by default for the best speed-to-size balance
- **Fully Standalone**: Bundles 7z.exe and 7z.sfx internally — no external 7-Zip installation needed

## Usage

1. Download `PortablePackager.exe`
2. **Drag and drop** any software folder onto `PortablePackager.exe`
3. Wait for packaging to complete; the portable EXE is generated in the parent directory

### Example

```
Source folder structure:
  D:\Software\DDU v18.1.5.3\
  ├── Display Driver Uninstaller.exe
  ├── settings\
  └── ...

Action: Drag the "DDU v18.1.5.3" folder onto PortablePackager.exe

Output:
  D:\Software\DDU_v18_1_5_3_Portable.exe ← Double-click to run
```

## How It Works

### Packaging Flow

```
┌─────────────────────────────────────────────────┐
│              PortablePackager.exe                │
│                                                  │
│ 1. Scan target folder, detect main EXE           │
│ 2. Extract icon and version info from main EXE   │
│ 3. Generate VBS elevation script (UAC support)   │
│ 4. Compress all files with 7z (-mx=1 fast)      │
│ 5. Assemble: SFX module + config + 7z archive    │
│ 6. Replace icon, embed version info              │
│                                                  │
│ Output: A single runnable _Portable.exe          │
└─────────────────────────────────────────────────┘
```

### Portable EXE Runtime Flow

```
Double-click _Portable.exe
 → SFX silently extracts to %TEMP%\AppName\
 → Runs VBS elevation script
 → UAC prompt appears
 → Main program launches with admin privileges
 → VBS monitors process exit via WMI
 → SFX auto-cleans temp directory after program closes
```

## Technical Details

### Core Components

| Component | Description |
|---|---|
| SFX Module | 7-Zip self-extracting module (266KB), handles extraction and launch |
| 7z.exe | Bundled 7-Zip CLI tool for creating archives |
| VBS Elevation | Implements UAC elevation via `ShellExecute "runas"` |
| WMI Monitoring | Waits for target process exit via `Win32_Process` queries |
| Icon Extraction | Parses PE resource directory, extracts RT_GROUP_ICON |
| Icon Replacement | Writes via Windows `UpdateResource` API |
| Version Info | Extracts VS_VERSION_INFO from source and embeds it |

### SFX Self-Extraction Principle

SFX (Self-Extracting Archive) is a self-extracting module provided by 7-Zip. The final output is composed of three concatenated parts:

```
┌─────────────┬─────────────┬─────────────┐
│  SFX Module │  SFX Config │ 7z Archive  │
│  (7z.sfx)   │  (config)   │ (archive)   │
└─────────────┴─────────────┴─────────────┘
```

**Key Configuration Parameters:**

| Parameter | Description |
|---|---|
| `GUIMode="2"` | Fully hides extraction UI for silent extraction (only supported by 266KB version) |
| `MiscFlags="1+2+4"` | 1=overwrite existing files, 2=hide extraction window, 4=auto-cleanup temp dir after program closes |
| `InstallPath` | Extraction target path, uses `%TEMP%` for temp folder location |
| `RunProgram` | Program to execute after extraction, runs VBS elevation script via wscript.exe |

### VBS UAC Elevation & Process Waiting Mechanism

Many programs (e.g. system tools, driver tools) have `requireAdministrator` in their EXE manifest and must run with admin privileges.

**Elevation Approach:**

1. SFX runs the VBS script after extraction (no admin privileges needed)
2. VBS launches the target EXE via `Shell.Application.ShellExecute` in `"runas"` mode
3. Windows shows the UAC elevation dialog; user confirms to run with admin privileges

**Process Waiting (Critical Optimization):**

- `ShellExecute` is asynchronous — the VBS script exits immediately
- If VBS exits, SFX assumes the program has closed and attempts to clean up the temp directory
- At this point the target EXE is still running; files are locked and cannot be deleted, leaving residual junk files
- **Solution**: After launching the target EXE, VBS polls for process exit via WMI:

```vbscript
' Launch target program with admin privileges
shell.ShellExecute exePath, "", parentFolder, "runas", 1
' Monitor process exit via WMI
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Do
    WScript.Sleep 500
    Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='" & exeName & "'")
Loop While procs.Count > 0
```

This ensures SFX's cleanup mechanism (`MiscFlags="1+2+4"`) works correctly.

### PE File Icon Extraction Principle

**Standard PE File Flow:**

1. Read PE header offset (4-byte DWORD at byte 0x3C)
2. Locate resource directory entry in Optional Header (Data Directory item 3, offset 96+16)
3. Get resource directory RVA, convert to file offset via section table
4. Parse resource directory tree, find RT_GROUP_ICON (14) and RT_ICON (3)
5. Build standard ICO file format: ICONDIR (6 bytes) + ICONDIRENTRY (16 bytes/N) + icon data

**Non-Standard PE Files (Resource RVA is 0):**

- Added `extract_icon_from_rsrc_section()` as an alternative strategy
- Directly finds the .rsrc section via section table names
- Parses resource directory starting from the section's file offset
- RVA-to-file-offset conversion formula: `foff = rsrc_ro + (rva - rsrc_va)`

### Compression Levels

Uses `-mx=1` (fastest compression) by default for the best speed-to-size balance:

| Level | Mode | Speed | Size |
|---|---|---|---|
| 0 | Store only | Fastest | Largest |
| **1** | **Fastest compression (default)** | **Fast** | **Smaller** |
| 3 | Fast compression | Faster | Even smaller |
| 5 | Normal compression | Medium | Small |
| 9 | Maximum compression | Slowest | Smallest |

## Version History

### V1.2.0.0 (2026-05-24)

**Key Updates:**

- Brand new icon design (blue package box theme)
- Full version info embedding (visible in file properties)
- 7 bug fixes + 3 code optimizations
- Enhanced PE file compatibility

#### Bug Fixes (7 total)

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | `extract_icon()` crash | No boundary checks in PE resource directory parsing | Added comprehensive boundary checks and try-except |
| 2 | Non-standard PE icon extraction failure | PE header resource RVA is 0 but .rsrc section exists | Added `extract_icon_from_rsrc_section()` |
| 3 | SFX module path reference error | `SCRIPT_DIR` overwritten in main() | Use `__file__` to locate script directory |
| 4 | VBS encoding breaks Chinese paths | Saved as UTF-8 but WSH reads in GBK | Changed VBS save encoding to GBK |
| 5 | VBS breaks temp directory cleanup | `ShellExecute` is async, VBS exits immediately | Added WMI process monitoring to wait for exit |
| 6 | `SCRIPT_DIR` global variable pollution | main() overwrites global variable | Introduced `TARGET_DIR` variable for decoupling |
| 7 | `pefile` install failure with no prompt | Crashes directly after `pip install` fails | Enhanced error handling with prompt on failure |

#### Code Optimizations (3 total)

| # | Optimization | Description |
|---|---|---|
| 1 | Compression level optimization | Changed from `-mx=9` (maximum) to `-mx=1` (fastest), significantly faster |
| 2 | `SCRIPT_DIR` / `TARGET_DIR` decoupling | `SCRIPT_DIR` for script resources only, `TARGET_DIR` for target packaging directory |
| 3 | `pefile` error handling enhancement | Shows error details on install failure, verifies import after installation |

#### Icon Update

- Brand new blue package box theme icon
- Supports 6 sizes: 16x16, 32x32, 48x48, 64x64, 128x128, 256x256
- Embedded at build time using PyInstaller `--icon` parameter

#### Version Info

- File Version: 1.2.0.0
- Product Version: 1.2.0.0
- Company Name: PortablePackager Team
- File Description: Universal EXE Portable Packager
- Copyright: Copyright (C) 2026

## Building from Source

### Prerequisites

| Dependency | Description |
|---|---|
| Python 3.x | Script runtime environment |
| PyInstaller | `pip install pyinstaller`, for packaging into a single EXE |
| pefile | `pip install pefile`, for PE file parsing |
| 7z.sfx | SFX self-extracting module (266KB version, supports GUIMode="2") |
| 7z.exe + 7z.dll | 7-Zip CLI tools for creating archives |

### Build Steps

**Step 1: Prepare Files** — Ensure the following files are in the same directory:

- `build_portable_gui.py` (core script)
- `7z.sfx` (SFX self-extracting module)
- `7z.exe` (7-Zip CLI tool)
- `7z.dll` (7-Zip dynamic link library)
- `PortablePackager.ico` (application icon)
- `version_info.txt` (version info)

**Step 2: Install Dependencies**

```bash
pip install pyinstaller pefile
```

**Step 3: Build**

```bash
python -m PyInstaller ^
  --onefile ^
  --console ^
  --name PortablePackager ^
  --add-data "7z.sfx;." ^
  --add-data "7z.exe;." ^
  --add-data "7z.dll;." ^
  --icon "PortablePackager.ico" ^
  --version-file "version_info.txt" ^
  "build_portable_gui.py" ^
  --noconfirm ^
  --distpath "." ^
  --workpath "_build" ^
  --specpath "_build"
```

**Build Parameters:**

| Parameter | Description |
|---|---|
| `--onefile` | Package into a single EXE file |
| `--console` | Keep console window for viewing packaging logs |
| `--add-data` | Bundle 7z.sfx, 7z.exe, 7z.dll into the EXE |
| `--icon` | Embed application icon (ICO format) |
| `--version-file` | Embed version info (PyInstaller-specific format) |
| `--noconfirm` | Overwrite existing output files without asking |
| `--distpath` | Output directory |
| `--workpath` | Temporary build directory (can be deleted after build) |
| `--specpath` | .spec file output directory |

**Notes:**

- All paths must use absolute paths to avoid cross-drive issues
- `--add-data` separator is semicolon `;` on Windows, colon `:` on Linux/macOS
- **Do NOT use `BeginUpdateResource` API to modify the EXE after building** — it will corrupt PyInstaller's embedded data
- Icon and version info should be embedded at build time via PyInstaller's `--icon` and `--version-file` parameters
- The `_build` directory can be safely deleted after building

## File Structure

```
PortablePackager/
├── PortablePackager.exe          # Packager tool V1.2 (drag & drop to use)
├── build_portable_gui.py         # Core script source code
├── 7z.sfx                        # SFX self-extracting module (266KB)
├── 7z.exe                        # 7-Zip CLI tool
├── 7z.dll                        # 7-Zip dynamic link library
├── PortablePackager.png          # App icon (PNG source)
├── PortablePackager.ico          # App icon (ICO format)
├── version_info.txt              # Version info (PyInstaller format)
├── README.md                     # Documentation (Chinese)
├── docs/
│   └── README_en.md              # Documentation (English)
└── PortablePackager_Technical_Report.docx  # Full technical analysis report
```

## License

MIT License

## Update History

- **V1.2.0.0** — May 25, 2026: New icon, version info embedding, 7 bug fixes, 3 code optimizations
- **V1.0** — Initial release
