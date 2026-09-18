from style import svg_defs, DOWN, mark

def L(lang, zh, en): return zh if lang=="zh" else en

# ---------------------------------------------------------------- PIPELINE
def pipeline(lang):
    W,H=1280,846
    t=lambda z,e: L(lang,z,e)
    cw,gap,x0,py,ph=212,35,40,112,482
    xs=[x0+i*(cw+gap) for i in range(5)]
    def head(n,z,e,en):
        return f'<div class="ph"><div class="num">{n}</div><div><div class="pt">{t(z,e)}</div><div class="pe">{en if lang=="zh" else "stage 0"+str(n)}</div></div></div>'
    def blk(b,s="",cls=""):
        return f'<div class="blk {cls}"><b>{b}</b>' + (f'<span>{s}</span>' if s else '') + '</div>'
    p=[]
    # 1 capture
    p.append(f'''<div class="panel s1" style="left:{xs[0]}px;top:{py}px;width:{cw}px;height:{ph}px">
{head(1,"收进来","Capture","capture")}
{blk(t("点网站自己的收藏按钮","Click the site's own save"),t("13 个站点内置规则","13 built-in site recipes"))}
{blk(t("收藏夹一键扫描","One-click folder scan"),t("自动翻完，存量一次收齐","Auto-scrolls the whole backlog"))}
{blk(t("工具栏 · 任意页面","Toolbar · any page"),t("activeTab：只在点击时授权","activeTab: granted per click"))}
<div class="lbl" style="margin-top:6px">{t("内容源","content sources")}</div>
<div style="display:flex;flex-wrap:wrap;gap:6px">
<span class="chip">{t("字幕","Subtitles")}</span><span class="chip">{t("高赞评论","Top comments")}</span><span class="chip">{t("网页正文","Page body")}</span><span class="chip dash">Whisper*</span></div>
</div>''')
    # 2 index
    p.append(f'''<div class="panel s2" style="left:{xs[1]}px;top:{py}px;width:{cw}px;height:{ph}px">
{head(2,"建索引","Index","index")}
{blk(t("分块","Chunk"),t("视频按时间戳 · 帖子按自然段","Videos by timestamp · posts by paragraph"))}
{DOWN}
{blk(t("分词","Tokenize"),t("CJK 一元 + 二元组 · 拉丁词","CJK uni+bigrams · Latin words"))}
{DOWN}
<div class="row">{blk("BM25",t("倒排索引","inverted"))}{blk(t("向量","Vectors"),t("哈希 / e5","hash / e5"))}</div>
{DOWN}
<div class="blk" style="display:flex;gap:10px;align-items:center">
<svg width="26" height="30" viewBox="0 0 26 30" style="flex:none"><ellipse cx="13" cy="6" rx="11" ry="4" style="fill:none;stroke:var(--d2);stroke-width:1.6"></ellipse><path d="M2 6v18c0 2.2 4.9 4 11 4s11-1.8 11-4V6M2 15c0 2.2 4.9 4 11 4s11-1.8 11-4" style="fill:none;stroke:var(--d2);stroke-width:1.6"></path></svg>
<div><b>IndexedDB</b><span>{t("留在浏览器 profile 里","stays in your browser profile")}</span></div></div>
</div>''')
    # 3 retrieve
    p.append(f'''<div class="panel s3" style="left:{xs[2]}px;top:{py}px;width:{cw}px;height:{ph}px">
{head(3,"检索","Retrieve","retrieve")}
{blk(t("查询 = 当前页面","Query = current page"),t("标题 · 作者 · 标签 · 简介","title · author · tags · desc"))}
<div class="row">{blk("BM25",t("精确术语","exact terms"))}{blk("Dense",t("同义改写","paraphrase"))}</div>
{DOWN}
{blk(t("RRF 融合","RRF fusion"),t("0.6·向量 + 0.4·BM25 · k=60","0.6 dense + 0.4 BM25 · k=60"))}
{DOWN}
{blk(t("每条收藏最多 4 段","≤ 4 chunks per save"),t("替代 MMR：同源片段是互证","not MMR: siblings corroborate"))}
{DOWN}
{blk(t("置信度门控","Confidence gate"),t("conf ≥ 0.30 · 收藏 ≥ 15 条","conf ≥ 0.30 · library ≥ 15"),"hl")}
</div>''')
    # 4 surface
    p.append(f'''<div class="panel s4" style="left:{xs[3]}px;top:{py}px;width:{cw}px;height:{ph}px">
{head(4,"提醒","Surface","surface")}
<div class="blk" style="padding:0;overflow:hidden;box-shadow:var(--shadow);border-color:var(--k4)">
<div style="display:flex;align-items:center;gap:6px;padding:7px 10px;border-bottom:1px solid var(--line)">{mark(14)}<span style="font-size:11.5px;font-weight:600">你收藏过相关的</span><span class="mono" style="font-size:10.5px;color:var(--d4);margin-left:auto">1</span></div>
<div style="padding:8px 10px">
<div style="font-weight:600;font-size:13px;line-height:1.3;color:var(--d4);text-decoration:underline;text-underline-offset:2px">How Vector Databases Actually Work</div>
<div style="font-size:11px;color:var(--muted);margin-top:3px">YouTube · Watch Later</div>
<div style="font-size:11.5px;color:var(--muted);margin-top:4px;line-height:1.4"><span class="mono" style="color:var(--d4)">16:40</span> The real failure mode of pure vector search is…</div>
<div style="margin-top:7px;display:inline-block;border:1px solid var(--line);border-radius:7px;font-size:11.5px;padding:3px 9px">✓ 学完了</div></div>
<div style="padding:6px 10px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)">这条不用再提醒</div>
</div>
{blk(t("视频 → 跳到那一秒","Video → the exact second"),t("深链带 t= 时间戳","deep link with t= timestamp"))}
{blk(t("帖子 → 滚到那一段","Post → the exact passage"),t(":~:text= 滚动并高亮",":~:text= scroll + highlight"))}
</div>''')
    # 5 close
    p.append(f'''<div class="panel s5" style="left:{xs[4]}px;top:{py}px;width:{cw}px;height:{ph}px">
{head(5,"收口","Close the loop","close")}
<div class="blk" style="text-align:center"><b>{t("还欠着","Active")}</b><span>{t("默认 · 会弹","default · may fire")}</span></div>
<div style="position:relative;height:26px"><svg width="{cw-28}" height="26" viewBox="0 0 {cw-28} 26"><path d="M{(cw-28)/2} 0 L{(cw-28)/2} 8 M{(cw-28)/2} 8 Q{(cw-28)/2} 14 {(cw-28)*0.27} 14 L{(cw-28)*0.25} 22 M{(cw-28)/2} 8 Q{(cw-28)/2} 14 {(cw-28)*0.73} 14 L{(cw-28)*0.75} 22" style="fill:none;stroke:var(--d5);stroke-width:1.5"></path></svg></div>
<div class="row">{blk(t("已学完","Digested"),t("卡片一键","one click"),"hl")}{blk(t("已静音","Muted"),t("仍可搜到","still searchable"))}</div>
<div style="margin-top:auto;border-top:1px dashed var(--k5);padding-top:10px">
<div class="lbl" style="color:var(--d5)">{t("成功指标","success metric")}</div>
<div class="serif" style="font-size:26px;font-weight:600;line-height:1.15;margin-top:2px">{t("学完率","Digested rate")}</div>
<div style="font-size:12.5px;color:var(--muted);margin-top:3px">{t("而不是弹出次数。重新同步永远不覆盖你的标记。","not popup count. Re-syncs never overwrite your marks.")}</div>
</div></div>''')
    # frame + labels
    frame=f'''<div class="abs" style="left:22px;top:84px;width:{W-44}px;height:{ph+84}px;border:1.5px dashed var(--line);border-radius:22px"></div>
<div class="abs tag" style="left:44px;top:74px;background:var(--bg);padding:0 10px;color:var(--muted)">{t("浏览器扩展 · 默认路径 · 零配置 · 无需 API key","Browser extension · default path · zero config · no API key")}</div>'''
    header=f'''<div class="abs" style="left:40px;top:26px;display:flex;align-items:center;gap:10px">{mark(22)}<span class="tag" style="color:var(--ink)">ChekhovsGun</span><span class="tag" style="color:var(--faint)">/ {t("系统总览","system overview")}</span></div>
<div class="abs" style="right:40px;top:26px;display:flex;gap:18px;align-items:center;font-size:12.5px;color:var(--muted)">
<span style="display:flex;align-items:center;gap:6px"><svg width="28" height="8"><path d="M0 4h28" style="stroke:var(--muted);stroke-width:1.6"></path></svg>{t("浏览器内","in-browser")}</span>
<span style="display:flex;align-items:center;gap:6px"><svg width="28" height="8"><path d="M0 4h28" style="stroke:var(--muted);stroke-width:1.6;stroke-dasharray:4 3"></path></svg>{t("可选后端","optional backend")}</span>
<span style="display:flex;align-items:center;gap:6px"><svg width="28" height="8"><path d="M0 4h28" style="stroke:var(--d5);stroke-width:1.6"></path></svg>{t("反馈回路","feedback loop")}</span></div>'''
    # backend band
    by,bh=694,96
    bw=xs[2]+cw-xs[0]
    band=f'''<div class="abs" style="left:{xs[0]}px;top:{by}px;width:{bw}px;height:{bh}px;border:1.5px dashed var(--faint);border-radius:16px;padding:12px 14px;display:flex;gap:14px;align-items:center">
<div style="width:150px;flex:none"><div class="tag" style="color:var(--ink)">{t("可选 Python 后端","Optional Python backend")}</div><div class="mono" style="font-size:11.5px;color:var(--muted);margin-top:4px">FastAPI · SQLite<br>127.0.0.1 only</div></div>
<div class="blk" style="flex:1"><b>{t("批量同步","Bulk sync")}</b><span>{t("YouTube / B 站收藏夹 + 字幕 + 热评","YouTube / Bilibili + captions + comments")}</span></div>
<div class="blk" style="flex:1"><b>{t("Whisper 本地转写","Local Whisper")}</b><span>{t("≤45 分钟/条 · 每次同步 ≤30 分钟","≤45 min/video · ≤30 min per sync")}</span></div>
<div class="blk" style="flex:1"><b>{t("正文补全","Hydrate links")}</b><span>{t("抓取扫描得到的链接","fetch scanned links")}</span></div>
</div>'''
    note=f'''<div class="abs cap" style="left:{xs[3]}px;top:{by+4}px;width:{W-xs[3]-40}px">
<b>{t("两边独立检索，只在结果层相遇。","Two engines, one result list.")}</b>
{t("后端没开、慢或挂了，只是少贡献一些结果；两边永远不需要共用同一个向量空间。","If the backend is off, slow or down, it just contributes fewer results — the two never have to share a vector space.")}</div>'''
    # arrows overlay
    my=py+ph/2
    ar=[]
    for i in range(4):
        a=xs[i]+cw+3; b=xs[i+1]-3
        ar.append(f'<path d="M{a} {my} L{b} {my}" style="stroke:var(--muted);stroke-width:1.8;fill:none" marker-end="url(#ah)"></path>')
    # feedback loop: from 5 bottom to 4 bottom
    fy=py+ph
    x5=xs[4]+cw/2; x4=xs[3]+cw/2
    ar.append(f'<path d="M{x5} {fy+2} C{x5} {fy+40} {x4} {fy+40} {x4} {fy+6}" style="stroke:var(--d5);stroke-width:1.8;fill:none" marker-end="url(#ahD)"></path>')
    fb=f'<div class="abs mono" style="left:{(x4+x5)/2-110}px;top:{fy+34}px;width:220px;text-align:center;font-size:11.5px;color:var(--d5);background:var(--bg)">{t("已学完 / 已静音 → 不再打扰","digested / muted → stays quiet")}</div>'
    # backend merge arrow into retrieve
    x3=xs[2]+cw/2
    ar.append(f'<path d="M{x3} {by-2} L{x3} {fy+4}" style="stroke:var(--muted);stroke-width:1.8;fill:none;stroke-dasharray:5 4" marker-end="url(#ah)"></path>')
    x1=xs[0]+cw/2
    ar.append(f'<path d="M{x1+40} {fy+4} L{x1+40} {by-2}" style="stroke:var(--muted);stroke-width:1.8;fill:none;stroke-dasharray:5 4" marker-end="url(#ah)"></path>')
    mg=f'<div class="abs mono" style="left:{x3+10}px;top:{fy+46}px;font-size:11.5px;color:var(--muted);background:var(--bg);padding:0 4px">{t("结果层 RRF · 按条目 ID / URL 去重","result-level RRF · dedup by id / URL")}</div>'
    sy=f'<div class="abs mono" style="left:{x1+50}px;top:{fy+46}px;font-size:11.5px;color:var(--muted);background:var(--bg);padding:0 4px">{t("已收藏条目","your saves")}</div>'
    svg=f'<svg class="ov" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{svg_defs()}{"".join(ar)}</svg>'
    cap=f'''<div class="abs cap" style="left:40px;top:{H-38}px;width:{W-80}px"><b>{t("图 1","Figure 1")}.</b> {t("一次收藏的完整旅程：采集 → 本地索引 → 混合检索与置信度门控 → 在对的时刻提醒 → 以「学完」收口。* Whisper 由可选后端提供。","The life of one save: capture → local index → gated hybrid retrieval → a cue at the right moment → closed by “digested”. *Whisper comes from the optional backend.")}</div>'''
    return W,H, header+frame+"".join(p)+band+note+svg+fb+mg+sy+cap

