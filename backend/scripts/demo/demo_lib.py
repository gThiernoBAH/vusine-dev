"""
demo_lib.py -- socle commun des outils de simulation (base de DÉMO uniquement).

Ces outils font travailler des opérateurs FICTIFS à travers la VRAIE API (connexion, saisie de
palette, arrêts), exactement comme le fera la tablette, puis écrivent un fichier de RÉFÉRENCE (ce
qui a réellement été simulé, ligne par ligne et jour par jour). `verifier_coherence.py` compare
ensuite ce fichier aux chiffres affichés par le cockpit.

GARDE-FOUS (tous bloquants) :
  1. La base ciblée doit avoir « demo » dans son nom. Jamais la base de production.
  2. Confirmation en tapant le nom de la base (sauf --oui).
  3. Contrôle « sentinelle » : l'API jointe doit lire LA MÊME base que le script, sinon arrêt.
  4. Tous les comptes fictifs portent le matricule DEMOnnn : `nettoyer_demo.py` efface tout.

Lancer depuis le dossier backend/ (le .env est lu ici) avec DATABASE_URL pointant sur la base de démo.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

MOT_DE_PASSE_DEMO = "Demo2026!"
PREFIXE_MATRICULE = "DEMO"
ID_CLONE_MIN = 900_000_000          # ids des lignes de planning clonées pour « aujourd'hui » (nettoyables)

PRENOMS = ["Awa", "Koffi", "Aminata", "Yao", "Fatou", "Serge", "Mariam", "Jean", "Adjoua", "Ibrahim", "Salimata", "Paul",
           "Nadège", "Moussa", "Estelle", "Kouadio", "Rokia", "Éric", "Bintou", "Alain", "Clarisse", "Souleymane", "Prisca", "Lassina"]
NOMS = ["Kouassi", "Traoré", "Konan", "Coulibaly", "Diallo", "Bamba", "N'Guessan", "Ouattara", "Koné", "Yao", "Soro", "Kouamé",
        "Touré", "Zadi", "Aka", "Sangaré", "Tano", "Dembélé"]

# ------------------------------------------------------------------ base de données et API


def ouvrir_db(oui: bool = False):
    """Session SQLAlchemy de l'application, après vérification que c'est bien une base de DÉMO."""
    from app.core.settings import settings
    from app.core.database import SessionLocal
    url = str(settings.DATABASE_URL)
    nom_base = url.rsplit("/", 1)[-1].split("?")[0]
    hote = url.split("@")[-1].split("/")[0] if "@" in url else "?"
    if "demo" not in nom_base.lower():
        sys.exit(f"REFUS : la base « {nom_base} » n'a pas « demo » dans son nom. Ces outils ne tournent QUE sur une base de démo.")
    print(f"Base ciblée : {nom_base} sur {hote}")
    if not oui:
        if input(f"Tapez le nom de la base ({nom_base}) pour confirmer : ").strip() != nom_base:
            sys.exit("Confirmation incorrecte : arrêt.")
    return SessionLocal()


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.jetons: dict[str, str] = {}

    def login(self, identifiant: str, mdp: str) -> str:
        r = self.s.post(f"{self.base}/auth/login", json={"identifiant": identifiant, "password": mdp}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Connexion refusée pour {identifiant} : {r.status_code} {r.text[:200]}")
        self.jetons[identifiant] = r.json()["access_token"]
        return self.jetons[identifiant]

    def appel(self, methode: str, chemin: str, identifiant: str, attendu=(200, 201), **kw):
        r = self.s.request(methode, f"{self.base}{chemin}", headers={"Authorization": "Bearer " + self.jetons[identifiant]}, timeout=60, **kw)
        if attendu and r.status_code not in attendu:
            raise RuntimeError(f"{methode} {chemin} ({identifiant}) -> {r.status_code} : {r.text[:300]}")
        return r


def verifier_meme_base(api: Api, db, admin: str) -> None:
    """Garde-fou 3 : écrit une valeur secrète en base, l'API doit la relire. Sinon l'API est branchée ailleurs
    (peut-être sur la production) : on s'arrête avant d'écrire quoi que ce soit."""
    jeton = uuid.uuid4().hex
    db.execute(text("INSERT INTO params (key, value) VALUES ('demo_sentinelle', :v) ON CONFLICT (key) DO UPDATE SET value = :v"), {"v": jeton})
    db.commit()
    lu = api.appel("GET", "/auth/params/demo_sentinelle", admin).json().get("value")
    if lu != jeton:
        sys.exit("REFUS : l'API ne lit pas la même base que ce script. Vérifiez DATABASE_URL de l'API (elle doit pointer sur la base de démo).")
    print("Contrôle sentinelle OK : l'API et le script utilisent la même base de démo.")


# ------------------------------------------------------------------ données de l'usine (lues en base)


@dataclass
class Poste:
    debut: datetime
    fin: datetime
    pause_debut: datetime | None
    pause_fin: datetime | None

    @property
    def net_min(self) -> float:
        pause = (self.pause_fin - self.pause_debut).total_seconds() / 60 if self.pause_debut and self.pause_fin else 0
        return (self.fin - self.debut).total_seconds() / 60 - pause

    def segments(self) -> list[tuple[datetime, datetime]]:
        if self.pause_debut and self.pause_fin:
            return [(self.debut, self.pause_debut), (self.pause_fin, self.fin)]
        return [(self.debut, self.fin)]


def poste_du_jour(db, jour: date) -> Poste | None:
    """Réutilise la règle de l'application (poste standard + jours spéciaux). None = jour fermé."""
    from app.services.performance_service import _bornes_poste_du_jour
    b = _bornes_poste_du_jour(db, jour)
    if not b or b.get("ferme"):
        return None
    c = lambda t: datetime.combine(jour, t) if t else None
    return Poste(c(b["heure_debut"]), c(b["heure_fin"]), c(b.get("pause_debut")), c(b.get("pause_fin")))


