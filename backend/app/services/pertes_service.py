"""
pertes_service.py -- pertes d'arrêt : durées plafonnées à la période, Pareto par cause,
coût estimé en FCFA.

*** NOUVEAU 2026-09-24 (Palier 0 de la roadmap) ***

RÈGLES DE DURÉE (corrigent un défaut de reports_service.py)
  Avant : un arrêt n'était retenu que si SON DÉBUT tombait dans la période, et il était
  compté en entier -- un arrêt encore ouvert comptait jusqu'à `now` même pour une période
  passée, un arrêt à cheval sur deux jours entièrement sur son jour de début.
  Maintenant : tout arrêt qui CHEVAUCHE la période est retenu, et seule la part comprise
  dans [début de période, fin de période[ est comptée (arrêt ouvert : jusqu'à
  min(now, fin de période)).

COÛT ESTIMÉ (paramétrable, jamais inventé)
  coût = minutes perdues PENDANT LES HEURES DE POSTE (hors pause programmée)
         × (Σ quantité planifiée × valeur d'une pièce, pour les produits planifiés ce
            jour-là sur cette ligne) ÷ (minutes nettes de poste)
  -> c'est la production que la ligne aurait dû sortir pendant l'arrêt, valorisée.
  Un arrêt hors heures de poste (ex. saisie oubliée ouverte la nuit) ne coûte rien : on
  ne perd pas de production quand personne ne devait produire. La DURÉE, elle, reste
  brute (plafonnée à la période) pour rester cohérente avec les autres écrans.
  La valeur d'une pièce = produits_cache.valeur_unitaire_fcfa si renseignée, sinon le
  paramètre valeur_piece_defaut_fcfa. Ce que « valeur » représente (prix de vente, coût
  de revient, marge) est un choix d'usage : libellé dans le paramètre libelle_valeur_piece.
  Quand le coût n'est pas calculable (pas de planning ce jour-là, poste non configuré, ou
  un produit sans aucune valeur), les minutes concernées sont comptées à part
  (`minutes_non_valorisees`) et le coût affiché est « n/d » plutôt qu'un chiffre sous-évalué :
  règle stricte -- si UN produit planifié ce jour-là n'a pas de valeur, le coût de ce
  jour-ligne n'est pas calculé.
"""
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..core import crud
from ..models.production import Arret, CauseArret, Equipement, LigneCache, ProduitCache
from ..schemas.reports import (
    ParetoArretsOut, ParetoCauseOut, ParetoLigneOut, ParetoEquipementOut,
)
from .ligne_helpers import get_planning_du_jour
from .performance_service import _bornes_poste_du_jour

LIBELLE_VALEUR_DEFAUT = "Valeur unitaire"


# ---------------------------------------------------------------------------
# Durées plafonnées à la période
# ---------------------------------------------------------------------------

def bornes_periode(date_debut: date, date_fin: date) -> tuple[datetime, datetime]:
    """[00:00 du premier jour, 00:00 du lendemain du dernier jour[."""
    debut = datetime.combine(date_debut, time.min)
    return debut, datetime.combine(date_fin, time.min) + timedelta(days=1)


def minutes_entre(debut: datetime, fin: datetime) -> float:
    return (fin - debut).total_seconds() / 60


def arrets_de_periode(
    db: Session, borne_debut: datetime, borne_fin: datetime,
    ligne_ids: Optional[list[int]] = None, maintenant: Optional[datetime] = None,
) -> list[tuple[Arret, datetime, datetime]]:
    """Arrêts qui chevauchent [borne_debut, borne_fin[, chacun avec son intervalle
    EFFECTIF (plafonné aux bornes). Un arrêt entièrement hors période, ou de durée nulle
    une fois plafonné, n'est pas retourné."""
    maintenant = maintenant or datetime.now()
    q = db.query(Arret).options(joinedload(Arret.equipement)).filter(
        Arret.heure_debut < borne_fin,
        or_(Arret.heure_fin.is_(None), Arret.heure_fin > borne_debut),
    )
    if ligne_ids is not None:
        q = q.filter(Arret.ligne_id.in_(ligne_ids))
    resultats = []
    for a in q.all():
        debut_eff = max(a.heure_debut, borne_debut)
        fin_eff = min(a.heure_fin or maintenant, borne_fin)
        if fin_eff > debut_eff:
            resultats.append((a, debut_eff, fin_eff))
    return resultats


