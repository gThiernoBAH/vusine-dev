"""
labo_explication_service.py -- F4 (explication à la demande).

*** RÈGLE STRICTE (cf. cadrage) *** : le modèle ne calcule RIEN. Il reçoit uniquement
les chiffres déjà calculés et stockés par les ingestors (F1, F3, F9b), et rédige un
commentaire structuré (synthèse, points d'attention, action). S'il lui manque une
donnée pour répondre, il doit le dire, jamais inventer un chiffre.

*** REFONTE 2026-09-23 *** :
  - OpenRouter (déjà en place) au lieu de l'API Anthropic directe.
  - Sortie STRUCTURÉE (JSON : synthese / points_attention / action) plutôt qu'un texte
    libre, pour un affichage avec badges côté écran (cf. cadrage avec l'utilisateur,
    référence SIVOX). Les chiffres affichés en badge viennent TOUJOURS de `donnees`
    (nos propres tables), jamais du texte renvoyé par le modèle -- un badge ne peut donc
    jamais afficher un nombre halluciné.
  - Mémoire serveur (labo_explication_cache) : une analyse déjà générée pour les mêmes
    chiffres est renvoyée sans appeler OpenRouter. Elle ne se régénère que si les
    chiffres ont changé (donnees_hash) ou si l'utilisateur force explicitement une
    nouvelle analyse (regenerer=True) -- évite de payer deux fois la même analyse.
"""
import hashlib
import json
import logging

import requests
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext

from ..core.settings import settings
from ..models.production import CapaciteLigneProduit, AlerteAchatProjete, ExplicationCache

logger = logging.getLogger(__name__)

PROMPT_SYSTEME = """Tu commentes des chiffres déjà calculés pour la Production d'une \
usine (Vusine, conditionnement de produits cosmétiques). Règles strictes :
- Tu ne calcules RIEN toi-même. Tu commentes UNIQUEMENT les chiffres fournis.
- Si une information nécessaire n'est pas dans les chiffres fournis, dis-le \
("donnée non disponible") -- n'invente jamais une valeur, un fournisseur, une cause.
- Ne répète PAS les chiffres bruts dans ton texte (ils sont déjà affichés à l'écran à \
côté de ton commentaire) : commente-les, n'énumère pas.
- Réponds STRICTEMENT en JSON, sans texte avant ni après, sans balises Markdown, selon \
ce schéma exact :
{
  "synthese": "une ou deux phrases : ce que montrent les chiffres",
  "points_attention": [
    {"niveau": "critique" | "attention" | "info", "texte": "une phrase"}
  ],
  "action": {"texte": "une suggestion concrète, jamais un ordre", "priorite": "haute" | "normale"}
}
0 à 3 points d'attention. "action" peut être null si rien de particulier à suggérer. \
Français, ton factuel, pas de familiarité."""


class ExplicationIndisponible(Exception):
    pass


def _appeler_llm(message_utilisateur: str) -> str:
    """Appel OpenRouter (/chat/completions). Toute indisponibilité (clé absente, réseau,
    quota, réponse inattendue) remonte en ExplicationIndisponible -> HTTP 503 côté route,
    avec un message lisible -- jamais une trace brute à l'écran."""
    if not settings.OPENROUTER_API_KEY:
        raise ExplicationIndisponible(
            "OPENROUTER_API_KEY absente de la configuration -- l'analyse est désactivée "
            "tant qu'elle n'est pas renseignée dans .env."
        )
    try:
        reponse = requests.post(
            f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "Vusine Labo",
            },
            json={
                "model": settings.LLM_MODEL,
                "max_tokens": 500,
                "temperature": 0.2,  # commentaire factuel, pas de créativité
                "messages": [
                    {"role": "system", "content": PROMPT_SYSTEME},
                    {"role": "user", "content": message_utilisateur},
                ],
            },
            timeout=60,
        )
    except requests.RequestException as e:
        raise ExplicationIndisponible(f"Service d'analyse injoignable ({type(e).__name__}).") from e

    if reponse.status_code != 200:
        logger.warning(f"[LABO EXPLICATION] OpenRouter HTTP {reponse.status_code} : {reponse.text[:300]}")
        raise ExplicationIndisponible(f"Le service d'analyse a répondu en erreur (HTTP {reponse.status_code}).")
    try:
        texte = reponse.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ExplicationIndisponible("Réponse inattendue du service d'analyse.") from e
    if not texte.strip():
        raise ExplicationIndisponible("Le service d'analyse a renvoyé une réponse vide.")
    return texte.strip()


