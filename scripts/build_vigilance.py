#!/usr/bin/env python3
"""
Construit vigilance.json (aujourd'hui J + demain J+1) pour les 19 departements
de PACA + Occitanie, avec la fenetre temporelle (debut/fin) de chaque alerte,
et notifie via une "issue" GitHub quand un departement est orange ou rouge.

Source : "Meteo Vigilance niveau departemental" (Opendatasoft / Meteo-France),
acces libre sans jeton. Colonnes reelles : domain_id, color, echeance,
phenomenon, begin_time, end_time.
"""

import json, os, sys, re, datetime, gzip, zlib, urllib.parse, urllib.request

DATASET = "weatherref-france-vigilance-meteo-departement"
BASE = f"https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/{DATASET}/records"
STATE_FILE = "alert_state.json"

DEPTS = {
    "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes", "06": "Alpes-Maritimes",
    "13": "Bouches-du-Rhone", "83": "Var", "84": "Vaucluse",
    "09": "Ariege", "11": "Aude", "12": "Aveyron", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "34": "Herault", "46": "Lot", "48": "Lozere", "65": "Hautes-Pyrenees",
    "66": "Pyrenees-Orientales", "81": "Tarn", "82": "Tarn-et-Garonne",
}
COLORS = {"vert": 0, "jaune": 1, "orange": 2, "rouge": 3}
RANK_TO_COLOR = {v: k for k, v in COLORS.items()}

PHENO_CODES = {
    "1": "Vent violent", "2": "Pluie-inondation", "3": "Orages", "4": "Crues",
    "5": "Neige-verglas", "6": "Canicule", "7": "Grand froid", "8": "Avalanches",
    "9": "Vagues-submersion",
}

DEPT_FIELDS  = ["domain_id", "code_dep", "code_departement", "code_insee_departement",
                "departement", "dep", "insee_dep"]
COLOR_FIELDS = ["color", "couleur", "couleur_texte", "vigilance_couleur_texte",
                "risque_couleur", "coloration"]
ECH_FIELDS   = ["echeance", "echeance_type", "echance"]
PHENO_FIELDS = ["phenomenon", "phenomene", "phenomene_libelle", "libelle_phenomene",
                "nom_phenomene", "phenomene_nom"]
BEGIN_FIELDS = ["begin_time", "date_debut", "debut", "start_time"]
END_FIELDS   = ["end_time", "date_fin", "fin", "stop_time"]

DEPT_RE = re.compile(r"^(2[ABab]|\d{1,3})$")


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "vigilance-pacao/1.0", "Accept": "application/json",
        "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return json.loads(raw.decode("utf-8"))


def fetch_page(offset, limit=100, where=None):
    params = {"limit": limit, "offset": offset}
    if where:
        params["where"] = where
    return get(BASE + "?" + urllib.parse.urlencode(params))


def norm_color(val):
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in COLORS:
        return s
    if s in ("1", "2", "3", "4"):
        return RANK_TO_COLOR.get(int(s) - 1)
    for c in COLORS:
        if c in s:
            return c
    return None


def norm_pheno(val, strict=False):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s in PHENO_CODES:
        return PHENO_CODES[s]
    low = s.lower()
    rules = [("pluie", "Pluie-inondation"), ("orage", "Orages"), ("crue", "Crues"),
             ("submersion", "Vagues-submersion"), ("vague", "Vagues-submersion"),
             ("vent", "Vent violent"), ("neige", "Neige-verglas"), ("verglas", "Neige-verglas"),
             ("canicul", "Canicule"), ("chaleur", "Canicule"), ("froid", "Grand froid"),
             ("avalanch", "Avalanches"), ("inondation", "Inondation")]
    for key, label in rules:
        if key in low:
            return label
    if strict:
        return None
    return s[:1].upper() + s[1:]


def is_text_color(v):
    return str(v).strip().lower() in COLORS


def pick_named(keys, candidates):
    for c in candidates:
        if c in keys:
            return c
    return None