# ---------------------------------------------------------------------------
# Valorisation (coût estimé)
# ---------------------------------------------------------------------------

def _recouvrement(d1: datetime, f1: datetime, d2: datetime, f2: datetime) -> float:
    """Minutes communes à [d1,f1] et [d2,f2] (0 si disjoints)."""
    debut, fin = max(d1, d2), min(f1, f2)
    return max(0.0, minutes_entre(debut, fin)) if fin > debut else 0.0


def minutes_productives(seg_debut: datetime, seg_fin: datetime, jour: date, bornes: dict) -> float:
    """Minutes du segment situées dans le poste du jour, moins la pause programmée.
    (Extrait de _Valorisation le 2026-09-24 pour être partagé avec trs_service.)"""
    p_debut = datetime.combine(jour, bornes["heure_debut"])
    p_fin = datetime.combine(jour, bornes["heure_fin"])
    d, f = max(seg_debut, p_debut), min(seg_fin, p_fin)
    if f <= d:
        return 0.0
    total = minutes_entre(d, f)
    if bornes.get("pause_debut") and bornes.get("pause_fin"):
        total -= _recouvrement(d, f, datetime.combine(jour, bornes["pause_debut"]),
                               datetime.combine(jour, bornes["pause_fin"]))
    return max(0.0, total)


class _Valorisation:
    """Cache des lectures nécessaires au coût (poste du jour, planning, valeurs) -- un
    même jour/ligne revient pour de nombreux arrêts, on ne le relit pas."""

    def __init__(self, db: Session):
        self.db = db
        self._postes: dict[date, Optional[dict]] = {}
        self._cout_minute: dict[tuple[int, date], Optional[float]] = {}
        self._produits: dict[int, Optional[float]] = {}
        try:
            self.valeur_defaut = float(crud.get_param(db, "valeur_piece_defaut_fcfa") or 0)
        except ValueError:
            self.valeur_defaut = 0.0

    def poste(self, jour: date) -> Optional[dict]:
        if jour not in self._postes:
            self._postes[jour] = _bornes_poste_du_jour(self.db, jour)
        return self._postes[jour]

    def _valeur_produit(self, produit_id: Optional[int]) -> float:
        """Valeur d'une pièce pour ce produit, 0.0 si aucune (ni propre ni par défaut)."""
        if produit_id is not None:
            if produit_id not in self._produits:
                p = self.db.query(ProduitCache.valeur_unitaire_fcfa).filter(ProduitCache.id == produit_id).first()
                self._produits[produit_id] = float(p[0]) if p and p[0] is not None else None
            propre = self._produits[produit_id]
            if propre is not None:
                return propre
        return self.valeur_defaut

    def cout_par_minute(self, ligne_id: int, jour: date, bornes: dict) -> Optional[float]:
        cle = (ligne_id, jour)
        if cle in self._cout_minute:
            return self._cout_minute[cle]

        p_debut = datetime.combine(jour, bornes["heure_debut"])
        p_fin = datetime.combine(jour, bornes["heure_fin"])
        duree_pause = 0.0
        if bornes.get("pause_debut") and bornes.get("pause_fin"):
            duree_pause = max(0.0, minutes_entre(
                datetime.combine(jour, bornes["pause_debut"]), datetime.combine(jour, bornes["pause_fin"])))
        minutes_nettes = minutes_entre(p_debut, p_fin) - duree_pause

        resultat: Optional[float] = None
        items = get_planning_du_jour(self.db, ligne_id, jour)
        if items and minutes_nettes > 0:
            total, complet = 0.0, True
            for item in items:
                qty = float(item.qty or 0)
                if qty <= 0:
                    continue
                valeur = self._valeur_produit(item.produit_id)
                if valeur <= 0:
                    complet = False  # règle stricte : pas de coût sous-évalué
                    break
                total += qty * valeur
            if complet and total > 0:
                resultat = total / minutes_nettes
        self._cout_minute[cle] = resultat
        return resultat

    def minutes_productives(self, seg_debut: datetime, seg_fin: datetime, jour: date, bornes: dict) -> float:
        return minutes_productives(seg_debut, seg_fin, jour, bornes)

    def valoriser(self, ligne_id: int, debut: datetime, fin: datetime) -> tuple[float, float, float]:
        """(coût FCFA, minutes valorisées, minutes non valorisables) pour l'intervalle
        effectif d'un arrêt, découpé jour par jour (un arrêt peut passer minuit)."""
        cout = minutes_val = minutes_non = 0.0
        jour = debut.date()
        dernier = (fin - timedelta(microseconds=1)).date()
        while jour <= dernier:
            seg_d = max(debut, datetime.combine(jour, time.min))
            seg_f = min(fin, datetime.combine(jour + timedelta(days=1), time.min))
            bornes = self.poste(jour)
            if bornes is None:
                minutes_non += minutes_entre(seg_d, seg_f)          # poste non configuré
            elif bornes.get("ferme"):
                pass                                                 # usine fermée : rien perdu
            else:
                prod = self.minutes_productives(seg_d, seg_f, jour, bornes)
                if prod > 0:
                    cpm = self.cout_par_minute(ligne_id, jour, bornes)
                    if cpm is None:
                        minutes_non += prod
                    else:
                        cout += prod * cpm
                        minutes_val += prod
            jour += timedelta(days=1)
        return cout, minutes_val, minutes_non


