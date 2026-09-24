from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..core.models import User
from ..models.production import (
    LigneCache, PerformanceLigneJour, Palette, Arret, CauseArret,
    PlanningDetailCache, ProduitCache,
)
from ..schemas.reports import (
    RapportLigneOut, RapportDirectionOut, TopFlopLigneOut, PerteCauseOut, EvolutionJourOut,
    RapportProduitOut, RapportSectionOut, HistoriqueScanOut,
)

# NB IMPORTANT (2026-09-17, ce fichier n'existait pas -- écrit à partir de ce
# qu'attendent reports_routes.py et RapportsView.vue) : les chiffres reel/theorique
# viennent de performance_ligne_jour, le snapshot figé chaque soir (23:50, cf.
# snapshot_service.py) -- PAS d'un calcul en direct pour le jour en cours, contrairement
# au cockpit Vue Usine. Concrètement : tant qu'aucun snapshot n'a encore été déclenché
# (POST /scoring/snapshot/run-now, ou le job planifié une fois activé), le jour
# d'aujourd'hui n'apparaît dans aucun rapport. À garder en tête pour le plan de test #4 :
# lancer un snapshot manuel avant de tester l'écran Rapports, sinon la période "7 derniers
# jours" par défaut peut remonter vide si aucun snapshot n'a jamais tourné.


def _bornes_jour(d: date) -> tuple[datetime, datetime]:
    """Bornes [00:00, 00:00 du lendemain[ pour un jour donné -- utilisé pour filtrer
    palettes/arrêts (tables horodatées en TIMESTAMP, pas en DATE)."""
    debut = datetime.combine(d, datetime.min.time())
    return debut, debut + timedelta(days=1)


