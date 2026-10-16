# cachemover

**搞清楚开发工具到底把缓存藏在哪，然后只用官方机制把它们统一到一个目录。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#依赖与版本)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#平台支持)

一个**单文件 Python 脚本**（`cachemover.py`）：不需要安装、不需要建虚拟环境、
不需要 `pip install`，也不依赖任何第三方库。它内置一份可审阅的重定向清单
（40 条，覆盖 Python / Rust / Go / Node / ML / .NET / Java / Android / GUI 应用），
查出每个缓存的**实际位置与实际占用**，并且——只有在你确认计划之后——才去改写
**用户级**设置，让工具换个地方找数据。

它**从不删除任何东西，也不搬动你的数据**。搬字节是你自己的决定，这个脚本只负责
把"工具去哪里找缓存"改掉。

```console
$ python cachemover.py scan --drive C
状态              占用      来源        工具 / 路径
--------------------------------------------------------------------------
movable           0 B      default     Go（模块缓存）  C:\Users\me\go\pkg\mod
running           0 B      default     uv（包与解释器缓存）  C:\Users\me\AppData\Local\uv\cache
                                       └─ 有进程正在运行，默认跳过
missing           —        default     npm（cacache）  C:\Users\me\AppData\Local\npm-cache
no-official-way   0 B      default     SynthCut by Relo  C:\Users\me\.aive
                                       └─ 官方没有提供重定向机制
```

## 为什么需要它

开发缓存是悄悄长大的：一个模型仓库、一个每次测试都下载浏览器的工具、一个视频
编辑器的代理素材……直到 250 GB 的系统盘满了。而你需要的信息（哪个变量、哪个配置
项、哪份文档）散落在几十个厂商网站上，也没有一个现成工具能既**查清位置**又**按规范
搬迁**。

`cachemover` 用一份**清单**解决这件事：每条可执行条目都必须给出 `official_doc`
文档链接，加载器会**拒绝**没有文档背书的条目，所以这份清单不会悄悄退化成猜测。

## 快速开始

不需要安装，直接跑脚本（要求 **Python 3.9+**，零依赖）：

```bash
git clone https://github.com/jumppppp/cachemover
cd cachemover
python cachemover.py scan                        # 缓存都在哪、多大、什么状态
python cachemover.py scan --drive C              # 只看物理落在 C: 上的条目
python cachemover.py plan --target R:\Caches     # 生成迁移计划（不写任何东西）
python cachemover.py plan --target R:\Caches -o plan.json
python cachemover.py apply -p plan.json          # dry-run：只打印"将要改什么"
python cachemover.py apply -p plan.json --apply  # 执行（先自动备份）
python cachemover.py verify                      # 重新读取环境，核对是否已指向目标
python cachemover.py undo --backup <备份目录>     # 从备份回滚一次 apply
```

Windows 下想更省事，可以放一个 bat 在旁边：

```bat
@echo off
python "%~dp0cachemover.py" %*
```

## 命令

| 命令 | 作用 |
|---|---|
| `cachemover.py scan` | 列出每个已知缓存：实际路径、占用、来源、状态 |
| `cachemover.py plan` | 生成迁移计划（**不写盘**） |
| `cachemover.py apply` | 执行计划——**默认 dry-run**，加 `--apply` 才写入，且一定先备份 |
| `cachemover.py verify` | 重新读取环境并与目标目录比对 |
| `cachemover.py export` | 导出完整清单（`--format json` 供程序消费） |
| `cachemover.py undo` | 用备份目录回滚一次 apply |
| `cachemover.py junction …` | **兜底方案**：官方没有任何机制的应用，用 NTFS junction 搬 |

通用选项：`--target <目录>`（默认 `R:\Caches`）、`--catalog <目录>`（改用外部 TOML
清单，默认用脚本内嵌清单）、`--category dev|gui`、`--no-size`、`--drive C`。

计划会把"要执行的"和"只报告的"分开说清楚：

