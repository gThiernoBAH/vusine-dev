"""configurer_valeurs_demo.py -- *** AJOUT 2026-09-25 *** : renseigne les valeurs FCFA
("Rapports -> Pareto des arrêts", coût estimé) pour que la démo affiche des chiffres au
lieu de "n/d". Sans ce script, PERSONNE n'a de valeur configurée (ni le paramètre par
défaut, ni aucun produit) -- comportement volontaire de l'application ("aucune valeur
inventée sans que quelqu'un l'ait explicitement configurée", cf. config_admin_routes.py),
donc rien ne se remplit tout seul en simulant de l'historique.

Deux choses, dans cet ordre (celui que l'écran Administration -> Paramètres explique) :
  1. Une valeur PAR DÉFAUT (valeur_piece_defaut_fcfa), qui s'applique à tout produit sans
     valeur propre -- suffit à elle seule pour que "Coût estimé" cesse d'afficher "n/d".
  2. Une valeur PROPRE à une partie des produits finis confirmés, pour un Pareto plus
     réaliste (tous les produits n'ont pas le même prix) -- déterministe (graine
     -config-valeurs), rejouable comme le reste des scripts de démo. VOLONTAIREMENT
     PAS TOUS LES PRODUITS : dans la vraie vie, tout n'est pas valorisé individuellement
     non plus, le reste retombant sur la valeur par défaut -- comportement qu'il est utile
     de voir aussi en démo.

  cd backend
  python scripts/demo/configurer_valeurs_demo.py                     # défaut 150 FCFA/pièce
  python scripts/demo/configurer_valeurs_demo.py --defaut 200 --part-produits 0.6
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from app.core import crud
from app.models.production import ProduitCache
from sqlalchemy import text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--defaut", type=float, default=150.0, help="valeur par défaut en FCFA/pièce (défaut : 150)")
    p.add_argument("--part-produits", type=float, default=0.5,
                   help="fraction des produits finis confirmés qui reçoivent une valeur PROPRE, le reste retombant sur --defaut (défaut : 0.5)")
    p.add_argument("--min", dest="mini", type=float, default=60.0, help="borne basse des valeurs propres, en FCFA/pièce (défaut : 60)")
    p.add_argument("--max", dest="maxi", type=float, default=650.0, help="borne haute des valeurs propres, en FCFA/pièce (défaut : 650)")
    p.add_argument("--graine", type=int, default=None, help="défaut : celle de la simulation d'historique (demo_reference.json)")
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--oui", action="store_true")
    a = p.parse_args()

    db = L.ouvrir_db(a.oui)
    graine = a.graine
    if graine is None:
        try:
            graine = L.charger_reference(a.reference)["meta"]["graine"]
        except FileNotFoundError:
            graine = 0   # pas de simulation d'historique lancée -- la répétabilité n'a alors pas d'importance

    crud.set_param(db, "valeur_piece_defaut_fcfa", str(a.defaut))
    db.commit()
    print(f"Valeur par défaut : {a.defaut:g} FCFA/pièce.")

    produits = db.query(ProduitCache).filter(ProduitCache.confirme_produit_fini.is_(True)).order_by(ProduitCache.id).all()
    r = random.Random(f"{graine}-valeurs-produits")
    n = 0
    for prod in produits:
        if r.random() < a.part_produits:
            valeur = round(r.uniform(a.mini, a.maxi), -1)  # arrondi à la dizaine, plus lisible dans le tableau
            db.execute(text("UPDATE produits_cache SET valeur_unitaire_fcfa = :v WHERE id = :i"), {"v": valeur, "i": prod.id})
            n += 1
    db.commit()
    print(f"{n}/{len(produits)} produit(s) fini(s) confirmé(s) avec une valeur propre ({a.mini:g}-{a.maxi:g} FCFA/pièce) ;"
          f" les {len(produits) - n} autres retombent sur la valeur par défaut.")
    print("Vérifiez sur Rapports -> Pareto des arrêts : \"Coût estimé\" doit maintenant afficher un montant.")


if __name__ == "__main__":
    main()