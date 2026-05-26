# PortablePackager - 通用型 EXE 便携版打包工具
# PortablePackager - Universal EXE Portable Packager

**版本 / Version：1.2.0.0**

[中文](#中文) | [English](#english)

---

## 中文

将任意 EXE 程序及其关联文件夹封装为一个便携版 EXE，双击即可运行，无需安装。

### 功能特性

- **一键打包**：将软件文件夹拖拽到 `PortablePackager.exe` 上即可生成便携版
- **自动检测**：自动识别主程序、提取图标和版本信息
- **UAC 提权**：自动生成 VBS 提权脚本，支持需要管理员权限的程序
- **自动清理**：解压到临时目录，程序关闭后自动删除（WMI 进程监听）
- **快速压缩**：默认使用 `-mx=1` 最快压缩，速度和体积平衡最佳
- **完全独立**：内置 7z.exe 和 7z.sfx，不依赖外部 7-Zip 安装

### 使用方法

1. 下载 `PortablePackager.exe`
2. 将任意软件文件夹**拖拽**到 `PortablePackager.exe` 上
3. 等待打包完成，便携版 EXE 自动生成在软件文件夹的上一级目录

#### 示例

```
源文件夹结构：
  D:\Software\DDU v18.1.5.3\
  ├── Display Driver Uninstaller.exe
  ├── settings\
  └── ...

操作：将 "DDU v18.1.5.3" 文件夹拖到 PortablePackager.exe 上

输出：
  D:\Software\DDU_v18_1_5_3_Portable.exe ← 双击即可运行
```

### 工作原理

#### 打包流程

```
┌─────────────────────────────────────────────────┐
│              PortablePackager.exe                │
│                                                  │
│ 1. 扫描目标文件夹，检测主程序 EXE                 │
│ 2. 提取主程序的图标和版本信息                      │
│ 3. 生成 VBS 提权脚本（支持 UAC）                  │
│ 4. 用 7z 压缩所有文件（-mx=1 最快压缩）           │
│ 5. 组装：SFX 模块 + 配置 + 7z 压缩包              │
│ 6. 替换图标、嵌入版本信息                          │
│                                                  │
│ 输出：单个可运行的 _Portable.exe                  │
└─────────────────────────────────────────────────┘
```

#### 运行便携版时的流程

```
双击 _Portable.exe
 → SFX 静默解压到 %TEMP%\软件名\
 → 运行 VBS 提权脚本
 → UAC 弹窗确认
 → 以管理员权限启动主程序
 → VBS 通过 WMI 监听进程退出
 → 主程序关闭后 SFX 自动清理临时目录
```

### 技术细节

#### 核心组件

| 组件 | 说明 |
|---|---|
| SFX 模块 | 7-Zip 自解压模块（266KB），负责解压和启动 |
| 7z.exe | 内嵌的 7-Zip 命令行工具，用于创建压缩包 |
| VBS 提权 | 通过 `ShellExecute "runas"` 实现 UAC 提权 |
| WMI 监听 | 通过 `Win32_Process` 查询等待目标进程退出 |
| 图标提取 | 解析 PE 资源目录，提取 RT_GROUP_ICON |
| 图标替换 | 通过 Windows `UpdateResource` API 写入 |
| 版本信息 | 从源程序提取 VS_VERSION_INFO 并嵌入 |

#### SFX 自解压原理

SFX（Self-Extracting Archive）是 7-Zip 提供的自解压模块。最终输出由三部分串联而成：

```
┌─────────────┬─────────────┬─────────────┐
│  SFX 模块   │  SFX 配置   │ 7z 压缩包   │
│  (7z.sfx)   │  (config)   │ (archive)   │
└─────────────┴─────────────┴─────────────┘
```

**关键配置参数：**

| 参数 | 说明 |
|---|---|
| `GUIMode="2"` | 完全隐藏解压界面，实现静默解压（仅 266KB 版本支持） |
| `MiscFlags="1+2+4"` | 1=覆盖已有文件, 2=不显示解压窗口, 4=程序关闭后自动清理临时目录 |
| `InstallPath` | 解压目标路径，使用 `%TEMP%` 确保临时文件夹位置 |
| `RunProgram` | 解压后执行的程序，通过 wscript.exe 运行 VBS 提权脚本 |

#### VBS UAC 提权与进程等待机制

许多程序（如系统工具、驱动类工具）的 EXE manifest 中标记了 requireAdministrator，必须以管理员权限运行。

**提权方案：**

1. SFX 解压后先运行 VBS 脚本（不需要管理员权限）
2. VBS 通过 `Shell.Application.ShellExecute` 以 `"runas"` 模式启动目标 EXE
3. Windows 弹出 UAC 提权对话框，用户确认后以管理员权限运行

**进程等待（关键优化）：**

- `ShellExecute` 是异步调用，VBS 脚本会立即退出
- 如果 VBS 退出，SFX 会误以为程序已关闭，尝试清理临时目录
- 此时目标 EXE 仍在运行，文件被占用无法删除，导致垃圾文件残留
- **解决方案**：VBS 启动目标 EXE 后，通过 WMI 轮询监听进程退出：

```vbscript
' 以管理员权限启动目标程序
shell.ShellExecute exePath, "", parentFolder, "runas", 1
' 通过 WMI 监听进程退出
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Do
    WScript.Sleep 500
    Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='" & exeName & "'")
Loop While procs.Count > 0
```

这样 SFX 的清理机制（`MiscFlags="1+2+4"`）才能正常工作。

#### PE 文件图标提取原理

**标准 PE 文件流程：**

1. 读取 PE 头偏移量（字节 0x3C 处的 4 字节 DWORD）
2. 定位 Optional Header 中的资源目录条目（Data Directory 第 3 项，偏移 96+16）
3. 获取资源目录 RVA，通过节表转换为文件偏移
4. 解析资源目录树，查找 RT_GROUP_ICON (14) 和 RT_ICON (3)
5. 构建标准 ICO 文件格式：ICONDIR(6字节) + ICONDIRENTRY(16字节/N) + 图标数据

**非标准 PE 文件（资源 RVA 为 0）：**

- 新增 `extract_icon_from_rsrc_section()` 采用替代策略
- 直接通过节表名称查找 .rsrc 节
- 从该节的文件偏移处开始解析资源目录
- RVA 到文件偏移的转换公式：`foff = rsrc_ro + (rva - rsrc_va)`

#### 压缩级别

默认使用 `-mx=1`（最快压缩），在速度和体积之间取得最佳平衡：

| 级别 | 模式 | 速度 | 体积 |
|---|---|---|---|
| 0 | 仅存储 | 最快 | 最大 |
| **1** | **最快压缩（默认）** | **快** | **较小** |
| 3 | 快速压缩 | 较快 | 更小 |
| 5 | 标准压缩 | 中等 | 小 |
| 9 | 极限压缩 | 最慢 | 最小 |

### 版本历史

#### V1.2.0.0 (2026-05-24)

**主要更新：**

- 全新图标设计（蓝色包装盒主题）
- 完整的版本信息嵌入（文件属性可查看）
- 7 个 Bug 修复 + 3 项代码优化
- 增强的 PE 文件兼容性

##### Bug 修复（共 7 项）

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | `extract_icon()` 崩溃 | PE 资源目录解析无边界检查 | 添加全面的边界检查和 try-except |
| 2 | 非标准 PE 图标提取失败 | PE 头资源 RVA 为 0 但 .rsrc 节存在 | 新增 `extract_icon_from_rsrc_section()` |
| 3 | SFX 模块路径引用错误 | `SCRIPT_DIR` 在 main() 中被覆盖 | 使用 `__file__` 定位脚本目录 |
| 4 | VBS 编码导致中文路径失败 | UTF-8 保存但 WSH 用 GBK 读取 | VBS 保存编码改为 GBK |
| 5 | VBS 导致临时目录清理失效 | `ShellExecute` 异步调用，VBS 立即退出 | 添加 WMI 进程监听等待退出 |
| 6 | `SCRIPT_DIR` 全局变量污染 | main() 中覆盖全局变量 | 引入 `TARGET_DIR` 变量解耦 |
| 7 | `pefile` 安装失败无提示 | `pip install` 失败后直接崩溃 | 增强错误处理，失败时提示并退出 |

##### 代码优化（共 3 项）

| # | 优化内容 | 说明 |
|---|---|---|
| 1 | 压缩级别优化 | 从 `-mx=9`（极限压缩）改为 `-mx=1`（最快压缩），速度大幅提升 |
| 2 | `SCRIPT_DIR` / `TARGET_DIR` 解耦 | `SCRIPT_DIR` 仅用于查找脚本资源，`TARGET_DIR` 用于目标打包目录 |
| 3 | `pefile` 错误处理增强 | 安装失败时显示错误详情，安装后验证导入 |

##### 图标更新

- 全新设计的蓝色包装盒主题图标
- 支持 6 种尺寸：16x16、32x32、48x48、64x64、128x128、256x256
- 使用 PyInstaller `--icon` 参数在构建时嵌入

##### 版本信息

- 文件版本：1.2.0.0
- 产品版本：1.2.0.0
- 公司名称：PortablePackager Team
- 文件描述：通用型 EXE 便携版打包工具
- 版权信息：Copyright (C) 2026

### 从源码构建

#### 环境要求

| 依赖项 | 说明 |
|---|---|
| Python 3.x | 脚本运行环境 |
| PyInstaller | `pip install pyinstaller`，用于打包为单文件 EXE |
| pefile | `pip install pefile`，用于 PE 文件解析 |
| 7z.sfx | SFX 自解压模块（266KB 版本，支持 GUIMode="2"） |
| 7z.exe + 7z.dll | 7-Zip 命令行工具，用于创建压缩包 |

#### 构建步骤

**步骤 1：准备文件** — 确保以下文件在同一目录下：

- `build_portable_gui.py`（核心脚本）
- `7z.sfx`（SFX 自解压模块）
- `7z.exe`（7-Zip 命令行工具）
- `7z.dll`（7-Zip 动态链接库）
- `PortablePackager.ico`（应用图标）
- `version_info.txt`（版本信息）

**步骤 2：安装依赖**

```bash
pip install pyinstaller pefile
```

**步骤 3：执行构建**

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

**构建参数说明：**

| 参数 | 说明 |
|---|---|
| `--onefile` | 打包为单个 EXE 文件 |
| `--console` | 保留控制台窗口，便于查看打包日志 |
| `--add-data` | 将 7z.sfx、7z.exe、7z.dll 嵌入到 EXE 中 |
| `--icon` | 嵌入应用图标（ICO 格式） |
| `--version-file` | 嵌入版本信息（PyInstaller 专用格式） |
| `--noconfirm` | 覆盖已有的输出文件时不询问 |
| `--distpath` | 输出目录 |
| `--workpath` | 临时构建目录（构建完成后可删除） |
| `--specpath` | .spec 文件输出目录 |

**注意事项：**

- 所有路径必须使用绝对路径，避免跨盘符问题
- `--add-data` 的分隔符在 Windows 上是分号 `;`，Linux/macOS 是冒号 `:`
- **不要在构建后使用 `BeginUpdateResource` API 修改 EXE**，会破坏 PyInstaller 的嵌入数据
- 图标和版本信息应通过 PyInstaller 的 `--icon` 和 `--version-file` 参数在构建时嵌入
- 构建完成后，`_build` 目录可安全删除

### 文件结构

```
PortablePackager/
├── PortablePackager.exe          # 打包工具 V1.2（拖拽使用）
├── build_portable_gui.py         # 核心脚本源码
├── 7z.sfx                        # SFX 自解压模块（266KB）
├── 7z.exe                        # 7-Zip 命令行工具
├── 7z.dll                        # 7-Zip 动态链接库
├── PortablePackager.png          # 软件图标（PNG 源文件）
├── PortablePackager.ico          # 软件图标（ICO 格式）
├── version_info.txt              # 版本信息（PyInstaller 格式）
├── README.md                     # 说明文档
└── PortablePackager_技术分析报告.docx  # 完整技术分析报告
```

### 许可证

MIT License

### 更新日期

- **V1.2.0.0** — 2026年5月25日：全新图标、版本信息嵌入、7个Bug修复、3项代码优化
- **V1.0** — 初始版本

---

## English

Package any EXE program and its associated folders into a single portable EXE. Double-click to run — no installation required.

### Features

- **One-Click Packaging**: Drag and drop a software folder onto `PortablePackager.exe` to generate a portable version
- **Auto Detection**: Automatically identifies the main program, extracts icons and version information
- **UAC Elevation**: Auto-generates VBS elevation scripts to support programs requiring admin privileges
- **Auto Cleanup**: Extracts to a temp directory and auto-deletes when the program closes (WMI process monitoring)
- **Fast Compression**: Uses `-mx=1` fast compression by default for the best speed-to-size balance
- **Fully Standalone**: Bundles 7z.exe and 7z.sfx internally — no external 7-Zip installation needed

### Usage

1. Download `PortablePackager.exe`
2. **Drag and drop** any software folder onto `PortablePackager.exe`
3. Wait for packaging to complete; the portable EXE is generated in the parent directory

#### Example

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

### How It Works

#### Packaging Flow

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

#### Portable EXE Runtime Flow

```
Double-click _Portable.exe
 → SFX silently extracts to %TEMP%\AppName\
 → Runs VBS elevation script
 → UAC prompt appears
 → Main program launches with admin privileges
 → VBS monitors process exit via WMI
 → SFX auto-cleans temp directory after program closes
```

### Technical Details

#### Core Components

| Component | Description |
|---|---|
| SFX Module | 7-Zip self-extracting module (266KB), handles extraction and launch |
| 7z.exe | Bundled 7-Zip CLI tool for creating archives |
| VBS Elevation | Implements UAC elevation via `ShellExecute "runas"` |
| WMI Monitoring | Waits for target process exit via `Win32_Process` queries |
| Icon Extraction | Parses PE resource directory, extracts RT_GROUP_ICON |
| Icon Replacement | Writes via Windows `UpdateResource` API |
| Version Info | Extracts VS_VERSION_INFO from source and embeds it |

#### SFX Self-Extraction Principle

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

#### VBS UAC Elevation & Process Waiting Mechanism

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

#### PE File Icon Extraction Principle

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

#### Compression Levels

Uses `-mx=1` (fastest compression) by default for the best speed-to-size balance:

| Level | Mode | Speed | Size |
|---|---|---|---|
| 0 | Store only | Fastest | Largest |
| **1** | **Fastest compression (default)** | **Fast** | **Smaller** |
| 3 | Fast compression | Faster | Even smaller |
| 5 | Normal compression | Medium | Small |
| 9 | Maximum compression | Slowest | Smallest |

### Version History

#### V1.2.0.0 (2026-05-24)

**Key Updates:**

- Brand new icon design (blue package box theme)
- Full version info embedding (visible in file properties)
- 7 bug fixes + 3 code optimizations
- Enhanced PE file compatibility

##### Bug Fixes (7 total)

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | `extract_icon()` crash | No boundary checks in PE resource directory parsing | Added comprehensive boundary checks and try-except |
| 2 | Non-standard PE icon extraction failure | PE header resource RVA is 0 but .rsrc section exists | Added `extract_icon_from_rsrc_section()` |
| 3 | SFX module path reference error | `SCRIPT_DIR` overwritten in main() | Use `__file__` to locate script directory |
| 4 | VBS encoding breaks Chinese paths | Saved as UTF-8 but WSH reads in GBK | Changed VBS save encoding to GBK |
| 5 | VBS breaks temp directory cleanup | `ShellExecute` is async, VBS exits immediately | Added WMI process monitoring to wait for exit |
| 6 | `SCRIPT_DIR` global variable pollution | main() overwrites global variable | Introduced `TARGET_DIR` variable for decoupling |
| 7 | `pefile` install failure with no prompt | Crashes directly after `pip install` fails | Enhanced error handling with prompt on failure |

##### Code Optimizations (3 total)

| # | Optimization | Description |
|---|---|---|
| 1 | Compression level optimization | Changed from `-mx=9` (maximum) to `-mx=1` (fastest), significantly faster |
| 2 | `SCRIPT_DIR` / `TARGET_DIR` decoupling | `SCRIPT_DIR` for script resources only, `TARGET_DIR` for target packaging directory |
| 3 | `pefile` error handling enhancement | Shows error details on install failure, verifies import after installation |

##### Icon Update

- Brand new blue package box theme icon
- Supports 6 sizes: 16x16, 32x32, 48x48, 64x64, 128x128, 256x256
- Embedded at build time using PyInstaller `--icon` parameter

##### Version Info

- File Version: 1.2.0.0
- Product Version: 1.2.0.0
- Company Name: PortablePackager Team
- File Description: Universal EXE Portable Packager
- Copyright: Copyright (C) 2026

### Building from Source

#### Prerequisites

| Dependency | Description |
|---|---|
| Python 3.x | Script runtime environment |
| PyInstaller | `pip install pyinstaller`, for packaging into a single EXE |
| pefile | `pip install pefile`, for PE file parsing |
| 7z.sfx | SFX self-extracting module (266KB version, supports GUIMode="2") |
| 7z.exe + 7z.dll | 7-Zip CLI tools for creating archives |

#### Build Steps

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

### File Structure

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
├── README.md                     # Documentation
└── PortablePackager_Technical_Report.docx  # Full technical analysis report
```

### License

MIT License

### Update History

- **V1.2.0.0** — May 25, 2026: New icon, version info embedding, 7 bug fixes, 3 code optimizations
- **V1.0** — Initial release
