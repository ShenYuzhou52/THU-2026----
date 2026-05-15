# -*- coding: utf-8 -*-
"""
抓取「名侦探柯南」背景语料与 tag 规模统计。

输出：
  - conan_background_danmaku1-5.csv
  - conan_background_comments1-5.csv
  - conan_tag_stats_名侦探柯南.csv
  - conan_tag_stats_松田阵平.csv
  - conan_background_sample_videos.csv
  - conanpedia_background_text.csv

默认优先走 B 站 tag「名侦探柯南」，失败时退到关键词搜索。
"""
from __future__ import annotations

import asyncio
import csv
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import aiohttp
from bilibili_api import Credential, comment, search, video
from bilibili_api.exceptions import DanmakuClosedException
from bilibili_api.utils.aid_bvid_transformer import bvid2aid
from bilibili_api.video_tag import Tag

from wiki_appearance_stats_conanpedia_zh import (
    fetch_wikitext_batch,
    list_category_character_titles,
)


BASE = Path(__file__).resolve().parent

BACKGROUND_TAG = os.environ.get("CONAN_BACKGROUND_TAG", "名侦探柯南")
TARGET_TAG = os.environ.get("CONAN_TARGET_TAG", "松田阵平")
BACKGROUND_SOURCE = os.environ.get("CONAN_BACKGROUND_SOURCE", "tag_first").strip().lower()
BACKGROUND_PAGES = max(1, int(os.environ.get("CONAN_BACKGROUND_PAGES", "5") or "5"))
TAG_PAGE_SIZE = max(1, min(50, int(os.environ.get("CONAN_TAG_PAGE_SIZE", "20") or "20")))
TAG_STATS_MAX_PAGES = int(os.environ.get("CONAN_TAG_STATS_MAX_PAGES", "0") or "0")
BACKGROUND_SORT_BY = os.environ.get("CONAN_BACKGROUND_SORT_BY", "view_desc").strip().lower()
BACKGROUND_SORT_CANDIDATE_PAGES = int(os.environ.get("CONAN_BACKGROUND_SORT_CANDIDATE_PAGES", "0") or "0")
MAX_COMMENT_PAGES_PER_VIDEO = max(
    0, int(os.environ.get("CONAN_MAX_COMMENT_PAGES_PER_VIDEO", "0") or "0")
)
MAX_COMMENT_PAGE_SAFETY = max(
    1, int(os.environ.get("CONAN_MAX_COMMENT_PAGE_SAFETY", "500") or "500")
)
REQUEST_DELAY_S = float(os.environ.get("REQUEST_DELAY_S", "0.8") or "0.8")
WIKI_CHARACTER_LIMIT = max(0, int(os.environ.get("CONAN_WIKI_CHARACTER_LIMIT", "120") or "120"))
VIDEO_INFO_TIMEOUT_S = float(os.environ.get("CONAN_VIDEO_INFO_TIMEOUT_S", "25") or "25")
DANMAKU_TIMEOUT_S = float(os.environ.get("CONAN_DANMAKU_TIMEOUT_S", "45") or "45")
COMMENT_TIMEOUT_S = float(os.environ.get("CONAN_COMMENT_TIMEOUT_S", "25") or "25")

SESSDATA = os.environ.get("BILI_SESSDATA", "")
BILI_JCT = os.environ.get("BILI_JCT", "")
BUVID3 = os.environ.get("BILI_BUVID3", "")
DEDE_USER_ID = os.environ.get("BILI_DEDEUSERID", "")

if not SESSDATA:
    try:
        from main import BILI_JCT as _MAIN_BILI_JCT
        from main import BUVID3 as _MAIN_BUVID3
        from main import DEDE_USER_ID as _MAIN_DEDE_USER_ID
        from main import SESSDATA as _MAIN_SESSDATA

        SESSDATA = _MAIN_SESSDATA
        BILI_JCT = BILI_JCT or _MAIN_BILI_JCT
        BUVID3 = BUVID3 or _MAIN_BUVID3
        DEDE_USER_ID = DEDE_USER_ID or _MAIN_DEDE_USER_ID
    except Exception:
        pass

