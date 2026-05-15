"""
从 Detective Conan Wiki（英文）各角色的 *Appearances* 页面拉取 Wikitext，定量统计：
  • TV 动画：{{appear ep|…}} 条数（含 Specials 等节内条目）
  • 漫画：{{appear file|…}}、剧场版 {{appear movie|…}}、OP/ED 等（分项列）

默认模式：枚举站内**全部**以「 Appearances」结尾的主名字空间页面，**排除主角团**
（仅按下方「页面标题」硬编码排除，不做任何剧情/生死判断），按剧集模板数降序排序，
并输出松田阵平（Jinpei Matsuda Appearances）在全表中的相邻名次。

依赖：urllib（标准库）。

用法：
  cd crawl
  python wiki_appearance_stats.py

说明：中文名未做全量映射；展示列以英文页面标题推导的角色名为准。
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

API = "https://www.detectiveconanworld.com/wiki/api.php"

# --- 排除「主角团」：DC Wiki 上 Appearances 页的**完整标题**（精确匹配）---
# 对应常见日常阵容：柯南/新一、兰、毛利、哀、博士、少年侦探团、园子。
# 如需再排除关西组等，在此集合中追加页面标题即可。
PROTAGONIST_APPEARANCE_PAGE_TITLES: frozenset[str] = frozenset(
    {
        "Conan Edogawa Appearances",
        "Shinichi Kudo Appearances",
        "Ran Mouri Appearances",
        "Kogoro Mouri Appearances",
        "Ai Haibara Appearances",
        "Hiroshi Agasa Appearances",
        "Ayumi Yoshida Appearances",
        "Mitsuhiko Tsuburaya Appearances",
        "Genta Kojima Appearances",
        "Sonoko Suzuki Appearances",
    }
)

MATSUDA_APPEARANCES_TITLE = "Jinpei Matsuda Appearances"
SUFFIX = " Appearances"
BATCH_SIZE = 40


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


def fetch_wikitext(title: str, timeout: float = 45.0, _depth: int = 0) -> str:
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "revisions",
            "rvprop": "content",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        }
    )
    url = f"{API}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WritingProjectWikiStats/1.1 (research; Python urllib)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages:
        raise RuntimeError(f"无页面返回: {title}")
    p0 = pages[0]
    if p0.get("missing"):
        raise RuntimeError(f"维基无此页（missing）: {title}")
    revs = p0.get("revisions") or []
    if not revs:
        raise RuntimeError(f"无 revisions: {title}")
    wt = revs[0].get("content") or ""
    if _depth < 5 and wt.strip().upper().startswith("#REDIRECT"):
        m = _REDIRECT_RE.match(wt.strip())
        if m:
            target = m.group(1).split("|", 1)[0].strip()
            return fetch_wikitext(target, timeout, _depth + 1)
    return wt


def fetch_wikitext_batch(titles: list[str], timeout: float = 60.0) -> dict[str, str]:
    """titles -> wikitext（含简单 #REDIRECT 跟随，逐条）。"""
    if not titles:
        return {}
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(titles),
            "prop": "revisions",
            "rvprop": "content",
            "redirects": "1",
        }
    )
    url = f"{API}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WritingProjectWikiStats/1.1 (research; Python urllib)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out: dict[str, str] = {}
    for p in (data.get("query") or {}).get("pages") or []:
        t = p.get("title") or ""
        if p.get("missing") or not t:
            continue
        revs = p.get("revisions") or []
        if not revs:
            continue
        wt = revs[0].get("content") or ""
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