```console
$ python cachemover.py plan --target 'R:\Caches'
目标目录: R:\Caches   条目: 40   可执行: 7   仅报告: 33

工具                       机制        风险      当前 → 目标
-------------------------------------------------------------------------------
pip（下载缓存 / HTTP cache） env_var    low      C:\Users\me\AppData\Local\pip\Cache → R:\Caches\pip
                                                          └─ 官方提供 --cache-dir 命令行参数、global.cache-dir 配置项与 PIP_CACHE_DIR 环境变量
rustup（工具链目录）          env_var    high     C:\Users\me\.rustup → R:\Caches\rustup
                                                          └─ RUSTUP_HOME 里是编译好的 toolchain：单独改它会让 rustc/cargo 立刻报 no installed toolchains

不执行（原因）：
  · Go（构建缓存）            [already-moved] 已经在目标位置
  · npm（cacache）           [missing] 目录不存在，无需迁移
```

## 安全模型

* **默认 dry-run。** 不加 `--apply` 什么都不会写。
* **只动用户级。** 唯一会被写入的注册表位置是 `HKCU\Environment`（机器级只读）。
  不需要管理员权限，不改动全系统。
* **先备份。** 每次 apply 都会把两个环境变量注册表键导出为 `.reg`、把计划本身
  和 `env-before.json` 快照一起写进 `<备份根>/<时间戳>/`，`undo` 可精确还原。
* **不删文件、不搬数据。** 真实数据的搬迁交给你（`robocopy` / `move`）；
  如果某个条目的目标目录还不存在，`apply` 会直接拒绝执行。
* **正在运行的程序默认跳过**，除非显式加 `--force`。
* **junction 迁移默认拒绝。** 它从来不是官方机制，所以必须同时满足
  `--allow-destructive`、交互式终端、已存在的备份目录三个条件才会执行。

## 兜底方案：NTFS junction

有些应用**根本没有**官方重定向机制——它们把路径硬编码在用户目录下（视频编辑器的
`~/.aive`、聊天客户端的 `%APPDATA%`、IDE 的扩展缓存）。只对这些应用，`cachemover`
可以退回到 NTFS **junction**：原路径变成一个 reparse point，由文件系统透明重定向，
于是**所有**程序都会跟着走，不需要任何程序配合。

因为它不是厂商文档化的机制，所以永远不会自动执行：

```bash
python cachemover.py junction scan                        # 识别：列出现存 junction
python cachemover.py junction add --path %USERPROFILE%\.lingma --process lingma.exe          # dry-run
python cachemover.py junction add --path %USERPROFILE%\.lingma --process lingma.exe --yes    # 执行
python cachemover.py junction list                        # 记账：账本内容
python cachemover.py junction status                      # 体检：每个链接是否健康
python cachemover.py junction restore --id lingma --yes   # 还原：瞬时且无损
python cachemover.py junction cleanup --id lingma --yes   # 释放空间：删掉影子副本
```

**为什么它是安全的**

| 保证 | 做法 |
|---|---|
| 迁移过程中不删任何东西 | 源目录被**改名**为影子目录（`<名字>.cachemover-old-<时间戳>`）——同盘 O(1) 元数据操作，不占额外空间 |
| 切换前先校验 | 复制结果双向比对文件数与字节数 |
| 瞬时、无损还原 | `rmdir` 掉链接，把影子目录改回原名；数据从未离开原盘 |
| 记账而不是靠记忆 | 每次迁移都追加到 `%USERPROFILE%\.cachemover\manifest.json` |
| 不安全就拒绝 | 进程在跑、目标不是本机固定磁盘、目标非空、空间不足都是硬错误 |
| 绝不递归删除 | 删链接只用 `cmd /c rmdir` |

> ⚠️ **永远不要用递归删除去删 junction。** `Remove-Item -Recurse`、`rmdir /s`、
> `del /s` 会**穿透**链接，把目标盘上的真实数据删掉。永远用 `rmdir <链接>`，
> 或者交给 `cachemover junction restore`。

