from __future__ import annotations

import ast
import json
import math
import re
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime
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

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}

YEARS = list(range(2010, datetime.now().year + 1))
POLICE_DATE = 2019.75  # 2019-10-01 约等于 2019.75
MOVIE_DATE = 2022.29   # 2022-04-15 约等于 2022.29

AO3_MATSUDA_CSV = OUT / "ao3_matsuda_yearly_scan.csv"
AO3_MATSUDA_URL = "https://archive.transformativeworks.org/tags/Matsuda%20Jinpei/works"
AO3_CONAN_URL = "https://archive.transformativeworks.org/tags/%E5%90%8D%E6%8E%A2%E5%81%B5%E3%82%B3%E3%83%8A%E3%83%B3%20%7C%20Detective%20Conan%20%7C%20Case%20Closed/works"

PIXIV_BASE = "https://www.pixiv.net/ajax/search/novels/{tag_path}"
PIXIV_MATSUDA = "松田陣平"
PIXIV_CONAN = "名探偵コナン"

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
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def fetch_text(url: str, retries: int = 4, timeout: int = 45, headers: Optional[dict[str, str]] = None) -> str:
    last_err = None
    hs = headers or HEADERS
    for i in range(retries):
        try:
            r = requests.get(url, headers=hs, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 1.2)
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def fetch_json(url: str, retries: int = 4, timeout: int = 35) -> dict[str, Any]:
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


def parse_int(text: str) -> int:
    m = re.search(r"\d[\d,]*", text or "")
    return int(m.group(0).replace(",", "")) if m else 0


def ao3_build_url(base: str, year: int, sort_column: str) -> str:
    q = urllib.parse.urlencode(
        {
            "page": 1,
            "work_search[date_from]": f"{year}-01-01",
            "work_search[date_to]": f"{year}-12-31",
            "work_search[sort_column]": sort_column,
        }
    )
    return f"{base}?{q}"


