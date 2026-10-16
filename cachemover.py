#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cachemover 命令入口。

    python cachemover.py scan                      # 缓存都在哪、多大、什么状态
    python cachemover.py plan --target R:\\Caches  # 生成迁移计划（不写盘）
    python cachemover.py apply -p plan.json        # dry-run
    python cachemover.py apply -p plan.json --apply  # 执行（先备份）
    python cachemover.py verify
    python cachemover.py junction --help           # 兜底方案（NTFS junction）

代码按职责拆在 libs/ 下，本文件只负责把入口接起来：

    libs/catalog.py        清单（40 条）与字段校验
    libs/detect.py         检测缓存位置、占用与状态
    libs/sizing.py         目录体积统计
    libs/winenv.py         Windows 环境变量与注册表读写
    libs/plan.py           迁移计划、执行、备份与回滚
    libs/junction.py       NTFS junction 底层操作
    libs/migrate.py        兜底迁移（复制 → 双向校验 → 改名 → 记账）
    libs/cli.py            命令行入口与各子命令
    libs/cli_junction.py   junction 子命令组
    libs/data/*.toml       清单源文件（按生态分组，可直接编辑）
"""
import sys
from pathlib import Path

# 把项目根目录加入模块搜索路径，这样从任何目录调用本脚本都能找到 libs。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from libs.cli import main  # noqa: E402  （必须在 sys.path 调整之后导入）

if __name__ == "__main__":
    raise SystemExit(main())