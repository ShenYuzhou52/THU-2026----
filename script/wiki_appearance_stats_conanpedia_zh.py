"""
柯南百科（conanpedia.com）角色登场定量统计（中文版数据源）

枚举 Category:角色 下主名字空间条目，抓取wikitext，在「剧内登场情况」相关小节中统计：
  • 本篇动画：===本篇动画=== 节内维基表格数据行数（以 |- 计，含 TV / M / SPTV 等混排，与百科列表一致）
  • 原作漫画：===原作漫画=== 节内表格行数
  • 本篇动画内剧场版：该节中首条数据为 |M数字 的行数（通常对应剧场版单元）

排除「主角团」仅按页面标题精确匹配；不做剧情或生死判断。

排序默认：按「本篇动画_表格行数」降序。

依赖：urllib（标准库）。请求须使用常见浏览器 User-Agent，否则站点可能返回 403。

用法：
  cd crawl
  python wiki_appearance_stats_conanpedia_zh.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://www.conanpedia.com/api.php"

# 排除的主角团（柯南百科页面标题，须与站内完全一致）
PROTAGONIST_PAGE_TITLES_ZH: frozenset[str] = frozenset(
    {
        "江户川柯南",
        "工藤新一",
        "毛利兰",
        "毛利小五郎",
        "灰原哀",
        "阿笠博士",
        "吉田步美",
        "圆谷光彦",
        "小岛元太",
        "铃木园子",
    }
)

MATSUDA_PAGE_TITLE_ZH = "松田阵平"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BATCH_SIZE = 35


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

_REDIRECT_RE = re.compile(r"^#REDIRECT\s*\[\[(.*?)\]\]", re.IGNORECASE | re.MULTILINE)


def _request_json(params: dict[str, str], timeout: float = 90.0) -> dict[str, Any]:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_wikitext(title: str, timeout: float = 60.0, _depth: int = 0) -> str:
    data = _request_json(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
        },
        timeout=timeout,
    )
    pages = (data.get("query") or {}).get("pages") or []
    if not pages:
        raise RuntimeError(f"无页面返回: {title}")
    p0 = pages[0]
    if p0.get("missing"):
        raise RuntimeError(f"页面不存在: {title}")
    slots = (p0.get("revisions") or [{}])[0].get("slots") or {}
    main = slots.get("main") or {}
    wt = main.get("content") or ""
    if _depth < 5 and wt.strip().upper().startswith("#REDIRECT"):
        m = _REDIRECT_RE.match(wt.strip())
        if m:
            target = m.group(1).split("|", 1)[0].strip()
            return fetch_wikitext(target, timeout, _depth + 1)
    return wt


def fetch_wikitext_batch(titles: list[str], timeout: float = 90.0) -> dict[str, str]:
    if not titles:
        return {}
    data = _request_json(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(titles),
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "redirects": "1",
        },
        timeout=timeout,
    )
    out: dict[str, str] = {}
    for p in (data.get("query") or {}).get("pages") or []:
        t = p.get("title") or ""
        if p.get("missing") or not t:
            continue
        slots = (p.get("revisions") or [{}])[0].get("slots") or {}
        wt = (slots.get("main") or {}).get("content") or ""
        if wt.strip().upper().startswith("#REDIRECT"):
            m = _REDIRECT_RE.match(wt.strip())
            if m:
                target = m.group(1).split("|", 1)[0].strip()
                try:
                    wt = fetch_wikitext(target, timeout=timeout)
                except OSError:
                    pass
        out[t] = wt
    return out


def list_category_character_titles(timeout: float = 90.0) -> list[str]:
    """主名字空间内 Category:角色 成员标题。"""
    titles: list[str] = []
    cmcontinue: str | None = None
    while True:
        params: dict[str, str] = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": "Category:角色",
            "cmlimit": "500",
            "cmnamespace": "0",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = _request_json(params, timeout=timeout)
        for m in (data.get("query") or {}).get("categorymembers") or []:
            t = m.get("title") or ""
            if t:
                titles.append(t)
        cmcontinue = (data.get("continue") or {}).get("cmcontinue")
        if not cmcontinue:
            break
    titles.sort()
    return titles


def extract_h3_section(wikitext: str, section_name: str) -> str:
    """抽取三级标题 === 名称 === 下正文，直到下一个同级 H3（非 ====）。"""
    m = re.search(
        rf"^===\s*{re.escape(section_name)}\s*===\s*\n",
        wikitext,
        re.MULTILINE,
    )
    if not m:
        return ""
    rest = wikitext[m.end() :]
    m2 = re.search(r"(?m)^(?!====)===[^=\n][^\n]*?===\s*$", rest)
    if not m2:
        return rest
    return rest[: m2.start()]


def count_table_body_rows(section_text: str) -> int:
    """维基表格中数据行：行首 |-（允许空白）。"""
    if not section_text:
        return 0
    return len(re.findall(r"(?m)^\s*\|-\s*$", section_text))


def count_tv_section_movie_rows(tv_section: str) -> int:
    """本篇动画节内，首条单元格为剧场版编号 |Mxx 的行数。"""
    if not tv_section:
        return 0
    return len(re.findall(r"(?ms)^\s*\|-\s*\n\|\s*M\d+", tv_section))


def analyze_conanpedia_wikitext(wt: str) -> dict[str, Any]:
    manga_sec = extract_h3_section(wt, "原作漫画")
    tv_sec = extract_h3_section(wt, "本篇动画")
    return {
        "本篇动画_表格行数": count_table_body_rows(tv_sec),
        "本篇动画内_剧场版M行数": count_tv_section_movie_rows(tv_sec),
        "原作漫画_表格行数": count_table_body_rows(manga_sec),
    }


def main() -> None:
    out_dir = os.path.dirname(os.path.abspath(__file__))
    print("正在从柯南百科获取 Category:角色 列表…")
    all_titles = list_category_character_titles()
    print(f"共 {len(all_titles)} 个主名字空间角色页。")

    skipped = [t for t in PROTAGONIST_PAGE_TITLES_ZH if t in all_titles]
    work = [t for t in all_titles if t not in PROTAGONIST_PAGE_TITLES_ZH]
    excluded = len(all_titles) - len(work)
    print(f"排除主角团（标题在 Category:角色 内且命中剔除表）共 {excluded} 个：{skipped}")
    not_in_cat = sorted(set(PROTAGONIST_PAGE_TITLES_ZH) - set(all_titles))
    if not_in_cat:
        print(
            "下列剔除用标题未出现在 Category:角色 枚举中（条目可能不在该分类或页面名不同）：",
            not_in_cat,
        )
    print(f"待统计 {len(work)} 个。")

    rows: list[dict[str, Any]] = []
    failed: list[tuple[str, str]] = []

    for i in range(0, len(work), BATCH_SIZE):
        chunk = work[i : i + BATCH_SIZE]
        try:
            batch_map = fetch_wikitext_batch(chunk)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            for t in chunk:
                failed.append((t, str(e)))
            time.sleep(0.8)
            continue
        for t in chunk:
            wt = batch_map.get(t)
            if wt is None:
                try:
                    wt = fetch_wikitext(t)
                except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                    failed.append((t, str(e)))
                    continue
            stats = analyze_conanpedia_wikitext(wt)
            rows.append(
                {
                    "排名": 0,
                    "角色名_页面标题": t,
                    "排序用_本篇动画表格行数": stats["本篇动画_表格行数"],
                    "本篇动画内_剧场版M行数": stats["本篇动画内_剧场版M行数"],
                    "原作漫画_表格行数": stats["原作漫画_表格行数"],
                    "柯南百科URL": "https://www.conanpedia.com/index.php?"
                    + urllib.parse.urlencode({"title": t}),
                }
            )
        time.sleep(0.2)

    valid = [r for r in rows if isinstance(r.get("排序用_本篇动画表格行数"), int)]
    valid.sort(key=lambda r: r["排序用_本篇动画表格行数"], reverse=True)
    for idx, r in enumerate(valid, start=1):
        r["排名"] = idx

    rank_path = os.path.join(out_dir, "wiki_appearance_rank_conanpedia_zh.csv")
    with open(rank_path, "w", encoding="utf-8-sig", newline="") as f:
        if valid:
            w = csv.DictWriter(f, fieldnames=list(valid[0].keys()))
            w.writeheader()
            w.writerows(valid)

    neighbors_path = os.path.join(out_dir, "wiki_matsuda_neighbors_conanpedia_zh.csv")
    target = next((r for r in valid if r["角色名_页面标题"] == MATSUDA_PAGE_TITLE_ZH), None)
    neighbor_rows: list[dict[str, str]] = []
    if target and valid:
        idx = valid.index(target)
        neighbor_rows.append(
            {
                "关系": "榜单上一行_名次更靠前",
                "排名": str(valid[idx - 1]["排名"]) if idx - 1 >= 0 else "",
                "角色名_页面标题": valid[idx - 1]["角色名_页面标题"] if idx - 1 >= 0 else "",
                "本篇动画表格行数": str(valid[idx - 1]["排序用_本篇动画表格行数"])
                if idx - 1 >= 0
                else "",
            }
        )
        neighbor_rows.append(
            {
                "关系": "当前_松田阵平",
                "排名": str(target["排名"]),
                "角色名_页面标题": target["角色名_页面标题"],
                "本篇动画表格行数": str(target["排序用_本篇动画表格行数"]),
            }
        )
        neighbor_rows.append(
            {
                "关系": "榜单下一行_名次更靠后",
                "排名": str(valid[idx + 1]["排名"]) if idx + 1 < len(valid) else "",
                "角色名_页面标题": valid[idx + 1]["角色名_页面标题"]
                if idx + 1 < len(valid)
                else "",
                "本篇动画表格行数": str(valid[idx + 1]["排序用_本篇动画表格行数"])
                if idx + 1 < len(valid)
                else "",
            }
        )

    with open(neighbors_path, "w", encoding="utf-8-sig", newline="") as f:
        if neighbor_rows:
            w = csv.DictWriter(f, fieldnames=list(neighbor_rows[0].keys()))
            w.writeheader()
            w.writerows(neighbor_rows)

    if failed:
        fail_path = os.path.join(out_dir, "wiki_appearance_fetch_failed_conanpedia_zh.csv")
        with open(fail_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["角色名_页面标题", "错误"])
            w.writerows(failed)
        print(f"部分页面失败，见：{fail_path}（{len(failed)} 条）")

    print(f"\n已写入：{rank_path}（共 {len(valid)} 行）")
    print(f"已写入：{neighbors_path}")
    print(
        "\n口径说明：排序依据为柯南百科角色页「本篇动画」小节内维基表格 `|-` 行数；"
        "与英文 DC Wiki 的 `{{appear ep|` 计数不是同一套数据，不宜直接横向对比。"
    )


if __name__ == "__main__":
    main()