def jours_de_reference(db, nb: int, fin: date) -> list[date]:
    """Les `nb` derniers jours ouverts, jusqu'à `fin`, ayant un planning confirmé sur au moins 3 lignes."""
    rows = db.execute(text("""
        SELECT d.jour FROM planning_detail_cache d JOIN planning_cache p ON p.id = d.planning_id
        JOIN lignes_cache l ON l.id = d.ligne_id
        WHERE p.etat = 'confirmed' AND d.qty > 0 AND l.actif AND d.jour <= :fin
        GROUP BY d.jour HAVING COUNT(DISTINCT d.ligne_id) >= 3 ORDER BY d.jour DESC LIMIT :n"""), {"fin": fin, "n": nb * 2}).fetchall()
    jours = [r[0] for r in rows if poste_du_jour(db, r[0])]
    return sorted(jours[:nb])


def charger_planning(db, jours: list[date]) -> dict[tuple[int, date], list[dict]]:
    rows = db.execute(text("""
        SELECT d.id, d.ligne_id, d.jour, d.qty, d.produit_id, pr.nom, pr.colisage_par_carton, pr.cartons_par_palette
        FROM planning_detail_cache d JOIN planning_cache p ON p.id = d.planning_id
        JOIN lignes_cache l ON l.id = d.ligne_id LEFT JOIN produits_cache pr ON pr.id = d.produit_id
        WHERE p.etat = 'confirmed' AND d.qty > 0 AND l.actif AND d.jour = ANY(:jours) ORDER BY d.jour, d.ligne_id, d.id"""),
                      {"jours": list(jours)}).fetchall()
    out: dict[tuple[int, date], list[dict]] = {}
    for r in rows:
        out.setdefault((r.ligne_id, r.jour), []).append({
            "id": r.id, "qty": float(r.qty), "produit": r.nom or "Produit", "colisage": r.colisage_par_carton, "cartons_palette": r.cartons_par_palette})
    return out


