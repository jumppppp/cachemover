# cachemover

[![CI](https://github.com/jumppppp/cachemover/actions/workflows/ci.yml/badge.svg)](https://github.com/jumppppp/cachemover/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cachemover.svg)](https://pypi.org/project/cachemover/)
[![Python versions](https://img.shields.io/pypi/pyversions/cachemover.svg)](https://pypi.org/project/cachemover/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#platform-support)

**Find out where your development tools actually keep their caches — then move
them to one directory using only official mechanisms.**

`cachemover` is a small, dependency-free CLI. It reads a reviewable TOML catalog
of *official* relocation mechanisms (documented environment variables and
official config files), reports what is on disk, and — only after you review
the generated plan — rewrites **user-level** settings so the tools look
somewhere else instead.

It never deletes anything and never moves your data. Migrating bytes is your
call; this tool only redirects where tools look.

```console
$ cachemover scan --drive C
状态              占用      来源        工具 / 路径
--------------------------------------------------------------------------
movable           0 B      default     Go（模块缓存）  C:\Users\me\go\pkg\mod
running           0 B      default     uv（包与解释器缓存）  C:\Users\me\AppData\Local\uv\cache
                                       └─ 有进程正在运行，默认跳过
missing           —        default     npm（cacache）  C:\Users\me\AppData\Local\npm-cache
no-official-way   0 B      default     SynthCut by Relo  C:\Users\me\.aive
                                       └─ 官方没有提供重定向机制
```

## Why this exists

Developer caches grow silently — a model hub, a browser-per-test-tool, a video
editor's proxy media — until a 250 GB system drive is full. The information you
need (which variable, which config key, which doc) is scattered across dozens
of vendor sites, and there is no maintained tool that both *detects* the
locations and *relocates* them by the book.

`cachemover` fixes that with a catalog whose every executable entry must cite its
official documentation URL — the loader **rejects** entries without one, so the
catalog cannot silently drift into guessing.

## Install

```bash
pip install cachemover
```

Optional extras:

```bash
pip install "cachemover[yaml]"   # rewriting YAML configs (e.g. conda .condarc)
pip install "cachemover[dev]"    # pytest, tomli (for Python < 3.11)
```

From a clone:

```bash
git clone https://github.com/jumppppp/cachemover
cd cachemover
pip install -e ".[dev]"
```

Requires **Python 3.9+**. Python 3.10 needs `tomli`; 3.11+ uses stdlib `tomllib`.

## Quick start

```console
$ cachemover scan                      # what is where, how big, in which state
$ cachemover scan --drive C            # only entries physically on C:
$ cachemover plan --target R:\Caches   # migration plan — writes nothing
$ cachemover plan --target R:\Caches -o plan.json
$ cachemover apply -p plan.json        # dry-run: prints exactly what would change
$ cachemover apply -p plan.json --apply  # execute (backs up first)
$ cachemover verify                    # re-read the environment, compare with target
$ cachemover undo --backup <dir>       # roll back an apply from its backup dir
```

A plan separates what it *will* do from what it only *reports*:

```console
$ cachemover plan --target 'R:\Caches'
目标目录: R:\Caches   条目: 39   可执行: 13   仅报告: 26

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

## Commands

| command | what it does |
|---|---|
| `cachemover scan` | list every known cache: effective path, size, source, state |
| `cachemover plan` | build a migration plan (writes nothing) |
| `cachemover apply` | execute a plan — **dry-run unless `--apply`**, backs up first |
| `cachemover verify` | re-read the environment and compare against the target |
| `cachemover export` | dump the whole catalog (`--format json` for tooling) |
| `cachemover undo` | restore an apply from its backup directory |

Common options: `--target <dir>` (default `R:\Caches`), `--catalog <dir>`,
`--category dev|gui`, `--no-size`, `--drive C`.

## Safety model

* **Dry-run by default.** Nothing is written until you pass `--apply`.
* **User scope only.** The only hive ever written is `HKCU\Environment`
  (machine scope is read-only). No admin rights required, nothing system-wide.
* **Backup first.** Every apply dumps both environment keys as `.reg`, the plan
  itself, and an `env-before.json` snapshot into `<backup_root>/<timestamp>/`.
  `cachemover undo --backup <that dir>` restores it exactly.
* **Never deletes, never moves data.** Relocating the actual bytes is your job
  (`robocopy` / `move`); `apply` refuses to run if the target directory for an
  entry does not already exist.
* **Running apps are skipped** unless you pass `--force`.
* **Junction relocation is refused by default.** It is never an official
  mechanism, so it requires `--allow-destructive`, an interactive terminal, and
  an existing backup directory — and even then the guard rails only allow an
  explicit, confirmed action.

## Supported entries

39 entries ship in `src/cachemover/data/*.toml`, grouped by ecosystem:

| file | covers |
|---|---|
| `dev-python.toml` | pip, uv, uv tool, pipx, Poetry, conda, Jupyter, matplotlib, Hugging Face, PyTorch Hub, ModelScope |
| `dev-rust.toml` | Cargo, rustup |
| `dev-go.toml` | GOCACHE, GOMODCACHE, GOPATH |
| `dev-node.toml` | npm, Yarn, pnpm, Electron, Playwright, Puppeteer |
| `dev-ml.toml` | Ollama models, Keras |
| `dev-misc.toml` | NuGet, Gradle, Maven, ccache, Android SDK/AVD, VS Code |
| `gui-windows.toml` | SynthCut, WeChat, JianyingPro, LM Studio, WorkBuddy, Lingma, Chrome — **report-only** (no official mechanism) |

## Catalog format

```toml
[[app]]
id = "pip"
name = "pip (download cache)"
category = "dev"                       # dev | gui
platforms = ["windows", "macos", "linux"]
official_doc = "https://pip.pypa.io/en/stable/topics/caching/"
risk = "low"                           # low | medium | high
notes = "…"
processes = ["python.exe"]             # optional: running-app detection

detect.env = ["PIP_CACHE_DIR"]         # checked first, in order
detect.windows = "%LOCALAPPDATA%\\pip\\Cache"
detect.macos = "~/Library/Caches/pip"
detect.linux = "~/.cache/pip"

redirect.method = "env_var"            # env_var | config_file | none
redirect.env_name = "PIP_CACHE_DIR"
redirect.scope = "user"
redirect.value_template = "{target}\\pip"
```

| field | meaning |
|---|---|
| `official_doc` | **required** for `env_var` / `config_file`; the loader rejects entries without it |
| `redirect.method` | `env_var` / `config_file` are executable; `none` means "report only" |
| `redirect.value_template` | target path, with `{target}` substituted |
| `redirect.config_path` / `config_key` / `config_format` | for `config_file` (`yaml` / `ini`) |

> **TOML gotcha:** `processes` (and any scalar) must appear **before** the first
> `detect.` / `redirect.` dotted key, otherwise it lands inside that sub-table.
> The loader will then treat it as a missing field.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The suite runs on Windows and Linux (non-Windows runs degrade registry access to
"not set" so detection logic stays testable).

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a catalog entry, and
[docs/DESIGN.md](docs/DESIGN.md) for the design decisions and guard rails.

## Platform support

Windows is the implemented platform: registry access, `%VAR%` expansion and
config writing are Windows-specific. macOS/Linux defaults are already carried in
the catalog so adding those platforms later does not change the data model.

## License

[MIT](LICENSE)