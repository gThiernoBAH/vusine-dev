"""
demo_actions.py -- déclencher UNE action à la main pendant la démo (depuis un second terminal).

  python scripts/demo/demo_actions.py arret CCL04 --cause "Manque MP"   # la ligne passe en arrêt sur l'Andon
  python scripts/demo/demo_actions.py reprise CCL04                       # elle repart
  python scripts/demo/demo_actions.py palette CCL04 [--partielle]         # un scan de palette, maintenant
  python scripts/demo/demo_actions.py etat                                # ce que voit l'Andon, en texte

Comme l'opérateur de la tablette : connexion avec le matricule de l'équipe de la ligne, puis appels de la vraie API.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from sqlalchemy import text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["arret", "reprise", "palette", "etat"])
    p.add_argument("ligne", nargs="?")
    p.add_argument("--cause", default="Panne machine")
    p.add_argument("--partielle", action="store_true")
    p.add_argument("--api", default="http://localhost:8001")
    p.add_argument("--admin", default=os.getenv("DEMO_ADMIN_USER", "admin"))
    p.add_argument("--admin-password", default=os.getenv("DEMO_ADMIN_PASSWORD"))
    p.add_argument("--reference", default="demo_reference.json")
    a = p.parse_args()

    db = L.ouvrir_db(True)
    api = L.Api(a.api)
    api.login(a.admin, a.admin_password)
    L.verifier_meme_base(api, db, a.admin)
    if a.action == "etat":
        d = api.appel("GET", "/dashboard/andon", a.admin).json()
        print(f"Performance {d['resume']['performance_usine_pct']} % | arrêt {d['resume']['lignes_a_larret']} | critique {d['resume']['lignes_rouges']} | retard {d['resume']['lignes_orange']} | ok {d['resume']['lignes_vertes']}")
        for l in d["lignes"]:
            if l["statut"] != "inactif":
                print(f"  {l['code']:<8}{l['statut']:<10}{l['performance_pct'] if l['performance_pct'] is not None else '-':>5} %  {l['arret_cause'] or ''}")
        return
    if not a.ligne:
        sys.exit("Indiquez le code de la ligne (ex. CCL04).")
    ref = L.charger_reference(a.reference)
    ligne = db.execute(text("SELECT id, code FROM lignes_cache WHERE upper(code) = upper(:c)"), {"c": a.ligne}).fetchone()
    if not ligne:
        sys.exit(f"Ligne {a.ligne} inconnue.")
    mats = ref["equipes"].get(str(ligne.id))
    if not mats:
        sys.exit(f"{ligne.code} n'a pas d'équipe fictive (ligne non simulée).")
    op = mats[0]
    api.login(op, L.MOT_DE_PASSE_DEMO)
    if a.action == "arret":
        cause = db.execute(text("SELECT id FROM causes_arret WHERE lower(libelle) = lower(:l)"), {"l": a.cause}).scalar()
        if not cause:
            sys.exit(f"Cause « {a.cause} » inconnue.")
        api.appel("POST", "/actions/arrets/demarrer", op, json={"ligne_id": ligne.id, "cause_id": cause})
        print(f"{ligne.code} : arrêt démarré ({a.cause}).")
    elif a.action == "reprise":
        en_cours = api.appel("GET", "/actions/arrets/en-cours", op, params={"ligne_id": ligne.id}).json()
        if not en_cours:
            sys.exit(f"{ligne.code} n'a pas d'arrêt en cours.")
        api.appel("POST", f"/actions/arrets/{en_cours['id']}/terminer", op)
        print(f"{ligne.code} : reprise.")
    else:
        item = db.execute(text("""SELECT d.id, pr.colisage_par_carton c, pr.cartons_par_palette k FROM planning_detail_cache d JOIN planning_cache p ON p.id = d.planning_id
                                  LEFT JOIN produits_cache pr ON pr.id = d.produit_id WHERE d.ligne_id = :l AND d.jour = CURRENT_DATE AND p.etat = 'confirmed' ORDER BY d.id LIMIT 1"""), {"l": ligne.id}).fetchone()
        col, cartons = (item.c or 12) if item else 12, (item.k or 50) if item else 50
        if a.partielle:
            cartons = max(1, cartons // 3)
        api.appel("POST", "/actions/palettes", op, json={"ligne_id": ligne.id, "planning_detail_id": item.id if item else None, "numero_lot": "DEMO-MANUEL", "nb_cartons": cartons,
                                                         "colisage_carton": col, "complete": not a.partielle, "motif_partielle": "Démo" if a.partielle else None})
        print(f"{ligne.code} : palette de {cartons * col} pièces enregistrée.")


if __name__ == "__main__":
    main()