def cellules_hors_simulation(db, jours: list[str], cel: list[dict]) -> list[dict]:
    """*** AJOUT 2026-09-25 (correction verifier_coherence.py) ***

    `verifier_coherence.py` interroge l'API sur toute la fenêtre CONTINUE [jours[0],
    jours[-1]] (cf. P = {date_debut, date_fin}), exactement comme le fera un manager qui
    choisit une période dans les Rapports. Or l'application agrège, sur cette fenêtre :
      1. TOUTES les lignes actives de l'usine (88 chez SIVOP) pour les totaux « usine » --
         pas seulement les ~40 lignes que `simuler_historique.py` a choisi de faire jouer
         par des opérateurs fictifs (`--max-lignes`, cf. README_DEMO.md) ;
      2. sur une ligne simulée, TOUT le planning confirmé de la fenêtre -- pas seulement
         les jours retenus par `jours_de_reference` (qui exige >= 3 lignes planifiées le
         même jour, et peut donc écarter un jour isolé sur UNE ligne, ex. CCL06 le
         2026-09-19, découvert le 2026-09-25 sur la vraie base à 88 lignes).
    `demo_reference.json`, lui, ne décrit QUE les (ligne, jour) réellement simulés : tout
    le reste (les ~48 lignes jamais touchées, les jours isolés comme ci-dessus) est un
    angle mort de la référence, pas de l'application -- d'où des écarts sur les totaux
    usine (disponibilité/performance/TRS) alors que le « Par ligne » et le score d'équipe,
    eux, sont corrects.

    Cette fonction comble cet angle mort : pour chaque (ligne, jour) de la fenêtre qui a
    du planning confirmé réel mais n'est couvert par AUCUNE cellule de `cel`, elle
    recalcule une cellule directement depuis la base (palettes et arrêts RÉELS sur cette
    ligne/jour, quels qu'ils soient -- fictifs ou non ; en pratique 0 partout chez SIVOP
    sur la période testée, mais on ne le suppose pas, on le lit). Même format que la
    cellule de planifier_journee(...)['cellule'], pour un ajout transparent côté
    verifier_coherence.py (simple concaténation à la liste des cellules)."""
    from app.services.performance_service import _bornes_poste_du_jour
    from app.services.pertes_service import minutes_entre, minutes_productives, bornes_periode

    d0, d1 = date.fromisoformat(jours[0]), date.fromisoformat(jours[-1])
    couvertes = {(c["ligne"], c["jour"]) for c in cel}
    tous_les_jours = []
    d = d0
    while d <= d1:
        tous_les_jours.append(d)
        d += timedelta(days=1)

    lignes = charger_lignes(db)
    planning = charger_planning(db, tous_les_jours)
    if not planning:
        return []

    borne_debut, borne_fin = bornes_periode(d0, d1)
    palettes_par_cle: dict[tuple[int, date], tuple[float, float, int]] = {}
    for lid, jr, conforme, rebuts, nb in db.execute(text(
            "SELECT ligne_id, created_at::date, COALESCE(SUM(quantite_totale),0), "
            "COALESCE(SUM(nb_rebuts),0), COUNT(*) FROM palettes "
            "WHERE created_at >= :a AND created_at < :b GROUP BY ligne_id, created_at::date"),
            {"a": borne_debut, "b": borne_fin}).fetchall():
        palettes_par_cle[(lid, jr)] = (float(conforme), float(rebuts), int(nb))

    arrets_par_ligne: dict[int, list[tuple[datetime, datetime, bool]]] = defaultdict(list)
    for lid, hd, hf, neutre in db.execute(text(
            "SELECT ligne_id, heure_debut, heure_fin, neutralise_score FROM arrets "
            "WHERE heure_debut < :b AND (heure_fin IS NULL OR heure_fin > :a)"),
            {"a": borne_debut, "b": borne_fin}).fetchall():
        arrets_par_ligne[lid].append((hd, hf or borne_fin, bool(neutre)))

    cellules = []
    for (ligne_id, jour), items in planning.items():
        ligne = lignes.get(ligne_id)
        if not ligne or (ligne["code"], jour.isoformat()) in couvertes:
            continue
        bornes = _bornes_poste_du_jour(db, jour)
        if not bornes or bornes.get("ferme"):
            continue
        qty_totale = sum(i["qty"] for i in items)
        if qty_totale <= 0:
            continue
        p_debut = datetime.combine(jour, bornes["heure_debut"])
        p_fin = datetime.combine(jour, bornes["heure_fin"])
        pause = 0.0
        if bornes.get("pause_debut") and bornes.get("pause_fin"):
            pause = minutes_entre(datetime.combine(jour, bornes["pause_debut"]), datetime.combine(jour, bornes["pause_fin"]))
        net_min = max(0.0, minutes_entre(p_debut, p_fin) - pause)
        if net_min <= 0:
            continue
        j_debut, j_fin = datetime.combine(jour, time.min), datetime.combine(jour + timedelta(days=1), time.min)
        arret_min_brut, min_arret_net, min_neutre_net = 0.0, 0.0, 0.0
        for hd, hf, neutre in arrets_par_ligne.get(ligne_id, []):
            seg_d, seg_f = max(hd, j_debut), min(hf, j_fin)
            if seg_f <= seg_d:
                continue
            arret_min_brut += minutes_entre(seg_d, seg_f)
            m = minutes_productives(seg_d, seg_f, jour, bornes)
            min_arret_net += m
            if neutre:
                min_neutre_net += m
        min_arret_net = min(min_arret_net, net_min)
        min_neutre_net = min(min_neutre_net, min_arret_net)
        conforme, rebuts, nb_pal = palettes_par_cle.get((ligne_id, jour), (0.0, 0.0, 0))
        q_run = qty_totale * (net_min - min_arret_net) / net_min
        cellules.append({
            "ligne": ligne["code"], "ligne_id": ligne_id, "section": ligne["section"], "jour": jour.isoformat(),
            "planifie": qty_totale, "net_min": net_min, "arret_min": round(arret_min_brut, 2),
            "min_imputables": round(min_arret_net - min_neutre_net, 2), "min_neutralisees": round(min_neutre_net, 2),
            "q_run": round(q_run, 3), "conforme": conforme, "rebuts": rebuts, "nb_palettes": nb_pal,
            "nb_partielles": 0, "changements_serie": max(0, len(items) - 1), "rejets_attendus": 0,
            "profil": None, "scan": None, "arrets": [], "equipe": [], "par_operateur": {},
        })
    return cellules


