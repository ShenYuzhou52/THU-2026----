"""
按 B 站「视频标签」抓取标签下全部视频的播放量、评论数、发布时间等。
接口：GET https://api.bilibili.com/x/tag/detail?tag_id=&pn=&ps=

用法：
  python tag_statistics.py

环境变量：
  TAG_PAGE_SIZE  每页条数，默认 20
  REQUEST_DELAY_S 翻页间隔秒，默认 0.45
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from datetime import datetime, timezone, timedelta

import aiohttp

from bilibili_api.video_tag import Tag

# 北京时间展示用
_CN_TZ = timezone(timedelta(hours=8))


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

PAGE_SIZE = max(1, min(50, int(os.environ.get("TAG_PAGE_SIZE", "20") or "20")))
DELAY_S = float(os.environ.get("REQUEST_DELAY_S", "0.45") or "0.45")

TAG_JOBS: list[tuple[str, str]] = [
    ("松田阵平", "stats_tag_matsuda.csv"),
    # 「朱蒂老师」与「朱蒂」为不同标签：前者更贴近口述习惯，后者稿件更多，可按需改 TAG_JOBS。
    ("朱蒂老师", "stats_tag_jodie_sensei.csv"),
]


HEADERS = [
    "标签名",
    "标签ID",
    "BV号",
    "标题",
    "发布时间戳",
    "发布时间_ISO8601_北京时间",
    "播放量",
    "评论数_reply",
    "弹幕数",
    "时长秒",
    "UP主MID",
    "UP主昵称",
    "页码_抓取时",
]


async def resolve_tag_id(tag_name: str) -> int:
    t = Tag(tag_name=tag_name)
    return await t.get_tag_id()


def _safe_ts_iso(ts: int | float | None) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=_CN_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return ""


async def fetch_tag_page(
    session: aiohttp.ClientSession, tag_id: int, pn: int
) -> tuple[list[dict], int]:
    """返回 (本页 archives 列表, 总条数 count)。"""
    url = "https://api.bilibili.com/x/tag/detail"
    params = {"tag_id": tag_id, "pn": pn, "ps": PAGE_SIZE}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    async with session.get(url, params=params, headers=headers) as resp:
        resp.raise_for_status()
        j = await resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"tag/detail 错误: code={j.get('code')} msg={j.get('message')}")
    data = j.get("data") or {}
    news = data.get("news") or {}
    archives = news.get("archives") or []
    total = int(news.get("count") or 0)
    return archives, total


async def crawl_one_tag(
    session: aiohttp.ClientSession,
    tag_name: str,
    out_path: str,
) -> None:
    tag_id = await resolve_tag_id(tag_name)
    print(f"\n==== 标签「{tag_name}」 tag_id={tag_id} → {out_path} ====")

    pn = 1
    total_reported = 0
    rows_written = 0
    seen_bvid: set[str] = set()

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)

        while True:
            archives, total_reported = await fetch_tag_page(session, tag_id, pn)
            if pn == 1:
                print(f"  接口报告该标签下共约 {total_reported} 条稿件（分页抓取）")

            if not archives:
                break

            for arc in archives:
                bvid = arc.get("bvid") or ""
                if not bvid or bvid in seen_bvid:
                    continue
                seen_bvid.add(bvid)
                stat = arc.get("stat") or {}
                owner = arc.get("owner") or {}
                pub = arc.get("pubdate")
                w.writerow(
                    [
                        tag_name,
                        tag_id,
                        bvid,
                        (arc.get("title") or "").replace("\r\n", " ").replace("\n", " "),
                        pub if pub is not None else "",
                        _safe_ts_iso(pub),
                        stat.get("view", ""),
                        stat.get("reply", ""),
                        stat.get("danmaku", ""),
                        arc.get("duration", ""),
                        owner.get("mid", ""),
                        owner.get("name", ""),
                        pn,
                    ]
                )
                rows_written += 1

            print(f"  已写入页 {pn}，本页 {len(archives)} 条，累计去重 {rows_written} 条")

            if len(archives) < PAGE_SIZE:
                break
            pn += 1
            await asyncio.sleep(DELAY_S)

    print(f"  完成：{out_path}，共 {rows_written} 行（表头除外）")


async def run_tag_jobs(jobs: list[tuple[str, str]] | None = None) -> None:
    """执行一组 (B站标签名, 输出csv路径)。jobs 默认使用模块内 TAG_JOBS。"""
    todo = jobs if jobs is not None else TAG_JOBS
    connector = aiohttp.TCPConnector(limit=5)
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for tag_name, fname in todo:
            await crawl_one_tag(session, tag_name, fname)
            await asyncio.sleep(DELAY_S)


async def main_async() -> None:
    await run_tag_jobs()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
