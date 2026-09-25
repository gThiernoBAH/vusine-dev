"""
rapport_matinal_service.py -- rapport matinal automatique. *** NOUVEAU 2026-09-24 (Palier 1) ***

Synthèse envoyée chaque matin (email et/ou Telegram) aux comptes qui l'ont demandé
(users.is_alert_mail / is_alert_telegram) :
  - performance de l'usine sur le DERNIER JOUR ÉVALUABLE (pas forcément hier : après un
    week-end ou un jour férié, c'est le dernier jour terminé avec un planning, dans les 7
    derniers jours), comparée au jour évaluable précédent ;
  - meilleures et moins bonnes lignes ;
  - TRS décomposé de ce jour ;
  - principales causes d'arrêt et leur coût estimé ;
  - arrêts encore ouverts à l'heure de l'envoi (souvent une saisie oubliée) ;
  - ce qui est planifié aujourd'hui.

FIABILITÉ DE L'ENVOI
  - Le job tourne toutes les 15 minutes ; ce service décide s'il doit envoyer : bon jour de
    la semaine, heure configurée atteinte, fenêtre de 6 h non dépassée, pas déjà envoyé
    aujourd'hui. Un redémarrage du serveur ou un échec SMTP à 7 h 00 est donc rattrapé à
    7 h 15, sans doublon possible (paramètre rapport_matinal_dernier_envoi).
  - Aucune donnée récente -> aucun envoi (un rapport vide habitue à l'ignorer).
  - Un destinataire en échec n'empêche pas les autres ; le jour n'est marqué « envoyé »
    que si au moins un envoi a réussi.
"""
import html as _html
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..core import crud
from ..core.models import User
from ..models.production import Arret, LigneCache
from .reports_service import perf_ligne_jour
from . import notification_service
from .ligne_helpers import get_planning_du_jour
from .pertes_service import pareto_arrets
from .trs_service import calculer_trs

logger = logging.getLogger(__name__)

RECHERCHE_JOURS = 7                 # on remonte au plus 7 jours pour trouver un jour de production
HEURE_DEFAUT = "07:00"
JOURS_DEFAUT = "1,2,3,4,5,6"        # lundi..samedi (ISO : lundi = 1)
FENETRE_ENVOI_HEURES = 6
CLE_DERNIER_ENVOI = "rapport_matinal_dernier_envoi"


# ----------------------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------------------