def _valorisation_configuree(db: Session, valeur_defaut: float) -> bool:
    if valeur_defaut > 0:
        return True
    return db.query(ProduitCache.id).filter(ProduitCache.valeur_unitaire_fcfa > 0).first() is not None


def _libelle_equipement(e: Optional[Equipement]) -> str:
    if e is None:
        return "Non précisé"
    numero = f"({e.numero_interne})" if e.numero_interne else ""
    return " ".join(x for x in (e.type, e.marque, numero) if x)


class _Agregat:
    """Somme de durée, nombre d'arrêts et coût, avec la distinction « coût inconnu » /
    « coût nul » (aucune minute valorisée ET des minutes non valorisables -> n/d)."""
    __slots__ = ("duree", "nb", "cout", "min_val", "min_non")

    def __init__(self):
        self.duree = self.cout = self.min_val = self.min_non = 0.0
        self.nb = 0

    def ajouter(self, duree: float, cout: float, min_val: float, min_non: float) -> None:
        self.duree += duree
        self.nb += 1
        self.cout += cout
        self.min_val += min_val
        self.min_non += min_non

    def cout_out(self, configure: bool) -> Optional[int]:
        if not configure or (self.min_val == 0 and self.min_non > 0):
            return None
        return round(self.cout)


# ---------------------------------------------------------------------------
# Pareto
# ---------------------------------------------------------------------------

