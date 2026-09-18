#!/usr/bin/env python3
"""把 Larch 市集上的《第九號病人》抓下來，整理成網站要用的 data/story.json。

用法：
    python3 tools/build.py            # 線上抓一份再整理
    python3 tools/build.py raw.json   # 用已經抓下來的檔案
"""
import json, sys, os, urllib.request, collections

GAME_ID = "e1519bf9-dbc8-4830-9873-3ae50416d955"
API = "https://larch.ink/api/marketplace/%s?play=1" % GAME_ID
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 玩家點背包用道具的那幾張卡是自己連自己，真正的去向寫在發道具那張卡的 storyNodeId。
# 這裡靠卡片文字裡的道具名把兩邊接起來。
def fetch():
    if len(sys.argv) > 1:
        return json.load(open(sys.argv[1]))
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=180).read()
    open(os.path.join(HERE, "data", "raw.json"), "wb").write(raw)
    return json.loads(raw)


def lines_of(nd):
    dl = [l for l in (nd.get("dialogueLines") or []) if (l.get("text") or "").strip()]
    if dl:
        return [l["text"].strip() for l in dl]
    t = (nd.get("text") or "").strip()
    return [t] if t else []


def main():
    doc = fetch()
    proj = doc["project"]
    board = proj["boards"][0]
    nodes = {n["id"]: n for n in board["nodes"]}
    out = collections.defaultdict(list)
    for e in board["edges"]:
        out[e["source"]].append(e)

    # 道具名 -> 使用後前往的卡
    item_jump = {}
    for n in board["nodes"]:
        d = n["data"]
        if d.get("type") == "plugin" and d.get("pluginCardId") == "grant-item":
            v = d.get("pluginValues") or {}
            if v.get("storyNodeId"):
                item_jump[v.get("itemName", "").strip()] = v["storyNodeId"]

    def transitions(nid):
        """回傳 [(標籤, 目標)]；標籤是選項文字，沒有選項就是 None。"""
        d = nodes[nid]["data"]
        es = [e for e in out[nid] if e["target"] != nid]
        if not es:
            # 自己連自己的「點擊背包使用 X」卡，改走道具的去向
            txt = " ".join(lines_of(d)) + " " + (d.get("title") or "")
            for name, target in item_jump.items():
                if name and name in txt:
                    return [(None, target)]
            return []
        if d.get("type") != "choice":
            return [(None, es[0]["target"])]
        choices = d.get("choices") or []
        grouped = collections.OrderedDict()
        for e in es:
            h = e.get("sourceHandle") or ""
            if h.startswith("choice-") and h[7:].isdigit() and int(h[7:]) < len(choices):
                label = choices[int(h[7:])]
            else:
                label = None
            grouped.setdefault(e["target"], []).append(label)
        res = []
        for target, labels in grouped.items():
            named = [l for l in labels if l]
            res.append(("／".join(named) if named else None, target))
        return res

    def reach(nid):
        seen, stack = set(), [nid]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            for _, t in transitions(x):
                stack.append(t)
        return seen

    def dist(src, target):
        seen, q = {src}, collections.deque([(src, 0)])
        while q:
            x, k = q.popleft()
            if x == target:
                return k
            for _, t in transitions(x):
                if t not in seen:
                    seen.add(t)
                    q.append((t, k + 1))
        return -1

    def node_out(nid):
        d = nodes[nid]["data"]
        item = None
        if d.get("type") == "plugin":
            v = d.get("pluginValues") or {}
            item = {"name": v.get("itemName"), "image": v.get("itemImage"),
                    "keep": not v.get("consumable", True)}
        o = {"id": nid, "kind": d.get("type"), "lines": lines_of(nd_or(d))}
        if d.get("type") == "choice":
            o["choices"] = [c for c in (d.get("choices") or []) if str(c).strip()]
        if d.get("background"):
            o["bg"] = d["background"]
        if item:
            o["item"] = item
        return o

    def nd_or(d):
        return d

    # 一張卡只放進一個段落：主線先走，其他選項各自成一段，撞到已經寫過的卡就接回去。
    claimed = {}
    segments = []

    def claim_walk(start_id, seg_id):
        """沿著單線往下走，直到分歧、結局，或撞上別段已經寫過的卡。"""
        body, cur = [], start_id
        while True:
            if cur in claimed:
                return body, {"kind": "rejoin", "node": cur, "seg": claimed[cur]}
            claimed[cur] = seg_id
            body.append(node_out(cur))
            nxts = transitions(cur)
            if not nxts:
                return body, {"kind": "ending", "node": cur}
            if len(nxts) > 1:
                return body, {"kind": "branch", "node": cur, "options": nxts}
            cur = nxts[0][1]

    def make_segment(start_id, label, parent, depth):
        seg_id = "s%d" % len(segments)
        seg = {"id": seg_id, "label": label, "parent": parent, "depth": depth,
               "body": [], "branch": None, "end": None}
        segments.append(seg)
        body, stop = claim_walk(start_id, seg_id)
        seg["body"] = body
        pending = []
        while stop["kind"] == "branch":
            node = stop["node"]
            d = nodes[node]["data"]
            prompt = " ".join(lines_of(d)) or (d.get("title") or "")
            opts = stop["options"]
            main_idx = pick_main([t for _, t in opts])
            branch = {"node": node, "prompt": prompt, "options": []}
            for i, (lab, target) in enumerate(opts):
                branch["options"].append({"label": lab or "（繼續）", "main": i == main_idx,
                                          "target": target, "seg": None})
            seg["body"].append({"kind": "branch", "branch": branch})
            pending.append((branch, opts, main_idx, depth))
            more, stop = claim_walk(opts[main_idx][1], seg_id)
            seg["body"].extend(more)
        seg["end"] = stop
        for branch, opts, main_idx, dep in pending:
            for i, (lab, target) in enumerate(opts):
                if i == main_idx:
                    continue
                if target in claimed:
                    branch["options"][i]["seg"] = claimed[target]
                    branch["options"][i]["rejoin"] = True
                else:
                    branch["options"][i]["seg"] = make_segment(
                        target, lab or "（繼續）", seg["id"], dep + 1)
        return seg["id"]

    TE = [None]

    def pick_main(targets):
        best, best_key = 0, None
        for i, t in enumerate(targets):
            r = reach(t)
            key = (0 if (TE[0] and TE[0] in r) else 1, -len(r))
            if best_key is None or key < best_key:
                best, best_key = i, key
        return best

    start = next(n["id"] for n in board["nodes"] if n["data"].get("start"))
    reachable = reach(start)
    ends = [n["id"] for n in board["nodes"] if n["id"] in reachable and not transitions(n["id"])]
    # 真結局＝走得到的終點裡最深的那一個（孤兒院回憶那條）
    TE[0] = max(ends, key=lambda e: dist(start, e))
    make_segment(start, "主線", None, 0)

    def path_to(target):
        prev, q = {start: None}, collections.deque([start])
        while q:
            x = q.popleft()
            if x == target:
                break
            for lab, t in transitions(x):
                if t not in prev:
                    prev[t] = (x, lab)
                    q.append(t)
        if target not in prev:
            return []
        chain, cur = [], target
        while prev[cur]:
            src, lab = prev[cur]
            chain.append((src, lab, cur))
            cur = src
        chain.reverse()
        steps = []
        ctx = ""
        for src, lab, tgt in chain:
            ls = lines_of(nodes[src]["data"])
            if nodes[src]["data"].get("type") != "choice" and ls:
                ctx = ls[-1].replace("\n", " ").strip()
            opts = transitions(src)
            if nodes[src]["data"].get("type") != "choice" or len({t for _, t in opts}) < 2:
                continue
            prompt = " ".join(lines_of(nodes[src]["data"])) or "選擇"
            ok = [l or "（繼續）" for l, t in opts if target in reach(t)]
            steps.append({"prompt": prompt, "context": ctx, "choice": lab or "（繼續）",
                          "decisive": len(ok) < len(opts),
                          "also": [l for l in ok if l != (lab or "（繼續）")]})
        return steps

    ending_list = []
    for e in ends:
        d = nodes[e]["data"]
        prev_bg = None
        for n in board["nodes"]:
            for ed in out[n["id"]]:
                if ed["target"] == e:
                    prev_bg = n["data"].get("background")
        ending_list.append({"node": e, "image": d.get("background") or prev_bg,
                            "steps": path_to(e), "depth": dist(start, e)})
    ending_list.sort(key=lambda x: x["depth"])

    orphans = [n["id"] for n in board["nodes"] if n["id"] not in reachable]
    data = {
        "meta": {
            "title": doc["title"], "author": doc["authorName"],
            "handle": doc.get("authorHandle"), "cover": doc["coverUrl"],
            "description": doc["description"], "tags": doc.get("tags", []),
            "playUrl": "https://larch.ink/play/market/" + GAME_ID,
            "publishedAt": doc.get("publishedAt"), "release": doc.get("releaseNumber"),
            "nodeCount": len(board["nodes"]), "edgeCount": len(board["edges"]),
            "trueEnding": TE[0],
        },
        "segments": segments,
        "endings": ending_list,
        "stats": {"claimed": len(claimed), "orphans": orphans, "endings": ends},
    }
    # 有跑過 tools/fetch_images.py 的話，圖改指到本地縮圖
    m_path = os.path.join(HERE, "img", "sources.json")
    if os.path.exists(m_path):
        m = json.load(open(m_path))

        def local(u):
            v = m.get(u)
            if isinstance(v, dict):
                return v["src"], v.get("w") or 0, v.get("h") or 0
            return (v or u), 0, 0

        data["meta"]["cover"] = local(data["meta"]["cover"])[0]
        for seg in data["segments"]:
            for it in seg["body"]:
                if it.get("bg"):
                    src, w, h = local(it["bg"])
                    if w:
                        it["bg"], it["bgw"], it["bgh"] = src, w, h
                    else:
                        # 背景放的是影片（Cloudflare Stream 的內嵌網址），不能當圖畫。
                        # 保險箱打開那一段就是這樣接的，站上改成標一格「這裡是影片」。
                        it["video"] = it.pop("bg")
                if (it.get("item") or {}).get("image"):
                    it["item"]["image"] = local(it["item"]["image"])[0]
        for e in data["endings"]:
            if e.get("image"):
                e["image"], e["imgw"], e["imgh"] = local(e["image"])

    path = os.path.join(HERE, "data", "story.json")
    json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    # 同一份資料也寫成 js，網站用 file:// 直接打開也讀得到
    with open(os.path.join(HERE, "data", "story.js"), "w") as f:
        f.write("window.STORY=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print("卡片 %d 張；寫進 %d 張、走不到 %d 張；段落 %d 段、結局 %d 個"
          % (len(board["nodes"]), len(claimed), len(orphans), len(segments), len(ends)))
    print("輸出：" + path)


if __name__ == "__main__":
    main()