credential = Credential(
    sessdata=SESSDATA or None,
    bili_jct=BILI_JCT or None,
    buvid3=BUVID3 or None,
    dedeuserid=DEDE_USER_ID or None,
)


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


def _clean_title(raw: str) -> str:
    return html.unescape((raw or "").replace('<em class="keyword">', "").replace("</em>", ""))


def _comment_text(content: dict | None) -> str:
    if not content:
        return ""
    msg = content.get("message") or ""
    return html.unescape(str(msg)).replace("\r", " ").replace("\n", " ")


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _csv_path(kind: str, page: int) -> Path:
    return BASE / f"conan_background_{kind}{page}.csv"


def init_background_csv(page: int, fresh: bool) -> tuple[Path, Path]:
    dm = _csv_path("danmaku", page)
    cm = _csv_path("comments", page)
    if fresh:
        for p in (dm, cm):
            if p.exists():
                p.unlink()
    if not dm.exists():
        with dm.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["视频标题", "BVID", "分P序号", "弹幕内容"])
    if not cm.exists():
        with cm.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["视频标题", "BVID", "用户名", "评论内容"])
    return dm, cm


async def resolve_tag_id(tag_name: str) -> int:
    return await Tag(tag_name=tag_name).get_tag_id()


async def fetch_tag_page(
    session: aiohttp.ClientSession, tag_id: int, pn: int
) -> tuple[list[dict], int]:
    url = "https://api.bilibili.com/x/tag/detail"
    params = {"tag_id": tag_id, "pn": pn, "ps": TAG_PAGE_SIZE}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept-Encoding": "gzip, deflate",
    }
    async with session.get(url, params=params, headers=headers) as resp:
        resp.raise_for_status()
        j = await resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"tag/detail 错误: code={j.get('code')} msg={j.get('message')}")
    news = ((j.get("data") or {}).get("news") or {})
    return list(news.get("archives") or []), _safe_int(news.get("count"))


async def get_background_page_videos(
    session: aiohttp.ClientSession, page: int
) -> tuple[list[dict], str]:
    if BACKGROUND_SOURCE != "search":
        try:
            tag_id = await asyncio.wait_for(resolve_tag_id(BACKGROUND_TAG), timeout=20)
            archives, _ = await fetch_tag_page(session, tag_id, page)
            if archives:
                return archives, f"tag:{BACKGROUND_TAG}"
        except Exception as exc:
            print(f"[背景] tag 第 {page} 页失败，改用搜索：{exc}")

    result = await asyncio.wait_for(
        search.search_by_type(
            keyword=BACKGROUND_TAG,
            search_type=search.SearchObjectType.VIDEO,
            page=page,
        ),
        timeout=25,
    )
    videos = []
    for item in result.get("result") or []:
        videos.append(
            {
                "bvid": item.get("bvid"),
                "title": _clean_title(item.get("title") or ""),
                "stat": {},
                "duration": item.get("duration") or "",
                "owner": {"name": item.get("author") or ""},
            }
        )
    return videos, f"search:{BACKGROUND_TAG}"


