import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "empirical_output"
OUT_DIR.mkdir(exist_ok=True)

BASE_URL = "https://archiveofourown.org/tags/Matsuda%20Jinpei/works"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE_SIZE = 20


@dataclass
class WorkRow:
    work_id: str
    title: str
    published: str
    words: int
    kudos: int
    hits: int
    comments: int
    bookmarks: int


def parse_int(text: Optional[str]) -> int:
    if not text:
        return 0
    txt = text.replace(",", "").strip()
    m = re.search(r"\d+", txt)
    return int(m.group(0)) if m else 0


def fetch_html(url: str, retries: int = 3, timeout: int = 25) -> str:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def get_total_works_and_pages(first_html: str) -> tuple[int, int]:
    soup = BeautifulSoup(first_html, "html.parser")
    heading = soup.select_one("h2.heading")
    total_works = 0
    if heading:
        total_works = parse_int(heading.get_text(" ", strip=True))
    pages = max(1, (total_works + PAGE_SIZE - 1) // PAGE_SIZE)
    return total_works, pages


def parse_page(html: str) -> list[WorkRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[WorkRow] = []
    for li in soup.select("li.work.blurb.group"):
        work_id = (li.get("id") or "").replace("work_", "").strip()
        title_el = li.select_one("h4.heading a")
        title = title_el.get_text(strip=True) if title_el else ""
        date_el = li.select_one("p.datetime")
        published = date_el.get_text(strip=True) if date_el else ""

        words = parse_int((li.select_one("dd.words") or {}).get_text(strip=True) if li.select_one("dd.words") else "0")
        kudos = parse_int((li.select_one("dd.kudos") or {}).get_text(strip=True) if li.select_one("dd.kudos") else "0")
        hits = parse_int((li.select_one("dd.hits") or {}).get_text(strip=True) if li.select_one("dd.hits") else "0")
        comments = parse_int((li.select_one("dd.comments") or {}).get_text(strip=True) if li.select_one("dd.comments") else "0")
        bookmarks = parse_int((li.select_one("dd.bookmarks") or {}).get_text(strip=True) if li.select_one("dd.bookmarks") else "0")

        rows.append(
            WorkRow(
                work_id=work_id,
                title=title,
                published=published,
                words=words,
                kudos=kudos,
                hits=hits,
                comments=comments,
                bookmarks=bookmarks,
            )
        )
    return rows


def plot_yearly(df_year: pd.DataFrame, out: Path) -> None:
    plt.figure(figsize=(9, 4.8))
    plt.plot(df_year["year"], df_year["works"], marker="o", linewidth=2, label="Works")
    plt.plot(df_year["year"], df_year["hits_total"], marker="s", linewidth=2, label="Hits (total)")
    plt.title("AO3 Matsuda Jinpei Works by Year")
    plt.xlabel("Year")
    plt.ylabel("Count")
    plt.grid(alpha=0.25, linestyle="--")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def main() -> None:
    first_url = f"{BASE_URL}?page=1&view_adult=true"
    first_html = fetch_html(first_url)
    total_works, total_pages = get_total_works_and_pages(first_html)
    print(f"total_works={total_works}, total_pages={total_pages}")

    rows: list[WorkRow] = []
    rows.extend(parse_page(first_html))

    for page in range(2, total_pages + 1):
        url = f"{BASE_URL}?page={page}&view_adult=true"
        html = fetch_html(url)
        rows.extend(parse_page(html))
        if page % 5 == 0:
            print(f"fetched page {page}/{total_pages}")
        time.sleep(0.35)

    # 去重（以 work_id 为准）
    seen = set()
    unique_rows: list[WorkRow] = []
    for r in rows:
        if not r.work_id or r.work_id in seen:
            continue
        seen.add(r.work_id)
        unique_rows.append(r)

    df = pd.DataFrame([asdict(r) for r in unique_rows])
    df["published_dt"] = pd.to_datetime(df["published"], errors="coerce")
    df = df.dropna(subset=["published_dt"]).copy()
    df["year"] = df["published_dt"].dt.year.astype(int)
    df["month"] = df["published_dt"].dt.to_period("M").astype(str)

    year_stats = (
        df.groupby("year")
        .agg(
            works=("work_id", "count"),
            hits_total=("hits", "sum"),
            kudos_total=("kudos", "sum"),
            comments_total=("comments", "sum"),
            bookmarks_total=("bookmarks", "sum"),
            words_total=("words", "sum"),
        )
        .reset_index()
        .sort_values("year")
    )

    month_stats = (
        df.groupby("month")
        .agg(
            works=("work_id", "count"),
            hits_total=("hits", "sum"),
            kudos_total=("kudos", "sum"),
        )
        .reset_index()
        .sort_values("month")
    )

    works_path = OUT_DIR / "ao3_matsuda_works.csv"
    year_path = OUT_DIR / "ao3_matsuda_yearly.csv"
    month_path = OUT_DIR / "ao3_matsuda_monthly.csv"
    fig_path = OUT_DIR / "ao3_matsuda_yearly.png"
    json_path = OUT_DIR / "ao3_matsuda_summary.json"

    df.to_csv(works_path, index=False, encoding="utf-8-sig")
    year_stats.to_csv(year_path, index=False, encoding="utf-8-sig")
    month_stats.to_csv(month_path, index=False, encoding="utf-8-sig")
    plot_yearly(year_stats, fig_path)

    nonzero_months = int((month_stats["works"] > 0).sum()) if not month_stats.empty else 0
    all_months = int(len(month_stats))
    summary = {
        "tag": "Matsuda Jinpei",
        "total_works_reported": int(total_works),
        "total_works_crawled": int(len(df)),
        "year_min": int(year_stats["year"].min()) if not year_stats.empty else None,
        "year_max": int(year_stats["year"].max()) if not year_stats.empty else None,
        "active_months": nonzero_months,
        "months_span": all_months,
        "coverage_ratio_active_months": round(nonzero_months / all_months, 4) if all_months else 0.0,
        "files": {
            "works_csv": str(works_path),
            "yearly_csv": str(year_path),
            "monthly_csv": str(month_path),
            "yearly_chart": str(fig_path),
        },
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
