"""
================================================================================
【文献与网上资料结论（简要）】
--------------------------------------------------------------------------------
检索公开网页与维基后：目前几乎找不到面向《名侦探柯南》、且对全体角色做过
「逐镜头累计出场时长（分钟）」并公开发布的权威数据集。常见可得的是：
  • 柯南百科 / Detective Conan Wiki：按话数、TV 集、登场形式（远影 / 回忆等）
    的条目列表；
  • DC Wiki 「Appearances」页：统计漫画话数、TV 集数、剧场版次数等，
    仍不是音视频逐帧对齐后的「时长」。

因此无法用网上数据做严格的「分钟级」相等匹配。本脚本采用可操作的对照口径：
【剧情档位相近 + 维基「登场条目」量级同属配角线】的一批角色，再在 B 站按
【官方视频标签 Tag】拉取播放量、评论数、发布时间（与 tag_statistics.py 相同）。

若需严格时长，只能自建：逐集字幕时间轴 / 镜头跟踪，不在本脚本范围内。
================================================================================

用法：
  cd crawl
  python conan_character_tag_batch.py

环境变量同 tag_statistics.py（TAG_PAGE_SIZE、REQUEST_DELAY_S）。
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys

from tag_statistics import run_tag_jobs

# （B站标签中文名，输出文件名）—— 与 character_tag_selection_meta.csv 对应
COMPARE_TAG_JOBS: list[tuple[str, str]] = [
    ("松田阵平", "tag_stats_batch_松田阵平.csv"),
    ("萩原研二", "tag_stats_batch_萩原研二.csv"),
    ("伊达航", "tag_stats_batch_伊达航.csv"),
    ("诸伏景光", "tag_stats_batch_诸伏景光.csv"),
    ("茱蒂", "tag_stats_batch_茱蒂.csv"),
    ("詹姆斯布莱克", "tag_stats_batch_詹姆斯布莱克.csv"),
    ("卡迈尔", "tag_stats_batch_卡迈尔.csv"),
]


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


_configure_stdio_utf8()


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    jobs = [
        (tag, os.path.normpath(os.path.join(root, fname)))
        for tag, fname in COMPARE_TAG_JOBS
    ]

    meta = os.path.join(root, "character_tag_selection_meta.csv")
    if os.path.isfile(meta):
        print(f"选取说明见：{meta}\n")

    asyncio.run(run_tag_jobs(jobs))


if __name__ == "__main__":
    main()
