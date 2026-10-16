#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化小说大纲工程目录。

用法：
    python init_outline.py "《书名》" --path ./novel --volumes 4 --chapters 160
    python init_outline.py "《书名》" --path ./novel --style fanqie     # 番茄小说风格档位

生成结构：
    <path>/
    ├── outline.md                    全书大纲（L1）
    ├── characters.md                 人物设定（L2）
    ├── volumes/第1卷-卷纲.md ...      分卷卷纲（L3）
    ├── 细纲/第1卷-细纲.md ...         逐章细纲（L4，已铺好章号骨架）
    ├── ledger.json                   伏笔台账
    ├── style.json                    风格档位（standard / fanqie）
    └── state.json                    工程元数据与进度

默认不覆盖已存在的文件；加 --force 可覆盖。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"

CHAPTER_BLOCK = """### 第{num:03d}章 章标题

- **本章事件**：
- **本章变化**：
- **出场人物**：
- **场景分解**：
  1. 【目标】　【阻碍】　【变化】
- **伏笔**：埋 —；收 —
- **章末钩子**：类型=；内容=
- **目标字数**：3000
"""

# 番茄档位：额外要求「开篇抓手」与「本章爽点」，字数默认 2500
CHAPTER_BLOCK_FANQIE = """### 第{num:03d}章 章标题

- **开篇抓手**：
- **本章事件**：
- **本章爽点**：类型=；兑现=
- **本章变化**：
- **出场人物**：
- **场景分解**：
  1. 【目标】　【阻碍】　【变化】
- **伏笔**：埋 —；收 —
- **章末钩子**：类型=；内容=
- **目标字数**：2500
"""

# 番茄档位注入到 outline.md 的书名与简介区块
FANQIE_OUTLINE_BLOCK = """
## 书名与简介 【必填 · 番茄档位】

- **书名**：（15 字以内，直白点明主角身份或核心剧情，带 1 个热搜词：重生 / 系统 / 末世 / 囤货 / 逆袭 / 战神 / 马甲）
- **简介**：（150 字以内，写清 主角困境 → 金手指 → 最终目标，最后一句留悬念）
- **对标榜单**：（番茄同赛道当前 Top 作品 2-3 本，只记它们的开局结构与节奏，不抄情节）
- **开篇三百字**：（第 1 章前 300 字要抛的核心冲突，具体到事件）
"""


def read_template(name, fallback):
    p = TEMPLATE_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return fallback


def split_chapters(total, volumes):
    """把 total 章尽量均匀分到 volumes 卷，返回每卷章数列表。"""
    base, rest = divmod(total, volumes)
    return [base + (1 if i < rest else 0) for i in range(volumes)]


def build_volume_files(out_root, book, volumes, total_chapters, force, style="standard"):
    counts = split_chapters(total_chapters, volumes)
    vol_tpl = read_template("volume-template.md", "# 第N卷 卷纲\n")
    if style == "fanqie":
        chap_tpl = read_template("chapter-outline-fanqie-template.md", "# 第N卷 逐章细纲\n")
        block_tpl = CHAPTER_BLOCK_FANQIE
    else:
        chap_tpl = read_template("chapter-outline-template.md", "# 第N卷 逐章细纲\n")
        block_tpl = CHAPTER_BLOCK

    vol_dir = out_root / "volumes"
    chap_dir = out_root / "细纲"
    vol_dir.mkdir(parents=True, exist_ok=True)
    chap_dir.mkdir(parents=True, exist_ok=True)

    created = []
    cursor = 1
    for i, cnt in enumerate(counts, start=1):
        start, end = cursor, cursor + cnt - 1
        cursor = end + 1

        vol_text = vol_tpl.replace("# 第N卷 卷纲", "# 第%d卷 卷纲" % i)
        vol_text = vol_text.replace("第 ______ 章 ~ 第 ______ 章", "第 %03d 章 ~ 第 %03d 章" % (start, end))
        vol_path = vol_dir / ("第%d卷-卷纲.md" % i)
        if force or not vol_path.exists():
            vol_path.write_text(vol_text, encoding="utf-8")
            created.append(vol_path)

        blocks = "\n".join(block_tpl.format(num=n) for n in range(start, end + 1))
        chap_text = chap_tpl.replace("# 第N卷 逐章细纲", "# 第%d卷 逐章细纲" % i)
        chap_text = chap_text.replace("第 ______ 章 ~ 第 ______ 章", "第 %03d 章 ~ 第 %03d 章" % (start, end))
        # 用真实章号骨架替换模板里的示例章
        if "## 章纲" in chap_text:
            head, _sep, _tail = chap_text.partition("## 章纲")
            chap_text = head + "## 章纲\n\n" + blocks + "\n---\n" + _tail.partition("---")[2].lstrip("\n-")
        chap_path = chap_dir / ("第%d卷-细纲.md" % i)
        if force or not chap_path.exists():
            chap_path.write_text(chap_text, encoding="utf-8")
            created.append(chap_path)

    return counts, created


