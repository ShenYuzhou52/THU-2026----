import json
import math
import re
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import matplotlib.pyplot as plt
import pandas as pd
import requests
from bs4 import BeautifulSoup
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "empirical_output"
OUT.mkdir(exist_ok=True)

POST_START = date(2019, 10, 2)
POST_END = date.today()
MOVIE_DATE = date(2022, 4, 15)  # 万圣节的新娘日本上映

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}

AO3_MATSUDA = "https://archive.transformativeworks.org/tags/Matsuda%20Jinpei/works"
AO3_CONAN = "https://archive.transformativeworks.org/tags/%E5%90%8D%E6%8E%A2%E5%81%B5%E3%82%B3%E3%83%8A%E3%83%B3%20%7C%20Detective%20Conan%20%7C%20Case%20Closed/works"
PIXIV_MATSUDA_TAG = "松田陣平"
PIXIV_CONAN_TAG = "名探偵コナン"
PIXIV_BASE = "https://www.pixiv.net/ajax/search/novels/{tag_path}"
ANIMEXX_CONAN_LIST = "https://www.animexx.de/fanfiction/serie/333_Detektiv_Conan/order_1_{page}/"
ANIMEXX_MATSUDA_META = OUT / "animexx_matsuda_all_story_meta.csv"


CHAR_ALIASES = {
    "松田阵平": ["松田陣平", "松田阵平", "松田", "Jinpei Matsuda", "Matsuda Jinpei"],
    "萩原研二": ["萩原研二", "Hagiwara Kenji", "Kenji Hagiwara"],
    "降谷零": ["降谷零", "安室透", "安室", "古谷零", "Furuya Rei", "Amuro Tooru"],
    "诸伏景光": ["諸伏景光", "诸伏景光", "景光", "スコッチ", "Scotch", "Morofushi Hiromitsu"],
    "伊达航": ["伊達航", "伊达航", "Date Wataru", "Wataru Date"],
    "赤井秀一": ["赤井秀一", "沖矢昴", "冲矢昴", "Akai Shuuichi", "Okiya Subaru"],
    "江户川柯南": ["江戸川コナン", "江户川柯南", "工藤新一", "Kudou Shinichi", "Edogawa Conan"],
    "佐藤美和子": ["佐藤美和子", "Satou Miwako", "Miwako Sato"],
    "高木涉": ["高木渉", "高木涉", "Takagi Wataru", "Wataru Takagi"],
}


def pick_font_path() -> Optional[str]:
    for p in [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\SimHei.ttf"),
    ]:
        if p.exists():
            return str(p)
    return None


def setup_font() -> None:
    fp = pick_font_path()
    if fp:
        name = font_manager.FontProperties(fname=fp).get_name()
        plt.rcParams["font.family"] = name
    plt.rcParams["axes.unicode_minus"] = False


def fetch_text(url: str, retries: int = 5, timeout: int = 40, headers: Optional[dict] = None) -> str:
    last_err = None
    h = headers or HEADERS
    for i in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 1.2)
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def fetch_json(url: str, retries: int = 5, timeout: int = 35) -> dict[str, Any]:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 1.0)
    raise RuntimeError(f"json fetch failed: {url}, err={last_err}")


def parse_int(text: Optional[str]) -> int:
    if not text:
        return 0
    m = re.search(r"\d[\d,]*", text)
    return int(m.group(0).replace(",", "")) if m else 0


def canon_characters(raw_tags: list[str]) -> list[str]:
    out: list[str] = []
    for tag in raw_tags:
        for c, aliases in CHAR_ALIASES.items():
            if any(a in tag for a in aliases):
                if c not in out:
                    out.append(c)
                break
    return out