# ---------------------------------------------------------------- RETRIEVAL
def retrieval(lang):
    W,H=1280,700
    t=lambda z,e: L(lang,z,e)
    o=[]
    o.append(f'''<div class="abs" style="left:40px;top:26px;display:flex;align-items:center;gap:10px">{mark(22)}<span class="tag" style="color:var(--ink)">ChekhovsGun</span><span class="tag" style="color:var(--faint)">/ {t("检索：排序与门控是两件事","retrieval: ranking ≠ gating")}</span></div>''')
    # input column
    o.append(f'''<div class="abs" style="left:40px;top:92px;width:236px;display:flex;flex-direction:column;gap:10px">
<div class="lbl">{t("输入 · 标题+作者+标签+简介","input · title+author+tags+desc")}</div>
<div class="blk" style="padding:12px"><div class="mono" style="font-size:10.5px;color:var(--faint)">youtube.com/watch?v=…</div><div style="font-weight:600;font-size:15px;line-height:1.35;margin-top:6px">Why is my retrieval so bad? Chunking and hybrid search explained</div><div class="mono" style="font-size:11px;color:var(--faint);margin-top:6px">+ author · tags · desc[:600]</div></div>
{DOWN.replace('class="dn"','class="dn" style="color:var(--muted)"')}
<div class="lbl">{t("分词 · 拉丁词 + CJK 一/二元组","tokens · Latin + CJK uni/bigrams")}</div>
<div style="display:flex;flex-wrap:wrap;gap:6px">
<span class="chip mono" style="font-size:12px">retrieval</span><span class="chip mono" style="font-size:12px">chunking</span><span class="chip mono" style="font-size:12px">hybrid</span><span class="chip mono" style="font-size:12px">search</span>
<span class="chip dash mono" style="font-size:12px;text-decoration:line-through">why</span><span class="chip dash mono" style="font-size:12px;text-decoration:line-through">bad</span><span class="chip dash mono" style="font-size:12px;text-decoration:line-through">explained</span></div>
<div style="font-size:12.5px;color:var(--muted);line-height:1.45">{t("虚线词在你的收藏里从未出现，<b style='color:var(--ink)'>不计入覆盖率分母</b>，不会稀释真正的证据。","Dashed words never occur in your library, so they are <b style='color:var(--ink)'>left out of the coverage denominator</b> instead of diluting real evidence.")}</div>
</div>''')
    # ranking lane
    lx,lw=320,610
    o.append(f'''<div class="panel s3" style="left:{lx}px;top:84px;width:{lw}px;height:262px;padding:16px 18px">
<div style="display:flex;justify-content:space-between;align-items:baseline"><div class="pt">{t("排序","Ranking")}<span class="pe" style="margin-left:10px">{t("决定先后","who goes first")}</span></div></div>
<div style="display:flex;gap:14px;align-items:stretch;margin-top:6px">
<div style="display:flex;flex-direction:column;gap:8px;width:150px">
 <div class="blk"><b>BM25</b><div class="mono" style="font-size:12px;color:var(--muted);margin-top:4px;line-height:1.6">#1 A<br>#2 C<br>#3 B</div></div>
 <div class="blk"><b>Dense</b><div class="mono" style="font-size:12px;color:var(--muted);margin-top:4px;line-height:1.6">#1 A<br>#2 B<br>#3 D</div></div>
</div>
<div style="flex:1;display:flex;flex-direction:column;gap:8px">
 <div class="blk" style="flex:1;display:flex;flex-direction:column;justify-content:center"><b>{t("RRF 融合","RRF fusion")}</b>
 <div class="serif" style="font-size:19px;margin-top:6px;font-style:italic;white-space:nowrap">RRF(d) = 0.6 ⁄ (60 + r<sub style="font-size:11px">dense</sub>) + 0.4 ⁄ (60 + r<sub style="font-size:11px">bm25</sub>)</div>
 <span>{t("只看排名，不看分数 —— 两条量纲完全不同的分数无需校准，也不会被一个离群值带偏。","Ranks only — two incomparable score scales never need calibrating, and one outlier can't drag the list.")}</span></div>
 <div class="blk"><b>{t("每条收藏最多 4 段 → 按收藏聚合","≤ 4 chunks per save → aggregate per save")}</b><span>{t("score = 最佳段 + 0.25 × 其后 3 段。不用 MMR：它会删掉命中最好的那一段。","score = best + 0.25 × next 3. Not MMR: it deleted the best passage.")}</span></div>
</div></div></div>''')
    # gating lane
    gy=378
    o.append(f'''<div class="panel s4" style="left:{lx}px;top:{gy}px;width:{lw}px;height:236px;padding:16px 18px">
<div class="pt">{t("门控","Gating")}<span class="pe" style="margin-left:10px">{t("决定要不要开口","speak up at all?")}</span></div>
<div style="display:flex;gap:10px;align-items:center;margin-top:6px">
 <div class="blk" style="flex:1.45"><b>{t("IDF 加权覆盖率 cov","IDF-weighted coverage cov")}</b>
 <span>· {t("按书写系统分开算，跨语言不吃亏","per writing system: cross-language isn't penalised")}</span>
 <span>· {t("× m/(m+0.8) 饱和：单词命中 ≤ 56%","× m/(m+0.8): one matched word ≤ 56%")}</span></div>
 <div class="serif" style="font-size:26px;color:var(--d4)">+</div>
 <div class="blk" style="flex:.75"><b>{t("向量余弦","Vector cosine")}</b><span>cos(q, chunk)</span></div>
 <div class="serif" style="font-size:26px;color:var(--d4)">→</div>
 <div class="blk hl" style="flex:.6;text-align:center"><b style="font-size:20px" class="serif">conf</b><span class="mono">∈ [0, 1]</span></div>
</div>
<div class="serif" style="font-size:16.5px;font-style:italic;margin-top:12px;white-space:nowrap">conf = 0.55·(0.45·cos + 0.55·cov) + 0.45·√(cos·cov)</div>
<div style="font-size:12.5px;color:var(--muted);margin-top:6px;line-height:1.45">{t("几何项要求两路信号都不为零；块还没有向量时退化为 0.85·cov。RRF 分数随语料漂移，给不出绝对阈值，所以由它来回答「值不值得打扰你」。","The geometric term needs both signals; a chunk without a vector falls back to 0.85·cov. RRF scores drift with corpus size, so this — not RRF — decides whether to interrupt.")}</div>
</div>''')
    # merge + decision
    mx=968
    o.append(f'''<div class="abs" style="left:{mx}px;top:84px;width:272px;display:flex;flex-direction:column;gap:12px">
<div class="lbl">{t("合流","merge")}</div>
<div class="blk" style="padding:14px"><div class="serif" style="font-size:17px;font-style:italic;line-height:1.35;white-space:nowrap">final = score × (0.2 + 0.8 · conf)</div><span>{t("低置信度的结果不会消失，只是被压到后面。","Low-confidence hits sink rather than vanish.")}</span></div>
</div>''')
    o.append(f'''<div class="abs" style="left:{mx}px;top:262px;width:272px;height:150px">
<svg width="272" height="150" viewBox="0 0 272 150"><path d="M136 4 L266 75 L136 146 L6 75 Z" style="fill:var(--card);stroke:var(--ink);stroke-width:1.5"></path></svg>
<div class="abs" style="left:46px;top:40px;width:180px;text-align:center;font-size:13px;line-height:1.45"><b>conf ≥ 0.30</b><br>score ⁄ top ≥ 0.45<br>{t("收藏 ≥ 15 条 ?","library ≥ 15 ?")}</div></div>''')
    o.append(f'''<div class="abs s4" style="left:{mx}px;top:452px;width:128px;height:118px;border-radius:12px;background:var(--accent);color:var(--accent-ink);padding:12px;display:flex;flex-direction:column;justify-content:space-between">
<div class="tag" style="font-size:10px;opacity:.85">{t("是","yes")}</div><div><div class="serif" style="font-size:20px;font-weight:600;line-height:1.1">{t("开火","Fire")}</div><div style="font-size:12px;margin-top:3px;opacity:.9">{t("弹卡片 · 跳到 16:40","card · jump to 16:40")}</div></div></div>
<div class="abs" style="left:{mx+144}px;top:452px;width:128px;height:118px;border-radius:12px;border:1.5px solid var(--line);background:var(--card);padding:12px;display:flex;flex-direction:column;justify-content:space-between">
<div class="tag" style="font-size:10px;color:var(--muted)">{t("否","no")}</div><div><div class="serif" style="font-size:20px;font-weight:600;line-height:1.1">{t("保持安静","Stay quiet")}</div><div style="font-size:12px;margin-top:3px;color:var(--muted)">{t("主动搜索仍可用","search still works")}</div></div></div>''')
    o.append(f'''<div class="abs" style="left:{mx}px;top:586px;width:272px;font-size:12.5px;color:var(--muted);line-height:1.45">
<div class="lbl" style="margin-bottom:4px">{t("为什么是 15 条","why 15")}</div>
{t("固定一组不相关页面扫不同库大小：≤ 12 条时误弹 <b style='color:var(--ink)'>2/6</b>，≥ 15 条起 <b style='color:var(--ink)'>0/6</b>，真命中每档照常命中。","Same unrelated pages across library sizes: <b style='color:var(--ink)'>2/6</b> false fires up to 12 saves, <b style='color:var(--ink)'>0/6</b> from 15 on — every true hit still fires.")}</div>''')
    # arrows
    ar=[]
    ar.append(f'<path d="M280 190 C300 190 300 215 {lx-4} 215" style="stroke:var(--d3);stroke-width:1.8;fill:none" marker-end="url(#ahB)"></path>')
    ar.append(f'<path d="M280 190 C300 190 300 496 {lx-4} 496" style="stroke:var(--d4);stroke-width:1.8;fill:none" marker-end="url(#ahA)"></path>')
    ar.append(f'<path d="M{lx+lw+3} 215 C{mx-14} 215 {mx-14} 160 {mx-4} 160" style="stroke:var(--d3);stroke-width:1.8;fill:none" marker-end="url(#ahB)"></path>')
    ar.append(f'<path d="M{lx+lw+3} 496 C{mx-20} 496 {mx-20} 170 {mx-4} 170" style="stroke:var(--accent);stroke-width:1.8;fill:none" marker-end="url(#ahA)"></path>')
    ar.append(f'<path d="M{mx+136} 222 L{mx+136} 258" style="stroke:var(--muted);stroke-width:1.8;fill:none" marker-end="url(#ah)"></path>')
    ar.append(f'<path d="M{mx+56} 366 L{mx+56} 448" style="stroke:var(--accent);stroke-width:1.8;fill:none" marker-end="url(#ahA)"></path>')
    ar.append(f'<path d="M{mx+216} 366 L{mx+216} 448" style="stroke:var(--muted);stroke-width:1.8;fill:none" marker-end="url(#ah)"></path>')
    o.append(f'<svg class="ov" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{svg_defs()}{"".join(ar)}</svg>')
    o.append(f'''<div class="abs cap" style="left:40px;top:{H-40}px;width:880px"><b>{t("图 2","Figure 2")}.</b> {t("排序与门控分离。RRF 只负责先后；一个独立的置信度决定是否打扰你，最终排序再用它做软加权。","Ranking ≠ gating. RRF only orders results; an independent confidence decides whether to interrupt at all.")}</div>''')
    return W,H,"".join(o)

