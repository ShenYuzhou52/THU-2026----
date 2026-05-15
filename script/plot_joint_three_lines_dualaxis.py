from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager


BASE = Path(__file__).resolve().parent
EMP = BASE / "empirical_output"
SRC = EMP / "crosssite_joint_three_lines_raw.csv"
OUT = EMP / "crosssite_joint_three_lines_corrected.png"


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


def setup_font() -> None:
    fp = pick_font_path()
    if fp:
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def main() -> None:
    setup_font()
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    df = df[df["year"] >= 2017].copy()

    fig, ax_works = plt.subplots(figsize=(10.8, 6.0))
    # 左侧第二套刻度（热度）
    ax_heat = ax_works.twinx()
    ax_heat.spines["left"].set_position(("outward", 52))
    ax_heat.spines["left"].set_visible(True)
    ax_heat.spines["right"].set_visible(False)
    ax_heat.yaxis.set_label_position("left")
    ax_heat.yaxis.tick_left()

    # 右侧比例轴
    ax_share = ax_works.twinx()

    l1 = ax_works.plot(
        df["year"],
        df["matsuda_total_works_3sites"],
        marker="o",
        linewidth=2,
        color="#1f77b4",
        label="同人文总数（3站合并）",
    )
    l2 = ax_heat.plot(
        df["year"],
        df["matsuda_total_top20_heat_3sites"],
        marker="s",
        linewidth=2,
        color="#ff7f0e",
        label="Top20热度总量（3站合并）",
    )
    l3 = ax_share.plot(
        df["year"],
        df["matsuda_share_in_conan_3sites"],
        marker="^",
        linewidth=2,
        color="#2ca02c",
        label="占柯南圈层比例",
    )

    ax_works.axvline(2019.75, linestyle="--", alpha=0.35)
    ax_works.axvline(2022.29, linestyle="--", alpha=0.35)

    ax_works.set_title("")
    ax_works.set_xlabel("年份")
    ax_works.set_ylabel("同人文总数（蓝）", color="#1f77b4")
    ax_heat.set_ylabel("Top20热度总量（橙）", color="#ff7f0e")
    ax_share.set_ylabel("占柯南圈层比例（绿）", color="#2ca02c")

    ax_works.tick_params(axis="y", colors="#1f77b4")
    ax_heat.tick_params(axis="y", colors="#ff7f0e")
    ax_share.tick_params(axis="y", colors="#2ca02c")
    ax_works.grid(alpha=0.22, linestyle="--")

    # 关键节点文字标注（放在比例轴上方，避免遮挡左轴两条数量曲线）
    y_top = float(df["matsuda_share_in_conan_3sites"].max()) * 0.95
    ax_share.text(
        2019.78,
        y_top,
        "警察学校篇\n2019-10-01",
        fontsize=9,
        color="#444444",
        ha="left",
        va="top",
        bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=2.5),
    )
    ax_share.text(
        2022.32,
        y_top * 0.84,
        "万圣节的新娘\n2022-04-15",
        fontsize=9,
        color="#444444",
        ha="left",
        va="top",
        bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=2.5),
    )

    lines = l1 + l2 + l3
    labels = [ln.get_label() for ln in lines]
    ax_works.legend(lines, labels, loc="upper left")

    fig.tight_layout()
    fig.savefig(OUT, dpi=180)
    plt.close(fig)
    print(f"已输出：{OUT}")


if __name__ == "__main__":
    main()