def charger_lignes(db) -> dict[int, dict]:
    return {r.id: {"id": r.id, "code": r.code, "nom": r.nom, "section": r.section_nom or "—"}
            for r in db.execute(text("SELECT id, code, nom, section_nom FROM lignes_cache WHERE actif")).fetchall()}


def charger_causes(db) -> list[dict]:
    return [{"id": r.id, "libelle": r.libelle, "imputable": bool(r.imputable_equipe)}
            for r in db.execute(text("SELECT id, libelle, imputable_equipe FROM causes_arret WHERE actif ORDER BY ordre_affichage")).fetchall()]


# ------------------------------------------------------------------ personnages : profils de lignes, équipes


def profil_ligne(graine: int, ligne_id: int) -> dict:
    """Caractère d'une ligne, stable d'un lancement à l'autre (même graine -> mêmes lignes « difficiles »)."""
    r = random.Random(f"{graine}-profil-{ligne_id}")
    x = r.random()
    if x < 0.22:      niveau, mu = "bonne", r.uniform(0.94, 1.04)
    elif x < 0.72:    niveau, mu = "moyenne", r.uniform(0.80, 0.93)
    elif x < 0.92:    niveau, mu = "faible", r.uniform(0.55, 0.75)
    else:             niveau, mu = "chronique", r.uniform(0.60, 0.80)          # pannes à répétition
    y = r.random()
    scan = "regulier" if y < 0.72 else ("fin_de_poste" if y < 0.90 else "irregulier")   # quand l'opérateur saisit
    return {"niveau": niveau, "mu": mu, "scan": scan, "rebut": r.uniform(0.004, 0.04),
            "erreurs": r.random() < 0.3, "arrets_x": 2.0 if niveau == "chronique" else (1.3 if niveau == "faible" else 1.0)}


def constituer_equipes(graine: int, ligne_ids: list[int], nb_operateurs: int) -> tuple[list[dict], dict[int, list[str]]]:
    """Pool d'opérateurs fictifs et équipe (2 à 4 personnes) de chaque ligne. Polyvalence : un opérateur peut
    servir plusieurs lignes, comme en vrai."""
    r = random.Random(f"{graine}-equipes")
    ops = []
    for i in range(nb_operateurs):
        ops.append({"matricule": f"{PREFIXE_MATRICULE}{i + 1:03d}", "nom": f"{r.choice(PRENOMS)} {r.choice(NOMS)} (démo)"})
    equipes = {lid: [o["matricule"] for o in r.sample(ops, min(len(ops), r.choice([2, 3, 3, 4])))] for lid in ligne_ids}
    return ops, equipes


