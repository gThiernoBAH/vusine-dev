from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..models.production import LigneCache, Arret, Palette, PerformanceLigneJour, ProduitCache
from ..schemas.dashboard import (
    LignePerformanceOut, VueUsineResume, VueUsineOut, ArretJourOut, LigneDetailPerformanceOut,
    AndonLigneOut, AndonOut,
)
from .auth_routes import get_current_user, require_permission, require_andon
from ..services.ligne_helpers import get_planning_du_jour
from ..services.performance_service import calculer_performance_ligne

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _ligne_perf_out(db: Session, ligne: LigneCache, jour: date) -> LignePerformanceOut:
    """*** ÉTENDU 2026-09-18 (filtre par date) *** : pour AUJOURD'HUI, comportement
    inchangé -- calcul en direct depuis le planning + les palettes/arrêts en cours. Pour
    un jour PASSÉ, lit le snapshot figé (performance_ligne_jour, cf. snapshot_service.py)
    -- jamais de recalcul rétroactif, même principe déjà appliqué par reports_service.py.
    Le snapshot ne stocke que reel/theorique/performance_pct (pas de statut ni de retard
    -- des notions "temps réel" qui n'ont plus de sens une fois la journée close) :
    statut est donc redérivé ici des mêmes seuils que le calcul en direct
    (vert>=100/orange>=80/rouge<80), retard_min et prevision_fin_poste renvoyés neutres."""
    if jour == date.today():
        items = get_planning_du_jour(db, ligne.id, jour)
        perf = calculer_performance_ligne(db, ligne, items)
        return LignePerformanceOut(
            id=ligne.id, code=ligne.code, nom=ligne.nom, section_nom=ligne.section_nom,
            reel=perf["reel"], theorique=perf["theorique"], performance_pct=perf["performance_pct"],
            retard_min=perf["retard_min"], statut=perf["statut"],
            prevision_fin_poste=perf.get("prevision_fin_poste"), objectif_jour=perf.get("objectif_jour"),
        )

    snap = (
        db.query(PerformanceLigneJour)
        .filter(PerformanceLigneJour.ligne_id == ligne.id, PerformanceLigneJour.jour == jour)
        .first()
    )
    if not snap:
        # Pas de snapshot pour ce jour (avant la mise en place du mécanisme, ou job
        # manqué ce soir-là) -- "inactif" plutôt qu'un chiffre inventé, même principe
        # que le calcul en direct sans planning.
        return LignePerformanceOut(
            id=ligne.id, code=ligne.code, nom=ligne.nom, section_nom=ligne.section_nom,
            reel=0, theorique=None, performance_pct=None, retard_min=0, statut="inactif",
            prevision_fin_poste=None,
        )

    pct = snap.performance_pct
    if pct is None:
        statut = "inactif"
    elif pct >= 100:
        statut = "vert"
    elif pct >= 80:
        statut = "orange"
    else:
        statut = "rouge"

    return LignePerformanceOut(
        id=ligne.id, code=ligne.code, nom=ligne.nom, section_nom=ligne.section_nom,
        reel=snap.reel, theorique=snap.theorique, performance_pct=snap.performance_pct,
        retard_min=0, statut=statut, prevision_fin_poste=None,
    )


