"""
通用型 EXE 便携版打包工具（GUI 版）
====================================
将任意 EXE 程序及其关联文件夹封装为一个便携版 EXE。
支持通过文件夹选择对话框选择目标目录。

功能：
  - 弹出文件夹选择对话框，选择要打包的软件文件夹
  - 自动检测当前目录下的 EXE 和子文件夹
  - 自动提取图标和版本信息
  - 解压到临时目录 + 程序关闭后自动清理
  - 输出单个可双击运行的 EXE

使用方法：
  1. 直接运行此脚本（或双击 build_portable_gui.bat）
  2. 在弹出的对话框中选择要打包的软件文件夹
  3. 等待打包完成，便携版 EXE 输出到所选文件夹的上一级目录

依赖：
  - Python 3.x
  - pefile（自动安装）
  - 7-Zip（系统 PATH 中需有 7z.exe）
"""

import struct
import os
import sys
import glob
import shutil
import subprocess
import ctypes
import base64
from ctypes import wintypes

# ============================================================
# 工作目录
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # 脚本所在目录（用于查找 7z.sfx 等资源）
TARGET_DIR = None  # 用户选择的目标打包目录（在 main() 中设置）
WORK_DIR = os.path.join(os.environ.get("TEMP", "."), "sfx_build_workspace")
ICO_OUTPUT = os.path.join(WORK_DIR, "app_icon.ico")
CONFIG_PATH = os.path.join(WORK_DIR, "sfx_config.txt")
ARCHIVE_PATH = os.path.join(WORK_DIR, "package.7z")
TEMP_SFX = os.path.join(WORK_DIR, "sfx_with_version.exe")


def log(msg):
    print(f"  {msg}")


def separator():
    print()


# ============================================================
# 文件夹选择对话框（使用 ctypes，不依赖 tkinter）
# ============================================================

def browse_for_folder(title="请选择文件夹"):
    """
    使用 Windows Shell API (IFileDialog) 弹出文件夹选择对话框。
    不依赖 tkinter，纯 ctypes 实现。
    返回选中的文件夹路径，取消则返回 None。
    """
    # 尝试使用 IFileDialog（Windows Vista+，推荐方式）
    try:
        return _browse_with_ifiledialog(title)
    except Exception:
        pass

    # 回退到 SHBrowseForFolder（兼容旧系统）
    try:
        return _browse_with_shbrowseforfolder(title)
    except Exception:
        pass

    return None


def _browse_with_ifiledialog(title):
    """使用 IFileDialog 接口（Windows Vista+）选择文件夹"""
    import comtypes.client
    from comtypes import GUID

    FOS_PICKFOLDERS = 0x00000020
    CLSID_FileOpenDialog = GUID("{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}")
    IID_IFileOpenDialog = GUID("{D57C7288-D4AD-4768-BE02-9D969532D960}")

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx(None, 0)  # COINIT_APARTMENTTHREADED

    pfd = ctypes.POINTER(comtypes.IUnknown)()
    comtypes.CoCreateInstance(
        CLSID_FileOpenDialog,
        None,
        1,  # CLSCTX_INPROC_SERVER
        IID_IFileOpenDialog,
        ctypes.byref(pfd),
    )

    # 设置选项：只选择文件夹
    dialog = ctypes.cast(pfd, ctypes.POINTER(comtypes.IUnknown))

    # 使用 vtable 调用 SetOptions
    # IFileDialog::SetOptions(DWORD fos)
    # vtable index for SetOptions in IFileDialog is 5 (after IUnknown 3 + GetOptions 4 + SetOptions 5)
    # 实际上更安全的做法是直接用 comtypes 的动态接口
    from comtypes.client import GetModule
    try:
        shell_mod = GetModule("shobjidl")
        fd = ctypes.cast(pfd, ctypes.POINTER(shell_mod.IFileOpenDialog))
        fd.SetOptions(FOS_PICKFOLDERS)
        fd.SetTitle(title)

        hr = fd.Show(None)
        if hr == 0:  # S_OK
            pisi = fd.GetResult()
            path = ctypes.c_wchar_p()
            pisi.GetDisplayName(0, ctypes.byref(path))  # SIGDN_FILESYSPATH = 0
            result = path.value
            pisi.Release()
            ole32.CoUninitialize()
            return result
        else:
            ole32.CoUninitialize()
            return None
    except Exception:
        ole32.CoUninitialize()
        raise


def _browse_with_shbrowseforfolder(title):
    """使用 SHBrowseForFolder（兼容旧版 Windows）选择文件夹"""
    BIF_RETURNONLYFSDIRS = 0x0001
    BIF_NEWDIALOGSTYLE = 0x0040

    # 定义 SHBrowseForFolder 相关结构
    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", ctypes.c_wchar_p),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", ctypes.c_uint),
            ("lpfn", ctypes.c_void_p),
            ("lParam", ctypes.c_long),
            ("iImage", ctypes.c_int),
        ]

    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")

    # 初始化 COM
    ole32.CoInitializeEx(None, 0)

    bi = BROWSEINFO()
    bi.hwndOwner = None
    bi.pidlRoot = None
    bi.pszDisplayName = ctypes.create_unicode_buffer(260)
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
    bi.lpfn = 0
    bi.lParam = 0
    bi.iImage = 0

    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if pidl:
        path = ctypes.create_unicode_buffer(260)
        shell32.SHGetPathFromIDListW(pidl, path)
        # 释放 PIDL
        ole32.CoTaskMemFree(pidl)
        ole32.CoUninitialize()
        return path.value
    else:
        ole32.CoUninitialize()
        return None


# ============================================================
# 自动检测
# ============================================================