def construire_rapport(db: Session, aujourd_hui: Optional[date] = None, maintenant: Optional[datetime] = None) -> Optional[dict]:
    """None s'il n'existe aucun jour évaluable dans les 7 derniers jours.

    *** REVU 2026-09-24 *** : ne dépend plus du job de snapshot du soir. Un jour est évaluable
    s'il est TERMINÉ et que des lignes y avaient un planning ; les chiffres viennent du
    snapshot quand il existe, sinon du calcul direct (reports_service.perf_ligne_jour) --
    exactement comme les écrans Rapports."""
    maintenant = maintenant or datetime.now()
    aujourd_hui = aujourd_hui or maintenant.date()
    lignes = db.query(LigneCache).filter(LigneCache.actif.is_(True)).order_by(LigneCache.code).all()
    perf = perf_ligne_jour(db, lignes, aujourd_hui - timedelta(days=RECHERCHE_JOURS), aujourd_hui - timedelta(days=1), maintenant)
    par_jour: dict[date, dict[int, tuple[float, float]]] = {}
    for (lid, j), (reel, theo) in perf.items():
        if theo > 0:
            par_jour.setdefault(j, {})[lid] = (reel, theo)
    if not par_jour:
        return None
    jours = sorted(par_jour, reverse=True)
    jour = jours[0]
    jour_prec = jours[1] if len(jours) > 1 else None

    def pct_usine(j: date) -> tuple[int, int, Optional[int]]:
        reel = sum(r for r, _t in par_jour[j].values()); theo = sum(t for _r, t in par_jour[j].values())
        return round(reel), round(theo), round(reel / theo * 100) if theo > 0 else None

    reel, theo, pct = pct_usine(jour)
    pct_prec = pct_usine(jour_prec)[2] if jour_prec else None
    par_id = {l.id: l for l in lignes}
    classees = sorted(
        [{"code": par_id[lid].code, "nom": par_id[lid].nom, "pct": round(r / t * 100), "reel": round(r), "theorique": round(t)}
         for lid, (r, t) in par_jour[jour].items()],
        key=lambda x: (-x["pct"], x["code"]),
    )
    meilleures = classees[:3]
    moins_bonnes = [c for c in reversed(classees) if c not in meilleures][:3]
    perf_out = {"reel": reel, "theorique": theo, "pct": pct, "pct_precedent": pct_prec,
                "jour_precedent": jour_prec, "nb_lignes": len(par_jour[jour])}

    trs = None
    t = calculer_trs(db, jour, jour, maintenant=maintenant)
    if t.nb_jours > 0:
        u = t.usine
        trs = {"trs_pct": u.trs_pct, "disponibilite_pct": u.disponibilite_pct, "performance_pct": u.performance_pct,
               "qualite_pct": u.qualite_pct, "cible_pct": t.cible_pct, "qualite_renseignee": t.qualite_renseignee}

    p = pareto_arrets(db, jour, jour, maintenant=maintenant)
    arrets = {
        "total_duree_min": p.total_duree_min, "nb": p.total_nb_arrets, "cout_fcfa": p.total_cout_fcfa,
        "valorisation_configuree": p.valorisation_configuree, "libelle_valeur": p.libelle_valeur,
        "top": [{"cause": c.cause, "duree_min": c.duree_min, "pct": c.pct, "cout_fcfa": c.cout_fcfa} for c in p.causes[:3]],
    }

    ouverts = []
    for a in (db.query(Arret).filter(Arret.heure_fin.is_(None)).order_by(Arret.heure_debut).all()):
        ouverts.append({
            "ligne": a.ligne.code if a.ligne else f"#{a.ligne_id}",
            "cause": a.cause.libelle if a.cause else "Cause non précisée",
            "depuis_min": max(0, round((maintenant - a.heure_debut).total_seconds() / 60)),
        })

    nb_planifiees, qte = 0, 0
    for l in db.query(LigneCache).filter(LigneCache.actif.is_(True)).all():
        q = sum(float(i.qty or 0) for i in get_planning_du_jour(db, l.id, aujourd_hui))
        if q > 0:
            nb_planifiees += 1; qte += q

    return {
        "aujourd_hui": aujourd_hui, "jour_rapport": jour, "genere_le": maintenant.isoformat(timespec="minutes"),
        "performance": perf_out,
        "meilleures": meilleures, "moins_bonnes": moins_bonnes, "trs": trs, "arrets": arrets,
        "arrets_ouverts": ouverts, "aujourdhui": {"nb_lignes": nb_planifiees, "qte_planifiee": round(qte)},
    }


# ----------------------------------------------------------------------------------
# Rendu (texte / HTML)
# ----------------------------------------------------------------------------------

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _date_fr(d: date) -> str:
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"


def _n(v) -> str:
    return "—" if v is None else f"{round(v):,}".replace(",", "\u202f")


def _p(v, dec=0) -> str:
    return "—" if v is None else f"{v:.{dec}f}".replace(".", ",") + " %"


def _duree(min_: int) -> str:
    return f"{min_} min" if min_ < 60 else (f"{min_ // 60} h {min_ % 60:02d}" if min_ < 1440 else f"{min_ // 1440} j")


def _evolution(r: dict) -> str:
    a, b = r["performance"]["pct"], r["performance"]["pct_precedent"]
    if a is None or b is None:
        return ""
    ecart = a - b
    return f" ({'+' if ecart > 0 else ''}{ecart} pt vs {_date_fr(r['performance']['jour_precedent'])})" if ecart else " (stable)"


def sujet(r: dict) -> str:
    pct = r["performance"]["pct"]
    return f"Vusine — Rapport matinal du {r['aujourd_hui'].strftime('%d/%m/%Y')} : performance {_p(pct) if pct is not None else 'n/d'} le {_date_fr(r['jour_rapport'])}"


