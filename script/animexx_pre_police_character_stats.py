import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "empirical_output"
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_LIST = "https://www.animexx.de/fanfiction/charakter/1316/"
CUTOFF = datetime(2019, 10, 1)  # 警察学校篇前


def fetch(url: str, retries: int = 4, timeout: int = 40) -> str:
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


def extract_story_links(list_html: str) -> list[str]:
    soup = BeautifulSoup(list_html, "html.parser")
    links = set()
    for a in soup.select("a[href]"):
        h = a.get("href") or ""
        m = re.search(r"/fanfiction/(\d+)/?$", h)
        if m:
            links.add(f"https://www.animexx.de/fanfiction/{m.group(1)}/")
    return sorted(links)


def parse_story(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    story_id = re.search(r"/fanfiction/(\d+)/", url).group(1) if re.search(r"/fanfiction/(\d+)/", url) else ""

    # 标题
    title = ""
    m_title = re.search(r"^(.*?)\s*-\s*Fanfic", text)
    if m_title:
        title = m_title.group(1).strip()

    # 创建日期（德语格式）
    created = ""
    m_created = re.search(r"Erstellt:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", text)
    if m_created:
        created = m_created.group(1)

    # 角色字段
    main_chars = []
    b = soup.find("b", string=re.compile(r"Hauptcharaktere"))
    if b:
        # 只取紧随其后的角色链接，避免吞掉整段描述文本
        for sib in b.next_siblings:
            if getattr(sib, "name", None) == "a":
                t = sib.get_text(strip=True)
                if t:
                    main_chars.append(t)
                continue
            # 允许逗号/空白
            if isinstance(sib, str) and sib.strip() in {"", ","}:
                continue
            break

    return {
        "site": "Animexx",
        "story_id": story_id,
        "url": url,
        "title": title,
        "created_raw": created,
        "main_characters": " | ".join(main_chars),
        "primary_character_proxy": main_chars[0] if main_chars else "",
    }


def parse_de_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d.%m.%Y")
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    html = fetch(BASE_LIST)
    story_links = extract_story_links(html)
    print(f"animexx story links: {len(story_links)}")

    rows = []
    for i, u in enumerate(story_links, start=1):
        try:
            s_html = fetch(u)
            row = parse_story(s_html, u)
            row["created_dt"] = parse_de_date(row["created_raw"])
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "site": "Animexx",
                    "story_id": "",
                    "url": u,
                    "title": "",
                    "created_raw": "",
                    "main_characters": "",
                    "primary_character_proxy": "",
                    "error": str(e),
                    "created_dt": None,
                }
            )
        print(f"{i}/{len(story_links)} {u}")
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    df["created_dt"] = pd.to_datetime(df["created_dt"], errors="coerce")
    pre_df = df[df["created_dt"].notna() & (df["created_dt"] <= pd.Timestamp(CUTOFF))].copy()

    # 角色总频次
    c_all = Counter()
    for s in pre_df["main_characters"].fillna(""):
        chars = [x.strip() for x in s.split("|") if x.strip()]
        c_all.update(chars)
    all_df = pd.DataFrame(c_all.items(), columns=["character", "appear_count"]).sort_values("appear_count", ascending=False)

    # 主角代理频次
    c_pri = Counter([x for x in pre_df["primary_character_proxy"].fillna("").tolist() if x])
    pri_df = pd.DataFrame(c_pri.items(), columns=["primary_character_proxy", "primary_count"]).sort_values("primary_count", ascending=False)

    works_path = OUT / "animexx_matsuda_all_story_meta.csv"
    pre_path = OUT / "animexx_pre_police_story_meta.csv"
    all_path = OUT / "animexx_pre_police_character_counts.csv"
    pri_path = OUT / "animexx_pre_police_primary_character_proxy_counts.csv"

    df.to_csv(works_path, index=False, encoding="utf-8-sig")
    pre_df.to_csv(pre_path, index=False, encoding="utf-8-sig")
    all_df.to_csv(all_path, index=False, encoding="utf-8-sig")
    pri_df.to_csv(pri_path, index=False, encoding="utf-8-sig")

    summary = {
        "site": "Animexx",
        "cutoff_date": CUTOFF.strftime("%Y-%m-%d"),
        "stories_total_found": int(len(df)),
        "stories_pre_police": int(len(pre_df)),
        "files": {
            "all_story_meta_csv": str(works_path),
            "pre_police_story_meta_csv": str(pre_path),
            "character_counts_csv": str(all_path),
            "primary_proxy_counts_csv": str(pri_path),
        },
    }
    (OUT / "animexx_pre_police_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