async def get_sorted_background_videos(session: aiohttp.ClientSession) -> tuple[list[dict], str]:
    """按播放量降序选取要抓弹幕评论的柯南 tag 视频。"""
    if BACKGROUND_SOURCE == "search" or BACKGROUND_SORT_BY != "view_desc":
        return [], ""

    tag_id = await asyncio.wait_for(resolve_tag_id(BACKGROUND_TAG), timeout=20)
    wanted = BACKGROUND_PAGES * TAG_PAGE_SIZE
    candidates: list[dict] = []
    seen: set[str] = set()
    page = 1
    while True:
        archives, _ = await fetch_tag_page(session, tag_id, page)
        if not archives:
            break
        for arc in archives:
            bvid = arc.get("bvid") or ""
            if bvid and bvid not in seen:
                seen.add(bvid)
                candidates.append(arc)
        if len(archives) < TAG_PAGE_SIZE:
            break
        if BACKGROUND_SORT_CANDIDATE_PAGES > 0 and page >= BACKGROUND_SORT_CANDIDATE_PAGES:
            break
        if TAG_STATS_MAX_PAGES > 0 and page >= TAG_STATS_MAX_PAGES:
            break
        page += 1
        await asyncio.sleep(REQUEST_DELAY_S)

    candidates.sort(key=lambda x: _safe_int((x.get("stat") or {}).get("view")), reverse=True)
    return candidates[:wanted], f"tag:{BACKGROUND_TAG}:view_desc"


async def fetch_comment_main_page(aid: int, next_page: int) -> dict:
    """新版评论分页接口；旧 x/v2/reply 对部分视频会返回空页。"""
    url = "https://api.bilibili.com/x/v2/reply/main"
    params = {
        "oid": aid,
        "type": comment.CommentResourceType.VIDEO.value,
        "mode": 3,
        "next": next_page,
        "ps": 30,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
        "Accept-Encoding": "gzip, deflate",
    }
    timeout = aiohttp.ClientTimeout(total=COMMENT_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            j = await resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"评论接口错误: code={j.get('code')} msg={j.get('message')}")
    return j.get("data") or {}


async def process_video_to_csv(bvid: str, title: str, dm_path: Path, cm_path: Path) -> dict[str, int]:
    stats = {
        "bvid": bvid,
        "title": title,
        "view": 0,
        "reply": 0,
        "danmaku": 0,
        "danmaku_rows": 0,
        "comment_rows": 0,
    }
    print(f">>> 背景视频：{title} ({bvid})", flush=True)
    v_api = video.Video(bvid=bvid, credential=credential)

    try:
        info = await asyncio.wait_for(v_api.get_info(), timeout=VIDEO_INFO_TIMEOUT_S)
        info_stat = info.get("stat") or {}
        stats["view"] = _safe_int(info_stat.get("view"))
        stats["reply"] = _safe_int(info_stat.get("reply"))
        stats["danmaku"] = _safe_int(info_stat.get("danmaku"))
        pages = info.get("pages") or [{"page": 1, "part": "正片"}]
        with dm_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for idx, part in enumerate(pages):
                part_label = str(part.get("page", idx + 1))
                try:
                    danmakus = await asyncio.wait_for(
                        v_api.get_danmakus(page_index=idx), timeout=DANMAKU_TIMEOUT_S
                    )
                except DanmakuClosedException:
                    print(f"    [弹幕] 分P {part_label} 关闭，跳过", flush=True)
                    continue
                except TimeoutError:
                    print(f"    [弹幕] 分P {part_label} 超时，跳过", flush=True)
                    continue
                for d in danmakus:
                    writer.writerow([title, bvid, part_label, d.text])
                stats["danmaku_rows"] += len(danmakus)
                await asyncio.sleep(0.25)
        print(f"    [弹幕] {stats['danmaku_rows']} 条", flush=True)
    except Exception as exc:
        print(f"    [弹幕] 失败：{exc}", flush=True)

    try:
        aid = bvid2aid(bvid)
        with cm_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            next_page = 0
            page_cap = MAX_COMMENT_PAGES_PER_VIDEO or MAX_COMMENT_PAGE_SAFETY
            for _ in range(1, page_cap + 1):
                data = await asyncio.wait_for(
                    fetch_comment_main_page(aid, next_page),
                    timeout=COMMENT_TIMEOUT_S,
                )
                replies = data.get("replies") or []
                if not replies:
                    break
                for c in replies:
                    writer.writerow(
                        [
                            title,
                            bvid,
                            ((c.get("member") or {}).get("uname") or ""),
                            _comment_text(c.get("content")),
                        ]
                    )
                stats["comment_rows"] += len(replies)
                cursor = data.get("cursor") or {}
                if cursor.get("is_end"):
                    break
                next_page = _safe_int(cursor.get("next"))
                if next_page <= 0:
                    break
                await asyncio.sleep(0.6)
        print(f"    [评论] {stats['comment_rows']} 条", flush=True)
    except TimeoutError:
        print("    [评论] 超时，跳过该视频评论", flush=True)
    except Exception as exc:
        print(f"    [评论] 失败：{exc}", flush=True)
    return stats