def pareto_arrets(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None,
    maintenant: Optional[datetime] = None,
) -> ParetoArretsOut:
    """Pareto des causes d'arrêt sur [date_debut, date_fin] inclus : cause, durée, %,
    % cumulé, coût estimé, et détail par ligne et par équipement.

    `section_scope` : périmètre d'un Chef d'équipe (une seule section) -- même règle que
    dashboard_routes.get_vue_usine. `ligne_id` : filtre optionnel sur une ligne."""
    borne_debut, borne_fin = bornes_periode(date_debut, date_fin)
    maintenant = maintenant or datetime.now()

    ligne_ids: Optional[list[int]] = None
    if section_scope or ligne_id:
        q = db.query(LigneCache.id)
        if section_scope:
            q = q.filter(LigneCache.section_nom == section_scope)
        if ligne_id:
            q = q.filter(LigneCache.id == ligne_id)
        ligne_ids = [r[0] for r in q.all()]

    valo = _Valorisation(db)
    configure = _valorisation_configuree(db, valo.valeur_defaut)
    libelle = crud.get_param(db, "libelle_valeur_piece") or LIBELLE_VALEUR_DEFAUT

    causes_libelle = {c.id: c.libelle for c in db.query(CauseArret).all()}
    codes_lignes = {l.id: l.code for l in db.query(LigneCache).all()}

    par_cause: dict[int, _Agregat] = {}
    par_cause_ligne: dict[int, dict[int, _Agregat]] = {}
    par_cause_equip: dict[int, dict[str, _Agregat]] = {}
    total = _Agregat()
    non_clotures = 0

    for arret, debut_eff, fin_eff in arrets_de_periode(db, borne_debut, borne_fin, ligne_ids, maintenant):
        duree = minutes_entre(debut_eff, fin_eff)
        if arret.heure_fin is None:
            non_clotures += 1
        cout, m_val, m_non = valo.valoriser(arret.ligne_id, debut_eff, fin_eff)

        for agregat in (
            par_cause.setdefault(arret.cause_id, _Agregat()),
            par_cause_ligne.setdefault(arret.cause_id, {}).setdefault(arret.ligne_id, _Agregat()),
            total,
        ):
            agregat.ajouter(duree, cout, m_val, m_non)
        # Le détail par équipement ne porte pas de coût (le coût est celui de la ligne,
        # pas de la machine) -- durée et nombre seulement.
        par_cause_equip.setdefault(arret.cause_id, {}).setdefault(
            _libelle_equipement(arret.equipement), _Agregat()).ajouter(duree, 0.0, 0.0, 0.0)

    ordre = sorted(par_cause.items(), key=lambda kv: (-kv[1].duree, causes_libelle.get(kv[0], "")))
    causes_out: list[ParetoCauseOut] = []
    cumul = 0.0
    for rang, (cause_id, ag) in enumerate(ordre, start=1):
        cumul += ag.duree
        causes_out.append(ParetoCauseOut(
            rang=rang, cause_id=cause_id, cause=causes_libelle.get(cause_id, "Inconnue"),
            duree_min=round(ag.duree), nb_arrets=ag.nb,
            pct=round(ag.duree / total.duree * 100, 1) if total.duree else 0.0,
            pct_cumule=round(cumul / total.duree * 100, 1) if total.duree else 0.0,
            cout_fcfa=ag.cout_out(configure), minutes_non_valorisees=round(ag.min_non),
            par_ligne=[
                ParetoLigneOut(
                    ligne_id=lid, ligne_code=codes_lignes.get(lid, str(lid)),
                    duree_min=round(a.duree), nb_arrets=a.nb, cout_fcfa=a.cout_out(configure))
                for lid, a in sorted(par_cause_ligne[cause_id].items(), key=lambda kv: -kv[1].duree)
            ],
            par_equipement=[
                ParetoEquipementOut(equipement=nom, duree_min=round(a.duree), nb_arrets=a.nb)
                for nom, a in sorted(par_cause_equip[cause_id].items(), key=lambda kv: -kv[1].duree)
            ],
        ))

    return ParetoArretsOut(
        date_debut=date_debut, date_fin=date_fin,
        total_duree_min=round(total.duree), total_nb_arrets=total.nb,
        total_cout_fcfa=total.cout_out(configure), minutes_non_valorisees=round(total.min_non),
        valorisation_configuree=configure, libelle_valeur=libelle,
        nb_arrets_non_clotures=non_clotures, causes=causes_out,
    )