def find_7z():
    """查找系统中的 7z.exe（优先查找 PyInstaller 内嵌的）"""
    # PyInstaller 打包模式：优先从内嵌资源目录查找
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundled_7z = os.path.join(sys._MEIPASS, "7z.exe")
        if os.path.isfile(bundled_7z):
            return bundled_7z
    # 系统查找
    for path in os.environ.get("PATH", "").split(";"):
        exe = os.path.join(path.strip(), "7z.exe")
        if os.path.isfile(exe):
            return exe
    for c in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]:
        if os.path.isfile(c):
            return c
    return None


def find_all_files(directory):
    """列出目录下的所有文件和文件夹（不含脚本自身和无关项）"""
    files = []
    folders = []
    script_names = {"build_portable.py", "build_portable.bat",
                    "build_portable_gui.py", "build_portable_gui.bat",
                    "__sfx_temp__.sfx"}
    # 通用排除项：缓存、日志、临时目录
    exclude_dirs = {"__pycache__", "node_modules", ".git"}
    for item in os.listdir(directory):
        if item in script_names or item.startswith("."):
            continue
        if item.lower() in exclude_dirs:
            continue
        # 排除之前打包生成的便携版 EXE
        if item.endswith("_Portable.exe"):
            continue
        full = os.path.join(directory, item)
        if os.path.isfile(full):
            files.append(item)
        elif os.path.isdir(full):
            folders.append(item)
    return files, folders


def detect_main_exe(files, folders):
    """
    自动检测主程序 EXE。
    策略：
      1. 优先在根目录（不递归）查找最大的 EXE
      2. 如果根目录没有，再递归子文件夹查找
      3. 排除已知的非主程序文件名
    """
    exclude_names = {
        "uninstall.exe", "uninst.exe", "setup.exe", "install.exe",
        "update.exe", "updater.exe", "helper.exe", "check.exe",
        "7z.exe", "7za.exe", "sfx.dll",
    }

    candidates = []
    # 优先在根目录查找
    for f in files:
        if f.lower().endswith(".exe") and f.lower() not in exclude_names:
            full = os.path.join(TARGET_DIR, f)
            candidates.append((full, os.path.getsize(full)))

    # 根目录没有 EXE 时，再递归子目录查找
    if not candidates:
        for root, dirs, filenames in os.walk(TARGET_DIR):
            dirs[:] = [d for d in dirs if d.lower() not in {"__pycache__", "node_modules", ".git"}]
            for f in filenames:
                if f.lower().endswith(".exe") and f.lower() not in exclude_names:
                    full = os.path.join(root, f)
                    candidates.append((full, os.path.getsize(full)))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    return None


def detect_sfx_module(files, main_exe=None):
    """检测当前目录中是否有 SFX 启动器（用于提取 SFX 模块）"""
    for f in files:
        if f.lower().endswith(".exe"):
            full = os.path.join(TARGET_DIR, f)
            # 跳过主程序本身
            if main_exe and os.path.normcase(full) == os.path.normcase(main_exe):
                continue
            with open(full, "rb") as fh:
                data = fh.read(4096)
            # 检查是否包含 7z SFX 特征
            if b"7z" in data[0x100:0x400] or b"7-Zip" in data[0x100:0x400]:
                return full
    return None


def detect_pack_items(main_exe_path, files, folders):
    """
    决定要打包的文件和文件夹。

    策略：
      始终打包 TARGET_DIR（用户选择的文件夹）下的所有内容，
      不再进入子目录打包。主程序路径仅用于提取图标和生成启动配置。
    """
    skip_exts = {".pdb"}

    items = []
    work_dir = TARGET_DIR

    # 打包所有文件夹
    for f in folders:
        full = os.path.join(TARGET_DIR, f)
        if os.path.isdir(full):
            file_count = sum(len(fs) for _, _, fs in os.walk(full))
            if file_count > 0:
                items.append(f)

    # 打包所有文件
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in skip_exts and not f.endswith("_Portable.exe"):
            items.append(f)

    return items, work_dir


def detect_run_program(main_exe_path, work_dir):
    """
    根据打包结构，自动生成 RunProgram 路径。
    使用 %%T 变量（解压目录的绝对路径）。
    """
    # 计算主程序相对于工作目录的路径
    exe_rel = os.path.relpath(main_exe_path, work_dir).replace("/", "\\")
    return f'%%T\\{exe_rel}'


# ============================================================
# SFX 模块提取
# ============================================================

def extract_sfx_module(target_exe):
    """从 SFX 文件中提取 7z SFX 模块"""
    with open(target_exe, "rb") as f:
        data = f.read()
    sig = b"\x37\x7A\xBC\xAF\x27\x1C"
    idx = data.find(sig)
    if idx == -1:
        return None
    sfx_out = os.path.join(WORK_DIR, "7z.sfx")
    with open(sfx_out, "wb") as f:
        f.write(data[:idx])
    return sfx_out


def download_sfx_module():
    """
    如果无法从本地提取 SFX 模块，尝试从多个位置查找。
    搜索策略：
      1. PyInstaller 打包后的临时目录（sys._MEIPASS）
      2. 7-Zip 安装目录
      3. 7z.exe 所在目录（可能是便携版 7-Zip）
      4. 脚本所在目录
    """
    candidates = []

    # 最高优先级：PyInstaller 打包后的临时目录
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        meipass_sfx = os.path.join(sys._MEIPASS, "7z.sfx")
        if os.path.isfile(meipass_sfx):
            log(f"从 PyInstaller 临时目录找到 SFX 模块：{meipass_sfx}")
            return meipass_sfx

    # 从脚本所在目录查找（确保使用用户提供的 SFX 模块）
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ["7z.sfx", "7zSD.sfx", "7zS.sfx"]:
        candidates.append(os.path.join(_script_dir, name))

    # 7-Zip 安装目录
    candidates.extend([
        r"C:\Program Files\7-Zip\7z.sfx",
        r"C:\Program Files\7-Zip\7zSD.sfx",
        r"C:\Program Files\7-Zip\7zS.sfx",
        r"C:\Program Files (x86)\7-Zip\7z.sfx",
        r"C:\Program Files (x86)\7-Zip\7zSD.sfx",
    ])

    # 从 7z.exe 所在目录查找（便携版 7-Zip）
    seven_z = find_7z()
    if seven_z:
        seven_z_dir = os.path.dirname(seven_z)
        for name in ["7z.sfx", "7zSD.sfx", "7zS.sfx"]:
            candidates.append(os.path.join(seven_z_dir, name))

    for c in candidates:
        if os.path.isfile(c):
            return c

    # 最终回退：使用内置的 SFX 模块
    log("尝试使用内置 SFX 模块...")
    builtin_sfx = get_builtin_sfx_module()
    if builtin_sfx:
        return builtin_sfx

    return None


