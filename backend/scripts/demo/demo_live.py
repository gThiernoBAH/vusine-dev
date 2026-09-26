"""
demo_live.py -- fait travailler les opérateurs fictifs EN DIRECT pendant la démo.

  cd backend
  DATABASE_URL=postgresql://.../vusine_demo  python scripts/demo/demo_live.py \\
      --api http://localhost:8001 --admin-password '***' --regler-poste --cloner-planning-depuis 2026-09-23

Au lancement, la journée est REJOUÉE jusqu'à « maintenant » (palettes et arrêts déjà passés, datés aux bonnes
heures) : l'Andon et la Vue Usine s'ouvrent sur une usine en pleine activité, pas sur un écran vide. Ensuite le script
continue AU RYTHME RÉEL : chaque palette et chaque arrêt part de l'API à l'heure prévue. Ctrl-C pour arrêter.

  --regler-poste            pose pour AUJOURD'HUI seulement un horaire spécial qui englobe l'heure actuelle
                            (le poste standard, et donc tout l'historique, n'est pas touché). Utile si la démo
                            a lieu en dehors de 7h30-17h.
  --cloner-planning-depuis  si Odoo n'a pas de planning pour aujourd'hui (synchro pas à jour), recopie celui d'un
                            jour passé sur aujourd'hui, dans la base de démo uniquement.
"""
import argparse
import heapq
import itertools
import os
import sys
import time as tm
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from sqlalchemy import text


def regler_poste_aujourdhui(db, maintenant: datetime) -> None:
    debut = max(datetime.combine(maintenant.date(), time(0, 0)), (maintenant - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0))
    fin = min(datetime.combine(maintenant.date(), time(23, 30)), debut + timedelta(hours=9))
    db.execute(text("DELETE FROM jours_speciaux WHERE date = :d"), {"d": maintenant.date()})
    db.execute(text("INSERT INTO jours_speciaux (date, type, heure_debut, heure_fin, pause_debut, pause_fin, commentaire) VALUES (:d, 'horaire_special', :a, :b, NULL, NULL, 'demo_live')"),
               {"d": maintenant.date(), "a": debut.time(), "b": fin.time()})
    db.commit()
    print(f"Horaire spécial d'aujourd'hui : {debut:%H:%M} -> {fin:%H:%M} (sans pause).")


