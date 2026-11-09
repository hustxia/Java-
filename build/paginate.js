/* ============================================================
   分页引擎
   把 #flow-front / #flow-body 的块元素搬进固定高度的 .page，
   溢出就换页；拆不开的长块（代码、表格、列表）按行/行内子块拆。
   顺带算出每章起始页，生成带页码的目录。
   ============================================================ */
(function () {
    'use strict';

    var pagesRoot = document.getElementById('pages');
    var stage = document.getElementById('stage');

    function makePage(extra) {
        var sec = document.createElement('section');
        sec.className = 'page' + (extra ? ' ' + extra : '');
        sec.innerHTML =
            '<div class="page-head"><span class="ph-l"></span><span class="ph-r"></span></div>' +
            '<div class="page-body"></div>' +
            '<div class="page-foot"><span class="pn"></span></div>';
        return sec;
    }


    /* 已用高度：最后一个子块的底边相对于 body 顶边 —— scrollHeight 在 overflow:hidden 下不可靠 */
    function used(body) {
        var last = body.lastElementChild;
        if (!last) return 0;
        var b = body.getBoundingClientRect();
        var r = last.getBoundingClientRect();
        return r.bottom - b.top + (parseFloat(getComputedStyle(last).marginBottom) || 0);
    }

    /* -------------------- 拆分：把整块装不下的大块切开 -------------------- */
    function splitFill(el, body, avail) {
        if (el.tagName === 'TABLE') return splitTable(el, body, avail);

        var kids = Array.prototype.slice.call(el.children);
        if (!kids.length) { body.appendChild(el); return null; }

        var shell = el.cloneNode(false);
        shell.classList.add('cont');
        body.appendChild(shell);

        var moved = 0;
        for (var i = 0; i < kids.length; i++) {
            shell.appendChild(kids[i]);
            if (used(body) > avail && moved > 0) {
                shell.removeChild(kids[i]);
                break;
            }
            moved++;
        }
        if (moved === 0) {                       /* 单个子块都放不下，硬放一个 */
            shell.appendChild(kids[0]);
        }
        return el.children.length ? el : null;
    }

    function splitTable(el, body, avail) {
        var tbody = el.tBodies[0];
        if (!tbody || !tbody.rows.length) { body.appendChild(el); return null; }

        var shell = el.cloneNode(true);
        var shellBody = shell.tBodies[0];
        while (shellBody.rows.length) shellBody.deleteRow(0);
        body.appendChild(shell);

        var rows = Array.prototype.slice.call(tbody.rows);
        var moved = 0;
        for (var i = 0; i < rows.length; i++) {
            shellBody.appendChild(rows[i]);
            if (used(body) > avail && moved > 0) {
                shellBody.removeChild(rows[i]);
                break;
            }
            moved++;
        }
        if (moved === 0) shellBody.appendChild(rows[0]);

        if (!tbody.rows.length) {
            el.parentNode && el.parentNode.removeChild(el);
            return null;
        }
        var wrap = document.createElement('div');
        wrap.appendChild(el);
        return el;
    }

    /* -------------------- 主分页循环 -------------------- */
    function paginate(blocks, container, cls) {
        var pages = [];
        var page = null, body = null, avail = 0;

        function newPage(inherit) {
            var prev = page;
            page = makePage(cls);
            container.appendChild(page);
            pages.push(page);
            body = page.querySelector('.page-body');
            avail = body.clientHeight;
            if (inherit && prev) {
                page.dataset.vol = prev.dataset.vol || '';
                page.dataset.title = prev.dataset.title || '';
            }
            return page;
        }

        newPage(false);
        if (!window.__dbg) window.__dbg = { avail: avail, pageH: page.offsetHeight, bodyH: body.offsetHeight, headH: page.querySelector('.page-head').offsetHeight };

        function place(b) {
            var isChapter = b.classList.contains('chapter-start');

            if (isChapter && body.childElementCount > 0) newPage(true);
            if (isChapter) {
                page.dataset.vol = b.dataset.vol || '';
                page.dataset.title = b.dataset.title || '';
            }

            /* 标题不要压在页脚边上 */
            if (!isChapter && /^H[23]$/.test(b.tagName) && body.childElementCount > 0) {
                if (avail - used(body) < 105) newPage(true);
            }
            /* 目录条目同理，避免只留一行 */
            if (b.classList.contains('toc-entry') && body.childElementCount > 0) {
                if (avail - used(body) < 40) newPage(true);
            }

            body.appendChild(b);
                        if (used(body) <= avail + 1) return;

            body.removeChild(b);
            if (body.childElementCount > 0) { newPage(true); place(b); return; }

            var rest = splitFill(b, body, avail);
            if (rest) { newPage(true); place(rest); }
        }

        blocks.forEach(place);
        return pages;
    }

    /* -------------------- 目录 -------------------- */
    function buildToc(entries) {
        var blocks = [];
        var head = document.createElement('div');
        head.className = 'toc-head';
        head.innerHTML = '<div class="toc-kicker">CONTENTS</div>' +
            '<h1 class="toc-title">目　录</h1><div class="ch-rule"></div>';
        blocks.push(head);

        var lastVol = null;
        entries.forEach(function (e) {
            if (e.level === 1 && e.vol && e.vol !== lastVol) {
                lastVol = e.vol;
                var v = document.createElement('div');
                v.className = 'toc-vol';
                v.textContent = e.vol;
                blocks.push(v);
            }
            var row = document.createElement('div');
            row.className = 'toc-entry l' + e.level;
            row.innerHTML = '<span class="toc-t"></span><span class="toc-lead"></span><span class="toc-pg"></span>';
            row.querySelector('.toc-t').textContent = e.title;
            row.querySelector('.toc-pg').textContent = e.page;
            blocks.push(row);
        });
        return blocks;
    }

    /* -------------------- 页码：罗马数字 -------------------- */
    function roman(n) {
        var map = [[1000, 'm'], [900, 'cm'], [500, 'd'], [400, 'cd'], [100, 'c'],
                   [90, 'xc'], [50, 'l'], [40, 'xl'], [10, 'x'], [9, 'ix'],
                   [5, 'v'], [4, 'iv'], [1, 'i']];
        var s = '';
        for (var i = 0; i < map.length; i++) {
            while (n >= map[i][0]) { s += map[i][1]; n -= map[i][0]; }
        }
        return s;
    }

    function decorate(page, label) {
        var foot = page.querySelector('.pn');
        if (foot) foot.textContent = label;
        var l = page.querySelector('.ph-l'), r = page.querySelector('.ph-r');
        if (l) l.textContent = page.dataset.vol || '';
        if (r) r.textContent = page.dataset.title || '';
        if (page.querySelector('.chapter-start')) page.classList.add('no-head');
    }

    /* -------------------- 跑 -------------------- */
    function run() {
        window.__trace = [];
        var bodyBlocks = Array.prototype.slice.call(document.getElementById('flow-body').children);
        var frontBlocks = Array.prototype.slice.call(document.getElementById('flow-front').children);

        /* 1. 正文 */
        var bodyPages = paginate(bodyBlocks, stage, 'body');

        var entries = [];
        bodyPages.forEach(function (p, idx) {
            Array.prototype.forEach.call(p.querySelectorAll('.chapter-start, h2'), function (h) {
                if (h.classList.contains('chapter-start')) {
                    entries.push({ level: 1, title: h.dataset.title, vol: h.dataset.vol, page: idx + 1 });
                } else {
                    entries.push({ level: 2, title: h.textContent.trim(), page: idx + 1 });
                }
            });
        });

        /* 2. 目录 */
        var tocPages = paginate(buildToc(entries), stage, 'toc');
        tocPages.forEach(function (p) {
            p.dataset.vol = 'Java 后端故障图鉴';
            p.dataset.title = '目录';
        });

        /* 3. 前言 */
        var frontPages = paginate(frontBlocks, stage, 'front');
        frontPages.forEach(function (p) {
            p.dataset.vol = 'Java 后端故障图鉴';
            if (!p.dataset.title) p.dataset.title = '前言';
        });

        /* 4. 组装 */
        pagesRoot.appendChild(document.createDocumentFragment());
        tocPages.forEach(function (p) { pagesRoot.appendChild(p); });
        frontPages.forEach(function (p) { pagesRoot.appendChild(p); });
        bodyPages.forEach(function (p) { pagesRoot.appendChild(p); });

        /* 5. 编页码 */
        var i;
        for (i = 0; i < tocPages.length; i++) decorate(tocPages[i], roman(i + 1));
        for (i = 0; i < frontPages.length; i++) decorate(frontPages[i], roman(tocPages.length + i + 1));
        for (i = 0; i < bodyPages.length; i++) decorate(bodyPages[i], String(i + 1));

        /* 6. 清理 */
        document.getElementById('flow-front').style.display = 'none';
        document.getElementById('flow-body').style.display = 'none';
        stage.parentNode.removeChild(stage);

        /* 7. 统计 + 单页预览 */
        var total = tocPages.length + frontPages.length + bodyPages.length + 1;
        document.getElementById('stats').textContent = JSON.stringify({
            cover: 1,
            toc: tocPages.length,
            front: frontPages.length,
            body: bodyPages.length,
            total: total,
            entries: entries.length,
            dbg: window.__dbg, trace: window.__trace
        });

        var q = new URLSearchParams(location.search);
        var want = q.get('p');
        if (want) {
            document.body.classList.add('single');
            var all = document.querySelectorAll('.page');
            var k = parseInt(want, 10);
            if (all[k - 1]) all[k - 1].classList.add('keep');
        }
        document.body.classList.add('ready');
    }

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(run);
    } else {
        window.addEventListener('load', run);
    }
})();