def get_builtin_sfx_module():
    """从脚本同目录下的 7z.sfx 文件加载 SFX 模块"""
    sfx_path = os.path.join(SCRIPT_DIR, "7z.sfx")
    if os.path.isfile(sfx_path):
        return sfx_path
    return None



# ============================================================
# 图标提取
# ============================================================

def extract_icon(exe_path, ico_path):
    """从 PE 文件中提取图标，保存为 .ico 文件"""
    try:
        with open(exe_path, "rb") as f:
            data = f.read()

        if len(data) < 64:
            return False

        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset == 0 or pe_offset + 24 > len(data):
            return False

        coff_offset = pe_offset + 4
        num_sections = struct.unpack_from("<H", data, coff_offset + 2)[0]
        opt_header_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
        opt_offset = coff_offset + 20

        if opt_offset + 112 > len(data):
            return False

        ddo = opt_offset + 96
        res_rva = struct.unpack_from("<I", data, ddo + 16)[0]

        # 没有资源段则直接返回
        if res_rva == 0:
            return False

        sections = []
        for i in range(num_sections):
            off = opt_offset + opt_header_size + i * 40
            if off + 40 > len(data):
                continue
            sections.append((
                struct.unpack_from("<I", data, off + 12)[0],
                struct.unpack_from("<I", data, off + 8)[0],
                struct.unpack_from("<I", data, off + 20)[0],
                struct.unpack_from("<I", data, off + 16)[0],
            ))

        def rva_to_off(rva):
            for va, vs, ro, rs in sections:
                if va <= rva < va + max(vs, rs):
                    return ro + (rva - va)
            return 0

        res_off = rva_to_off(res_rva)
        if res_off == 0 or res_off + 16 > len(data):
            return False

        def parse_dir(off, base):
            if off + 16 > len(data):
                return []
            nn = struct.unpack_from("<H", data, off + 12)[0]
            ni = struct.unpack_from("<H", data, off + 14)[0]
            entries = []
            for i in range(nn + ni):
                eo = off + 16 + i * 8
                if eo + 8 > len(data):
                    break
                nid = struct.unpack_from("<I", data, eo)[0]
                dv = struct.unpack_from("<I", data, eo + 4)[0]
                entries.append((str(nid), bool(dv & 0x80000000), dv & 0x7FFFFFFF))
            return entries

        def get_data(off, base):
            if off + 8 > len(data):
                return b""
            rva = struct.unpack_from("<I", data, off)[0]
            size = struct.unpack_from("<I", data, off + 4)[0]
            foff = rva_to_off(rva)
            if foff == 0 or foff + size > len(data):
                return b""
            return data[foff:foff + size]

        types = parse_dir(res_off, res_off)
        icon_group_dir = icon_dir = None
        for name, is_dir, sub in types:
            if name == "14":
                icon_group_dir = parse_dir(res_off + sub, res_off)
            elif name == "3":
                icon_dir = parse_dir(res_off + sub, res_off)

        if not icon_group_dir or not icon_dir:
            return False

        grp_entries = parse_dir(res_off + icon_group_dir[0][2], res_off)
        if not grp_entries:
            return False
        grp_data = get_data(res_off + grp_entries[0][2], res_off)
        if len(grp_data) < 6:
            return False
        count = struct.unpack_from("<H", grp_data, 4)[0]

        icon_entries = {}
        for name, is_dir, sub in icon_dir:
            if is_dir:
                lang_entries = parse_dir(res_off + sub, res_off)
                for _, _, lsub in lang_entries:
                    icon_entries[name] = get_data(res_off + lsub, res_off)

        ico = bytearray(struct.pack("<HHH", 0, 1, count))
        data_offset = 6 + count * 16
        data_parts = []

        for idx in range(count):
            eo = 6 + idx * 14
            if eo + 14 > len(grp_data):
                break
            w, h = grp_data[eo], grp_data[eo + 1]
            colors = grp_data[eo + 2]
            planes = struct.unpack_from("<H", grp_data, eo + 4)[0]
            bpp = struct.unpack_from("<H", grp_data, eo + 6)[0]
            icon_id = str(struct.unpack_from("<H", grp_data, eo + 12)[0])

            ico_w = w if w < 256 else 0
            ico_h = h if h < 256 else 0

            if icon_id in icon_entries:
                actual = len(icon_entries[icon_id])
                ico += struct.pack("<BBBBHHII", ico_w, ico_h, colors, 0, planes, bpp, actual, data_offset)
                data_parts.append(icon_entries[icon_id])
                data_offset += actual

        with open(ico_path, "wb") as f:
            f.write(ico)
            for part in data_parts:
                f.write(part)

        log(f"图标已提取：{count} 种尺寸，{os.path.getsize(ico_path)} 字节")
        return True
    except Exception as e:
        log(f"图标提取异常：{e}")
        return False


