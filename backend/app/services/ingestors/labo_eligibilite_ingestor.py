"""
labo_eligibilite_ingestor.py -- F1 (capacité démontrée par ligne/produit) et base de F8
(quelles lignes peuvent physiquement produire quel produit).

*** DÉCISION IMPORTANTE (cf. cadrage 22/09) *** : l'éligibilité N'utilise PAS
product_section_id/packaging_line_id sur product.template -- vérifié par inspection
XML-RPC que ces deux champs sont vides à 100% sur les 1164 produits finis actifs
(product_section_id sert en réalité à classer les MATIÈRES PREMIÈRES côté Odoo, pas les
produits finis). Seule source retenue : l'historique réel des OF ('historique'). Une
ligne ajoutée à la main en admin ('manuel') n'est jamais retirée par ce recalcul.

Appelé par le job nocturne (services/scheduler.py) avant labo_optimize_pp_ingestor
(qui dépend de ses deux tables).
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ...models.production import CapaciteLigneProduit, LigneProduitEligible

logger = logging.getLogger(__name__)


def recalculer_capacite_lignes_produits(db: Session) -> int:
    """F1 -- médiane/p90 par (ligne, produit), à partir des OF UPRINC terminés,
    groupés par jour de production réelle (plusieurs OF le même jour/ligne/produit
    sont sommés avant le calcul des percentiles)."""
    db.query(CapaciteLigneProduit).delete()
    rows = db.execute(sqltext("""
        WITH jours AS (
            SELECT ligne_id, produit_id, production_date AS jour, SUM(qty_planifiee) AS qte
            FROM of_cache
            WHERE usine = 'UPRINC' AND etat = 'done' AND production_date IS NOT NULL
              AND ligne_id IS NOT NULL AND produit_id IS NOT NULL
            GROUP BY ligne_id, produit_id, production_date
        )
        SELECT ligne_id, produit_id, COUNT(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY qte) AS mediane,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY qte) AS p90,
               MAX(jour) AS dernier
        FROM jours GROUP BY ligne_id, produit_id
    """)).fetchall()
    for ligne_id, produit_id, n, mediane, p90, dernier in rows:
        db.add(CapaciteLigneProduit(
            ligne_id=ligne_id, produit_id=produit_id, nb_jours_observes=n,
            mediane_jour=mediane, p90_jour=p90, dernier_jour_observe=dernier,
        ))
    db.commit()
    logger.info(f"[LABO CAPACITE] {len(rows)} couple(s) (ligne, produit) recalculé(s).")
    return len(rows)


def recalculer_eligibilite_lignes(db: Session) -> int:
    """Base de F8 -- une ligne est éligible à un produit si l'historique réel (OF
    terminés) montre qu'elle l'a déjà produit. Les entrées source='manuel' (ajoutées en
    admin pour des cas où la Production sait qu'une ligne jamais utilisée pourrait
    néanmoins convenir) sont préservées à chaque recalcul."""
    db.query(LigneProduitEligible).filter(LigneProduitEligible.source == "historique").delete()
    paires = db.execute(sqltext("""
        SELECT DISTINCT ligne_id, produit_id FROM of_cache
        WHERE usine = 'UPRINC' AND etat = 'done' AND ligne_id IS NOT NULL AND produit_id IS NOT NULL
    """)).fetchall()
    for ligne_id, produit_id in paires:
        existe_manuel = db.query(LigneProduitEligible).filter(
            LigneProduitEligible.ligne_id == ligne_id, LigneProduitEligible.produit_id == produit_id,
            LigneProduitEligible.source == "manuel").first()
        if not existe_manuel:
            db.add(LigneProduitEligible(ligne_id=ligne_id, produit_id=produit_id, source="historique"))
    db.commit()
    logger.info(f"[LABO ELIGIBILITE] {len(paires)} couple(s) (ligne, produit) éligible(s) via l'historique.")
    return len(paires)


def run_eligibilite_cycle(db: Session) -> dict:
    return {
        "capacite": recalculer_capacite_lignes_produits(db),
        "eligibilite": recalculer_eligibilite_lignes(db),
    }


if __name__ == "__main__":
    from ...core.database import SessionLocal
    session = SessionLocal()
    try:
        print(run_eligibilite_cycle(session))
    finally:
        session.close()