def discover_fields(sample):
    keys = set()
    for rec in sample:
        keys |= set(rec.keys())

    dept_field = pick_named(keys, DEPT_FIELDS)
    if dept_field is None:
        for k in keys:
            if k.endswith("_id"):
                continue
            vals = [str(rec.get(k)).strip() for rec in sample if rec.get(k) is not None]
            if vals and sum(1 for v in vals if DEPT_RE.match(v)) >= 3:
                dept_field = k
                break

    color_field = None
    for c in COLOR_FIELDS:
        if c in keys and any(norm_color(rec.get(c)) for rec in sample):
            color_field = c
            break
    if color_field is None:
        best, best_ratio = None, 0.0
        for k in keys:
            vals = [rec.get(k) for rec in sample if rec.get(k) is not None]
            if len(vals) < 3:
                continue
            ratio = sum(1 for v in vals if is_text_color(v)) / len(vals)
            if ratio >= 0.5 and ratio > best_ratio:
                best, best_ratio = k, ratio
        color_field = best

    ech_field = pick_named(keys, ECH_FIELDS)
    if ech_field is None:
        for k in keys:
            vals = [str(rec.get(k)).strip().lower() for rec in sample if rec.get(k) is not None]
            if any(v in ("j", "j1", "j+1", "j 1") for v in vals):
                ech_field = k
                break

    pheno_field = pick_named(keys, PHENO_FIELDS)
    if pheno_field is None:
        for k in keys:
            if k in (dept_field, color_field, ech_field) or k.endswith("_id"):
                continue
            vals = [rec.get(k) for rec in sample if rec.get(k) is not None]
            if vals and sum(1 for v in vals if norm_pheno(v, strict=True)) >= 3:
                pheno_field = k
                break

    begin_field = pick_named(keys, BEGIN_FIELDS)
    end_field = pick_named(keys, END_FIELDS)
    return dept_field, color_field, ech_field, pheno_field, begin_field, end_field


def code_of(rec, f):
    return str(rec.get(f, "")).strip().zfill(2)


def echeance_key(rec, ech_field):
    if not ech_field:
        return "J"
    v = str(rec.get(ech_field, "")).strip().lower()
    if v in ("j", ""):
        return "J"
    if v in ("j1", "j+1", "j 1"):
        return "J1"
    return None


def aggregate(recs, dept_f, color_f, ech_f, pheno_f, begin_f, end_f):
    levels = {"J": {c: 0 for c in DEPTS}, "J1": {c: 0 for c in DEPTS}}
    info = {"J": {c: {} for c in DEPTS}, "J1": {c: {} for c in DEPTS}}
    for r in recs:
        code = code_of(r, dept_f)
        if code not in DEPTS:
            continue
        key = echeance_key(r, ech_f)
        if key is None:
            continue
        col = norm_color(r.get(color_f))
        if not col:
            continue
        rank = COLORS[col]
        if rank > levels[key][code]:
            levels[key][code] = rank
        if rank >= 1 and pheno_f:
            name = norm_pheno(r.get(pheno_f))
            if not name:
                continue
            b = r.get(begin_f) if begin_f else None
            e = r.get(end_f) if end_f else None
            cur = info[key][code].get(name)
            if cur is None:
                info[key][code][name] = {"rank": rank, "debut": b, "fin": e}
            else:
                cur["rank"] = max(cur["rank"], rank)
                if b and (cur["debut"] is None or b < cur["debut"]):
                    cur["debut"] = b
                if e and (cur["fin"] is None or e > cur["fin"]):
                    cur["fin"] = e
    return levels, info


def phenos_list(day_code_info):
    out = []
    for n, v in sorted(day_code_info.items(), key=lambda kv: -kv[1]["rank"]):
        out.append({"phenomene": n, "niveau": RANK_TO_COLOR[v["rank"]],
                    "debut": v.get("debut"), "fin": v.get("fin")})
    return out


def window(day_code_info):
    items = [v for v in day_code_info.values() if v["rank"] >= 1]
    debuts = [v["debut"] for v in items if v.get("debut")]
    fins = [v["fin"] for v in items if v.get("fin")]
    return (min(debuts) if debuts else None, max(fins) if fins else None)


def compute_alerts(levels):
    alerts = []
    for c in DEPTS:
        lj, l1 = levels["J"][c], levels["J1"][c]
        if max(lj, l1) >= 2:
            alerts.append({"code": c, "nom": DEPTS[c], "j": lj, "j1": l1})
    alerts.sort(key=lambda a: a["code"])
    sig = ";".join(f"{a['code']}={a['j']}{a['j1']}" for a in alerts)
    return alerts, sig


def build_issue(alerts, owner):
    maxrank = max(max(a["j"], a["j1"]) for a in alerts)
    word = "ROUGE" if maxrank == 3 else "orange"
    emoji = "\U0001F534" if maxrank == 3 else "\U0001F7E0"
    codes = ", ".join(a["code"] for a in alerts)
    title = f"{emoji} Vigilance {word} — {codes}"
    lines = ["Vigilance **orange/rouge** detectee sur les prochaines 24-48 h :", ""]
    for a in alerts:
        parts = []
        if a["j"] >= 1:
            parts.append(f"aujourd'hui **{RANK_TO_COLOR[a['j']].upper()}**")
        if a["j1"] >= 1:
            parts.append(f"demain **{RANK_TO_COLOR[a['j1']].upper()}**")
        lines.append(f"- **{a['code']} {a['nom']}** — " + " · ".join(parts))
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    lines += ["", f"_Mis a jour le {now}._"]
    if owner:
        lines += ["", f"cc @{owner}"]
    return title, "\n".join(lines)