def _avertissements(r: dict) -> list[str]:
    av = []
    if r["trs"] and not r["trs"]["qualite_renseignee"]:
        av.append("Qualité non mesurée : aucun rebut déclaré ce jour-là, le TRS suppose 100 % de conformité.")
    if r["arrets"]["nb"] and not r["arrets"]["valorisation_configuree"]:
        av.append("Coût des arrêts non calculé : aucune valeur de pièce n'est configurée.")
    anciens = [a for a in r["arrets_ouverts"] if a["depuis_min"] >= 12 * 60]
    if anciens:
        av.append(f"{len(anciens)} arrêt(s) ouvert(s) depuis plus de 12 h : probablement une clôture oubliée.")
    return av


def rendre_texte(r: dict) -> str:
    perf = r["performance"]
    L = [f"VUSINE — Rapport matinal du {_date_fr(r['aujourd_hui'])}", "",
         f"PERFORMANCE — {_date_fr(r['jour_rapport'])}",
         f"  Usine : {_p(perf['pct'])} ({_n(perf['reel'])} / {_n(perf['theorique'])} pièces){_evolution(r)}"]
    if r["meilleures"]:
        L.append("  Meilleures : " + ", ".join(f"{x['code']} {_p(x['pct'])}" for x in r["meilleures"]))
    if r["moins_bonnes"]:
        L.append("  À surveiller : " + ", ".join(f"{x['code']} {_p(x['pct'])}" for x in r["moins_bonnes"]))
    if r["trs"]:
        t = r["trs"]
        L += ["", "TRS", f"  {_p(t['trs_pct'], 1)} (cible {_p(t['cible_pct'])}) = Dispo {_p(t['disponibilite_pct'], 1)} × Perf {_p(t['performance_pct'], 1)} × Qualité "
              + (_p(t['qualite_pct'], 1) if t["qualite_renseignee"] else "non mesurée")]
    a = r["arrets"]
    L += ["", "ARRÊTS"]
    if a["nb"]:
        cout = f" — coût estimé {_n(a['cout_fcfa'])} FCFA" if a["cout_fcfa"] is not None else ""
        L.append(f"  {a['nb']} arrêt(s), {_duree(a['total_duree_min'])} au total{cout}")
        for c in a["top"]:
            L.append(f"  • {c['cause']} : {_duree(c['duree_min'])} ({_p(c['pct'])})" + (f", {_n(c['cout_fcfa'])} FCFA" if c["cout_fcfa"] is not None else ""))
    else:
        L.append("  Aucun arrêt déclaré.")
    if r["arrets_ouverts"]:
        L += ["", "ARRÊTS EN COURS"] + [f"  • {o['ligne']} — {o['cause']} depuis {_duree(o['depuis_min'])}" for o in r["arrets_ouverts"]]
    ajd = r["aujourdhui"]
    L += ["", "AUJOURD'HUI", f"  {ajd['nb_lignes']} ligne(s) planifiée(s), {_n(ajd['qte_planifiee'])} pièces prévues."]
    if _avertissements(r):
        L += [""] + [f"⚠ {x}" for x in _avertissements(r)]
    return "\n".join(L)