def _parser_reponse_llm(texte: str) -> dict:
    """Extrait le JSON demandé au modèle. Un modèle qui ajoute des balises ```json ou du
    texte autour est encore accepté (on isole le premier { ... } équilibré) ; un JSON
    manifestement invalide retombe sur une structure minimale (le texte brut en
    synthèse) plutôt qu'une erreur -- l'analyse reste lisible même mal formée."""
    brut = texte.strip()
    if brut.startswith("```"):
        brut = brut.strip("`")
        if brut.lower().startswith("json"):
            brut = brut[4:]
        brut = brut.strip()
    debut, fin = brut.find("{"), brut.rfind("}")
    if debut != -1 and fin != -1:
        brut = brut[debut:fin + 1]
    try:
        structure = json.loads(brut)
    except json.JSONDecodeError:
        logger.warning(f"[LABO EXPLICATION] Réponse non-JSON du modèle, repli texte brut : {texte[:200]}")
        return {"synthese": texte.strip(), "points_attention": [], "action": None, "brut": True}

    points = structure.get("points_attention") or []
    points_valides = [
        {"niveau": p.get("niveau") if p.get("niveau") in ("critique", "attention", "info") else "info",
         "texte": str(p.get("texte", "")).strip()}
        for p in points if isinstance(p, dict) and p.get("texte")
    ]
    action = structure.get("action")
    action_valide = None
    if isinstance(action, dict) and action.get("texte"):
        action_valide = {
            "texte": str(action["texte"]).strip(),
            "priorite": action.get("priorite") if action.get("priorite") in ("haute", "normale") else "normale",
        }
    return {
        "synthese": str(structure.get("synthese", "")).strip() or texte.strip(),
        "points_attention": points_valides,
        "action": action_valide,
        "brut": False,
    }


# =============================================================
# Récupération des chiffres déjà calculés, par domaine
# =============================================================

def _donnees_capacite(db: Session, ligne_id: int, produit_id: int) -> dict | None:
    row = db.query(CapaciteLigneProduit).filter(
        CapaciteLigneProduit.ligne_id == ligne_id, CapaciteLigneProduit.produit_id == produit_id).first()
    if not row:
        return None
    noms = db.execute(sqltext("""
        SELECT l.code AS ligne_code, p.nom AS produit_nom
        FROM lignes_cache l, produits_cache p WHERE l.id = :l AND p.id = :p
    """), {"l": ligne_id, "p": produit_id}).mappings().first() or {}
    return {
        # Code et nom lisibles plutôt que des identifiants internes : le commentaire
        # généré les reprend tels quels.
        "ligne": noms.get("ligne_code"), "produit": noms.get("produit_nom"),
        "nb_jours_observes": row.nb_jours_observes,
        "mediane_jour": float(row.mediane_jour) if row.mediane_jour else None,
        "p90_jour": float(row.p90_jour) if row.p90_jour else None,
        "dernier_jour_observe": str(row.dernier_jour_observe) if row.dernier_jour_observe else None,
        "nb_jours_atypiques": row.nb_jours_atypiques,
    }


def _donnees_fiabilite_saisie(db: Session, ligne_id: int) -> dict | None:
    row = db.execute(sqltext("""
        SELECT l.code AS ligne_code, COUNT(*) AS nb_of,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (s.create_date - of_cache.production_date::timestamp)) / 3600
               ) AS delai_median_h,
               (SELECT COUNT(*) FROM corrections_cache c WHERE c.ligne_id = of_cache.ligne_id
                AND c.date_correction >= CURRENT_DATE - INTERVAL '30 days') AS nb_corrections
        FROM of_cache
        JOIN lignes_cache l ON l.id = of_cache.ligne_id
        LEFT JOIN saisies_production_cache s ON s.reference = of_cache.saisie_reference
        WHERE of_cache.ligne_id = :ligne_id AND of_cache.usine = 'UPRINC' AND of_cache.etat = 'done'
          AND of_cache.production_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY l.code, of_cache.ligne_id
    """), {"ligne_id": ligne_id}).mappings().first()
    return dict(row) if row else None


def _donnees_alerte_achat(db: Session, matiere_code: str) -> dict | None:
    row = db.query(AlerteAchatProjete).filter(AlerteAchatProjete.matiere_code == matiere_code).first()
    if not row:
        return None
    return {
        "matiere_code": row.matiere_code,
        "date_rupture_projetee": str(row.date_rupture_projetee),
        "quantite_manquante": float(row.quantite_manquante),
        "meilleur_delai_jours": row.meilleur_delai_jours,
        "date_limite_commande": str(row.date_limite_commande) if row.date_limite_commande else None,
        "nb_fournisseurs_disponibles": row.nb_fournisseurs_disponibles,
    }


