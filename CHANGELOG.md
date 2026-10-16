# 更新日志

本文件记录本项目所有值得注意的变更。

## [未发布]

### 变更

- **单文件化**：原来的 `src/cachemover/` 包 + `pyproject.toml` 打包结构，合并为
  一个可直接运行的脚本 **`cachemover.py`**。不再是 Python 库，不需要 `pip install`，
  也没有 `src/`、`*.egg-info` 这类包结构。
- **零依赖**：40 条重定向清单由原来的 `src/cachemover/data/*.toml` 在构建时转成
  Python 字面量内嵌进脚本（`BUILTIN_CATALOG`），因此默认路径不需要任何 TOML
  解析库，Python 3.9+ 可直接运行。需要把清单放在外部维护时，仍可用
  `--catalog <目录>` 读取该目录下的 `*.toml`。
- **修复一个真实 bug**：`junction scan` 之前会错误地执行顶层的 `scan`，报
  `AttributeError: 'Namespace' object has no attribute 'drive'`。原因是
  `cli.py` 与 `cli_junction.py` **各自定义了一个 `cmd_scan`**，单文件化后互相
  覆盖。现已把 junction 的那个改名为 `cmd_junction_scan`。
- **描述中文化**：README、本更新日志以及各模块的说明文字改为中文。
- 删除已不再适用的文件：`pyproject.toml`、`MANIFEST.in`、`CONTRIBUTING.md`、
  `SECURITY.md`（安全边界已并入 README）。

### 删除

- PyPI 发布流程 —— 本项目是直接从源码运行的脚本，不发布到 PyPI。

## [0.1.0] - 2026-10-05

首个版本。Windows 优先，只做「报告 + 重定向」。

### 新增

- **清单** —— 40 条条目，覆盖 Python、Rust、Go、Node、ML、.NET/Java/Android 与
  Windows GUI 应用。每条可执行条目都必须给出 `official_doc` 文档链接，加载器会
  拒绝没有文档的条目。
- **`scan`** —— 每个已知缓存的真实路径、来源（`env:` / `default`）、占用、文件数
  与状态；支持 `--json`、`--no-size`、`--drive C`。
- **`plan`** —— 把可执行动作与只报告条目分开，并逐条解释跳过原因；`-o` 可把计划
  保存为 JSON。
- **`apply`** —— 默认 dry-run；`--apply` 会在写入前导出两个环境变量注册表键，并
  保存计划与 `env-before.json` 快照；支持 `--only`、`--force`、`--backup-root`。
- **`verify`** —— 重新读取环境并输出 `[OK]` / `[MISS]` / `[N/A]`，区分"仍在 C 盘"
  与"已搬到别处但没统一"，以及用户级与机器级。
- **`export`** —— 导出完整清单（文本或 JSON）。
- **`undo`** —— 从备份目录回滚一次 apply。
- **`junction` 子命令** —— 兜底迁移：`scan` 找出现存 junction（绝不进入链接内部）、
  `list` 查看账本、`status` 体检每个链接（消失 / 目标不可达 / 指向别处 / 体积漂移）、
  `add` 迁移（默认 dry-run，源目录只被**改名**为影子副本，切换前先双向校验文件数与
  字节数）、`restore`（瞬时无损还原）、`cleanup`（删除影子副本以释放空间）。
  一切记录在 `%USERPROFILE%\.cachemover\manifest.json`。
- **护栏** —— junction 迁移需要 `--allow-destructive`、交互式终端与已存在的备份
  目录三者同时满足；非交互运行一律拒绝。