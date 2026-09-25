"""
verifier_coherence.py -- compare ce qui a été SIMULÉ (demo_reference.json) à ce que le cockpit AFFICHE.

  cd backend
  DATABASE_URL=postgresql://.../vusine_demo python scripts/demo/verifier_coherence.py \\
      --api http://localhost:8001 --admin admin --admin-password '***'

Les valeurs attendues sont recalculées ICI à partir de la vérité terrain (quantités scannées, minutes d'arrêt,
planning), avec les définitions du métier -- pas en relisant le code de l'application. Un écart signifie donc
soit un bug de l'application, soit une définition à rediscuter ; dans les deux cas, on le voit.

Trois niveaux : OK, ÉCART (chiffre faux -> à corriger) et ALERTE (chiffre cohérent avec sa formule mais
discutable pour le métier -> à décider). Code de sortie 1 s'il y a au moins un ÉCART.
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from sqlalchemy import text

RES = []     # (categorie, nom, statut, detail)


def noter(cat, nom, ok, detail="", alerte=False):
    RES.append((cat, nom, "OK" if ok else ("ALERTE" if alerte else "ÉCART"), detail))


def proche(a, b, tol):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8001")
    p.add_argument("--admin", default=os.getenv("DEMO_ADMIN_USER", "admin"))
    p.add_argument("--admin-password", default=os.getenv("DEMO_ADMIN_PASSWORD"))
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--echantillon-operateurs", type=int, default=5)
    p.add_argument("--oui", action="store_true")
    a = p.parse_args()

    ref = L.charger_reference(a.reference)
    cel = ref["cellules"]
    jours = sorted(ref["meta"]["jours"])
    P = {"date_debut": jours[0], "date_fin": jours[-1]}
    db = L.ouvrir_db(a.oui)
    # *** AJOUT 2026-09-25, CORRIGÉ 2026-09-25 *** : l'API est interrogée sur toute la
    # fenêtre continue [jours[0], jours[-1]] et sur TOUTES les lignes actives de l'usine
    # pour les totaux usine -- pas seulement les lignes/jours retenus par la simulation.
    # On calcule donc le planning confirmé réel (recalculé depuis la base) de tout
    # (ligne, jour) absent de la simulation -- cf. docstring de cellules_hors_simulation
    # dans demo_lib.py -- mais on ne le traite PAS de la même façon selon la ligne :
    #   - une ligne SIMULÉE (ex. CCL06 le 2026-09-19, un jour isolé écarté par
    #     jours_de_reference) : la cellule complète la référence de cette ligne, comme les
    #     autres -- les vérifications PAR LIGNE (Par ligne, TRS par ligne, Score équipe)
    #     doivent en tenir compte.
    #   - une ligne JAMAIS simulée (les ~48 autres, sans équipe fictive affectée ni entrée
    #     dans demo_reference.json) : sa cellule ne sert QU'à corriger l'agrégat usine du
    #     TRS (qui, lui, porte sur les 88 lignes) -- l'injecter dans `sain`/`par_ligne`
    #     ferait planter les vérifications par ligne (KeyError sur ref["equipes"], qui ne
    #     connaît que les lignes simulées).
    codes_simules = {c["ligne"] for c in cel}
    hors_simulation = L.cellules_hors_simulation(db, jours, cel)
    cel = cel + [c for c in hors_simulation if c["ligne"] in codes_simules]
    extra_usine_seulement = [c for c in hors_simulation if c["ligne"] not in codes_simules]
    api = L.Api(a.api)
    api.login(a.admin, a.admin_password)
    L.verifier_meme_base(api, db, a.admin)
    get = lambda chemin, ident=a.admin, **q: api.appel("GET", chemin, ident, params={**P, **q}).json()
    print(f"Référence : {len(cel)} journées-lignes du {jours[0]} au {jours[-1]}"
          f" (+{len(extra_usine_seulement)} journées d'autres lignes de l'usine, hors périmètre simulé, pour les totaux usine)\n")

    par_ligne = defaultdict(list)
    for c in cel:
        par_ligne[c["ligne"]].append(c)
    # une ligne avec un arrêt jamais clôturé est comptée par l'application jusqu'à « maintenant » : hors comparaison chiffrée
    ouvertes = {l for l, cs in par_ligne.items() if any(x["fin"] is None for c in cs for x in c["arrets"])}
    if ouvertes:
        print(f"Lignes avec arrêt non clôturé (exclues des comparaisons chiffrées) : {sorted(ouvertes)}\n")
    sain = {l: cs for l, cs in par_ligne.items() if l not in ouvertes}

    # ---- 1. Intégrité brute en base (limitée à la période simulée : la production du jour, en direct, n'entre pas) ----
    borne = {"p": L.PREFIXE_MATRICULE + "%", "a": jours[0], "b": jours[-1]}
    n_pal = db.execute(text("SELECT COUNT(*) FROM palettes p JOIN users u ON u.id = p.operateur_id WHERE u.matricule LIKE :p AND p.created_at::date BETWEEN :a AND :b"), borne).scalar()
    noter("Base", "palettes fictives en base = palettes simulées", n_pal == sum(c["nb_palettes"] for c in cel), f"{n_pal} vs {sum(c['nb_palettes'] for c in cel)}")
    q = db.execute(text("SELECT COALESCE(SUM(quantite_totale),0), COALESCE(SUM(nb_rebuts),0) FROM palettes p JOIN users u ON u.id = p.operateur_id WHERE u.matricule LIKE :p AND p.created_at::date BETWEEN :a AND :b"), borne).fetchone()
    noter("Base", "quantité totale scannée", int(q[0]) == sum(c["conforme"] for c in cel), f"{int(q[0])} vs {sum(c['conforme'] for c in cel)}")
    noter("Base", "rebuts déclarés", int(q[1]) == sum(c["rebuts"] for c in cel), f"{int(q[1])} vs {sum(c['rebuts'] for c in cel)}")
    n_arr = db.execute(text("SELECT COUNT(*) FROM arrets a JOIN users u ON u.id = a.operateur_id WHERE u.matricule LIKE :p AND a.heure_debut::date BETWEEN :a AND :b"), borne).scalar()
    noter("Base", "arrêts en base = arrêts simulés", n_arr == sum(len(c["arrets"]) for c in cel), f"{n_arr} vs {sum(len(c['arrets']) for c in cel)}")
    doublons = db.execute(text("SELECT COUNT(*) FROM (SELECT numero_palette FROM palettes GROUP BY 1 HAVING COUNT(*) > 1) t")).scalar()
    noter("Base", "aucun numéro de palette en double", doublons == 0, str(doublons))
    hors = db.execute(text("""SELECT COUNT(*) FROM palettes p JOIN users u ON u.id = p.operateur_id WHERE u.matricule LIKE :p AND
        (p.created_at::time < '00:01' OR p.numero_palette NOT LIKE 'PAL-%-' || to_char(p.created_at, 'YYYYMMDD') || '-%')"""), {"p": L.PREFIXE_MATRICULE + "%"}).scalar()
    noter("Base", "numéro de palette cohérent avec sa date", hors == 0, str(hors))

    # ---- 2. Rapport « Par ligne » -----------------------------------------------------------------
    rows = {r["code"]: r for r in get("/rapports/par-ligne")}
    for code, cs in sain.items():
        r = rows.get(code)
        if not r:
            noter("Par ligne", f"{code} présente", False); continue
        att = dict(reel=sum(c["conforme"] for c in cs), theo=sum(c["q_run"] for c in cs), pal=sum(c["nb_palettes"] for c in cs), arret=sum(c["arret_min"] for c in cs))
        noter("Par ligne", f"{code} réel", r["reel_total"] == att["reel"], f"{r['reel_total']} vs {att['reel']}")
        noter("Par ligne", f"{code} théorique", proche(r["theorique_total"], att["theo"], 1.01), f"{r['theorique_total']} vs {att['theo']:.1f}")
        noter("Par ligne", f"{code} palettes", r["nb_palettes"] == att["pal"], f"{r['nb_palettes']} vs {att['pal']}")
        noter("Par ligne", f"{code} minutes d'arrêt", proche(r["temps_arret_min"], att["arret"], 1.01), f"{r['temps_arret_min']} vs {att['arret']:.1f}")
        if att["theo"] > 0:
            noter("Par ligne", f"{code} performance %", proche(r["performance_moyenne"], att["reel"] / att["theo"] * 100, 1.0), f"{r['performance_moyenne']} vs {att['reel'] / att['theo'] * 100:.1f}")

    # ---- 3. TRS (Disponibilité x Performance x Qualité) ---------------------------------------------
    trs = get("/rapports/trs")
    # Les totaux usine du TRS portent sur les 88 lignes actives, pas seulement les lignes
    # simulées : on y ajoute donc `extra_usine_seulement` (planning réel des autres
    # lignes), sans le faire remonter dans les vérifications par ligne ci-dessus.
    sel = [c for l, cs in sain.items() for c in cs] + extra_usine_seulement
    plan, qrun = sum(c["planifie"] for c in sel), sum(c["q_run"] for c in sel)
    conf, reb = sum(c["conforme"] for c in sel), sum(c["rebuts"] for c in sel)
    if not ouvertes:
        u = trs["usine"]
        noter("TRS", "disponibilité usine", proche(u["disponibilite_pct"], qrun / plan * 100, 0.15), f"{u['disponibilite_pct']} vs {qrun / plan * 100:.2f}")
        noter("TRS", "performance usine", proche(u["performance_pct"], (conf + reb) / qrun * 100, 0.15), f"{u['performance_pct']} vs {(conf + reb) / qrun * 100:.2f}")
        noter("TRS", "qualité usine", proche(u["qualite_pct"], conf / (conf + reb) * 100, 0.15), f"{u['qualite_pct']} vs {conf / (conf + reb) * 100:.2f}")
        noter("TRS", "TRS usine = conforme / planifié", proche(u["trs_pct"], conf / plan * 100, 0.15), f"{u['trs_pct']} vs {conf / plan * 100:.2f}")
        noter("TRS", "TRS = disponibilité x performance x qualité", proche(u["trs_pct"], u["disponibilite_pct"] * u["performance_pct"] * u["qualite_pct"] / 10000, 0.3), f"{u['trs_pct']}")
        noter("TRS", "données jugées suffisantes", not trs["donnees_insuffisantes"], f"{trs['nb_palettes']} palettes")
    for l in trs["lignes"]:
        cs = sain.get(l["code"])
        if cs:
            noter("TRS", f"{l['code']} TRS", proche(l["trs_pct"], sum(c["conforme"] for c in cs) / sum(c["planifie"] for c in cs) * 100, 0.15), f"{l['trs_pct']}")

    # ---- 4. Pareto des causes d'arrêt ----------------------------------------------------------------
    par = get("/rapports/pareto-arrets")
    att_c, att_n = defaultdict(float), defaultdict(int)
    for l, cs in sain.items():
        for c in cs:
            for x in c["arrets"]:
                d = (L.datetime.fromisoformat(x["fin"]) - L.datetime.fromisoformat(x["debut"])).total_seconds() / 60
                att_c[x["cause"]] += d; att_n[x["cause"]] += 1
    if not ouvertes:
        vus = {c["cause"]: c for c in par["causes"]}
        for cause, mins in att_c.items():
            c = vus.get(cause)
            noter("Pareto", f"{cause} : durée et nombre", bool(c) and proche(c["duree_min"], mins, 1.01) and c["nb_arrets"] == att_n[cause], f"{c and c['duree_min']} min/{c and c['nb_arrets']} vs {mins:.0f} min/{att_n[cause]}")
        noter("Pareto", "durée totale", proche(par["total_duree_min"], sum(att_c.values()), 2.01), f"{par['total_duree_min']} vs {sum(att_c.values()):.0f}")
        rangs = [c["duree_min"] for c in par["causes"]]
        noter("Pareto", "causes classées par durée décroissante", rangs == sorted(rangs, reverse=True))
        noter("Pareto", "cumul final = 100 %", proche(par["causes"][-1]["pct_cumule"], 100, 0.2) if par["causes"] else True)
    noter("Pareto", "arrêts non clôturés signalés", par["nb_arrets_non_clotures"] == sum(1 for cs in par_ligne.values() for c in cs for x in c["arrets"] if x["fin"] is None), str(par["nb_arrets_non_clotures"]))

    # ---- 5. Score d'équipe (arrêts non imputables neutralisés) ------------------------------------------
    eq = get("/scoring/equipes")
    lg = {l["code"]: l for l in eq["lignes"]}
    for code, cs in sain.items():
        l = lg.get(code)
        if not l or l["masque"]:
            continue
        att = sum(c["planifie"] * (c["net_min"] - c["min_neutralisees"]) / c["net_min"] for c in cs)
        prod = sum(c["conforme"] + c["rebuts"] for c in cs)
        noter("Score équipe", f"{code} attendu et produit", proche(l["attendu"], att, 1.01) and proche(l["produit"], prod, 1.01), f"{l['attendu']}/{l['produit']} vs {att:.0f}/{prod}")
        if att > 0 and l["score_pct"] is not None:
            noter("Score équipe", f"{code} score %", proche(l["score_pct"], prod / att * 100, 0.15), f"{l['score_pct']} vs {prod / att * 100:.1f}")
    seuil = int(float(api.appel("GET", "/auth/params/scoring_equipe_effectif_min", a.admin).json().get("value") or 0))
    noter("Score équipe", f"masquage conforme au seuil ({seuil})", all(l["masque"] == (l["effectif"] is not None and l["effectif"] < seuil) for l in eq["lignes"]),
          f"{sum(1 for l in eq['lignes'] if l['masque'])} masquées")
    if seuil > 0:
        print(f"Note : le seuil de masquage est à {seuil} -> les équipes plus petites sont masquées (Administration -> Paramètres pour le mettre à 0).\n")
    noter("Score équipe", "effectif = équipe affectée", all(lg[c]["effectif"] == len(ref["equipes"][str(cs[0]["ligne_id"])]) for c, cs in sain.items() if c in lg and not lg[c]["masque"]))
    noter("Score équipe", "aucun nom d'opérateur dans la réponse", "(démo)" not in str(eq))

    # ---- 6. Côté opérateur ------------------------------------------------------------------------------
    ids = {r.matricule: r.id for r in db.execute(text("SELECT id, matricule FROM users WHERE matricule LIKE :p"), {"p": L.PREFIXE_MATRICULE + "%"})}
    nb_par_op = defaultdict(int)
    for c in cel:
        for o, n in c["par_operateur"].items():
            nb_par_op[o] += n
    ech = sorted(nb_par_op, key=lambda m: -nb_par_op[m])[: a.echantillon_operateurs]
    for mat in ech:
        api.login(mat, L.MOT_DE_PASSE_DEMO)
        h = api.appel("GET", "/rapports/historique-scans", mat, params=P).json()
        noter("Opérateur", f"{mat} : son historique = ses palettes", len(h) == nb_par_op[mat] and all(x["operateur_id"] == ids[mat] for x in h), f"{len(h)} vs {nb_par_op[mat]}")
        m = api.appel("GET", "/scoring/mon-activite", mat, params=P).json()
        noter("Opérateur", f"{mat} : « Mes performances » sans score personnel", not any(k in m for k in ("score_pct", "rang", "classement")) and m["nom"].endswith("(démo)"))
        lignes_op = [c for c, cs in par_ligne.items() if mat in cs[0]["equipe"]]
        noter("Opérateur", f"{mat} : lignes affichées = lignes de son équipe", sorted(x["ligne_code"] for x in m["lignes"]) == sorted(lignes_op), f"{sorted(x['ligne_code'] for x in m['lignes'])} vs {sorted(lignes_op)}")
        # Heures de présence : une personne affectée sur toute la période ne peut compter que les heures de poste
        # (pause déduite), quel que soit le nombre de lignes où elle est affectée.
        attendu_h = 0.0
        d = date.fromisoformat(jours[0])
        while d <= date.fromisoformat(jours[-1]):
            poste = L.poste_du_jour(db, d)
            attendu_h += poste.net_min / 60 if poste else 0
            d += L.timedelta(days=1)
        noter("Opérateur", f"{mat} : heures de présence = heures de poste ({attendu_h:.1f} h)", proche(m["heures_totales"], attendu_h, 0.3),
              f"affiché {m['heures_totales']} h pour {len(lignes_op)} ligne(s)")
        api.appel("GET", "/dashboard/vue_usine", mat, attendu=None)

    # ---- 7. Cloisonnement : un opérateur ne voit pas la direction ------------------------------------------
    if ech:
        mat = ech[0]
        for chemin in ("/scoring/equipes", "/rapports/trs", "/rapports/pareto-arrets", "/admin/affectations-ligne/" + str(cel[0]["ligne_id"])):
            r = api.appel("GET", chemin, mat, attendu=None, params=P)
            noter("Cloisonnement", f"opérateur refusé sur {chemin.split('?')[0]}", r.status_code in (401, 403), str(r.status_code))
        sc = api.appel("GET", "/scoring/suivi-individuel", mat, attendu=None, params=P)
        noter("Cloisonnement", "opérateur refusé sur le suivi individuel", sc.status_code in (401, 403), str(sc.status_code))

    # ---- Synthèse ---------------------------------------------------------------------------------------------
    print(f"{'Domaine':<15}{'OK':>6}{'ÉCART':>7}{'ALERTE':>8}")
    for cat in dict.fromkeys(r[0] for r in RES):
        rs = [r for r in RES if r[0] == cat]
        print(f"{cat:<15}{sum(r[2] == 'OK' for r in rs):>6}{sum(r[2] == 'ÉCART' for r in rs):>7}{sum(r[2] == 'ALERTE' for r in rs):>8}")
    for niveau in ("ÉCART", "ALERTE"):
        lst = [r for r in RES if r[2] == niveau]
        if lst:
            print(f"\n{niveau} ({len(lst)}) :")
            for cat, nom, _s, d in lst[:25]:
                print(f"  [{cat}] {nom} -> {d}")
            if len(lst) > 25:
                print(f"  ... et {len(lst) - 25} autres")
    n_ecart = sum(r[2] == "ÉCART" for r in RES)
    print(f"\n{len(RES)} contrôles : {sum(r[2] == 'OK' for r in RES)} OK, {n_ecart} écart(s), {sum(r[2] == 'ALERTE' for r in RES)} alerte(s).")
    sys.exit(1 if n_ecart else 0)


if __name__ == "__main__":
    main()