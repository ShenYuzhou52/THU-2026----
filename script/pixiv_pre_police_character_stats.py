import json
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "empirical_output"
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
BASE = "https://www.pixiv.net/ajax/search/novels/%E6%9D%BE%E7%94%B0%E9%99%A3%E5%B9%B3"

# 研究窗口：警察学校篇前
START = date(2010, 1, 1)
END = date(2019, 10, 1)

# 角色归一化（中日常见写法）
CHAR_ALIASES = {
    "松田阵平": ["松田陣平", "松田阵平", "松田"],
    "萩原研二": ["萩原研二"],
    "降谷零": ["降谷零", "安室透", "安室", "古谷零", "Furuya Rei", "Amuro Tooru"],
    "诸伏景光": ["諸伏景光", "诸伏景光", "景光", "スコッチ", "Scotch", "Morofushi Hiromitsu"],
    "伊达航": ["伊達航", "伊达航"],
    "赤井秀一": ["赤井秀一", "沖矢昴", "冲矢昴", "Akai Shuuichi", "Okiya Subaru"],
    "佐藤美和子": ["佐藤美和子", "Satou Miwako"],
    "高木涉": ["高木渉", "高木涉", "Takagi Wataru"],
    "江户川柯南": ["江戸川コナン", "江户川柯南", "工藤新一", "Kudou Shinichi"],
}


def fetch_json(params: dict[str, Any], retries: int = 5, timeout: int = 35) -> dict[str, Any]:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 1.0)
    raise RuntimeError(f"pixiv fetch failed params={params}, err={last_err}")


def date_to_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def normalize_characters(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        for canon, aliases in CHAR_ALIASES.items():
            if any(a in t for a in aliases):
                if canon not in out:
                    out.append(canon)
                break
    return out


def crawl_window(s: date, e: date, acc: dict[str, dict[str, Any]], depth: int = 0) -> None:
    """按时间窗抓取；当窗口结果过大（>300）时递归拆窗。"""
    if s > e:
        return
    params = {
        "word": "松田陣平",
        "order": "date_d",
        "mode": "all",
        "p": 1,
        "s_mode": "s_tag",
        "scd": date_to_str(s),
        "ecd": date_to_str(e),
    }
    j = fetch_json(params)
    body = j.get("body", {}).get("novel", {})
    total = int(body.get("total", 0) or 0)
    last_page = int(body.get("lastPage", 1) or 1)

    # pixiv搜索最多返回前10页*30=300条；超出则拆分时间窗口
    if total > 300 and s < e:
        mid = s + (e - s) // 2
        crawl_window(s, mid, acc, depth + 1)
        crawl_window(mid + timedelta(days=1), e, acc, depth + 1)
        return

    # 抓本窗口所有可返回页
    for p in range(1, last_page + 1):
        params["p"] = p
        jj = fetch_json(params)
        data = jj.get("body", {}).get("novel", {}).get("data", []) or []
        for it in data:
            nid = str(it.get("id", ""))
            if not nid:
                continue
            acc[nid] = {
                "site": "Pixiv",
                "novel_id": nid,
                "title": it.get("title", ""),
                "createDate": it.get("createDate", ""),
                "tags": it.get("tags", []),
                "bookmarkCount": int(it.get("bookmarkCount", 0) or 0),
                "userName": it.get("userName", ""),
                "url": f"https://www.pixiv.net/novel/show.php?id={nid}",
            }
        time.sleep(0.15)


def main() -> None:
    acc: dict[str, dict[str, Any]] = {}
    crawl_window(START, END, acc)
    rows = list(acc.values())
    print(f"pixiv rows fetched: {len(rows)}")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No pixiv data fetched.")

    df["create_dt"] = pd.to_datetime(df["createDate"], errors="coerce")
    df = df[df["create_dt"].notna()].copy()
    df = df[df["create_dt"].dt.date <= END].copy()
    df = df.sort_values("create_dt", ascending=False)

    # 角色提取
    df["matched_characters"] = df["tags"].apply(lambda x: normalize_characters(x if isinstance(x, list) else []))
    df["primary_character_proxy"] = df["matched_characters"].apply(lambda x: x[0] if x else "")
    df["tags_joined"] = df["tags"].apply(lambda x: " | ".join(x) if isinstance(x, list) else "")
    df["matched_characters_joined"] = df["matched_characters"].apply(lambda x: " | ".join(x))

    # 计数：角色出现次数
    c_all = Counter()
    for arr in df["matched_characters"]:
        for c in arr:
            c_all[c] += 1
    all_df = pd.DataFrame(c_all.items(), columns=["character", "appear_count"]).sort_values("appear_count", ascending=False)

    # 计数：主角代理
    c_pri = Counter([x for x in df["primary_character_proxy"].tolist() if x])
    pri_df = pd.DataFrame(c_pri.items(), columns=["primary_character_proxy", "primary_count"]).sort_values("primary_count", ascending=False)

    works_path = OUT / "pixiv_pre_police_matsuda_novels.csv"
    all_path = OUT / "pixiv_pre_police_character_counts.csv"
    pri_path = OUT / "pixiv_pre_police_primary_character_proxy_counts.csv"

    df[
        [
            "site",
            "novel_id",
            "title",
            "createDate",
            "bookmarkCount",
            "userName",
            "url",
            "tags_joined",
            "matched_characters_joined",
            "primary_character_proxy",
        ]
    ].to_csv(works_path, index=False, encoding="utf-8-sig")
    all_df.to_csv(all_path, index=False, encoding="utf-8-sig")
    pri_df.to_csv(pri_path, index=False, encoding="utf-8-sig")

    summary = {
        "site": "Pixiv",
        "window": [date_to_str(START), date_to_str(END)],
        "novels_total": int(len(df)),
        "files": {
            "novels_csv": str(works_path),
            "character_counts_csv": str(all_path),
            "primary_proxy_counts_csv": str(pri_path),
        },
    }
    (OUT / "pixiv_pre_police_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
