#!/usr/bin/env python3
"""
Construit vigilance.json pour les 19 departements de PACA + Occitanie.

Source : jeu de donnees public "Meteo Vigilance niveau departemental"
(Opendatasoft, alimente par Meteo-France) — acces libre, sans jeton.

Le script DECOUVRE les noms de champs au demarrage (departement / couleur /
echeance / phenomene), il est donc robuste si la source renomme ses colonnes.
Il affiche ce qu'il a trouve dans les logs de l'Action.
"""

import json, sys, datetime, gzip, zlib, urllib.parse, urllib.request

DATASET = "weatherref-france-vigilance-meteo-departement"
BASE = f"https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/{DATASET}/records"

DEPTS = {
    "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes", "06": "Alpes-Maritimes",
    "13": "Bouches-du-Rhone", "83": "Var", "84": "Vaucluse",
    "09": "Ariege", "11": "Aude", "12": "Aveyron", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "34": "Herault", "46": "Lot", "48": "Lozere", "65": "Hautes-Pyrenees",
    "66": "Pyrenees-Orientales", "81": "Tarn", "82": "Tarn-et-Garonne",
}
COLORS = {"vert": 0, "jaune": 1, "orange": 2, "rouge": 3}
RANK_TO_COLOR = {v: k for k, v in COLORS.items()}

# Codes officiels des phenomenes de vigilance Meteo-France
PHENO_CODES = {
    "1": "Vent violent", "2": "Pluie-inondation", "3": "Orages", "4": "Crues",
    "5": "Neige-verglas", "6": "Canicule", "7": "Grand froid", "8": "Avalanches",
    "9": "Vagues-submersion",
}
PHENO_FIELDS = ["phenomene", "phenomene_libelle", "libelle_phenomene", "nom_phenomene",
                "phenomene_nom", "risque", "type_risque", "type", "libelle"]


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "vigilance-pacao/1.0",
        "Accept": "application/json",
        "Accept-Encoding": "identity",   # demande une reponse non compressee
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        # repli : certains serveurs compressent quand meme -> on decompresse
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
    """Ramene une valeur (code 1-9 ou texte) a un libelle de phenomene lisible."""
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
    return s[:1].upper() + s[1:]   # phenomene inconnu : on garde le libelle brut


def discover_fields(sample):
    dept_field = color_field = ech_field = pheno_field = None
    keys = set()
    for rec in sample:
        keys |= set(rec.keys())
    for k in keys:
        vals = [rec.get(k) for rec in sample if rec.get(k) is not None]
        if not vals:
            continue
        svals = [str(v).strip() for v in vals]
        if dept_field is None and sum(1 for v in svals if v.zfill(2) in DEPTS) >= 3:
            dept_field = k
        if color_field is None and sum(1 for v in svals if norm_color(v)) >= 3:
            color_field = k
        low = [v.lower() for v in svals]
        if ech_field is None and any(v in ("j", "j1", "j+1", "j 1") for v in low):
            ech_field = k
    # phenomene : d'abord les noms de champ connus, sinon detection par valeurs
    for cand in PHENO_FIELDS:
        if cand in keys:
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


def is_today(rec, ech_field):
    if not ech_field:
        return True
    return str(rec.get(ech_field, "")).strip().lower() in ("j", "")


def main():
    first = fetch_page(0, limit=100)
    total = first.get("total_count", 0)
    sample = first.get("results", [])
    dept_f, color_f, ech_f, pheno_f = discover_fields(sample)
    print(f"[schema] total={total} dept={dept_f!r} color={color_f!r} "
          f"echeance={ech_f!r} phenomene={pheno_f!r}")
    if not dept_f or not color_f:
        print("[ERREUR] champs departement/couleur non identifies. Exemple de record :")
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

    levels = {c: 0 for c in DEPTS}
    pheno_rank = {c: {} for c in DEPTS}   # dept -> {libelle: rang maxi}
    for r in recs:
        if not is_today(r, ech_f):
            continue
        code = code_of(r, dept_f)
        if code not in DEPTS:
            continue
        col = norm_color(r.get(color_f))
        if not col:
            continue
        rank = COLORS[col]
        if rank > levels[code]:
            levels[code] = rank
        if rank >= 1 and pheno_f:                      # note le type des le jaune
            name = norm_pheno(r.get(pheno_f))
            if name:
                prev = pheno_rank[code].get(name, -1)
                if rank > prev:
                    pheno_rank[code][name] = rank

    departements = {}
    for c in DEPTS:
        phenos = [{"phenomene": n, "niveau": RANK_TO_COLOR[rk]}
                  for n, rk in sorted(pheno_rank[c].items(), key=lambda kv: -kv[1])]
        departements[c] = {"niveau": RANK_TO_COLOR[levels[c]], "nom": DEPTS[c],
                           "phenomenes": phenos}

    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    out = {"date": now.date().isoformat(), "updated": now.isoformat(timespec="minutes"),
           "source": "Meteo-France via Opendatasoft", "departements": departements}
    with open("vigilance.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    n = sum(1 for c in DEPTS if levels[c] >= 1)
    print(f"[ok] vigilance.json ecrit — {n} departement(s) en vigilance")


if __name__ == "__main__":
    main()