# ---------------------------------------------------------------- STATS
def stats(lang):
    W,H=1280,310
    t=lambda z,e: L(lang,z,e)
    tiles=[("6.1","ms",t("检索 p50","query p50"),t("p95 8.0 ms","p95 8.0 ms"),"s4"),
           ("62→6.1","ms",t("BM25 向量化","BM25 vectorised"),t("numpy + 跳过 DF>35% 的词","numpy + skip DF > 35% tokens"),"s3"),
           ("1.5","s",t("冷启动","cold start"),t("原 6.1 s · 分词持久化","was 6.1 s · persisted tokens"),"s2"),
           ("32","MB",t("常驻内存","resident memory"),t("磁盘 65 MB","65 MB on disk"),"s1"),
           ("0","",t("API key · 服务端","API keys · servers"),t("装一个扩展即可完整使用","one extension is the whole product"),"s5")]
    tw=(W-80-4*16)/5
    o=[f'''<div class="abs" style="left:40px;top:28px;display:flex;align-items:center;gap:10px">{mark(22)}<span class="tag" style="color:var(--ink)">ChekhovsGun</span><span class="tag" style="color:var(--faint)">/ {t("性能 · Python 引擎实测","performance · measured on the Python engine")}</span></div>''']
    for i,(big,unit,lab,sub,s) in enumerate(tiles):
        x=40+i*(tw+16)
        o.append(f'''<div class="abs {s}" style="left:{x}px;top:78px;width:{tw}px;height:160px;border-radius:16px;background:var(--t);border:1px solid var(--k);padding:18px 18px 16px;display:flex;flex-direction:column">
<div class="lbl" style="color:var(--d)">{lab}</div>
<div style="margin-top:auto;display:flex;align-items:baseline;gap:6px"><span class="serif" style="font-size:{50 if len(big)<5 else 40}px;font-weight:600;line-height:1;letter-spacing:-.02em">{big}</span><span class="mono" style="font-size:16px;color:var(--d)">{unit}</span></div>
<div style="font-size:12.5px;color:var(--muted);margin-top:10px;line-height:1.4">{sub}</div></div>''')
    o.append(f'''<div class="abs mono" style="left:40px;top:{H-46}px;font-size:12px;color:var(--muted)">$ python scripts/benchmark.py &nbsp;·&nbsp; {t("合成库 2,000 条收藏 / 15,555 个片段","synthetic library · 2,000 saves / 15,555 chunks")}</div>''')
    return W,H,"".join(o)