def extract_icon_from_rsrc_section(exe_path, ico_path):
    """
    从具有非标准资源目录的 PE 文件中提取图标
    适用于 PE 头中资源 RVA 为 0 但 .rsrc 节仍然存在的情况
    """
    try:
        with open(exe_path, "rb") as f:
            data = f.read()

        if len(data) < 64:
            return False

        # 解析 PE 头
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset == 0 or pe_offset + 24 > len(data):
            return False

        coff_offset = pe_offset + 4
        num_sections = struct.unpack_from("<H", data, coff_offset + 2)[0]
        opt_header_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
        opt_offset = coff_offset + 20

        if opt_offset + 112 > len(data):
            return False

        # 查找 .rsrc 节
        rsrc_ro = None
        rsrc_va = None
        for i in range(num_sections):
            off = opt_offset + opt_header_size + i * 40
            if off + 40 > len(data):
                continue
            name = data[off:off+8].rstrip(b'\x00').decode('ascii', errors='ignore')
            if name == '.rsrc':
                rsrc_va = struct.unpack_from("<I", data, off + 12)[0]
                rsrc_ro = struct.unpack_from("<I", data, off + 20)[0]
                break

        if rsrc_ro is None:
            return False

        # 从 .rsrc 节解析资源目录
        base = rsrc_ro

        def parse_dir(off):
            """解析资源目录"""
            if base + off + 16 > len(data):
                return []
            nn = struct.unpack_from("<H", data, base + off + 12)[0]
            ni = struct.unpack_from("<H", data, base + off + 14)[0]
            entries = []
            for i in range(nn + ni):
                eo = base + off + 16 + i * 8
                if eo + 8 > len(data):
                    break
                nid = struct.unpack_from("<I", data, eo)[0]
                dv = struct.unpack_from("<I", data, eo + 4)[0]
                entries.append((nid, bool(dv & 0x80000000), dv & 0x7FFFFFFF))
            return entries

        def get_data(off):
            """获取资源数据"""
            if base + off + 8 > len(data):
                return b""
            rva = struct.unpack_from("<I", data, base + off)[0]
            size = struct.unpack_from("<I", data, base + off + 4)[0]
            # 资源数据 RVA 需要转换为文件偏移
            foff = rsrc_ro + (rva - rsrc_va)
            if foff + size > len(data):
                return b""
            return data[foff:foff + size]

        # 查找 RT_ICON (3) 和 RT_GROUP_ICON (14)
        root = parse_dir(0)
        icon_group_dir = None
        icon_dir = None

        for nid, is_dir, sub in root:
            if nid == 3:  # RT_ICON
                icon_dir = parse_dir(sub)
            elif nid == 14:  # RT_GROUP_ICON
                icon_group_dir = parse_dir(sub)

        if not icon_group_dir or not icon_dir:
            return False

        # 获取第一个图标组
        if not icon_group_dir:
            return False

        grp_entries = parse_dir(icon_group_dir[0][2])
        if not grp_entries:
            return False

        grp_data = get_data(grp_entries[0][2])
        if len(grp_data) < 6:
            return False

        count = struct.unpack_from("<H", grp_data, 4)[0]

        # 获取所有图标数据
        icon_entries = {}
        for nid, is_dir, sub in icon_dir:
            if is_dir:
                lang_entries = parse_dir(sub)
                for _, _, lsub in lang_entries:
                    icon_entries[nid] = get_data(lsub)

        # 构建 ICO 文件
        ico = bytearray(struct.pack("<HHH", 0, 1, count))
        data_offset = 6 + count * 16
        data_parts = []

        for idx in range(count):
            eo = 6 + idx * 14
            if eo + 14 > len(grp_data):
                break
            w = grp_data[eo]
            h = grp_data[eo + 1]
            colors = grp_data[eo + 2]
            planes = struct.unpack_from("<H", grp_data, eo + 4)[0]
            bpp = struct.unpack_from("<H", grp_data, eo + 6)[0]
            icon_id = struct.unpack_from("<H", grp_data, eo + 12)[0]

            ico_w = w if w < 256 else 0
            ico_h = h if h < 256 else 0

            if icon_id in icon_entries:
                icon_data = icon_entries[icon_id]
                actual = len(icon_data)
                ico += struct.pack("<BBBBHHII", ico_w, ico_h, colors, 0, planes, bpp, actual, data_offset)
                data_parts.append(icon_data)
                data_offset += actual

        with open(ico_path, "wb") as f:
            f.write(ico)
            for part in data_parts:
                f.write(part)

        log(f"图标已提取（.rsrc节）：{count} 种尺寸，{os.path.getsize(ico_path)} 字节")
        return True
    except Exception as e:
        return False


