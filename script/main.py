import asyncio
import csv
import html
import os
import shutil
import sys

# 历史数据（只读备份，首次运行若存在旧文件则复制一份）
LEGACY_DANMAKU = "danmaku.csv"
LEGACY_COMMENTS = "comments.csv"
ARCHIVE_DANMAKU = "danmaku_archive.csv"
ARCHIVE_COMMENTS = "comments_archive.csv"
# 之后爬虫只往这两个文件追加
OUT_DANMAKU = "danmaku_new.csv"
OUT_COMMENTS = "comments_new.csv"


def _configure_stdio_utf8() -> None:
    """避免 Windows 默认 GBK 控制台在打印 ✧ 等字符时 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


_configure_stdio_utf8()

from bilibili_api import search, video, comment, Credential
from bilibili_api.exceptions import DanmakuClosedException
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

# ==========================================
# 1. 配置你的 B站 Cookie (务必替换为你自己的)
# ==========================================
SESSDATA = "aea0b90f%2C1790956131%2C1bb36%2A41CjD1JzSTMJzPAHp4Pwp6wXUhL7Uk7JE9U1BVxW9nwLxIEiIGPzvFxiUwsa8-G3aP1dcSVkktLWJxSkZzalBZRGxpWmtrc3RELVczWlMwTXJ2RXlWVFZabmxBcWdKWFF2Ym5YcEhxR0F4Z1pOUVAzYzJGdU1zdFNhd2xuMnVNRHlCZUVlSU15UHd3IIEC"
BILI_JCT = "65c7f3debea3e4a01d436f0256d265aa"
BUVID3 = "9A12211B-6C25-7DE4-651B-CF06A310CDF913401infoc"

# 实例化凭证（建议同时填写浏览器 Cookie 里的 DedeUserID，与网页登录态一致）
DEDE_USER_ID = ""  # 例如 "123456789"，没有可留空
credential = Credential(
    sessdata=SESSDATA,
    bili_jct=BILI_JCT,
    buvid3=BUVID3,
    dedeuserid=DEDE_USER_ID or None,
)

# 仅调试用：跳过搜索结果前 N 个视频（例如前几条无评论时可设为 2）
SKIP_VIDEOS = int(os.environ.get("CRAWL_SKIP_VIDEOS", "0") or "0")
# 仅处理前 N 个视频（0=不限制）；可与 SKIP 组合，先跳过再截取
LIMIT_VIDEOS = int(os.environ.get("CRAWL_LIMIT_VIDEOS", "0") or "0")
# 每个视频最多爬多少页一级评论（0=不限制，按接口总数翻完；可用环境变量限制）
MAX_COMMENT_PAGES = int(os.environ.get("CRAWL_MAX_COMMENT_PAGES", "0") or "0")
_MAX_COMMENT_PAGE_SAFETY = 5000

# 按「搜索页」分别输出：danmaku{N}.csv / comments{N}.csv（N 与 B 站搜索页码一致）
# 优先级：环境变量 CRAWL_SEARCH_PAGE_END > 0 时用 CRAWL_SEARCH_PAGE_START～END；否则用下面元组；再否则单页模式写 OUT_*
SEARCH_PAGE_START = max(1, int(os.environ.get("CRAWL_SEARCH_PAGE_START", "2") or "2"))
SEARCH_PAGE_END = int(os.environ.get("CRAWL_SEARCH_PAGE_END", "0") or "0")
# 不设环境变量时：在此填写 (起始页, 结束页)，例如 (2, 10) 表示第 2～10 页；None 表示不启用（除非上面 END>0）
FILE_MULTI_SEARCH_PAGES: tuple[int, int] | None = (2, 10)


def _clean_title(raw: str) -> str:
    if not raw:
        return ""
    t = raw.replace('<em class="keyword">', "").replace("</em>", "")
    return html.unescape(t)


def _comment_text(content: dict | None) -> str:
    if not content:
        return ""
    msg = content.get("message")
    if msg is None:
        return ""
    if not isinstance(msg, str):
        msg = str(msg)
    return html.unescape(msg).replace("\n", " ")


async def probe_comment_credential(cred: Credential) -> bool:
    """
    B 站评论接口在 Cookie 失效时仍可能返回 200，但 replies 为空。
    用固定热门视频采样一页；采样为 0 条时基本可判定需重新登录/换 Cookie。
    """
    if not cred.has_sessdata():
        print(
            "[评论] 未设置 SESSDATA：一级评论几乎必定为空，请到浏览器登录 bilibili 后从 Cookie 复制。"
        )
        return False
    aid = bvid2aid("BV13f4y1G7uY")
    try:
        sample = await comment.get_comments(
            aid,
            comment.CommentResourceType.VIDEO,
            page_index=1,
            credential=cred,
        )
    except Exception as e:
        print(f"[评论] 登录态检测请求失败: {e}")
        return False
    n = len(sample.get("replies") or [])
    if n == 0:
        print(
            "[评论] 采样未取到任何评论（0 条）。若浏览器里该视频有评论，请更新 SESSDATA、bili_jct，"
            "并尽量同时填写 DedeUserID（与网页 Cookie 一致）。"
        )
        return False
    print(f"[评论] 登录态正常（采样视频首屏一级评论 {n} 条）。")
    return True


def archive_legacy_csv_if_needed() -> None:
    """把当前 danmaku.csv / comments.csv 各备份一份为 *_archive.csv（仅当归档尚不存在时）。"""
    for src, dst in (
        (LEGACY_DANMAKU, ARCHIVE_DANMAKU),
        (LEGACY_COMMENTS, ARCHIVE_COMMENTS),
    ):
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)
            print(f"[归档] 已保存现有数据：{src} -> {dst}")


# 初始化输出 CSV（仅作用于 OUT_*；fresh=True 时清空这两个新文件并重建表头）
def init_csv(fresh: bool = False) -> None:
    if fresh:
        for name in (OUT_DANMAKU, OUT_COMMENTS):
            if os.path.exists(name):
                os.remove(name)
    if not os.path.exists(OUT_DANMAKU):
        with open(OUT_DANMAKU, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["视频标题", "BVID", "分P序号", "弹幕内容"])
    if not os.path.exists(OUT_COMMENTS):
        with open(OUT_COMMENTS, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["视频标题", "BVID", "用户名", "评论内容"])


def _page_output_paths(search_page: int) -> tuple[str, str]:
    return f"danmaku{search_page}.csv", f"comments{search_page}.csv"


def init_page_csv(search_page: int, fresh: bool) -> tuple[str, str]:
    """本搜索页对应的弹幕/评论文件；fresh 时先删再建表头。"""
    dm, cm = _page_output_paths(search_page)
    if fresh:
        for name in (dm, cm):
            if os.path.exists(name):
                os.remove(name)
    if not os.path.exists(dm):
        with open(dm, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["视频标题", "BVID", "分P序号", "弹幕内容"])
    if not os.path.exists(cm):
        with open(cm, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["视频标题", "BVID", "用户名", "评论内容"])
    return dm, cm


def get_multi_search_range() -> tuple[int, int] | None:
    if SEARCH_PAGE_END >= SEARCH_PAGE_START and SEARCH_PAGE_END > 0:
        return SEARCH_PAGE_START, SEARCH_PAGE_END
    if FILE_MULTI_SEARCH_PAGES is not None:
        lo, hi = FILE_MULTI_SEARCH_PAGES
        if hi >= lo >= 1:
            return lo, hi
        print("警告：FILE_MULTI_SEARCH_PAGES 无效（需 hi>=lo>=1），已忽略。")
    return None


def uses_multi_search_pages() -> bool:
    return get_multi_search_range() is not None


async def process_video(
    bvid: str,
    title: str,
    danmaku_csv: str | None = None,
    comments_csv: str | None = None,
) -> None:
    """处理单个视频，获取弹幕和评论并保存到指定 CSV（默认 OUT_DANMAKU / OUT_COMMENTS）。"""
    dm_path = danmaku_csv or OUT_DANMAKU
    cm_path = comments_csv or OUT_COMMENTS

    print(f"\n>>> 开始处理视频: 【{title}】 (BVID: {bvid})", flush=True)
    v_api = video.Video(bvid=bvid, credential=credential)
    
    # --- 获取并保存弹幕（多分 P 时按 P 逐段拉取，单 P 内库会按 6 分钟一段拉全）---
    try:
        info = await v_api.get_info()
        page_list = info.get("pages") or []
        if not page_list:
            page_list = [{"page": 1, "part": "正片"}]

        total_dm = 0
        with open(dm_path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for idx, p in enumerate(page_list):
                part_label = str(p.get("page", idx + 1))
                try:
                    danmakus = await v_api.get_danmakus(page_index=idx)
                except DanmakuClosedException:
                    print(f"    [弹幕] 分P {part_label} 弹幕已关闭，跳过")
                    continue
                for d in danmakus:
                    writer.writerow([title, bvid, part_label, d.text])
                total_dm += len(danmakus)
                if len(page_list) > 1:
                    await asyncio.sleep(0.4)
        print(f"    [弹幕] 共 {len(page_list)} 个分P，累计保存 {total_dm} 条到 {dm_path}")
    except Exception as e:
        print(f"    [弹幕] 获取失败: {e}")

    await asyncio.sleep(2)

    # --- 获取并保存评论（须有效登录 Cookie，否则接口会返回空列表）---
    try:
        all_replies_count = 0
        aid = bvid2aid(bvid)
        total_count: int | None = None
        page_size = 20
        page_cap = (
            MAX_COMMENT_PAGES
            if MAX_COMMENT_PAGES > 0
            else _MAX_COMMENT_PAGE_SAFETY
        )

        for page_num in range(1, page_cap + 1):
            comments_data = await comment.get_comments(
                aid,
                comment.CommentResourceType.VIDEO,
                page_index=page_num,
                credential=credential,
            )
            page_meta = comments_data.get("page") or {}
            if total_count is None:
                total_count = int(page_meta.get("count") or 0)
                page_size = int(page_meta.get("size") or 20) or 20

            replies = comments_data.get("replies") or []

            if not replies:
                break

            with open(cm_path, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                for c in replies:
                    uname = (c.get("member") or {}).get("uname", "")
                    msg = _comment_text(c.get("content"))
                    writer.writerow([title, bvid, uname, msg])

            all_replies_count += len(replies)
            await asyncio.sleep(1.5)

            if total_count is not None and page_num * page_size >= total_count:
                break

        if all_replies_count == 0:
            if (total_count or 0) == 0:
                print("    [评论] 该视频一级评论数为 0（未开放评论或确实无人留言）。")
            else:
                print(
                    "    [评论] 未写入任何行：接口返回空列表，可稍后重试或检查网络/风控。"
                )
        else:
            print(f"    [评论] 成功保存 {all_replies_count} 条评论到 {cm_path}")
    except Exception as e:
        print(f"    [评论] 获取失败: {e}")

async def main():
    archive_legacy_csv_if_needed()

    if SEARCH_PAGE_END > 0 and SEARCH_PAGE_END < SEARCH_PAGE_START:
        print(
            "错误：CRAWL_SEARCH_PAGE_END 必须大于等于 CRAWL_SEARCH_PAGE_START。"
        )
        return

    fresh = os.environ.get("CRAWL_FRESH", "").strip().lower() in ("1", "true", "yes")
    page_range = get_multi_search_range()
    multi_pages = page_range is not None

    if not multi_pages:
        init_csv(fresh=fresh)
        if fresh:
            print(
                f"已开启 CRAWL_FRESH：已清空 {OUT_DANMAKU} / {OUT_COMMENTS} 仅保留表头。"
            )
        else:
            print(
                f"弹幕/评论写入 {OUT_DANMAKU}、{OUT_COMMENTS}；"
                f"{LEGACY_DANMAKU} / {LEGACY_COMMENTS} 仅作留档、脚本不再改写。"
            )
    else:
        assert page_range is not None
        lo, hi = page_range
        if fresh:
            print(
                f"已开启 CRAWL_FRESH：将清空搜索第 {lo}–{hi} 页"
                f" 对应的 danmaku*.csv / comments*.csv 后重建表头。"
            )
        print(
            f"多页模式：搜索页 [{lo}, {hi}]，"
            f"每页写入 danmaku<N>.csv 与 comments<N>.csv。"
        )

    await probe_comment_credential(credential)

    keyword = "松田阵平"
    print(f"=== 开始检索关键词/标签: {keyword} ===")

    try:
        if multi_pages:

            async def run_one_search_page(sp: int) -> None:
                dm_file, cm_file = init_page_csv(sp, fresh=fresh)
                print(f"\n--- 搜索第 {sp} 页 → {dm_file} / {cm_file} ---")
                search_result = await search.search_by_type(
                    keyword=keyword,
                    search_type=search.SearchObjectType.VIDEO,
                    page=sp,
                )
                videos = search_result.get("result", [])
                if not videos:
                    print(f"第 {sp} 页无视频结果。")
                    return
                vlist = videos
                if SKIP_VIDEOS > 0:
                    if SKIP_VIDEOS >= len(vlist):
                        print(
                            f"第 {sp} 页：CRAWL_SKIP_VIDEOS={SKIP_VIDEOS} 大于等于本页条数，跳过。"
                        )
                        return
                    vlist = vlist[SKIP_VIDEOS:]
                if LIMIT_VIDEOS > 0:
                    vlist = vlist[:LIMIT_VIDEOS]
                print(f"第 {sp} 页共 {len(vlist)} 个视频待抓取。")
                for v in vlist:
                    bvid = v.get("bvid")
                    title = _clean_title(v.get("title") or "")
                    await process_video(bvid, title, dm_file, cm_file)
                    await asyncio.sleep(3)

            assert page_range is not None
            lo, hi = page_range
            for sp in range(lo, hi + 1):
                await run_one_search_page(sp)
                await asyncio.sleep(2)
            return

        search_result = await search.search_by_type(
            keyword=keyword,
            search_type=search.SearchObjectType.VIDEO,
            page=1,
        )

        videos = search_result.get("result", [])
        if not videos:
            print("未搜索到任何视频结果。")
            return

        if SKIP_VIDEOS > 0:
            if SKIP_VIDEOS >= len(videos):
                print(f"CRAWL_SKIP_VIDEOS={SKIP_VIDEOS} 大于等于本页视频数 {len(videos)}，无视频可处理。")
                return
            videos = videos[SKIP_VIDEOS:]
            print(f"已跳过前 {SKIP_VIDEOS} 个视频，剩余 {len(videos)} 个待处理。")

        if LIMIT_VIDEOS > 0:
            videos = videos[:LIMIT_VIDEOS]
            print(f"在第1页找到视频，因 CRAWL_LIMIT_VIDEOS={LIMIT_VIDEOS} 仅处理前 {len(videos)} 个。")
        else:
            print(f"在第1页找到了 {len(videos)} 个视频。开始逐个抓取...")

        for v in videos:
            bvid = v.get("bvid")
            title = _clean_title(v.get("title") or "")

            await process_video(bvid, title)
            await asyncio.sleep(3)

    except Exception as e:
        print(f"搜索请求发生错误: {e}")

if __name__ == '__main__':
    asyncio.run(main())