def year_range(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def ao3_build_url(base: str, y: int, sort_column: str) -> str:
    params = {
        "page": 1,
        "work_search[date_from]": f"{y}-01-01",
        "work_search[date_to]": f"{y}-12-31",
        "work_search[sort_column]": sort_column,
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def ao3_total_from_html(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h2.heading")
    if not h:
        return 0
    m = re.search(r"of\s+([\d,]+)\s+Works", h.get_text(" ", strip=True), flags=re.I)
    return int(m.group(1).replace(",", "")) if m else 0


def ao3_yearly_share(years: list[int]) -> pd.DataFrame:
    rows = []
    for y in years:
        m_html = fetch_text(ao3_build_url(AO3_MATSUDA, y, "created_at"))
        c_html = fetch_text(ao3_build_url(AO3_CONAN, y, "created_at"))
        m_total = ao3_total_from_html(m_html)
        c_total = ao3_total_from_html(c_html)
        share = (m_total / c_total) if c_total > 0 else None
        rows.append({"year": y, "site": "AO3", "matsuda_works": m_total, "conan_works": c_total, "share": share})
        print(f"[AO3] {y}: {m_total}/{c_total}")
        time.sleep(0.2)
    return pd.DataFrame(rows)


def pixiv_search_url(word: str, y: int, page: int, order: str = "date_d") -> str:
    tag_path = urllib.parse.quote(word, safe="")
    query = urllib.parse.urlencode(
        {
            "word": word,
            "order": order,
            "p": page,
            "s_mode": "s_tag",
            "scd": f"{y}-01-01",
            "ecd": f"{y}-12-31",
        }
    )
    return PIXIV_BASE.format(tag_path=tag_path) + "?" + query


def pixiv_yearly_share(years: list[int]) -> pd.DataFrame:
    rows = []
    for y in years:
        jm = fetch_json(pixiv_search_url(PIXIV_MATSUDA_TAG, y, 1, "date_d"))
        jc = fetch_json(pixiv_search_url(PIXIV_CONAN_TAG, y, 1, "date_d"))
        m_total = int(jm["body"]["novel"]["total"])
        c_total = int(jc["body"]["novel"]["total"])
        share = (m_total / c_total) if c_total > 0 else None
        rows.append({"year": y, "site": "Pixiv", "matsuda_works": m_total, "conan_works": c_total, "share": share})
        print(f"[Pixiv] {y}: {m_total}/{c_total}")
        time.sleep(0.2)
    return pd.DataFrame(rows)


def animexx_extract_dates_from_page(html: str) -> list[datetime]:
    soup = BeautifulSoup(html, "html.parser")
    dates = []
    for li in soup.select("li.ff_big_thumb_box.hat_cover.preview"):
        txt = " ".join(li.get_text(" ", strip=True).split())
        m = re.search(r"Datum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", txt)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1), "%d.%m.%Y")
            dates.append(dt)
        except Exception:  # noqa: BLE001
            continue
    return dates


def animexx_conan_year_counts(years: list[int]) -> dict[int, int]:
    # 从第一页推断最大分页索引
    first = fetch_text(ANIMEXX_CONAN_LIST.format(page=0), headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(first, "html.parser")
    nums = []
    for a in soup.select("a[href]"):
        h = a.get("href") or ""
        m = re.search(r"/fanfiction/serie/333_Detektiv_Conan/order_1_(\d+)/", h)
        if m:
            nums.append(int(m.group(1)))
    max_page = max(nums) if nums else 0

    counts = {y: 0 for y in years}
    for p in range(0, max_page + 1):
        html = fetch_text(ANIMEXX_CONAN_LIST.format(page=p), headers={"User-Agent": "Mozilla/5.0"})
        for dt in animexx_extract_dates_from_page(html):
            if dt.year in counts:
                counts[dt.year] += 1
        if p % 10 == 0:
            print(f"[Animexx Conan] page {p}/{max_page}")
        time.sleep(0.15)
    return counts


def animexx_matsuda_year_counts(years: list[int]) -> dict[int, int]:
    if not ANIMEXX_MATSUDA_META.exists():
        raise FileNotFoundError(f"{ANIMEXX_MATSUDA_META} missing.")
    df = pd.read_csv(ANIMEXX_MATSUDA_META, encoding="utf-8-sig")
    df["created_dt"] = pd.to_datetime(df["created_dt"], errors="coerce")
    df = df[df["created_dt"].notna()].copy()
    counts = {y: 0 for y in years}
    for y, n in df.groupby(df["created_dt"].dt.year).size().items():
        if int(y) in counts:
            counts[int(y)] = int(n)
    return counts


def animexx_yearly_share(years: list[int]) -> pd.DataFrame:
    m_counts = animexx_matsuda_year_counts(years)
    c_counts = animexx_conan_year_counts(years)
    rows = []
    for y in years:
        m_total = m_counts.get(y, 0)
        c_total = c_counts.get(y, 0)
        share = (m_total / c_total) if c_total > 0 else None
        rows.append({"year": y, "site": "Animexx", "matsuda_works": m_total, "conan_works": c_total, "share": share})
        print(f"[Animexx] {y}: {m_total}/{c_total}")
    return pd.DataFrame(rows)


def ao3_post_protagonists(years: list[int]) -> pd.DataFrame:
    rows = []
    for y in years:
        # 先拿总页数
        first_url = ao3_build_url(AO3_MATSUDA, y, "created_at")
        first_html = fetch_text(first_url)
        total = ao3_total_from_html(first_html)
        pages = max(1, math.ceil(total / 20))
        html_pages = {1: first_html}
        for p in range(2, pages + 1):
            params = {
                "page": p,
                "work_search[date_from]": f"{y}-01-01",
                "work_search[date_to]": f"{y}-12-31",
                "work_search[sort_column]": "created_at",
            }
            u = AO3_MATSUDA + "?" + urllib.parse.urlencode(params)
            html_pages[p] = fetch_text(u)
            time.sleep(0.1)

        for html in html_pages.values():
            soup = BeautifulSoup(html, "html.parser")
            for li in soup.select("li.work.blurb.group"):
                dt_text = (li.select_one("p.datetime").get_text(strip=True) if li.select_one("p.datetime") else "")
                try:
                    dt = datetime.strptime(dt_text, "%d %b %Y")
                except Exception:  # noqa: BLE001
                    continue
                if dt.date() < POST_START:
                    continue
                tags = [a.get_text(strip=True) for a in li.select("li.characters a.tag")]
                chars = canon_characters(tags)
                rows.append({"site": "AO3", "year": dt.year, "chars": chars})
        print(f"[AO3 protagonists] {y}: done")
    return pd.DataFrame(rows)


def pixiv_post_protagonists() -> pd.DataFrame:
    # 递归拆窗抓全量（避免每窗最多300条上限）
    acc: dict[str, dict[str, Any]] = {}

    def crawl_window(s: date, e: date) -> None:
        if s > e:
            return
        params = {
            "word": PIXIV_MATSUDA_TAG,
            "order": "date_d",
            "p": 1,
            "s_mode": "s_tag",
            "scd": s.strftime("%Y-%m-%d"),
            "ecd": e.strftime("%Y-%m-%d"),
        }
        tag_path = urllib.parse.quote(PIXIV_MATSUDA_TAG, safe="")
        url = PIXIV_BASE.format(tag_path=tag_path) + "?" + urllib.parse.urlencode(params)
        j = fetch_json(url)
        body = j.get("body", {}).get("novel", {})
        total = int(body.get("total", 0) or 0)
        last_page = int(body.get("lastPage", 1) or 1)

        if total > 300 and s < e:
            mid = s + (e - s) // 2
            crawl_window(s, mid)
            crawl_window(mid + timedelta(days=1), e)
            return

        for p in range(1, last_page + 1):
            params["p"] = p
            u = PIXIV_BASE.format(tag_path=tag_path) + "?" + urllib.parse.urlencode(params)
            jj = fetch_json(u)
            data = jj.get("body", {}).get("novel", {}).get("data", []) or []
            for it in data:
                nid = str(it.get("id", ""))
                if not nid:
                    continue
                acc[nid] = {"createDate": it.get("createDate", ""), "tags": it.get("tags", [])}
            time.sleep(0.08)

    crawl_window(POST_START, POST_END)

    rows = []
    for nid, r in acc.items():
        dt = pd.to_datetime(r.get("createDate", ""), errors="coerce")
        if pd.isna(dt):
            continue
        tags = r.get("tags", []) if isinstance(r.get("tags", []), list) else []
        chars = canon_characters(tags)
        rows.append({"site": "Pixiv", "year": int(dt.year), "chars": chars})
    print(f"[Pixiv protagonists] rows={len(rows)}")
    return pd.DataFrame(rows)


def animexx_post_protagonists() -> pd.DataFrame:
    if not ANIMEXX_MATSUDA_META.exists():
        return pd.DataFrame(columns=["site", "year", "chars"])
    df = pd.read_csv(ANIMEXX_MATSUDA_META, encoding="utf-8-sig")
    df["created_dt"] = pd.to_datetime(df["created_dt"], errors="coerce")
    df = df[df["created_dt"].notna()].copy()
    df = df[df["created_dt"].dt.date >= POST_START]
    rows = []
    for _, r in df.iterrows():
        raw = str(r.get("main_characters", "") or "")
        tags = [x.strip() for x in raw.split("|") if x.strip()]
        chars = canon_characters(tags)
        rows.append({"site": "Animexx", "year": int(r["created_dt"].year), "chars": chars})
    print(f"[Animexx protagonists] rows={len(rows)}")
    return pd.DataFrame(rows)


def build_stacked_proportion(prot_df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    counts = defaultdict(Counter)  # year -> counter
    for _, r in prot_df.iterrows():
        y = int(r["year"])
        chars = [c for c in (r["chars"] or []) if c != "松田阵平"]
        for c in chars:
            counts[y][c] += 1

    # 总体 top5（剔除松田后）
    total = Counter()
    for y in counts:
        total.update(counts[y])
    top5 = [c for c, _ in total.most_common(5)]

    rows = []
    for y in years:
        c = counts.get(y, Counter())
        denom = sum(c.values())
        if denom == 0:
            rows.append({"year": y, **{k: 0.0 for k in top5}, "其他": 0.0})
            continue
        row = {"year": y}
        used = 0
        for k in top5:
            v = c.get(k, 0)
            used += v
            row[k] = v / denom
        row["其他"] = max(0.0, (denom - used) / denom)
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("year")
    return out


def main() -> None:
    setup_font()
    years = year_range(2020, datetime.now().year)

    # 1) 三网站“松田/柯南”占比三折线
    ao3 = ao3_yearly_share(years)
    pix = pixiv_yearly_share(years)
    ani = animexx_yearly_share(years)
    share_df = pd.concat([ao3, pix, ani], ignore_index=True)
    share_csv = OUT / "crosssite_post2019_matsuda_share.csv"
    share_df.to_csv(share_csv, index=False, encoding="utf-8-sig")

    plt.figure(figsize=(9.6, 5.4))
    for site, g in share_df.groupby("site"):
        plt.plot(g["year"], g["share"], marker="o", linewidth=2, label=site)
    plt.axvline(2020, linestyle="--", alpha=0.35, label="警察学校篇后首完整年")
    plt.axvline(2022, linestyle="--", alpha=0.35, label="M25上映年")
    plt.title("三站联合：松田同人占柯南圈层比例（按年）")
    plt.xlabel("年份")
    plt.ylabel("比例")
    plt.grid(alpha=0.25, linestyle="--")
    plt.legend()
    plt.tight_layout()
    share_png = OUT / "crosssite_post2019_share_three_lines.png"
    plt.savefig(share_png, dpi=180)
    plt.close()

    # 2) 主角聚合度堆叠比例图（剔除松田）
    prot_ao3 = ao3_post_protagonists(years)
    prot_pix = pixiv_post_protagonists()
    prot_ani = animexx_post_protagonists()
    prot_df = pd.concat([prot_ao3, prot_pix, prot_ani], ignore_index=True)
    prot_path = OUT / "crosssite_post2019_protagonists_raw.csv"
    prot_df.to_csv(prot_path, index=False, encoding="utf-8-sig")

    stack_df = build_stacked_proportion(prot_df, years)
    stack_csv = OUT / "crosssite_post2019_protagonist_proportions_top5.csv"
    stack_df.to_csv(stack_csv, index=False, encoding="utf-8-sig")

    cols = [c for c in stack_df.columns if c != "year"]
    x = stack_df["year"].tolist()
    ys = [stack_df[c].tolist() for c in cols]

    plt.figure(figsize=(10.2, 5.6))
    plt.stackplot(x, ys, labels=cols, alpha=0.88)
    plt.axvline(2020, linestyle="--", alpha=0.4)
    plt.axvline(2022, linestyle="--", alpha=0.4)
    plt.title("三站联合：剔除松田后的主角结构占比（Top5+其他）")
    plt.xlabel("年份")
    plt.ylabel("比例（总和=1）")
    plt.ylim(0, 1)
    plt.grid(alpha=0.2, linestyle="--")
    plt.legend(loc="upper left", ncol=3)
    plt.tight_layout()
    stack_png = OUT / "crosssite_post2019_protagonist_stack_top5.png"
    plt.savefig(stack_png, dpi=180)
    plt.close()

    # 节点对比（聚合度：Top5占比）
    node = stack_df.copy()
    node["top5_sum"] = node[[c for c in cols if c != "其他"]].sum(axis=1)
    node_csv = OUT / "crosssite_post2019_cohesion_node_table.csv"
    node.to_csv(node_csv, index=False, encoding="utf-8-sig")

    summary = {
        "window": [POST_START.strftime("%Y-%m-%d"), POST_END.strftime("%Y-%m-%d")],
        "sites": ["AO3", "Pixiv", "Animexx"],
        "files": {
            "share_csv": str(share_csv),
            "share_plot": str(share_png),
            "protagonist_raw_csv": str(prot_path),
            "proportion_csv": str(stack_csv),
            "stack_plot": str(stack_png),
            "node_table_csv": str(node_csv),
        },
    }
    (OUT / "crosssite_post2019_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
