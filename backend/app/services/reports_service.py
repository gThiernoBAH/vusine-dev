from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..core.models import User
from ..models.production import (
    LigneCache, PerformanceLigneJour, Palette, Arret, CauseArret,
    PlanningDetailCache, ProduitCache,
)
from .pertes_service import arrets_de_periode, minutes_entre
from .trs_service import donnees_ligne_jour
from ..schemas.reports import (
    RapportLigneOut, RapportDirectionOut, TopFlopLigneOut, PerteCauseOut, EvolutionJourOut,
    RapportProduitOut, RapportSectionOut, HistoriqueScanOut,
)

# *** REVU 2026-09-24 *** : ces rapports dépendaient UNIQUEMENT du snapshot figé chaque soir
# (performance_ligne_jour) -- tant que le job n'avait pas tourné, tout s'affichait à 0 sans
# aucune explication (constaté chez l'utilisateur : « Réel 0 / Théorique 0 » avec 1 palette
# pourtant visible dans la colonne Palettes). Désormais : le snapshot fait foi quand il existe
# (l'historique figé n'est jamais recalculé) ; à défaut, le jour COMPLET est calculé
# directement depuis planning, palettes et arrêts (trs_service.donnees_ligne_jour). Le jour
# en cours n'est compté ni par l'un ni par l'autre.

def _bornes_jour(d: date) -> tuple[datetime, datetime]:
    """Bornes [00:00, 00:00 du lendemain[ pour un jour donné -- utilisé pour filtrer
    palettes/arrêts (tables horodatées en TIMESTAMP, pas en DATE)."""
    debut = datetime.combine(d, datetime.min.time())
    return debut, debut + timedelta(days=1)


def _lignes_du_perimetre(db: Session, ligne_id: Optional[int], section_scope: Optional[str]) -> list[LigneCache]:
    q = db.query(LigneCache).filter(LigneCache.actif.is_(True))
    if section_scope:
        q = q.filter(LigneCache.section_nom == section_scope)
    if ligne_id:
        q = q.filter(LigneCache.id == ligne_id)
    return q.order_by(LigneCache.code).all()


def perf_ligne_jour(db: Session, lignes: list[LigneCache], date_debut: date, date_fin: date,
                    maintenant: Optional[datetime] = None) -> dict[tuple[int, date], tuple[float, float]]:
    """{(ligne_id, jour): (reel, theorique)} -- snapshot si présent, sinon calcul direct."""
    maintenant = maintenant or datetime.now()
    ids = [l.id for l in lignes]
    resultat: dict[tuple[int, date], tuple[float, float]] = {}
    if not ids:
        return resultat
    for snap in db.query(PerformanceLigneJour).filter(
        PerformanceLigneJour.ligne_id.in_(ids), PerformanceLigneJour.jour >= date_debut, PerformanceLigneJour.jour <= date_fin,
    ):
        resultat[(snap.ligne_id, snap.jour)] = (float(snap.reel), float(snap.theorique or 0))
    live = donnees_ligne_jour(db, lignes, date_debut, date_fin, maintenant)
    for cle, c in live.cellules.items():
        resultat.setdefault(cle, (c["conforme"], c["q_run"]))
    return resultat


def rapport_par_ligne(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None, maintenant: Optional[datetime] = None,
) -> list[RapportLigneOut]:
    """Écran Rapports, onglet 'Par ligne' (slide 14) -- une ligne du tableau par ligne
    active du périmètre, agrégée sur [date_debut, date_fin] inclus."""
    lignes = _lignes_du_perimetre(db, ligne_id, section_scope)
    perf = perf_ligne_jour(db, lignes, date_debut, date_fin, maintenant)
    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)
    sorties = []
    for ligne in lignes:
        jours = [v for (lid, _j), v in perf.items() if lid == ligne.id]
        reel_total = round(sum(r for r, _t in jours))
        theorique_total = round(sum(t for _r, t in jours))
        nb_palettes = (
            db.query(Palette)
            .filter(Palette.ligne_id == ligne.id, Palette.created_at >= borne_debut, Palette.created_at < borne_fin).count()
        )
        # *** CORRIGÉ 2026-09-24 *** : tout arrêt qui chevauche la période, plafonné à ses bornes.
        temps_arret_min = round(sum(
            minutes_entre(debut, fin) for _a, debut, fin in arrets_de_periode(db, borne_debut, borne_fin, [ligne.id])
        ))
        sorties.append(RapportLigneOut(
            ligne_id=ligne.id, code=ligne.code, nom=ligne.nom, reel_total=reel_total, theorique_total=theorique_total,
            performance_moyenne=round(reel_total / theorique_total * 100) if theorique_total > 0 else None,
            nb_palettes=nb_palettes, temps_arret_min=temps_arret_min,
        ))
    return sorties