def gh_api(method, path, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "vigilance-pacao/1.0", "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def run_notifications(alerts, sig, state, repo, token):
    prev_sig = state.get("signature", "")
    prev_issue = state.get("issue")
    if sig == prev_sig:
        print("[notif] pas de changement d'alerte")
        return state
    owner = repo.split("/")[0] if repo else ""
    if not (token and repo):
        print(f"[notif] (local) changement detecte -> {sig or 'aucune alerte'}")
        return {"signature": sig, "issue": prev_issue}
    try:
        if alerts:
            title, body = build_issue(alerts, owner)
            issue = gh_api("POST", f"/repos/{repo}/issues", token, {"title": title, "body": body})
            num = issue.get("number")
            print(f"[notif] issue #{num} creee : {title}")
            if prev_issue:
                try:
                    gh_api("POST", f"/repos/{repo}/issues/{prev_issue}/comments", token,
                           {"body": "Situation mise a jour — voir la nouvelle alerte."})
                    gh_api("PATCH", f"/repos/{repo}/issues/{prev_issue}", token, {"state": "closed"})
                except Exception as e:
                    print(f"[notif] cloture #{prev_issue} KO ({e})")
            return {"signature": sig, "issue": num}
        else:
            if prev_issue:
                gh_api("POST", f"/repos/{repo}/issues/{prev_issue}/comments", token,
                       {"body": f"\u2705 Retour au vert — plus de vigilance orange/rouge. cc @{owner}"})
                gh_api("PATCH", f"/repos/{repo}/issues/{prev_issue}", token, {"state": "closed"})
                print(f"[notif] retour au vert — issue #{prev_issue} cloturee")
            return {"signature": "", "issue": None}
    except Exception as e:
        print(f"[notif] ECHEC ({e}) — reessai au prochain run")
        return state


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"signature": "", "issue": None}


def main():
    first = fetch_page(0, limit=100)
    total = first.get("total_count", 0)
    sample = first.get("results", [])
    dept_f, color_f, ech_f, pheno_f, begin_f, end_f = discover_fields(sample)
    print(f"[schema] total={total} dept={dept_f!r} color={color_f!r} echeance={ech_f!r} "
          f"phenomene={pheno_f!r} debut={begin_f!r} fin={end_f!r}")
    if sample:
        ex = {k: sample[0].get(k) for k in list(sample[0].keys())[:12]}
        print("[sample] " + json.dumps(ex, ensure_ascii=False))
    if not dept_f or not color_f:
        print("[ERREUR] champs departement/couleur non identifies. Exemple complet :")
        print(json.dumps(sample[0] if sample else {}, ensure_ascii=False, indent=2))
        sys.exit(1)

    recs = []
    codes_q = ",".join(f'"{c}"' for c in DEPTS)
    try:
        where = f"{dept_f} in ({codes_q})"
        offset = 0
        while True:
            page = fetch_page(offset, 100, where=where)
            res = page.get("results", [])
            recs.extend(res)
            offset += 100
            if offset >= page.get("total_count", 0) or not res or offset > 5000:
                break
        print(f"[fetch] filtre serveur OK, {len(recs)} records")
    except Exception as e:
        print(f"[fetch] filtre serveur KO ({e}); repli pagination complete")
        recs, offset = [], 0
        while offset < total and offset <= 5000:
            recs.extend(fetch_page(offset, 100).get("results", []))
            offset += 100
        recs = [r for r in recs if code_of(r, dept_f) in DEPTS]
        print(f"[fetch] {len(recs)} records apres filtrage local")

    levels, info = aggregate(recs, dept_f, color_f, ech_f, pheno_f, begin_f, end_f)

    departements = {}
    for c in DEPTS:
        dj, fj = window(info["J"][c])
        d1, f1 = window(info["J1"][c])
        departements[c] = {
            "niveau": RANK_TO_COLOR[levels["J"][c]], "nom": DEPTS[c],
            "phenomenes": phenos_list(info["J"][c]), "debut": dj, "fin": fj,
            "demain": {"niveau": RANK_TO_COLOR[levels["J1"][c]],
                       "phenomenes": phenos_list(info["J1"][c]), "debut": d1, "fin": f1},
        }
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    out = {"date": now.date().isoformat(), "updated": now.isoformat(timespec="minutes"),
           "source": "Meteo-France via Opendatasoft", "departements": departements}
    with open("vigilance.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    alerts, sig = compute_alerts(levels)
    n_today = sum(1 for c in DEPTS if levels["J"][c] >= 1)
    print(f"[ok] vigilance.json ecrit — {n_today} dept en vigilance aujourd'hui, "
          f"{len(alerts)} en orange/rouge (J ou J+1)")

    state = load_state()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    new_state = run_notifications(alerts, sig, state, repo, token)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
