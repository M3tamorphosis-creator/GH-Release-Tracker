# GitHub 下载记录器（GH Release Tracker）

> 双击即用的图形界面工具：**自动记录你在 GitHub 上下载过的软件，并检查它们有没有新版本。**

**中文** · [English](README.en.md)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20x64-lightgrey.svg)]()

> ⬇️ **下载：** [**GH-Release-Tracker.exe**](https://github.com/M3tamorphosis-creator/GH-Release-Tracker/releases/latest)（12 MB，免装 Python，双击即用）

---

## 它是什么

GitHub 官方**没有**"我下载过什么"这个记录页面，你只能自己记。这个工具帮你自动记：

- 你去 GitHub 下载了一个软件（比如 PowerToys）
- 它自动记下：**叫什么、哪个仓库、哪个版本、什么时候下的、存在哪**
- 以后那个仓库出了新版本，点一下就能**知道"该更新了"**

一句话：**你下过啥、要不要更新，它都帮你盯着。**

---

## 完整图文教程（新手照着做）

> 全程鼠标操作，不用敲任何命令。下面每一步都配了**实际界面截图**。

### 第 1 步：双击打开软件

双击文件夹里的 **`GH-Release-Tracker.exe`**。

![第 1 步：打开软件](images/zh-step1-launch.png)

窗口各部分：顶部 5 个按钮是全部功能入口；右上角「打开即开始监听」默认已勾选；中间深色区显示结果；底部状态栏显示当前状态。**打开后它就已经自动开始监听了。**

> 🌐 界面支持**中英双语**，点右上角的「English」按钮即可切换。

> 首次启动会慢 2~3 秒（单文件程序要先解压），属正常现象。

### 第 2 步：点「扫描并记录」，把以前下过的找出来

![第 2 步：扫描并记录](images/zh-step2-scan.png)

等几秒结果就打印出来了：第一行是「本次新记录 6 条、累计 6 条」，下面一条条用**卡片**排版。每张卡片含文件名大小、下载时间、**仓库（owner/repo）和版本**、来源页、保存位置。

卡片里那行 `└─ 复制上面 "owner/repo" 到 GitHub 搜索框即可`，就是提示你把仓库名复制到 GitHub 搜索框。

### 第 3 步：点「查看记录」，随时看全部

![第 3 步：查看记录](images/zh-step3-list.png)

用**鼠标滚轮**或**右侧滑动条**上下翻阅；复制任意一条的仓库名，粘到 GitHub 搜索框就能打开那个项目。

### 第 4 步：点「检查新版本」，看哪些该更新

![第 4 步：检查新版本](images/zh-step4-check.png)

| 标记 | 含义 |
|---|---|
| ✅ 已最新 | 你下的就是最新版，放心 |
| ⬆ 有更新 | 出新版本了，点下面的链接去下载 |
| ⬇ 你下过更新版 | 你下的比 GitHub 上的"最新"还新（比如预发布版） |
| ？ 无法比较 | 版本号格式特殊，比不出来（不影响使用） |

> 上图里 5 个仓库显示「**有更新**」（fzf、vscode、neovim、bat、Ventoy），1 个显示「**已最新**」（PowerToys）。

### 额外：点「导出 JSON」

把全部记录存成一个 JSON 文件（记事本或 Excel 都能打开），方便备份或转发。

> 💡 以上内容也单独保存在同目录的 `新手教程.md` 里，内容一致。

---

## 界面按钮说明

| 按钮 | 作用 |
|---|---|
| **扫描并记录** | 扫一遍下载目录 + 浏览器记录，回填历史下载 |
| **开始监听 / 停止监听** | 常驻监听（默认每 15 秒查一次），新下载自动记录 |
| **查看记录** | 列出所有记录（新→旧），卡片式排版，仓库名单独成行并提示可复制到 GitHub 搜索框 |
| **检查新版本** | 对每个下过的仓库，对照 GitHub 查有没有更新 |
| **导出 JSON** | 把记录存成一个 JSON 文件 |
| ☑ **打开即开始监听** | 勾选后，双击 exe 就自动进入监听 |

输出示例：

```
──────────────────────────────────────────────────────────────────────
  PowerToysUserSetup-0.101.2362.0-x64.exe  282.6 MB
    下载时间 : 2026-09-18 14:06:51
    仓库     : microsoft/PowerToys @ v0.101.2362.0
              └─ 复制上面 "microsoft/PowerToys" 到 GitHub 搜索框即可
    来源页   : https://github.com/microsoft/PowerToys/releases/tag/v0.101.2362.0
    保存于   : C:\Users\你\Downloads\PowerToysUserSetup-...-x64.exe
──────────────────────────────────────────────────────────────────────
```

---

## 文件说明

| 文件 | 说明 |
|---|---|
| `GH-Release-Tracker.exe` | **主程序**。从 [Releases](https://github.com/M3tamorphosis-creator/GH-Release-Tracker/releases/latest) 下载，双击即用，无需安装 Python |
| `README.md` | 本说明文档（**图文教程已内嵌在上面的「完整图文教程」章节**） |
| `新手教程.md` | 上面那份图文教程的单独副本（内容一致，可选） |
| `images/` | 教程用的截图 |
| `gh-release-tracker-gui.pyw` | 图形界面源码（.pyw = 双击无黑窗） |
| `gh-release-tracker.py` | 核心逻辑 + 命令行版（exe 也调用它） |

**数据存在哪**：`C:\Users\你的用户名\.gh-release-tracker\downloads.jsonl`（每行一条 JSON，可用记事本打开）。备份这个文件，换电脑/重装后历史还在。

---

## 常见问题

| 问题 | 解决 |
|---|---|
| 双击提示 "Windows 已保护你的电脑" | 点「更多信息 → 仍要运行」。这是未签名 exe 的常见提示，本程序无恶意代码 |
| 被杀毒软件误报/隔离 | 加到信任区即可；PyInstaller 打包的程序偶尔被误报 |
| 首次启动慢 | 单文件程序启动时要解压，之后正常 |
| 数据在哪 | 见上文"文件说明"里的 `downloads.jsonl` |
| 换电脑怎么迁移 | 拷贝 `downloads.jsonl` 到新电脑同名目录即可 |

---

## 进阶：命令行版

图形界面底层就是命令行版，想用脚本/定时任务时可用：

```bash
python gh-release-tracker.py            # 自动模式（扫描记录→输出→继续监听）
python gh-release-tracker.py scan       # 一次性回填历史
python gh-release-tracker.py watch      # 常驻监听
python gh-release-tracker.py list       # 查看记录
python gh-release-tracker.py check      # 检查新版本
```

通用参数：`--log PATH`（记录文件）、`--dirs D1 [D2]`（追加目录）、`--interval N`（监听间隔秒）。

---

## 从源码重新打包成 exe

需要 Python 3.8+ 和 PyInstaller：

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "GH-Release-Tracker" --add-data "gh-release-tracker.py;." "gh-release-tracker-gui.pyw"
```

生成的 exe 在 `dist\GH-Release-Tracker.exe`。

---

## 它是怎么做到的（简要）

程序不依赖 GitHub（GitHub 也不提供个人下载记录），而是从**你电脑本地的两处痕迹**取证：

1. **浏览器下载历史库**（Edge / Chrome 的 `downloads` 表）——有时间、大小、来源页
2. **Windows 文件自带的 Mark-of-the-Web**（`Zone.Identifier` 备用数据流）——记录原始下载链接

两者交叉比对、按路径去重，写入 `downloads.jsonl`。解压产物、已删除文件等噪音会被自动排除。

---

## 🔒 隐私说明（重要）

本项目会访问你电脑上的以下数据，**请先知悉**：

| 访问什么 | 为什么 | 会离开本机吗 |
|---|---|---|
| 浏览器下载历史（Edge / Chrome 等的 `History` 数据库） | 识别你从 GitHub 下载过什么 | ❌ 只读，不外传 |
| 文件的 Mark-of-the-Web 标记（`Zone.Identifier`） | 兜底识别原始下载链接 | ❌ 只读，不外传 |
| `~/.gh-release-tracker/downloads.jsonl` | 保存你的下载记录 | ❌ 只写在本机 |

**唯一的联网行为**：点「检查新版本」时，向 `https://api.github.com/repos/<你下过的仓库>/releases/latest` 发一个 HTTPS GET 请求。

- 除了**仓库名**（它本来就写在 URL 里），**不上传任何其他信息**——不上传你的文件名、路径、下载时间、账号
- 用 `--token` 时，令牌只作为请求头发给 `api.github.com`，**不落盘、不写日志**
- 程序**不会**读取你的密码、Cookie 或任何登录凭据

**记录文件含敏感信息**：`downloads.jsonl` 里有你的完整下载历史和本地路径（含 Windows 用户名）。分享给别人或上传到网上之前，请先处理这个文件。

> 💡 本项目源码完全公开可审计，运行时**只用 Python 标准库**，无第三方依赖，无任何后台上传、埋点或统计行为。

---

## 已知限制

- **已删除的文件可能找不到**：只认"现在还在本机、且有痕迹"的下载
- **非浏览器下载不一定记到**：走浏览器的最稳；某些下载工具若不写来源标记、也不走浏览器，就记录不到
- **Windows 上功能最全**：Mark-of-the-Web 是 Windows 特性，Mac/Linux 只有浏览器记录一条途径
- **版本比较是启发式**：按版本号数字部分比大小，遇到特别不规则的版本号会显示"无法比较"
- **走镜像站的可能认不出仓库**：来源是第三方镜像时，有时解析不出 `owner/repo`

---

## License

MIT