def _agregat_ligne(db: Session, ligne: LigneCache, date_debut: date, date_fin: date) -> RapportLigneOut:
    snapshots = (
        db.query(PerformanceLigneJour)
        .filter(
            PerformanceLigneJour.ligne_id == ligne.id,
            PerformanceLigneJour.jour >= date_debut,
            PerformanceLigneJour.jour <= date_fin,
        )
        .all()
    )
    reel_total = sum(s.reel for s in snapshots)
    theorique_total = sum(s.theorique or 0 for s in snapshots)
    performance_moyenne = round(reel_total / theorique_total * 100) if theorique_total > 0 else None

    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)

    nb_palettes = (
        db.query(Palette)
        .filter(Palette.ligne_id == ligne.id, Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
        .count()
    )

    arrets = (
        db.query(Arret)
        .filter(Arret.ligne_id == ligne.id, Arret.heure_debut >= borne_debut, Arret.heure_debut < borne_fin)
        .all()
    )
    maintenant = datetime.now()
    temps_arret_min = round(sum(
        ((a.heure_fin or maintenant) - a.heure_debut).total_seconds() / 60 for a in arrets
    ))

    return RapportLigneOut(
        ligne_id=ligne.id, code=ligne.code, nom=ligne.nom,
        reel_total=reel_total, theorique_total=theorique_total,
        performance_moyenne=performance_moyenne, nb_palettes=nb_palettes,
        temps_arret_min=temps_arret_min,
    )


def rapport_par_ligne(db: Session, date_debut: date, date_fin: date) -> list[RapportLigneOut]:
    """Écran Rapports, onglet 'Par ligne' (slide 14) -- une ligne du tableau par ligne
    active, agrégée sur [date_debut, date_fin] inclus."""
    lignes = db.query(LigneCache).filter(LigneCache.actif.is_(True)).order_by(LigneCache.code).all()
    return [_agregat_ligne(db, ligne, date_debut, date_fin) for ligne in lignes]


def rapport_par_produit(db: Session, date_debut: date, date_fin: date) -> list[RapportProduitOut]:
    """*** NOUVEAU 2026-09-18 *** : écran Rapports, onglet 'Par produit' (slide 14).

    Agrégé depuis les palettes validées sur la période, rattachées à un produit via
    planning_detail_cache -- l'ancien "OF" (of_cache) n'est plus la source de vérité
    depuis la découverte du 2026-09-17 (of_id sur palettes est déprécié, NULL sur toute
    palette créée après cette date). Une palette sans planning_detail_id (saisie
    manuelle un jour sans planning pour cette ligne) n'est rattachable à aucun produit
    -- exclue de ce rapport plutôt que comptée sous un faux produit "inconnu", mais
    potentiellement significative si nombreuse : à surveiller au fil des tests."""
    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)

    rows = (
        db.query(PlanningDetailCache.produit_id, ProduitCache.nom, Palette)
        .join(PlanningDetailCache, Palette.planning_detail_id == PlanningDetailCache.id)
        .join(ProduitCache, PlanningDetailCache.produit_id == ProduitCache.id)
        .filter(Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
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
    """*** NOUVEAU 2026-09-18 *** : 'Performance par atelier' de la Vue Direction (slide
    14) -- regroupe le rapport 'par ligne' déjà calculé par section_nom. Fiable
    seulement depuis que section_nom est synchronisé depuis Odoo (2026-09-18, cf.
    investigate_sections.py) -- avant cette date, en partie manuel/vide, ce
    regroupement aurait été trompeur.

    Agrégation en somme(reel)/somme(theorique), pas une moyenne des % par ligne : une
    moyenne simple pondérerait à tort une petite ligne comme une grosse, cf. le même
    principe déjà appliqué à performance_usine_pct (dashboard_routes.get_vue_usine)."""
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


def rapport_vue_direction(db: Session, date_debut: date, date_fin: date) -> RapportDirectionOut:
    """Écran Rapports, onglet 'Vue Direction' (slide 14) : top/flop 5 lignes, pertes
    par cause, évolution quotidienne de la performance usine."""
    rows = rapport_par_ligne(db, date_debut, date_fin)

    # --- Top / flop 5 : seules les lignes avec une performance calculable entrent
    # dans le classement (une ligne sans aucun snapshot sur la période n'a rien à
    # montrer, ni en haut ni en bas de classement). ---
    classables = [r for r in rows if r.performance_moyenne is not None]
    classables_tries = sorted(classables, key=lambda r: r.performance_moyenne, reverse=True)
    top = [TopFlopLigneOut(ligne_id=r.ligne_id, code=r.code, performance_moyenne=r.performance_moyenne) for r in classables_tries[:5]]
    flop = [TopFlopLigneOut(ligne_id=r.ligne_id, code=r.code, performance_moyenne=r.performance_moyenne) for r in classables_tries[-5:][::-1]]

    # --- Pertes par cause (toutes lignes confondues, sur la période) ---
    borne_debut, _ = _bornes_jour(date_debut)
    _, borne_fin = _bornes_jour(date_fin)
    arrets = (
        db.query(Arret)
        .filter(Arret.heure_debut >= borne_debut, Arret.heure_debut < borne_fin)
        .all()
    )
    maintenant = datetime.now()
    causes_par_id = {c.id: c.libelle for c in db.query(CauseArret).all()}
    duree_par_cause: dict[str, float] = {}
    for a in arrets:
        libelle = causes_par_id.get(a.cause_id, "Inconnue")
        duree_min = ((a.heure_fin or maintenant) - a.heure_debut).total_seconds() / 60
        duree_par_cause[libelle] = duree_par_cause.get(libelle, 0) + duree_min
    pertes_par_cause = sorted(
        (PerteCauseOut(cause=c, duree_min=round(d)) for c, d in duree_par_cause.items()),
        key=lambda p: p.duree_min, reverse=True,
    )

    # --- Évolution quotidienne : performance usine agrégée (toutes lignes actives)
    # jour par jour sur la période, depuis les snapshots. ---
    evolution_quotidienne = []
    jour_courant = date_debut
    while jour_courant <= date_fin:
        snapshots_jour = (
            db.query(PerformanceLigneJour)
            .join(LigneCache, PerformanceLigneJour.ligne_id == LigneCache.id)
            .filter(PerformanceLigneJour.jour == jour_courant, LigneCache.actif.is_(True))
            .all()
        )
        reel_jour = sum(s.reel for s in snapshots_jour)
        theorique_jour = sum(s.theorique or 0 for s in snapshots_jour)
        pct = round(reel_jour / theorique_jour * 100) if theorique_jour > 0 else None
        evolution_quotidienne.append(EvolutionJourOut(jour=jour_courant, performance_pct=pct))
        jour_courant += timedelta(days=1)

    par_atelier = _rapport_par_section(db, rows)

    return RapportDirectionOut(
        top=top, flop=flop, pertes_par_cause=pertes_par_cause,
        evolution_quotidienne=evolution_quotidienne, par_atelier=par_atelier,
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
        db.query(Palette, LigneCache.code, User.nom, User.matricule, ProduitCache.nom)
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
            ligne_code=ligne_code, produit_nom=produit_nom, numero_lot=palette.numero_lot,
            nb_cartons=palette.nb_cartons, colisage_carton=palette.colisage_carton,
            quantite_totale=palette.quantite_totale, complete=palette.complete,
            motif_partielle=palette.motif_partielle, operateur_id=palette.operateur_id,
            operateur_nom=operateur_nom, operateur_matricule=operateur_matricule,
        )
        for palette, ligne_code, operateur_nom, operateur_matricule, produit_nom in q.all()
    ]
