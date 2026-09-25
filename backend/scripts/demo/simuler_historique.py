"""
simuler_historique.py -- fait travailler des opérateurs FICTIFS sur plusieurs jours d'historique.

  cd backend
  DATABASE_URL=postgresql://.../vusine_demo  python scripts/demo/simuler_historique.py \\
      --api http://localhost:8001 --admin admin --admin-password '***' --jours 15

Ce que fait le script :
  1. crée N opérateurs fictifs (matricules DEMO001...) et l'équipe de chaque ligne (écran d'affectation en masse) ;
  2. pour chaque jour et chaque ligne planifiée dans Odoo : arrêts, changements de série, palettes partielles,
     rebuts, erreurs de saisie -- le tout envoyé par la VRAIE API (comme la tablette) puis daté à l'heure simulée ;
  3. écrit demo_reference.json : ce qui a été simulé, à comparer ensuite avec le cockpit (verifier_coherence.py).

  --a-blanc  : calcule et résume le scénario sans rien écrire ni appeler l'API (à lancer en premier).
"""
import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from sqlalchemy import text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8001")
    p.add_argument("--admin", default=os.getenv("DEMO_ADMIN_USER", "admin"))
    p.add_argument("--admin-password", default=os.getenv("DEMO_ADMIN_PASSWORD"))
    p.add_argument("--jours", type=int, default=15, help="nombre de jours ouvrés d'historique (défaut 15)")
    p.add_argument("--fin", type=date.fromisoformat, default=date.today() - timedelta(days=1), help="dernier jour simulé (défaut hier)")
    p.add_argument("--du", type=date.fromisoformat, help="forcer le premier jour (sinon : les N derniers jours planifiés)")
    p.add_argument("--max-lignes", type=int, default=40, help="nombre maximal de lignes simulées (défaut 40)")
    p.add_argument("--operateurs", type=int, default=40, help="taille du pool d'opérateurs fictifs (défaut 40)")
    p.add_argument("--graine", type=int, default=42, help="même graine = même scénario, rejouable")
    p.add_argument("--jour-sans-scan", type=date.fromisoformat, help="un jour où personne ne saisit (test de l'avertissement « aucun scan »)")
    p.add_argument("--arret-oublie", action="store_true", help="un arrêt jamais clôturé sur une ligne, le dernier jour")
    p.add_argument("--bonus-efficacite", type=float, default=1.0, help="multiplie l'efficacité des lignes (1,0 = profils bruts ; 1,1 pour une usine plus à l'aise)")
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--a-blanc", action="store_true")
    p.add_argument("--oui", action="store_true", help="ne pas demander la confirmation")
    a = p.parse_args()

    db = L.ouvrir_db(a.oui or a.a_blanc)
    lignes = L.charger_lignes(db)
    jours = L.jours_de_reference(db, a.jours, a.fin) if not a.du else [j for j in (a.du + timedelta(days=i) for i in range((a.fin - a.du).days + 1)) if L.poste_du_jour(db, j)]
    if not jours:
        sys.exit("Aucun jour avec planning confirmé trouvé : la synchronisation Odoo a-t-elle tourné ? (voir --du / --fin)")
    planning = L.charger_planning(db, jours)
    nb_jours_par_ligne = Counter(lid for (lid, _j) in planning)
    retenues = [lid for lid, _n in sorted(nb_jours_par_ligne.items(), key=lambda kv: (-kv[1], lignes[kv[0]]["code"]))[: a.max_lignes]]
    causes = L.charger_causes(db)
    ops, equipes = L.constituer_equipes(a.graine, retenues, a.operateurs)
    print(f"Période : {jours[0]} -> {jours[-1]} ({len(jours)} jours ouvrés) | {len(retenues)} lignes sur {len(lignes)} | {len(ops)} opérateurs fictifs")
    if len(jours) < a.jours:
        print(f"  (attention : seulement {len(jours)} jours planifiés trouvés sur les {a.jours} demandés)")

    # -- scénario complet, calculé sans effet de bord
    plans = []
    for jour in jours:
        poste = L.poste_du_jour(db, jour)
        for lid in retenues:
            items = planning.get((lid, jour))
            if not items:
                continue
            plans.append((lignes[lid], jour, L.planifier_journee(
                a.graine, lignes[lid], jour, items, poste, equipes[lid], causes,
                sans_scan=(a.jour_sans_scan == jour), bonus=a.bonus_efficacite, arret_oublie=(a.arret_oublie and jour == jours[-1] and lid == retenues[0]))))
    cel = [pl["cellule"] for _l, _j, pl in plans]
    print(f"Scénario : {len(cel)} journées-lignes | {sum(c['nb_palettes'] for c in cel)} palettes | {sum(len(c['arrets']) for c in cel)} arrêts | "
          f"{sum(c['rejets_attendus'] for c in cel)} saisies erronées | {sum(c['changements_serie'] for c in cel)} changements de série")
    print("Profils des lignes :", dict(Counter(L.profil_ligne(a.graine, lid)["niveau"] for lid in retenues)))
    if a.a_blanc:
        print("\n--a-blanc : rien n'a été écrit.")
        return

    if not a.admin_password:
        sys.exit("Mot de passe admin manquant (--admin-password ou DEMO_ADMIN_PASSWORD).")
    api = L.Api(a.api)
    api.login(a.admin, a.admin_password)
    L.verifier_meme_base(api, db, a.admin)

    # -- garde-fou : ne jamais écraser de la vraie production sur ces lignes / jours
    deja = db.execute(text("SELECT COUNT(*) FROM palettes p JOIN users u ON u.id = p.operateur_id WHERE p.ligne_id = ANY(:l) AND p.created_at::date = ANY(:j) AND u.matricule NOT LIKE :pf"),
                      {"l": retenues, "j": jours, "pf": L.PREFIXE_MATRICULE + "%"}).scalar()
    if deja:
        sys.exit(f"REFUS : {deja} palettes non fictives existent déjà sur ces lignes et ces jours. Choisissez une autre période (--fin / --du).")
    db.execute(text("DELETE FROM performance_ligne_jour WHERE ligne_id = ANY(:l) AND jour = ANY(:j)"), {"l": retenues, "j": jours})   # snapshots éventuels : ils fausseraient la comparaison
    db.commit()

    ids = L.creer_operateurs(api, db, a.admin, ops)
    n = L.affecter_equipes(api, db, a.admin, equipes, ids, datetime.combine(jours[0] - timedelta(days=1), datetime.min.time()))
    print(f"{len(ids)} comptes opérateurs prêts, {n} affectations créées (date de début remontée au {jours[0] - timedelta(days=1)}).")

    seq, faits, rejets = {}, Counter(), 0
    for i, (ligne, jour, pl) in enumerate(plans, start=1):
        for ev in pl["evenements"]:
            faits[L.executer_evenement(api, db, ligne, ev, seq, redater=True)] += 1
        rejets += pl["cellule"]["rejets_attendus"]
        if i % 25 == 0 or i == len(plans):
            print(f"  {i}/{len(plans)} journées-lignes ({faits['palette']} palettes, {faits['arret']} arrêts)")

    # *** AJOUT 2026-09-25 *** : la Vue Usine et l'Andon ne recalculent JAMAIS un jour
    # passé -- ils lisent le snapshot figé de performance_ligne_jour (écrit chaque soir
    # par le scheduler, cf. app/services/snapshot_service.py). Ce scheduler est désactivé
    # pendant la démo (SNAPSHOT_SCHEDULER_ENABLED=False, pour ne rien envoyer vers
    # l'extérieur) : sans ce rattrapage, "Vue Usine -> jour passé" afficherait "Inactif"
    # partout alors que la simulation a bien écrit des données (découvert le 2026-09-25).
    from app.services.snapshot_service import snapshoter_performance_du_jour
    for jour in jours:
        snapshoter_performance_du_jour(db, jour)
    print(f"{len(jours)} jour(s) figé(s) dans performance_ligne_jour (Vue Usine/Andon consultables sur ces dates).")

    meta = {"graine": a.graine, "genere_le": datetime.now().isoformat(timespec="seconds"), "jours": [j.isoformat() for j in jours],
            "rejets_attendus": rejets, "api": a.api}
    L.sauver_reference(a.reference, meta, cel, ops, equipes)
    print(f"\nTerminé : {faits['palette']} palettes, {faits['arret']} arrêts, {rejets} saisies erronées refusées par le serveur.")
    print(f"Référence écrite : {a.reference}  ->  lancez maintenant verifier_coherence.py")


if __name__ == "__main__":
    main()