# ------------------------------------------------------------------ moteur : une journée d'une ligne


def _soustraire(segments, debut, fin):
    """Retire [debut, fin] d'une liste de segments d'horloge."""
    out = []
    for a, b in segments:
        if fin <= a or debut >= b:
            out.append((a, b)); continue
        if debut > a: out.append((a, debut))
        if fin < b: out.append((fin, b))
    return out


def _horloge(segments, minute: float) -> datetime:
    """minute productive -> heure d'horloge, en sautant les pauses et les arrêts."""
    reste = minute
    for a, b in segments:
        d = (b - a).total_seconds() / 60
        if reste <= d:
            return a + timedelta(minutes=reste)
        reste -= d
    return segments[-1][1] - timedelta(minutes=1)


def planifier_journee(graine: int, ligne: dict, jour: date, items: list[dict], poste: Poste, equipe: list[str],
                      causes: list[dict], *, sans_scan: bool = False, arret_oublie: bool = False,
                      bonus: float = 1.0, scan_force: str | None = None) -> dict:
    """Simule une journée : arrêts, changements de série, palettes (avec partielles et rebuts). Retourne
    {'cellule': vérité terrain, 'evenements': [...]}. Aucune écriture : c'est un calcul pur (donc testable)."""
    rng = random.Random(f"{graine}-{ligne['id']}-{jour.isoformat()}")
    prof = profil_ligne(graine, ligne["id"])
    scan = scan_force or prof["scan"]          # réglages de démo : bonus d'efficacité, saisie régulière imposée
    net = poste.net_min
    qty_totale = sum(i["qty"] for i in items)

    # 1. Arrêts : posés à la minute près, jamais à cheval sur la pause.
    nb = rng.choices([0, 1, 2, 3, 4], [0.22, 0.38, 0.25, 0.1, 0.05])[0]
    nb = int(round(nb * prof["arrets_x"])) if prof["arrets_x"] > 1 else nb
    poids = {c["libelle"]: 1.0 for c in causes}
    for lib, p in (("Panne machine", 3), ("Manque MP", 2), ("Réglage", 2), ("Changement produit", 1.5), ("Manque emballage", 1.5)):
        if lib in poids: poids[lib] = p
    if prof["niveau"] == "chronique" and "Panne machine" in poids: poids["Panne machine"] = 14
    libres = poste.segments()
    arrets = []
    for _ in range(nb):
        duree = rng.choices([10, 15, 20, 30, 45, 60, 90], [3, 4, 4, 4, 2, 1.5, 0.5])[0]
        candidats = [(a, b) for a, b in libres if (b - a).total_seconds() / 60 >= duree + 10]
        if not candidats:
            break
        a, b = rng.choice(candidats)
        marge = int((b - a).total_seconds() / 60) - duree
        debut = (a + timedelta(minutes=rng.randint(0, marge))).replace(second=0, microsecond=0)
        fin = debut + timedelta(minutes=duree)
        cause = rng.choices(causes, [poids[c["libelle"]] for c in causes])[0]
        arrets.append({"cause": cause, "debut": debut, "fin": fin})
        libres = _soustraire(libres, debut, fin)
    arrets.sort(key=lambda x: x["debut"])
    if arret_oublie and arrets:
        arrets[-1]["fin"] = None        # saisie oubliée : jamais clôturé
    min_arret = sum((a["fin"] - a["debut"]).total_seconds() / 60 for a in arrets if a["fin"])
    min_imp = sum((a["fin"] - a["debut"]).total_seconds() / 60 for a in arrets if a["fin"] and a["cause"]["imputable"])
    min_neutre = min_arret - min_imp
    q_run = qty_totale * (net - min_arret) / net

    # 2. Production visée : efficacité de la ligne (avec bruit du jour) x ce que le temps de marche permettait.
    eff = min(1.15, max(0.3, prof["mu"] * bonus * rng.gauss(1.0, 0.08)))
    cible = eff * q_run
    total_min_marche = sum((b - a).total_seconds() / 60 for a, b in libres)

    # 3. Items du planning : produits enchaînés, temps réparti au prorata des quantités, changement de série entre deux.
    gap = 25 if len(items) > 1 else 0
    dispo = max(1.0, total_min_marche - gap * (len(items) - 1))
    palettes, curseur = [], 0.0
    for idx, it in enumerate(items):
        part = it["qty"] / qty_totale
        prod_item, fenetre = cible * part, dispo * part
        col = it["colisage"] or 12
        cartons_pal = it["cartons_palette"] or max(10, round(it["qty"] / (10 * col)))
        taille = cartons_pal * col
        n_pleines, reste = int(prod_item // taille), prod_item - int(prod_item // taille) * taille
        lots = [(cartons_pal, True)] * n_pleines
        if reste >= 0.3 * taille:
            lots.append((max(1, round(reste / col)), False))
        for k, (cartons, complete) in enumerate(lots, start=1):
            m = curseur + fenetre * k / len(lots)
            if scan == "fin_de_poste":
                ts = poste.fin - timedelta(minutes=rng.uniform(3, 38))
            else:
                if scan == "irregulier" and rng.random() < 0.4:
                    m = min(curseur + fenetre, m + rng.uniform(20, 70))
                ts = _horloge(libres, min(total_min_marche - 1, max(0, m + rng.uniform(-3, 3))))
            qte = cartons * col
            palettes.append({
                "type": "palette", "ts": ts.replace(microsecond=0), "item": it, "item_idx": idx, "cartons": cartons, "colisage": col, "complete": complete,
                "motif": None if complete else rng.choice(["Fin de commande", "Manque matière", "Fin de poste"]),
                "rebuts": int(qte * prof["rebut"] * rng.uniform(0.5, 1.5)), "operateur": rng.choices(equipe, [4] + [2] * (len(equipe) - 1))[0],
                "lot": f"{ligne['code']}{jour:%d%m}{idx + 1}", "mauvaise_saisie": prof["erreurs"] and rng.random() < 0.08})
        curseur += fenetre + gap
    if sans_scan:
        palettes = []
    palettes.sort(key=lambda p: p["ts"])
    op_arret = equipe[0]
    ev_arrets = [{"type": "arret", "ts": a["debut"], "fin": a["fin"], "cause": a["cause"], "operateur": op_arret} for a in arrets]

    conforme = sum(p["cartons"] * p["colisage"] for p in palettes)
    cellule = {
        "ligne": ligne["code"], "ligne_id": ligne["id"], "section": ligne["section"], "jour": jour.isoformat(),
        "planifie": qty_totale, "net_min": net, "arret_min": round(min_arret, 2), "min_imputables": round(min_imp, 2),
        "min_neutralisees": round(min_neutre, 2), "q_run": round(q_run, 3), "conforme": conforme,
        "rebuts": sum(p["rebuts"] for p in palettes), "nb_palettes": len(palettes),
        "nb_partielles": sum(1 for p in palettes if not p["complete"]), "changements_serie": len(items) - 1,
        "rejets_attendus": sum(1 for p in palettes if p["mauvaise_saisie"]), "profil": prof["niveau"], "scan": scan,
        "arrets": [{"cause": a["cause"]["libelle"], "imputable": a["cause"]["imputable"], "debut": a["debut"].isoformat(),
                    "fin": a["fin"].isoformat() if a["fin"] else None} for a in arrets],
        "equipe": equipe,
        "par_operateur": {o: sum(1 for p in palettes if p["operateur"] == o) for o in set(p["operateur"] for p in palettes)},
    }
    return {"cellule": cellule, "evenements": sorted(palettes + ev_arrets, key=lambda e: e["ts"])}


# ------------------------------------------------------------------ exécution via l'API


def fixer_date_palette(db, palette_id: int, code: str, ts: datetime, seq: int) -> None:
    db.execute(text("UPDATE palettes SET created_at = :ts, numero_palette = :n WHERE id = :i"),
               {"ts": ts, "n": f"PAL-{code}-{ts:%Y%m%d}-{seq:04d}", "i": palette_id})


def executer_evenement(api: Api, db, ligne: dict, ev: dict, seq: dict, *, redater: bool) -> str:
    """Envoie UN évènement par l'API. redater=True : le serveur date « maintenant », on recale à l'heure simulée."""
    op = ev["operateur"]
    if ev["type"] == "palette":
        payload = {"ligne_id": ligne["id"], "planning_detail_id": ev["item"]["id"], "numero_lot": ev["lot"], "nb_cartons": ev["cartons"],
                   "colisage_carton": ev["colisage"], "complete": ev["complete"], "motif_partielle": ev["motif"], "nb_rebuts": ev["rebuts"]}
        if ev.get("mauvaise_saisie"):     # l'opérateur se trompe (0 carton) : le serveur DOIT refuser ; il ressaisit ensuite
            r = api.appel("POST", "/actions/palettes", op, attendu=None, json={**payload, "nb_cartons": 0})
            if r.status_code != 422:
                raise RuntimeError(f"Saisie invalide acceptée par le serveur ({r.status_code}) sur {ligne['code']}")
        p = api.appel("POST", "/actions/palettes", op, json=payload).json()
        if redater:
            cle = (ligne["id"], ev["ts"].date())
            seq[cle] = seq.get(cle, 0) + 1
            fixer_date_palette(db, p["id"], ligne["code"], ev["ts"], seq[cle])
            db.commit()
        return "palette"
    a = api.appel("POST", "/actions/arrets/demarrer", op, json={"ligne_id": ligne["id"], "cause_id": ev["cause"]["id"]}).json()
    if redater:
        db.execute(text("UPDATE arrets SET heure_debut = :t WHERE id = :i"), {"t": ev["ts"], "i": a["id"]}); db.commit()
    if ev["fin"] is not None:
        api.appel("POST", f"/actions/arrets/{a['id']}/terminer", op)
        if redater:
            db.execute(text("UPDATE arrets SET heure_fin = :t WHERE id = :i"), {"t": ev["fin"], "i": a["id"]}); db.commit()
    return "arret"


def creer_operateurs(api: Api, db, admin: str, ops: list[dict]) -> dict[str, int]:
    """Comptes fictifs (idempotent : un compte existant est réutilisé)."""
    ids = {r.matricule: r.id for r in db.execute(text("SELECT id, matricule FROM users WHERE matricule LIKE :p"), {"p": PREFIXE_MATRICULE + "%"})}
    for o in ops:
        if o["matricule"] in ids:
            continue
        r = api.appel("POST", "/auth/users", admin, json={"nom": o["nom"], "password": MOT_DE_PASSE_DEMO, "matricule": o["matricule"], "user_type": "operateur"})
        ids[o["matricule"]] = r.json()["id"]
    for o in ops:
        if o["matricule"] not in api.jetons:
            api.login(o["matricule"], MOT_DE_PASSE_DEMO)
    return ids


def affecter_equipes(api: Api, db, admin: str, equipes: dict[int, list[str]], ids: dict[str, int], depuis: datetime) -> int:
    """Passe par l'écran d'affectation en masse (donc le teste), puis remonte la date de début pour couvrir la période simulée."""
    n = 0
    for lid, mats in equipes.items():
        r = api.appel("POST", f"/admin/affectations-ligne/{lid}", admin, json={"user_ids": [ids[m] for m in mats]}).json()
        n += r["ajoutes"]
    db.execute(text("UPDATE affectations_ligne SET date_debut = :d WHERE user_id = ANY(:u) AND date_debut > :d"),
               {"d": depuis, "u": list(ids.values())})
    db.commit()
    return n


def sauver_reference(chemin: str, meta: dict, cellules: list[dict], ops: list[dict], equipes: dict[int, list[str]]) -> None:
    Path(chemin).write_text(json.dumps({"meta": meta, "operateurs": ops, "equipes": {str(k): v for k, v in equipes.items()}, "cellules": cellules},
                                        ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def charger_reference(chemin: str) -> dict:
    return json.loads(Path(chemin).read_text(encoding="utf-8"))