# ---------------------------------------------------------------- LIFECYCLE
def lifecycle(lang):
    W,H=1280,420
    t=lambda z,e: L(lang,z,e)
    o=[f'''<div class="abs" style="left:40px;top:28px;display:flex;align-items:center;gap:10px">{mark(22)}<span class="tag" style="color:var(--ink)">ChekhovsGun</span><span class="tag" style="color:var(--faint)">/ {t("收藏的一生","the life of a save")}</span></div>''']
    def node(x,y,w,h,s,title,sub,badges,strong=False):
        bd="".join(f'<span class="chip" style="font-size:11.5px;padding:2px 8px;border-color:var(--k)">{b}</span>' for b in badges)
        return f'''<div class="abs {s}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;border-radius:16px;background:var(--t);border:{'2px' if strong else '1px'} solid {'var(--d)' if strong else 'var(--k)'};padding:16px 18px;display:flex;flex-direction:column;gap:6px">
<div class="serif" style="font-size:24px;font-weight:600;line-height:1.1">{title}</div><div style="font-size:13px;color:var(--muted);line-height:1.4">{sub}</div><div style="margin-top:auto;display:flex;gap:6px;flex-wrap:wrap">{bd}</div></div>'''
    # save event
    o.append(f'''<div class="abs" style="left:40px;top:150px;width:170px;height:120px;border-radius:16px;border:1.5px dashed var(--line);padding:16px;display:flex;flex-direction:column;gap:8px;align-items:flex-start">
{mark(30)}<div style="font-weight:600;font-size:14.5px">{t("你点了收藏","You hit save")}</div><div style="font-size:12.5px;color:var(--muted)">{t("第一幕，枪挂上墙","Act I: the gun is on the wall")}</div></div>''')
    o.append(node(290,110,300,200,"s1",t("还欠着","Active"),t("默认状态。刷到相关内容时它会开口。","The default. It speaks up when you scroll onto something related."),[t("会弹","fires"),t("可搜索","searchable")]))
    o.append(node(700,70,300,130,"s2",t("已学完","Digested"),t("你回去看完了，学到了。","You went back and actually learned it."),[t("不再弹","quiet"),t("计入学完率","counts toward the rate")],True))
    o.append(node(700,230,300,130,"s5",t("已静音","Muted"),t("别再拿这个烦我。只停打扰，不停检索。","Stop nudging me. Silences popups, not search."),[t("不再弹","quiet"),t("仍可搜索","searchable")]))
    o.append(f'''<div class="abs" style="left:1050px;top:78px;width:190px">
<div class="lbl">{t("唯一的成功指标","the one metric")}</div>
<div class="serif" style="font-size:34px;font-weight:600;line-height:1.1;margin-top:6px">{t("学完率","Digested rate")}</div>
<div style="font-size:13px;color:var(--muted);margin-top:8px;line-height:1.5">{t("而不是弹出次数。这个数字，才是这个项目想改变的东西。","Not popup count. This number is what the project exists to change.")}</div></div>''')
    o.append(f'''<div class="abs" style="left:1050px;top:262px;width:190px;font-size:12.5px;color:var(--muted);line-height:1.5">
<div class="lbl" style="margin-bottom:4px">{t("每晚重新同步","nightly re-sync")}</div>
<span class="mono" style="color:var(--ink)">upsert</span> {t("刻意不碰","never touches")} <span class="mono" style="color:var(--ink)">status · user_tags · note</span>{t("：学完的东西不会被翻出来。","— what you finished stays finished.")}</div>''')
    ar=[f'<path d="M212 210 L286 210" style="stroke:var(--muted);stroke-width:1.8;fill:none" marker-end="url(#ah)"></path>',
        f'<path d="M592 180 C650 180 640 135 696 135" style="stroke:var(--d2);stroke-width:1.8;fill:none" marker-end="url(#ah)"></path>',
        f'<path d="M592 240 C650 240 640 295 696 295" style="stroke:var(--d5);stroke-width:1.8;fill:none" marker-end="url(#ahD)"></path>',
        f'<path d="M1002 135 L1040 135" style="stroke:var(--d2);stroke-width:1.8;fill:none;stroke-dasharray:4 3" marker-end="url(#ah)"></path>']
    o.append(f'<div class="abs mono" style="left:612px;top:112px;font-size:11.5px;color:var(--d2)">✓ {t("学完了","digested")}</div>')
    o.append(f'<div class="abs mono" style="left:600px;top:268px;font-size:11.5px;color:var(--d5)">{t("静音","mute")}</div>')
    o.append(f'<svg class="ov" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{svg_defs()}{"".join(ar)}</svg>')
    o.append(f'''<div class="abs cap" style="left:40px;top:{H-44}px;width:{W-80}px"><b>{t("图 3","Figure 3")}.</b> {t("三个状态回答「弹出来之后呢」。静音只停止打扰，主动搜索时它照样出现。","Three states answer “and after the popup?”. Muting stops the nudges; the save still shows up when you search.")}</div>''')
    return W,H,"".join(o)

