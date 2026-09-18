#!/usr/bin/env python3
"""把作品用到的場景圖抓下來、縮小成 WebP 放進 img/。

原圖一張約 2.2 MB、52 張合計超過 100 MB，直接連作者的圖床會把讀者的流量與
對方的主機一起拖垮，所以本站放的是縮到寬 1000 的副本，原圖網址記在 img/sources.json。
"""
import json, os, hashlib, urllib.request, io
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(HERE, "img")
MAXW = 1000

def collect():
    d = json.load(open(os.path.join(HERE, "data", "story.json")))
    urls = [d["meta"]["cover"]]
    def walk(seq):
        for it in seq:
            if it.get("bg"):
                urls.append(it["bg"])
            if (it.get("item") or {}).get("image"):
                urls.append(it["item"]["image"])
    for s in d["segments"]:
        walk(s["body"])
    for e in d["endings"]:
        if e.get("image"):
            urls.append(e["image"])
    return list(dict.fromkeys(u for u in urls if u and u.startswith("http")))

def main():
    os.makedirs(IMG, exist_ok=True)
    mapping = {}
    for i, u in enumerate(collect(), 1):
        name = hashlib.sha1(u.encode()).hexdigest()[:12] + ".webp"
        path = os.path.join(IMG, name)
        if os.path.exists(path):
            with Image.open(path) as ex:
                mapping[u] = {"src": "img/" + name, "w": ex.width, "h": ex.height}
            continue
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        try:
            raw = urllib.request.urlopen(req, timeout=120).read()
            im = Image.open(io.BytesIO(raw))
        except Exception as err:   # 少數網址不是圖（或已失效），留著原網址就好
            print("%3d 跳過 %s（%s）" % (i, u[-40:], err))
            mapping[u] = {"src": u, "w": 0, "h": 0}
            continue
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (0, 0, 0, 0))
            im = Image.alpha_composite(bg, im)
        if im.width > MAXW:
            im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
        im.save(path, "WEBP", quality=72, method=5)
        mapping[u] = {"src": "img/" + name, "w": im.width, "h": im.height}
        print("%3d %7d KB -> %5d KB  %s" % (i, len(raw) // 1024,
                                            os.path.getsize(path) // 1024, name))
    json.dump(mapping, open(os.path.join(IMG, "sources.json"), "w"),
              ensure_ascii=False, indent=1)
    print("共 %d 張，對照表寫進 img/sources.json" % len(mapping))

if __name__ == "__main__":
    main()