def cloner_planning(db, source: date, aujourdhui: date, ligne_ids: list[int]) -> int:
    db.execute(text("DELETE FROM planning_detail_cache WHERE id >= :m AND jour = :j"), {"m": L.ID_CLONE_MIN, "j": aujourdhui})
    n0 = db.execute(text("SELECT COALESCE(MAX(id), :m) FROM planning_detail_cache WHERE id >= :m"), {"m": L.ID_CLONE_MIN}).scalar()
    rows = db.execute(text("""SELECT d.planning_id, d.ligne_id, d.produit_id, d.qty, d.colisage, d.contenance FROM planning_detail_cache d JOIN planning_cache p ON p.id = d.planning_id
                              WHERE p.etat = 'confirmed' AND d.jour = :s AND d.ligne_id = ANY(:l) ORDER BY d.id"""), {"s": source, "l": ligne_ids}).fetchall()
    for i, r in enumerate(rows, start=1):
        db.execute(text("INSERT INTO planning_detail_cache (id, planning_id, ligne_id, produit_id, jour, qty, colisage, contenance) VALUES (:i,:p,:l,:pr,:j,:q,:c,:ct)"),
                   {"i": n0 + i, "p": r.planning_id, "l": r.ligne_id, "pr": r.produit_id, "j": aujourdhui, "q": r.qty, "c": r.colisage, "ct": r.contenance})
    db.commit()
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8001")
    p.add_argument("--admin", default=os.getenv("DEMO_ADMIN_USER", "admin"))
    p.add_argument("--admin-password", default=os.getenv("DEMO_ADMIN_PASSWORD"))
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--graine", type=int, default=None, help="défaut : celle de la simulation d'historique")
    p.add_argument("--regler-poste", action="store_true")
    p.add_argument("--cloner-planning-depuis", type=date.fromisoformat)
    p.add_argument("--bonus-efficacite", type=float, default=1.10, help="multiplie l'efficacité des lignes (défaut 1,10 : une usine qui va plutôt bien ; 1,0 = profils bruts)")
    p.add_argument("--garder-fin-de-poste", action="store_true", help="conserver les opérateurs qui saisissent tout en fin de poste (sinon : saisie régulière)")
    p.add_argument("--sans-attente", action="store_true", help="rejoue seulement le passé de la journée puis s'arrête (tests)")
    p.add_argument("--vitesse", type=float, default=1.0, help="*** AJOUT 2026-09-25 *** : multiplie la vitesse d'écoulement du temps EN MODE DIRECT (2 = deux fois plus vite, 10 = un après-midi en quelques minutes). Les évènements sont toujours postés à l'heure RÉELLE où ils partent (pas de redatage) -- accélérer déplace donc simplement CE MOMENT plus tôt, ça ne triche pas sur l'horodatage affiché dans l'app. Défaut 1.0 = rythme réel, pensé pour une vraie démo en direct.")
    p.add_argument("--oui", action="store_true")
    a = p.parse_args()

    ref = L.charger_reference(a.reference)
    graine = a.graine if a.graine is not None else ref["meta"]["graine"]
    equipes = {int(k): v for k, v in ref["equipes"].items()}
    db = L.ouvrir_db(a.oui)
    api = L.Api(a.api)
    api.login(a.admin, a.admin_password)
    L.verifier_meme_base(api, db, a.admin)
    maintenant = datetime.now().replace(microsecond=0)
    aujourdhui = maintenant.date()
    L.creer_operateurs(api, db, a.admin, ref["operateurs"])

    if a.regler_poste:
        regler_poste_aujourdhui(db, maintenant)
    poste = L.poste_du_jour(db, aujourdhui)
    if not poste:
        sys.exit("Aujourd'hui est un jour fermé dans le Calendrier. Utilisez --regler-poste ou modifiez le Calendrier de la base de démo.")
    if a.cloner_planning_depuis:
        print(f"{cloner_planning(db, a.cloner_planning_depuis, aujourdhui, list(equipes))} items de planning recopiés du {a.cloner_planning_depuis} vers aujourd'hui.")
    planning = L.charger_planning(db, [aujourdhui])
    lignes, causes = L.charger_lignes(db), L.charger_causes(db)
    if not any(lid in equipes for (lid, _j) in planning):
        sys.exit("Aucun planning confirmé aujourd'hui pour les lignes simulées. Relancez avec --cloner-planning-depuis AAAA-MM-JJ.")
    if db.execute(text("SELECT COUNT(*) FROM palettes WHERE created_at::date = :d AND ligne_id = ANY(:l)"), {"d": aujourdhui, "l": list(equipes)}).scalar():
        sys.exit("Des palettes existent déjà aujourd'hui sur ces lignes : lancez nettoyer_demo.py --aujourdhui, puis recommencez.")

    futur, passe, compteur = [], [], itertools.count()
    for lid, mats in equipes.items():
        items = planning.get((lid, aujourdhui))
        if not items:
            continue
        pl = L.planifier_journee(graine, lignes[lid], aujourdhui, items, poste, mats, causes, bonus=a.bonus_efficacite,
                                 scan_force=None if a.garder_fin_de_poste else "regulier")
        for ev in pl["evenements"]:
            (passe if ev["ts"] <= maintenant else futur).append((ev["ts"], next(compteur), lignes[lid], ev))
    passe.sort(key=lambda x: x[:2])
    print(f"Aujourd'hui : {len({x[2]['id'] for x in passe + futur})} lignes actives | {len(passe)} évènements déjà passés, {len(futur)} à venir "
          f"({poste.debut:%H:%M} -> {poste.fin:%H:%M}).")

    # 1. Rattrapage : le début de journée est rejoué, daté aux heures simulées.
    seq, fils, ouverts = {}, [], {}
    for ts, _n, ligne, ev in passe:
        if ev["type"] == "arret" and ev["fin"] is not None and ev["fin"] > maintenant:
            # arrêt en cours à cet instant : démarré dans le passé, clôturé à l'heure prévue
            r = api.appel("POST", "/actions/arrets/demarrer", ev["operateur"], json={"ligne_id": ligne["id"], "cause_id": ev["cause"]["id"]}).json()
            db.execute(text("UPDATE arrets SET heure_debut = :t WHERE id = :i"), {"t": ev["ts"], "i": r["id"]}); db.commit()
            heapq.heappush(fils, (ev["fin"], next(compteur), "fin_arret", ligne, {**ev, "arret_id": r["id"]}))
            continue
        L.executer_evenement(api, db, ligne, ev, seq, redater=True)
    print(f"Rattrapage terminé : l'usine est à l'état de {maintenant:%H:%M}.")
    if a.sans_attente:
        return

    # 2. Direct : chaque évènement part à son heure, sans redatage (l'API date « maintenant », c'est la vérité).
    for ts, n, ligne, ev in futur:
        heapq.heappush(fils, (ts, n, "evt", ligne, ev))
    print("Mode direct (Ctrl-C pour arrêter)..." if a.vitesse == 1.0 else f"Mode direct, x{a.vitesse:g} (Ctrl-C pour arrêter)...")
    debut_direct = datetime.now()   # *** AJOUT 2026-09-25 *** : ancres pour --vitesse (temps virtuel = temps réel écoulé x vitesse)
    try:
        while fils:
            ts, _n, genre, ligne, ev = fils[0]
            virtuel = maintenant + (datetime.now() - debut_direct) * a.vitesse
            if ts > virtuel:
                attente = (ts - virtuel).total_seconds() / a.vitesse
                tm.sleep(min(2.0, max(0.0, attente))); continue
            heapq.heappop(fils)
            if genre == "fin_arret":
                api.appel("POST", f"/actions/arrets/{ev['arret_id']}/terminer", ev["operateur"])
                print(f"{datetime.now():%H:%M:%S}  {ligne['code']:<8} reprise après arrêt ({ev['cause']['libelle']})")
            elif ev["type"] == "palette":
                L.executer_evenement(api, db, ligne, ev, seq, redater=False)
                print(f"{datetime.now():%H:%M:%S}  {ligne['code']:<8} palette {ev['cartons'] * ev['colisage']} pièces ({'partielle' if not ev['complete'] else 'complète'})")
            else:
                r = api.appel("POST", "/actions/arrets/demarrer", ev["operateur"], json={"ligne_id": ligne["id"], "cause_id": ev["cause"]["id"]}).json()
                print(f"{datetime.now():%H:%M:%S}  {ligne['code']:<8} ARRÊT : {ev['cause']['libelle']}")
                if ev["fin"] is not None:
                    heapq.heappush(fils, (ev["fin"], next(compteur), "fin_arret", ligne, {**ev, "arret_id": r["id"]}))
        print("Fin de la journée simulée.")
    except KeyboardInterrupt:
        print("\nArrêt demandé. (Un arrêt éventuellement en cours reste ouvert : utilisez demo_actions.py reprise CODE.)")


if __name__ == "__main__":
    main()