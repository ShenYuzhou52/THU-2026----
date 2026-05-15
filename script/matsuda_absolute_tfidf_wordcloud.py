# -*- coding: utf-8 -*-
"""
绝对化 TF-IDF：
  1. 背景词库：名侦探柯南 tag 背景弹幕评论 * R + conanpedia 中文文本
  2. 目标语料：松田阵平相关 comments1-10.csv / danmaku1-10.csv
  3. 分数：目标估计词频 * 背景逆频率

输出 matsuda_absolute_* 结果到 matsuda_wordcloud_output。
"""
from __future__ import annotations

import csv
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import jieba
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from wordcloud import WordCloud


BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "matsuda_wordcloud_output"
MATSUDA_KEYS = ("松田阵平", "松田", "阵平")
STOPWORDS_FILE = BASE / "matsuda_wordcloud_output" / "stopwords_zh_matsuda.txt"

BACKGROUND_COMMENT_PATTERN = "conan_background_comments*.csv"
BACKGROUND_DANMAKU_PATTERN = "conan_background_danmaku*.csv"
WIKI_TEXT_PATH = BASE / "conanpedia_background_text.csv"
BACKGROUND_STATS_PATH = BASE / "conan_tag_stats_名侦探柯南.csv"
TARGET_STATS_PATH = BASE / "conan_tag_stats_松田阵平.csv"
BACKGROUND_SAMPLE_PATH = BASE / "conan_background_sample_videos.csv"
BACKGROUND_VOCAB_PATH = OUT_DIR / "conan_background_scaled_vocabulary.csv"
BACKGROUND_PAGES_FOR_R = 5
BACKGROUND_STATS_FALLBACKS = [BASE / "conan_tag_stats_名侦探柯南.csv"]
TARGET_STATS_FALLBACKS = [
    BASE / "conan_tag_stats_松田阵平.csv",
    BASE / "tag_stats_batch_松田阵平.csv",
    BASE / "stats_tag_matsuda.csv",
]

WIKI_BACKGROUND_WEIGHT = 1.0
MIN_TARGET_COUNT = 2
TOP_N = 200

KEEP_TERMS = frozenset(
    {
        "白月光",
        "意难平",
        "警校",
        "警官",
        "萩原",
        "萩原研二",
        "炸弹",
        "爆处",
        "爆炸",
        "马自达",
        "卷毛",
        "墨镜",
        "老公",
        "殉职",
        "拆弹",
        "同期",
    }
)

STOPWORDS = frozenset(
    """
    的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 看 好 自己 这
    为 那 他 她 它 们 吗 吧 啊 哦 嗯 噢 呀 嘛 哈 嘿 唉 诶 呃 啥 咋 么
    什么 怎么 这个 那个 这样 那样 还是 或者 而且 因为 所以 但是 如果 虽然 然后 可以 应该
    真的 确实 感觉 觉得 认为 知道 看到 听到 出来 起来 下来 过来
    没有 有没有 是不是 会不会 要不要 能不能 不是 就是 这么 那么 为什么
    你 我 他 她 咱 咱们 你们 他们 她们 大家 有人 别人 其他人
    评论 弹幕 转发 点赞 收藏 关注 订阅 投币 直播间 视频 链接 网盘 up UP BV
    哈哈 哈哈哈 哈哈哈哈 啊啊 啊啊啊 啊啊啊啊 呜呜 呜呜呜 呜呜呜呜
    笑死 笑哭 哭死 救命 家人们 兄弟们 姐妹们 卧槽 我靠 我去
    现在 以前 时候 感觉 一直 还有 已经 还是 可能 肯定 直接 反正
    今天 明天 今年 明年 这里 那里 这集 这部 这段 这一 这一段
    柯南 名侦探柯南 名侦探 江户川柯南 工藤新一 主角 剧场版 电影
    松田 阵平 松田阵平
    http https www com bilibili b站 B站
    """.split()
) - KEEP_TERMS


def load_extra_stopwords(path: Path) -> set[str]:
    """从外部 txt 读取停用词（支持 # 注释）。"""
    if not path.exists():
        return set()
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        words.add(s)
    return words


