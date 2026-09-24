"""
odoo_sync_service.py -- Synchronisation Odoo -> Vusine (lecture seule).

Reprend les conventions de run_sivox_etl.py (connexion XML-RPC, transformation des
valeurs m2o, retry sur erreur réseau transitoire) mais VOLONTAIREMENT simplifié :
resynchronisation COMPLÈTE à chaque passage plutôt qu'incrémentale. Justifié par
l'échelle : SIVOX gère des millions de lignes de mouvement de stock (incrémental
indispensable) ; Vusine ne gère que ~60 lignes, quelques centaines de produits finis, et
un nombre borné d'OF/planning actifs -- une resynchro complète toutes les
ODOO_SYNC_INTERVAL_MINUTES (défaut 10 min) est largement dans le budget.

6 tables synchronisées :
    lignes_cache          <- mrp.packaging.line
    produits_cache        <- product.template (colisage_par_carton/cartons_par_palette)
    of_cache               <- mrp.production (INFORMATIF depuis 2026-09-17, cf. plus bas)
    cadence_reference      <- mrp.packaging.pp (INFORMATIF depuis 2026-09-17, cf. plus bas)
    planning_cache          <- mrp.planning (*** NOUVEAU 2026-09-17 -- LA vraie source du
                               théorique, cf. docstring de sync_planning_detail)
    planning_detail_cache   <- mrp.detail.planning.line (*** NOUVEAU 2026-09-17 ***)
    sections_cache          <- product.section (*** NOUVEAU 2026-09-18 ***, cf. plus bas)

*** DÉCOUVERTE 2026-09-18 (investigate_sections.py) *** : section_nom de lignes_cache
était laissé 100% manuel depuis le 17/09 faute d'avoir vérifié la vraie liste de
sections Odoo -- confirmé par introspection XML-RPC (fields_get) que le modèle exact
est product.section (id, code, name), 28 enregistrements dont 16 réellement utilisés
par les 88 lignes (comptage qui colle exactement). Remplace donc la saisie manuelle par
une synchro comme les autres tables cache -- sync_sections() DOIT tourner avant
sync_lignes (FK lignes_cache.section_id -> sections_cache.id) et avant sync_planning
(même FK sur planning_cache.section_id).

*** DÉCOUVERTE 2026-09-17 *** : contrairement à l'hypothèse initiale, Odoo n'enregistre
PAS d'OF "en cours" au sens classique chez SIVOP -- mrp.production (of_cache) n'y sert
qu'à CONSTATER une production déjà terminée (confirmé sur 2972 OF réels : 100% à l'état
'done', aucun état intermédiaire observé). Le pilotage réel de la production se fait via
un planning HEBDOMADAIRE (écran Odoo "Usine de fabrication > Planification de la
fabrication", modèle mrp.planning, détaillé jour par jour et par ligne dans
mrp.detail.planning.line) -- c'est cette dernière qui alimente désormais le calcul du
théorique (cf. performance_service.py). of_cache et cadence_reference restent
synchronisés (traçabilité, comparaison de capacité machine) mais ne pilotent plus rien.

*** POINT NON VÉRIFIABLE DEPUIS CET ENVIRONNEMENT *** : le réseau sortant du sandbox où
ce fichier a été écrit ne peut pas atteindre odoo.com -- seule la logique de
transformation/upsert a été testée ici (réponses XML-RPC simulées). sync_lignes/
sync_produits/sync_of/sync_cadence ont été validées en conditions réelles le 2026-09-16 ;
sync_planning/sync_planning_detail sont nouvelles (2026-09-17), leurs noms de champs sont
confirmés par introspection XML-RPC réelle (fields_get), mais le premier run réel de CES
deux fonctions précises doit être surveillé de près (logs).
"""
import xmlrpc.client
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..core.settings import settings
from ..models.production import (
    LigneCache, ProduitCache, OfCache, CadenceReference, PlanningCache, PlanningDetailCache,
    SectionCache,
    # *** AJOUTS (chantier Labo, ETL v2) ***
    SaisieProductionCache, CorrectionCache, FormuleExplosionCache, StockMatiereCache,
    SyncState, EcartInventaireCache, FournisseurMatiereCache,
)

# *** AJOUT (chantier Labo) *** : fenêtre profonde pour le job nocturne (F1 a besoin de
# jusqu'à 180 jours d'historique de production, au-delà de ce que sync_of couvre en
# rythme normal -- cf. OF_FENETRE_JOURS/write_date plus bas, insuffisant seul pour cet
# usage). Référentiels (formules, stock, fournisseurs, écarts inventaire) resynchronisés
# en entier à chaque passage nocturne, pas de fenêtre glissante sur eux.
OF_FENETRE_PROFONDE_JOURS = 180

logger = logging.getLogger(__name__)

# Fenêtre glissante pour les OF -- pas tout l'historique (potentiellement des dizaines de
# milliers d'OF côté Odoo, cf. run_sivox_etl.py qui en compte 60k+). Vusine n'a besoin que
# des OF récents/actifs pour son cockpit temps réel, jamais d'historique profond.
OF_FENETRE_JOURS = 30

