"""
labo_ecritures_ingestor.py -- F5 (export uniquement, PAS d'écriture réelle dans Odoo --
ODOO_WRITEBACK_ENABLED reste False, décision actée).

Reconstitue chaque nuit ce que Vusine écrirait dans Odoo si F5 était actif (depuis les
PALETTES réellement scannées, jamais depuis le planning théorique), et compare ce
résultat à ce qu'Odoo contient réellement (of_cache, saisi par l'agent le lendemain).
Cette comparaison, accumulée sur plusieurs semaines, est la preuve chiffrée qui
décidera un jour d'activer F5 -- un ecart_pct proche de 0 et stable dirait que Vusine
peut se substituer à la saisie manuelle.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ...models.production import EcritureOdooProposee, ComparaisonEcritureOdoo

logger = logging.getLogger(__name__)


def recalculer_ecritures_proposees(db: Session) -> int:
    db.query(EcritureOdooProposee).delete()
    lignes = db.execute(sqltext("""
        SELECT p.ligne_id, DATE(p.created_at) AS jour, pdc.produit_id,
               SUM(p.quantite_totale) AS qte, COUNT(*) AS nb,
               COUNT(*) FILTER (WHERE NOT p.complete) AS nb_partielles
        FROM palettes p
        JOIN planning_detail_cache pdc ON pdc.id = p.planning_detail_id
        WHERE pdc.produit_id IS NOT NULL
        GROUP BY p.ligne_id, DATE(p.created_at), pdc.produit_id
    """)).fetchall()
    for ligne_id, jour, produit_id, qte, nb, nb_partielles in lignes:
        db.add(EcritureOdooProposee(
            ligne_id=ligne_id, jour=jour, produit_id=produit_id,
            quantite_reelle=int(qte), nb_palettes=nb, nb_palettes_partielles=nb_partielles,
        ))
    db.commit()
    logger.info(f"[LABO ECRITURES] {len(lignes)} écriture(s) proposée(s) reconstituée(s).")
    return len(lignes)


def recalculer_comparaison_odoo(db: Session) -> int:
    """FULL OUTER pour ne perdre ni les palettes sans OF correspondant (saisie pas
    encore faite côté Odoo) ni les OF sans palette (production hors tablette, ou
    tablette pas encore adoptée sur cette ligne)."""
    db.query(ComparaisonEcritureOdoo).delete()
    lignes = db.execute(sqltext("""
        SELECT COALESCE(v.ligne_id, o.ligne_id) AS ligne_id, COALESCE(v.jour, o.jour) AS jour,
               COALESCE(v.produit_id, o.produit_id) AS produit_id,
               v.quantite_reelle AS qte_vusine, o.qte_odoo
        FROM labo_ecritures_odoo_proposees v
        FULL OUTER JOIN (
            SELECT ligne_id, produit_id, production_date AS jour, SUM(qty_planifiee) AS qte_odoo
            FROM of_cache WHERE usine = 'UPRINC' AND etat = 'done' AND production_date IS NOT NULL
            GROUP BY ligne_id, produit_id, production_date
        ) o ON o.ligne_id = v.ligne_id AND o.jour = v.jour AND o.produit_id = v.produit_id
    """)).fetchall()
    for ligne_id, jour, produit_id, qv, qo in lignes:
        ecart = (qv - qo) if (qv is not None and qo is not None) else None
        ecart_pct = round(100 * ecart / qo, 1) if (ecart is not None and qo) else None
        db.add(ComparaisonEcritureOdoo(
            ligne_id=ligne_id, jour=jour, produit_id=produit_id,
            quantite_vusine=int(qv) if qv is not None else None,
            quantite_odoo=int(qo) if qo is not None else None,
            ecart_qte=ecart, ecart_pct=ecart_pct,
        ))
    db.commit()
    logger.info(f"[LABO ECRITURES] {len(lignes)} ligne(s) de comparaison Vusine/Odoo calculée(s).")
    return len(lignes)


def lister_ecritures_proposees(db: Session, date_debut, date_fin):
    return db.execute(sqltext("""
        SELECT l.code AS ligne_code, e.jour, p.nom AS produit_nom,
               e.quantite_reelle, e.nb_palettes, e.nb_palettes_partielles
        FROM labo_ecritures_odoo_proposees e
        JOIN lignes_cache l ON l.id = e.ligne_id
        JOIN produits_cache p ON p.id = e.produit_id
        WHERE e.jour BETWEEN :d1 AND :d2 ORDER BY e.jour, l.code
    """), {"d1": date_debut, "d2": date_fin}).mappings().all()


def lister_comparaison_odoo(db: Session, date_debut, date_fin):
    return db.execute(sqltext("""
        SELECT l.code AS ligne_code, c.jour, p.nom AS produit_nom,
               c.quantite_vusine, c.quantite_odoo, c.ecart_qte, c.ecart_pct
        FROM labo_comparaison_ecritures c
        LEFT JOIN lignes_cache l ON l.id = c.ligne_id
        LEFT JOIN produits_cache p ON p.id = c.produit_id
        WHERE c.jour BETWEEN :d1 AND :d2 ORDER BY c.jour, l.code
    """), {"d1": date_debut, "d2": date_fin}).mappings().all()


def run_ecritures_cycle(db: Session) -> dict:
    return {
        "ecritures_proposees": recalculer_ecritures_proposees(db),
        "comparaison_odoo": recalculer_comparaison_odoo(db),
    }


if __name__ == "__main__":
    from ...core.database import SessionLocal
    session = SessionLocal()
    try:
        print(run_ecritures_cycle(session))
    finally:
        session.close()