# GET /dashboard/vue_usine (underscore -- convention actée, pas de tiret dans les routes)
@router.get("/vue_usine", response_model=VueUsineOut)
def get_vue_usine(
    jour: Optional[date] = Query(None, description="Jour à consulter (défaut : aujourd'hui). Un jour passé est lu depuis le snapshot figé, jamais recalculé."),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("view_vue_usine")),
):
    """Vue d'ensemble des lignes (écran cockpit direction). Interrogée par le front
    toutes les 5-10s (polling léger, cf. décision d'architecture -- pas de WebSocket/Redis
    en V1, le volume et le besoin réel ne le justifient pas) -- UNIQUEMENT quand jour
    est aujourd'hui ou omis ; consulter un jour passé n'a pas vocation à être pollé.

    *** AJOUT 2026-09-16 (rôle Chef d'équipe, slide 16) *** : si le compte connecté a un
    section_scope renseigné, la vue est restreinte à cette seule section -- un chef
    d'équipe ne voit que son atelier, jamais l'usine complète."""
    jour = jour or date.today()
    query = db.query(LigneCache).filter(LigneCache.actif.is_(True))
    if user.section_scope:
        query = query.filter(LigneCache.section_nom == user.section_scope)
    lignes = query.order_by(LigneCache.code).all()

    resultats: list[LignePerformanceOut] = []
    lignes_vertes = lignes_orange = lignes_rouges = a_larret = 0
    total_reel = total_theorique = 0

    for ligne in lignes:
        perf_out = _ligne_perf_out(db, ligne, jour)
        resultats.append(perf_out)
        if perf_out.statut == "arret":
            a_larret += 1
        elif perf_out.statut == "rouge":
            lignes_rouges += 1
        elif perf_out.statut == "orange":
            lignes_orange += 1
        elif perf_out.statut == "vert":
            lignes_vertes += 1
        total_reel += perf_out.reel
        total_theorique += perf_out.theorique or 0

    resume = VueUsineResume(
        total_lignes=len(lignes),
        lignes_vertes=lignes_vertes,
        lignes_orange=lignes_orange,
        lignes_rouges=lignes_rouges,
        lignes_a_larret=a_larret,
        total_reel=total_reel,
        total_theorique=total_theorique,
        # slide 9 : "Performance usine 92,8%" -- None plutôt que 0% si aucune ligne
        # n'a de théorique calculable (usine fermée, par ex.), pour ne pas afficher un
        # faux 0% de sous-performance.
        performance_usine_pct=round(total_reel / total_theorique * 100) if total_theorique > 0 else None,
    )
    return VueUsineOut(resume=resume, lignes=resultats)


