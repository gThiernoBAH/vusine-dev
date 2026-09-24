"""
labo_optimize_pp_ingestor.py -- Plan de production optimisé [F8], portage direct de
app/services/ingestors/optimize_pp_ingestor.py (SIVOX) -- même modèle mathématique
(programme linéaire, PuLP), adapté à l'échelle et aux tables Vusine.

*** NE REMPLACE JAMAIS LE PLANNING ODOO/SIVOP *** : Vusine reste en lecture seule sur
Odoo (F5 non implémenté). F8 est une RECOMMANDATION affichée à côté du planning réel,
jamais écrite nulle part côté Odoo.

Différences avec l'original SIVOX :
  - Couples (produit, ligne) faisables : dwh.config_capacite_ligne_produit (SIVOX,
    déclaratif) -> labo_lignes_eligibles_produit x labo_capacite_ligne_produit (Vusine,
    déduit de l'historique réel -- product_section_id vide à 100% sur les produits
    finis, cf. labo_eligibilite_ingestor.py).
  - Score de priorité (vw_priorite_fabrication, SIVOX) -> AUCUN équivalent chez Vusine
    en V1. Objectif neutre (chaque unité de déficit pèse pareil). Interface prête pour
    un score futur si l'un apparaît (valeur marchande, criticité client...).
  - Demande prévue (dwh.forecast_cache, SIVOX Prophet) -> labo_prevision_volume (F7,
    labo_predict_ingestor.py, ce même répertoire), au grain PRODUIT depuis le 23/09 :
    c'est ce modèle qui répartit la demande d'un produit entre ses lignes éligibles.
  - Stock/stock de sécurité produit fini : AUCUNE notion chez Vusine (pas de gestion de
    stock de produits finis dans le périmètre CDC). Modèle simplifié en conséquence :
    pas de variable stock/deficit cumulé, l'objectif porte directement sur l'écart
    entre demande prévue et ce qui est planifiable CE JOUR-LÀ (pas de report d'un jour
    sur l'autre).
"""
import logging
from collections import defaultdict
from datetime import date, timedelta

import pulp
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ...models.production import PlanOptimise, PrevisionVolume

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_DAYS = 14


def _load_eligibilite(db: Session) -> list[dict]:
    rows = db.execute(sqltext("""
        SELECT e.produit_id, e.ligne_id, c.p90_jour AS capacite_max_jour
        FROM labo_lignes_eligibles_produit e
        LEFT JOIN labo_capacite_ligne_produit c ON c.ligne_id = e.ligne_id AND c.produit_id = e.produit_id
        WHERE c.p90_jour IS NOT NULL AND c.p90_jour > 0
    """)).mappings().fetchall()
    return [dict(r) for r in rows]


def _load_prevision(db: Session, produit_ids: list[int], horizon_start: date, horizon_end: date) -> dict:
    if not produit_ids:
        return {}
    rows = db.query(PrevisionVolume).filter(
        PrevisionVolume.produit_id.in_(produit_ids),
        PrevisionVolume.jour_horizon >= horizon_start,
        PrevisionVolume.jour_horizon <= horizon_end,
    ).all()
    demande = defaultdict(float)
    for r in rows:
        # *** CORRIGÉ 2026-09-23 *** : "+=" et non "=". Tant que F7 était au grain
        # (ligne, produit), un produit fabriqué sur plusieurs lignes voyait chaque
        # prévision écraser la précédente -> demande sous-estimée. F7 est désormais au
        # grain produit (une seule ligne par produit et par jour) ; le += reste correct
        # et protège contre tout retour à un grain plus fin.
        demande[(r.produit_id, r.jour_horizon)] += float(r.qte_prevue or 0)
    return demande


