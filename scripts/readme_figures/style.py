FONTS = [
 ("Fraunces",400,"normal","fraunces-latin-400-normal.woff2"),
 ("Fraunces",400,"italic","fraunces-latin-400-italic.woff2"),
 ("Fraunces",600,"normal","fraunces-latin-600-normal.woff2"),
 ("Fraunces",700,"normal","fraunces-latin-700-normal.woff2"),
 ("IBM Plex Sans",400,"normal","ibm-plex-sans-latin-400-normal.woff2"),
 ("IBM Plex Sans",500,"normal","ibm-plex-sans-latin-500-normal.woff2"),
 ("IBM Plex Sans",600,"normal","ibm-plex-sans-latin-600-normal.woff2"),
 ("JetBrains Mono",400,"normal","jetbrains-mono-latin-400-normal.woff2"),
 ("JetBrains Mono",500,"normal","jetbrains-mono-latin-500-normal.woff2"),
]
def fontface(urlmap):
    return "\n".join(f"@font-face{{font-family:'{f}';font-weight:{w};font-style:{s};src:url('{urlmap[file]}') format('woff2');}}" for f,w,s,file in FONTS)

CSS = r"""
body{margin:0}
.fig{--sans:'IBM Plex Sans','Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif;
--serif:'Fraunces','Noto Serif CJK SC','Songti SC',serif;--mono:'JetBrains Mono','Noto Sans Mono CJK SC',ui-monospace,monospace;
--bg:#F6F3EC;--card:#FFFFFF;--ink:#1C1B18;--muted:#6A655B;--faint:#A39D90;--line:#DDD6C8;--accent:#C8452A;--accent-ink:#FFFFFF;
--t1:#FBF0DA;--k1:#E2BE78;--d1:#8A5E0E;--t2:#E8F0E4;--k2:#A9C4A2;--d2:#3F6B3A;--t3:#E4EDF8;--k3:#A6BFE0;--d3:#2F5A92;
--t4:#FBE5DC;--k4:#EBAE98;--d4:#B23E22;--t5:#EEE8F6;--k5:#C3B4DE;--d5:#5E4A8C;--shadow:0 18px 40px -18px rgba(60,40,20,.35);
position:relative;overflow:hidden;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.4;box-sizing:border-box}
.fig.dark{--bg:#121317;--card:#1C1E24;--ink:#ECE7DD;--muted:#A19C91;--faint:#6E6A62;--line:#30333B;--accent:#F07152;--accent-ink:#1A0C08;
--t1:#272116;--k1:#6B5429;--d1:#F0C36E;--t2:#19241D;--k2:#3F5E45;--d2:#9DD29A;--t3:#17202C;--k3:#3B5578;--d3:#9DBEF0;
--t4:#2A1A16;--k4:#7A3E2E;--d4:#F59A7E;--t5:#211D2B;--k5:#53477A;--d5:#C7B6F2;--shadow:0 18px 40px -18px rgba(0,0,0,.8)}
.fig *{box-sizing:border-box}
.mono{font-family:var(--mono)}.serif{font-family:var(--serif)}
.abs{position:absolute}
.ov{position:absolute;left:0;top:0;pointer-events:none;overflow:visible}
.s1{--t:var(--t1);--k:var(--k1);--d:var(--d1)}.s2{--t:var(--t2);--k:var(--k2);--d:var(--d2)}.s3{--t:var(--t3);--k:var(--k3);--d:var(--d3)}
.s4{--t:var(--t4);--k:var(--k4);--d:var(--d4)}.s5{--t:var(--t5);--k:var(--k5);--d:var(--d5)}
.panel{position:absolute;background:var(--t);border:1px solid var(--k);border-radius:16px;padding:16px 14px 14px;display:flex;flex-direction:column;gap:8px}
.ph{display:flex;align-items:center;gap:10px;margin-bottom:4px}
.num{width:28px;height:28px;border-radius:50%;background:var(--d);color:var(--bg);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-weight:500;font-size:14px;flex:none}
.pt{font-family:var(--serif);font-weight:600;font-size:20px;line-height:1.1;color:var(--ink)}
.pe{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--d);margin-top:3px}
.blk{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.blk b{display:block;font-weight:600;font-size:14px;line-height:1.3}
.blk span{display:block;color:var(--muted);font-size:12.5px;line-height:1.35;margin-top:2px}
.blk.hl{border:1.5px solid var(--d);box-shadow:0 0 0 3px color-mix(in srgb,var(--d) 14%,transparent)}
.row{display:flex;gap:6px}.row>*{flex:1;min-width:0}
.lbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--k);background:var(--card);border-radius:999px;padding:3px 9px;font-size:12.5px;white-space:nowrap}
.chip.dash{border-style:dashed;background:transparent;color:var(--muted)}
.dn{display:flex;justify-content:center;height:14px;color:var(--d)}
.cap{font-size:13.5px;color:var(--muted);line-height:1.5}.cap b{color:var(--ink);font-weight:600}
.tag{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase}
"""

def svg_defs():
    return """<defs>
<marker id="ah" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" style="fill:var(--muted)"></path></marker>
<marker id="ahA" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" style="fill:var(--accent)"></path></marker>
<marker id="ahD" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" style="fill:var(--d5)"></path></marker>
<marker id="ahB" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" style="fill:var(--d3)"></path></marker>
</defs>"""

DOWN = '<div class="dn"><svg width="12" height="14" viewBox="0 0 12 14"><path d="M6 1v10M2 8l4 4 4-4" style="fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round"></path></svg></div>'

# original mark: a bookmark ribbon whose notch throws three sparks
def mark(size=32, color="var(--accent)", spark="var(--accent)"):
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 32 32"><path d="M8 3h13a2 2 0 0 1 2 2v19l-8.5-5.5L6 24V5a2 2 0 0 1 2-2z" style="fill:none;stroke:{color};stroke-width:2.2;stroke-linejoin:round"></path><path d="M14.5 22.5v6.5M10 21.5l-3.2 5M19 21.5l3.2 5" style="fill:none;stroke:{spark};stroke-width:2.2;stroke-linecap:round"></path></svg>'''
