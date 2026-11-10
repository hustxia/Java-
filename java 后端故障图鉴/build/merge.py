# -*- coding: utf-8 -*-
"""从章节文件重生成 _全书合订.md（通读版，勿手改）。"""
import os
import re
import glob

BOOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BOOK, "_全书合订.md")

VOLUMES = {
    1: "卷一 请求进来",
    2: "卷二 业务跑起来",
    3: "卷三 数据落地",
    4: "卷四 异步与峰值",
    5: "卷五 上线之后",
}


def strip_fm(s):
    if s.startswith("---"):
        parts = s.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return s


def main():
    files = sorted(glob.glob(os.path.join(BOOK, "v*.md")))
    order = [os.path.join(BOOK, "00-前言.md")] + files

    out = ["# Java 后端故障图鉴\n\n> 写给要负责的人——那些不报错的 bug\n\n---\n\n"]
    out.append("## 目录\n\n")
    cur = None
    for f in order:
        if os.path.basename(f).startswith("00-"):
            out.append("- 前言　写给要负责的人\n")
            continue
        m = re.match(r"v(\d)-(\d+)-(.+)\.md$", os.path.basename(f))
        if not m:
            continue
        vol, ch, name = int(m.group(1)), int(m.group(2)), m.group(3)
        if vol != cur:
            out.append("\n**%s**\n\n" % VOLUMES[vol])
            cur = vol
        out.append("- 第%d章　%s\n" % (ch, name))
    out.append("\n---\n\n")

    for f in order:
        body = strip_fm(open(f, encoding="utf-8").read())
        out.append(body.rstrip() + "\n\n---\n\n")

    text = "".join(out).rstrip().rstrip("-").rstrip() + "\n"
    open(OUT, "w", encoding="utf-8").write(text)
    print("合订本 %d 章  %d 汉字  %.0f KB" % (
        len(files), len(re.findall(r"[\u4e00-\u9fa5]", text)), os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
