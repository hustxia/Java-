# -*- coding: utf-8 -*-
"""把 book/ 下的章节 markdown 编译成印刷用的单文件 HTML。

不做渲染（分页、页码、目录由 paginate.js 在浏览器里算），
只负责：解析 front-matter -> 按卷/章排序 -> markdown 转 HTML 片段 -> 套模板。
"""
import os
import re
import glob
import html
import json

BOOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BOOK, "build", "_book.html")

VOLUME = {
    "1": "卷一　请求进来",
    "2": "卷二　业务跑起来",
    "3": "卷三　数据落地",
    "4": "卷四　异步与峰值",
    "5": "卷五　上线之后",
}

TITLE = "Java 后端故障图鉴"
SUBTITLE = "写给要负责的人——那些不报错的 bug"


# ---------------------------------------------------------------- front-matter
def split_front(md):
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            fm = {}
            for line in parts[1].strip().split("\n"):
                if line.startswith((" ", "\t", "-")):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.split("#")[0].strip()
            return fm, parts[2].lstrip("\n")
    return {}, md


# ---------------------------------------------------------------- inline
SYMBOL = {
    "❌": '<span class="mk bad">✕</span>',
    "✅": '<span class="mk good">✓</span>',
    "⚠️": '<span class="mk warn">⚠</span>',
    "⚠": '<span class="mk warn">⚠</span>',
}


def emph(s):
    s = html.escape(s, quote=False)
    for k, v in SYMBOL.items():
        s = s.replace(k, v)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def inline(t):
    """粗体/斜体可能横跨行内代码段（如 **手动 `x()` 和 `y()`**），
    所以先把 ** 换成哨兵、最后统一配对。

    但必须先切出代码段再替换：Spring 路由 `/**`、Ant 通配 `**` 这类写法
    常出现在行内代码里，整行替换会把它们吞成 ＊。代码段内部不做 ** 替换。
    """
    parts = re.split(r"`([^`]+)`", t)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append("<code>%s</code>" % emph(p))
        else:
            out.append(emph(p.replace("**", "\x01")))
    s = "".join(out)
    s = re.sub(r"\x01(.+?)\x01", r"<strong>\1</strong>", s)
    s = s.replace("\x01", "＊")          # 落单的 **，原样兜底
    return s


# ---------------------------------------------------------------- blocks
def is_table_sep(line):
    return bool(re.match(r"^\|[\s:\-|]+\|?\s*$", line)) and "-" in line


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def render_table(lines):
    head = split_row(lines[0])
    aligns = []
    for c in split_row(lines[1]):
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    body = [split_row(l) for l in lines[2:] if l.strip().startswith("|")]
    out = ['<table class="tbl">', "<thead><tr>"]
    for i, c in enumerate(head):
        out.append('<th class="%s">%s</th>' % (aligns[i] if i < len(aligns) else "left", inline(c)))
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>")
        for i, c in enumerate(r):
            a = aligns[i] if i < len(aligns) else "left"
            out.append('<td class="%s">%s</td>' % (a, inline(c)))
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


CODE_SYMBOL = {"❌": "✕", "✅": "✓", "⚠️": "⚠"}


def render_code(lines):
    cls = ""
    if lines and re.match(r"^[a-zA-Z0-9+#-]{1,15}$", lines[0].strip()):
        cls = ' data-lang="%s"' % lines[0].strip()
        lines = lines[1:]
    out = []
    for l in lines:
        for k, v in CODE_SYMBOL.items():
            l = l.replace(k, v)
        out.append('<span class="cl">%s</span>' % (html.escape(l, quote=False) or "\u00a0"))
    return '<pre class="code"%s>%s</pre>' % (cls, "".join(out))


