# -*- coding: utf-8 -*-
"""
基于 comments1-10.csv / danmaku1-10.csv：分词 → TF-IDF → 词云（松田阵平相关人物标签）。
"""
from __future__ import annotations

import re
from pathlib import Path

import jieba
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from matplotlib import font_manager

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "matsuda_wordcloud_output"

# 仅保留标题或正文含以下任一关键词的样本，突出与松田阵平相关的讨论（设为 False 则用全量）
MATSUDA_FILTER = True
MATSUDA_KEYS = ("松田", "阵平")

# 词云中弱化角色名本身，突出关联标签
EXTRA_STOP = frozenset(
    {
        "松田",
        "阵平",
        "松田阵平",
        "视频",
        "http",
        "www",
        "com",
        "BV",
        "直播间",
    }
)

# 通用中文停用词（精简版，可按需扩充）
STOPWORDS = frozenset(
    """
    的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这
    为 那 他 她 它 们 吗 吧 啊 哦 嗯 噢 呀 嘛 哈 嘿 唉 诶
    什么 怎么 这个 那个 这样 那样 还是 或者 而且 因为 所以 但是 如果 虽然 然后 可以 应该
    真的 确实 感觉 觉得 认为 知道 看到 听到 出来 起来 下来 过来
    没有 有没有 是不是 会不会 要不要 能不能
    你 我 他 她 咱 咱们 你们 他们 她们 大家 有人
    这 那 哪 啥 咋 么 呃
    评论 弹幕 转发 点赞 收藏 关注 订阅 投币
    """.split()
) | EXTRA_STOP


def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"\[.+?\]", " ", s)  # [笑哭] 等
    s = re.sub(r"@\S+", " ", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_matsuda_related(title: str, body: str) -> bool:
    t = (title or "") + (body or "")
    return any(k in t for k in MATSUDA_KEYS)


def tokenize(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    out = []
    for w in jieba.cut(text):
        w = w.strip()
        if len(w) < 2:
            continue
        if re.fullmatch(r"[A-Za-z]+", w) and len(w) < 4:
            continue
        if w in STOPWORDS:
            continue
        if re.match(r"^[0-9\s\W_]+$", w):
            continue
        out.append(w)
    return out


def load_comment_lines() -> list[str]:
    rows: list[str] = []
    for i in range(1, 11):
        fp = BASE / f"comments{i}.csv"
        if not fp.exists():
            raise FileNotFoundError(fp)
        df = pd.read_csv(fp, encoding="utf-8")
        for _, r in df.iterrows():
            title = str(r.get("视频标题", "") or "")
            body = str(r.get("评论内容", "") or "")
            if MATSUDA_FILTER and not is_matsuda_related(title, body):
                continue
            if not str(body).strip():
                continue
            rows.append(body)
    return rows


def load_danmaku_lines() -> list[str]:
    rows: list[str] = []
    for i in range(1, 11):
        fp = BASE / f"danmaku{i}.csv"
        if not fp.exists():
            raise FileNotFoundError(fp)
        df = pd.read_csv(fp, encoding="utf-8")
        for _, r in df.iterrows():
            title = str(r.get("视频标题", "") or "")
            body = str(r.get("弹幕内容", "") or "")
            if MATSUDA_FILTER and not is_matsuda_related(title, body):
                continue
            if not str(body).strip():
                continue
            rows.append(body)
    return rows


def tfidf_term_scores(documents: list[str]) -> dict[str, float]:
    """每条文本为文档，对词在所有文档上的 TF-IDF 分量求和（较 max 更易拉开排序差距）。"""
    if not documents:
        return {}
    # 空格连接分词结果，配合 char_wb 不适用；使用可调用 analyzer
    def analyzer(doc: str):
        return tokenize(doc)

    vectorizer = TfidfVectorizer(analyzer=analyzer, max_features=20000, min_df=2)
    try:
        X = vectorizer.fit_transform(documents)
    except ValueError:
        # 样本过少时 min_df=2 可能失败，放宽
        vectorizer = TfidfVectorizer(analyzer=analyzer, max_features=20000, min_df=1)
        X = vectorizer.fit_transform(documents)
    terms = list(vectorizer.get_feature_names_out())
    # 按列求和：该词在全语料上的 TF-IDF 总贡献（稀疏矩阵显式转成 1 维向量）
    s = X.sum(axis=0)
    sum_per_term = np.asarray(s.toarray() if hasattr(s, "toarray") else s).ravel()
    out: dict[str, float] = {}
    for i, term in enumerate(terms):
        v = float(sum_per_term[i])
        if v > 0.0:
            out[term] = v
    return out


def pick_font_path() -> str | None:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\SimHei.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def draw_wordcloud(freq: dict[str, float], out_file: Path, title: str) -> None:
    font = pick_font_path()
    title_font = None
    if font:
        title_font = font_manager.FontProperties(fname=font)
    if not freq:
        # 空时写占位说明
        freq = {"无数据": 1.0}
    wc = WordCloud(
        font_path=font,
        width=1200,
        height=800,
        background_color="white",
        max_words=200,
        colormap="viridis",
        prefer_horizontal=0.85,
        relative_scaling=0.4,
        min_font_size=8,
    ).generate_from_frequencies(freq)

    fig, ax = plt.subplots(figsize=(12, 8))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(title, fontsize=14, pad=12, fontproperties=title_font)
    fig.savefig(out_file, dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_ranking_csv(scores: dict[str, float], out_file: Path, topn: int = 200) -> None:
    items = sorted(scores.items(), key=lambda x: -x[1])[:topn]
    pd.DataFrame(items, columns=["词", "tfidf_sum"]).to_csv(out_file, index=False, encoding="utf-8-sig")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    comments = load_comment_lines()
    danmaku = load_danmaku_lines()

    print(f"评论条数（当前筛选）: {len(comments)}")
    print(f"弹幕条数（当前筛选）: {len(danmaku)}")

    comment_scores = tfidf_term_scores(comments)
    danmaku_scores = tfidf_term_scores(danmaku)

    prefix = "matsuda_filtered" if MATSUDA_FILTER else "matsuda_all"

    save_ranking_csv(comment_scores, OUT_DIR / f"{prefix}_comments_tfidf_top.csv")
    save_ranking_csv(danmaku_scores, OUT_DIR / f"{prefix}_danmaku_tfidf_top.csv")

    # 词云用归一化权重（ relative_scaling 已设，直接用分数即可）
    draw_wordcloud(
        comment_scores,
        OUT_DIR / f"{prefix}_comments_wordcloud.png",
        "松田阵平 · 评论 TF-IDF 词云（人物关联标签）",
    )
    draw_wordcloud(
        danmaku_scores,
        OUT_DIR / f"{prefix}_danmaku_wordcloud.png",
        "松田阵平 · 弹幕 TF-IDF 词云（人物关联标签）",
    )

    # 合并评论+弹幕的一体化词云
    all_docs = comments + danmaku
    merged_scores = tfidf_term_scores(all_docs)
    save_ranking_csv(merged_scores, OUT_DIR / f"{prefix}_merged_tfidf_top.csv")
    draw_wordcloud(
        merged_scores,
        OUT_DIR / f"{prefix}_merged_wordcloud.png",
        "松田阵平 · 评论+弹幕 合并 TF-IDF 词云",
    )

    print(f"已输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
