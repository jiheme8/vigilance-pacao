#!/usr/bin/env python3
"""
Construit vigilance.json (aujourd'hui J + demain J+1) pour les 19 departements
de PACA + Occitanie, et notifie via une "issue" GitHub quand un departement est
orange ou rouge sur J ou J+1.

Source : jeu de donnees public "Meteo Vigilance niveau departemental"
(Opendatasoft, alimente par Meteo-France) — acces libre, sans jeton.

Notifications : utilise le GITHUB_TOKEN fourni automatiquement par l'Action
(aucun secret a configurer). Cree une issue quand la situation d'alerte change,
mentionne le proprietaire du depot, et cloture l'ancienne alerte au retour au vert.
"""

import json, os, sys, datetime, gzip, zlib, urllib.parse, urllib.request

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
PHENO_FIELDS = ["phenomene", "phenomene_libelle", "libelle_phenomene", "nom_phenomene",
                "phenomene_nom", "risque", "type_risque", "type", "libelle"]
# Noms de colonne "couleur" connus (essayes en priorite)
COLOR_FIELDS = ["couleur", "couleur_texte", "vigilance_couleur_texte", "risque_couleur",
                "coloration", "couleur_niveau", "color", "etat_couleur"]


# ------------------------- HTTP (donnees vigilance) -------------------------
def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "vigilance-pacao/1.0",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
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


# ------------------------- normalisation -------------------------
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
    return str(v).strip().lower() in COLORS   # vert/jaune/orange/rouge (jamais un chiffre seul)


def discover_fields(sample):
    dept_field = color_field = ech_field = pheno_field = None
    keys = set()
    for rec in sample:
        keys |= set(rec.keys())

    # --- departement : intersecte nos codes connus ---
    for k in keys:
        vals = [str(rec.get(k)).strip() for rec in sample if rec.get(k) is not None]
        if vals and sum(1 for v in vals if v.zfill(2) in DEPTS) >= 3:
            dept_field = k
            break

    # --- couleur : d'abord les noms connus, puis une colonne 100% texte-couleur ---
    for cand in COLOR_FIELDS:
        if cand in keys and any(norm_color(rec.get(cand)) for rec in sample):
            color_field = cand
            break
    if color_field is None:
        best, best_ratio = None, 0.0
        for k in keys:
            vals = [rec.get(k) for rec in sample if rec.get(k) is not None]
            if len(vals) < 3:
                continue
            ratio = sum(1 for v in vals if is_text_color(v)) / len(vals)
            # une vraie colonne couleur ne contient que vert/jaune/orange/rouge ;
            # on ignore ainsi toute colonne de chiffres (phenomene code, etc.)
            if ratio >= 0.5 and ratio > best_ratio:
                best, best_ratio = k, ratio
        color_field = best

    # --- echeance : valeurs J / J1 ---
    for k in keys:
        vals = [str(rec.get(k)).strip().lower() for rec in sample if rec.get(k) is not None]
        if any(v in ("j", "j1", "j+1", "j 1") for v in vals):
            ech_field = k
            break

    # --- phenomene : noms connus, sinon detection par valeurs (hors colonnes deja prises) ---
    for cand in PHENO_FIELDS:
        if cand in keys and cand != color_field:
            pheno_field = cand
            break
    if pheno_field is None:
        for k in keys:
            if k in (dept_field, color_field, ech_field):
                continue
            vals = [rec.get(k) for rec in sample if rec.get(k) is not None]
            if vals and sum(1 for v in vals if norm_pheno(v, strict=True)) >= 3:
                pheno_field = k
                break
    return dept_field, color_field, ech_field, pheno_field


def code_of(rec, f):
    return str(rec.get(f, "")).strip().zfill(2)


def echeance_key(rec, ech_field):
    """Retourne 'J' (aujourd'hui), 'J1' (demain) ou None."""
    if not ech_field:
        return "J"
    v = str(rec.get(ech_field, "")).strip().lower()
    if v in ("j", ""):
        return "J"
    if v in ("j1", "j+1", "j 1"):
        return "J1"
    return None


