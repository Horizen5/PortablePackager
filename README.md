# PortablePackager - 通用型 EXE 便携版打包工具

将任意 EXE 程序及其关联文件夹封装为一个便携版 EXE，双击即可运行，无需安装。

## 功能特性

- **一键打包**：将软件文件夹拖拽到 `PortablePackager.exe` 上即可生成便携版
- **自动检测**：自动识别主程序、提取图标和版本信息
- **UAC 提权**：自动生成 VBS 提权脚本，支持需要管理员权限的程序
- **自动清理**：解压到临时目录，程序关闭后自动删除
- **完全独立**：内置 7z.exe 和 7z.sfx，不依赖外部 7-Zip 安装

## 使用方法

1. 下载 `PortablePackager.exe`
2. 将任意软件文件夹**拖拽**到 `PortablePackager.exe` 上
3. 等待打包完成，便携版 EXE 自动生成在软件文件夹的上一级目录

### 示例

```
源文件夹结构：
  D:\Software\DDU v18.1.5.3\
    ├── Display Driver Uninstaller.exe
    ├── settings\
    └── ...

操作：将 "DDU v18.1.5.3" 文件夹拖到 PortablePackager.exe 上

输出：
  D:\Software\DDU_v18_1_5_3_Portable.exe  ← 双击即可运行
```

## 工作原理

```
┌─────────────────────────────────────────────────┐
│  PortablePackager.exe                            │
│                                                   │
│  1. 扫描目标文件夹，检测主程序 EXE                 │
│  2. 提取主程序的图标和版本信息                     │
│  3. 生成 VBS 提权脚本（支持 UAC）                 │
│  4. 用 7z 压缩所有文件                            │
│  5. 组装：SFX 模块 + 配置 + 7z 压缩包            │
│  6. 替换图标、嵌入版本信息                        │
│                                                   │
│  输出：单个可运行的 _Portable.exe                  │
└─────────────────────────────────────────────────┘
```

运行便携版时的流程：

```
双击 _Portable.exe
  → SFX 解压到 %TEMP%\软件名\
  → 运行 VBS 提权脚本
  → UAC 弹窗确认
  → 以管理员权限启动主程序
  → 主程序关闭后自动清理临时目录
```

## 技术细节

| 组件 | 说明 |
|------|------|
| SFX 模块 | 7-Zip 自解压模块，负责解压和启动 |
| 7z.exe | 内嵌的 7-Zip 命令行工具，用于创建压缩包 |
| VBS 提权 | 通过 `ShellExecute "runas"` 实现 UAC 提权 |
| 图标提取 | 解析 PE 资源目录，提取 RT_GROUP_ICON |
| 图标替换 | 通过 Windows `UpdateResource` API 写入 |
| 版本信息 | 从源程序提取 VS_VERSION_INFO 并嵌入 |

## 从源码构建

```bash
# 安装依赖
pip install pyinstaller pefile

# 打包为单文件 EXE（需要 7z.sfx、7z.exe、7z.dll 在同目录下）
pyinstaller --onefile --console --name PortablePackager ^
  --icon packager_icon.ico ^
  --add-data "7z.sfx;." ^
  --add-data "7z.exe;." ^
  --add-data "7z.dll;." ^
  build_portable_gui.py
```

## 文件结构

```
PortablePackager/
├── PortablePackager.exe      # 打包工具（拖拽使用）
├── build_portable_gui.py     # 核心脚本源码
├── 7z.sfx                    # SFX 自解压模块
└── README.md                 # 说明文档
```

## 许可证

MIT License
