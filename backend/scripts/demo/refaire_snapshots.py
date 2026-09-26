"""refaire_snapshots.py -- *** AJOUT 2026-09-25 ***, script PONCTUEL à lancer UNE FOIS après
avoir remplacé snapshot_service.py par la version corrigée (cf. son docstring pour le détail
du bug : reel figé à 0 pour un jour passé, calculé avec l'heure d'AUJOURD'HUI au lieu de
`jour`).

Les 15 jours simulés ont déjà un snapshot dans performance_ligne_jour, mais écrit avec
l'ANCIEN code buggé. Ce script les recalcule avec le nouveau code, sans rejouer toute la
simulation (simuler_historique.py). Idempotent : relançable sans risque, met juste à jour
les lignes déjà présentes.

  cd backend
  DEMO_ADMIN_PASSWORD='...' python scripts/demo/refaire_snapshots.py
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_lib as L
from app.services.snapshot_service import snapshoter_performance_du_jour


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reference", default="demo_reference.json")
    p.add_argument("--oui", action="store_true")
    a = p.parse_args()

    ref = L.charger_reference(a.reference)
    jours = sorted(ref["meta"]["jours"])
    db = L.ouvrir_db(a.oui)

    for j in jours:
        snapshoter_performance_du_jour(db, date.fromisoformat(j))
    print(f"{len(jours)} jour(s) recalculé(s) dans performance_ligne_jour : {jours[0]} -> {jours[-1]}.")


if __name__ == "__main__":
    main()