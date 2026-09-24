#!/usr/bin/env python3
"""
run_vusine_sync.py -- Script autonome de synchro Odoo -> Vusine.

Usage :
    python3 run_vusine_sync.py [--mode rapide|historique]
        Un seul passage de synchro, puis quitte.

        --mode rapide (défaut) : synchroniser_tout() -- lignes, produits, OF, cadence,
        planning, OF enrichis (fenêtre 30j sur write_date). C'est le mode à utiliser en
        cron fréquent (ex: toutes les 10 min).

        --mode full : vide UNIQUEMENT les tables cache Odoo SANS AUCUN dépendant réel
        (cadence_reference, saisies_production_cache, formules_cache,
        stock_matieres_cache, labo_formules_explosion, labo_ecarts_inventaire,
        labo_fournisseurs_matiere, sync_state), puis relance rapide + historique.
        JAMAIS lignes_cache/produits_cache/of_cache/planning_cache/planning_detail_cache/
        corrections_cache : ces six-là sont référencées par `palettes` (of_id legacy,
        planning_detail_id courant) -- un TRUNCATE dessus échoue (Postgres refuse de
        tronquer une table référencée par FK sans CASCADE) et un CASCADE viderait de
        vraies données terrain (palettes, alertes, réceptions magasin). Elles restent
        gérées par upsert seul, rafraîchies par la resynchro qui suit ce vidage.
        Usage rare -- utile pour repartir d'un cache incohérent sans passer par un
        reset complet de la base (reset_vusinedb_dev.sh, séparé).
        production_date, pas write_date) + resynchro complète des référentiels du
        chantier Labo (saisies_production_cache, corrections_cache,
        labo_formules_explosion, stock_matieres_cache, labo_ecarts_inventaire,
        labo_fournisseurs_matiere). À lancer une fois par nuit (le scheduler intégré le
        fait automatiquement à 2h30 si ODOO_SYNC_SCHEDULER_ENABLED=True), ou à la main
        pour un premier remplissage avant de tester les écrans du Labo.

        *** DIFFÉRENCE AVEC run_sivox_etl.py (--mode full/inc) *** : Vusine n'a PAS de
        staging + DWH séparés et reconstructibles -- une seule base métier, alimentée
        par upsert direct sur les tables finales. Il n'existe donc PAS d'équivalent à
        "--mode full" (DROP + reconstruction complète) : "rapide" et "historique" ne
        se distinguent que par la fenêtre temporelle et le périmètre des tables
        touchées, jamais par une suppression préalable.

    python3 run_vusine_sync.py --loop
        Tourne en continu, un passage toutes les ODOO_SYNC_INTERVAL_MINUTES (.env) --
        alternative au scheduler intégré. Applicable uniquement au mode rapide (le
        mode historique est pensé pour un passage nocturne unique, cf. scheduler.py) :
        --loop avec --mode historique est refusé.

Contrairement à run_sivox_etl.py (--mode full/inc/weekly), Vusine n'a que ces deux modes.

Ce script importe directement les modules de l'application (app.core.*, app.services.*)
-- il doit rester dans backend/scripts/, à côté de 01_auth_schema.sql/03_business_schema.sql/
04_labo_migration.sql, pour que le chemin relatif vers le package `app` soit correct.

NB (2026-09-17, migration audit CDC) : synchroniser_tout() ne touche que les tables
cache Odoo (lignes_cache, produits_cache, of_cache, cadence_reference, planning_cache,
planning_detail_cache). Les tables ajoutées par la migration audit CDC (configuration_poste,
jours_speciaux, palettes_corrections, alertes, receptions_magasin) et les colonnes ajoutées
(users.section_scope, arrets.neutralise_score, palettes.motif_partiel) sont toutes
saisies manuellement (tablette/admin) -- aucune n'est alimentée par Odoo.

*** AJOUT (chantier Labo, 22/09) *** : synchroniser_historique() touche des tables
supplémentaires (cf. 04_labo_migration.sql) -- toutes en lecture seule depuis Odoo,
jamais éditées à la main côté Vusine.
"""
import os
import sys
import time
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

from app.core.database import SessionLocal
from app.core.settings import settings
from app.services.odoo_sync_service import synchroniser_tout, synchroniser_historique, synchroniser_full, OdooSyncError


def run_once(mode: str):
    labels = {"rapide": "rapide", "historique": "HISTORIQUE (fenêtre profonde)",
              "full": "FULL (vidage caches + rapide + historique)"}
    print(f"=== Synchro Vusine <- Odoo ({labels[mode]}) -- {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    db = SessionLocal()
    t0 = time.time()
    try:
        if mode == "rapide":
            resultats = synchroniser_tout(db)
        elif mode == "historique":
            resultats = synchroniser_historique(db)
        else:
            resultats = synchroniser_full(db)
    except OdooSyncError as e:
        print(f"\n[ERREUR] {e}")
        return False
    finally:
        db.close()

    elapsed = time.time() - t0
    print(f"\n✅ Synchro terminée en {elapsed:.1f}s :")
    for table, count in resultats.items():
        print(f"   - {table} : {count}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Synchro Odoo -> Vusine (lecture seule).")
    parser.add_argument("--mode", choices=["rapide", "historique", "full"], default="rapide",
                         help="rapide (défaut, fenêtre 30j) / historique (fenêtre 180j + référentiels Labo) "
                              "/ full (vidage caches Odoo puis rapide+historique).")
    parser.add_argument("--loop", action="store_true",
                         help="Tourne en continu, un passage toutes les "
                              "ODOO_SYNC_INTERVAL_MINUTES (.env) -- Ctrl+C pour arrêter. "
                              "Mode rapide uniquement.")
    args = parser.parse_args()

    if args.loop and args.mode != "rapide":
        sys.exit(f"--loop n'est pas applicable au mode {args.mode!r} (pensé pour un passage "
                  "unique -- cf. scheduler.py).")

    if not args.loop:
        ok = run_once(args.mode)
        sys.exit(0 if ok else 1)

    intervalle_s = settings.ODOO_SYNC_INTERVAL_MINUTES * 60
    print(f"Mode --loop (rapide) : un passage toutes les {settings.ODOO_SYNC_INTERVAL_MINUTES} min. Ctrl+C pour arrêter.")
    try:
        while True:
            run_once("rapide")
            print(f"\nProchain passage dans {settings.ODOO_SYNC_INTERVAL_MINUTES} min...\n")
            time.sleep(intervalle_s)
    except KeyboardInterrupt:
        print("\nArrêté.")


if __name__ == "__main__":
    main()