RECUPERATEURS = {
    "capacite": lambda db, cle: _donnees_capacite(db, cle.get("ligne_id"), cle.get("produit_id")),
    "fiabilite_saisie": lambda db, cle: _donnees_fiabilite_saisie(db, cle.get("ligne_id")),
    "alertes_achat": lambda db, cle: _donnees_alerte_achat(db, cle.get("matiere_code")),
}


# =============================================================
# Chiffres clés affichés en badge -- toujours dérivés de `donnees`, jamais du texte LLM
# =============================================================

def _fmt(valeur):
    """Nombre à la française (espace des milliers) si `valeur` en est un ; inchangé
    sinon (code, date, texte)."""
    if isinstance(valeur, (int, float)):
        arrondi = round(valeur, 2)
        if arrondi % 1:
            texte = f"{arrondi:,.2f}".rstrip("0").rstrip(".")
            entier, _, decimales = texte.partition(".")
            texte = entier.replace(",", " ") + ("," + decimales if decimales else "")
        else:
            texte = f"{int(arrondi):,}".replace(",", " ")
        return texte
    return valeur


def _chiffres_cles(domaine: str, donnees: dict) -> list[dict]:
    def item(label, valeur, suffixe=""):
        return {"label": label, "valeur": f"{_fmt(valeur)}{suffixe}" if valeur is not None else "—"}

    if domaine == "capacite":
        return [
            item("Médiane / jour", donnees.get("mediane_jour")),
            item("P90 / jour", donnees.get("p90_jour")),
            item("Jours observés", donnees.get("nb_jours_observes")),
        ]
    if domaine == "fiabilite_saisie":
        return [
            item("Délai médian", donnees.get("delai_median_h"), " h"),
            item("Nb OF", donnees.get("nb_of")),
            item("Corrections (30j)", donnees.get("nb_corrections")),
        ]
    if domaine == "alertes_achat":
        return [
            item("Qté manquante", donnees.get("quantite_manquante")),
            item("Date limite", donnees.get("date_limite_commande")),
            item("Fournisseurs", donnees.get("nb_fournisseurs_disponibles")),
        ]
    return []


def _cle_signature(cle: dict) -> str:
    """Sérialisation déterministe de la clé (ordre des champs fixé par tri des noms),
    utilisée comme identifiant stable en cache."""
    return "&".join(f"{k}={cle[k]}" for k in sorted(cle))


def _hash_donnees(donnees: dict) -> str:
    return hashlib.sha256(json.dumps(donnees, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def expliquer(db: Session, domaine: str, cle: dict, regenerer: bool = False) -> dict:
    if domaine not in RECUPERATEURS:
        raise ValueError(f"Domaine d'explication inconnu : {domaine!r}. "
                          f"Choix possibles : {list(RECUPERATEURS)}")
    donnees = RECUPERATEURS[domaine](db, cle)
    if donnees is None:
        raise ValueError("Aucune donnée trouvée pour cette clé -- rien à expliquer.")

    signature = _cle_signature(cle)
    hash_actuel = _hash_donnees(donnees)
    chiffres_cles = _chiffres_cles(domaine, donnees)

    ligne_cache = db.query(ExplicationCache).filter(
        ExplicationCache.domaine == domaine, ExplicationCache.cle_signature == signature).first()

    if ligne_cache and not regenerer and ligne_cache.donnees_hash == hash_actuel:
        structure = json.loads(ligne_cache.contenu)
        return {**structure, "chiffres_cles": chiffres_cles, "genere_le": ligne_cache.genere_le.isoformat(),
                "depuis_cache": True}

    texte = _appeler_llm(
        f"Domaine : {domaine}\nChiffres calculés (JSON) :\n{json.dumps(donnees, ensure_ascii=False, default=str)}"
    )
    structure = _parser_reponse_llm(texte)

    if ligne_cache:
        ligne_cache.donnees_hash = hash_actuel
        ligne_cache.contenu = json.dumps(structure, ensure_ascii=False)
        ligne_cache.modele = settings.LLM_MODEL
    else:
        ligne_cache = ExplicationCache(
            domaine=domaine, cle_signature=signature, donnees_hash=hash_actuel,
            contenu=json.dumps(structure, ensure_ascii=False), modele=settings.LLM_MODEL,
        )
        db.add(ligne_cache)
    db.commit()
    db.refresh(ligne_cache)

    logger.info(f"[LABO EXPLICATION] domaine={domaine} cle={cle} régénérée "
                f"(modèle {settings.LLM_MODEL}, regenerer={regenerer}).")
    return {**structure, "chiffres_cles": chiffres_cles, "genere_le": ligne_cache.genere_le.isoformat(),
            "depuis_cache": False}