@router.get("/lignes/{ligne_id}", response_model=LigneDetailPerformanceOut)
def get_ligne_performance_detail(
    ligne_id: int,
    jour: Optional[date] = Query(None, description="Jour à consulter (défaut : aujourd'hui)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fiche performance d'une ligne (complète le détail référentiel de
    GET /entities/lignes/{id} avec les chiffres du jour choisi : arrêts, palettes)."""
    ligne = db.query(LigneCache).filter(LigneCache.id == ligne_id).first()
    if not ligne:
        raise HTTPException(status_code=404, detail="Ligne introuvable.")

    jour = jour or date.today()
    perf_out = _ligne_perf_out(db, ligne, jour)

    debut_jour = datetime.combine(jour, datetime.min.time())
    fin_jour = debut_jour + timedelta(days=1)
    arrets_du_jour = (
        db.query(Arret)
        .filter(Arret.ligne_id == ligne_id, Arret.heure_debut >= debut_jour, Arret.heure_debut < fin_jour)
        .order_by(Arret.heure_debut.desc())
        .all()
    )
    arrets_out = []
    for a in arrets_du_jour:
        fin_calc = a.heure_fin or datetime.now()
        duree_min = round((fin_calc - a.heure_debut).total_seconds() / 60)
        equipement_label = None
        if a.equipement:
            equipement_label = f"{a.equipement.type} {a.equipement.marque or ''}".strip()
        arrets_out.append(ArretJourOut(
            id=a.id,
            cause_libelle=a.cause.libelle if a.cause else "",
            equipement_label=equipement_label,
            heure_debut=a.heure_debut.isoformat(),
            heure_fin=a.heure_fin.isoformat() if a.heure_fin else None,
            duree_min=duree_min,
        ))

    nb_palettes_du_jour = (
        db.query(Palette)
        .filter(Palette.ligne_id == ligne_id, Palette.created_at >= debut_jour, Palette.created_at < fin_jour)
        .count()
    )

    return LigneDetailPerformanceOut(
        ligne=perf_out, arrets_du_jour=arrets_out, nb_palettes_du_jour=nb_palettes_du_jour,
    )


# =============================================================
# *** AJOUT 2026-09-24 (Palier 0) *** : écran Andon -- TV d'atelier.
# Une seule requête légère, interrogée toutes les ~10 s par l'écran, qui contient TOUT ce
# qu'il affiche : lecture seule, aucune interaction. Accessible au compte « kiosque »
# (seule route qu'il peut appeler, cf. auth_routes.get_current_user) et aux comptes
# direction autorisés à voir la Vue Usine (aperçu). Un compte avec section_scope
# (Chef d'équipe, ou kiosque d'un seul atelier) ne voit que sa section.
# =============================================================

# Les problèmes d'abord : c'est le principe même d'un Andon.
_ORDRE_STATUT_ANDON = {"arret": 0, "rouge": 1, "orange": 2, "demarrage": 3, "vert": 4, "inactif": 5}


def _libelle_produits_du_jour(db: Session, items) -> Optional[str]:
    """« Produit A » ou « Produit A +1 » (plusieurs produits planifiés le même jour)."""
    ids = [i.produit_id for i in items if i.produit_id]
    if not ids:
        return None
    nom = db.query(ProduitCache.nom).filter(ProduitCache.id == ids[0]).scalar()
    if not nom:
        return None
    return nom if len(ids) == 1 else f"{nom} +{len(ids) - 1}"


@router.get("/andon", response_model=AndonOut)
def get_andon(db: Session = Depends(get_db), user: User = Depends(require_andon)):
    jour = date.today()
    maintenant = datetime.now()
    query = db.query(LigneCache).filter(LigneCache.actif.is_(True))
    if user.section_scope:
        query = query.filter(LigneCache.section_nom == user.section_scope)
    lignes = query.order_by(LigneCache.code).all()
    ids = [l.id for l in lignes]

    # Arrêts en cours, en une seule requête (le plus récent par ligne).
    arrets_ouverts: dict[int, Arret] = {}
    if ids:
        for a in db.query(Arret).filter(Arret.ligne_id.in_(ids), Arret.heure_fin.is_(None)).order_by(Arret.heure_debut):
            arrets_ouverts[a.ligne_id] = a

    sorties: list[AndonLigneOut] = []
    compteurs = {"vert": 0, "orange": 0, "rouge": 0, "arret": 0}
    total_reel = total_theorique = 0
    for ligne in lignes:
        perf = _ligne_perf_out(db, ligne, jour)
        items = get_planning_du_jour(db, ligne.id, jour)
        arret = arrets_ouverts.get(ligne.id)
        sortie = AndonLigneOut(
            id=ligne.id, code=ligne.code, nom=ligne.nom, section_nom=ligne.section_nom,
            statut=perf.statut, reel=perf.reel, theorique=perf.theorique,
            performance_pct=perf.performance_pct, retard_min=perf.retard_min,
            prevision_fin_poste=perf.prevision_fin_poste, objectif_jour=perf.objectif_jour,
            produit=_libelle_produits_du_jour(db, items),
        )
        if arret:
            # Un arrêt ouvert prime, même si le statut calculé ne l'a pas (poste fermé...).
            sortie.statut = "arret"
            sortie.arret_cause = arret.cause.libelle if arret.cause else "Cause non précisée"
            sortie.arret_depuis_min = max(0, round((maintenant - arret.heure_debut).total_seconds() / 60))
            if arret.equipement:
                sortie.arret_equipement = f"{arret.equipement.type} {arret.equipement.marque or ''}".strip()
        if sortie.statut in compteurs:
            compteurs[sortie.statut] += 1
        total_reel += sortie.reel
        total_theorique += sortie.theorique or 0
        sorties.append(sortie)

    sorties.sort(key=lambda l: (_ORDRE_STATUT_ANDON.get(l.statut, 9), l.code))
    resume = VueUsineResume(
        total_lignes=len(lignes), lignes_vertes=compteurs["vert"], lignes_orange=compteurs["orange"],
        lignes_rouges=compteurs["rouge"], lignes_a_larret=compteurs["arret"],
        total_reel=total_reel, total_theorique=total_theorique,
        performance_usine_pct=round(total_reel / total_theorique * 100) if total_theorique > 0 else None,
    )
    return AndonOut(genere_a=maintenant.isoformat(timespec="seconds"), jour=jour.isoformat(), resume=resume, lignes=sorties)