def rendre_html(r: dict) -> str:
    e = _html.escape
    perf = r["performance"]

    def tuile(libelle, valeur, detail=""):
        return (f'<td style="padding:12px 16px;background:#f1f5f9;border-radius:8px;text-align:center;width:33%">'
                f'<div style="font-size:12px;color:#64748b;text-transform:uppercase">{e(libelle)}</div>'
                f'<div style="font-size:26px;font-weight:700;color:#0f172a">{e(valeur)}</div>'
                f'<div style="font-size:12px;color:#64748b">{e(detail)}</div></td>')

    def titre(t):
        return f'<h2 style="font-size:15px;margin:24px 0 8px;color:#0f172a;border-bottom:1px solid #e2e8f0;padding-bottom:4px">{e(t)}</h2>'

    def liste(items):
        return "<ul style=\"margin:0;padding-left:18px;line-height:1.6\">" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    corps = [titre(f"Performance — {_date_fr(r['jour_rapport'])}"),
             f'<p style="margin:0 0 8px"><strong>{e(_p(perf["pct"]))}</strong> — {e(_n(perf["reel"]))} / {e(_n(perf["theorique"]))} pièces{e(_evolution(r))}</p>']
    if r["meilleures"]:
        corps.append("<p style=\"margin:0\">Meilleures lignes : " + ", ".join(f"<strong>{e(x['code'])}</strong> {e(_p(x['pct']))}" for x in r["meilleures"]) + "</p>")
    if r["moins_bonnes"]:
        corps.append("<p style=\"margin:0\">À surveiller : " + ", ".join(f"<strong>{e(x['code'])}</strong> {e(_p(x['pct']))}" for x in r["moins_bonnes"]) + "</p>")

    if r["trs"]:
        t = r["trs"]
        corps.append(titre("TRS"))
        corps.append('<table role="presentation" width="100%" cellspacing="8" style="border-collapse:separate"><tr>'
                     + tuile("TRS", _p(t["trs_pct"], 1), f"cible {_p(t['cible_pct'])}")
                     + tuile("Disponibilité", _p(t["disponibilite_pct"], 1))
                     + tuile("Performance", _p(t["performance_pct"], 1))
                     + tuile("Qualité", _p(t["qualite_pct"], 1) if t["qualite_renseignee"] else "non mesurée")
                     + "</tr></table>")

    a = r["arrets"]
    corps.append(titre("Arrêts"))
    if a["nb"]:
        cout = f" — coût estimé <strong>{e(_n(a['cout_fcfa']))} FCFA</strong>" if a["cout_fcfa"] is not None else ""
        corps.append(f'<p style="margin:0 0 6px">{a["nb"]} arrêt(s), {e(_duree(a["total_duree_min"]))} au total{cout}</p>')
        corps.append(liste([f"{e(c['cause'])} : {e(_duree(c['duree_min']))} ({e(_p(c['pct']))})" + (f", {e(_n(c['cout_fcfa']))} FCFA" if c["cout_fcfa"] is not None else "") for c in a["top"]]))
    else:
        corps.append("<p style=\"margin:0\">Aucun arrêt déclaré.</p>")
    if r["arrets_ouverts"]:
        corps.append(titre("Arrêts en cours"))
        corps.append(liste([f"<strong>{e(o['ligne'])}</strong> — {e(o['cause'])} depuis {e(_duree(o['depuis_min']))}" for o in r["arrets_ouverts"]]))
    ajd = r["aujourdhui"]
    corps.append(titre("Aujourd'hui"))
    corps.append(f'<p style="margin:0">{ajd["nb_lignes"]} ligne(s) planifiée(s), {e(_n(ajd["qte_planifiee"]))} pièces prévues.</p>')
    if _avertissements(r):
        corps.append('<div style="margin-top:20px;padding:10px 14px;background:#fef3c7;border-radius:6px;color:#92400e;font-size:13px">'
                     + "<br>".join("⚠ " + e(x) for x in _avertissements(r)) + "</div>")

    return ('<!DOCTYPE html><html lang="fr"><body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#1e293b">'
            '<div style="max-width:640px;margin:0 auto;padding:24px">'
            f'<h1 style="font-size:20px;margin:0 0 4px">Rapport matinal</h1><div style="color:#64748b;font-size:13px">{e(_date_fr(r["aujourd_hui"]))}</div>'
            + "".join(corps) +
            '<p style="margin-top:28px;font-size:11px;color:#94a3b8">Envoyé automatiquement par Vusine.</p></div></body></html>')


# ----------------------------------------------------------------------------------
# Destinataires et envoi
# ----------------------------------------------------------------------------------

def destinataires(db: Session) -> dict[str, list[User]]:
    actifs = db.query(User).filter(User.is_active.is_(True))
    return {
        "email": [u for u in actifs.filter(User.is_alert_mail.is_(True)).all() if u.email],
        "telegram": [u for u in actifs.filter(User.is_alert_telegram.is_(True)).all() if u.telegram_chat_id],
    }


