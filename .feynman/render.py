#!/usr/bin/env python3
"""把 report.md 渲染成自包含网页。不引任何外部资源,双击能开。"""
import html, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
md = open(os.path.join(HERE, "report.md"), encoding="utf-8").read()

def inline(t):
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w])(https?://[^\s<)]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
    return t

out, i, lines = [], 0, md.split("\n")
while i < len(lines):
    l = lines[i]
    if l.startswith("```"):
        blk = []; i += 1
        while i < len(lines) and not lines[i].startswith("```"): blk.append(lines[i]); i += 1
        out.append("<pre><code>" + html.escape("\n".join(blk)) + "</code></pre>"); i += 1; continue
    if l.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells): rows.append(cells)
            i += 1
        if rows:
            h = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
        continue
    if l.startswith(">"):
        blk = []
        while i < len(lines) and lines[i].startswith(">"):
            blk.append(lines[i].lstrip(">").strip()); i += 1
        out.append("<blockquote>" + "<br>".join(inline(x) for x in blk if x) + "</blockquote>"); continue
    m = re.match(r"^(#{1,4})\s+(.*)$", l)
    if m:
        n = len(m.group(1)); out.append(f"<h{n}>{inline(m.group(2))}</h{n}>"); i += 1; continue
    if re.match(r"^\s*[-*]\s+", l) or re.match(r"^\s*\d+\.\s+", l):
        items, ordered = [], bool(re.match(r"^\s*\d+\.", l))
        while i < len(lines) and (re.match(r"^\s*[-*]\s+", lines[i]) or re.match(r"^\s*\d+\.\s+", lines[i])
                                  or (lines[i].startswith("  ") and lines[i].strip() and items)):
            t = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i])
            if lines[i].startswith("  ") and not re.match(r"^\s*(?:[-*]|\d+\.)\s", lines[i]) and items:
                items[-1] += " " + t.strip()
            else: items.append(t)
            i += 1
        tag = "ol" if ordered else "ul"
        out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); continue
    if l.strip() == "---": out.append("<hr>"); i += 1; continue
    if l.strip(): out.append(f"<p>{inline(l)}</p>")
    i += 1

CSS = """
:root{--ground:#EFEFF2;--paper:#FFF;--paper-2:#F6F6F9;--line:#DCDCE4;--line-2:#E9E9F0;
 --ink:#15171C;--ink-2:#4E525E;--ink-3:#82879A;--dye:#2B3F7A;--dye-soft:#E4E8F4;
 --pass:#1C6448;--fail:#9C3222;--warn:#7E5714;
 --mono:ui-monospace,SFMono-Regular,Menlo,"Courier New",monospace;
 --sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;}
@media(prefers-color-scheme:dark){:root{--ground:#0E1015;--paper:#161922;--paper-2:#1D212C;
 --line:#2A2F3D;--line-2:#232733;--ink:#E7E9EF;--ink-2:#A7ADBE;--ink-3:#767D92;
 --dye:#93A9E4;--dye-soft:#1A2140;--pass:#63C79E;--fail:#EC9481;--warn:#DFB25C;}}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:15.5px;
 line-height:1.75;margin:0;-webkit-font-smoothing:antialiased}
.wrap{max-width:820px;margin:0 auto;padding:44px 26px 90px}
h1{font-size:30px;font-weight:600;letter-spacing:-.022em;line-height:1.22;margin:0 0 6px}
h2{font-size:22px;font-weight:600;margin:46px 0 14px;padding-top:20px;border-top:1px solid var(--line);letter-spacing:-.015em}
h3{font-size:17px;font-weight:600;margin:30px 0 10px}
h4{font-size:15px;font-weight:600;margin:22px 0 8px;color:var(--ink-2)}
p{margin:11px 0}
ul,ol{margin:11px 0;padding-left:22px}li{margin:5px 0}
hr{border:none;border-top:1px solid var(--line);margin:34px 0}
code{font-family:var(--mono);font-size:12.5px;background:var(--paper-2);padding:1px 5px;
 border-radius:3px;border:1px solid var(--line-2)}
pre{background:var(--paper);border:1px solid var(--line);border-radius:5px;padding:14px 16px;
 overflow-x:auto;margin:14px 0}
pre code{background:none;border:none;padding:0;font-size:12px;line-height:1.6}
blockquote{border-left:3px solid var(--dye);background:var(--dye-soft);margin:16px 0;
 padding:12px 16px;border-radius:0 4px 4px 0;color:var(--ink-2);font-size:14.5px}
blockquote strong{color:var(--ink)}
.tw{overflow-x:auto;margin:16px 0;border:1px solid var(--line);border-radius:5px;background:var(--paper)}
table{border-collapse:collapse;width:100%;min-width:440px}
th,td{text-align:left;padding:9px 13px;border-bottom:1px solid var(--line-2);font-size:14px;vertical-align:top}
tbody tr:last-child td{border-bottom:none}
thead th{background:var(--paper-2);font-size:12px;font-weight:600;color:var(--ink-3);
 letter-spacing:.04em;border-bottom:1px solid var(--line)}
a{color:var(--dye)}
strong{font-weight:600}
"""
doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>澜绣云裳agent · 项目解读报告</title><style>{CSS}</style></head>
<body><div class="wrap">{''.join(out)}</div></body></html>"""
open(os.path.join(HERE, "report.html"), "w", encoding="utf-8").write(doc)
print(f"report.html {len(doc)/1024:.0f} KB")