def build_and_solve(db: Session, horizon_days: int = DEFAULT_HORIZON_DAYS):
    """Retourne (solution, deficit_solution, saturation, meta) -- même esprit de
    retour que l'original SIVOX, réduit à ce qui est exploitable ici (pas de
    deficit_motif textuel en V1 : F4, l'explication à la demande, s'en charge quand
    elle sera branchée sur cet écran)."""
    eligibilite = _load_eligibilite(db)
    if not eligibilite:
        logger.warning("[LABO OPTIMIZE PP] Aucun couple (produit, ligne) éligible avec capacité connue -- rien à optimiser.")
        return [], [], {}, {"status": "no_capacity_data"}

    produit_ids = sorted({r["produit_id"] for r in eligibilite})
    horizon_start = date.today()
    horizon_end = horizon_start + timedelta(days=horizon_days - 1)
    horizon = [horizon_start + timedelta(days=i) for i in range(horizon_days)]

    demande = _load_prevision(db, produit_ids, horizon_start, horizon_end)

    lignes_par_produit = defaultdict(list)
    for r in eligibilite:
        lignes_par_produit[r["produit_id"]].append((r["ligne_id"], float(r["capacite_max_jour"])))
    produits_par_ligne = defaultdict(list)
    for r in eligibilite:
        produits_par_ligne[r["ligne_id"]].append((r["produit_id"], float(r["capacite_max_jour"])))

    prob = pulp.LpProblem("vusine_plan_production", pulp.LpMinimize)

    # x[p, l, j] : quantité recommandée du produit p, sur la ligne l, au jour j.
    x = {}
    for p in produit_ids:
        for ligne_id, cap in lignes_par_produit[p]:
            for j in horizon:
                x[(p, ligne_id, j)] = pulp.LpVariable(f"x_{p}_{ligne_id}_{j.isoformat()}", lowBound=0)

    # deficit[p, j] : écart entre demande prévue et ce qui a pu être affecté ce jour-là.
    deficit = {p: {j: pulp.LpVariable(f"deficit_{p}_{j.isoformat()}", lowBound=0) for j in horizon} for p in produit_ids}

    # Contrainte de capacité partagée : une ligne, un jour, plusieurs produits possibles.
    lignes_vues = {(ligne_id, j) for p in produit_ids for ligne_id, _ in lignes_par_produit[p] for j in horizon}
    contraintes_capacite = {}
    for ligne_id, j in lignes_vues:
        # *** CORRIGÉ 2026-09-22 (erreur réelle : TypeError 'LpVariable' / 'float') ***
        # LpVariable n'implémente PAS __truediv__ -- seule la multiplication par une
        # constante est supportée par PuLP. x / cap doit s'écrire x * (1.0 / cap).
        contr = pulp.lpSum(
            x[(p, l, j)] * (1.0 / cap) for p in produit_ids for l, cap in lignes_par_produit[p] if l == ligne_id
        ) <= 1
        contr.name = f"capacite_{ligne_id}_{j.isoformat()}"
        prob += contr
        contraintes_capacite[(ligne_id, j)] = contr

    for p in produit_ids:
        for j in horizon:
            production_j = pulp.lpSum(x[(p, l, j)] for l, _ in lignes_par_produit[p])
            demande_j = demande.get((p, j), 0.0)
            prob += deficit[p][j] >= demande_j - production_j, f"deficit_{p}_{j.isoformat()}"

    # Objectif neutre en V1 (cf. docstring module) -- pas de score de priorité chez Vusine.
    prob += pulp.lpSum(deficit[p][j] for p in produit_ids for j in horizon)

    solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    logger.info(f"[LABO OPTIMIZE PP] Résolution : statut={status}, {len(produit_ids)} produits, horizon={horizon_days}j.")

    solution = []
    for (p, ligne_id, j), var in x.items():
        qty = var.value() or 0.0
        if qty > 0.01:  # seuil de bruit numérique du solveur, pas une vraie quantité
            solution.append({"produit_id": p, "ligne_id": ligne_id, "jour": j, "quantite_recommandee": round(qty, 2)})

    deficit_solution = []
    for p in produit_ids:
        for j in horizon:
            d = deficit[p][j].value() or 0.0
            if d > 0.01:
                deficit_solution.append({"produit_id": p, "jour": j, "deficit_qty": round(d, 2)})

    # Duales -- modèle 100% continu, directement fiables (même remarque que SIVOX).
    SEUIL_SATURATION_PCT = 99.9
    saturation = {}
    for ligne_id, j in lignes_vues:
        taux = 100.0 * sum(
            (x[(p, ligne_id, j)].value() or 0.0) / cap
            for p, cap in produits_par_ligne[ligne_id] if (p, ligne_id, j) in x
        )
        contr = contraintes_capacite.get((ligne_id, j))
        dual = contr.pi if contr is not None else None
        saturation[(ligne_id, j)] = round(dual / 100.0, 6) if (dual is not None and taux >= SEUIL_SATURATION_PCT) else None

    return solution, deficit_solution, saturation, {
        "status": status, "horizon_days": horizon_days, "nb_produits": len(produit_ids),
    }


def _upsert_plan(db: Session, solution: list[dict], deficit_solution: list[dict]):
    db.query(PlanOptimise).delete()
    for r in solution:
        db.add(PlanOptimise(
            ligne_id=r["ligne_id"], produit_id=r["produit_id"], jour=r["jour"],
            qte_recommandee=r["quantite_recommandee"], deficit_residuel=0,
        ))
    produits_couverts = {(r["produit_id"], r["jour"]) for r in solution}
    for d in deficit_solution:
        cle = (d["produit_id"], d["jour"])
        if cle not in produits_couverts:
            db.add(PlanOptimise(ligne_id=None, produit_id=d["produit_id"], jour=d["jour"],
                                 qte_recommandee=0, deficit_residuel=d["deficit_qty"]))
    db.commit()


def run_optimize_cycle(db: Session, horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    solution, deficit_solution, _saturation, meta = build_and_solve(db, horizon_days)
    if meta["status"] not in ("Optimal", "no_capacity_data"):
        logger.error(f"[LABO OPTIMIZE PP] Non résolu (statut={meta['status']}) -- plan précédent conservé.")
        return meta
    _upsert_plan(db, solution, deficit_solution)
    logger.info(f"[LABO OPTIMIZE PP] Plan écrit : {len(solution)} affectation(s), {len(deficit_solution)} déficit(s).")
    return meta


if __name__ == "__main__":
    import argparse
    from ...core.database import SessionLocal
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    args = ap.parse_args()
    session = SessionLocal()
    try:
        print(run_optimize_cycle(session, args.horizon_days))
    finally:
        session.close()