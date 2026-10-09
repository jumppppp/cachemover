# Security Policy

## What cachemover does — and deliberately does not do

`cachemover` modifies where your tools look for data, so it is worth being
explicit about its blast radius.

**It does:**

* read environment variables from the process, `HKCU\Environment` and
  `HKLM\...\Session Manager\Environment` (read-only for the machine hive);
* write **only** user-scope values under `HKCU\Environment` (`REG_EXPAND_SZ`);
* write official config files (YAML / `key=value` ini) for `config_file`
  entries, after copying `*.bak` next to the original;
* export `HKCU`/`HKLM` environment keys to `.reg` files as a backup before any
  write, plus an `env-before.json` snapshot of every variable it touches;
* walk directories to compute sizes, skipping reparse points so junctions are
  never followed.

**It does not:**

* delete files or directories — under any flag;
* move or copy your cached data (that is your `robocopy`/`move`, on purpose);
* write to the machine hive, or require administrator rights;
* modify an application's own settings; GUI apps without an official mechanism
  are reported only, never touched;
* create junctions automatically. Junction relocation requires
  `--allow-destructive`, an interactive terminal, and an existing backup
  directory, and is refused in non-interactive runs;
* send anything over the network.

## Running it safely

* `apply` is a dry-run unless you pass `--apply`.
* Review a plan (`cachemover plan -o plan.json`) before applying it.
* Keep the backup directory: `cachemover undo --backup <dir>` restores the exact
  prior state.

## Reporting a vulnerability

Please open a private security advisory on GitHub
(https://github.com/jumppppp/cachemover/security/advisories/new) rather than a
public issue, and include:

* what you did, what you expected, and what happened;
* the plan JSON and any output (`apply` log, backup directory listing);
* your Windows version and Python version.

Areas of particular interest: any path where a write can happen without an
explicit `--apply`, where a backup could be written outside `--backup-root`,
where a delete/move could be triggered, or where a junction could be created or
removed without the guard rails holding.