def convert(md):
    """返回 HTML 片段列表（每个元素是一个顶层块）。"""
    lines = md.split("\n")
    out = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        # 代码块
        if s.startswith("```"):
            j = i + 1
            buf = []
            while j < n and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append(render_code(buf))
            i = j + 1
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append('<hr class="sep">')
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lv = len(m.group(1))
            txt = m.group(2).strip()
            out.append("<h%d>%s</h%d>" % (lv, inline(txt), lv))
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            out.append(render_table(lines[i:j]))
            i = j
            continue

        # 引用块
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            paras, cur = [], []
            for b in buf:
                if b.strip():
                    cur.append(b)
                elif cur:
                    paras.append(" ".join(cur))
                    cur = []
            if cur:
                paras.append(" ".join(cur))
            out.append('<blockquote class="quote">%s</blockquote>'
                       % "".join("<p>%s</p>" % inline(p) for p in paras))
            continue

        # 列表
        if re.match(r"^[-*+]\s+", s) or re.match(r"^\d+[.)]\s+", s):
            ordered = bool(re.match(r"^\d+[.)]\s+", s))
            items = []          # (level, text)
            while i < n:
                cur = lines[i]
                mm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", cur)
                if mm:
                    level = 0 if len(mm.group(1)) < 2 else 1
                    items.append([level, mm.group(3).strip()])
                    i += 1
                elif cur.strip() and not re.match(r"^\s*([-*+]|\d+[.)])\s+", cur) \
                        and re.match(r"^\s{2,}\S", cur) and items and not cur.strip().startswith("|"):
                    items[-1][1] += " " + cur.strip()   # 续行
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            htmls = ['<%s class="list">' % tag]
            open_sub = False
            for level, text in items:
                if level == 1 and not open_sub:
                    htmls.append("<ul class=\"sub\">")
                    open_sub = True
                elif level == 0 and open_sub:
                    htmls.append("</ul>")
                    open_sub = False
                htmls.append("<li>%s</li>" % inline(text))
            if open_sub:
                htmls.append("</ul>")
            htmls.append("</%s>" % tag)
            out.append("".join(htmls))
            continue

        # 段落
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,4}\s|```|\||>)", lines[i].strip()) \
                and not re.match(r"^[-*+]\s+", lines[i].strip()) \
                and not re.match(r"^\d+[.)]\s+", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append("<p>%s</p>" % inline("".join(buf)))

    return out


# ---------------------------------------------------------------- chapters
def load_chapters():
    files = sorted(glob.glob(os.path.join(BOOK, "v*.md")))
    items = []
    for f in files:
        md = open(f, encoding="utf-8").read()
        fm, body = split_front(md)
        m = re.match(r"v(\d)-(\d+)-(.+)\.md$", os.path.basename(f))
        vol = int(m.group(1)) if m else 0
        ch = int(m.group(2)) if m else 0
        items.append({"path": f, "vol": vol, "ch": ch, "fm": fm, "body": body})
    items.sort(key=lambda x: (x["vol"], x["ch"]))
    return items


def chapter_html(it):
    blocks = convert(it["body"])
    # 第一个 h1 作为章标题；紧随其后的「> 卷二 · …」作为卷标
    title, kicker = "", ""
    start = 0
    for idx, b in enumerate(blocks[:4]):
        if re.match(r"^<h1>", b):
            title = re.sub(r"<[^>]+>", "", b)
            start = idx + 1
            break
    if start and blocks[start].startswith('<blockquote class="quote">'):
        raw = re.sub(r"<[^>]+>", "", blocks[start]).strip()
        if re.match(r"^卷[一二三四五]", raw):
            kicker = raw
            blocks.pop(start)

    rest = "\n".join(blocks[start:])
    vol = VOLUME.get(str(it["vol"]), "")
    vol_name = kicker or vol
    return ('<div class="chapter-start" data-title="%s" data-vol="%s" data-ch="%d">'
            '<div class="ch-kicker">%s</div>'
            '<h1 class="ch-title">%s</h1>'
            '<div class="ch-rule"></div>'
            "</div>\n%s") % (
        html.escape(title), html.escape(vol_name), it["ch"],
        html.escape(kicker or (vol + "　·　" + str(it["ch"]))),
        html.escape(title), rest)


def main():
    chapters = load_chapters()

    fm_md = open(os.path.join(BOOK, "00-前言.md"), encoding="utf-8").read()
    _, fm_body = split_front(fm_md)
    fm_blocks = convert(fm_body)
    fm_title = ""
    for b in fm_blocks[:3]:
        if b.startswith("<h1>"):
            fm_title = re.sub(r"<[^>]+>", "", b)
            break
    fm_blocks[fm_blocks.index(next(b for b in fm_blocks if b.startswith("<h1>")))] = \
        '<h1 class="fm-title">%s</h1>' % html.escape(fm_title)

    body_parts = [chapter_html(c) for c in chapters]

    css = open(os.path.join(BOOK, "build", "book.css"), encoding="utf-8").read()
    js = open(os.path.join(BOOK, "build", "paginate.js"), encoding="utf-8").read()

    doc = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div id="cover" class="page cover">
  <div class="cv-bar"></div>
  <div class="cv-wrap">
    <div class="cv-top">JAVA&nbsp;&nbsp;BACKEND&nbsp;&nbsp;FAILURE&nbsp;&nbsp;ATLAS</div>
    <h1 class="cv-title">{title}</h1>
    <div class="cv-sub">{subtitle}</div>
    <div class="cv-rule"></div>
    <div class="cv-desc">27 章 · 5 卷 · 从请求进来到故障复盘</div>
  </div>
  <div class="cv-meta">初稿 · 2026 年 11 月</div>
</div>
<div id="pages"></div>
<div id="flow-front">{front}</div>
<div id="flow-body">{body}</div>
<div id="stage"></div>
<div id="stats" style="display:none"></div>
<script>{js}</script>
</body>
</html>""".format(title=TITLE, subtitle=SUBTITLE, css=css, js=js,
                   front="\n".join(fm_blocks), body="\n".join(body_parts))

    open(OUT, "w", encoding="utf-8").write(doc)
    print("章节数 %d  输出 %s  %.0f KB" % (len(chapters), OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