def replace_icon_in_exe(exe_path, ico_path, output_path):
    """替换 EXE 中的图标资源"""
    with open(exe_path, "rb") as f:
        data = bytearray(f.read())
    with open(ico_path, "rb") as f:
        ico_data = f.read()

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    coff_offset = pe_offset + 4
    num_sections = struct.unpack_from("<H", data, coff_offset + 2)[0]
    opt_header_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
    opt_offset = coff_offset + 20
    ddo = opt_offset + 96
    res_rva = struct.unpack_from("<I", data, ddo + 16)[0]

    sections = []
    for i in range(num_sections):
        off = opt_offset + opt_header_size + i * 40
        sections.append({
            "va": struct.unpack_from("<I", data, off + 12)[0],
            "vs": struct.unpack_from("<I", data, off + 8)[0],
            "ro": struct.unpack_from("<I", data, off + 20)[0],
            "rs": struct.unpack_from("<I", data, off + 16)[0],
        })

    def rva_to_off(rva):
        for s in sections:
            if s["va"] <= rva < s["va"] + max(s["vs"], s["rs"]):
                return s["ro"] + (rva - s["va"])
        return 0

    res_off = rva_to_off(res_rva)

    def parse_dir(off, base):
        nn = struct.unpack_from("<H", data, off + 12)[0]
        ni = struct.unpack_from("<H", data, off + 14)[0]
        entries = []
        for i in range(nn + ni):
            eo = off + 16 + i * 8
            nid = struct.unpack_from("<I", data, eo)[0]
            dv = struct.unpack_from("<I", data, eo + 4)[0]
            entries.append((str(nid), bool(dv & 0x80000000), dv & 0x7FFFFFFF))
        return entries

    def get_data(off, base):
        rva = struct.unpack_from("<I", data, off)[0]
        size = struct.unpack_from("<I", data, off + 4)[0]
        foff = rva_to_off(rva)
        return data[foff:foff + size], rva, size, foff

    types = parse_dir(res_off, res_off)
    icon_group_dir = icon_dir = None
    for name, is_dir, sub in types:
        if name == "14":
            icon_group_dir = parse_dir(res_off + sub, res_off)
        elif name == "3":
            icon_dir = parse_dir(res_off + sub, res_off)

    if not icon_group_dir or not icon_dir:
        return False

    ico_count = struct.unpack_from("<H", ico_data, 4)[0]
    ico_icons = []
    for i in range(ico_count):
        eo = 6 + i * 16
        ico_icons.append({
            "w": ico_data[eo], "h": ico_data[eo + 1], "colors": ico_data[eo + 2],
            "planes": struct.unpack_from("<H", ico_data, eo + 4)[0],
            "bpp": struct.unpack_from("<H", ico_data, eo + 6)[0],
            "size": struct.unpack_from("<I", ico_data, eo + 8)[0],
            "data": ico_data[struct.unpack_from("<I", ico_data, eo + 12)[0]:
                               struct.unpack_from("<I", ico_data, eo + 12)[0] + ico_data[eo + 8]],
        })

    icon_data_map = {}
    for name, is_dir, sub in icon_dir:
        if is_dir:
            for _, _, lsub in parse_dir(res_off + sub, res_off):
                d, r, s, fo = get_data(res_off + lsub, res_off)
                icon_data_map[name] = {"size": s, "file_off": fo}

    for gname, gis_dir, gsub in icon_group_dir:
        if not gis_dir:
            continue
        for _, lis_dir, lsub in parse_dir(res_off + gsub, res_off):
            if lis_dir:
                continue
            grp_d, _, grp_size, grp_fo = get_data(res_off + lsub, res_off)
            old_count = struct.unpack_from("<H", grp_d, 4)[0]
            old_icons = []
            for idx in range(old_count):
                eo2 = 6 + idx * 14
                old_icons.append(str(struct.unpack_from("<H", grp_d, eo2 + 12)[0]))

            new_count = min(len(ico_icons), old_count)
            new_grp = bytearray(struct.pack("<HHH", 0, 1, new_count))
            for idx in range(new_count):
                icon = ico_icons[idx]
                old_id = old_icons[idx] if idx < len(old_icons) else str(idx + 1)
                new_grp += struct.pack(
                    "<BBBBHHIH",
                    icon["w"] if icon["w"] < 256 else 0,
                    icon["h"] if icon["h"] < 256 else 0,
                    icon["colors"], 0, icon["planes"], icon["bpp"],
                    icon["size"], int(old_id),
                )
                if old_id in icon_data_map:
                    entry = icon_data_map[old_id]
                    new_d = icon["data"]
                    old_s = entry["size"]
                    padded = new_d + b"\x00" * max(0, old_s - len(new_d))
                    data[entry["file_off"]:entry["file_off"] + old_s] = padded[:old_s]

            padded_grp = new_grp + b"\x00" * max(0, grp_size - len(new_grp))
            data[grp_fo:grp_fo + grp_size] = padded_grp[:grp_size]

    with open(output_path, "wb") as f:
        f.write(data)
    return True


# ============================================================
# 版本信息
# ============================================================

