"""
labo_service.py -- Calculs LABO à la demande (F2, F3), jamais de job nocturne ici (cf.
app/services/ingestors/ pour tout ce qui est recalculé chaque nuit -- ligne de partage
délibérée entre ce fichier et le répertoire ingestors).
"""
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext


def evaluer_planning_risque(db: Session, horizon_jours: int = 14):
    """F2 -- le planning des prochains jours demande-t-il plus que ce que la ligne a
    déjà démontré (F1) ? Statuts : 'risque' (> p90), 'a_surveiller' (> médiane),
    'ok', 'inconnu' (capacité pas encore démontrée, < 5 jours observés -- jamais fondu
    avec 'risque', pour ne pas crier au loup sur un manque de donnée)."""
    return db.execute(sqltext("""
        SELECT p.ligne_id, l.code AS ligne_code, p.produit_id, pr.nom AS produit_nom,
               p.jour, p.qty, c.mediane_jour, c.p90_jour, c.nb_jours_observes,
               CASE WHEN c.id IS NULL OR c.nb_jours_observes < 5 THEN 'inconnu'
                    WHEN p.qty > c.p90_jour THEN 'risque'
                    WHEN p.qty > c.mediane_jour THEN 'a_surveiller'
                    ELSE 'ok' END AS statut
        FROM planning_detail_cache p
        JOIN lignes_cache l ON l.id = p.ligne_id
        JOIN produits_cache pr ON pr.id = p.produit_id
        LEFT JOIN labo_capacite_ligne_produit c ON c.ligne_id = p.ligne_id AND c.produit_id = p.produit_id
        WHERE p.jour BETWEEN CURRENT_DATE AND CURRENT_DATE + (:horizon || ' days')::interval
        ORDER BY (CASE WHEN c.id IS NULL OR c.nb_jours_observes < 5 THEN 'inconnu'
                       WHEN p.qty > c.p90_jour THEN 'risque'
                       WHEN p.qty > c.mediane_jour THEN 'a_surveiller'
                       ELSE 'ok' END) = 'risque' DESC, p.jour
    """), {"horizon": horizon_jours}).mappings().all()


def calculer_fiabilite_saisie(db: Session, jours: int = 30, ligne_id: int | None = None):
    """F3 -- délai réel entre production et saisie Odoo (production.entry.create_date -
    of_cache.production_date), et nombre de corrections déclarées par ligne."""
    filtre_ligne = "AND of_cache.ligne_id = :ligne_id" if ligne_id else ""
    params = {"jours": jours}
    if ligne_id:
        params["ligne_id"] = ligne_id
    return db.execute(sqltext(f"""
        SELECT of_cache.ligne_id, l.code AS ligne_code,
               COUNT(*) AS nb_of,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (s.create_date - of_cache.production_date::timestamp)) / 3600
               ) AS delai_median_h,
               percentile_cont(0.9) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (s.create_date - of_cache.production_date::timestamp)) / 3600
               ) AS delai_p90_h,
               (SELECT COUNT(*) FROM corrections_cache c
                WHERE c.ligne_id = of_cache.ligne_id
                  AND c.date_correction >= CURRENT_DATE - (:jours || ' days')::interval) AS nb_corrections
        FROM of_cache
        JOIN lignes_cache l ON l.id = of_cache.ligne_id
        LEFT JOIN saisies_production_cache s ON s.reference = of_cache.saisie_reference
        WHERE of_cache.usine = 'UPRINC' AND of_cache.etat = 'done'
          AND of_cache.production_date >= CURRENT_DATE - (:jours || ' days')::interval
          {filtre_ligne}
        GROUP BY of_cache.ligne_id, l.code
        ORDER BY delai_median_h DESC NULLS LAST
    """), params).mappings().all()
