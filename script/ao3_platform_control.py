import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "empirical_output"
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}

MATSUDA_BASE = "https://archive.transformativeworks.org/tags/Matsuda%20Jinpei/works"
CONAN_BASE = "https://archive.transformativeworks.org/tags/%E5%90%8D%E6%8E%A2%E5%81%B5%E3%82%B3%E3%83%8A%E3%83%B3%20%7C%20Detective%20Conan%20%7C%20Case%20Closed/works"


def pick_font_path() -> str | None:
    for p in [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\SimHei.ttf"),
    ]:
        if p.exists():
            return str(p)
    return None


def setup_cn_font() -> None:
    font = pick_font_path()
    if font:
        name = font_manager.FontProperties(fname=font).get_name()
        plt.rcParams["font.family"] = name
    plt.rcParams["axes.unicode_minus"] = False


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
                time.sleep((i + 1) * 1.5)
    raise RuntimeError(f"fetch failed: {url}, err={last_err}")


def build_url(base: str, year: int, sort_column: str) -> str:
    params = {
        "page": 1,
        "work_search[date_from]": f"{year}-01-01",
        "work_search[date_to]": f"{year}-12-31",
        "work_search[sort_column]": sort_column,
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_heading_total(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h2.heading")
    if not h:
        return 0
    text = h.get_text(" ", strip=True)
    m = re.search(r"of\s+([\d,]+)\s+Works", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return parse_int(text)


def parse_top20_hits_sum(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    total = 0
    for li in soup.select("li.work.blurb.group"):
        dd = li.select_one("dd.hits")
        total += parse_int(dd.get_text(strip=True) if dd else "0")
    return total


def scan_tag_yearly(tag_name: str, base: str, years: list[int]) -> pd.DataFrame:
    rows = []
    for y in years:
        created_url = build_url(base, y, "created_at")
        hits_url = build_url(base, y, "hits")

        try:
            created_html = fetch(created_url)
            works_total = parse_heading_total(created_html)
        except Exception:  # noqa: BLE001
            works_total = -1

        try:
            hits_html = fetch(hits_url)
            top20_hits_sum = parse_top20_hits_sum(hits_html)
        except Exception:  # noqa: BLE001
            top20_hits_sum = -1

        rows.append(
            {
                "year": y,
                "tag": tag_name,
                "works_total": int(works_total),
                "top20_hits_sum": int(top20_hits_sum),
            }
        )
        print(f"[{tag_name}] {y}: works={works_total}, top20_hits_sum={top20_hits_sum}")
        time.sleep(0.4)
    return pd.DataFrame(rows)


def main() -> None:
    setup_cn_font()
    current_year = datetime.now().year
    years = list(range(2016, current_year + 1))

    matsuda_df = scan_tag_yearly("Matsuda Jinpei", MATSUDA_BASE, years)
    conan_df = scan_tag_yearly("Detective Conan", CONAN_BASE, years)

    matsuda_csv = OUT / "ao3_matsuda_yearly_scan.csv"
    if matsuda_csv.exists():
        # 优先采用你已跑好的松田序列，只在缺年时用新抓值兜底
        old = pd.read_csv(matsuda_csv, encoding="utf-8-sig")
        old = old[["year", "works_total", "top20_hits_sum"]].copy()
        old = old.rename(
            columns={
                "works_total": "works_total_old",
                "top20_hits_sum": "top20_hits_sum_old",
            }
        )
        matsuda_df = matsuda_df.merge(old, on="year", how="left")
        matsuda_df["works_total"] = matsuda_df["works_total_old"].fillna(matsuda_df["works_total"])
        matsuda_df["top20_hits_sum"] = matsuda_df["top20_hits_sum_old"].fillna(matsuda_df["top20_hits_sum"])
        matsuda_df = matsuda_df[["year", "tag", "works_total", "top20_hits_sum"]]

    merged = matsuda_df.merge(
        conan_df[["year", "works_total", "top20_hits_sum"]],
        on="year",
        suffixes=("_matsuda", "_conan"),
    )

    # 控制平台/圈层年度波动的归一化指标
    merged["works_share_in_conan"] = merged["works_total_matsuda"] / merged["works_total_conan"].replace(0, pd.NA)
    merged["hits_share_in_conan"] = merged["top20_hits_sum_matsuda"] / merged["top20_hits_sum_conan"].replace(0, pd.NA)

    merged["matsuda_top20_mean_hits"] = merged["top20_hits_sum_matsuda"] / merged["works_total_matsuda"].clip(lower=1).clip(upper=20)
    merged["conan_top20_mean_hits"] = merged["top20_hits_sum_conan"] / merged["works_total_conan"].clip(lower=1).clip(upper=20)
    merged["relative_mean_hits_vs_conan"] = merged["matsuda_top20_mean_hits"] / merged["conan_top20_mean_hits"].replace(0, pd.NA)

    merged_csv = OUT / "ao3_matsuda_vs_conan_controlled.csv"
    merged.to_csv(merged_csv, index=False, encoding="utf-8-sig")

    # 图1：占比趋势
    fig1 = OUT / "ao3_control_share_trend.png"
    plt.figure(figsize=(9.2, 5.0))
    plt.plot(merged["year"], merged["works_share_in_conan"], marker="o", label="作品占柯南圈层比例")
    plt.plot(merged["year"], merged["hits_share_in_conan"], marker="s", label="Top20点击占柯南圈层比例")
    plt.title("AO3控制后指标：松田在柯南圈层中的占比趋势")
    plt.xlabel("年份")
    plt.ylabel("占比")
    plt.grid(alpha=0.25, linestyle="--")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig1, dpi=180)
    plt.close()

    # 图2：单位作品流量相对值
    fig2 = OUT / "ao3_control_relative_mean_hits.png"
    plt.figure(figsize=(9.2, 5.0))
    plt.plot(merged["year"], merged["relative_mean_hits_vs_conan"], marker="o")
    plt.axhline(1.0, linestyle="--", alpha=0.5)
    plt.title("AO3控制后指标：松田单位作品流量相对值（对柯南圈层）")
    plt.xlabel("年份")
    plt.ylabel("相对值（=1 为圈层均值）")
    plt.grid(alpha=0.25, linestyle="--")
    plt.tight_layout()
    plt.savefig(fig2, dpi=180)
    plt.close()

    # 图3：三条折线合并
    fig3 = OUT / "ao3_control_three_lines.png"
    plt.figure(figsize=(9.6, 5.2))
    plt.plot(merged["year"], merged["works_share_in_conan"], marker="o", label="作品占比（松田/柯南）")
    plt.plot(merged["year"], merged["hits_share_in_conan"], marker="s", label="流量占比（Top20点击）")
    plt.plot(merged["year"], merged["relative_mean_hits_vs_conan"], marker="^", label="单位作品流量相对值")
    plt.title("AO3 控制后指标三线图（已控制平台圈层波动）")
    plt.xlabel("年份")
    plt.ylabel("比例/相对值")
    plt.grid(alpha=0.25, linestyle="--")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig3, dpi=180)
    plt.close()

    summary = {
        "years": [int(merged["year"].min()), int(merged["year"].max())],
        "files": {
            "controlled_csv": str(merged_csv),
            "share_trend_fig": str(fig1),
            "relative_mean_hits_fig": str(fig2),
            "three_lines_fig": str(fig3),
        },
    }
    (OUT / "ao3_control_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
