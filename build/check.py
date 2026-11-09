# -*- coding: utf-8 -*-
"""扩写后的统一收口：引号风格归一 + 渲染前静态体检。一次性脚本，跑完即删。"""
import io, os, glob, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(glob.glob(os.path.join(BASE, 'v*.md')))

# ---- 1) 引号归一：中文弯引号 -> ASCII 直引号（与基准章 6-8 及全书 19 章一致）----
changed = []
for f in FILES:
    s = io.open(f, encoding='utf-8').read()
    n = s.count(chr(0x201c)) + s.count(chr(0x201d))
    if n:
        s = s.replace(chr(0x201c), '"').replace(chr(0x201d), '"')
        io.open(f, 'w', encoding='utf-8', newline='').write(s)
        changed.append((os.path.basename(f), n))
print('引号归一:', len(changed), '章', changed)

# ---- 2) 静态体检 ----
problems = []
for f in FILES:
    name = os.path.basename(f)
    s = io.open(f, encoding='utf-8').read()
    lines = s.split('\n')

    if s.count('```') % 2:
        problems.append((name, '代码围栏未配对', s.count('```')))
    if chr(0xff0a) in s:
        problems.append((name, '出现全角星号兜底 ＊（说明有落单 **）', s.count(chr(0xff0a))))
    for ch in s:
        o = ord(ch)
        if o < 32 and ch not in '\n\t\r':
            problems.append((name, '控制字符 U+%04X' % o, ''))
            break
    if '\x01' in s:
        problems.append((name, '残留哨兵字符', ''))

    incode = False
    for i, l in enumerate(lines, 1):
        if l.startswith('```'):
            incode = not incode
            continue
        if incode:
            continue
        # 行内代码里的 ** 多为 Ant/Spring 路径通配（如 `/**`），不是粗体标记
        plain = re.sub('`[^`]+`', '', l)
        if plain.count('**') % 2:
            problems.append((name, '行%d 落单 **' % i, l[:70]))
        # 反引号行内代码：奇数个 `
        if l.count('`') % 2 and not l.startswith('|'):
            problems.append((name, '行%d 反引号奇数' % i, l[:70]))

    # 表格：连续以 | 开头的行视为一张表，组内列数须一致
    grp = []
    groups = []
    for l in lines + ['']:
        if l.startswith('|'):
            grp.append(l)
        else:
            if len(grp) >= 2:
                groups.append(grp)
            grp = []
    for gi, g in enumerate(groups, 1):
        cols = [row.count('|') for row in g]
        if len(set(cols)) > 1:
            problems.append((name, '第%d张表列数不一致 %s' % (gi, cols), g[0][:60]))
        # 分隔行
        if len(g) >= 2 and not re.match(r'^\|[\s:\-|]+\|$', g[1].strip()):
            problems.append((name, '第%d张表缺分隔行' % gi, g[1][:60]))

    # front-matter
    if 'status: review' not in s:
        problems.append((name, 'status 不是 review', ''))
    m = re.search('words:[ ]*([0-9]+)', s)
    if not m:
        problems.append((name, 'words 缺失', ''))
    else:
        real = len(re.findall('[\u4e00-\u9fa5]', s))
        if int(m.group(1)) != real:
            problems.append((name, 'words=%s 实测=%d 不符' % (m.group(1), real), ''))

    # 新增 ### 但不得新增非 X.Y 的 ## 大节（第27章模板已降级为 ###）
    for l in lines:
        if l.startswith('## ') and not re.match(r'^## [0-9]+\.[0-9]+', l):
            problems.append((name, '异常二级标题', l[:60]))

print('\n问题数:', len(problems))
for p in problems[:60]:
    print('  ', p[0], '|', p[1], '|', p[2])