`junction status` 还会抓出真正要紧的故障：链接消失（`broken`）、链接目标不可达
（`broken-target`）、指向了别处（`wrong-target`）、以及体积与账本不一致。

## 内置清单（40 条）

清单直接写在 `cachemover.py` 的 `BUILTIN_CATALOG` 里，按生态分组：

| 分组 | 覆盖 |
|---|---|
| Python | pip、uv、uv tool、pipx、Poetry、conda、Jupyter、matplotlib、Hugging Face、PyTorch Hub、ModelScope |
| Rust | Cargo、rustup |
| Go | GOCACHE、GOMODCACHE、GOPATH |
| Node | npm、Yarn、pnpm、Electron、Playwright、Puppeteer |
| ML | Ollama 模型、Keras |
| 其他开发工具 | NuGet、Gradle、Maven、ccache、Android SDK/AVD、VS Code |
| AI 工具 | OpenAI Codex CLI（`CODEX_HOME`） |
| Windows GUI | SynthCut、微信、剪映专业版、LM Studio、WorkBuddy、通义灵码、Chrome —— **只报告**（官方无机制） |

`python cachemover.py export --format json` 可以拿到机器可读的完整清单。

## 如何新增一条

清单是脚本里的一个 Python 列表，每条长这样：

```python
{
    "id": "pip",
    "name": "pip（下载缓存 / HTTP cache）",
    "category": "dev",                     # dev | gui
    "platforms": ["windows", "macos", "linux"],
    "official_doc": "https://pip.pypa.io/en/stable/topics/caching/",
    "risk": "low",                         # low | medium | high
    "notes": "官方提供 --cache-dir、global.cache-dir 与 PIP_CACHE_DIR",
    "processes": ["python.exe"],            # 可选：用于判断"正在运行"
    "detect": {                             # 先查 env，再按平台默认值
        "env": ["PIP_CACHE_DIR"],
        "windows": "%LOCALAPPDATA%\\pip\\Cache",
        "macos": "~/Library/Caches/pip",
        "linux": "~/.cache/pip",
    },
    "redirect": {                           # env_var | config_file | none
        "method": "env_var",
        "env_name": "PIP_CACHE_DIR",
        "scope": "user",
        "value_template": "{target}\\pip",
    },
}
```

规则：

* `method` 为 `env_var` / `config_file` 时，**必须**有 `official_doc`，否则加载器
  直接报错——这是防止清单退化成猜测的硬约束；
* `method` 为 `none` 表示"只报告位置，永不出现在可执行计划里"；
* `config_file` 需要额外给 `config_path` / `config_key` / `config_format`
  （目前支持 `yaml` 与 `ini`，`xml` 只报告不改写）。

如果想把这些条目放在**外部 TOML 文件**里维护，用 `--catalog <目录>` 指向目录即可
（需要一个 TOML 解析器：Python 3.11+ 自带，3.10 及以下 `pip install tomli`）。
注意 TOML 版本的排序陷阱：`processes` 这类标量必须写在第一个 `detect.` /
`redirect.` 点号键**之前**，否则会被塞进子表里、被当成字段缺失。

## 平台支持

Windows 是当前实现的平台：注册表读写、`%VAR%` 展开、配置文件改写都是 Windows 专属。
macOS / Linux 的默认路径已经写在清单里，所以以后要支持这些平台，数据模型不用改。

## 依赖与版本

* 默认路径：**零依赖**，Python 3.9+ 直接运行（40 条清单已内嵌在脚本里）。
* 只有用 `--catalog` 读外部 TOML 清单时才需要 TOML 解析器（Python 3.11+ 自带，
  或 `pip install tomli`）；只有 conda 的 `.condarc`（YAML）改写才需要 `PyYAML`。

## 许可

[MIT](LICENSE)