def _parametres(db: Session) -> tuple[time, set[int]]:
    try:
        h, m = (crud.get_param(db, "rapport_matinal_heure") or HEURE_DEFAUT).strip().split(":")
        heure = time(int(h), int(m))
    except (ValueError, TypeError):
        heure = time(*map(int, HEURE_DEFAUT.split(":")))
    try:
        jours = {int(x) for x in (crud.get_param(db, "rapport_matinal_jours") or JOURS_DEFAUT).split(",") if x.strip()}
        jours = {j for j in jours if 1 <= j <= 7} or {int(x) for x in JOURS_DEFAUT.split(",")}
    except ValueError:
        jours = {int(x) for x in JOURS_DEFAUT.split(",")}
    return heure, jours


def envoyer_rapport_matinal(
    db: Session, *, maintenant: Optional[datetime] = None, force: bool = False,
    test_user: Optional[User] = None, dry_run: bool = False,
) -> dict:
    """Décide s'il faut envoyer, puis envoie. Voir le docstring du module pour les règles.
    `test_user` : envoi à ce seul compte (email), hors règles de jour/heure, sans marquer
    la journée comme envoyée. `dry_run` : construit tout, n'envoie rien."""
    maintenant = maintenant or datetime.now()
    aujourd_hui = maintenant.date()
    resultat = {"envoye": False, "raison": "", "jour_rapport": None, "email_ok": 0, "email_echecs": [],
                "telegram_ok": 0, "telegram_echecs": []}

    if test_user is None and not force:
        heure, jours = _parametres(db)
        if maintenant.isoweekday() not in jours:
            resultat["raison"] = "jour non planifié"; return resultat
        debut = datetime.combine(aujourd_hui, heure)
        if maintenant < debut:
            resultat["raison"] = "heure d'envoi pas encore atteinte"; return resultat
        if maintenant > debut + timedelta(hours=FENETRE_ENVOI_HEURES):
            resultat["raison"] = "fenêtre d'envoi dépassée"; return resultat
        if crud.get_param(db, CLE_DERNIER_ENVOI) == aujourd_hui.isoformat():
            resultat["raison"] = "déjà envoyé aujourd'hui"; return resultat

    rapport = construire_rapport(db, aujourd_hui, maintenant)
    if rapport is None:
        resultat["raison"] = "aucune donnée de performance récente"; return resultat
    resultat["jour_rapport"] = rapport["jour_rapport"].isoformat()

    if test_user is not None:
        dest = {"email": [test_user] if test_user.email else [], "telegram": []}
        if not dest["email"]:
            resultat["raison"] = "votre compte n'a pas d'adresse email"; return resultat
    else:
        dest = destinataires(db)
    if not dest["email"] and not dest["telegram"]:
        resultat["raison"] = "aucun destinataire"; return resultat

    resultat["nb_destinataires_email"] = len(dest["email"]); resultat["nb_destinataires_telegram"] = len(dest["telegram"])
    if dry_run:
        resultat["raison"] = "simulation : rien n'a été envoyé"; return resultat

    html, texte, obj = rendre_html(rapport), rendre_texte(rapport), sujet(rapport)
    for u in dest["email"]:
        try:
            notification_service.envoyer_email(u.email, obj, html, texte)
            resultat["email_ok"] += 1
        except Exception as exc:  # noqa: BLE001 -- un destinataire en échec ne bloque pas les autres
            logger.error(f"[RAPPORT MATINAL] Échec email vers {u.email} : {exc}")
            resultat["email_echecs"].append({"destinataire": u.email, "erreur": str(exc)})
    for u in dest["telegram"]:
        try:
            notification_service.envoyer_telegram(u.telegram_chat_id, texte)
            resultat["telegram_ok"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[RAPPORT MATINAL] Échec Telegram vers {u.telegram_chat_id} : {exc}")
            resultat["telegram_echecs"].append({"destinataire": u.telegram_chat_id, "erreur": str(exc)})

    resultat["envoye"] = (resultat["email_ok"] + resultat["telegram_ok"]) > 0
    if resultat["envoye"]:
        resultat["raison"] = "envoyé"
        if test_user is None:
            crud.set_param(db, CLE_DERNIER_ENVOI, aujourd_hui.isoformat())
    else:
        resultat["raison"] = "tous les envois ont échoué"
    return resultat