def effective_stopwords() -> frozenset[str]:
    return (STOPWORDS | load_extra_stopwords(STOPWORDS_FILE)) - KEEP_TERMS


def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"\[.+?\]", " ", s)
    s = re.sub(r"@\S+", " ", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", " ", s)
    s = re.sub(r"[#【】《》「」『』（）()“”\"'.,!?！？、，。:：;；~～…]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokenize(text: str) -> list[str]:
    sw = effective_stopwords()
    out: list[str] = []
    for raw in jieba.cut(clean_text(text)):
        w = raw.strip()
        if not w:
            continue
        if w not in KEEP_TERMS:
            if len(w) < 2:
                continue
            if w in sw:
                continue
            if re.fullmatch(r"[A-Za-z]+", w) and len(w) < 4:
                continue
            if re.fullmatch(r"[0-9A-Za-z._-]+", w):
                continue
            if re.fullmatch(r"[0-9\s\W_]+", w):
                continue
            if re.fullmatch(r"(哈|啊|呜|哭|笑|草|艹|嘿|哦|噢|嗯){2,}", w):
                continue
        out.append(w)
    return out


def read_csv_texts(paths: Iterable[Path], text_column: str, title_column: str = "视频标题") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fp in paths:
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        for _, r in df.iterrows():
            body = str(r.get(text_column, "") or "")
            title = str(r.get(title_column, "") or "")
            if body.strip():
                rows.append({"title": title, "text": body, "source": str(fp.name)})
    return rows


def matsuda_related(row: dict[str, str]) -> bool:
    s = (row.get("title") or "") + " " + (row.get("text") or "")
    return any(k in s for k in MATSUDA_KEYS)


def load_target_comments() -> list[dict[str, str]]:
    paths = [BASE / f"comments{i}.csv" for i in range(1, 11)]
    return [r for r in read_csv_texts(paths, "评论内容") if matsuda_related(r)]


def load_target_danmaku() -> list[dict[str, str]]:
    paths = [BASE / f"danmaku{i}.csv" for i in range(1, 11)]
    return [r for r in read_csv_texts(paths, "弹幕内容") if matsuda_related(r)]


def load_background_comments() -> list[dict[str, str]]:
    paths = sorted(BASE.glob(BACKGROUND_COMMENT_PATTERN))
    return read_csv_texts(paths, "评论内容")


def load_background_danmaku() -> list[dict[str, str]]:
    paths = sorted(BASE.glob(BACKGROUND_DANMAKU_PATTERN))
    return read_csv_texts(paths, "弹幕内容")


def load_wiki_rows() -> list[dict[str, str]]:
    if not WIKI_TEXT_PATH.exists():
        return []
    df = pd.read_csv(WIKI_TEXT_PATH, encoding="utf-8")
    out: list[dict[str, str]] = []
    for _, r in df.iterrows():
        text = str(r.get("文本", "") or "")
        title = str(r.get("页面标题", "") or "")
        if text.strip():
            out.append({"title": title, "text": text, "source": WIKI_TEXT_PATH.name})
    return out


def count_tokens(rows: list[dict[str, str]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for row in rows:
        c.update(tokenize(row["text"]))
    return c


def read_stat_sum(paths: Path | list[Path], col: str) -> int:
    candidates = [paths] if isinstance(paths, Path) else paths
    for path in candidates:
        if not path.exists():
            continue
        df = pd.read_csv(path, encoding="utf-8")
        if col not in df.columns:
            continue
        val = int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
        if val > 0:
            return val
    return 0


def read_stat_cols_sum(paths: Path | list[Path], cols: tuple[str, ...]) -> int:
    return sum(read_stat_sum(paths, col) for col in cols)


def read_sample_stat_sum(col: str) -> int:
    if not BACKGROUND_SAMPLE_PATH.exists():
        return 0
    df = pd.read_csv(BACKGROUND_SAMPLE_PATH, encoding="utf-8")
    if col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def read_sample_cols_sum(cols: tuple[str, ...]) -> int:
    return sum(read_sample_stat_sum(col) for col in cols)


def read_tag_estimated_total(paths: Path | list[Path], col: str) -> tuple[float, str]:
    candidates = [paths] if isinstance(paths, Path) else paths
    for path in candidates:
        if not path.exists():
            continue
        df = pd.read_csv(path, encoding="utf-8")
        if col not in df.columns:
            continue
        observed_total = float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
        if observed_total <= 0:
            continue
        row_count = len(df)
        reported_count = (
            float(pd.to_numeric(df.get("接口报告总稿件数"), errors="coerce").fillna(0).max())
            if "接口报告总稿件数" in df.columns
            else 0.0
        )
        if row_count > 0 and reported_count > row_count:
            total = observed_total * reported_count / row_count
            total_metric = f"观测{row_count}条按接口报告{int(reported_count)}条估算"
        else:
            total = observed_total
            total_metric = f"已抓取{row_count}条求和"
        return total, total_metric
    return 0.0, ""


def read_sample_views_from_tag_stats() -> float:
    if not BACKGROUND_SAMPLE_PATH.exists():
        return 0.0
    sample_df = pd.read_csv(BACKGROUND_SAMPLE_PATH, encoding="utf-8")
    if "BV号" not in sample_df.columns:
        return 0.0
    bvids = set(str(v) for v in sample_df["BV号"].dropna())
    if not bvids:
        return 0.0
    for path in BACKGROUND_STATS_FALLBACKS:
        if not path.exists():
            continue
        tag_df = pd.read_csv(path, encoding="utf-8")
        if "BV号" not in tag_df.columns or "播放量" not in tag_df.columns:
            continue
        matched = tag_df[tag_df["BV号"].astype(str).isin(bvids)]
        views = float(pd.to_numeric(matched["播放量"], errors="coerce").fillna(0).sum())
        if views > 0:
            return views
    return 0.0


def read_crawled_background_rows(kind: str = "merged") -> int:
    total = 0
    if kind in {"comments", "merged"}:
        total += len(load_background_comments())
    if kind in {"danmaku", "merged"}:
        total += len(load_background_danmaku())
    return total


def scale_factor(total: int, sample_total: int) -> float:
    if total <= 0 or sample_total <= 0:
        return 1.0
    return max(1.0, total / sample_total)


def background_scale_info() -> dict[str, float | int | str]:
    """R = 所有带柯南 tag 视频播放量 / 已抓弹幕评论的柯南样本视频播放量。"""
    total_views, total_metric = read_tag_estimated_total(BACKGROUND_STATS_FALLBACKS, "播放量")
    sample_views = float(read_sample_stat_sum("播放量"))
    sample_metric = "conan_background_sample_videos.csv"
    if sample_views <= 0:
        sample_views = read_sample_views_from_tag_stats()
        sample_metric = "样本BV号匹配tag统计播放量"
    if total_views > 0 and sample_views > 0:
        return {
            "scale": scale_factor(total_views, sample_views),
            "metric": f"全tag播放量({total_metric}) / 已抓样本视频播放量({sample_metric})",
            "total": total_views,
            "sample": sample_views,
        }

    crawled_rows = read_crawled_background_rows("merged")
    return {
        "scale": 1.0,
        "metric": "播放量分子或分母缺失，未缩放",
        "total": total_views,
        "sample": sample_views or crawled_rows,
    }


def target_scale(kind: str) -> float:
    if kind == "comments":
        sample_total = sum(1 for _ in load_target_comments())
        return scale_factor(read_stat_sum(TARGET_STATS_FALLBACKS, "评论数_reply"), sample_total)
    if kind == "danmaku":
        sample_total = sum(1 for _ in load_target_danmaku())
        return scale_factor(read_stat_sum(TARGET_STATS_FALLBACKS, "弹幕数"), sample_total)
    sample_total = sum(1 for _ in load_target_comments()) + sum(1 for _ in load_target_danmaku())
    total = read_stat_sum(TARGET_STATS_FALLBACKS, "评论数_reply") + read_stat_sum(TARGET_STATS_FALLBACKS, "弹幕数")
    return max(1.0, total / sample_total) if sample_total > 0 and total > 0 else 1.0


def background_scale(kind: str) -> float:
    return float(background_scale_info()["scale"])


def absolute_scores(
    target_rows: list[dict[str, str]],
    background_rows: list[dict[str, str]],
    kind: str,
    wiki_rows: list[dict[str, str]],
) -> pd.DataFrame:
    target_counts = count_tokens(target_rows)
    background_counts = count_tokens(background_rows)
    wiki_counts = count_tokens(wiki_rows)

    t_scale = target_scale(kind)
    b_scale = background_scale(kind)
    all_terms = set(target_counts)
    background_total = sum(background_counts.values()) * b_scale
    background_total += sum(wiki_counts.values()) * WIKI_BACKGROUND_WEIGHT
    background_total = max(1.0, background_total)

    rows: list[dict[str, float | int | str]] = []
    for term in all_terms:
        raw_target = target_counts[term]
        if raw_target < MIN_TARGET_COUNT and term not in KEEP_TERMS:
            continue
        est_target = raw_target * t_scale
        est_background = background_counts.get(term, 0) * b_scale
        est_background += wiki_counts.get(term, 0) * WIKI_BACKGROUND_WEIGHT
        idf = math.log((background_total + 1.0) / (est_background + 1.0)) + 1.0
        score = est_target * idf
        rows.append(
            {
                "词": term,
                "score": score,
                "target_count": raw_target,
                "target_est_tf": est_target,
                "background_count": background_counts.get(term, 0),
                "background_est_tf": est_background,
                "wiki_count": wiki_counts.get(term, 0),
                "idf_from_background": idf,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "词",
                "score",
                "target_count",
                "target_est_tf",
                "background_count",
                "background_est_tf",
                "wiki_count",
                "idf_from_background",
            ]
        )
    return df.sort_values(["score", "target_count"], ascending=[False, False]).head(TOP_N)


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


def draw_wordcloud(df: pd.DataFrame, out_file: Path, title: str) -> None:
    freq = dict(zip(df["词"], df["score"])) if not df.empty else {"无数据": 1.0}
    font = pick_font_path()
    title_font = font_manager.FontProperties(fname=font) if font else None
    wc = WordCloud(
        font_path=font,
        width=1200,
        height=800,
        background_color="white",
        max_words=200,
        colormap="viridis",
        prefer_horizontal=0.85,
        relative_scaling=0.45,
        min_font_size=8,
    ).generate_from_frequencies(freq)
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(title, fontsize=14, pad=12, fontproperties=title_font)
    fig.savefig(out_file, dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_outputs(prefix: str, df: pd.DataFrame, title: str) -> None:
    csv_path = OUT_DIR / f"matsuda_absolute_{prefix}_tfidf_top.csv"
    png_path = OUT_DIR / f"matsuda_absolute_{prefix}_wordcloud.png"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    draw_wordcloud(df, png_path, title)


def write_background_vocabulary(
    background_comments: list[dict[str, str]],
    background_danmaku: list[dict[str, str]],
    wiki_rows: list[dict[str, str]],
) -> None:
    """输出 R 放大后的柯南背景词库，供复核 TF-IDF 背景项。"""
    background_counts = count_tokens(background_comments + background_danmaku)
    wiki_counts = count_tokens(wiki_rows)
    r_info = background_scale_info()
    r = float(r_info["scale"])
    rows: list[dict[str, float | int | str]] = []
    for term in sorted(set(background_counts) | set(wiki_counts)):
        bg_count = background_counts.get(term, 0)
        wiki_count = wiki_counts.get(term, 0)
        rows.append(
            {
                "词": term,
                "背景弹幕评论词数": bg_count,
                "R": r,
                "背景词数乘R": bg_count * r,
                "wiki词数": wiki_count,
                "wiki权重": WIKI_BACKGROUND_WEIGHT,
                "词库估计词数": bg_count * r + wiki_count * WIKI_BACKGROUND_WEIGHT,
                "R口径": r_info["metric"],
                "R分子_全tag总量": r_info["total"],
                "R分母_样本总量": r_info["sample"],
            }
        )
    pd.DataFrame(rows).sort_values(
        ["词库估计词数", "背景弹幕评论词数", "wiki词数"],
        ascending=[False, False, False],
    ).to_csv(BACKGROUND_VOCAB_PATH, index=False, encoding="utf-8-sig")


def write_token_stats(
    target_comments: list[dict[str, str]],
    target_danmaku: list[dict[str, str]],
    background_comments: list[dict[str, str]],
    background_danmaku: list[dict[str, str]],
    wiki_rows: list[dict[str, str]],
) -> None:
    r_info = background_scale_info()
    rows = [
        {
            "项目": "目标评论_松田筛选",
            "文本条数": len(target_comments),
            "token总数": sum(count_tokens(target_comments).values()),
            "scale": target_scale("comments"),
        },
        {
            "项目": "目标弹幕_松田筛选",
            "文本条数": len(target_danmaku),
            "token总数": sum(count_tokens(target_danmaku).values()),
            "scale": target_scale("danmaku"),
        },
        {
            "项目": "背景评论_柯南",
            "文本条数": len(background_comments),
            "token总数": sum(count_tokens(background_comments).values()),
            "scale": background_scale("comments"),
            "R口径": r_info["metric"],
            "R分子_全tag总量": r_info["total"],
            "R分母_样本总量": r_info["sample"],
        },
        {
            "项目": "背景弹幕_柯南",
            "文本条数": len(background_danmaku),
            "token总数": sum(count_tokens(background_danmaku).values()),
            "scale": background_scale("danmaku"),
            "R口径": r_info["metric"],
            "R分子_全tag总量": r_info["total"],
            "R分母_样本总量": r_info["sample"],
        },
        {
            "项目": "wiki背景_conanpedia",
            "文本条数": len(wiki_rows),
            "token总数": sum(count_tokens(wiki_rows).values()),
            "scale": WIKI_BACKGROUND_WEIGHT,
            "R口径": "wiki按原始词数进入背景词库",
            "R分子_全tag总量": "",
            "R分母_样本总量": "",
        },
    ]
    pd.DataFrame(rows).to_csv(
        OUT_DIR / "matsuda_absolute_method_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )


def write_top_tokens_snapshot(df: pd.DataFrame, name: str) -> None:
    path = OUT_DIR / f"matsuda_absolute_{name}_token_stats.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jieba.add_word("松田阵平")
    jieba.add_word("白月光")
    jieba.add_word("意难平")
    jieba.add_word("警校组")
    jieba.add_word("爆炸物处理班")
    jieba.add_word("萩原研二")

    target_comments = load_target_comments()
    target_danmaku = load_target_danmaku()
    background_comments = load_background_comments()
    background_danmaku = load_background_danmaku()
    wiki_rows = load_wiki_rows()

    print(f"目标评论：{len(target_comments)}")
    print(f"目标弹幕：{len(target_danmaku)}")
    print(f"背景评论：{len(background_comments)}")
    print(f"背景弹幕：{len(background_danmaku)}")
    print(f"wiki页面：{len(wiki_rows)}")

    comment_df = absolute_scores(target_comments, background_comments, "comments", wiki_rows)
    danmaku_df = absolute_scores(target_danmaku, background_danmaku, "danmaku", wiki_rows)
    merged_df = absolute_scores(
        target_comments + target_danmaku,
        background_comments + background_danmaku,
        "merged",
        wiki_rows,
    )

    save_outputs("comments", comment_df, "松田阵平 · 评论绝对化 TF-IDF 词云")
    save_outputs("danmaku", danmaku_df, "松田阵平 · 弹幕绝对化 TF-IDF 词云")
    save_outputs("merged", merged_df, "松田阵平 · 评论+弹幕绝对化 TF-IDF 词云")
    write_background_vocabulary(background_comments, background_danmaku, wiki_rows)
    write_token_stats(target_comments, target_danmaku, background_comments, background_danmaku, wiki_rows)
    write_top_tokens_snapshot(merged_df, "merged")

    print(f"已输出：{OUT_DIR}")


if __name__ == "__main__":
    main()
