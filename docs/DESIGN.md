# devcache — 设计与范围（草案 v0.1）

## 1. 目标

一个 Python CLI，做两件事：

1. **检测**：各开发工具与桌面应用当前实际使用的缓存/数据目录在哪、占多少、是否已重定向。
2. **重定向**：**只按官方机制**把它们改到统一目录（如 `R:\Caches`），并支持回滚。

范围优先级：**本机已装软件必须全覆盖**（见下方清单），其次覆盖市面主流常用软件。

## 2. 数据模型：catalog 条目

每个软件一条记录（TOML，便于人工审阅与 PR 贡献）：

```toml
[[app]]
id = "codex"                     # 唯一标识
name = "OpenAI Codex CLI"
platforms = ["windows", "macos", "linux"]
category = "dev"                 # dev | gui

[app.detect]
# 解析「当前生效路径」的规则，按顺序取第一个命中
env = ["CODEX_HOME"]             # 优先读环境变量
windows_default = "%USERPROFILE%\\.codex"
macos_default   = "~/.codex"
linux_default   = "~/.codex"

[app.redirect]
method = "env_var"               # env_var | config_file | none
env_name = "CODEX_HOME"
env_scope = "user"               # 只写用户级，绝不动系统级
value_template = "{target}\\.codex"

[app]
official_doc = "https://developers.openai.com/codex/config-reference"
risk = "low"                     # low | medium | high
notes = "改后新开会话生效；旧目录数据需自行迁移"
```

`method = "none"` 表示官方无重定向机制 —— **只报告，不提供 apply**。

## 3. 检测逻辑

1. 读环境变量：进程环境 + 注册表 `HKCU\Environment` 与 `HKLM\...\Environment` 两级。
2. 无变量则套平台默认模板（`%APPDATA%`、`%LOCALAPPDATA%`、`%USERPROFILE%`、`~`）。
3. 统计体积：文件数 + 字节数（跳过 reparse point，避免 junction 死循环）。
4. 与 `--target` 比对，判定状态：`already-moved` / `movable` / `no-official-way` / `running`。

## 4. 重定向逻辑（安全第一）

- 只写**用户级**环境变量（`HKCU\Environment`）或**用户级**配置文件。
- **默认 dry-run**：只打印将要执行的变更，不落盘。
- `--apply` 才写入；写入前自动备份（env → 导出 `.reg`；配置文件 → 复制 `.bak`）。
- **绝不删除任何文件**。源目录清理由用户手动执行，或 `--allow-destructive` 显式开启且逐项确认。
- 运行中的应用默认跳过（可 `--force` 覆盖，但会警告）。

## 5. CLI 命令

| 命令 | 作用 |
|---|---|
| `devcache scan` | 扫描并列出所有已知软件的缓存位置、占用、当前状态 |
| `devcache scan --json` | 同上，机器可读输出 |
| `devcache plan --target R:\Caches` | 生成迁移计划（含每条目的官方机制与风险），不落盘 |
| `devcache plan --target R:\Caches -o plan.json` | 计划导出为 JSON |
| `devcache apply -p plan.json` | 执行计划（仍默认 dry-run） |
| `devcache apply -p plan.json --apply` | 真正写入（先备份） |
| `devcache verify` | 核对生效状态（重读 env/配置并与计划比对） |
| `devcache export --format json` | 导出完整清单（供其他脚本/CI 使用） |
| `devcache undo --backup <dir>` | 从备份回滚环境变量与配置文件 |

## 6. 安全机制（对应用户「备份完整、再三确认」的要求）

- 默认 dry-run；危险动作需要 `--allow-destructive` **且**逐项交互确认。
- 每次 apply 前：`<backup_root>/<timestamp>/` 下保存 env `.reg`、被改的配置文件副本、计划 JSON。
- `undo` 可完整还原到 apply 前状态。
- 全流程支持 JSON 输出，便于审计与自动化测试。

## 7. 已确定的决策

1. **CLI 名称**：`devcache`（同时作为 PyPI 包名、命令行名、GitHub 仓库名）。
2. **纳入 junction**，但**默认关闭**：仅当显式 `--allow-destructive` 且在交互模式下逐项确认时才执行；
   执行前必须已生成备份；非交互（CI/管道）环境下该功能一律拒绝执行。
3. **只实现 Windows**；catalog 条目仍保留 `platforms`、`macos_default`、`linux_default` 字段，
   实现层用平台分支，后续补 macOS/Linux 时不必改数据结构。

### 由此产生的设计约束

- `detect` 与 `redirect` 都按 `platforms` 分发，Windows 分支读注册表（`HKCU\Environment`、
  `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`）。
- junction 相关代码独立成模块，默认不导入执行路径；单元测试对 dry-run 与拒绝路径做覆盖。
