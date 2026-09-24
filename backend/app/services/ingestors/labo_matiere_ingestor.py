"""
labo_matiere_ingestor.py -- Besoins matières projetés [F9a] et alertes d'achat [F9b].

F9a : combine F7 (labo_prevision_volume) x labo_formules_explosion (BOM explosée) pour
projeter la consommation à venir, comparée au stock actuel (stock_matieres_cache).
F9b : pour chaque matière en tension identifiée par F9a, cherche les fournisseurs
connus (labo_fournisseurs_matiere) et calcule une date limite de commande = date de
rupture projetée - meilleur délai connu. AUCUN prix, AUCUNE sélection automatique du
"meilleur" fournisseur (décision actée : pas de conversion de devise fiable
synchronisée -- 3 devises actives mesurées côté Odoo, XOF/EUR/USD) -- liste les
fournisseurs disponibles, la décision reste humaine.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ...models.production import (
    PrevisionVolume, FormuleExplosionCache, StockMatiereCache, ProduitCache,
    BesoinMatiereProjete, FournisseurMatiereCache, AlerteAchatProjete,
)

logger = logging.getLogger(__name__)


def recalculer_besoins_matieres(db: Session) -> int:
    db.query(BesoinMatiereProjete).delete()
    stocks = {s.produit_code: float(s.quantite_disponible) for s in db.query(StockMatiereCache).all()}
    explosion = db.query(FormuleExplosionCache).all()
    par_produit: dict[str, list] = defaultdict(list)
    for e in explosion:
        par_produit[e.produit_fini_code].append(e)

    # *** CORRIGÉ 2026-09-23 *** : seules les prévisions à partir d'aujourd'hui comptent
    # comme besoin futur. Garde-fou : labo_predict_ingestor ne produit plus de dates
    # passées depuis la même date, mais une prévision datée du passé ne doit JAMAIS
    # gonfler un besoin matière (c'était le cas avant : dates de rupture déjà dépassées).
    previsions = db.query(PrevisionVolume).filter(
        PrevisionVolume.jour_horizon >= date.today()).order_by(PrevisionVolume.jour_horizon).all()
    produits_code = {p.id: p.default_code for p in db.query(ProduitCache).all()}

    consommation_cumulee: dict[str, float] = defaultdict(float)
    ruptures_deja_vues: set[str] = set()
    nb_alertes = 0
    for prev in previsions:
        code_produit = produits_code.get(prev.produit_id)
        if not code_produit:
            continue
        for comp in par_produit.get(code_produit, []):
            besoin = float(prev.qte_prevue or 0) * float(comp.quantite_par_unite)
            consommation_cumulee[comp.composant_code] += besoin
            stock_projete = stocks.get(comp.composant_code, 0) - consommation_cumulee[comp.composant_code]
            # Une seule ligne par matière : la PREMIÈRE date où le stock projeté passe
            # sous 0 (pas une ligne par jour -- inutile pour une alerte d'achat).
            if stock_projete < 0 and comp.composant_code not in ruptures_deja_vues:
                ruptures_deja_vues.add(comp.composant_code)
                db.add(BesoinMatiereProjete(
                    matiere_code=comp.composant_code, date_rupture_projetee=prev.jour_horizon,
                    stock_projete=round(stock_projete, 2),
                ))
                nb_alertes += 1
    db.commit()
    logger.info(f"[LABO MATIERE] {nb_alertes} matière(s) en tension projetée (F9a).")
    return nb_alertes


def recalculer_alertes_achat(db: Session) -> int:
    db.query(AlerteAchatProjete).delete()
    besoins = db.query(BesoinMatiereProjete).all()
    for b in besoins:
        fournisseurs = db.query(FournisseurMatiereCache).filter(
            FournisseurMatiereCache.matiere_code == b.matiere_code).all()
        meilleur_delai = min((f.delai_jours for f in fournisseurs), default=None)
        date_limite = (b.date_rupture_projetee - timedelta(days=meilleur_delai)
                       if meilleur_delai is not None and b.date_rupture_projetee else None)
        db.add(AlerteAchatProjete(
            matiere_code=b.matiere_code, date_rupture_projetee=b.date_rupture_projetee,
            quantite_manquante=abs(b.stock_projete), meilleur_delai_jours=meilleur_delai,
            date_limite_commande=date_limite, nb_fournisseurs_disponibles=len(fournisseurs),
        ))
    db.commit()
    logger.info(f"[LABO MATIERE] {len(besoins)} alerte(s) d'achat calculée(s) (F9b).")
    return len(besoins)


def run_matiere_cycle(db: Session) -> dict:
    return {
        "besoins_matieres": recalculer_besoins_matieres(db),
        "alertes_achat": recalculer_alertes_achat(db),
    }


if __name__ == "__main__":
    from ...core.database import SessionLocal
    session = SessionLocal()
    try:
        print(run_matiere_cycle(session))
    finally:
        session.close()
