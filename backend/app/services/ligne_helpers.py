from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional

from ..models.production import OfCache, PlanningCache, PlanningDetailCache

# *** CONFIRMÉ 2026-09-16 (requête directe sur of_cache en conditions réelles) *** :
# "done" est un état terminal -- 100% des OF synchronisés étaient "done", aucun
# "confirmed"/"progress"/autre observé. Confirmé à nouveau le 2026-09-17 sur une
# resynchro fraîche (2972 OF, toujours 100% "done") -- cf. get_planning_du_jour
# ci-dessous pour la VRAIE source du théorique, of_cache n'étant plus qu'informatif.
ETATS_OF_TERMINES = ("done", "cancel")

# Seule valeur Odoo réelle confirmée (XML-RPC, 2026-09-17) pour "planning à considérer".
ETAT_PLANNING_CONFIRME = "confirmed"


def get_of_actuel(db: Session, ligne_id: int) -> Optional[OfCache]:
    """*** DEVENU INFORMATIF 2026-09-17 *** : ne pilote plus le calcul de performance
    (cf. get_planning_du_jour ci-dessous, remplacé par le planning hebdomadaire réel).
    Gardée pour un affichage éventuel "dernière production enregistrée sur cette ligne"
    si besoin plus tard -- of_cache n'est jamais réellement "en cours" chez SIVOP
    (mrp.production n'y sert qu'à constater une production déjà terminée)."""
    return (
        db.query(OfCache)
        .filter(OfCache.ligne_id == ligne_id, OfCache.etat.notin_(ETATS_OF_TERMINES))
        .order_by(desc(OfCache.date_debut))
        .first()
    )


def get_planning_du_jour(db: Session, ligne_id: int, jour: date = None) -> list[PlanningDetailCache]:
    """*** NOUVEAU 2026-09-17 -- REMPLACE get_of_actuel comme source du théorique ***

    Renvoie TOUS les items de planning confirmés pour cette ligne, ce jour (0, 1 ou
    PLUSIEURS -- une ligne peut avoir plusieurs produits planifiés le même jour, cf.
    décision du 2026-09-17 : pas de restriction artificielle à un seul produit/jour).
    Chaque item = un couple (produit, quantité cible du jour) issu de
    mrp.detail.planning.line, rattaché à un en-tête mrp.planning dont l'état doit être
    'confirmed' (filtré ici à la LECTURE, pas à la synchro -- cf. odoo_sync_service.py).

    Utilisé par :
      - performance_service.calculer_performance_ligne (théorique = somme des qty)
      - entity_routes.get_ligne_detail (liste affichée côté tablette/cockpit)
      - alertes_engine (ralentissement, silence de scan)
      - snapshot_service (snapshot quotidien)
    """
    jour = jour or date.today()
    return (
        db.query(PlanningDetailCache)
        .join(PlanningCache, PlanningDetailCache.planning_id == PlanningCache.id)
        .filter(
            PlanningDetailCache.ligne_id == ligne_id,
            PlanningDetailCache.jour == jour,
            PlanningCache.etat == ETAT_PLANNING_CONFIRME,
        )
        .order_by(PlanningDetailCache.id)
        .all()
    )