"""
nettoyer_demo.py -- efface TOUT ce que les outils de démo ont créé (comptes DEMO***, leurs palettes, arrêts,
affectations, planning cloné, horaire spécial du jour). Ne touche jamais aux données non fictives.

  python scripts/demo/nettoyer_demo.py            # tout effacer
  python scripts/demo/nettoyer_demo.py --aujourdhui   # seulement la production d'aujourd'hui (pour relancer demo_live)
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from sqlalchemy import text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aujourdhui", action="store_true")
    p.add_argument("--oui", action="store_true")
    a = p.parse_args()
    db = L.ouvrir_db(a.oui)
    px = {"p": L.PREFIXE_MATRICULE + "%", "m": L.ID_CLONE_MIN, "d": date.today()}
    users = "(SELECT id FROM users WHERE matricule LIKE :p)"
    cond_j = " AND created_at::date = :d" if a.aujourdhui else ""
    cond_a = " AND heure_debut::date = :d" if a.aujourdhui else ""
    n = {}
    n["palettes"] = db.execute(text(f"DELETE FROM palettes WHERE operateur_id IN {users}{cond_j}"), px).rowcount
    n["arrêts"] = db.execute(text(f"DELETE FROM arrets WHERE operateur_id IN {users}{cond_a}"), px).rowcount
    n["horaire spécial"] = db.execute(text("DELETE FROM jours_speciaux WHERE commentaire = 'demo_live' AND date = :d"), px).rowcount if a.aujourdhui else db.execute(text("DELETE FROM jours_speciaux WHERE commentaire = 'demo_live'")).rowcount
    n["planning cloné"] = db.execute(text("DELETE FROM planning_detail_cache WHERE id >= :m" + (" AND jour = :d" if a.aujourdhui else "")), px).rowcount
    if not a.aujourdhui:
        db.execute(text(f"DELETE FROM suivi_individuel_acces WHERE user_id IN {users} OR consulte_par IN {users}"), px)
        n["affectations"] = db.execute(text(f"DELETE FROM affectations_ligne WHERE user_id IN {users}"), px).rowcount
        db.execute(text(f"DELETE FROM user_permissions WHERE user_id IN {users}"), px)
        n["comptes"] = db.execute(text("DELETE FROM users WHERE matricule LIKE :p"), px).rowcount
        db.execute(text("DELETE FROM params WHERE key = 'demo_sentinelle'"))
    db.commit()
    print("Supprimé :", ", ".join(f"{v} {k}" for k, v in n.items()))


if __name__ == "__main__":
    main()
