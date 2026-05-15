import json
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "empirical_output"
OUT_DIR.mkdir(exist_ok=True)

# 评论区仪式化哀悼关键词（按“评论条数命中”计数）
MOURNING_KEYWORDS = [
    "意难平",
    "白月光",
    "致敬",
    "安息",
    "哭",
    "泪目",
    "大哭",
    "刀",
    "难过",
    "天堂",
    "祭",
    "缅怀",
    "想你",
]

SCENE_TITLE_PATTERN = r"摩天轮|1200万|人质|短信|喜欢上你|殉职|意难平|白月光|警视厅"


def load_comments() -> pd.DataFrame:
    files = sorted(ROOT.glob("comments*.csv"))
    frames: list[pd.DataFrame] = []
    for f in files:
        # comments_new.csv 几乎为空，忽略
        if f.name == "comments_new.csv":
            continue
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            if "评论内容" in df.columns:
                frames.append(df[["视频标题", "BVID", "评论内容"]].copy())
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["视频标题", "BVID", "评论内容"])
    out = pd.concat(frames, ignore_index=True)
    out["评论内容"] = out["评论内容"].fillna("").astype(str).str.strip()
    out = out[out["评论内容"] != ""]
    return out


def keyword_hits(texts: pd.Series, keywords: list[str]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for kw in keywords:
        hits[kw] = int(texts.str.contains(re.escape(kw), regex=True).sum())
    return hits


def build_yearly_fanwork_stats() -> pd.DataFrame:
    f = ROOT / "stats_tag_matsuda.csv"
    df = pd.read_csv(f, encoding="utf-8-sig")
    dt = pd.to_datetime(df["发布时间_ISO8601_北京时间"], errors="coerce")
    df = df.assign(year=dt.dt.year).dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    yearly = (
        df.groupby("year")
        .agg(
            二创投稿量=("BV号", "count"),
            总播放量=("播放量", "sum"),
            总评论量=("评论数_reply", "sum"),
            总弹幕量=("弹幕数", "sum"),
        )
        .reset_index()
        .sort_values("year")
    )
    return yearly


def plot_yearly_fanwork(yearly: pd.DataFrame) -> Path:
    out = OUT_DIR / "matsuda_fanwork_yearly.png"
    plt.figure(figsize=(8.5, 4.6))
    plt.plot(yearly["year"], yearly["二创投稿量"], marker="o", linewidth=2)
    for _, r in yearly.iterrows():
        plt.text(r["year"], r["二创投稿量"] + 1, str(int(r["二创投稿量"])), ha="center", fontsize=9)
    plt.title("松田阵平相关二创投稿量（按年）")
    plt.xlabel("年份")
    plt.ylabel("投稿量（条）")
    plt.grid(alpha=0.25, linestyle="--")
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()
    return out


def scene_uplift_from_video_meta() -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.read_csv(ROOT / "stats_tag_matsuda.csv", encoding="utf-8-sig")
    df["标题"] = df["标题"].fillna("").astype(str)
    df["scene_related"] = df["标题"].str.contains(SCENE_TITLE_PATTERN, regex=True, na=False)

    compare = (
        df.groupby("scene_related")
        .agg(
            视频数=("BV号", "count"),
            平均播放=("播放量", "mean"),
            平均评论=("评论数_reply", "mean"),
            平均弹幕=("弹幕数", "mean"),
            评论中位数=("评论数_reply", "median"),
            弹幕中位数=("弹幕数", "median"),
        )
        .reset_index()
    )
    compare["scene_related"] = compare["scene_related"].map({True: "场景相关视频", False: "非场景视频"})

    related = compare[compare["scene_related"] == "场景相关视频"].iloc[0]
    base = compare[compare["scene_related"] == "非场景视频"].iloc[0]
    uplift = {
        "评论均值提升倍数": round(float(related["平均评论"]) / max(float(base["平均评论"]), 1e-9), 2),
        "弹幕均值提升倍数": round(float(related["平均弹幕"]) / max(float(base["平均弹幕"]), 1e-9), 2),
        "播放均值提升倍数": round(float(related["平均播放"]) / max(float(base["平均播放"]), 1e-9), 2),
    }
    return compare, uplift


def main() -> None:
    report: dict[str, Any] = {}

    # 1) 评论区仪式化哀悼
    comments_df = load_comments()
    total_comments = int(len(comments_df))
    hits = keyword_hits(comments_df["评论内容"], MOURNING_KEYWORDS)
    hit_total = sum(hits.values())
    report["comments_total"] = total_comments
    report["mourning_keyword_hits"] = hits
    report["mourning_keyword_hits_total"] = int(hit_total)
    report["mourning_keyword_density_per_100_comments"] = round(hit_total / max(total_comments, 1) * 100, 2)

    pd.DataFrame(
        [{"关键词": k, "命中评论数": v} for k, v in sorted(hits.items(), key=lambda x: x[1], reverse=True)]
    ).to_csv(OUT_DIR / "mourning_keyword_counts.csv", index=False, encoding="utf-8-sig")

    # 2) 二创生产的持续性（按年）
    yearly = build_yearly_fanwork_stats()
    yearly.to_csv(OUT_DIR / "matsuda_fanwork_yearly.csv", index=False, encoding="utf-8-sig")
    yearly_fig = plot_yearly_fanwork(yearly)
    report["fanwork_yearly"] = yearly.to_dict(orient="records")
    report["fanwork_yearly_chart"] = str(yearly_fig)

    # 3) 用“场景相关视频”对照组证明RIP-ing聚集效应
    compare_df, uplift = scene_uplift_from_video_meta()
    compare_df.to_csv(OUT_DIR / "scene_related_uplift.csv", index=False, encoding="utf-8-sig")
    report["scene_related_comparison"] = compare_df.to_dict(orient="records")
    report["scene_related_uplift"] = uplift

    (OUT_DIR / "empirical_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