# Fenêtre glissante pour le planning détaillé -- plus large que OF_FENETRE_JOURS : un
# planning hebdo peut couvrir une semaine à venir (dates futures, naturellement incluses
# par une borne "depuis" sans borne haute), et on garde quelques semaines d'historique
# pour les Rapports.
PLANNING_FENETRE_JOURS = 60


class OdooSyncError(Exception):
    pass


def _connect_odoo():
    common = xmlrpc.client.ServerProxy(f"{settings.ODOO_CLOUD_URL}/xmlrpc/2/common")
    try:
        version = common.version()
    except Exception as e:
        raise OdooSyncError(f"Impossible de joindre {settings.ODOO_CLOUD_URL}/xmlrpc/2/common -- {e}")
    logger.info(f"[SYNC ODOO] Connecté à Odoo {version.get('server_version')}")

    uid = common.authenticate(settings.ODOO_CLOUD_DB, settings.ODOO_CLOUD_USER, settings.ODOO_CLOUD_API_KEY, {})
    if not uid:
        raise OdooSyncError("Authentification Odoo refusée -- vérifiez ODOO_CLOUD_DB/ODOO_CLOUD_USER/ODOO_CLOUD_API_KEY.")

    models = xmlrpc.client.ServerProxy(f"{settings.ODOO_CLOUD_URL}/xmlrpc/2/object")
    logger.info(f"[SYNC ODOO] Authentifié (uid={uid})")
    return uid, models


def _search_read(uid, models, model: str, domain: list, fields: list, tentatives: int = 3) -> list:
    """Même logique de retry que run_sivox_etl.py (502 Bad Gateway transitoires
    observés côté Odoo Cloud) -- 3 tentatives, backoff 5s/15s."""
    import time
    dernier_erreur = None
    for tentative in range(1, tentatives + 1):
        try:
            return models.execute_kw(
                settings.ODOO_CLOUD_DB, uid, settings.ODOO_CLOUD_API_KEY,
                model, "search_read", [domain], {"fields": fields, "context": {"active_test": False}},
            )
        except Exception as e:
            dernier_erreur = e
            if tentative < tentatives:
                attente = 5 if tentative == 1 else 15
                logger.warning(f"[SYNC ODOO] Tentative {tentative}/{tentatives} échouée sur {model} : {e} -- retry dans {attente}s")
                time.sleep(attente)
    raise OdooSyncError(f"Échec définitif sur {model} après {tentatives} tentatives : {dernier_erreur}")


def _m2o_id(raw) -> Optional[int]:
    """Many2one Odoo -> [id, 'display_name'] ou False si vide."""
    if not raw:
        return None
    return raw[0] if isinstance(raw, (list, tuple)) else raw


def _m2o_name(raw) -> Optional[str]:
    if not raw or not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    return raw[1]


