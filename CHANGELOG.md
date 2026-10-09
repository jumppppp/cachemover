# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-10-05

First release. Windows-first, report-and-redirect only.

### Added

- **Catalog** — 39 TOML entries in `src/cachemover/data/*.toml` covering Python,
  Rust, Go, Node, ML, .NET/Java/Android and GUI applications. Every executable
  entry must cite an `official_doc` URL; the loader rejects entries without one.
- **`cachemover scan`** — effective path, source (`env:`/`default`), size, file
  count and state for every known tool. `--json`, `--no-size`, `--drive C`.
- **`cachemover plan`** — separates executable actions from report-only entries and
  explains every skip reason. `-o` to persist the plan.
- **`cachemover apply`** — dry-run by default; `--apply` backs up both environment
  keys plus an `env-before.json` snapshot before writing anything. `--only`,
  `--force`, `--backup-root`.
- **`cachemover verify`** — re-reads the environment and reports `[OK]` / `[MISS]`
  / `[N/A]`, distinguishing "still on C:" from "already elsewhere but not
  unified", and user scope from machine scope.
- **`cachemover export`** — full catalog as text or JSON.
- **`cachemover undo`** — restores an apply from its backup directory.
- **Guard rails** — junction relocation requires `--allow-destructive`, an
  interactive terminal and an existing backup directory; it is refused outright
  in non-interactive runs.
- **Tests** — 46 pytest cases covering catalog validation, size accounting
  (including "a junction must not be followed"), detection rules, plan/apply
  dry-run semantics and junction refusal paths.

[Unreleased]: https://github.com/jumppppp/cachemover/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jumppppp/cachemover/releases/tag/v0.1.0