# -*- coding: utf-8 -*-
"""一键出 PDF：md2html.py 生成 _book.html，Chrome 无头打印成 PDF。

用法：python build.py
产物：book/Java后端故障图鉴-初稿.pdf
"""
import os
import subprocess
import sys

BUILD = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.dirname(BUILD)
HTML = os.path.join(BUILD, "_book.html")
PDF = os.path.join(BOOK, "Java后端故障图鉴-初稿.pdf")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def chrome_path():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Chrome/Edge，请把路径加进 CHROME_CANDIDATES")


def main():
    subprocess.run([sys.executable, os.path.join(BUILD, "merge.py")], check=True)
    subprocess.run([sys.executable, os.path.join(BUILD, "md2html.py")], check=True)

    url = "file:///" + HTML.replace("\\", "/")
    cmd = [chrome_path(),
           "--headless", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer",
           "--virtual-time-budget=60000",
           "--print-to-pdf=" + PDF, url]
    subprocess.run(cmd, check=True)

    size = os.path.getsize(PDF)
    print("PDF: %s  %.1f MB" % (PDF, size / 1e6))


if __name__ == "__main__":
    main()
