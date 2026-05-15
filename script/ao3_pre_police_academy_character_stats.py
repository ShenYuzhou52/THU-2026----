import json
import re
import time
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "empirical_output"
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE = "https://archive.transformativeworks.org/tags/Matsuda%20Jinpei/works"

# 《警察学校篇 Wild Police Story》连载开始：2019-10-02（用于“官方动作之前”界定）
CUTOFF_DATE = "2019-10-01"  # 含当日


def parse_int(text: Optional[str]) -> int:
    if not text:
        return 0
    m = re.search(r"\d[\d,]*", text)
    return int(m.group(0).replace(",", "")) if m else 0


def fetch(url: str, retries: int = 5, timeout: int = 45) -> str:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 1.2)
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def build_url(page: int) -> str:
    params = {
        "page": page,
        "work_search[date_to]": CUTOFF_DATE,
        "work_search[sort_column]": "created_at",
        "view_adult": "true",
    }
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def parse_total_works(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h2.heading")
    if not h:
        return 0
    text = h.get_text(" ", strip=True)
    m = re.search(r"of\s+([\d,]+)\s+Works", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return parse_int(text)


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for li in soup.select("li.work.blurb.group"):
        work_id = (li.get("id") or "").replace("work_", "")
        title_el = li.select_one("h4.heading a")
        title = title_el.get_text(strip=True) if title_el else ""
        date_el = li.select_one("p.datetime")
        pub = date_el.get_text(strip=True) if date_el else ""

        chars = [a.get_text(strip=True) for a in li.select("li.characters a.tag")]
        rels = [a.get_text(strip=True) for a in li.select("li.relationships a.tag")]

        rows.append(
            {
                "work_id": work_id,
                "title": title,
                "published": pub,
                "characters": " | ".join(chars),
                "relationships": " | ".join(rels),
                # 代理口径：AO3字符标签第一个通常是作者优先标注角色
                "primary_character_proxy": chars[0] if chars else "",
            }
        )
    return rows


def main() -> None:
    first_html = fetch(build_url(1))
    total_works = parse_total_works(first_html)
    total_pages = max(1, (total_works + 19) // 20)
    print(f"pre-police-academy works={total_works}, pages={total_pages}")

    all_rows = parse_page(first_html)
    for p in range(2, total_pages + 1):
        html = fetch(build_url(p))
        all_rows.extend(parse_page(html))
        print(f"page {p}/{total_pages}")
        time.sleep(0.3)

    # 去重
    uniq = {}
    for r in all_rows:
        if r["work_id"]:
            uniq[r["work_id"]] = r
    rows = list(uniq.values())

    works_df = pd.DataFrame(rows)
    works_path = OUT / "ao3_pre_police_academy_matsuda_works.csv"
    works_df.to_csv(works_path, index=False, encoding="utf-8-sig")

    # 统计“角色出现次数”（角色标签出现）
    char_counter = Counter()
    for s in works_df["characters"].fillna(""):
        parts = [x.strip() for x in s.split("|") if x.strip()]
        char_counter.update(parts)
    char_df = pd.DataFrame(char_counter.items(), columns=["character_tag", "appear_count"]).sort_values("appear_count", ascending=False)
    char_path = OUT / "ao3_pre_police_academy_character_counts.csv"
    char_df.to_csv(char_path, index=False, encoding="utf-8-sig")

    # 统计“主角代理次数”（characters 第一个 tag）
    pri_counter = Counter([x for x in works_df["primary_character_proxy"].fillna("").tolist() if x])
    pri_df = pd.DataFrame(pri_counter.items(), columns=["primary_character_proxy", "primary_count"]).sort_values("primary_count", ascending=False)
    pri_path = OUT / "ao3_pre_police_academy_primary_character_proxy_counts.csv"
    pri_df.to_csv(pri_path, index=False, encoding="utf-8-sig")

    summary = {
        "cutoff_date": CUTOFF_DATE,
        "works_total": int(len(works_df)),
        "files": {
            "works_csv": str(works_path),
            "character_counts_csv": str(char_path),
            "primary_proxy_counts_csv": str(pri_path),
        },
    }
    (OUT / "ao3_pre_police_academy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