# ---------------------------------------------------------------- HERO
def hero(lang):
    W,H=1280,620
    t=lambda z,e: L(lang,z,e)
    o=[]
    o.append('<div class="abs" style="inset:0;background:radial-gradient(ellipse 640px 460px at 76% 42%,rgba(240,113,82,.17),rgba(240,113,82,0) 70%)"></div>')
    o.append(f'''<div class="abs" style="left:72px;top:56px;display:flex;align-items:center;gap:12px">{mark(34)}<span class="serif" style="font-size:24px;font-weight:600;letter-spacing:-.01em">ChekhovsGun</span><span style="font-size:15px;color:var(--muted);font-family:var(--serif)">{t("契诃夫的枪","契诃夫的枪")}</span></div>''')
    title = t('你只需要<span style="color:var(--accent)">收藏</span>。','Just <span style="color:var(--accent);font-style:italic">save</span> it.')
    sub2 = t("剩下的，交给第三幕。","It goes off in Act III.")
    o.append(f'''<div class="abs" style="left:72px;top:150px;width:560px">
<div class="tag" style="color:var(--accent);font-size:12px">{t("第一幕挂上墙的枪 · 第三幕必须开火","a gun on the wall in act i must fire in act iii")}</div>
<div class="serif" style="font-size:{72 if lang=='zh' else 80}px;font-weight:{700 if lang=='zh' else 600};line-height:1.05;margin-top:18px;letter-spacing:-.02em">{title}</div>
<div class="serif" style="font-size:{34 if lang=='zh' else 36}px;font-weight:400;color:var(--muted);margin-top:10px;line-height:1.2">{sub2}</div>
<div style="font-size:17px;line-height:1.6;color:var(--muted);margin-top:26px;width:500px">{t("当你刷到相关内容，你收藏过的那一条会自己跳出来——视频直接跳到讲这件事的那一秒，帖子高亮讲这件事的那一段。","When you scroll onto something related, the thing you saved speaks up — jumping to the exact second of the video, or highlighting the exact passage of the post.")}</div>
<div style="display:flex;gap:8px;margin-top:28px;flex-wrap:wrap">
<span class="chip mono" style="font-size:12px;background:transparent;border-color:#3A3D45">{t("100% 本地","100% local")}</span>
<span class="chip mono" style="font-size:12px;background:transparent;border-color:#3A3D45">{t("零 API key","zero API keys")}</span>
<span class="chip mono" style="font-size:12px;background:transparent;border-color:#3A3D45">{t("中英混合检索","zh / en hybrid search")}</span>
<span class="chip mono" style="font-size:12px;background:transparent;border-color:#3A3D45">{t("13 个站点内置","13 built-in sites")}</span></div></div>''')
    # browser mock
    bx,by,bw,bh=680,70,540,392
    o.append(f'''<div class="abs" style="left:{bx}px;top:{by}px;width:{bw}px;height:{bh}px;border-radius:14px;background:#1A1C21;border:1px solid #2C2F36;box-shadow:0 40px 80px -30px rgba(0,0,0,.9);overflow:hidden">
<div style="height:38px;display:flex;align-items:center;gap:7px;padding:0 14px;border-bottom:1px solid #2C2F36">
<span style="width:10px;height:10px;border-radius:50%;background:#3A3D45"></span><span style="width:10px;height:10px;border-radius:50%;background:#3A3D45"></span><span style="width:10px;height:10px;border-radius:50%;background:#3A3D45"></span>
<span class="mono" style="margin-left:14px;flex:1;height:22px;border-radius:6px;background:#23262C;color:#7E7A72;font-size:11px;display:flex;align-items:center;padding:0 10px">youtube.com/watch?v=…</span></div>
<div style="padding:16px">
<div style="height:218px;border-radius:10px;background:linear-gradient(135deg,#23262E,#1B1D22);position:relative;overflow:hidden">
<div class="abs" style="left:22px;top:22px;right:22px"><div class="mono" style="font-size:11px;color:#8C877E;letter-spacing:.1em">{t("你正在看","NOW WATCHING")}</div><div style="font-size:23px;font-weight:600;color:#ECE7DD;line-height:1.25;margin-top:8px">Why is my retrieval so bad?<br><span style="color:#A19C91;font-weight:400">Chunking &amp; hybrid search, explained</span></div></div>
<div class="abs" style="left:22px;right:22px;bottom:18px;height:4px;border-radius:2px;background:#33363D"><div style="width:38%;height:4px;border-radius:2px;background:#ECE7DD"></div></div>
<div class="abs" style="left:calc(22px + 38% - 7px);bottom:13px;width:14px;height:14px;border-radius:50%;background:#ECE7DD"></div>
</div>
<div style="margin-top:14px;height:12px;width:70%;border-radius:6px;background:#2A2D34"></div>
<div style="margin-top:9px;height:10px;width:42%;border-radius:5px;background:#24272D"></div>
<div style="margin-top:16px;display:flex;gap:10px"><div style="width:30px;height:30px;border-radius:50%;background:#2A2D34"></div><div style="flex:1"><div style="height:9px;width:55%;border-radius:5px;background:#2A2D34"></div><div style="height:8px;width:35%;border-radius:5px;background:#24272D;margin-top:7px"></div></div></div>
</div></div>''')
    # popup card
    cx,cy,cwid=900,262,340
    o.append(f'''<div class="abs" style="left:{cx}px;top:{cy}px;width:{cwid}px;border-radius:14px;background:#F6F3EC;color:#1C1B18;box-shadow:0 30px 60px -20px rgba(0,0,0,.85),0 0 0 1px rgba(240,113,82,.5);overflow:hidden">
<div style="display:flex;align-items:center;gap:8px;padding:11px 16px;border-bottom:1px solid #E4DED2">{mark(18,"#C8452A","#C8452A")}<span style="font-size:14px;font-weight:600">你收藏过相关的</span><span class="mono" style="font-size:11px;color:#fff;background:#C8452A;border-radius:999px;padding:1px 7px">1</span><span style="margin-left:auto;color:#A39D90;font-size:16px">×</span></div>
<div style="padding:12px 16px 14px">
<div style="font-size:17px;font-weight:600;line-height:1.3;color:#B23E22">How Vector Databases Actually Work</div>
<div style="font-size:12.5px;color:#6A655B;margin-top:3px">YouTube · Engineering Deep Dives · Watch Later</div>
<div style="margin-top:10px;padding:10px 12px;border-radius:9px;background:#EFE9DD;font-size:13px;line-height:1.5;color:#3A372F"><span class="mono" style="color:#B23E22;font-weight:500">16:40</span>&nbsp; The real failure mode of pure vector search is <b style="background:#F7D9CD;font-weight:600">exact terminology</b>…</div>
<div style="display:flex;align-items:center;gap:10px;margin-top:12px"><span style="border-radius:8px;border:1px solid #DDD6C8;font-size:13px;padding:6px 12px;background:#fff">✓ 学完了</span><span class="mono" style="font-size:11px;color:#8A857B">{t("点标题 → 跳到 16:40","click title → 16:40")}</span></div>
</div>
<div style="display:flex;align-items:center;padding:8px 16px;border-top:1px solid #E4DED2;font-size:12px;color:#8A857B">这条不用再提醒<span style="margin-left:auto"><svg width="15" height="15" viewBox="0 0 24 24"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9A2 2 0 0 0 4.3 15H10zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3" style="fill:none;stroke:#8A857B;stroke-width:1.8;stroke-linejoin:round"></path></svg></span></div>
</div>''')
    # spark near card
    o.append(f'''<svg class="ov" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><g style="stroke:var(--accent);stroke-width:2.2;stroke-linecap:round;fill:none"><path d="M{cx-14} {cy+18} l-14 -8"></path><path d="M{cx-16} {cy+36} l-18 0"></path><path d="M{cx-14} {cy+54} l-14 8"></path></g></svg>''')
    # act timeline
    ty=548
    o.append(f'''<svg class="ov" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<path d="M84 {ty} L1196 {ty}" style="stroke:#2C2F36;stroke-width:1.5"></path>
<path d="M84 {ty} L1196 {ty}" style="stroke:var(--accent);stroke-width:1.5;stroke-dasharray:2 7;opacity:.7"></path>
<circle cx="84" cy="{ty}" r="6" style="fill:var(--bg);stroke:var(--muted);stroke-width:1.8"></circle>
<circle cx="640" cy="{ty}" r="3" style="fill:#3A3D45"></circle>
<circle cx="1196" cy="{ty}" r="7" style="fill:var(--accent)"></circle><circle cx="1196" cy="{ty}" r="13" style="fill:none;stroke:var(--accent);stroke-width:1.2;opacity:.5"></circle>
</svg>
<div class="abs" style="left:72px;top:{ty+16}px"><div class="tag" style="color:var(--muted);font-size:10.5px">{t("第一幕","act i")}</div><div style="font-size:14px;margin-top:3px">{t("你点了收藏，然后忘了它","You hit save — and forgot")}</div></div>
<div class="abs" style="left:540px;top:{ty+16}px;width:200px;text-align:center"><div class="tag" style="color:var(--faint);font-size:10.5px">{t("第二幕","act ii")}</div><div style="font-size:14px;margin-top:3px;color:var(--muted)">{t("它在本地安静地建好索引","It indexes quietly, locally")}</div></div>
<div class="abs" style="right:72px;top:{ty+16}px;text-align:right"><div class="tag" style="color:var(--accent);font-size:10.5px">{t("第三幕","act iii")}</div><div style="font-size:14px;margin-top:3px">{t("在你需要的那一刻，开火","The moment it matters, it fires")}</div></div>''')
    return W,H,"".join(o)

FIGS={"hero":hero,"pipeline":pipeline,"retrieval":retrieval,"lifecycle":lifecycle,"stats":stats}