def list_all_appearance_page_titles(timeout: float = 60.0) -> list[str]:
    """主名字空间内所有以「 Appearances」结尾的页面标题。"""
    titles: list[str] = []
    apcontinue: str | None = None
    while True:
        params: dict[str, str] = {
            "action": "query",
            "format": "json",
            "list": "allpages",
            "apnamespace": "0",
            "aplimit": "500",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "WritingProjectWikiStats/1.1 (research; Python urllib)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for page in (data.get("query") or {}).get("allpages") or []:
            t = page.get("title") or ""
            if t.endswith(SUFFIX):
                titles.append(t)
        apcontinue = (data.get("continue") or {}).get("apcontinue")
        if not apcontinue:
            break
    titles.sort()
    return titles


def split_level2_sections(text: str) -> dict[str, str]:
    parts = re.split(r"\n==\s*([^=\n]+?)\s*==\s*\n", text)
    sections: dict[str, str] = {}
    if not parts:
        return sections
    preamble = parts[0]
    if preamble.strip():
        sections["_preamble"] = preamble
    i = 1
    while i + 1 < len(parts):
        name = parts[i].strip()
        body = parts[i + 1]
        sections[name] = body
        i += 2
    return sections


def count_pattern(section_text: str, needle: str) -> int:
    return len(re.findall(re.escape(needle), section_text))


def analyze_wikitext(wt: str) -> dict[str, Any]:
    secs = split_level2_sections(wt)
    manga_block = secs.get("Manga", "") + secs.get("Manga listings", "")
    specials_block = secs.get("Specials", "")

    appear_file_total = count_pattern(wt, "{{appear file|")
    appear_ep_total = count_pattern(wt, "{{appear ep|")
    appear_movie_total = count_pattern(wt, "{{appear movie|")
    appear_op_total = count_pattern(wt, "{{appear op|")
    appear_ed_total = count_pattern(wt, "{{appear ed|")

    ep_in_specials = count_pattern(specials_block, "{{appear ep|")
    ep_elsewhere = max(0, appear_ep_total - ep_in_specials)

    manga_file_in_section = count_pattern(manga_block, "{{appear file|")
    wps_links = len(re.findall(r"\[\[Wild Police Story Volume", wt))

    return {
        "appear_file_total": appear_file_total,
        "appear_file_manga_section": manga_file_in_section,
        "wild_police_story_links": wps_links,
        "appear_ep_total": appear_ep_total,
        "appear_ep_excluding_specials_block": ep_elsewhere,
        "appear_ep_specials_only": ep_in_specials,
        "appear_movie_total": appear_movie_total,
        "appear_op_total": appear_op_total,
        "appear_ed_total": appear_ed_total,
    }


def appearance_title_to_display_en(full_title: str) -> str:
    if full_title.endswith(SUFFIX):
        return full_title[: -len(SUFFIX)]
    return full_title


def main() -> None:
    out_dir = os.path.dirname(os.path.abspath(__file__))
    print("正在枚举全部 *Appearances 页面…")
    all_titles = list_all_appearance_page_titles()
    print(f"共 {len(all_titles)} 个以「{SUFFIX}」结尾的页面。")

    work_titles = [t for t in all_titles if t not in PROTAGONIST_APPEARANCE_PAGE_TITLES]
    excluded_n = len(all_titles) - len(work_titles)
    print(
        f"排除主角团 Appearances 页 {excluded_n} 个；待统计 {len(work_titles)} 个。"
        f" 排除标题集合：{sorted(PROTAGONIST_APPEARANCE_PAGE_TITLES)}"
    )

    rows: list[dict[str, Any]] = []
    failed: list[tuple[str, str]] = []

    for i in range(0, len(work_titles), BATCH_SIZE):
        chunk = work_titles[i : i + BATCH_SIZE]
        try:
            batch_map = fetch_wikitext_batch(chunk)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            for t in chunk:
                failed.append((t, str(e)))
            time.sleep(0.5)
            continue
        for t in chunk:
            wt = batch_map.get(t)
            if wt is None:
                try:
                    wt = fetch_wikitext(t)
                except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                    failed.append((t, str(e)))
                    continue
            stats = analyze_wikitext(wt)
            display_en = appearance_title_to_display_en(t)
            rows.append(
                {
                    "排名": 0,
                    "英文名_自页面标题": display_en,
                    "DC_Wiki_Appearances页面": t,
                    "排序用_剧集数_appear_ep总数": stats["appear_ep_total"],
                    "漫画_appear_file_全页": stats["appear_file_total"],
                    "漫画_appear_file_Manga节": stats["appear_file_manga_section"],
                    "WildPoliceStory链接数": stats["wild_police_story_links"],
                    "剧场版_appear_movie": stats["appear_movie_total"],
                    "Specials内_ep条数": stats["appear_ep_specials_only"],
                    "片头_appear_op": stats["appear_op_total"],
                    "片尾_appear_ed": stats["appear_ed_total"],
                }
            )
        time.sleep(0.15)

    valid = [r for r in rows if isinstance(r.get("排序用_剧集数_appear_ep总数"), int)]
    valid.sort(key=lambda r: r["排序用_剧集数_appear_ep总数"], reverse=True)
    for idx, r in enumerate(valid, start=1):
        r["排名"] = idx

    rank_path = os.path.join(out_dir, "wiki_appearance_rank_episodes.csv")
    with open(rank_path, "w", encoding="utf-8-sig", newline="") as f:
        if valid:
            w = csv.DictWriter(f, fieldnames=list(valid[0].keys()))
            w.writeheader()
            w.writerows(valid)

    neighbors_path = os.path.join(out_dir, "wiki_matsuda_neighbors_by_episodes.csv")
    target_row = next(
        (r for r in valid if r["DC_Wiki_Appearances页面"] == MATSUDA_APPEARANCES_TITLE),
        None,
    )
    neighbor_rows: list[dict[str, str]] = []
    if target_row and valid:
        idx = valid.index(target_row)
        # 邻接行按「排名」相邻；同分时可能出现相邻行剧集模板条数相同（稳定排序按页面标题字母序）。
        neighbor_rows.append(
            {
                "关系": "榜单上一行_名次更靠前",
                "排名": str(valid[idx - 1]["排名"]) if idx - 1 >= 0 else "",
                "英文名_自页面标题": valid[idx - 1]["英文名_自页面标题"] if idx - 1 >= 0 else "",
                "DC_Wiki_Appearances页面": valid[idx - 1]["DC_Wiki_Appearances页面"]
                if idx - 1 >= 0
                else "",
                "剧集数_appear_ep": str(valid[idx - 1]["排序用_剧集数_appear_ep总数"])
                if idx - 1 >= 0
                else "",
            }
        )
        neighbor_rows.append(
            {
                "关系": "当前_松田阵平_Jinpei_Matsuda",
                "排名": str(target_row["排名"]),
                "英文名_自页面标题": target_row["英文名_自页面标题"],
                "DC_Wiki_Appearances页面": target_row["DC_Wiki_Appearances页面"],
                "剧集数_appear_ep": str(target_row["排序用_剧集数_appear_ep总数"]),
            }
        )
        neighbor_rows.append(
            {
                "关系": "榜单下一行_名次更靠后",
                "排名": str(valid[idx + 1]["排名"]) if idx + 1 < len(valid) else "",
                "英文名_自页面标题": valid[idx + 1]["英文名_自页面标题"]
                if idx + 1 < len(valid)
                else "",
                "DC_Wiki_Appearances页面": valid[idx + 1]["DC_Wiki_Appearances页面"]
                if idx + 1 < len(valid)
                else "",
                "剧集数_appear_ep": str(valid[idx + 1]["排序用_剧集数_appear_ep总数"])
                if idx + 1 < len(valid)
                else "",
            }
        )

    with open(neighbors_path, "w", encoding="utf-8-sig", newline="") as f:
        if neighbor_rows:
            w = csv.DictWriter(f, fieldnames=list(neighbor_rows[0].keys()))
            w.writeheader()
            w.writerows(neighbor_rows)

    fail_path = os.path.join(out_dir, "wiki_appearance_fetch_failed.csv")
    if failed:
        with open(fail_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["DC_Wiki_Appearances页面", "错误"])
            w.writerows(failed)
        print(f"部分页面抓取失败，见：{fail_path}（共 {len(failed)} 条）")

    print(f"\n已写入：{rank_path}（共 {len(valid)} 行，已排除主角团）")
    print(f"已写入：{neighbors_path}")
    print(
        "\n口径：「剧集数」= 页面 Wikitext 中 {{appear ep| 出现次数；"
        "统计对象为该 Wiki 全部 *Appearances 页（除去上述主角团页面标题），"
        "不包含任何剧情或角色生死判断。"
    )


if __name__ == "__main__":
    main()
