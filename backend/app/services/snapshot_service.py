from datetime import date as date_type
from sqlalchemy.orm import Session

from ..models.production import LigneCache, PerformanceLigneJour
from .ligne_helpers import get_planning_du_jour
from .performance_service import calculer_performance_ligne


def snapshoter_performance_du_jour(db: Session, jour: date_type = None) -> int:
    """Fige la performance de CHAQUE ligne pour `jour` (par défaut aujourd'hui) dans
    performance_ligne_jour -- idempotent (upsert manuel ci-dessous) : rejouable sans
    risque de doublon si le job tourne deux fois le même jour. Retourne le nombre de
    lignes traitées.

    *** IMPORTANT *** : ne fige QUE la performance du moment où la fonction est appelée --
    pensé pour tourner en FIN de journée/poste (cf. scheduler.py), pas au milieu. Un appel
    en cours de journée écrase le snapshot du jour avec une performance partielle, ce qui
    fausserait le scoring historique pour ce jour-là de façon permanente.

    *** REVU 2026-09-17 *** : la performance vient désormais du planning hebdomadaire
    (get_planning_du_jour) plutôt que d'un "OF en cours" (cf. performance_service.py
    pour le détail de la découverte -- of_cache n'est jamais "en cours" chez SIVOP).
    """
    jour = jour or date_type.today()
    lignes = db.query(LigneCache).all()

    for ligne in lignes:
        items = get_planning_du_jour(db, ligne.id, jour)
        perf = calculer_performance_ligne(db, ligne, items)

        existant = (
            db.query(PerformanceLigneJour)
            .filter(PerformanceLigneJour.ligne_id == ligne.id, PerformanceLigneJour.jour == jour)
            .first()
        )
        if existant:
            existant.reel = perf["reel"]
            existant.theorique = perf["theorique"]
            existant.performance_pct = perf["performance_pct"]
        else:
            db.add(PerformanceLigneJour(
                ligne_id=ligne.id, jour=jour,
                reel=perf["reel"], theorique=perf["theorique"], performance_pct=perf["performance_pct"],
            ))

    db.commit()
    return len(lignes)