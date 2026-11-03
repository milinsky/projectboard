# Projectboard

[English](README.md) | [Русский](README.ru.md) | **简体中文**

本地项目桌面仪表盘（macOS，Python 3.14 + PySide6）：扫描项目根目录（默认为
`~/Projects`），找出含有自身 `README.md` 的文件夹（最上层 README 优先），并以主从
视图展示——左侧是可搜索的项目表格，右侧是渲染后的 README，并提供
**在 ZCode 中打开** 按钮。

## 功能

- 扫描可配置的项目根目录（默认 `~/Projects`，最大深度 8）
- 项目 = 含有自身 `README.md` 的文件夹，最上层 README 优先
- 主从界面：可搜索的项目表格 + 渲染后的 README 预览
- 为选中的项目提供 **在 ZCode 中打开** 按钮
- 按需索引（按钮触发）并带 JSON 索引缓存——启动时不扫描
- 界面支持俄语、英语和简体中文
- 以 macOS 应用包形式安装：**Projectboard.app**

## 环境要求

- macOS、Python 3.14（`python3.14`）

## 安装

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 运行

两种方式。

开发模式——在项目根目录下运行：

```bash
.venv/bin/python main.py
```

日常使用——从 /Applications 双击启动 Projectboard.app 应用。
首次启动可能需要右键点击 → “打开”
（参见[未签名应用的首次启动](#未签名应用的首次启动)）。

## 构建并安装应用（Projectboard.app）

该脚本构建 Projectboard.app 并安装到 /Applications。在项目根目录下运行，
无需参数。前提条件：应用程序已关闭。重复运行会完整重建并更新已安装的应用。

```bash
./scripts/build_app.sh
```

## 未签名应用的首次启动

应用包不进行签名（签名与公证不在本项目范围内）。本地构建的应用包通常不会
携带隔离属性，双击即可启动。如果 Projectboard.app 无法通过双击启动（例如仓库
被下载或移动后 macOS 给应用包标记了隔离属性）——首次启动：右键点击
Projectboard.app → “打开”。

## 更新应用

更新代码后，请重新构建并安装应用：

```bash
git pull
./scripts/build_app.sh
```

如果项目文件夹被移动或重命名，启动器（使用绝对路径）将找不到项目文件，
应用无法启动。解决方法：在项目文件夹中打开终端并运行 `scripts/build_app.sh`
——应用包将按最新路径重新构建。

## 测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

## 配置

扫描根目录可在应用窗口中修改（根目录输入框 + “浏览…”）；仅通过“索引”按钮
执行索引。应用数据位于 `data/`（`config.json`——设置，`index.json`——索引缓存）。

## 界面语言

“语言”菜单（系统 / Русский / English / 简体中文）设置界面语言；重启应用后生效。

## 翻译（开发）

源字符串为俄语 `tr()` 字面量。`scripts/update_translations.sh` 重新生成
`translations/*.ts` / `*.qm`（pyside6-lupdate / lrelease），若有未完成的翻译
则报错退出。首次生成 `.ts` 请直接运行 `lupdate`。

## 许可证

Copyright © 2026 Mikhail Ilinsky。

本程序是自由软件：你可以依据 Free Software Foundation 发布的 GNU 通用公共
许可证第 3 版或（自行选择的）任何更高版本重新分发和/或修改它
（SPDX：`GPL-3.0-or-later`）。详见 [LICENSE](LICENSE)。