def rapport_par_produit(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None,
) -> list[RapportProduitOut]:
    """*** NOUVEAU 2026-09-18 *** : écran Rapports, onglet 'Par produit' (slide 14).

    Agrégé depuis les palettes validées sur la période, rattachées à un produit via
    planning_detail_cache. Une palette sans planning_detail_id est exclue de ce rapport
    plutôt que comptée sous un faux produit « inconnu ». Filtrable par ligne / section
    (2026-09-24)."""
    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)
    ids = [l.id for l in _lignes_du_perimetre(db, ligne_id, section_scope)]
    if not ids:
        return []

    rows = (
        db.query(PlanningDetailCache.produit_id, ProduitCache.nom, Palette)
        .join(PlanningDetailCache, Palette.planning_detail_id == PlanningDetailCache.id)
        .join(ProduitCache, PlanningDetailCache.produit_id == ProduitCache.id)
        .filter(Palette.created_at >= borne_debut, Palette.created_at < borne_fin, Palette.ligne_id.in_(ids))
        .all()
    )

    agregats: dict[int, dict] = {}
    for produit_id, nom, palette in rows:
        a = agregats.setdefault(produit_id, {
            "produit_id": produit_id, "nom": nom, "quantite_totale": 0,
            "nb_palettes": 0, "nb_palettes_completes": 0, "nb_palettes_partielles": 0,
        })
        a["quantite_totale"] += palette.quantite_totale
        a["nb_palettes"] += 1
        if palette.complete:
            a["nb_palettes_completes"] += 1
        else:
            a["nb_palettes_partielles"] += 1

    resultats = [RapportProduitOut(**a) for a in agregats.values()]
    resultats.sort(key=lambda r: r.quantite_totale, reverse=True)
    return resultats


def _rapport_par_section(db: Session, rows_par_ligne: list[RapportLigneOut]) -> list[RapportSectionOut]:
    """'Performance par atelier' de la Vue Direction (slide 14) -- regroupe le rapport
    'par ligne' déjà calculé par section_nom. Agrégation en somme(reel)/somme(theorique),
    pas une moyenne des % par ligne (une petite ligne ne pèse pas comme une grosse)."""
    lignes_par_id = {l.id: l for l in db.query(LigneCache).all()}
    agregats: dict[str, dict] = {}
    for r in rows_par_ligne:
        ligne = lignes_par_id.get(r.ligne_id)
        section = (ligne.section_nom if ligne else None) or "Sans section"
        a = agregats.setdefault(section, {"section_nom": section, "reel_total": 0, "theorique_total": 0, "nb_lignes": 0})
        a["reel_total"] += r.reel_total
        a["theorique_total"] += r.theorique_total
        a["nb_lignes"] += 1

    resultats = []
    for a in agregats.values():
        pct = round(a["reel_total"] / a["theorique_total"] * 100) if a["theorique_total"] > 0 else None
        resultats.append(RapportSectionOut(
            section_nom=a["section_nom"], reel_total=a["reel_total"],
            theorique_total=a["theorique_total"], performance_moyenne=pct, nb_lignes=a["nb_lignes"],
        ))
    resultats.sort(key=lambda r: (r.performance_moyenne is None, -(r.performance_moyenne or 0)))
    return resultats


