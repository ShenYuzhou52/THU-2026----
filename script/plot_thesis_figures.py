from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


BASE = Path(__file__).resolve().parent
EMP = BASE / "empirical_output"
WC = BASE / "matsuda_wordcloud_output"
OUT = EMP / "figures_for_thesis"
OUT.mkdir(parents=True, exist_ok=True)


def setup_style() -> None:
    # Windows 常见中文字体兜底
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def fig_top20_tfidf() -> None:
    df = pd.read_csv(WC / "matsuda_absolute_merged_tfidf_top.csv", encoding="utf-8-sig").head(20)
    df = df.iloc[::-1]
    plt.figure(figsize=(10, 8))
    plt.barh(df["词"], df["score"])
    plt.title("松田相关语料 Top20 关键词（绝对化 TF-IDF）")
    plt.xlabel("TF-IDF score")
    plt.ylabel("词项")
    plt.tight_layout()
    plt.savefig(OUT / "fig1_top20_tfidf_bar.png", dpi=180)
    plt.close()


def fig_mourning_keywords() -> None:
    df = pd.read_csv(EMP / "mourning_keyword_counts.csv", encoding="utf-8-sig")
    df = df.sort_values("命中评论数", ascending=True)
    plt.figure(figsize=(8.5, 5.8))
    plt.barh(df["关键词"], df["命中评论数"])
    plt.title("评论区哀悼词频分布")
    plt.xlabel("命中评论数")
    plt.ylabel("关键词")
    plt.tight_layout()
    plt.savefig(OUT / "fig2_mourning_keywords_bar.png", dpi=180)
    plt.close()


def fig_scene_vs_non_scene() -> None:
    df = pd.read_csv(EMP / "scene_related_uplift.csv", encoding="utf-8-sig")
    idx = range(len(df))
    width = 0.25
    plt.figure(figsize=(9, 5.5))
    plt.bar([i - width for i in idx], df["平均播放"], width=width, label="平均播放")
    plt.bar(idx, df["平均评论"], width=width, label="平均评论")
    plt.bar([i + width for i in idx], df["平均弹幕"], width=width, label="平均弹幕")
    plt.xticks(list(idx), df["scene_related"])
    plt.title("场景相关视频 vs 非场景视频：互动强度对比")
    plt.ylabel("均值")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT / "fig3_scene_vs_non_scene_grouped_bar.png", dpi=180)
    plt.close()


def fig_bili_yearly() -> None:
    df = pd.read_csv(EMP / "matsuda_fanwork_yearly.csv", encoding="utf-8-sig")
    plt.figure(figsize=(8.8, 4.8))
    plt.plot(df["year"], df["二创投稿量"], marker="o", linewidth=2, label="二创投稿量")
    plt.title("B站：松田相关二创年度投稿量")
    plt.xlabel("年份")
    plt.ylabel("投稿量")
    plt.grid(alpha=0.25, linestyle="--")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT / "fig4_bilibili_yearly_works_line.png", dpi=180)
    plt.close()


def fig_ao3_works() -> None:
    df = pd.read_csv(EMP / "ao3_matsuda_yearly_scan.csv", encoding="utf-8-sig")
    df = df[df["works_total"] > 0]
    plt.figure(figsize=(8.8, 4.8))
    plt.plot(df["year"], df["works_total"], marker="o", linewidth=2)
    plt.title("AO3：Matsuda Jinpei 年度作品量")
    plt.xlabel("年份")
    plt.ylabel("Works")
    plt.grid(alpha=0.25, linestyle="--")
    plt.tight_layout()
    plt.savefig(OUT / "fig5_ao3_yearly_works_line.png", dpi=180)
    plt.close()


def fig_ao3_hits() -> None:
    df = pd.read_csv(EMP / "ao3_matsuda_yearly_scan.csv", encoding="utf-8-sig")
    df = df[df["works_total"] > 0]
    plt.figure(figsize=(8.8, 4.8))
    plt.plot(df["year"], df["top20_hits_sum"], marker="s", linewidth=2, color="#e67e22")
    plt.title("AO3：年度流量代理（Top20 Hits Sum）")
    plt.xlabel("年份")
    plt.ylabel("Top20 hits sum")
    plt.grid(alpha=0.25, linestyle="--")
    plt.tight_layout()
    plt.savefig(OUT / "fig6_ao3_yearly_hits_line.png", dpi=180)
    plt.close()


def fig_ao3_dual_axis() -> None:
    df = pd.read_csv(EMP / "ao3_matsuda_yearly_scan.csv", encoding="utf-8-sig")
    df = df[df["works_total"] > 0]

    fig, ax1 = plt.subplots(figsize=(9.2, 5.2))
    ax2 = ax1.twinx()

    l1 = ax1.plot(df["year"], df["works_total"], marker="o", linewidth=2, label="Works total", color="#2e86de")
    l2 = ax2.plot(df["year"], df["top20_hits_sum"], marker="s", linewidth=2, label="Top20 hits sum", color="#e67e22")

    ax1.set_xlabel("年份")
    ax1.set_ylabel("Works total", color="#2e86de")
    ax2.set_ylabel("Top20 hits sum", color="#e67e22")
    ax1.set_title("AO3：作品产量与流量代理双轴图")
    ax1.grid(alpha=0.25, linestyle="--")

    lines = l1 + l2
    labels = [ln.get_label() for ln in lines]
    ax1.legend(lines, labels, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "fig7_ao3_dual_axis_works_hits.png", dpi=180)
    plt.close(fig)


def main() -> None:
    setup_style()
    fig_top20_tfidf()
    fig_mourning_keywords()
    fig_scene_vs_non_scene()
    fig_bili_yearly()
    fig_ao3_works()
    fig_ao3_hits()
    fig_ao3_dual_axis()
    print(f"输出完成：{OUT}")


if __name__ == "__main__":
    main()
