"""
scoring_service.py -- scoring d'ÉQUIPE et suivi individuel de formation.
*** REFONDU 2026-09-24 (Palier 2) *** sur le modèle « scoring légalement cadré » (diapo 13 du
document d'Opus, tel que résumé dans le récap du 23/09). Remplace l'ancien classement
NOMINATIF de chaque CDI/CDD (rang, matricule, nom, score par personne), supprimé.

LES QUATRE RÈGLES
  1. Le score est porté par l'ÉQUIPE / la LIGNE, jamais par l'individu. Aucun nom, aucun
     matricule, aucun rang de personne dans le score d'équipe ; aucune distinction CDI/CDD.
  2. Les arrêts NON IMPUTABLES sont neutralisés AVANT le calcul : le temps qu'ils occupent
     est retiré de ce qu'on attend de l'équipe. Seules les causes marquées « imputable à
     l'équipe » (causes_arret.imputable_equipe) comptent contre elle. Par défaut, aucune :
     tant que la Direction ne l'a pas décidé, rien n'est reproché à une équipe.
  3. Rien de nominatif à l'écran d'atelier : l'Andon et les endpoints de tablette ne
     renvoient aucun nom de personne (garanti par un test qui parcourt la réponse).
  4. Le suivi individuel est réservé à une permission distincte (view_suivi_individuel), sert
     à la FORMATION (il décrit le résultat des équipes pendant la présence de la personne,
     ni un score personnel ni un classement), et chaque consultation est journalisée.

DÉFINITION DU SCORE (par ligne et par jour, puis agrégé)
  Attendu = Q x (minutes nettes de poste - minutes d'arrêt NON imputables) / minutes nettes
  Produit = pièces conformes + rebuts déclarés
  Score   = Produit / Attendu           (100 % = plan tenu une fois les arrêts non imputables retirés)
  Agrégation : Somme(Produit) / Somme(Attendu) -- pondéré par ce qui était attendu.

  Les rebuts sont comptés DANS le produit : les compter contre l'équipe l'inciterait à ne pas
  les déclarer, ce qui fausserait la Qualité du TRS. La qualité se suit dans Rapports > TRS,
  pas dans le score d'équipe.

MASQUAGE : une « équipe » de une ou deux personnes identifierait quelqu'un. Sous
`scoring_equipe_effectif_min` personnes distinctes affectées à la ligne sur la période
(défaut 3), le score de la ligne n'est pas affiché. Affectations non renseignées (effectif 0)
-> score affiché, effectif « non renseigné ».

Seuls les jours COMPLETS comptent (poste terminé), comme pour le TRS.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core import crud
from ..core.models import User
from ..models.production import AffectationLigne, CauseArret, LigneCache, Palette
from ..schemas.scoring import (
    EquipeLigneOut, EquipeScoringOut, EquipeTotalOut, SuiviIndividuelOut, SuiviLigneOut, SuiviPersonneOut,
)
from .ligne_helpers import get_planning_du_jour
from .pertes_service import arrets_de_periode, bornes_periode, minutes_entre, minutes_productives
from .performance_service import _bornes_poste_du_jour

EFFECTIF_MIN_DEFAUT = 3
AVERTISSEMENT_SUIVI = (
    "Ces chiffres décrivent le résultat des ÉQUIPES pendant la présence de la personne. Ils ne "
    "constituent ni un score individuel ni un classement, et ne doivent servir qu'à repérer des "
    "besoins de formation. Cette consultation est enregistrée."
)


def _effectif_min(db: Session) -> int:
    try:
        return max(0, int(float(crud.get_param(db, "scoring_equipe_effectif_min") or EFFECTIF_MIN_DEFAUT)))
    except ValueError:
        return EFFECTIF_MIN_DEFAUT


def _resultats_ligne_jour(db: Session, lignes: list[LigneCache], d0: date, d1: date, maintenant: datetime) -> dict:
    """{(ligne_id, jour): {attendu, produit, min_imputables, min_neutralisees}} pour les seuls
    jours complets, ouverts, avec planning > 0 et un attendu > 0."""
    ids = [l.id for l in lignes]
    if not ids:
        return {}
    imputable = {c.id: bool(c.imputable_equipe) for c in db.query(CauseArret).all()}
    borne_debut, borne_fin = bornes_periode(d0, d1)

    produit: dict[tuple[int, date], float] = {}
    for lid, jour, conforme, rebuts in (
        db.query(Palette.ligne_id, func.date(Palette.created_at),
                 func.coalesce(func.sum(Palette.quantite_totale), 0), func.coalesce(func.sum(Palette.nb_rebuts), 0))
        .filter(Palette.ligne_id.in_(ids), Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
        .group_by(Palette.ligne_id, func.date(Palette.created_at)).all()
    ):
        produit[(lid, jour)] = float(conforme) + float(rebuts)

    arrets: dict[int, list] = defaultdict(list)
    for a, d, f in arrets_de_periode(db, borne_debut, borne_fin, ids, maintenant):
        arrets[a.ligne_id].append((d, f, imputable.get(a.cause_id, False)))

    resultats = {}
    jour = d0
    while jour <= d1:
        bornes = _bornes_poste_du_jour(db, jour)
        if bornes is None or bornes.get("ferme") or maintenant < datetime.combine(jour, bornes["heure_fin"]):
            jour += timedelta(days=1); continue
        pause = 0.0
        if bornes.get("pause_debut") and bornes.get("pause_fin"):
            pause = max(0.0, minutes_entre(datetime.combine(jour, bornes["pause_debut"]), datetime.combine(jour, bornes["pause_fin"])))
        min_net = minutes_entre(datetime.combine(jour, bornes["heure_debut"]), datetime.combine(jour, bornes["heure_fin"])) - pause
        j0, j1 = datetime.combine(jour, time.min), datetime.combine(jour + timedelta(days=1), time.min)
        for l in lignes:
            qty = sum(float(i.qty or 0) for i in get_planning_du_jour(db, l.id, jour))
            if qty <= 0 or min_net <= 0:
                continue
            m_imp = m_neutre = 0.0
            for d, f, est_imputable in arrets.get(l.id, []):
                sd, sf = max(d, j0), min(f, j1)
                if sf > sd:
                    minutes = minutes_productives(sd, sf, jour, bornes)
                    if est_imputable: m_imp += minutes
                    else: m_neutre += minutes
            m_neutre = min(m_neutre, min_net)
            attendu = qty * (min_net - m_neutre) / min_net
            if attendu <= 0:
                continue   # journée entièrement neutralisée : rien à juger
            resultats[(l.id, jour)] = {"attendu": attendu, "produit": produit.get((l.id, jour), 0.0),
                                       "min_imputables": m_imp, "min_neutralisees": m_neutre}
        jour += timedelta(days=1)
    return resultats


def _effectifs(db: Session, ligne_ids: list[int], d0: date, d1: date) -> dict[int, int]:
    """Nombre de personnes DISTINCTES affectées à chaque ligne sur la période (un nombre,
    jamais une liste de noms)."""
    if not ligne_ids:
        return {}
    debut, fin = datetime.combine(d0, time.min), datetime.combine(d1 + timedelta(days=1), time.min)
    rows = (
        db.query(AffectationLigne.ligne_id, func.count(func.distinct(AffectationLigne.user_id)))
        .filter(AffectationLigne.ligne_id.in_(ligne_ids), AffectationLigne.date_debut < fin,
                (AffectationLigne.date_fin.is_(None)) | (AffectationLigne.date_fin > debut))
        .group_by(AffectationLigne.ligne_id).all()
    )
    return {lid: n for lid, n in rows}


def _lignes_du_perimetre(db: Session, ligne_id: Optional[int], section_scope: Optional[str]) -> list[LigneCache]:
    q = db.query(LigneCache).filter(LigneCache.actif.is_(True))
    if section_scope:
        q = q.filter(LigneCache.section_nom == section_scope)
    if ligne_id:
        q = q.filter(LigneCache.id == ligne_id)
    return q.order_by(LigneCache.code).all()


def _masque(effectif: int, seuil: int) -> bool:
    return seuil > 0 and 1 <= effectif < seuil


def scoring_equipes(
    db: Session, d0: date, d1: date, ligne_id: Optional[int] = None, section_scope: Optional[str] = None,
    maintenant: Optional[datetime] = None,
) -> EquipeScoringOut:
    maintenant = maintenant or datetime.now()
    lignes = _lignes_du_perimetre(db, ligne_id, section_scope)
    seuil = _effectif_min(db)
    res = _resultats_ligne_jour(db, lignes, d0, d1, maintenant)
    effectifs = _effectifs(db, [l.id for l in lignes], d0, d1)
    imputables = [c.libelle for c in db.query(CauseArret).filter(CauseArret.imputable_equipe.is_(True), CauseArret.actif.is_(True)).order_by(CauseArret.ordre_affichage)]

    sorties, tot_att, tot_prod = [], 0.0, 0.0
    for l in lignes:
        jours = [(k[1], v) for k, v in res.items() if k[0] == l.id]
        if not jours:
            continue
        att = sum(v["attendu"] for _, v in jours); prod = sum(v["produit"] for _, v in jours)
        eff = effectifs.get(l.id, 0)
        cache = _masque(eff, seuil)
        sorties.append(EquipeLigneOut(
            ligne_id=l.id, code=l.code, nom=l.nom, section_nom=l.section_nom, jours=len(jours),
            effectif=eff or None, score_pct=None if cache or att <= 0 else round(prod / att * 100, 1),
            attendu=round(att), produit=round(prod),
            minutes_arret_imputables=round(sum(v["min_imputables"] for _, v in jours)),
            minutes_neutralisees=round(sum(v["min_neutralisees"] for _, v in jours)),
            masque=cache,
            masque_raison=f"Équipe de moins de {seuil} personnes : score non affiché pour ne désigner personne." if cache else None,
        ))
        if not cache:                      # le total ne doit pas trahir une ligne masquée
            tot_att += att; tot_prod += prod
    return EquipeScoringOut(
        date_debut=d0, date_fin=d1, nb_jours=len({k[1] for k in res}), effectif_min=seuil,
        causes_imputables=imputables, aucune_cause_imputable=not imputables,
        total=EquipeTotalOut(score_pct=round(tot_prod / tot_att * 100, 1) if tot_att > 0 else None,
                             attendu=round(tot_att), produit=round(tot_prod)),
        lignes=sorties,
    )


# ----------------------------------------------------------------------------------
# Suivi individuel (formation)
# ----------------------------------------------------------------------------------

def _personnes_du_perimetre(db: Session, section_scope: Optional[str]):
    q = db.query(User).filter(User.id.in_(db.query(AffectationLigne.user_id)), User.user_type.in_(("operateur", "ouvrier")))
    if section_scope:
        lignes = db.query(LigneCache.id).filter(LigneCache.section_nom == section_scope)
        q = db.query(User).filter(
            User.id.in_(db.query(AffectationLigne.user_id).filter(AffectationLigne.ligne_id.in_(lignes))),
            User.user_type.in_(("operateur", "ouvrier")))
    return q


def liste_personnes_suivi(db: Session, section_scope: Optional[str]) -> list[SuiviPersonneOut]:
    """Ordre ALPHABÉTIQUE, sans aucune valeur chiffrée : cette liste ne peut pas servir de classement."""
    return [SuiviPersonneOut(user_id=u.id, nom=u.nom, matricule=u.matricule)
            for u in _personnes_du_perimetre(db, section_scope).order_by(User.nom).all()]


def personne_dans_perimetre(db: Session, user_id: int, section_scope: Optional[str]) -> bool:
    return _personnes_du_perimetre(db, section_scope).filter(User.id == user_id).first() is not None


def suivi_individuel(
    db: Session, user: User, d0: date, d1: date, section_scope: Optional[str] = None, maintenant: Optional[datetime] = None,
) -> SuiviIndividuelOut:
    maintenant = maintenant or datetime.now()
    debut, fin = datetime.combine(d0, time.min), datetime.combine(d1 + timedelta(days=1), time.min)
    affs = (db.query(AffectationLigne).filter(AffectationLigne.user_id == user.id, AffectationLigne.date_debut < fin,
            (AffectationLigne.date_fin.is_(None)) | (AffectationLigne.date_fin > debut)).all())

    # heures de présence par (ligne, jour)
    presence: dict[tuple[int, date], float] = defaultdict(float)
    for a in affs:
        a_debut, a_fin = max(a.date_debut, debut), min(a.date_fin or maintenant, fin, maintenant)
        jour = a_debut.date()
        while jour <= a_fin.date():
            j0 = datetime.combine(jour, time.min)
            h = (min(a_fin, j0 + timedelta(days=1)) - max(a_debut, j0)).total_seconds() / 3600
            if h > 0:
                presence[(a.ligne_id, jour)] += h
            jour += timedelta(days=1)

    lignes = {l.id: l for l in db.query(LigneCache).filter(LigneCache.id.in_({k[0] for k in presence})).all()} if presence else {}
    res = _resultats_ligne_jour(db, list(lignes.values()), d0, d1, maintenant)
    seuil = _effectif_min(db)
    effectifs = _effectifs(db, list(lignes), d0, d1)

    par_ligne, tot_att, tot_prod = [], 0.0, 0.0
    for lid, l in sorted(lignes.items(), key=lambda kv: kv[1].code):
        jours = sorted(j for (i, j) in presence if i == lid)
        heures = sum(presence[(lid, j)] for j in jours)
        cache = _masque(effectifs.get(lid, 0), seuil)
        rl = [res[(lid, j)] for j in jours if (lid, j) in res]
        att, prod = sum(r["attendu"] for r in rl), sum(r["produit"] for r in rl)
        par_ligne.append(SuiviLigneOut(
            ligne_code=l.code, ligne_nom=l.nom, jours_presence=len(jours), heures=round(heures, 1),
            resultat_equipe_pct=None if cache or att <= 0 else round(prod / att * 100, 1), equipe_masquee=cache))
        if not cache:
            tot_att += att; tot_prod += prod
    return SuiviIndividuelOut(
        user_id=user.id, nom=user.nom, matricule=user.matricule, date_debut=d0, date_fin=d1,
        heures_totales=round(sum(presence.values()), 1), lignes=par_ligne,
        resultat_equipe_pct=round(tot_prod / tot_att * 100, 1) if tot_att > 0 else None,
        avertissement=AVERTISSEMENT_SUIVI,
    )