# ------------------------- agregation -------------------------
def aggregate(recs, dept_f, color_f, ech_f, pheno_f):
    levels = {"J": {c: 0 for c in DEPTS}, "J1": {c: 0 for c in DEPTS}}
    pheno = {"J": {c: {} for c in DEPTS}, "J1": {c: {} for c in DEPTS}}
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
            if name and rank > pheno[key][code].get(name, -1):
                pheno[key][code][name] = rank
    return levels, pheno


def phenos_list(d):
    return [{"phenomene": n, "niveau": RANK_TO_COLOR[rk]}
            for n, rk in sorted(d.items(), key=lambda kv: -kv[1])]


def compute_alerts(levels, pheno):
    """Departements orange/rouge sur J ou J1. Retourne (liste, signature)."""
    alerts = []
    for c in DEPTS:
        lj, l1 = levels["J"][c], levels["J1"][c]
        if max(lj, l1) >= 2:
            alerts.append({"code": c, "nom": DEPTS[c], "j": lj, "j1": l1,
                           "pj": phenos_list(pheno["J"][c]),
                           "p1": phenos_list(pheno["J1"][c])})
    alerts.sort(key=lambda a: a["code"])
    sig = ";".join(f"{a['code']}={a['j']}{a['j1']}" for a in alerts)
    return alerts, sig


# ------------------------- notification GitHub -------------------------
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
            ph = ", ".join(p["phenomene"] for p in a["pj"])
            parts.append(f"aujourd'hui **{RANK_TO_COLOR[a['j']].upper()}**" + (f" ({ph})" if ph else ""))
        if a["j1"] >= 1:
            ph = ", ".join(p["phenomene"] for p in a["p1"])
            parts.append(f"demain **{RANK_TO_COLOR[a['j1']].upper()}**" + (f" ({ph})" if ph else ""))
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
        body = r.read().decode() or "{}"
        return json.loads(body)


def run_notifications(alerts, sig, state, repo, token):
    """Cree/cloture une issue selon l'evolution. Retourne le nouvel etat."""
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
                    print(f"[notif] cloture ancienne issue #{prev_issue} KO ({e})")
            return {"signature": sig, "issue": num}
        else:
            if prev_issue:
                gh_api("POST", f"/repos/{repo}/issues/{prev_issue}/comments", token,
                       {"body": f"\u2705 Retour au vert — plus de vigilance orange/rouge sur les 19 departements. cc @{owner}"})
                gh_api("PATCH", f"/repos/{repo}/issues/{prev_issue}", token, {"state": "closed"})
                print(f"[notif] retour au vert — issue #{prev_issue} cloturee")
            return {"signature": "", "issue": None}
    except Exception as e:
        print(f"[notif] ECHEC ({e}) — nouvelle tentative au prochain run")
        return state


# ------------------------- main -------------------------
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
    dept_f, color_f, ech_f, pheno_f = discover_fields(sample)
    print(f"[schema] total={total} dept={dept_f!r} color={color_f!r} "
          f"echeance={ech_f!r} phenomene={pheno_f!r}")
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

    levels, pheno = aggregate(recs, dept_f, color_f, ech_f, pheno_f)

    departements = {}
    for c in DEPTS:
        departements[c] = {
            "niveau": RANK_TO_COLOR[levels["J"][c]], "nom": DEPTS[c],
            "phenomenes": phenos_list(pheno["J"][c]),
            "demain": {"niveau": RANK_TO_COLOR[levels["J1"][c]],
                       "phenomenes": phenos_list(pheno["J1"][c])},
        }
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    out = {"date": now.date().isoformat(), "updated": now.isoformat(timespec="minutes"),
           "source": "Meteo-France via Opendatasoft", "departements": departements}
    with open("vigilance.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    alerts, sig = compute_alerts(levels, pheno)
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
