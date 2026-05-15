import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "empirical_output"
OUT_DIR.mkdir(exist_ok=True)

BASE = "https://archive.transformativeworks.org/tags/Matsuda%20Jinpei/works"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CHECKPOINT = OUT_DIR / "ao3_matsuda_yearly_scan_checkpoint.csv"


def parse_int(text: Optional[str]) -> int:
    if not text:
        return 0
    m = re.search(r"\d[\d,]*", text)
    return int(m.group(0).replace(",", "")) if m else 0


def fetch(url: str, retries: int = 6, timeout: int = 35) -> str:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < retries - 1:
                time.sleep((i + 1) * 2)
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def build_url(year: int, sort_column: str) -> str:
    params = {
        "page": 1,
        "work_search[date_from]": f"{year}-01-01",
        "work_search[date_to]": f"{year}-12-31",
        "work_search[sort_column]": sort_column,
    }
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def parse_heading_total(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h2.heading")
    if not h:
        return 0
    text = h.get_text(" ", strip=True)
    # heading 常见形态： "1 - 20 of 132 Works in Matsuda Jinpei"
    m = re.search(r"of\s+([\d,]+)\s+Works", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    # 兜底
    return parse_int(text)


def parse_work_metrics(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for li in soup.select("li.work.blurb.group"):
        title_el = li.select_one("h4.heading a")
        rows.append(
            {
                "title": title_el.get_text(strip=True) if title_el else "",
                "hits": parse_int(li.select_one("dd.hits").get_text(strip=True) if li.select_one("dd.hits") else "0"),
                "kudos": parse_int(li.select_one("dd.kudos").get_text(strip=True) if li.select_one("dd.kudos") else "0"),
                "comments": parse_int(li.select_one("dd.comments").get_text(strip=True) if li.select_one("dd.comments") else "0"),
                "bookmarks": parse_int(li.select_one("dd.bookmarks").get_text(strip=True) if li.select_one("dd.bookmarks") else "0"),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    current_year = datetime.now().year
    years = list(range(2010, current_year + 1))
    out_rows = []
    finished_years = set()
    if CHECKPOINT.exists():
        ck = pd.read_csv(CHECKPOINT, encoding="utf-8-sig")
        out_rows = ck.to_dict(orient="records")
        finished_years = set(int(y) for y in ck["year"].tolist())

    for y in years:
        if y in finished_years:
            continue
        created_url = build_url(y, "created_at")
        hits_url = build_url(y, "hits")
        row = {"year": y}
        try:
            created_html = fetch(created_url)
            total_works = parse_heading_total(created_html)
            created_df = parse_work_metrics(created_html)
            row.update(
                {
                    "works_total": int(total_works),
                    "sample_size_latest20": int(len(created_df)),
                    "latest20_hits_sum": int(created_df["hits"].sum()) if not created_df.empty else 0,
                    "latest20_kudos_sum": int(created_df["kudos"].sum()) if not created_df.empty else 0,
                    "latest20_comments_sum": int(created_df["comments"].sum()) if not created_df.empty else 0,
                }
            )
        except Exception as e:  # noqa: BLE001
            row.update(
                {
                    "works_total": -1,
                    "sample_size_latest20": 0,
                    "latest20_hits_sum": 0,
                    "latest20_kudos_sum": 0,
                    "latest20_comments_sum": 0,
                    "error_created": str(e),
                }
            )

        # 热门前20流量代理，不阻塞主流程
        try:
            hits_html = fetch(hits_url)
            hits_df = parse_work_metrics(hits_html)
            row.update(
                {
                    "top20_hits_sum": int(hits_df["hits"].sum()) if not hits_df.empty else 0,
                    "top20_kudos_sum": int(hits_df["kudos"].sum()) if not hits_df.empty else 0,
                    "top20_comments_sum": int(hits_df["comments"].sum()) if not hits_df.empty else 0,
                    "top20_bookmarks_sum": int(hits_df["bookmarks"].sum()) if not hits_df.empty else 0,
                }
            )
        except Exception as e:  # noqa: BLE001
            row.update(
                {
                    "top20_hits_sum": 0,
                    "top20_kudos_sum": 0,
                    "top20_comments_sum": 0,
                    "top20_bookmarks_sum": 0,
                    "error_hits": str(e),
                }
            )

        out_rows.append(row)
        pd.DataFrame(out_rows).sort_values("year").to_csv(CHECKPOINT, index=False, encoding="utf-8-sig")
        print(f"year={y}, works={row.get('works_total')}, top20_hits_sum={row.get('top20_hits_sum')}")
        time.sleep(0.5)

    df = pd.DataFrame(out_rows)
    df_nonzero = df[df["works_total"] > 0].copy()

    csv_path = OUT_DIR / "ao3_matsuda_yearly_scan.csv"
    chart_path = OUT_DIR / "ao3_matsuda_yearly_scan.png"
    summary_path = OUT_DIR / "ao3_matsuda_yearly_scan_summary.json"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    if not df_nonzero.empty:
        plt.figure(figsize=(9, 4.8))
        plt.plot(df_nonzero["year"], df_nonzero["works_total"], marker="o", linewidth=2, label="Works total")
        plt.plot(df_nonzero["year"], df_nonzero["top20_hits_sum"], marker="s", linewidth=2, label="Top20 hits sum")
        plt.title("AO3 Matsuda Jinpei: Yearly Works and Traffic Proxy")
        plt.xlabel("Year")
        plt.ylabel("Count")
        plt.grid(alpha=0.25, linestyle="--")
        plt.legend()
        plt.tight_layout()
        plt.savefig(chart_path, dpi=180)
        plt.close()

    active_years = int((df["works_total"] > 0).sum())
    span_years = int(len(df))
    summary = {
        "tag": "Matsuda Jinpei",
        "year_range": [years[0], years[-1]],
        "active_years_nonzero": active_years,
        "year_span": span_years,
        "active_year_ratio": round(active_years / span_years, 4) if span_years else 0.0,
        "first_nonzero_year": int(df_nonzero["year"].min()) if not df_nonzero.empty else None,
        "latest_year": int(df_nonzero["year"].max()) if not df_nonzero.empty else None,
        "files": {
            "yearly_scan_csv": str(csv_path),
            "yearly_scan_chart": str(chart_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