def main():
    ap = argparse.ArgumentParser(description="初始化小说大纲工程目录")
    ap.add_argument("book", help="书名，例如 《书名》")
    ap.add_argument("--path", default="./novel", help="工程目录（默认 ./novel）")
    ap.add_argument("--volumes", type=int, default=4, help="卷数（默认 4）")
    ap.add_argument("--chapters", type=int, default=160, help="总章数（默认 160）")
    ap.add_argument("--words", type=int, default=0, help="目标总字数（万），可选")
    ap.add_argument("--style", choices=["standard", "fanqie"], default="standard",
                    help="风格档位：standard 通用 / fanqie 番茄小说风格（默认 standard）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = ap.parse_args()

    if args.volumes < 1 or args.chapters < args.volumes:
        print("[错误] 卷数与章数不合法：章数必须不少于卷数")
        return 1

    out_root = Path(args.path).expanduser().resolve()
    if out_root.exists() and any(out_root.iterdir()) and not args.force:
        print("[提示] 目录非空，将只补缺失文件（如需覆盖请加 --force）：%s" % out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    created = []

    # L1 全书大纲
    outline_tpl = read_template("outline-template.md", "# 《书名》全书大纲\n")
    outline_text = outline_tpl.replace("# 《书名》全书大纲", "# %s 全书大纲" % args.book)
    if args.words:
        outline_text = outline_text.replace("约 ______ 万字", "约 %d 万字" % args.words)
    if args.style == "fanqie":
        idx = outline_text.find("\n---\n")
        if idx != -1:
            outline_text = outline_text[:idx] + FANQIE_OUTLINE_BLOCK + outline_text[idx:]
        else:
            outline_text += FANQIE_OUTLINE_BLOCK
    outline_path = out_root / "outline.md"
    if args.force or not outline_path.exists():
        outline_path.write_text(outline_text, encoding="utf-8")
        created.append(outline_path)

    # L2 人物设定
    char_tpl = read_template("characters-template.md", "# 《书名》人物设定\n")
    char_text = char_tpl.replace("# 《书名》人物设定", "# %s 人物设定" % args.book)
    char_path = out_root / "characters.md"
    if args.force or not char_path.exists():
        char_path.write_text(char_text, encoding="utf-8")
        created.append(char_path)

    # L3 / L4
    counts, more = build_volume_files(out_root, args.book, args.volumes, args.chapters, args.force, args.style)
    created.extend(more)

    # 风格档位
    style_path = out_root / "style.json"
    if args.force or not style_path.exists():
        style = {
            "style": args.style,
            "min_words": 1800 if args.style == "fanqie" else 0,
            "max_words": 3500 if args.style == "fanqie" else 0,
            "hook_repeat_limit": 2 if args.style == "fanqie" else 3,
            "shuang_repeat_limit": 3,
            "note": "fanqie：番茄小说风格，check_outline.py 会自动加严规则",
        }
        style_path.write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(style_path)

    # 伏笔台账
    ledger_path = out_root / "ledger.json"
    if args.force or not ledger_path.exists():
        ledger = {"book": args.book, "next_id": 1, "foreshadows": []}
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(ledger_path)

    # 工程元数据
    state_path = out_root / "state.json"
    if args.force or not state_path.exists():
        state = {
            "book": args.book,
            "volumes": args.volumes,
            "chapters": args.chapters,
            "volume_chapters": counts,
            "word_target_wan": args.words or None,
            "style": args.style,
            "stage": "L1",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(state_path)

    print("[完成] 大纲工程已就绪：%s" % out_root)
    print("       卷数 %d / 总章数 %d / 风格档位 %s" % (args.volumes, args.chapters, args.style))
    for p in created:
        print("       + %s" % p.relative_to(out_root))
    print()
    print("下一步：")
    print("  1. 填写 outline.md 的必填区块（L1 全书大纲）")
    print("  2. 填写 characters.md 的人物卡七问与声线卡（L2 人物设定）")
    print("  3. 逐卷展开 volumes/第N卷-卷纲.md（L3 卷纲）")
    print("  4. 逐章填写 细纲/第N卷-细纲.md（L4 细纲）")
    print("  5. 随时体检：python check_outline.py \"%s\" --strict" % out_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
