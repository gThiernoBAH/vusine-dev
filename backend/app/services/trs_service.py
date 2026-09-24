"""
trs_service.py -- TRS (Taux de Rendement Synthétique / OEE) décomposé en
Disponibilité x Performance x Qualité. *** NOUVEAU 2026-09-24 (Palier 1) ***

DÉFINITIONS (par ligne et par jour, puis agrégées)
  Q       = quantité planifiée du jour (somme des items du planning confirmé)
  Dispo   = (minutes nettes de poste - minutes d'arrêt pendant le poste) / minutes nettes
  Q_run   = Q x Dispo            (ce que la ligne aurait dû sortir pendant qu'elle tournait)
  Brut    = conforme + rebuts    (conforme = palettes.quantite_totale ; rebuts = nb_rebuts)
  Perf    = Brut / Q_run         (peut dépasser 100 % si la cadence planifiée est prudente)
  Qualité = conforme / Brut
  TRS     = Dispo x Perf x Qualité = conforme / Q   (identité exacte)

  Agrégation sur plusieurs jours/lignes : sommes pondérées par la quantité planifiée
  (Dispo = Somme(Q_run) / Somme(Q), Perf = Somme(Brut) / Somme(Q_run), Qualité =
  Somme(conforme) / Somme(Brut)) -- l'identité TRS = D x P x Q reste exacte, ce qu'une
  moyenne de pourcentages ne garantirait pas.

PÉRIMÈTRE
  Seuls les jours COMPLETS comptent (poste terminé) : aujourd'hui, avant la fin de poste, est
  exclu -- mesurer une journée en cours écraserait le TRS. Les jours fermés (jours spéciaux)
  et les couples ligne/jour sans planning sont exclus ; les pièces produites hors planning
  sont signalées (`pieces_hors_planning`) plutôt que perdues en silence.

QUALITÉ : tant qu'aucun rebut n'est déclaré sur la période, Qualité = 100 % est un DÉFAUT,
pas une mesure (`qualite_renseignee` = False) -- à afficher comme tel.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core import crud
from ..models.production import LigneCache, Palette
from ..schemas.reports import TrsJourOut, TrsLigneOut, TrsOut
from .ligne_helpers import get_planning_du_jour
from .pertes_service import arrets_de_periode, bornes_periode, minutes_entre, minutes_productives
from .performance_service import _bornes_poste_du_jour

CIBLE_TRS_DEFAUT = 85.0  # référence « classe mondiale » usuelle, paramétrable (trs_cible_pct)


def _pct(num: float, den: float) -> Optional[float]:
    return round(num / den * 100, 1) if den > 0 else None


class _Acc:
    __slots__ = ("qty", "q_run", "conforme", "rebuts", "min_net", "min_arret", "jours")

    def __init__(self):
        self.qty = self.q_run = self.conforme = self.rebuts = self.min_net = self.min_arret = 0.0
        self.jours = 0

    def ajouter(self, qty, q_run, conforme, rebuts, min_net, min_arret):
        self.qty += qty; self.q_run += q_run; self.conforme += conforme; self.rebuts += rebuts
        self.min_net += min_net; self.min_arret += min_arret; self.jours += 1

    def fusionner(self, autre: "_Acc"):
        self.qty += autre.qty; self.q_run += autre.q_run; self.conforme += autre.conforme
        self.rebuts += autre.rebuts; self.min_net += autre.min_net; self.min_arret += autre.min_arret

    @property
    def brut(self):
        return self.conforme + self.rebuts

    def facteurs(self):
        return (_pct(self.q_run, self.qty), _pct(self.brut, self.q_run),
                _pct(self.conforme, self.brut), _pct(self.conforme, self.qty))


def _ligne_out(ligne_id, code, nom, acc: _Acc, jours: int) -> TrsLigneOut:
    dispo, perf, qualite, trs = acc.facteurs()
    return TrsLigneOut(
        ligne_id=ligne_id, code=code, nom=nom, jours=jours,
        qte_planifiee=round(acc.qty), production_conforme=round(acc.conforme), rebuts=round(acc.rebuts),
        minutes_arret=round(acc.min_arret),
        disponibilite_pct=dispo, performance_pct=perf, qualite_pct=qualite, trs_pct=trs,
        pertes_arrets_pieces=round(acc.qty - acc.q_run),
        pertes_cadence_pieces=round(acc.q_run - acc.brut),
        pertes_rebuts_pieces=round(acc.rebuts),
    )


def calculer_trs(
    db: Session, date_debut: date, date_fin: date,
    ligne_id: Optional[int] = None, section_scope: Optional[str] = None,
    maintenant: Optional[datetime] = None,
) -> TrsOut:
    maintenant = maintenant or datetime.now()
    try:
        cible = float(crud.get_param(db, "trs_cible_pct") or CIBLE_TRS_DEFAUT)
    except ValueError:
        cible = CIBLE_TRS_DEFAUT

    q = db.query(LigneCache).filter(LigneCache.actif.is_(True))
    if section_scope:
        q = q.filter(LigneCache.section_nom == section_scope)
    if ligne_id:
        q = q.filter(LigneCache.id == ligne_id)
    lignes = q.order_by(LigneCache.code).all()
    ids = [l.id for l in lignes]

    borne_debut, borne_fin = bornes_periode(date_debut, date_fin)

    # Palettes de la période, agrégées par (ligne, jour) : une seule requête.
    palettes: dict[tuple[int, date], tuple[float, float]] = {}
    if ids:
        for lid, jour, conforme, rebuts in (
            db.query(Palette.ligne_id, func.date(Palette.created_at),
                     func.coalesce(func.sum(Palette.quantite_totale), 0), func.coalesce(func.sum(Palette.nb_rebuts), 0))
            .filter(Palette.ligne_id.in_(ids), Palette.created_at >= borne_debut, Palette.created_at < borne_fin)
            .group_by(Palette.ligne_id, func.date(Palette.created_at)).all()
        ):
            palettes[(lid, jour)] = (float(conforme), float(rebuts))

    arrets_par_ligne: dict[int, list] = defaultdict(list)
    if ids:
        for a, d, f in arrets_de_periode(db, borne_debut, borne_fin, ids, maintenant):
            arrets_par_ligne[a.ligne_id].append((d, f))

    par_ligne: dict[int, _Acc] = {l.id: _Acc() for l in lignes}
    par_jour: dict[date, _Acc] = {}
    jours_pris = set()
    jour_en_cours_exclu = False
    utilises: set[tuple[int, date]] = set()
    jours_termines: set[date] = set()   # jours dont on peut juger la production (poste fini, ouvert OU fermé)

    jour = date_debut
    while jour <= date_fin:
        bornes = _bornes_poste_du_jour(db, jour)
        if bornes is None:
            jour += timedelta(days=1); continue   # aucun poste configuré : impossible de juger ce jour
        if bornes.get("ferme"):
            jours_termines.add(jour)              # production un jour fermé : à signaler, pas à compter
            jour += timedelta(days=1); continue
        p_debut = datetime.combine(jour, bornes["heure_debut"])
        p_fin = datetime.combine(jour, bornes["heure_fin"])
        if maintenant < p_fin:
            jour_en_cours_exclu = jour_en_cours_exclu or jour == maintenant.date()
            jour += timedelta(days=1); continue   # journée non terminée (ou future)
        jours_termines.add(jour)
        pause = 0.0
        if bornes.get("pause_debut") and bornes.get("pause_fin"):
            pause = max(0.0, minutes_entre(datetime.combine(jour, bornes["pause_debut"]),
                                           datetime.combine(jour, bornes["pause_fin"])))
        min_net = minutes_entre(p_debut, p_fin) - pause
        j_debut, j_fin = datetime.combine(jour, time.min), datetime.combine(jour + timedelta(days=1), time.min)

        for ligne in lignes:
            qty = sum(float(i.qty or 0) for i in get_planning_du_jour(db, ligne.id, jour))
            if qty <= 0 or min_net <= 0:
                continue
            min_arret = 0.0
            for d, f in arrets_par_ligne.get(ligne.id, []):
                seg_d, seg_f = max(d, j_debut), min(f, j_fin)
                if seg_f > seg_d:
                    min_arret += minutes_productives(seg_d, seg_f, jour, bornes)
            min_arret = min(min_arret, min_net)
            q_run = qty * (min_net - min_arret) / min_net
            conforme, rebuts = palettes.get((ligne.id, jour), (0.0, 0.0))
            utilises.add((ligne.id, jour))
            par_ligne[ligne.id].ajouter(qty, q_run, conforme, rebuts, min_net, min_arret)
            par_jour.setdefault(jour, _Acc()).ajouter(qty, q_run, conforme, rebuts, min_net, min_arret)
            jours_pris.add(jour)
        jour += timedelta(days=1)

    # Production d'un jour TERMINÉ sans planning pour cette ligne, ou un jour fermé. Le jour en
    # cours n'en fait pas partie : sa production n'est pas « hors planning », elle est simplement
    # pas encore évaluée (corrigé le 2026-09-24 pendant les tests).
    hors_planning = sum(
        conforme for (lid, j), (conforme, _r) in palettes.items()
        if j in jours_termines and (lid, j) not in utilises
    )

    total = _Acc()
    lignes_out = []
    for l in lignes:
        acc = par_ligne[l.id]
        if acc.jours:
            total.fusionner(acc)
            lignes_out.append(_ligne_out(l.id, l.code, l.nom, acc, acc.jours))

    evolution = []
    for j in sorted(par_jour):
        d, p, qu, t = par_jour[j].facteurs()
        evolution.append(TrsJourOut(jour=j, trs_pct=t, disponibilite_pct=d, performance_pct=p, qualite_pct=qu))

    return TrsOut(
        date_debut=date_debut, date_fin=date_fin, cible_pct=cible, nb_jours=len(jours_pris),
        jour_en_cours_exclu=jour_en_cours_exclu, qualite_renseignee=total.rebuts > 0,
        pieces_hors_planning=round(hors_planning),
        usine=_ligne_out(None, "USINE", "Toutes lignes", total, len(jours_pris)),
        lignes=lignes_out, evolution=evolution,
    )