def rapport_vue_direction(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None, maintenant: Optional[datetime] = None,
) -> RapportDirectionOut:
    """Écran Rapports, onglet 'Vue Direction' (slide 14) : top/flop 5 lignes, pertes
    par cause, évolution quotidienne de la performance usine."""
    maintenant = maintenant or datetime.now()
    lignes = _lignes_du_perimetre(db, ligne_id, section_scope)
    ids = [l.id for l in lignes]
    rows = rapport_par_ligne(db, date_debut, date_fin, ligne_id, section_scope, maintenant)

    classables = [r for r in rows if r.performance_moyenne is not None]
    classables_tries = sorted(classables, key=lambda r: r.performance_moyenne, reverse=True)
    top = [TopFlopLigneOut(ligne_id=r.ligne_id, code=r.code, performance_moyenne=r.performance_moyenne) for r in classables_tries[:5]]
    flop = [TopFlopLigneOut(ligne_id=r.ligne_id, code=r.code, performance_moyenne=r.performance_moyenne) for r in classables_tries[-5:][::-1]]

    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)
    causes_par_id = {c.id: c.libelle for c in db.query(CauseArret).all()}
    duree_par_cause: dict[str, float] = {}
    for a, debut, fin in (arrets_de_periode(db, borne_debut, borne_fin, ids) if ids else []):
        libelle = causes_par_id.get(a.cause_id, "Inconnue")
        duree_par_cause[libelle] = duree_par_cause.get(libelle, 0) + minutes_entre(debut, fin)
    pertes_par_cause = sorted(
        (PerteCauseOut(cause=c, duree_min=round(d)) for c, d in duree_par_cause.items()),
        key=lambda p: p.duree_min, reverse=True,
    )

    perf = perf_ligne_jour(db, lignes, date_debut, date_fin, maintenant)
    evolution_quotidienne = []
    jour_courant = date_debut
    while jour_courant <= date_fin:
        jour_vals = [v for (_lid, j), v in perf.items() if j == jour_courant]
        reel_jour, theo_jour = sum(r for r, _t in jour_vals), sum(t for _r, t in jour_vals)
        evolution_quotidienne.append(EvolutionJourOut(jour=jour_courant, performance_pct=round(reel_jour / theo_jour * 100) if theo_jour > 0 else None))
        jour_courant += timedelta(days=1)

    return RapportDirectionOut(
        top=top, flop=flop, pertes_par_cause=pertes_par_cause,
        evolution_quotidienne=evolution_quotidienne, par_atelier=_rapport_par_section(db, rows),
    )

# =============================================================
# *** AJOUT 2026-09-23 *** : historique des scans (palettes) par opérateur -- écran
# Rapports (Direction, tous les opérateurs) et écran tablette "Mon historique"
# (opérateur/ouvrier, restreint à ses propres scans -- la restriction elle-même est
# faite dans reports_routes.py, pas ici : cette fonction se contente du filtre qu'on
# lui donne).
# =============================================================

def historique_scans(
    db: Session, date_debut: date, date_fin: date,
    operateur_id: int | None = None, ligne_id: int | None = None,
) -> list[HistoriqueScanOut]:
    """Une ligne par palette scannée, la plus récente en premier. `produit_nom` est
    absent quand la palette n'a pas de planning_detail_id (saisie un jour sans
    planning pour cette ligne, cf. la même remarque dans rapport_par_produit) --
    jointure externe, jamais une ligne perdue pour cette seule raison."""
    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)

    q = (
        db.query(Palette, LigneCache.code, LigneCache.section_nom, User.nom, User.matricule, ProduitCache.nom)
        .join(LigneCache, Palette.ligne_id == LigneCache.id)
        .join(User, Palette.operateur_id == User.id)
        .outerjoin(PlanningDetailCache, Palette.planning_detail_id == PlanningDetailCache.id)
        .outerjoin(ProduitCache, PlanningDetailCache.produit_id == ProduitCache.id)
        .filter(Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
    )
    if operateur_id:
        q = q.filter(Palette.operateur_id == operateur_id)
    if ligne_id:
        q = q.filter(Palette.ligne_id == ligne_id)
    q = q.order_by(Palette.created_at.desc())

    return [
        HistoriqueScanOut(
            id=palette.id, created_at=palette.created_at, ligne_id=palette.ligne_id,
            ligne_code=ligne_code, section_nom=section_nom, produit_nom=produit_nom, numero_lot=palette.numero_lot,
            nb_cartons=palette.nb_cartons, colisage_carton=palette.colisage_carton,
            quantite_totale=palette.quantite_totale, complete=palette.complete,
            motif_partielle=palette.motif_partielle, nb_rebuts=palette.nb_rebuts or 0, operateur_id=palette.operateur_id,
            operateur_nom=operateur_nom, operateur_matricule=operateur_matricule,
        )
        for palette, ligne_code, section_nom, operateur_nom, operateur_matricule, produit_nom in q.all()
    ]