async def crawl_background_samples() -> None:
    fresh = os.environ.get("CONAN_BACKGROUND_FRESH", "1").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    sample_path = BASE / "conan_background_sample_videos.csv"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        sorted_videos, sorted_source = await get_sorted_background_videos(session)
        if sorted_videos:
            print(
                f"\n[背景] 来源 {sorted_source}，候选按播放量降序，视频数 {len(sorted_videos)}",
                flush=True,
            )
            initialized_pages: set[int] = set()
            for idx, item in enumerate(sorted_videos):
                page = (idx // TAG_PAGE_SIZE) + 1
                dm_path, cm_path = init_background_csv(page, fresh=fresh and page not in initialized_pages)
                initialized_pages.add(page)
                bvid = item.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                title = _clean_title(item.get("title") or "")
                stat = item.get("stat") or {}
                saved = await process_video_to_csv(bvid, title, dm_path, cm_path)
                rows.append(
                    {
                        "来源": sorted_source,
                        "页码": page,
                        "BV号": bvid,
                        "标题": title,
                        "播放量": _safe_int(stat.get("view")) or saved["view"],
                        "评论数_reply": _safe_int(stat.get("reply")) or saved["reply"],
                        "弹幕数": _safe_int(stat.get("danmaku")) or saved["danmaku"],
                        "采样弹幕行数": saved["danmaku_rows"],
                        "采样评论行数": saved["comment_rows"],
                    }
                )
                await asyncio.sleep(REQUEST_DELAY_S)
        else:
            for page in range(1, BACKGROUND_PAGES + 1):
                dm_path, cm_path = init_background_csv(page, fresh=fresh)
                videos, source = await get_background_page_videos(session, page)
                print(f"\n[背景] 第 {page} 页来源 {source}，视频数 {len(videos)}", flush=True)
                for item in videos:
                    bvid = item.get("bvid") or ""
                    if not bvid or bvid in seen:
                        continue
                    seen.add(bvid)
                    title = _clean_title(item.get("title") or "")
                    stat = item.get("stat") or {}
                    saved = await process_video_to_csv(bvid, title, dm_path, cm_path)
                    rows.append(
                        {
                            "来源": source,
                            "页码": page,
                            "BV号": bvid,
                            "标题": title,
                            "播放量": _safe_int(stat.get("view")) or saved["view"],
                            "评论数_reply": _safe_int(stat.get("reply")) or saved["reply"],
                            "弹幕数": _safe_int(stat.get("danmaku")) or saved["danmaku"],
                            "采样弹幕行数": saved["danmaku_rows"],
                            "采样评论行数": saved["comment_rows"],
                        }
                    )
                    await asyncio.sleep(REQUEST_DELAY_S)

    with sample_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "来源",
            "页码",
            "BV号",
            "标题",
            "播放量",
            "评论数_reply",
            "弹幕数",
            "采样弹幕行数",
            "采样评论行数",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[背景] 样本视频清单：{sample_path}", flush=True)


async def crawl_tag_stats(tag_name: str, out_path: Path) -> None:
    tag_id = await asyncio.wait_for(resolve_tag_id(tag_name), timeout=25)
    print(f"\n[tag统计] {tag_name} tag_id={tag_id}", flush=True)
    timeout = aiohttp.ClientTimeout(total=120)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_reported = 0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        page = 1
        while True:
            archives, total_reported = await fetch_tag_page(session, tag_id, page)
            if not archives:
                break
            for arc in archives:
                bvid = arc.get("bvid") or ""
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                stat = arc.get("stat") or {}
                owner = arc.get("owner") or {}
                rows.append(
                    {
                        "标签名": tag_name,
                        "标签ID": tag_id,
                        "接口报告总稿件数": total_reported,
                        "BV号": bvid,
                        "标题": _clean_title(arc.get("title") or ""),
                        "播放量": _safe_int(stat.get("view")),
                        "评论数_reply": _safe_int(stat.get("reply")),
                        "弹幕数": _safe_int(stat.get("danmaku")),
                        "时长秒": _safe_int(arc.get("duration")),
                        "UP主MID": (owner.get("mid") or ""),
                        "UP主昵称": (owner.get("name") or ""),
                        "页码_抓取时": page,
                    }
                )
            print(f"  第 {page} 页，累计 {len(rows)} 条")
            if len(archives) < TAG_PAGE_SIZE:
                break
            if TAG_STATS_MAX_PAGES > 0 and page >= TAG_STATS_MAX_PAGES:
                break
            page += 1
            await asyncio.sleep(REQUEST_DELAY_S)

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "标签名",
            "标签ID",
            "接口报告总稿件数",
            "BV号",
            "标题",
            "播放量",
            "评论数_reply",
            "弹幕数",
            "时长秒",
            "UP主MID",
            "UP主昵称",
            "页码_抓取时",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[tag统计] 已写入 {out_path}（{len(rows)} 行）")


def _strip_wikitext(wt: str) -> str:
    wt = re.sub(r"<!--.*?-->", " ", wt, flags=re.S)
    wt = re.sub(r"\{\{.*?\}\}", " ", wt, flags=re.S)
    wt = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", wt)
    wt = re.sub(r"\[\[([^\]]+)\]\]", r"\1", wt)
    wt = re.sub(r"\[https?://[^\s\]]+\s*([^\]]*)\]", r"\1", wt)
    wt = re.sub(r"<[^>]+>", " ", wt)
    wt = re.sub(r"[{}|\[\]=#*;:]", " ", wt)
    return re.sub(r"\s+", " ", wt).strip()


def crawl_conanpedia_text() -> None:
    out_path = BASE / "conanpedia_background_text.csv"
    base_titles = [
        "名侦探柯南",
        "江户川柯南",
        "警视厅",
        "警视厅警察学校",
        "松田阵平",
        "萩原研二",
        "伊达航",
        "诸伏景光",
        "降谷零",
        "佐藤美和子",
        "高木涉",
        "爆炸物处理班",
    ]
    titles = list(dict.fromkeys(base_titles))
    if WIKI_CHARACTER_LIMIT > 0:
        try:
            for t in list_category_character_titles()[:WIKI_CHARACTER_LIMIT]:
                if t not in titles:
                    titles.append(t)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"[wiki] 角色分类列表失败，仅抓固定页面：{exc}")

    rows: list[dict[str, str]] = []
    for i in range(0, len(titles), 35):
        chunk = titles[i : i + 35]
        try:
            data = fetch_wikitext_batch(chunk)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            print(f"[wiki] 批次失败：{exc}")
            time.sleep(1.0)
            continue
        for title, wt in data.items():
            text = _strip_wikitext(wt)
            if text:
                rows.append({"页面标题": title, "文本": text})
        time.sleep(0.4)

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["页面标题", "文本"])
        w.writeheader()
        w.writerows(rows)
    print(f"[wiki] 已写入 {out_path}（{len(rows)} 页）")


async def main_async() -> None:
    await crawl_background_samples()
    for tag in (BACKGROUND_TAG, TARGET_TAG):
        out = BASE / f"conan_tag_stats_{tag}.csv"
        try:
            await crawl_tag_stats(tag, out)
        except Exception as exc:
            print(f"[tag统计] {tag} 失败：{exc}")


def main() -> None:
    asyncio.run(main_async())
    crawl_conanpedia_text()


if __name__ == "__main__":
    main()