def extract_version_info(exe_path):
    """从 PE 文件中提取 VS_VERSION_INFO 原始数据"""
    import pefile
    pe = pefile.PE(exe_path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    ver_data = None
    if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == 16:
                for id_entry in entry.directory.entries:
                    for lang_entry in id_entry.directory.entries:
                        rva = lang_entry.data.struct.OffsetToData
                        size = lang_entry.data.struct.Size
                        ver_data = pe.get_data(rva, size)
                        break
                    if ver_data:
                        break
                break
    pe.close()
    return ver_data


def add_version_info(exe_path, ver_data):
    """使用 Windows API 将版本信息添加到 EXE"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    BeginUpdateResource = kernel32.BeginUpdateResourceW
    BeginUpdateResource.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    BeginUpdateResource.restype = wintypes.HANDLE

    UpdateResource = kernel32.UpdateResourceW
    UpdateResource.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    UpdateResource.restype = wintypes.BOOL

    EndUpdateResource = kernel32.EndUpdateResourceW
    EndUpdateResource.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    EndUpdateResource.restype = wintypes.BOOL

    hUpdate = BeginUpdateResource(exe_path, False)
    if not hUpdate:
        return False

    RT_VERSION = ctypes.cast(16, wintypes.LPCWSTR)
    RT_VERSION_ID = ctypes.cast(1, wintypes.LPCWSTR)

    if not UpdateResource(hUpdate, RT_VERSION, RT_VERSION_ID, 0, ver_data, len(ver_data)):
        return False
    if not EndUpdateResource(hUpdate, False):
        return False
    return True


def replace_icon_windows_api(exe_path, ico_path):
    """使用 Windows API 替换 EXE 图标（最可靠的方式）

    原理：
      1. 解析 ICO 文件，提取每个尺寸的图标数据
      2. 构建 GRPICONDIR 结构（GROUP_ICON 资源数据）
      3. 先删除所有旧的 RT_ICON 和 RT_GROUP_ICON
      4. 用 UpdateResource 写入新的 RT_ICON 和 RT_GROUP_ICON
      5. EndUpdateResource 生成新的 EXE

    注意：
      必须操作纯净的 SFX 模块（不含 7z 附加数据），
      因为 EndUpdateResource 会截断非 PE 数据。
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    BeginUpdateResource = kernel32.BeginUpdateResourceW
    BeginUpdateResource.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    BeginUpdateResource.restype = wintypes.HANDLE

    UpdateResource = kernel32.UpdateResourceW
    UpdateResource.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    UpdateResource.restype = wintypes.BOOL

    EndUpdateResource = kernel32.EndUpdateResourceW
    EndUpdateResource.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    EndUpdateResource.restype = wintypes.BOOL

    # 读取 ICO 文件
    with open(ico_path, "rb") as f:
        ico_data = f.read()

    ico_count = struct.unpack_from("<H", ico_data, 4)[0]

    # 解析 ICO 文件中每个图标
    icons = []
    for i in range(ico_count):
        eo = 6 + i * 16
        w = ico_data[eo]
        h = ico_data[eo + 1]
        colors = ico_data[eo + 2]
        planes = struct.unpack_from("<H", ico_data, eo + 4)[0]
        bpp = struct.unpack_from("<H", ico_data, eo + 6)[0]
        size = struct.unpack_from("<I", ico_data, eo + 8)[0]
        offset = struct.unpack_from("<I", ico_data, eo + 12)[0]
        icons.append({
            "w": w, "h": h, "colors": colors,
            "planes": planes, "bpp": bpp,
            "size": size,
            "data": ico_data[offset:offset + size],
        })

    # 构建 GRPICONDIR（RT_GROUP_ICON 的数据）
    # 结构：ICONDIR(6) + ICONDIRENTRY(14) * count
    grp_data = struct.pack("<HHH", 0, 1, ico_count)  # Reserved, Type, Count
    for i, icon in enumerate(icons):
        grp_data += struct.pack(
            "<BBBBHHIH",
            icon["w"] if icon["w"] < 256 else 0,
            icon["h"] if icon["h"] < 256 else 0,
            icon["colors"], 0,
            icon["planes"], icon["bpp"],
            icon["size"], i + 1,  # RT_ICON ID 从 1 开始
        )

    # 开始更新资源
    hUpdate = BeginUpdateResource(exe_path, False)
    if not hUpdate:
        return False

    RT_ICON = ctypes.cast(3, wintypes.LPCWSTR)
    RT_GROUP_ICON = ctypes.cast(14, wintypes.LPCWSTR)

    # 先删除所有旧的图标资源（通过写入 NULL 数据）
    # 读取现有图标 ID 列表
    try:
        import pefile
        pe = pefile.PE(exe_path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
            for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
                if entry.id == 3:  # RT_ICON
                    for id_entry in entry.directory.entries:
                        for lang_entry in id_entry.directory.entries:
                            icon_id = ctypes.cast(id_entry.id, wintypes.LPCWSTR)
                            UpdateResource(hUpdate, RT_ICON, icon_id, lang_entry.id, None, 0)
                elif entry.id == 14:  # RT_GROUP_ICON
                    for id_entry in entry.directory.entries:
                        for lang_entry in id_entry.directory.entries:
                            grp_id = ctypes.cast(id_entry.id, wintypes.LPCWSTR)
                            UpdateResource(hUpdate, RT_GROUP_ICON, grp_id, lang_entry.id, None, 0)
        pe.close()
    except Exception:
        pass  # 如果读取失败，继续尝试写入

    # 写入新的 RT_ICON 资源
    for i, icon in enumerate(icons):
        icon_id = ctypes.cast(i + 1, wintypes.LPCWSTR)
        if not UpdateResource(hUpdate, RT_ICON, icon_id, 0, icon["data"], icon["size"]):
            EndUpdateResource(hUpdate, True)  # 丢弃更改
            return False

    # 写入新的 RT_GROUP_ICON 资源
    grp_id = ctypes.cast(1, wintypes.LPCWSTR)
    if not UpdateResource(hUpdate, RT_GROUP_ICON, grp_id, 0, grp_data, len(grp_data)):
        EndUpdateResource(hUpdate, True)
        return False

    # 提交更改
    if not EndUpdateResource(hUpdate, False):
        return False

    return True


# ============================================================
# SFX 配置
# ============================================================

def create_sfx_config(config_path, run_program, temp_folder_name, exe_name):
    """创建 SFX 配置文件

    原理说明：
      许多程序（如 DDU、驱动类工具等）的 EXE manifest 中标记了
      requireAdministrator，必须以管理员权限运行。

      如果 SFX 直接启动这类 EXE，Windows 会因权限不足而报错：
        "系统找不到指定的文件。"（误导性错误，实际是权限问题）

      解决方案：
      1. 生成一个 VBS 提权脚本（_run_elevated.vbs）
      2. SFX 解压后先运行 VBS（不需要管理员权限）
      3. VBS 通过 ShellExecute 以 "runas" 模式启动目标 EXE
      4. Windows 弹出 UAC 提权对话框，用户确认后以管理员权限运行
      5. 目标程序关闭后，SFX 自动清理临时目录
    """
    # 生成 VBS 提权启动脚本（写入工作目录，打包时一起压缩）
    vbs_name = "_run_elevated.vbs"
    vbs_path = os.path.join(WORK_DIR, vbs_name)
    # VBS 脚本：以管理员权限启动目标 EXE，并等待其退出
    # 使用 Shell.Application 提权启动，然后用 WMI 监听进程退出
    # 这样 SFX 的清理机制才能正常工作（否则会产生垃圾文件）
    vbs_content = f'''Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("Shell.Application")
scriptPath = WScript.ScriptFullName
parentFolder = fso.GetParentFolderName(scriptPath)
exePath = parentFolder & "\\{exe_name}"
' 以管理员权限启动目标程序
shell.ShellExecute exePath, "", parentFolder, "runas", 1
' 等待目标进程退出（通过 WMI 监听）
Set wmi = GetObject("winmgmts:\\\\.\\root\\cimv2")
exeName = "{exe_name}"
Do
    WScript.Sleep 500
    Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='" & exeName & "'")
Loop While procs.Count > 0
'''
    # VBS 脚本必须使用系统 ANSI 编码（中文系统为 GBK/cp936），否则中文字符会乱码
    # Windows Script Host 默认使用系统代码页，不是 UTF-8
    with open(vbs_path, "w", encoding="gbk") as f:
        f.write(vbs_content)

    # SFX 配置：先运行 VBS 提权脚本
    config = f""";
;!@Install@!UTF-8!
GUIMode="2"
MiscFlags="1+2+4"
InstallPath="%TEMP%\\{temp_folder_name}"
RunProgram="wscript.exe %%T\\{vbs_name}"
;!@InstallEnd@!
"""
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config)
    return vbs_name


# ============================================================
# 主流程
# ============================================================

def safe_input(msg=""):
    """安全的 input，在非交互模式下不会崩溃"""
    try:
        return input(msg)
    except EOFError:
        return ""


def main():
    print("=" * 60)
    print("  通用型 EXE 便携版打包工具")
    print("=" * 60)

    # 压缩级别：1（最快压缩，速度和体积平衡最佳）
    compress_level = 1

    # ---- 获取目标文件夹（支持拖拽） ----
    separator()
    target_dir = None

    # 方式1：拖拽文件夹到 EXE 上 → sys.argv[1] 是文件夹路径
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.isdir(arg):
            target_dir = os.path.abspath(arg)
        elif os.path.isfile(arg):
            # 如果拖入的是文件，取其所在目录
            target_dir = os.path.abspath(os.path.dirname(arg))

    # 方式2：双击运行 → 提示用户拖拽
    if not target_dir:
        log("使用方法：请将软件文件夹拖拽到本程序上即可开始打包。")
        safe_input("\n按回车键退出...")
        sys.exit(0)

    # 设置目标打包目录
    global TARGET_DIR
    TARGET_DIR = target_dir
    log(f"目标文件夹：{TARGET_DIR}")

    # 输出目录为用户选择的文件夹的上一级目录
    OUTPUT_DIR = os.path.dirname(TARGET_DIR)
    log(f"输出目录：{OUTPUT_DIR}")

    # ---- 依赖检查 ----
    seven_z = find_7z()
    if not seven_z:
        log("错误：找不到 7z.exe，请安装 7-Zip")
        safe_input("\n按回车键退出...")
        sys.exit(1)

    try:
        import pefile  # noqa: F401
    except ImportError:
        log("正在安装 pefile...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "pefile"], capture_output=True)
        if result.returncode != 0:
            log("错误：pefile 安装失败，请手动执行 pip install pefile")
            log(f"详情：{result.stderr.decode('utf-8', errors='ignore')}")
            safe_input("\n按回车键退出...")
            sys.exit(1)
        try:
            import pefile  # noqa: F401
        except ImportError:
            log("错误：pefile 安装后仍无法导入，请检查 Python 环境")
            safe_input("\n按回车键退出...")
            sys.exit(1)

    # ---- 自动检测 ----
    separator()
    print("[自动检测] 扫描当前目录...")
    files, folders = find_all_files(TARGET_DIR)

    log(f"文件：{len(files)} 个")
    for f in files:
        log(f"  {f}")
    log(f"文件夹：{len(folders)} 个")
    for f in folders:
        log(f"  {f}\\")
    if not files and not folders:
        log("错误：当前目录为空")
        safe_input("\n按回车键退出...")
        sys.exit(1)

    # 检测主程序
    separator()
    print("[自动检测] 查找主程序...")
    main_exe = detect_main_exe(files, folders)
    if not main_exe:
        log("错误：未找到主程序 EXE")
        safe_input("\n按回车键退出...")
        sys.exit(1)
    main_exe_rel = os.path.relpath(main_exe, TARGET_DIR).replace("/", "\\")
    log(f"主程序：{main_exe_rel}（{os.path.getsize(main_exe)} 字节）")

    # 检测 SFX 模块
    separator()
    print("[自动检测] 查找 SFX 模块...")
    sfx_module = detect_sfx_module(files, main_exe)
    if sfx_module:
        log(f"找到 SFX 启动器：{os.path.basename(sfx_module)}")
    else:
        log("未找到本地 SFX 启动器，尝试从 7-Zip 安装目录获取...")
        sfx_module = download_sfx_module()
        if sfx_module:
            log(f"使用 7-Zip SFX 模块：{sfx_module}")
        else:
            log("错误：找不到 SFX 模块")
            log("请将 SFX 启动器 EXE 放到当前目录，或安装 7-Zip")
            safe_input("\n按回车键退出...")
            sys.exit(1)

    # 确定打包内容
    separator()
    print("[自动检测] 确定打包内容...")
    pack_items, pack_work_dir = detect_pack_items(main_exe, files, folders)
    log("将打包以下内容：")
    for item in pack_items:
        full = os.path.join(pack_work_dir, item)
        if os.path.isdir(full):
            count = sum(len(f) for _, _, f in os.walk(full))
            log(f"  {item}\\（{count} 个文件）")
        else:
            log(f"  {item}（{os.path.getsize(full)} 字节）")

    # 以程序所在文件夹名作为软件名称
    folder_name = os.path.basename(pack_work_dir)
    # 清理文件夹名：去除空格，将点号替换为下划线（SFX 模块会把点号当作扩展名分隔符）
    safe_name = folder_name.replace(" ", "").replace(".", "_")

    # 确定输出名称（输出到用户选择的文件夹的上一级目录）
    output_name = f"{safe_name}_Portable.exe"
    output_path = os.path.join(OUTPUT_DIR, output_name)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except PermissionError:
            for i in range(2, 100):
                output_name = f"{safe_name}_Portable_{i}.exe"
                output_path = os.path.join(OUTPUT_DIR, output_name)
                if not os.path.exists(output_path):
                    break
            else:
                log("错误：输出文件全部被占用")
                safe_input("\n按回车键退出...")
                sys.exit(1)

    # 临时文件夹名 = 程序所在文件夹名（去除空格）
    temp_folder = safe_name

    # 确定启动路径
    run_program = detect_run_program(main_exe, pack_work_dir)

    # ---- 创建工作目录 ----
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR)

    # ---- 步骤 1：提取 SFX 模块 ----
    separator()
    print("[1/6] 准备 SFX 模块...")
    # 如果找到的是独立的 .sfx 文件，直接使用；否则从 EXE 中提取
    if sfx_module.lower().endswith(".sfx"):
        log(f"SFX 模块：{os.path.getsize(sfx_module)} 字节（直接使用）")
    else:
        extracted_sfx = extract_sfx_module(sfx_module)
        if extracted_sfx:
            sfx_module = extracted_sfx
            log(f"SFX 模块：{os.path.getsize(sfx_module)} 字节（从 EXE 提取）")
        else:
            log("警告：无法从 EXE 中提取 SFX 模块，尝试直接使用原文件")
            log(f"SFX 模块：{os.path.getsize(sfx_module)} 字节")

    # ---- 步骤 2：提取图标 ----
    separator()
    print("[2/6] 提取图标...")
    icon_extracted = extract_icon(main_exe, ICO_OUTPUT)
    if not icon_extracted:
        # 尝试从 .rsrc 节提取（适用于非标准 PE 文件）
        icon_extracted = extract_icon_from_rsrc_section(main_exe, ICO_OUTPUT)
    if not icon_extracted:
        log("警告：图标提取失败，将使用默认图标")

    # ---- 步骤 3：提取版本信息 ----
    separator()
    print("[3/6] 提取版本信息...")
    ver_data = extract_version_info(main_exe)
    if ver_data:
        log(f"版本信息：{len(ver_data)} 字节")
    else:
        log("未找到版本信息，将跳过")

    # ---- 步骤 4：创建 SFX 配置和提权脚本 ----
    separator()
    print("[4/7] 创建启动配置...")
    exe_basename = os.path.basename(main_exe)
    vbs_name = create_sfx_config(CONFIG_PATH, run_program, temp_folder, exe_basename)
    log(f"启动路径：{run_program}")
    log(f"提权脚本：{vbs_name}")
    log(f"临时目录：%TEMP%\\{temp_folder}")
    log(f"自动清理：是")

    # ---- 步骤 5：创建 7z 压缩包 ----
    separator()
    print("[5/7] 创建 7z 压缩包...")
    # 从 pack_work_dir 打包，保持相对路径结构
    pack_paths = [os.path.join(pack_work_dir, item) for item in pack_items]
    # 将 VBS 提权脚本也打包进去
    vbs_full_path = os.path.join(WORK_DIR, vbs_name)
    if os.path.isfile(vbs_full_path):
        pack_paths.append(vbs_full_path)
    result = subprocess.run(
        [seven_z, "a", "-t7z", f"-mx={compress_level}", ARCHIVE_PATH] + pack_paths,
        capture_output=True, text=True, cwd=pack_work_dir,
    )
    if result.returncode != 0:
        log(f"7z 错误：{result.stderr}")
        safe_input("\n按回车键退出...")
        sys.exit(1)
    log(f"压缩包：{os.path.getsize(ARCHIVE_PATH) / 1024 / 1024:.2f} MB")

    # ---- 步骤 6：组装 SFX ----
    separator()
    print("[6/7] 组装便携版 EXE...")

    # 5a. 复制 SFX 模块
    shutil.copy2(sfx_module, TEMP_SFX)

    # 5b. 替换图标（使用 Windows API，最可靠）
    if os.path.isfile(ICO_OUTPUT):
        log("替换图标...")
        if not replace_icon_windows_api(TEMP_SFX, ICO_OUTPUT):
            log("警告：Windows API 图标替换失败，尝试备用方案...")
            replace_icon_in_exe(TEMP_SFX, ICO_OUTPUT, TEMP_SFX)

    # 5c. 添加版本信息
    if ver_data:
        log("添加版本信息...")
        add_version_info(TEMP_SFX, ver_data)

    # 5d. SFX 配置已在步骤 4 创建
    log(f"启动方式：VBS 提权启动")

    # 5e. 合并
    with open(TEMP_SFX, "rb") as f:
        sfx_bytes = f.read()
    with open(CONFIG_PATH, "rb") as f:
        config_bytes = f.read()
    with open(ARCHIVE_PATH, "rb") as f:
        archive_bytes = f.read()

    with open(output_path, "wb") as f:
        f.write(sfx_bytes)
        f.write(config_bytes)
        f.write(archive_bytes)

    # ---- 步骤 7：验证 ----
    separator()
    print("[7/7] 验证...")
    output_ver = extract_version_info(output_path)
    if output_ver:
        log("版本信息：OK 已嵌入")
    else:
        log("版本信息：X 未嵌入（源程序可能不含版本信息）")

    output_size = os.path.getsize(output_path)
    log(f"输出文件：{output_name}（{output_size / 1024 / 1024:.2f} MB）")

    # 清理
    shutil.rmtree(WORK_DIR)
    # 清理内置 SFX 临时文件
    builtin_sfx_temp = os.path.join(TARGET_DIR, "__sfx_temp__.sfx")
    if os.path.isfile(builtin_sfx_temp):
        os.remove(builtin_sfx_temp)

    # ---- 完成 ----
    separator()
    print("=" * 60)
    print(f"  打包完成！")
    print(f"  输出：{OUTPUT_DIR}\\{output_name}")
    print(f"  大小：{output_size / 1024 / 1024:.2f} MB")
    print(f"  临时目录：%TEMP%\\{temp_folder}")
    print(f"  自动清理：程序关闭后自动删除")
    print("=" * 60)
    safe_input("\n按回车键退出...")


if __name__ == "__main__":
    main()
