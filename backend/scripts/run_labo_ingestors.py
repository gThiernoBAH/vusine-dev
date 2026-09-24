#!/usr/bin/env python3
"""
run_labo_ingestors.py -- Lance les ingestors du chantier Labo (F1, F7, F8, F9, F10, F5),
en miroir de la façon dont SIVOX lance chacun de ses ingestors séparément
(`python3 -u -m app.services.ingestors.predict_ingestor`, etc.).

*** DEUX FAÇONS DE LES LANCER, les deux fonctionnent : ***

1. Un par un, exactement comme côté SIVOX (chaque fichier a son propre bloc
   `if __name__ == "__main__"`) -- utile pour tester ou relancer un seul domaine :

     python3 -u -m app.services.ingestors.labo_eligibilite_ingestor 2>&1 | tee logs/labo_eligibilite_ingestor.log
     python3 -u -m app.services.ingestors.labo_predict_ingestor 2>&1 | tee logs/labo_predict_ingestor.log
     python3 -u -m app.services.ingestors.labo_optimize_pp_ingestor --horizon-days 14 2>&1 | tee logs/labo_optimize_pp_ingestor.log
     python3 -u -m app.services.ingestors.labo_matiere_ingestor 2>&1 | tee logs/labo_matiere_ingestor.log
     python3 -u -m app.services.ingestors.labo_simulation_ingestor 2>&1 | tee logs/labo_simulation_ingestor.log
     python3 -u -m app.services.ingestors.labo_ecritures_ingestor 2>&1 | tee logs/labo_ecritures_ingestor.log

   *** L'ORDRE COMPTE *** si vous les lancez un par un : labo_eligibilite_ingestor
   D'ABORD (F1, base de F8), labo_predict_ingestor ENSUITE (F7, base de F8 et F9),
   PUIS labo_optimize_pp_ingestor et labo_matiere_ingestor (qui dépendent de F7).
   labo_simulation_ingestor et labo_ecritures_ingestor sont indépendants, n'importe
   quand.

2. Ce script (scripts/run_labo_ingestors.py), qui les enchaîne dans le bon ordre en
   UNE commande -- recommandé pour un premier remplissage ou un lancement manuel
   complet (c'est ce que fait le scheduler nocturne automatiquement à 3h00) :

     python3 -u -m scripts.run_labo_ingestors 2>&1 | tee logs/run_labo_ingestors.log
     python3 -u -m scripts.run_labo_ingestors --only capacite,previsions  # sous-ensemble

*** PRÉREQUIS *** : ce script lit les tables synchronisées par
`python3 -u -m scripts.run_vusine_sync --mode historique` (of_cache avec
production_date, formules explosées, stock matières...). Sans un passage --mode
historique au moins une fois, les tables labo resteront vides (comme sur la capture
"Aucune capacité démontrée pour l'instant.").
"""
import os
import sys
import argparse
import logging
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from app.core.database import SessionLocal
from app.services.ingestors import (
    labo_eligibilite_ingestor, labo_predict_ingestor, labo_optimize_pp_ingestor,
    labo_matiere_ingestor, labo_simulation_ingestor, labo_ecritures_ingestor,
    labo_emballage_ingestor,
)

# Ordre de dépendance -- respecté même avec --only (les étapes demandées gardent leur
# position relative dans cette liste, jamais l'ordre donné en argument).
ETAPES = [
    ("capacite", "Capacité démontrée + éligibilité des lignes (F1, base de F8)",
     labo_eligibilite_ingestor.run_eligibilite_cycle),
    ("previsions", "Prévision de volume (F7, Prophet)",
     labo_predict_ingestor.run_predict_cycle),
    ("plan", "Plan de production optimisé (F8, MILP -- dépend de capacite + previsions)",
     labo_optimize_pp_ingestor.run_optimize_cycle),
    ("matieres", "Besoins matières et alertes d'achat (F9 -- dépend de previsions)",
     labo_matiere_ingestor.run_matiere_cycle),
    ("emballage", "Alertes emballage priorisées (F6 -- dépend de matieres/F9b)",
     lambda db: {"alertes_emballage": labo_emballage_ingestor.recalculer_alertes_emballage(db)}),
    ("simulation", "Simulation stock -> produits finis (F10)",
     lambda db: {"simulation_productible": labo_simulation_ingestor.recalculer_simulation_productible(db)}),
    ("ecritures", "Écritures proposées vers Odoo + comparaison (F5, export)",
     labo_ecritures_ingestor.run_ecritures_cycle),
]


def main():
    parser = argparse.ArgumentParser(description="Enchaîne les ingestors du Labo, dans l'ordre de dépendance.")
    parser.add_argument("--only", type=str, default=None,
                         help="Sous-ensemble d'étapes, séparées par virgule (ex: 'capacite,previsions'). "
                              "Sans cet argument, toutes les étapes sont lancées.")
    args = parser.parse_args()

    demandees = set(args.only.split(",")) if args.only else None
    if demandees:
        inconnues = demandees - {cle for cle, _, _ in ETAPES}
        if inconnues:
            sys.exit(f"Étape(s) inconnue(s) : {sorted(inconnues)}. Choix possibles : "
                      f"{[cle for cle, _, _ in ETAPES]}")

    print(f"=== Ingestors Labo -- {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    db = SessionLocal()
    resultats = {}
    try:
        for cle, description, fonction in ETAPES:
            if demandees and cle not in demandees:
                continue
            print(f"\n--- {cle} : {description} ---")
            try:
                resultats[cle] = fonction(db)
                print(f"✅ {cle} : {resultats[cle]}")
            except Exception as e:
                logger.error(f"[LABO INGESTORS] Échec sur '{cle}' : {e}", exc_info=True)
                resultats[cle] = f"échec : {e}"
                # *** CORRIGÉ 2026-09-22 (erreur réelle en prod) *** : sans rollback,
                # la session reste dans un état "PendingRollbackError" et TOUTE étape
                # suivante échoue en cascade, même sans rapport avec l'échec initial
                # (confirmé : l'étape 'ecritures' a échoué à cause de l'échec de
                # 'simulation' juste avant, alors que les deux sont indépendantes).
                db.rollback()
    finally:
        db.close()

    print(f"\n=== Terminé : {resultats} ===")


if __name__ == "__main__":
    main()