def ao3_total_from_html(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h2.heading")
    if not h:
        return 0
    m = re.search(r"of\s+([\d,]+)\s+Works", h.get_text(" ", strip=True), flags=re.I)
    return int(m.group(1).replace(",", "")) if m else 0


def ao3_conan_yearly_counts() -> dict[int, int]:
    out = {}
    for y in YEARS:
        html = fetch_text(ao3_build_url(AO3_CONAN_URL, y, "created_at"))
        out[y] = ao3_total_from_html(html)
        time.sleep(0.1)
    return out


def pixiv_url(word: str, year: int, page: int, order: str = "date_d") -> str:
    tag_path = urllib.parse.quote(word, safe="")
    q = urllib.parse.urlencode(
        {
            "word": word,
            "order": order,
            "p": page,
            "s_mode": "s_tag",
            "scd": f"{year}-01-01",
            "ecd": f"{year}-12-31",
        }
    )
    return PIXIV_BASE.format(tag_path=tag_path) + "?" + q


def pixiv_yearly_counts_and_heat(word: str) -> tuple[dict[int, int], dict[int, int]]:
    counts: dict[int, int] = {}
    heats: dict[int, int] = {}
    for y in YEARS:
        # 总量
        j = fetch_json(pixiv_url(word, y, 1, "date_d"))
        total = int(j.get("body", {}).get("novel", {}).get("total", 0) or 0)
        counts[y] = total

        # top20 热度代理：popular_d 首页按 bookmarkCount 取前20
        j2 = fetch_json(pixiv_url(word, y, 1, "popular_d"))
        data = j2.get("body", {}).get("novel", {}).get("data", []) or []
        top20 = sorted(data, key=lambda x: int(x.get("bookmarkCount", 0) or 0), reverse=True)[:20]
        heats[y] = int(sum(int(x.get("bookmarkCount", 0) or 0) for x in top20))
        time.sleep(0.1)
    return counts, heats


def animexx_conan_yearly_counts() -> dict[int, int]:
    # 解析分页上限
    first = fetch_text(ANIMEXX_CONAN_LIST.format(page=0), headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(first, "html.parser")
    max_page = 0
    for a in soup.select("a[href]"):
        h = a.get("href") or ""
        m = re.search(r"/fanfiction/serie/333_Detektiv_Conan/order_1_(\d+)/", h)
        if m:
            max_page = max(max_page, int(m.group(1)))

    out = {y: 0 for y in YEARS}
    for p in range(0, max_page + 1):
        html = fetch_text(ANIMEXX_CONAN_LIST.format(page=p), headers={"User-Agent": "Mozilla/5.0"})
        soup_p = BeautifulSoup(html, "html.parser")
        for li in soup_p.select("li.ff_big_thumb_box.hat_cover.preview"):
            txt = " ".join(li.get_text(" ", strip=True).split())
            m = re.search(r"Datum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", txt)
            if not m:
                continue
            try:
                y = datetime.strptime(m.group(1), "%d.%m.%Y").year
                if y in out:
                    out[y] += 1
            except Exception:  # noqa: BLE001
                pass
        if p % 15 == 0:
            print(f"[Animexx Conan] page {p}/{max_page}")
        time.sleep(0.05)
    return out


def animexx_matsuda_counts_and_heat() -> tuple[dict[int, int], dict[int, int]]:
    if not ANIMEXX_MATSUDA_META.exists():
        return {y: 0 for y in YEARS}, {y: 0 for y in YEARS}
    df = pd.read_csv(ANIMEXX_MATSUDA_META, encoding="utf-8-sig")
    df["created_dt"] = pd.to_datetime(df["created_dt"], errors="coerce")
    df = df[df["created_dt"].notna()].copy()

    counts = {y: 0 for y in YEARS}
    heat_story: dict[str, int] = {}

    # story热度代理：评论数
    for _, r in df.iterrows():
        y = int(r["created_dt"].year)
        if y in counts:
            counts[y] += 1

        url = str(r.get("url", "") or "")
        if not url:
            continue
        html = fetch_text(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
        m = re.search(r"Kommentare\s*\(\s*(\d+)\s*\)", txt, flags=re.I)
        heat_story[url] = int(m.group(1)) if m else 0
        time.sleep(0.05)

    # 每年 top20 评论和（实际样本很小）
    heats = {y: 0 for y in YEARS}
    for y in YEARS:
        urls = df[df["created_dt"].dt.year == y]["url"].dropna().astype(str).tolist()
        vals = sorted([heat_story.get(u, 0) for u in urls], reverse=True)[:20]
        heats[y] = int(sum(vals))
    return counts, heats


def canonicalize_chars(raw: list[str]) -> list[str]:
    out: list[str] = []
    for t in raw:
        for c, aliases in CHAR_ALIASES.items():
            if any(a in t for a in aliases):
                if c not in out:
                    out.append(c)
                break
    return out


def load_pre_post_protagonist_rows() -> pd.DataFrame:
    rows = []
    # AO3 pre
    p = OUT / "ao3_pre_police_academy_matsuda_works.csv"
    if p.exists():
        df = pd.read_csv(p, encoding="utf-8-sig")
        for _, r in df.iterrows():
            dt = pd.to_datetime(str(r.get("published", "")), errors="coerce")
            if pd.isna(dt):
                continue
            tags = [x.strip() for x in str(r.get("characters", "")).split("|") if x.strip()]
            rows.append({"year": int(dt.year), "chars": canonicalize_chars(tags)})

    # AO3 post raw
    p2 = OUT / "crosssite_post2019_protagonists_raw.csv"
    if p2.exists():
        df = pd.read_csv(p2, encoding="utf-8-sig")
        sub = df[df["site"] == "AO3"]
        for _, r in sub.iterrows():
            y = int(r.get("year", 0) or 0)
            try:
                tags = ast.literal_eval(str(r.get("chars", "[]")))
                if not isinstance(tags, list):
                    tags = []
            except Exception:  # noqa: BLE001
                tags = []
            rows.append({"year": y, "chars": canonicalize_chars([str(t) for t in tags])})

    # Pixiv pre
    pp = OUT / "pixiv_pre_police_matsuda_novels.csv"
    if pp.exists():
        df = pd.read_csv(pp, encoding="utf-8-sig")
        for _, r in df.iterrows():
            dt = pd.to_datetime(str(r.get("createDate", "")), errors="coerce")
            if pd.isna(dt):
                continue
            tags = [x.strip() for x in str(r.get("matched_characters_joined", "")).split("|") if x.strip()]
            rows.append({"year": int(dt.year), "chars": canonicalize_chars(tags)})

    # Pixiv post raw
    if p2.exists():
        df = pd.read_csv(p2, encoding="utf-8-sig")
        sub = df[df["site"] == "Pixiv"]
        for _, r in sub.iterrows():
            y = int(r.get("year", 0) or 0)
            try:
                tags = ast.literal_eval(str(r.get("chars", "[]")))
                if not isinstance(tags, list):
                    tags = []
            except Exception:  # noqa: BLE001
                tags = []
            rows.append({"year": y, "chars": canonicalize_chars([str(t) for t in tags])})

    # Animexx pre
    ap = OUT / "animexx_pre_police_story_meta.csv"
    if ap.exists():
        df = pd.read_csv(ap, encoding="utf-8-sig")
        for _, r in df.iterrows():
            dt = pd.to_datetime(str(r.get("created_dt", "")), errors="coerce")
            if pd.isna(dt):
                continue
            tags = [x.strip() for x in str(r.get("main_characters", "")).split("|") if x.strip()]
            rows.append({"year": int(dt.year), "chars": canonicalize_chars(tags)})

    # Animexx post raw
    if p2.exists():
        df = pd.read_csv(p2, encoding="utf-8-sig")
        sub = df[df["site"] == "Animexx"]
        for _, r in sub.iterrows():
            y = int(r.get("year", 0) or 0)
            try:
                tags = ast.literal_eval(str(r.get("chars", "[]")))
                if not isinstance(tags, list):
                    tags = []
            except Exception:  # noqa: BLE001
                tags = []
            rows.append({"year": y, "chars": canonicalize_chars([str(t) for t in tags])})

    return pd.DataFrame(rows)


def main() -> None:
    setup_font()

    # -------- 三折线（按你定义） --------
    # AO3 matsuda 与 top20 heat
    ao3_df = pd.read_csv(AO3_MATSUDA_CSV, encoding="utf-8-sig")
    ao3_m_count = {int(r["year"]): int(r["works_total"]) for _, r in ao3_df.iterrows() if int(r["year"]) in YEARS}
    ao3_m_heat = {int(r["year"]): int(r["top20_hits_sum"]) for _, r in ao3_df.iterrows() if int(r["year"]) in YEARS}
    ao3_c_count = ao3_conan_yearly_counts()

    # Pixiv matsuda/conan
    pix_m_count, pix_m_heat = pixiv_yearly_counts_and_heat(PIXIV_MATSUDA)
    pix_c_count, _ = pixiv_yearly_counts_and_heat(PIXIV_CONAN)

    # Animexx matsuda/conan
    ani_m_count, ani_m_heat = animexx_matsuda_counts_and_heat()
    ani_c_count = animexx_conan_yearly_counts()

    agg_rows = []
    for y in YEARS:
        matsuda_total = ao3_m_count.get(y, 0) + pix_m_count.get(y, 0) + ani_m_count.get(y, 0)
        top20_heat_total = ao3_m_heat.get(y, 0) + pix_m_heat.get(y, 0) + ani_m_heat.get(y, 0)
        conan_total = ao3_c_count.get(y, 0) + pix_c_count.get(y, 0) + ani_c_count.get(y, 0)
        share = matsuda_total / conan_total if conan_total > 0 else 0.0
        agg_rows.append(
            {
                "year": y,
                "matsuda_total_works_3sites": matsuda_total,
                "matsuda_total_top20_heat_3sites": top20_heat_total,
                "matsuda_share_in_conan_3sites": share,
                "conan_total_works_3sites": conan_total,
            }
        )

    agg = pd.DataFrame(agg_rows)
    agg_csv = OUT / "crosssite_joint_three_lines_raw.csv"
    agg.to_csv(agg_csv, index=False, encoding="utf-8-sig")

    # 归一化为比例后同图（避免量纲差异）
    p = agg.copy()
    p["works_norm"] = p["matsuda_total_works_3sites"] / max(1, p["matsuda_total_works_3sites"].max())
    p["heat_norm"] = p["matsuda_total_top20_heat_3sites"] / max(1, p["matsuda_total_top20_heat_3sites"].max())
    p["share_norm"] = p["matsuda_share_in_conan_3sites"] / max(1e-9, p["matsuda_share_in_conan_3sites"].max())

    plt.figure(figsize=(10.2, 5.8))
    plt.plot(p["year"], p["works_norm"], marker="o", linewidth=2, label="同人文总数（归一化）")
    plt.plot(p["year"], p["heat_norm"], marker="s", linewidth=2, label="Top20热度总量（归一化）")
    plt.plot(p["year"], p["share_norm"], marker="^", linewidth=2, label="占柯南圈层比例（归一化）")
    plt.axvline(POLICE_DATE, linestyle="--", alpha=0.4, label="警察学校篇起点 2019-10-01")
    plt.axvline(MOVIE_DATE, linestyle="--", alpha=0.4, label="万圣节的新娘 2022-04-15")
    plt.title("三站联合三折线：总量-热度-占比（2010年至今）")
    plt.xlabel("年份")
    plt.ylabel("比例（各指标归一化）")
    plt.grid(alpha=0.2, linestyle="--")
    plt.legend()
    plt.tight_layout()
    line_png = OUT / "crosssite_joint_three_lines_corrected.png"
    plt.savefig(line_png, dpi=180)
    plt.close()

    # -------- 主角比例堆叠图（剔除松田，Top5+其他）--------
    prot = load_pre_post_protagonist_rows()
    prot_path = OUT / "crosssite_joint_protagonists_all_raw.csv"
    prot.to_csv(prot_path, index=False, encoding="utf-8-sig")

    by_year: dict[int, Counter[str]] = defaultdict(Counter)
    total = Counter()
    for _, r in prot.iterrows():
        y = int(r["year"])
        chars = [c for c in (r["chars"] or []) if c != "松田阵平"]
        for c in chars:
            by_year[y][c] += 1
            total[c] += 1
    top5 = [c for c, _ in total.most_common(5)]

    stack_rows = []
    for y in YEARS:
        c = by_year.get(y, Counter())
        denom = sum(c.values())
        row = {"year": y}
        if denom <= 0:
            for t in top5:
                row[t] = 0.0
            row["其他"] = 0.0
        else:
            used = 0
            for t in top5:
                v = c.get(t, 0)
                row[t] = v / denom
                used += v
            row["其他"] = max(0.0, (denom - used) / denom)
        stack_rows.append(row)

    stack = pd.DataFrame(stack_rows)
    stack["top5_sum"] = stack[[c for c in stack.columns if c not in ("year", "其他", "top5_sum")]].sum(axis=1)
    stack_csv = OUT / "crosssite_joint_stack_top5_corrected.csv"
    stack.to_csv(stack_csv, index=False, encoding="utf-8-sig")

    cols = [c for c in stack.columns if c not in ("year", "top5_sum")]
    x = stack["year"].tolist()
    ys = [stack[c].tolist() for c in cols]
    plt.figure(figsize=(10.4, 6.0))
    plt.stackplot(x, ys, labels=cols, alpha=0.88)
    plt.axvline(POLICE_DATE, linestyle="--", alpha=0.4)
    plt.axvline(MOVIE_DATE, linestyle="--", alpha=0.4)
    plt.title("三站联合：剔除松田后的主角占比堆叠图（Top5+其他）")
    plt.xlabel("年份")
    plt.ylabel("比例（总和=1）")
    plt.ylim(0, 1)
    plt.grid(alpha=0.2, linestyle="--")
    plt.legend(loc="upper left", ncol=3)
    plt.tight_layout()
    stack_png = OUT / "crosssite_joint_stack_top5_corrected.png"
    plt.savefig(stack_png, dpi=180)
    plt.close()

    # 节点表
    node_csv = OUT / "crosssite_joint_node_table_corrected.csv"
    stack.to_csv(node_csv, index=False, encoding="utf-8-sig")

    summary = {
        "years": [YEARS[0], YEARS[-1]],
        "top5_excluding_matsuda": top5,
        "files": {
            "three_lines_raw_csv": str(agg_csv),
            "three_lines_plot": str(line_png),
            "stack_csv": str(stack_csv),
            "stack_plot": str(stack_png),
            "node_table_csv": str(node_csv),
            "protagonists_raw_csv": str(prot_path),
        },
    }
    (OUT / "crosssite_joint_corrected_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
