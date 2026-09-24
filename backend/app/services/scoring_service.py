from datetime import datetime, date, timedelta, time
from typing import Optional
from sqlalchemy.orm import Session

from ..core.models import User
from ..models.production import AffectationLigne, LigneCache, PerformanceLigneJour
from .ligne_helpers import get_planning_du_jour
from .performance_service import calculer_performance_ligne


def _performance_du_jour(db: Session, ligne_id: int, ligne: LigneCache, jour: date) -> Optional[int]:
    """Performance % d'une ligne pour un jour donné. Pour un jour PASSÉ (déjà clos), lit
    le snapshot figé (performance_ligne_jour) -- jamais recalculé rétroactivement, pour
    que le score d'une période passée reste stable dans le temps même si on le consulte
    plusieurs fois. Pour AUJOURD'HUI (pas encore snapshotté par le job du soir), calcule
    en direct -- seule exception, documentée, à l'utilisation exclusive de l'historique
    figé.

    *** CORRIGÉ 2026-09-18 *** : appelait encore get_of_actuel (of_cache), qui ne renvoie
    plus jamais rien depuis le 17/09 (of_cache n'est jamais "en cours" chez SIVOP) --
    calculer_performance_ligne recevait donc toujours None au lieu de la liste attendue,
    et renvoyait systématiquement performance_pct=None pour aujourd'hui. Conséquence
    concrète : la journée en cours était silencieusement exclue du score pondéré
    (cf. somme_ponderee plus bas, qui ignore les perf_pct None). Remplacé par
    get_planning_du_jour, la vraie source du théorique depuis le 17/09."""
    if jour == date.today():
        items_planning = get_planning_du_jour(db, ligne_id, jour)
        return calculer_performance_ligne(db, ligne, items_planning)["performance_pct"]

    snap = (
        db.query(PerformanceLigneJour)
        .filter(PerformanceLigneJour.ligne_id == ligne_id, PerformanceLigneJour.jour == jour)
        .first()
    )
    return snap.performance_pct if snap else None


def calculer_score_personnel(db: Session, user: User) -> Optional[dict]:
    """
    Score pondéré : moyenne de la performance JOURNALIÈRE des lignes affectées,
    pondérée par le temps réellement passé sur chacune CHAQUE JOUR (cf. récap de
    cadrage : "calculé par ligne × temps d'affectation"). Uniquement pour CDI/CDD --
    retourne None pour un Journalier ou un compte direction.

    S'appuie sur le vrai historique quotidien (performance_ligne_jour, figé chaque soir
    par services/snapshot_service.py) plutôt que sur la seule performance actuelle -- le
    score d'un mois d'affectation reflète donc la performance RÉELLE de chaque jour de ce
    mois, pas une photo instantanée d'aujourd'hui appliquée rétroactivement à tout
    l'historique (limitation de la version précédente, corrigée ici). Un jour sans
    snapshot disponible (avant la mise en place de ce mécanisme, ou job manqué un soir)
    est exclu du calcul plutôt que de fabriquer une valeur -- le score peut donc porter
    sur moins de jours que la durée totale d'affectation si l'historique est incomplet.
    """
    if user.categorie_personnel not in ("CDI", "CDD"):
        return None

    affectations = db.query(AffectationLigne).filter(AffectationLigne.user_id == user.id).all()
    if not affectations:
        return {"score_pct": None, "nb_lignes": 0, "heures_totales": 0.0}

    maintenant = datetime.now()
    total_heures = 0.0
    somme_ponderee = 0.0
    lignes_vues = set()
    lignes_cache: dict[int, LigneCache] = {}

    for aff in affectations:
        fin = aff.date_fin or maintenant
        if fin <= aff.date_debut:
            continue

        ligne = lignes_cache.get(aff.ligne_id)
        if ligne is None:
            ligne = db.query(LigneCache).filter(LigneCache.id == aff.ligne_id).first()
            if not ligne:
                continue
            lignes_cache[aff.ligne_id] = ligne

        # Parcours jour par jour de la période d'affectation -- une ligne peut avoir une
        # performance différente d'un jour à l'autre, contrairement à l'ancienne version
        # qui appliquait la performance actuelle à toute la période d'un coup.
        jour_courant = aff.date_debut.date()
        jour_fin = fin.date()
        while jour_courant <= jour_fin:
            debut_jour_dt = datetime.combine(jour_courant, time.min)
            fin_jour_dt = debut_jour_dt + timedelta(days=1)
            borne_debut = max(debut_jour_dt, aff.date_debut)
            borne_fin = min(fin_jour_dt, fin)
            heures_ce_jour = max(0.0, (borne_fin - borne_debut).total_seconds() / 3600)

            if heures_ce_jour > 0:
                perf_pct = _performance_du_jour(db, aff.ligne_id, ligne, jour_courant)
                if perf_pct is not None:
                    total_heures += heures_ce_jour
                    somme_ponderee += heures_ce_jour * perf_pct
                    lignes_vues.add(aff.ligne_id)

            jour_courant += timedelta(days=1)

    if total_heures == 0:
        return {"score_pct": None, "nb_lignes": len(lignes_vues), "heures_totales": 0.0}

    return {
        "score_pct": round(somme_ponderee / total_heures),
        "nb_lignes": len(lignes_vues),
        "heures_totales": round(total_heures, 1),
    }