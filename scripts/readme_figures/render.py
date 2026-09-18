"""Render the README figures in docs/assets/v2 (zh/en x light/dark).

Usage: pip install playwright && playwright install chromium
       python scripts/readme_figures/render.py [hero pipeline retrieval lifecycle stats]
CJK text uses Noto Sans/Serif CJK SC if installed. Fonts: Fraunces, IBM Plex Sans, JetBrains Mono (SIL OFL).
"""
import sys,os,asyncio,tempfile
from pathlib import Path
sys.path.insert(0,os.path.dirname(__file__))
from style import CSS,fontface,FONTS
from figs import FIGS
from playwright.async_api import async_playwright
D=os.path.dirname(os.path.abspath(__file__))
urlmap={f:Path(D,"fonts",f).as_uri() for *_,f in FONTS}
def page(name,lang,theme):
    W,H,body=FIGS[name](lang)
    return W,H,f'<!doctype html><html lang="{"zh-CN" if lang=="zh" else "en"}"><head><meta charset="utf-8"><style>{fontface(urlmap)}{CSS}</style></head><body><div id="fig" class="fig {theme}" style="width:{W}px;height:{H}px">{body}</div></body></html>'
async def main(only=None):
    out=os.path.join(D,"..","..","docs","assets","v2"); os.makedirs(out,exist_ok=True); tmp=tempfile.mkdtemp()
    jobs=[]
    for n in FIGS:
        if only and n not in only: continue
        for lang in ("zh","en"):
            themes=["dark"] if n=="hero" else ["light","dark"]
            for th in themes: jobs.append((n,lang,th))
    async with async_playwright() as p:
        b=await p.chromium.launch()
        pg=await b.new_page(device_scale_factor=2,viewport={"width":1400,"height":900})
        for n,lang,th in jobs:
            W,H,html=page(n,lang,th)
            fn=os.path.join(tmp,f"_{n}.html"); open(fn,"w",encoding="utf-8").write(html)
            await pg.goto(Path(fn).as_uri()); await pg.evaluate("document.fonts.ready")
            await pg.wait_for_timeout(150)
            name=f"{n}-{lang}.png" if n=="hero" else f"{n}-{lang}-{th}.png"
            await pg.locator("#fig").screenshot(path=os.path.join(out,name))
            print(name)
        await b.close()
asyncio.run(main(sys.argv[1:] or None))
