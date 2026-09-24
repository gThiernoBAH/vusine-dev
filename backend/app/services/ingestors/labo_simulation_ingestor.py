"""
labo_simulation_ingestor.py -- Simulation stock MP -> produits finis possibles [F10].

Prédictif, distinct de labo_ecarts_inventaire (F10b, constatatif -- alimenté par
odoo_sync_service.sync_ecarts_inventaire, pas de calcul ici) : les deux ne sont JAMAIS
fusionnés dans un même chiffre.
"""
import logging
from sqlalchemy.orm import Session

from ...models.production import FormuleExplosionCache, StockMatiereCache, SimulationProductible

logger = logging.getLogger(__name__)


def recalculer_simulation_productible(db: Session) -> int:
    stocks = {s.produit_code: s.quantite_disponible for s in db.query(StockMatiereCache).all()}
    db.query(SimulationProductible).delete()
    produits = [r[0] for r in db.query(FormuleExplosionCache.produit_fini_code).distinct().all()]

    nb = 0
    for produit_fini_code in produits:
        composants = db.query(FormuleExplosionCache).filter(
            FormuleExplosionCache.produit_fini_code == produit_fini_code).all()
        ratios, nb_sans_stock = [], 0
        for c in composants:
            stock = stocks.get(c.composant_code)
            if stock is None:
                nb_sans_stock += 1
                continue
            if c.quantite_par_unite > 0:
                # *** CORRIGÉ 2026-09-22 (erreur réelle : integer out of range) ***
                # Un stock DÉJÀ négatif (déficit en cours, cf. stock_matieres_cache
                # agrégeant des mouvements Virtual Locations mal filtrés ou des écarts
                # d'inventaire non régularisés) divisé par un besoin unitaire infime
                # (ex. 0.000003) produit des ratios de plusieurs centaines de millions,
                # hors de portée d'une colonne INTEGER. Un stock négatif signifie "0
                # unité productible avec ce composant", jamais un nombre géant --
                # clampé à 0 avant d'entrer en compétition dans le min().
                ratio = max(0.0, float(stock) / float(c.quantite_par_unite))
                ratios.append((ratio, c.composant_code, stock, c.quantite_par_unite))
        if not ratios:
            continue
        qte, comp_lim, stock_lim, besoin_lim = min(ratios, key=lambda r: r[0])
        # Garde-fou supplémentaire (defense in depth) : même un ratio positif peut
        # théoriquement dépasser INTEGER si besoin_par_unite est extrêmement petit --
        # plafonné à 2 milliards plutôt que de faire à nouveau planter l'insertion.
        qte_bornee = min(int(qte), 2_000_000_000)
        db.add(SimulationProductible(
            produit_fini_code=produit_fini_code, quantite_productible=qte_bornee,
            composant_limitant_code=comp_lim, stock_limitant=stock_lim,
            besoin_limitant_par_unite=besoin_lim, nb_composants_sans_stock_connu=nb_sans_stock,
        ))
        nb += 1
    db.commit()
    logger.info(f"[LABO SIMULATION] {nb} produit(s) fini(s) simulé(s) (F10).")
    return nb


if __name__ == "__main__":
    from ...core.database import SessionLocal
    session = SessionLocal()
    try:
        print({"simulation_productible": recalculer_simulation_productible(session)})
    finally:
        session.close()