def _parse_odoo_datetime(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _code_produit(m2o_raw) -> Optional[str]:
    """*** AJOUT (chantier Labo) *** : extrait le code entre crochets du display_name
    d'un many2one product.* -- format Odoo constant ici ('[CODE] Désignation'), confirmé
    sur stock.quant.entry.line/product.supplierinfo/mrp.bom.line (22/09). Repli sur le
    display_name complet si le format ne matche pas exceptionnellement (mieux qu'une
    valeur vide -- garde une trace exploitable plutôt qu'un NULL silencieux)."""
    nom = _m2o_name(m2o_raw)
    if not nom:
        return None
    match = re.match(r"^\[([^\]]+)\]", nom)
    return match.group(1) if match else nom


def _maj_sync_state(db: Session, domaine: str, nb_lignes: int):
    """*** AJOUT (chantier Labo) *** : trace la fraîcheur par domaine -- correction n°1
    actée dès le début du chantier (le cache a dormi du 18 au 21/09 sans que personne ne
    le sache). Affiché en admin, cf. labo_routes/SyncStateView.vue."""
    etat = db.query(SyncState).filter(SyncState.domaine == domaine).first()
    if not etat:
        etat = SyncState(domaine=domaine)
        db.add(etat)
    etat.derniere_synchro = datetime.now()
    etat.nb_lignes = nb_lignes
    db.commit()


def _parse_odoo_date(raw):
    """Champs Date (pas Datetime) Odoo -- format 'YYYY-MM-DD' -- utilisé par
    planning_cache.begin_date/end_date et planning_detail_cache.jour."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# =============================================================
# SECTIONS -- *** NOUVEAU 2026-09-18 *** (product.section, confirmé par
# investigate_sections.py) -- référentiel léger (28 lignes), synchronisé en entier
# (pas de fenêtre glissante, pas de filtre -- même philosophie que lignes_cache : tout
# ramener, y compris les sections non-production comme LABO/VENTES/magasins, pour ne
# jamais avoir un section_id orphelin côté lignes_cache/planning_cache).
# =============================================================

def sync_sections(uid, models, db: Session) -> int:
    records = _search_read(uid, models, "product.section", [], ["id", "name", "code"])
    for r in records:
        section = db.query(SectionCache).filter(SectionCache.id == r["id"]).first()
        if not section:
            section = SectionCache(id=r["id"])
            db.add(section)
        section.code = r.get("code")
        section.nom = r.get("name")
        section.synced_at = datetime.now()
    db.commit()
    return len(records)


# =============================================================
# LIGNES
# =============================================================

def sync_lignes(uid, models, db: Session) -> int:
    # *** CORRIGÉ 2026-09-16 (2e passage réel) *** : le filtre active=True ajouté plus tôt
    # aujourd'hui provoque un rejet XML-RPC pur et simple -- confirmé en conditions
    # réelles : "Invalid field mrp.packaging.line.active in leaf" -- ce modèle sur-mesure
    # SIVOP n'a PAS de champ standard 'active' (pas de notion d'archivage Odoo classique
    # dessus). Retiré. Interrupteur `actif` géré côté Vusine (admin), pas déduit d'Odoo.
    records = _search_read(uid, models, "mrp.packaging.line", [], ["id", "name", "code", "section_id"])
    for r in records:
        ligne = db.query(LigneCache).filter(LigneCache.id == r["id"]).first()
        if not ligne:
            ligne = LigneCache(id=r["id"])
            db.add(ligne)
        ligne.nom = r.get("name") or ligne.nom or ""
        ligne.code = r.get("code") or ligne.code or ""
        section_id = _m2o_id(r.get("section_id"))
        ligne.section_id = section_id
        # *** CORRIGÉ 2026-09-18 *** : section_nom/section_code étaient soit manuels
        # (section_nom) soit jamais résolus (section_id brut seul) -- dénormalisés ici
        # depuis sections_cache (déjà synchronisée avant sync_lignes, cf.
        # synchroniser_tout) plutôt que ressaisis à la main par un admin.
        if section_id:
            section = db.query(SectionCache).filter(SectionCache.id == section_id).first()
            ligne.section_code = section.code if section else None
            ligne.section_nom = section.nom if section else None
        else:
            ligne.section_code = None
            ligne.section_nom = None
        ligne.synced_at = datetime.now()
    db.commit()
    return len(records)


# =============================================================
# PRODUITS -- colisage/capacité palette uniquement, duree_vie_mois JAMAIS touché ici
# =============================================================

def sync_produits(uid, models, db: Session) -> int:
    # Filtre sur les produits finis actifs uniquement (même logique de filtrage que
    # SIVOX, cf. params.sql : detailed_type_custom = 'final_product') -- pas la peine de
    # ramener les matières premières/emballages, jamais fabriqués sur une ligne Vusine.
    domain = [("active", "=", True), ("detailed_type_custom", "=", "final_product")]
    # *** AJOUT (chantier Labo) *** : default_code -- indispensable pour rapprocher un
    # produit fini de sa nomenclature (labo_formules_explosion) et du stock matières
    # (stock_matieres_cache), qui raisonnent tous deux par code, pas par id Odoo.
    records = _search_read(uid, models, "product.template", domain,
                            ["id", "name", "packing", "pallet_capacity", "default_code"])
    for r in records:
        produit = db.query(ProduitCache).filter(ProduitCache.id == r["id"]).first()
        if not produit:
            produit = ProduitCache(id=r["id"])
            db.add(produit)
        produit.nom = r.get("name") or produit.nom or ""
        produit.default_code = r.get("default_code")
        packing = r.get("packing")
        produit.colisage_par_carton = int(packing) if packing else produit.colisage_par_carton
        pallet_capacity = r.get("pallet_capacity")
        produit.cartons_par_palette = int(pallet_capacity) if pallet_capacity else produit.cartons_par_palette
        produit.confirme_produit_fini = True
        # duree_vie_mois : AUCUNE ligne ici -- champ purement manuel (cf. schema.sql),
        # une synchro ne doit JAMAIS écraser une valeur saisie par un admin.
        produit.synced_at = datetime.now()
    db.commit()
    return len(records)


# =============================================================
# ORDRES DE FABRICATION -- *** INFORMATIF depuis 2026-09-17 ***
# Ne pilote plus rien (cf. planning_cache/planning_detail_cache plus bas) -- toujours
# synchronisé pour traçabilité/comparaison, fenêtre glissante, pas tout l'historique.
# =============================================================

# *** AJOUT (chantier Labo) *** : champs communs à sync_of (rythme normal) et
# sync_of_historique (nocturne, fenêtre profonde) -- éviter la divergence des deux
# fonctions sur ce qu'elles lisent.
CHAMPS_OF = [
    "id", "name", "product_id", "product_qty", "state", "date_start", "date_deadline",
    "packaging_line_id", "production_date", "production_entry_id",
]


def _upsert_of(records: list, db: Session):
    """*** AJOUT (chantier Labo) *** : factorisation du corps commun à sync_of et
    sync_of_historique -- même logique d'upsert, seule la fenêtre/le domaine change côté
    appelant. usine toujours 'UPRINC' ici (les deux appelants filtrent sur name like
    'ENUPR/%') : écrit en dur plutôt que déduit, pour rester correct si ce filtre est un
    jour retiré."""
    for r in records:
        of_id = r["id"]
        product_raw = r.get("product_id")
        produit_id = _m2o_id(product_raw)
        produit_nom = _m2o_name(product_raw)

        if produit_id:
            produit_existant = db.query(ProduitCache).filter(ProduitCache.id == produit_id).first()
            if not produit_existant:
                nouveau_prod = ProduitCache(
                    id=produit_id, nom=produit_nom or f"Produit Inconnu {produit_id}", synced_at=datetime.now()
                )
                db.add(nouveau_prod)
                db.flush()

        of = db.query(OfCache).filter(OfCache.id == of_id).first()
        if not of:
            of = OfCache(id=of_id)
            db.add(of)

        of.reference = r.get("name")
        of.usine = "UPRINC"
        of.produit_id = produit_id
        of.produit_nom = produit_nom
        of.ligne_id = _m2o_id(r.get("packaging_line_id"))
        of.qty_planifiee = r.get("product_qty")
        of.date_debut = _parse_odoo_datetime(r.get("date_start"))
        of.date_echeance = _parse_odoo_datetime(r.get("date_deadline"))
        of.etat = r.get("state")
        of.production_date = _parse_odoo_date(r.get("production_date"))
        of.saisie_reference = _m2o_name(r.get("production_entry_id"))
        of.synced_at = datetime.now()


def sync_of(uid, models, db: Session) -> int:
    """*** MODIFIÉ (chantier Labo) *** : filtre "ENUPR/%" ajouté -- exclut l'usine
    plastique à la source (49% des OF du cache avant ce filtre, sans ligne, produits
    hors périmètre CDC -- cf. exploration 21-22/09). Convention "colonne usine sur
    toute table" respectée malgré ce filtre : OfCache.usine reste rempli, pour pouvoir
    lever ce filtre un jour sans changer le schéma (décision explicite : garder la
    possibilité d'intégrer l'usine plastique plus tard)."""
    depuis = (datetime.now() - timedelta(days=OF_FENETRE_JOURS)).strftime("%Y-%m-%d %H:%M:%S")
    domain = [("name", "like", "ENUPR/%"), ("write_date", ">=", depuis)]
    records = _search_read(uid, models, "mrp.production", domain, CHAMPS_OF)
    _upsert_of(records, db)
    db.commit()
    return len(records)


def sync_of_historique(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : passage nocturne, fenêtre large (180j) sur
    production_date (pas write_date) -- rattrape l'angle mort de sync_of : un OF dont le
    write_date est sorti de sa fenêtre de 30j mais dont la production reste dans
    l'historique voulu par F1 (capacité démontrée). Sans cette fonction, F1 manquerait
    des OF plus anciens jamais retouchés depuis leur création."""
    depuis = (datetime.now() - timedelta(days=OF_FENETRE_PROFONDE_JOURS)).strftime("%Y-%m-%d")
    domain = [("name", "like", "ENUPR/%"), ("production_date", ">=", depuis), ("state", "=", "done")]
    records = _search_read(uid, models, "mrp.production", domain, CHAMPS_OF)
    _upsert_of(records, db)
    db.commit()
    return len(records)


def sync_saisies_production(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : production.entry -- base du délai de saisie (F3).
    Le préfixe de référence distingue l'usine ('PROC' = UPRINC, 'PROP' = UPLAST) --
    inférence confirmée par exploration (22/09), pas un champ dédié côté Odoo."""
    depuis = (datetime.now() - timedelta(days=OF_FENETRE_PROFONDE_JOURS)).strftime("%Y-%m-%d")
    domain = [("production_date", ">=", depuis)]
    records = _search_read(
        uid, models, "production.entry", domain,
        ["id", "reference", "production_date", "create_date", "write_date", "state", "user_id"],
    )
    for r in records:
        ref = r.get("reference") or ""
        usine = "UPLAST" if ref.startswith("PROP") else "UPRINC" if ref.startswith("PROC") else None
        s = db.query(SaisieProductionCache).filter(SaisieProductionCache.id == r["id"]).first()
        if not s:
            s = SaisieProductionCache(id=r["id"])
            db.add(s)
        s.reference = ref
        s.usine = usine
        s.production_date = _parse_odoo_date(r.get("production_date"))
        s.create_date = _parse_odoo_datetime(r.get("create_date"))
        s.write_date = _parse_odoo_datetime(r.get("write_date"))
        s.etat = r.get("state")
        s.auteur_nom = _m2o_name(r.get("user_id"))
        s.synced_at = datetime.now()
    db.commit()
    return len(records)


def sync_corrections(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : mrp.unbuild -- compteur de corrections pour F3.
    NE PAS réutiliser comme signal de gaspillage matière (exploration : très
    majoritairement des erreurs de saisie/retours magasin, jamais un vrai motif de
    perte structuré).

    *** CORRIGÉ 2026-09-22 (2e correction, sur inspection XML-RPC réelle) *** :
    mrp.unbuild n'a NI 'origin' NI 'origin_doc' (confirmé par --custom mrp.unbuild --
    mes deux tentatives précédentes étaient fausses). Le motif est en réalité porté par
    deconstruction.entry.origin_doc (confirmé avec de vraies valeurs en exploration :
    'RETOUR MAGASIN', 'ERREUR 2024'...), l'EN-TÊTE relié à mrp.unbuild via son champ
    deconstruction_entry_id (confirmé présent). Deux requêtes liées, pas une seule."""
    depuis = (datetime.now() - timedelta(days=OF_FENETRE_PROFONDE_JOURS)).strftime("%Y-%m-%d")
    domain = [("mo_id.name", "like", "ENUPR/%"), ("operation_date", ">=", depuis)]
    records = _search_read(uid, models, "mrp.unbuild", domain,
                            ["id", "mo_id", "state", "operation_date", "deconstruction_entry_id"])

    entry_ids = {_m2o_id(r.get("deconstruction_entry_id")) for r in records} - {None}
    origines_par_entry: dict[int, str] = {}
    if entry_ids:
        entetes = _search_read(uid, models, "deconstruction.entry",
                                [("id", "in", list(entry_ids))], ["id", "origin_doc"])
        origines_par_entry = {e["id"]: e.get("origin_doc") for e in entetes}

    for r in records:
        of_id = _m2o_id(r.get("mo_id"))
        of = db.query(OfCache).filter(OfCache.id == of_id).first() if of_id else None
        c = db.query(CorrectionCache).filter(CorrectionCache.id == r["id"]).first()
        if not c:
            c = CorrectionCache(id=r["id"])
            db.add(c)
        c.of_id = of_id
        c.ligne_id = of.ligne_id if of else None
        c.origine = origines_par_entry.get(_m2o_id(r.get("deconstruction_entry_id")))
        c.etat = r.get("state")
        c.date_correction = _parse_odoo_date(r.get("operation_date"))
        c.synced_at = datetime.now()
    db.commit()
    return len(records)


def sync_formules_explosion(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : nomenclature explosée jusqu'aux matières
    premières (F10). Tente last.degree.components (déjà explosé par Odoo) ; en cas
    d'échec (modèle absent/vide -- jamais vérifié par XML-RPC avant cette livraison),
    repli automatique sur une explosion locale à 1 seul niveau (mrp.bom.line),
    marquée incomplète pour les BOM à semi-fini."""
    try:
        boms = _search_read(uid, models, "mrp.bom", [("active", "=", True)],
                             ["id", "product_tmpl_id", "product_qty"])
        base_qty = {b["id"]: (b.get("product_qty") or 1.0) for b in boms}
        bom_produit = {b["id"]: _code_produit(b.get("product_tmpl_id")) for b in boms}

        composants = _search_read(uid, models, "last.degree.components",
                                   [("bom_id", "in", list(base_qty))], ["bom_id", "product_id", "quantity"])
        if not composants:
            raise OdooSyncError("last.degree.components vide -- repli sur explosion locale.")

        vus, maj = set(), 0
        for c in composants:
            bom_id = _m2o_id(c.get("bom_id"))
            produit_fini = bom_produit.get(bom_id)
            composant = _code_produit(c.get("product_id"))
            if not (bom_id and produit_fini and composant):
                continue
            cle = (produit_fini, composant)
            if cle in vus:
                continue
            vus.add(cle)
            qte_unite = (c.get("quantity") or 0) / (base_qty.get(bom_id) or 1.0)
            _upsert_explosion(db, produit_fini, composant, qte_unite, complete=True)
            maj += 1
        db.commit()
        logger.info(f"[SYNC ODOO] Explosion via last.degree.components : {maj} ligne(s).")
        return maj
    except OdooSyncError as e:
        logger.warning(f"[SYNC ODOO] {e}")
        return _sync_formules_explosion_repli(uid, models, db)


def _sync_formules_explosion_repli(uid, models, db: Session) -> int:
    """Repli 1 niveau : raw_material_lines direct de chaque BOM. Ignore les
    semi_finished_lines -- un produit qui en a explicitement gardera
    explosion_complete=False, visible à l'écran plutôt que silencieux."""
    boms = _search_read(uid, models, "mrp.bom", [("active", "=", True)],
                         ["id", "product_tmpl_id", "product_qty", "semi_finished_lines"])
    base_qty = {b["id"]: (b.get("product_qty") or 1.0) for b in boms}
    bom_produit = {b["id"]: _code_produit(b.get("product_tmpl_id")) for b in boms}
    a_semi_fini = {b["id"] for b in boms if b.get("semi_finished_lines")}

    lignes = _search_read(uid, models, "mrp.bom.line", [("bom_id", "in", list(base_qty))],
                           ["bom_id", "product_id", "product_qty"])
    vus, maj = set(), 0
    for l in lignes:
        bom_id = _m2o_id(l.get("bom_id"))
        produit_fini = bom_produit.get(bom_id)
        composant = _code_produit(l.get("product_id"))
        if not (bom_id and produit_fini and composant):
            continue
        cle = (produit_fini, composant)
        if cle in vus:
            continue
        vus.add(cle)
        qte_unite = (l.get("product_qty") or 0) / (base_qty.get(bom_id) or 1.0)
        _upsert_explosion(db, produit_fini, composant, qte_unite, complete=(bom_id not in a_semi_fini))
        maj += 1
    db.commit()
    logger.warning(f"[SYNC ODOO] Repli explosion 1 niveau : {maj} ligne(s), incomplet sur BOM à semi-fini.")
    return maj


def _upsert_explosion(db, produit_fini_code, composant_code, quantite_par_unite, complete):
    e = (db.query(FormuleExplosionCache)
         .filter(FormuleExplosionCache.produit_fini_code == produit_fini_code,
                 FormuleExplosionCache.composant_code == composant_code).first())
    if not e:
        e = FormuleExplosionCache(produit_fini_code=produit_fini_code, composant_code=composant_code)
        db.add(e)
    e.quantite_par_unite = quantite_par_unite
    e.explosion_complete = complete
    e.synced_at = datetime.now()


def sync_stock_matieres(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : stock.quant -- disponible actuel par matière
    (F10, F9a). Tentative avec un domaine relationnel à 2 niveaux (location_id.usage) ;
    si Odoo le rejette (même famille d'erreur que 'active' sur mrp.packaging.line,
    cf. sync_lignes), repli sur un domaine plat + filtrage Python sur le display_name
    de location_id."""
    champs = ["product_id", "quantity", "location_id"]
    try:
        records = _search_read(
            uid, models, "stock.quant",
            [("location_id.usage", "=", "internal"), ("product_id.default_code", "!=", False)],
            champs,
        )
    except OdooSyncError as e:
        logger.warning(f"[SYNC ODOO] Domaine relationnel refusé sur stock.quant ({e}) -- repli filtrage Python.")
        bruts = _search_read(uid, models, "stock.quant", [("product_id.default_code", "!=", False)], champs)
        records = [r for r in bruts if not (_m2o_name(r.get("location_id")) or "").startswith("Virtual Locations")]

    agrege: dict[str, float] = {}
    for r in records:
        code = _code_produit(r.get("product_id"))
        if not code:
            continue
        agrege[code] = agrege.get(code, 0.0) + (r.get("quantity") or 0.0)

    for code, qte in agrege.items():
        s = db.query(StockMatiereCache).filter(StockMatiereCache.produit_code == code).first()
        if not s:
            s = StockMatiereCache(produit_code=code)
            db.add(s)
        s.quantite_disponible = qte
        s.synced_at = datetime.now()
    db.commit()
    return len(agrege)


def sync_ecarts_inventaire(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : stock.quant.entry.line, state='valid' uniquement
    -- écarts réels (F10b). Resynchro complète (référentiel borné, ~17k lignes en tout,
    pas de fenêtre)."""
    entetes = _search_read(uid, models, "stock.quant.entry", [("state", "=", "valid")], ["id", "name"])
    noms = {e["id"]: e["name"] for e in entetes}
    if not noms:
        return 0
    lignes = _search_read(uid, models, "stock.quant.entry.line", [("quant_entry_id", "in", list(noms))],
                           ["id", "quant_entry_id", "product_id", "location_id", "dte_val",
                            "qte_logic", "qte_count", "difference", "diff_value"])
    for l in lignes:
        e = db.query(EcartInventaireCache).filter(EcartInventaireCache.id == l["id"]).first()
        if not e:
            e = EcartInventaireCache(id=l["id"])
            db.add(e)
        e.inventaire_reference = noms.get(_m2o_id(l.get("quant_entry_id")))
        e.produit_code = _code_produit(l.get("product_id"))
        e.emplacement_nom = _m2o_name(l.get("location_id"))
        e.date_validation = _parse_odoo_date(l.get("dte_val"))
        e.stock_systeme = l.get("qte_logic")
        e.stock_compte = l.get("qte_count")
        e.ecart_qte = l.get("difference")
        e.ecart_valeur = l.get("diff_value")
        e.synced_at = datetime.now()
    db.commit()
    return len(lignes)


def sync_fournisseurs_matiere(uid, models, db: Session) -> int:
    """*** AJOUT (chantier Labo) *** : product.supplierinfo -- délai d'appro (F9b),
    prix EXCLU (décision actée). Resynchro complète (référentiel, 4146 lignes mesurées)."""
    records = _search_read(uid, models, "product.supplierinfo", [("product_tmpl_id.default_code", "!=", False)],
                            ["product_tmpl_id", "partner_id", "delay", "min_qty"])
    db.query(FournisseurMatiereCache).delete()
    for r in records:
        db.add(FournisseurMatiereCache(
            id=r["id"], matiere_code=_code_produit(r.get("product_tmpl_id")),
            fournisseur_nom=_m2o_name(r.get("partner_id")),
            delai_jours=r.get("delay") or 0, quantite_min=r.get("min_qty"),
        ))
    db.commit()
    return len(records)


# =============================================================
# CADENCE -- *** INFORMATIF depuis 2026-09-17 *** (capacité machine max, distincte du
# besoin du planning) -- source signalée peu fiable (cf. schema.sql, [G17] SIVOX) :
# ne JAMAIS écraser une valeur corrigée à la main (source_cadence = 'manuel')
# =============================================================

def sync_cadence(uid, models, db: Session) -> int:
    domain = [("capacity", ">", 0)]
    records = _search_read(uid, models, "mrp.packaging.pp", domain, ["id", "product_id", "packaging_line_id", "capacity"])
    maj = 0
    for r in records:
        product_raw = r.get("product_id")
        produit_id = _m2o_id(product_raw)
        produit_nom = _m2o_name(product_raw)
        ligne_id = _m2o_id(r.get("packaging_line_id"))

        if not produit_id or not ligne_id:
            continue

        produit_existant = db.query(ProduitCache).filter(ProduitCache.id == produit_id).first()
        if not produit_existant:
            nouveau_prod = ProduitCache(
                id=produit_id, nom=produit_nom or f"Produit Inconnu {produit_id}", synced_at=datetime.now()
            )
            db.add(nouveau_prod)
            db.flush()

        cadence = (
            db.query(CadenceReference)
            .filter(CadenceReference.produit_id == produit_id, CadenceReference.ligne_id == ligne_id)
            .first()
        )
        if cadence and cadence.source_cadence == "manuel":
            continue

        if not cadence:
            cadence = CadenceReference(produit_id=produit_id, ligne_id=ligne_id, source_cadence="odoo_sync")
            db.add(cadence)

        cadence.cadence_theorique_horaire = r.get("capacity")
        cadence.synced_at = datetime.now()
        maj += 1
    db.commit()
    return maj


# =============================================================
# PLANNING HEBDOMADAIRE -- *** NOUVEAU 2026-09-17, LA VRAIE SOURCE DU THÉORIQUE ***
# =============================================================

def sync_planning(uid, models, db: Session) -> int:
    """En-tête mrp.planning -- synchronisé quel que soit l'état (draft/confirmed/cancel),
    filtré à la LECTURE (cf. ligne_helpers.get_planning_du_jour), même philosophie que
    lignes_cache/of_cache : tout ramener, ne jamais perdre le fait qu'un planning est
    passé confirmed -> cancel après coup en ne le resynchronisant plus."""
    records = _search_read(
        uid, models, "mrp.planning", [],
        ["id", "reference", "code", "product_section_id", "begin_date", "end_date", "state"],
    )
    for r in records:
        planning = db.query(PlanningCache).filter(PlanningCache.id == r["id"]).first()
        if not planning:
            planning = PlanningCache(id=r["id"])
            db.add(planning)
        planning.reference = r.get("reference")
        planning.code = r.get("code")
        planning.section_id = _m2o_id(r.get("product_section_id"))
        planning.begin_date = _parse_odoo_date(r.get("begin_date"))
        planning.end_date = _parse_odoo_date(r.get("end_date"))
        planning.etat = r.get("state")
        planning.synced_at = datetime.now()
    db.commit()
    return len(records)


def sync_planning_detail(uid, models, db: Session) -> int:
    """mrp.detail.planning.line -- LA source réelle du théorique (ligne + jour + produit
    + quantité cible). Fenêtre glissante PLANNING_FENETRE_JOURS (pas de borne haute :
    les dates futures d'un planning à venir sont naturellement incluses). Même sécurité
    FK que sync_of : produit inséré à la volée si absent de produits_cache."""
    depuis = (datetime.now() - timedelta(days=PLANNING_FENETRE_JOURS)).strftime("%Y-%m-%d")
    domain = [("date", ">=", depuis)]
    records = _search_read(
        uid, models, "mrp.detail.planning.line", domain,
        ["id", "planning_id", "packaging_line_id", "product_id", "date", "qty", "package", "capacity"],
    )

    maj = 0
    for r in records:
        planning_id = _m2o_id(r.get("planning_id"))
        if not planning_id:
            continue  # ligne orpheline sans en-tête -- ne devrait pas arriver, ignorée par sécurité
        if not db.query(PlanningCache).filter(PlanningCache.id == planning_id).first():
            # L'en-tête n'est pas encore en base -- ordre garanti par synchroniser_tout
            # (sync_planning avant sync_planning_detail), défensif au cas où.
            continue

        product_raw = r.get("product_id")
        produit_id = _m2o_id(product_raw)
        if produit_id:
            produit_existant = db.query(ProduitCache).filter(ProduitCache.id == produit_id).first()
            if not produit_existant:
                nouveau_prod = ProduitCache(
                    id=produit_id, nom=_m2o_name(product_raw) or f"Produit Inconnu {produit_id}",
                    synced_at=datetime.now(),
                )
                db.add(nouveau_prod)
                db.flush()

        detail = db.query(PlanningDetailCache).filter(PlanningDetailCache.id == r["id"]).first()
        if not detail:
            detail = PlanningDetailCache(id=r["id"])
            db.add(detail)
        detail.planning_id = planning_id
        detail.ligne_id = _m2o_id(r.get("packaging_line_id"))
        detail.produit_id = produit_id
        detail.jour = _parse_odoo_date(r.get("date"))
        detail.qty = r.get("qty")
        detail.colisage = r.get("package")
        detail.contenance = r.get("capacity")
        detail.synced_at = datetime.now()
        maj += 1

    db.commit()
    return maj


# =============================================================
# ORCHESTRATION
# =============================================================

def synchroniser_tout(db: Session) -> dict:
    """Point d'entrée unique -- appelé par POST /sync/run-now et par le scheduler
    périodique (cf. services/scheduler.py). Une connexion Odoo, 7 tables synchronisées
    dans un ordre qui respecte les dépendances (sections avant tout ce qui la référence ;
    lignes/produits avant tout ce qui les référence ; planning_cache avant
    planning_detail_cache)."""
    uid, models = _connect_odoo()

    resultats = {}
    resultats["sections_cache"] = sync_sections(uid, models, db)
    resultats["lignes_cache"] = sync_lignes(uid, models, db)
    resultats["produits_cache"] = sync_produits(uid, models, db)

    resultats["of_cache"] = sync_of(uid, models, db)
    resultats["cadence_reference"] = sync_cadence(uid, models, db)

    resultats["planning_cache"] = sync_planning(uid, models, db)
    resultats["planning_detail_cache"] = sync_planning_detail(uid, models, db)

    # *** AJOUT (chantier Labo) *** : trace la fraîcheur de chaque table -- correction
    # n°1 actée dès le début du chantier (cache endormi 3 jours sans que personne ne le
    # sache, 18-21/09).
    for table, n in resultats.items():
        _maj_sync_state(db, table, n)

    logger.info(f"[SYNC ODOO] Terminé : {resultats}")
    return resultats


def vider_caches_synchronises(db: Session):
    """*** AJOUT (chantier Labo) *** : --mode full de run_vusine_sync.py -- vide
    UNIQUEMENT les tables cache Odoo SANS AUCUN dépendant réel (pas de FK entrante
    depuis une table terrain). Jamais lignes_cache/produits_cache/of_cache/
    planning_cache/planning_detail_cache -- toutes les quatre sont référencées par
    `palettes` (of_id legacy, planning_detail_id courant) : un TRUNCATE échoue dessus
    (FeatureNotSupported, testé en réel le 22/09) et un TRUNCATE CASCADE viderait
    palettes/alertes/receptions_magasin/palettes_corrections avec -- de vraies données
    de terrain. Ces quatre tables restent gérées par upsert seul (sync_lignes/
    sync_produits/sync_of/sync_planning*), rafraîchies par la resynchro qui suit ce
    vidage, sans purge préalable.

    corrections_cache est également exclue : elle référence of_cache (of_id), qui
    n'est lui-même jamais vidé -- la vider isolément casserait le lien vers les OF
    encore en base, sans bénéfice (elle sera de toute façon réécrite par
    sync_corrections à la resynchro qui suit)."""
    tables_sans_dependant_reel = [
        "cadence_reference",
        "saisies_production_cache",
        "formules_cache",
        "stock_matieres_cache",
        "labo_formules_explosion",
        "labo_ecarts_inventaire",
        "labo_fournisseurs_matiere",
        "sync_state",
    ]
    for table in tables_sans_dependant_reel:
        db.execute(text(f"TRUNCATE TABLE {table}"))
    db.commit()
    logger.warning(f"[SYNC ODOO] --mode full : {len(tables_sans_dependant_reel)} table(s) sans dépendant "
                    f"réel vidée(s). of_cache/planning_cache/planning_detail_cache/corrections_cache/"
                    f"lignes_cache/produits_cache PRÉSERVÉES (référencées par palettes) -- "
                    f"rafraîchies par upsert seul lors de la resynchro qui suit.")


def synchroniser_full(db: Session) -> dict:
    """*** AJOUT (chantier Labo) *** : vide les caches Odoo puis relance une synchro
    complète (rapide + historique) -- équivalent Vusine du --mode full de SIVOX (qui
    vide staging+DWH, pas la base entière). Usage rare, mais utile pour repartir
    proprement d'un cache incohérent sans passer par un reset complet de la base."""
    vider_caches_synchronises(db)
    resultats = {"vidage": "ok"}
    resultats.update(synchroniser_tout(db))
    resultats.update(synchroniser_historique(db))
    logger.info(f"[SYNC ODOO] --mode full terminé : {resultats}")
    return resultats


def synchroniser_historique(db: Session) -> dict:
    """*** AJOUT (chantier Labo) *** : point d'entrée du passage NOCTURNE -- fenêtre
    profonde (180j) sur les OF + resynchro complète des référentiels labo (formules,
    stock matières, écarts inventaire, fournisseurs). Appelé par
    services/scheduler.py::_odoo_sync_historique_job, jamais par le cycle rapide
    (synchroniser_tout). Un échec sur un domaine n'empêche jamais les suivants --
    chaque sync_* est indépendant, comme pour synchroniser_tout."""
    uid, models = _connect_odoo()
    resultats = {}
    for nom, fn in [
        ("of_cache_historique", sync_of_historique),
        ("saisies_production_cache", sync_saisies_production),
        ("corrections_cache", sync_corrections),
        ("labo_formules_explosion", sync_formules_explosion),
        ("stock_matieres_cache", sync_stock_matieres),
        ("labo_ecarts_inventaire", sync_ecarts_inventaire),
        ("labo_fournisseurs_matiere", sync_fournisseurs_matiere),
    ]:
        try:
            n = fn(uid, models, db)
            resultats[nom] = n
            _maj_sync_state(db, nom, n)
        except OdooSyncError as e:
            logger.error(f"[SYNC ODOO HISTORIQUE] Échec sur {nom} : {e}")
            resultats[nom] = f"échec : {e}"
    logger.info(f"[SYNC ODOO HISTORIQUE] Terminé : {resultats}")
    return resultats