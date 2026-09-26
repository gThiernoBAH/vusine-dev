from datetime import date as date_type, datetime
from sqlalchemy.orm import Session

from ..models.production import LigneCache, PerformanceLigneJour
from .trs_service import donnees_ligne_jour


def snapshoter_performance_du_jour(db: Session, jour: date_type = None) -> int:
    """Fige la performance de CHAQUE ligne pour `jour` (par défaut aujourd'hui) dans
    performance_ligne_jour -- idempotent (upsert manuel ci-dessous) : rejouable sans
    risque de doublon si le job tourne deux fois le même jour. Retourne le nombre de
    lignes traitées.

    *** IMPORTANT *** : ne fige QUE la performance du moment où la fonction est appelée --
    pensé pour tourner en FIN de journée/poste (cf. scheduler.py), pas au milieu. Un appel
    en cours de journée écrase le snapshot du jour avec une performance partielle, ce qui
    fausserait le scoring historique pour ce jour-là de façon permanente.

    *** CORRIGÉ 2026-09-25 *** : reposait sur calculer_performance_ligne (performance_service.py),
    une fonction "à l'instant présent" qui borne son calcul sur `datetime.now().date()` --
    PAS sur `jour`. Tant que le scheduler l'appelle en fin de poste pour AUJOURD'HUI (son
    usage prévu), jour == aujourd'hui et l'erreur ne se voit jamais. Mais appelée pour un
    jour PASSÉ (rattrapage après-coup -- cf. scripts/demo/simuler_historique.py), elle
    cherchait les palettes sur la fenêtre d'AUJOURD'HUI au lieu de `jour` : "reel" figé à 0
    pour toujours (le snapshot n'est jamais recalculé une fois écrit). Découvert le
    2026-09-25 en reprenant une démo à zéro : 120 écarts "réel -> 0 vs X" dans
    verifier_coherence.py sur des lignes dont les palettes existaient bel et bien en base.
    Utilise maintenant donnees_ligne_jour (trs_service), qui borne correctement son calcul
    sur `jour` lui-même -- la même fonction déjà utilisée par le rapport TRS et validée par
    verifier_coherence.py sur 601 journées-lignes réelles dans cette même session.
    """
    jour = jour or date_type.today()
    lignes = db.query(LigneCache).all()
    live = donnees_ligne_jour(db, lignes, jour, jour, datetime.now())

    for ligne in lignes:
        c = live.cellules.get((ligne.id, jour))
        reel = c["conforme"] if c else 0
        theorique = c["q_run"] if c else 0
        performance_pct = round(reel / theorique * 100) if theorique else None

        existant = (
            db.query(PerformanceLigneJour)
            .filter(PerformanceLigneJour.ligne_id == ligne.id, PerformanceLigneJour.jour == jour)
            .first()
        )
        if existant:
            existant.reel = reel
            existant.theorique = theorique
            existant.performance_pct = performance_pct
        else:
            db.add(PerformanceLigneJour(
                ligne_id=ligne.id, jour=jour,
                reel=reel, theorique=theorique, performance_pct=performance_pct,
            ))

    db.commit()
    return len(lignes)