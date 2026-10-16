#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小说大纲结构体检。

用法：
    python check_outline.py ./novel
    python check_outline.py ./novel --strict

体检项：
    1. 工程文件与目录是否齐备
    2. outline.md 的必填区块
    3. characters.md（人物设定）的必填区块
    4. 每份卷纲的必填区块
    5. 每章细纲的字段完整性
    6. 章号是否连续
    7. 章末钩子是否连章重复
    8. 伏笔台账与细纲标注是否配对、是否有超期未回收
    9. 结构层 AI 味机检：ban 词命中、本章变化缺四类关键词、章标题连章同构、钩子套话
   10. 风格档位（style.json / --style）：番茄档位额外查 本章爽点必填、爽点连章重复、
       钩子连续 2 章重复、目标字数区间、长句、文青词

退出码：0 通过；1 未通过。--strict 下警告同样导致未通过。
"""

import argparse
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUTLINE_SECTIONS = [
    "一句话梗概", "故事引擎", "核心冲突", "主角弧光",
    "分卷总览", "人物索引", "关键伏笔", "关键节点年表",
]
CHARACTERS_SECTIONS = [
    "人物总表", "主角卡", "主要配角卡", "反派卡", "关系网", "声线卡", "弧光进度表",
]
VOLUME_SECTIONS = [
    "本卷任务", "卷内起伏", "爽点与压抑配比", "人物进出", "伏笔", "章数分配",
]
CHAPTER_FIELDS_ERROR = ["本章事件", "章末钩子"]
CHAPTER_FIELDS_WARN = ["本章变化", "场景分解", "出场人物", "伏笔", "目标字数"]

# 结构层去 AI 味（详见 references/anti-ai-outline.md）
AI_BAN = [
    "命运的齿轮", "宿命感", "宿命的", "命运的", "不禁", "不由自主", "下意识",
    "与此同时", "内心深处", "五味杂陈", "意味深长", "气氛变得", "空气中弥漫",
    "这一刻他", "他明白了", "不知不觉", "林林总总", "氤氲", "弥漫着",
]
AI_HOOK_CLICHE = ["意味深长", "不安", "微妙", "复杂", "难以言说", "说不清"]
AI_CHANGE_KEYS = ["局面", "权力", "关系", "认知"]
AI_EVENT_MIN_LEN = 8

# 番茄小说风格档位（详见 references/fanqie-style.md）
FANQIE_BAN = [
    "氤氲", "斑驳", "缱绻", "旖旎", "怅然", "恍惚", "疏离", "徜徉",
    "岑寂", "萧索", "迷离", "苍茫", "缄默", "跋涉", "逡巡",
]
FANQIE_MAX_SENTENCE = 40
FANQIE_OUTLINE_SECTIONS = ["书名与简介"]
SHUANG_RE = re.compile(r"类型\s*[=:：]\s*([^\s；;，,、]*)")

CHAP_RE = re.compile(r"^#{2,4}\s*第\s*0*(\d+)\s*章\s*(.*)$")
FIELD_RE = re.compile(r"^-\s*\*\*(.+?)\*\*\s*[：:]\s*(.*)$")
HOOK_RE = re.compile(r"类型\s*[=:：]\s*([^\s；;，,、]*)")
FS_ID_RE = re.compile(r"F-\d+", re.IGNORECASE)
TITLE_JUNK_RE = re.compile(r"[\s《》〈〉“”\"'·、，,。.！!？?—\-:：;；()（）【】\[\]]")


def hits_of(text, words):
    return [w for w in words if w in text]


def scan_ban_lines(text):
    """逐行扫 ban 词，跳过「去 AI 味自检」小节与含 ban 字样的说明行（避免自检清单误报）。"""
    out = []
    in_doc = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            flat = s.replace(" ", "")
            in_doc = ("去AI味" in flat) or ("AI味自检" in flat)
            continue
        if in_doc:
            continue
        if "ban" in s.lower():
            continue
        for w in AI_BAN:
            if w in s:
                out.append(w)
    return out


def read_text(p):
    return p.read_text(encoding="utf-8-sig", errors="replace")


def split_chapter_blocks(text):
    """把一个细纲文件按 '### 第NNN章' 切成块，返回 [(num, title, block_text)]。"""
    lines = text.splitlines()
    blocks, cur = [], None
    for ln in lines:
        m = CHAP_RE.match(ln.strip())
        if m:
            if cur:
                blocks.append(cur)
            cur = [int(m.group(1)), m.group(2).strip(), [ln]]
        elif cur is not None:
            cur[2].append(ln)
    if cur:
        blocks.append(cur)
    return [(n, t, "\n".join(b)) for n, t, b in blocks]


def parse_fields(block_text):
    fields = {}
    for ln in block_text.splitlines():
        m = FIELD_RE.match(ln.strip())
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key not in fields:
                fields[key] = val
    return fields


def main():
    ap = argparse.ArgumentParser(description="小说大纲结构体检")
    ap.add_argument("project", help="大纲工程目录")
    ap.add_argument("--strict", action="store_true", help="警告同样视为未通过")
    ap.add_argument("--style", choices=["standard", "fanqie"], default=None,
                    help="覆盖 style.json 里的风格档位（fanqie = 番茄小说风格，规则更严）")
    args = ap.parse_args()

    root = Path(args.project).expanduser().resolve()
    errors, warns = [], []

    def err(msg):
        errors.append(msg)

    def warn(msg):
        warns.append(msg)

    if not root.is_dir():
        print("[错误] 目录不存在：%s" % root)
        return 1

    # ---------- 风格档位 ----------
    cfg = {}
    style_p = root / "style.json"
    if style_p.exists():
        try:
            cfg = json.loads(read_text(style_p)) or {}
        except Exception as e:
            warn("style.json 解析失败，按 standard 档位处理：%s" % e)
            cfg = {}
    style = args.style or cfg.get("style", "standard")
    if style not in ("standard", "fanqie"):
        style = "standard"
    min_words = cfg.get("min_words") or 0
    max_words = cfg.get("max_words") or 0
    hook_limit = cfg.get("hook_repeat_limit") or 3
    if style == "fanqie":
        min_words = min_words or 1800
        max_words = max_words or 3500
        hook_limit = min(hook_limit, 2)

    outline_p = root / "outline.md"
    chars_p = root / "characters.md"
    ledger_p = root / "ledger.json"
    state_p = root / "state.json"
    vol_dir = root / "volumes"
    chap_dir = root / "细纲"

    for p, name in [(outline_p, "outline.md"), (chars_p, "characters.md"), (ledger_p, "ledger.json"),
                    (vol_dir, "volumes/"), (chap_dir, "细纲/")]:
        if not p.exists():
            err("缺少 %s" % name)

    ai_hits = 0

    # ---------- L1 全书大纲 ----------
    if outline_p.exists():
        t = read_text(outline_p)
        for sec in OUTLINE_SECTIONS:
            if not re.search(r"^##\s*" + re.escape(sec), t, re.M):
                warn("outline.md 缺少区块：## %s" % sec)
        for w in scan_ban_lines(t):
            err("[AI味] outline.md 命中 ban 词「%s」" % w)
            ai_hits += 1
        if style == "fanqie":
            for sec in FANQIE_OUTLINE_SECTIONS:
                if not re.search(r"^##\s*" + re.escape(sec), t, re.M):
                    warn("outline.md 番茄档位缺少区块：## %s（书名与简介决定点击率）" % sec)

    # ---------- L2 人物设定 ----------
    if chars_p.exists():
        t = read_text(chars_p)
        for sec in CHARACTERS_SECTIONS:
            if not re.search(r"^##\s*" + re.escape(sec), t, re.M):
                warn("characters.md 缺少区块：## %s" % sec)
        for w in scan_ban_lines(t):
            err("[AI味] characters.md 命中 ban 词「%s」" % w)
            ai_hits += 1

    # ---------- L3 卷纲 ----------
    vol_files = sorted(vol_dir.glob("*.md")) if vol_dir.exists() else []
    if not vol_files:
        err("volumes/ 下没有卷纲文件")
    for vf in vol_files:
        t = read_text(vf)
        for sec in VOLUME_SECTIONS:
            if not re.search(r"^##\s*" + re.escape(sec), t, re.M):
                warn("%s 缺少区块：## %s" % (vf.name, sec))
        for w in scan_ban_lines(t):
            err("[AI味] %s 命中 ban 词「%s」" % (vf.name, w))
            ai_hits += 1

    # ---------- L4 细纲 ----------
    chap_files = sorted(chap_dir.glob("*.md")) if chap_dir.exists() else []
    if not chap_files:
        err("细纲/ 下没有细纲文件")

    chapters = []          # (num, title, filename, block_text)
    for cf in chap_files:
        t = read_text(cf)
        for num, title, block in split_chapter_blocks(t):
            chapters.append((num, title, cf.name, block))

    chapters.sort(key=lambda x: x[0])

    # 章号连续
    nums = [c[0] for c in chapters]
    dups = sorted({n for n in nums if nums.count(n) > 1})
    if dups:
        err("细纲存在重复章号：%s" % ", ".join("第%03d章" % n for n in dups))
    if nums:
        expected = list(range(1, nums[-1] + 1))
        missing = [n for n in expected if n not in set(nums)]
        if missing:
            err("细纲章号不连续，缺：%s" % ", ".join("第%03d章" % n for n in missing[:20]))

    # 字段完整性 + 钩子类型 + 结构层 AI 味
    hook_seq = []
    title_seq = []
    shuang_seq = []
    for num, title, fname, block in chapters:
        fields = parse_fields(block)
        for f in CHAPTER_FIELDS_ERROR:
            if f not in fields:
                err("%s 第%03d章 缺少字段「%s」" % (fname, num, f))
            elif not fields[f].strip():
                err("%s 第%03d章 字段「%s」为空" % (fname, num, f))
        for f in CHAPTER_FIELDS_WARN:
            if f not in fields:
                warn("%s 第%03d章 缺少字段「%s」" % (fname, num, f))

        # 钩子类型
        hook_val = fields.get("章末钩子", "")
        if hook_val:
            m = HOOK_RE.search(hook_val)
            if not m:
                warn("%s 第%03d章 章末钩子未标注「类型=」" % (fname, num))
            elif not m.group(1).strip():
                err("%s 第%03d章 章末钩子类型为空" % (fname, num))
            else:
                hook_seq.append((num, m.group(1).strip()))

        # --- AI 味：事件字段 ---
        ev = fields.get("本章事件", "").strip()
        if ev:
            for w in hits_of(ev, AI_BAN):
                err("[AI味] 第%03d章 本章事件命中 ban 词「%s」" % (num, w))
                ai_hits += 1
            if len(TITLE_JUNK_RE.sub("", ev)) < AI_EVENT_MIN_LEN:
                warn("[AI味] 第%03d章 本章事件过短或过于概括，缺少具体动作" % num)
        # --- AI 味：变化字段 ---
        ch = fields.get("本章变化", "").strip()
        if ch and not any(k in ch for k in AI_CHANGE_KEYS):
            warn("[AI味] 第%03d章 本章变化未命中 局面/权力/关系/认知 四类之一" % num)
        # --- AI 味：钩子 ---
        if hook_val:
            for w in hits_of(hook_val, AI_BAN):
                err("[AI味] 第%03d章 章末钩子命中 ban 词「%s」" % (num, w))
                ai_hits += 1
            content = re.sub(r"^.*?类型\s*[=:：]\s*[^\s；;，,、]*", "", hook_val)
            for w in AI_HOOK_CLICHE:
                if w in content:
                    warn("[AI味] 第%03d章 钩子内容含抽象感受词「%s」，改为具体事件" % (num, w))
                    break
        # --- 番茄档位专属检查 ---
        if style == "fanqie":
            if "开篇抓手" not in fields:
                warn("%s 第%03d章 番茄档位缺少字段「开篇抓手」" % (fname, num))
            elif not fields["开篇抓手"].strip():
                warn("%s 第%03d章 番茄档位未填「开篇抓手」（本章前 300 字要抛的冲突）" % (fname, num))

            if "本章爽点" not in fields:
                err("%s 第%03d章 番茄档位缺少字段「本章爽点」" % (fname, num))
            else:
                sv = fields["本章爽点"].strip()
                if sv == "":
                    err("%s 第%03d章 番茄档位「本章爽点」为空" % (fname, num))
                else:
                    m = SHUANG_RE.search(sv)
                    if m is None:
                        warn("%s 第%03d章 本章爽点未标注「类型=」" % (fname, num))
                    elif not m.group(1).strip():
                        err("%s 第%03d章 本章爽点类型为空" % (fname, num))
                    else:
                        shuang_seq.append((num, m.group(1).strip()))
                    if "兑现" not in sv:
                        warn("%s 第%03d章 本章爽点未写「兑现=」具体兑现方式" % (fname, num))

            wv = fields.get("目标字数", "").strip()
            wn = re.findall(r"\d+", wv)
            if wn:
                w = int(wn[0])
                if (min_words and w < min_words) or (max_words and w > max_words):
                    warn("%s 第%03d章 目标字数 %d 超出番茄档位区间 %d-%d" % (fname, num, w, min_words, max_words))

            if ev:
                long_sents = [s for s in re.split(r"[。！？!?；;\n]", ev)
                              if len(TITLE_JUNK_RE.sub("", s)) > FANQIE_MAX_SENTENCE]
                if long_sents:
                    warn("%s 第%03d章 本章事件含长句（超 %d 字），番茄档位建议拆成短句"
                         % (fname, num, FANQIE_MAX_SENTENCE))

        # --- 文青词（番茄档位告警）---
        if style == "fanqie":
            blob = " ".join([fields.get("本章事件", ""), fields.get("开篇抓手", ""),
                             fields.get("本章变化", ""), fields.get("章末钩子", "")])
            for w in FANQIE_BAN:
                if w in blob:
                    warn("[番茄] 第%03d章 出现文青词「%s」，通常说明这段在写文学而不是写剧情" % (num, w))
                    break

        # --- 章标题（用于同构检测）---
        tt = title.strip()
        if tt and tt != "章标题":
            title_seq.append((num, len(TITLE_JUNK_RE.sub("", tt))))

    def consecutive_same(seq, k):
        out = []
        for i in range(len(seq) - k + 1):
            win = seq[i:i + k]
            if len({x[1] for x in win}) == 1 and all(win[j + 1][0] == win[j][0] + 1 for j in range(k - 1)):
                out.append(win)
        return out

    for win in consecutive_same(hook_seq, hook_limit):
        warn("第%03d-%03d章 章末钩子连续同类型「%s」%s"
             % (win[0][0], win[-1][0], win[0][1], "（番茄档位限 2 章）" if style == "fanqie" else ""))

    if style == "fanqie":
        for win in consecutive_same(shuang_seq, 3):
            warn("[番茄] 第%03d-%03d章 本章爽点连续同类型「%s」" % (win[0][0], win[-1][0], win[0][1]))
        last_ch = nums[-1] if nums else 0
        for start in range(1, last_ch + 1, 5):
            win = [s[1] for s in shuang_seq if start <= s[0] < start + 5]
            if len(win) >= 3 and len(set(win)) < 3:
                warn("[番茄] 第%03d-%03d章 爽点类型只覆盖 %d 种，建议每 5 章至少 3 种"
                     % (start, min(start + 4, last_ch), len(set(win))))

    for win in consecutive_same(title_seq, 3):
        warn("[AI味] 第%03d-%03d章 章标题疑似同构（去标点后均为 %d 字）" % (win[0][0], win[-1][0], win[0][1]))

    # ---------- 伏笔台账 ----------
    ledger = None
    if ledger_p.exists():
        try:
            ledger = json.loads(read_text(ledger_p))
        except Exception as e:
            err("ledger.json 解析失败：%s" % e)

    if isinstance(ledger, dict):
        items = ledger.get("foreshadows") or []
        ids = {str(it.get("id", "")).upper() for it in items if it.get("id")}
        max_ch = nums[-1] if nums else 0

        # 细纲里出现的收/埋
        planted_in_outline, resolved_in_outline = set(), set()
        for num, title, fname, block in chapters:
            val = parse_fields(block).get("伏笔", "")
            if not val:
                continue
            for part in re.split(r"[；;]", val):
                found = {x.upper() for x in FS_ID_RE.findall(part)}
                if not found:
                    continue
                if "埋" in part:
                    planted_in_outline |= found
                if "收" in part:
                    resolved_in_outline |= found

        # 幽灵伏笔：细纲收了台账里没有的编号
        ghosts = sorted(resolved_in_outline - ids) if ids else sorted(resolved_in_outline)
        for g in ghosts:
            err("细纲标注「收 %s」，但台账中没有该伏笔" % g)

        # 台账与细纲不一致
        for it in items:
            fid = str(it.get("id", "")).upper()
            st = str(it.get("status", "open")).lower()
            due = it.get("due_chapter")
            plant = it.get("plant_chapter")
            if plant and fid not in planted_in_outline and plant <= max_ch:
                warn("台账 %s 声称在第 %s 章埋下，但细纲未见「埋 %s」" % (fid, plant, fid))
            resolved = st in ("resolved", "closed", "done") or fid in resolved_in_outline
            if not resolved and isinstance(due, int) and max_ch and due <= max_ch:
                warn("伏笔 %s 计划第 %s 章回收，已过期未收" % (fid, due))

        open_cnt = sum(
            1 for it in items
            if str(it.get("status", "open")).lower() not in ("resolved", "closed", "done")
            and str(it.get("id", "")).upper() not in resolved_in_outline
        )
        print("伏笔台账：共 %d 条，未回收 %d 条" % (len(items), open_cnt))

    # ---------- 汇总 ----------
    print()
    print("=" * 56)
    print("大纲结构体检报告：%s" % root)
    print("=" * 56)
    print("细纲：%d 份文件 / %d 章" % (len(chap_files), len(chapters)))
    print("卷纲：%d 份" % len(vol_files))
    print("风格档位：%s%s" % (style, "（番茄小说：爽点必填、钩子限 2 章、字数 %d-%d）" % (min_words, max_words)
                              if style == "fanqie" else "（通用）"))
    if chars_p.exists():
        ctext = read_text(chars_p)
        have = sum(1 for s in CHARACTERS_SECTIONS if re.search(r"^##\s*" + re.escape(s), ctext, re.M))
        print("人物设定：characters.md（必填区块 %d/%d）" % (have, len(CHARACTERS_SECTIONS)))
    print("结构层 AI 味：%d 处 ban 词命中" % ai_hits)
    print()

    if errors:
        print("【错误 %d】" % len(errors))
        for e in errors:
            print("  ✗ %s" % e)
        print()
    if warns:
        print("【警告 %d】" % len(warns))
        for w in warns:
            print("  ! %s" % w)
        print()

    if not errors and not warns:
        print("✓ 结构体检全绿。")
    else:
        print("结论：错误 %d 项，警告 %d 项。" % (len(errors), len(warns)))
        print("提示：字段缺失 → 补细纲；伏笔未回收 → 回卷纲/全书大纲重排；钩子重复或同构 → 改章末设计；")
        print("      人物工具人 → 回 characters.md 补七问；AI 味命中 → 按 references/anti-ai-outline.md 改写对照重写该字段；")
        print("      番茄档位告警 → 按 references/fanqie-style.md 调爽点密度、钩子与字数。")

    failed = bool(errors) or (args.strict and bool(warns))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
