from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, Numeric, Date, Time, TIMESTAMP,
    ForeignKey, UniqueConstraint, CheckConstraint, Index, func
)
from sqlalchemy.orm import relationship
from ..core.database import Base
# Import explicite (pas seulement via ForeignKey("users.id")) : nécessaire pour que le
# registre de classes SQLAlchemy connaisse 'User' au moment de résoudre les
# relationship("User") ci-dessous (PaletteCorrection, ReceptionMagasin), y compris
# quand ce module est importé seul -- ex: run_vusine_sync.py, qui ne charge jamais
# core.models autrement (contrairement à main.py qui importe tous les routers/auth).
from ..core.models import User  # noqa: F401


# =============================================================
# CACHE ODOO -- lecture périodique, jamais écrit depuis la tablette
# (cf. schema.sql pour le détail des sources Odoo : mrp.packaging.line /
# mrp.production / mrp.packaging.pp)
# =============================================================

class SectionCache(Base):
    """*** NOUVEAU 2026-09-18 *** : product.section (confirmé par investigate_sections.py
    -- 28 sections réelles, 16 utilisées par les 88 lignes). Remplace la saisie manuelle
    de lignes_cache.section_nom par une vraie synchro (cf. odoo_sync_service.sync_sections,
    qui doit tourner avant sync_lignes/sync_planning -- FK ci-dessous)."""
    __tablename__ = "sections_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (product.section)
    code = Column(String(10), nullable=False)   # ex: "SAV", "PAR"
    nom = Column(String(100), nullable=False)   # ex: "SAVON", "PARFUM"
    synced_at = Column(TIMESTAMP, server_default=func.now())


class LigneCache(Base):
    __tablename__ = "lignes_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (mrp.packaging.line)
    code = Column(String(20), nullable=False)
    nom = Column(String(255), nullable=False)
    section_id = Column(Integer, ForeignKey("sections_cache.id"), nullable=True)
    # *** CORRIGÉ 2026-09-18 *** : section_nom/section_code sont maintenant SYNCHRONISÉS
    # depuis sections_cache (cf. odoo_sync_service.sync_lignes) -- avant cette date,
    # section_nom était 100% manuel (granularité Odoo supposée incompatible avec le CDC,
    # jamais vérifié). investigate_sections.py a confirmé que product.section (28
    # sections, 16 utilisées) est en fait exactement ce qu'il faut -- plus besoin de
    # ressaisir quoi que ce soit à la main dans Admin > Lignes.
    section_nom = Column(String(100), nullable=True)
    section_code = Column(String(10), nullable=True)  # identifiant stable, ex. "SAV"
    # Géré côté Vusine (admin), pas déduit d'Odoo -- cf. schema.sql pour le détail.
    actif = Column(Boolean, nullable=False, default=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())

    section = relationship("SectionCache", foreign_keys=[section_id], viewonly=True)


class ProduitCache(Base):
    """Propriétés du PRODUIT seul (indépendantes de la ligne) -- colisage_par_carton et
    cartons_par_palette synchronisés depuis Odoo (product.template.packing /
    .pallet_capacity, confirmés le 2026-09-16). duree_vie_mois reste purement manuel :
    aucun champ Odoo fiable identifié (nbjourn1/2/3 confirmés à 0 sur tous les produits
    finis actifs).

    confirme_produit_fini (*** AJOUT 2026-09-16 ***) : True si la ligne vient du passage
    normal de sync_produits (filtré sur detailed_type_custom='final_product' côté Odoo).
    False si la ligne a été insérée "à la volée" par sync_of/sync_cadence pour satisfaire
    une contrainte FK (un OF ou une entrée de cadence référence un produit qui n'a jamais
    matché le filtre produit fini -- matière première, semi-fini, article de conditionnement
    référencé par erreur ou par une fabrication multi-niveaux). Ne bascule JAMAIS de True
    à False -- seulement False -> True si ce produit finit par apparaître dans un passage
    normal de sync_produits plus tard."""
    __tablename__ = "produits_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (product.template)
    nom = Column(String(255), nullable=False)
    colisage_par_carton = Column(Integer, nullable=True)
    cartons_par_palette = Column(Integer, nullable=True)
    duree_vie_mois = Column(Integer, nullable=True)  # manuel uniquement
    confirme_produit_fini = Column(Boolean, nullable=False, default=False, server_default="false")
    # *** AJOUT (chantier Labo) *** : product.template.default_code -- indispensable pour
    # rapprocher un produit fini de sa nomenclature (labo_formules_explosion) et du stock
    # matières (stock_matieres_cache), qui raisonnent tous deux par code, pas par id Odoo.
    default_code = Column(String(30), nullable=True, index=True)
    # *** AJOUT 2026-09-24 (coût des pertes, Palier 0) *** : valeur d'une pièce en FCFA,
    # saisie à la main, jamais écrasée par la synchro Odoo. NULL -> paramètre global
    # valeur_piece_defaut_fcfa (cf. pertes_service.py).
    valeur_unitaire_fcfa = Column(Numeric, nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class OfCache(Base):
    __tablename__ = "of_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (mrp.production)
    reference = Column(String(64), nullable=True)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=True)
    produit_nom = Column(String(255), nullable=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=True)
    qty_planifiee = Column(Numeric, nullable=True)
    date_debut = Column(TIMESTAMP, nullable=True)
    date_echeance = Column(TIMESTAMP, nullable=True)
    etat = Column(String(64), nullable=True)
    # *** AJOUT (chantier Labo) *** : cf. odoo_sync_service.sync_of -- filtre "ENUPR/%"
    # à la source, usine toujours 'UPRINC' en pratique (écrit en dur, pas déduit, pour
    # rester correct si le filtre est un jour retiré). production_date = vrai jour de
    # production (distinct de date_debut/date_echeance, prévisionnels). saisie_reference
    # = référence production.entry (ex. 'PROC008552'), pour joindre saisies_production_cache
    # et mesurer le délai réel de saisie (F3).
    usine = Column(String(10), nullable=True)
    production_date = Column(Date, nullable=True)
    saisie_reference = Column(String(20), nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class CadenceReference(Base):
    __tablename__ = "cadence_reference"
    __table_args__ = (
        UniqueConstraint("produit_id", "ligne_id", name="uq_cadence_produit_ligne"),
    )

    id = Column(Integer, primary_key=True)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    # Synchronisée depuis Odoo mais éditable à la main (donnée source signalée peu fiable
    # par le DWH SIVOX, [G17]) -- cf. commentaire détaillé dans schema.sql.
    # *** RÔLE REVU 2026-09-17 *** : ne pilote plus le calcul du théorique -- donnée
    # informative distincte (capacité machine max), cf. schema.sql.
    cadence_theorique_horaire = Column(Numeric, nullable=True)
    source_cadence = Column(String(20), nullable=False, default="odoo_sync")  # 'odoo_sync' | 'manuel'
    synced_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")


# *** NOUVEAU 2026-09-17 -- LA VRAIE SOURCE DU THÉORIQUE *** (cf. schema.sql pour le
# détail de la découverte : mrp.production/of_cache n'est jamais "en cours" chez SIVOP,
# le pilotage réel se fait via ce planning hebdomadaire Odoo).

class PlanningCache(Base):
    __tablename__ = "planning_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (mrp.planning)
    reference = Column(String(64), nullable=True)   # ex: "OPF01274"
    code = Column(String(64), nullable=True)
    section_id = Column(Integer, ForeignKey("sections_cache.id"), nullable=True)  # informatif
    begin_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    # 'draft' | 'confirmed' | 'cancel' (valeurs réelles confirmées XML-RPC 2026-09-17) --
    # synchronisé quel que soit l'état, filtré à la LECTURE (cf. ligne_helpers.py).
    etat = Column(String(20), nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class PlanningDetailCache(Base):
    __tablename__ = "planning_detail_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (mrp.detail.planning.line)
    planning_id = Column(Integer, ForeignKey("planning_cache.id"), nullable=False)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=True)      # packaging_line_id
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=True)  # product_id
    jour = Column(Date, nullable=False)     # champ 'date' Odoo
    qty = Column(Numeric, nullable=True)
    colisage = Column(Numeric, nullable=True)     # champ 'package' Odoo, informatif
    contenance = Column(Numeric, nullable=True)   # champ 'capacity' Odoo
    synced_at = Column(TIMESTAMP, server_default=func.now())

    planning = relationship("PlanningCache")
    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


# =============================================================
# DONNÉES PROPRES À VUSINE -- saisies tablette / gérées par l'admin
# =============================================================

class Equipement(Base):
    """Fiche d'identité PHYSIQUE et immuable d'une machine (numero_interne stable). Plus
    de ligne_id direct -- où se trouve cet équipement à un instant T est tracé par
    AffectationEquipementLigne ci-dessous, pour garder l'historique de panne/maintenance
    intact même après un remplacement (décision explicite : traçabilité nécessaire)."""
    __tablename__ = "equipements"

    id = Column(Integer, primary_key=True)
    type = Column(String(50), nullable=False)  # remplisseuse | étiqueteuse | fardeleuse | ...
    marque = Column(String(100), nullable=True)
    modele = Column(String(100), nullable=True)
    numero_interne = Column(String(50), unique=True, nullable=True)
    capacite = Column(String(100), nullable=True)  # texte libre, unités hétérogènes (cf. schema.sql)
    statut = Column(String(20), nullable=False, default="disponible")
    # "disponible" | "en_panne" | "en_maintenance" | "retire"
    derniere_maintenance = Column(Date, nullable=True)
    prochaine_maintenance = Column(Date, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class AffectationEquipementLigne(Base):
    """Quel équipement physique occupe quelle ligne, sur quelle période -- même principe
    qu'AffectationLigne pour le personnel. La ligne "actuelle" d'un équipement = la ligne
    de son affectation où date_fin IS NULL."""
    __tablename__ = "affectations_equipement_ligne"

    id = Column(Integer, primary_key=True)
    equipement_id = Column(Integer, ForeignKey("equipements.id"), nullable=False)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    date_debut = Column(TIMESTAMP, nullable=False)
    date_fin = Column(TIMESTAMP, nullable=True)  # NULL = affectation en cours
    created_at = Column(TIMESTAMP, server_default=func.now())

    equipement = relationship("Equipement")
    ligne = relationship("LigneCache")


class CauseArret(Base):
    __tablename__ = "causes_arret"

    id = Column(Integer, primary_key=True)
    libelle = Column(String(100), unique=True, nullable=False)
    actif = Column(Boolean, nullable=False, default=True)
    ordre_affichage = Column(Integer, nullable=False, default=0)
    # *** AJOUT 2026-09-24 (Palier 2) *** : cf. schema.sql -- false = arrêt neutralisé dans le
    # score d'équipe.
    imputable_equipe = Column(Boolean, nullable=False, default=False, server_default="false")


class Arret(Base):
    __tablename__ = "arrets"

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    cause_id = Column(Integer, ForeignKey("causes_arret.id"), nullable=False)
    equipement_id = Column(Integer, ForeignKey("equipements.id"), nullable=True)
    commentaire = Column(Text, nullable=True)
    heure_debut = Column(TIMESTAMP, nullable=False)
    heure_fin = Column(TIMESTAMP, nullable=True)  # NULL = arrêt en cours
    operateur_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # *** AJOUT 2026-09-17 (audit CDC, slide 20) *** : un arrêt neutralisé compte
    # toujours dans les stats d'arrêts/pertes (Rapports, TRS) mais est exclu du calcul
    # de scoring CDI/CDD -- l'équipe n'est pas pénalisée pour une cause hors de son
    # contrôle (ex: manque MP, attente maintenance).
    neutralise_score = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    cause = relationship("CauseArret")
    equipement = relationship("Equipement")


class Palette(Base):
    __tablename__ = "palettes"

    id = Column(Integer, primary_key=True)
    numero_palette = Column(String(50), unique=True, nullable=False)  # généré backend
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    # *** REVU 2026-09-17 *** : of_id nullable, plus jamais renseigné par les nouvelles
    # palettes (of_cache n'est jamais "en cours" chez SIVOP) -- gardé pour ne pas casser
    # les palettes créées avant cette date. planning_detail_id le remplace.
    of_id = Column(Integer, ForeignKey("of_cache.id"), nullable=True)
    planning_detail_id = Column(Integer, ForeignKey("planning_detail_cache.id"), nullable=True)
    numero_lot = Column(String(50), nullable=False)  # saisi opérateur
    date_expiration = Column(Date, nullable=True)
    nb_cartons = Column(Integer, nullable=False)
    colisage_carton = Column(Integer, nullable=False)
    quantite_totale = Column(Integer, nullable=False)
    complete = Column(Boolean, nullable=False, default=True)
    # *** AJOUT 2026-09-17 (audit CDC, slide 6 : "Le motif peut être enregistré : fin OF,
    # fin poste, manque composants, etc.") *** : NULL si complete=True, texte libre
    # saisi côté tablette si complete=False. Pas de CHECK -- liste d'exemples ouverte.
    # Nommage confirmé par alertes_engine.py (filtre Palette.motif_partielle.is_(None)).
    motif_partielle = Column(String(100), nullable=True)
    # *** AJOUT 2026-09-24 (Palier 1, TRS) *** : pièces rebutées déclarées au scan, HORS
    # quantite_totale (qui ne contient que les pièces conformes) -- cf. schema.sql.
    nb_rebuts = Column(Integer, nullable=False, default=0, server_default="0")
    operateur_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    of = relationship("OfCache")
    planning_detail = relationship("PlanningDetailCache")


class AffectationLigne(Base):
    """Base du calcul de scoring CDI/CDD -- scoring_service.py croise cette table avec
    PerformanceLigneJour (performance figée chaque soir). Jamais de score stocké en dur
    ici, toujours recalculé (cf. schema.sql)."""
    __tablename__ = "affectations_ligne"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    date_debut = Column(TIMESTAMP, nullable=False)
    date_fin = Column(TIMESTAMP, nullable=True)  # NULL = affectation en cours
    created_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")


class PerformanceLigneJour(Base):
    """Snapshot quotidien, figé par un job planifié (cf. services/snapshot_service.py) --
    jamais recalculé rétroactivement une fois la journée close. Le jour en cours n'a pas
    de ligne ici tant que le job du soir ne l'a pas encore traité."""
    __tablename__ = "performance_ligne_jour"
    __table_args__ = (
        UniqueConstraint("ligne_id", "jour", name="uq_performance_ligne_jour"),
    )

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    jour = Column(Date, nullable=False)
    reel = Column(Integer, nullable=False)
    theorique = Column(Integer, nullable=True)
    performance_pct = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")


# =============================================================
# AUDIT CAHIER DES CHARGES -- ajouté 2026-09-17 (rattrapage, cf. schema.sql pour le
# détail des décisions -- notamment configuration_poste : un seul poste actif à la
# fois, contrainte imposée en base via un index unique partiel).
# =============================================================

class ConfigurationPoste(Base):
    """Référentiel Calendrier (slide 7 : calcul du théorique, slide 15). Le CDC ne
    décrit qu'un seul poste actif à la fois -- table multi-lignes pour ne pas bloquer
    une évolution future (2x8, 3x8), mais un seul actif=True est permis en base
    (index unique partiel, cf. schema.sql) : c'est celui qu'exploite le calcul du
    théorique (ligne_helpers.get_of_actuel et consorts)."""
    __tablename__ = "configuration_poste"

    id = Column(Integer, primary_key=True)
    nom = Column(String(50), unique=True, nullable=False)  # ex: "Poste unique", "Matin"
    heure_debut = Column(Time, nullable=False)
    heure_fin = Column(Time, nullable=False)
    pause_debut = Column(Time, nullable=True)
    pause_fin = Column(Time, nullable=True)
    actif = Column(Boolean, nullable=False, default=True)


class JourSpecial(Base):
    """Jours fériés / horaires spéciaux / fermetures (slide 15). Un jour présent ici
    surcharge configuration_poste pour cette seule date -- absence = poste standard."""
    __tablename__ = "jours_speciaux"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    type = Column(String(30), nullable=False, default="ferie")  # 'ferie' | 'horaire_special' | 'ferme'
    heure_debut = Column(Time, nullable=True)  # override, NULL si 'ferme'
    heure_fin = Column(Time, nullable=True)
    pause_debut = Column(Time, nullable=True)
    pause_fin = Column(Time, nullable=True)
    commentaire = Column(Text, nullable=True)


class PaletteCorrection(Base):
    """Journal d'audit des corrections de palette (permission correction_palette, déjà
    gérable via le système générique user_permissions -- rien à ajouter côté
    permissions, juste ce journal). Une palette déjà validée ne peut être corrigée que
    par un compte disposant de cette permission (slide 18)."""
    __tablename__ = "palettes_corrections"

    id = Column(Integer, primary_key=True)
    palette_id = Column(Integer, ForeignKey("palettes.id"), nullable=False)
    corrige_par = Column(Integer, ForeignKey("users.id"), nullable=False)
    champ_modifie = Column(String(50), nullable=False)
    ancienne_valeur = Column(Text, nullable=True)
    nouvelle_valeur = Column(Text, nullable=True)
    motif = Column(Text, nullable=True)
    corrige_at = Column(TIMESTAMP, server_default=func.now())

    palette = relationship("Palette")
    utilisateur = relationship("User")


class Alerte(Base):
    """Moteur d'alertes -- 5 catégories (slide 13). Schéma confirmé par
    alertes_engine.py (2026-09-17b -- corrigé après avoir vu ce fichier, qui existait
    déjà et attend ces noms précis) : `type` (pas categorie), `resolue` booléen (pas
    statut), `niveau` limité aux couleurs déjà utilisées ailleurs dans l'app
    ('orange'/'rouge'). Dédoublonnage géré au niveau applicatif par message exact
    (cf. alertes_engine._alerte_deja_ouverte : type + ligne_id + message) -- pas de
    contrainte d'unicité stricte en base, un simple index de perf suffit."""
    __tablename__ = "alertes"
    __table_args__ = (
        CheckConstraint(
            "type IN ('performance', 'silence_scan', 'ralentissement_progressif', "
            "'partielle_non_justifiee', 'of_termine_scan')",
            name="ck_alertes_type",
        ),
        CheckConstraint("niveau IN ('info', 'orange', 'rouge')", name="ck_alertes_niveau"),
        Index("ix_alertes_ligne_type_resolue", "ligne_id", "type", "resolue"),
    )

    id = Column(Integer, primary_key=True)
    type = Column(String(50), nullable=False)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    palette_id = Column(Integer, ForeignKey("palettes.id"), nullable=True)  # optionnel, non utilisé par le moteur actuel
    message = Column(Text, nullable=False)
    niveau = Column(String(20), nullable=False)
    resolue = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    palette = relationship("Palette")


# =============================================================
# ETL v2 (chantier Labo) -- SAISIES / CORRECTIONS / FORMULES / STOCK MATIÈRES /
# FRAÎCHEUR SYNCHRO. Cf. odoo_sync_service.py pour le détail de chaque synchro.
# =============================================================

class SaisieProductionCache(Base):
    """production.entry Odoo -- délai réel entre production et saisie (F3)."""
    __tablename__ = "saisies_production_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (production.entry)
    reference = Column(String(20), nullable=True)  # 'PROC...' (UPRINC) | 'PROP...' (UPLAST)
    usine = Column(String(10), nullable=True)
    production_date = Column(Date, nullable=True)
    create_date = Column(TIMESTAMP, nullable=True)
    write_date = Column(TIMESTAMP, nullable=True)
    etat = Column(String(20), nullable=True)
    auteur_nom = Column(String(100), nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class CorrectionCache(Base):
    """mrp.unbuild -- corrections/déconstructions déclarées après coup sur un OF,
    compteur de fiabilité (F3), PAS un signal de perte matière (exploration : très
    majoritairement des erreurs de saisie, retours magasin, etc.)."""
    __tablename__ = "corrections_cache"

    id = Column(Integer, primary_key=True)  # id Odoo (mrp.unbuild)
    of_id = Column(Integer, ForeignKey("of_cache.id"), nullable=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=True)  # résolu via of_id.ligne_id
    origine = Column(String(255), nullable=True)  # origin_doc, texte libre
    etat = Column(String(20), nullable=True)
    date_correction = Column(Date, nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())

    of = relationship("OfCache")
    ligne = relationship("LigneCache")


class FormuleCache(Base):
    """mrp.bom / mrp.bom.line brute, dédoublonnée sur (bom_id, produit, composant) --
    référentiel de premier niveau. labo_formules_explosion (plus bas) porte la version
    explosée jusqu'aux matières premières, utilisée par F10."""
    __tablename__ = "formules_cache"
    __table_args__ = (UniqueConstraint("bom_id", "produit_fini_code", "composant_code", name="uq_formule_composant"),)

    id = Column(Integer, primary_key=True)
    bom_id = Column(Integer, nullable=False)
    produit_fini_code = Column(String(30), nullable=False, index=True)
    composant_code = Column(String(30), nullable=False, index=True)
    quantite = Column(Numeric, nullable=False)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class StockMatiereCache(Base):
    """stock.quant -- disponible actuel par matière (F10, F9a)."""
    __tablename__ = "stock_matieres_cache"

    id = Column(Integer, primary_key=True)
    produit_code = Column(String(30), nullable=False, unique=True, index=True)
    quantite_disponible = Column(Numeric, nullable=False)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class SyncState(Base):
    """Fraîcheur par domaine synchronisé -- affiché en admin (correction n°1 actée dès
    le début du chantier : ne plus jamais laisser le cache dormir sans le savoir)."""
    __tablename__ = "sync_state"

    domaine = Column(String(50), primary_key=True)
    derniere_synchro = Column(TIMESTAMP, nullable=True)
    nb_lignes = Column(Integer, nullable=True)


# =============================================================
# LABO -- F1 à F10 (chantier SIVOX -> Vusine). Toutes ces tables sont recalculées par
# les ingestors de app/services/ingestors/, jamais éditées à la main sauf mention
# contraire (source='manuel' sur LigneProduitEligible).
# =============================================================

class FormuleExplosionCache(Base):
    """Nomenclature explosée jusqu'aux matières premières (F10) -- source préférée :
    mrp.bom.last_degree_components (Odoo). Repli automatique sur une explosion locale à
    UN SEUL niveau (mrp.bom.line) si ce modèle est vide/absent -- explosion_complete=False
    le signale alors plutôt que de mentir sur un produit à semi-fini."""
    __tablename__ = "labo_formules_explosion"
    __table_args__ = (UniqueConstraint("produit_fini_code", "composant_code", name="uq_explosion_produit_composant"),)

    id = Column(Integer, primary_key=True)
    produit_fini_code = Column(String(30), nullable=False, index=True)
    composant_code = Column(String(30), nullable=False, index=True)
    quantite_par_unite = Column(Numeric, nullable=False)
    explosion_complete = Column(Boolean, nullable=False, default=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class EcartInventaireCache(Base):
    """stock.quant.entry.line, filtré state='valid' -- écarts RÉELS entre stock système
    et comptage physique (F10b). Seul signal mesuré de perte/vol/gaspillage -- par
    campagnes, pas continu (exploration : 89 des 379 inventaires touchés sur 3 mois).
    Purement informatif, ne nourrit AUCUN calcul de F10 (simulation) : les deux restent
    séparés, l'un prédictif, l'autre constatatif."""
    __tablename__ = "labo_ecarts_inventaire"

    id = Column(Integer, primary_key=True)  # id Odoo (stock.quant.entry.line)
    inventaire_reference = Column(String(30), nullable=True)  # quant_entry_id.name
    produit_code = Column(String(30), nullable=True, index=True)
    emplacement_nom = Column(String(100), nullable=True)
    date_validation = Column(Date, nullable=True)  # dte_val
    stock_systeme = Column(Numeric, nullable=True)   # qte_logic
    stock_compte = Column(Numeric, nullable=True)    # qte_count
    ecart_qte = Column(Numeric, nullable=True)       # difference
    ecart_valeur = Column(Numeric, nullable=True)    # diff_value
    synced_at = Column(TIMESTAMP, server_default=func.now())


class FournisseurMatiereCache(Base):
    """product.supplierinfo -- délai d'appro par matière/fournisseur (F9b). Prix
    volontairement EXCLU (pas de conversion de devise fiable synchronisée -- 3 devises
    actives mesurées : XOF, EUR, USD) : F9b reste un signal de date, pas un arbitrage
    de coût, qui reste une décision humaine."""
    __tablename__ = "labo_fournisseurs_matiere"

    id = Column(Integer, primary_key=True)  # id Odoo (product.supplierinfo)
    matiere_code = Column(String(30), nullable=False, index=True)
    fournisseur_nom = Column(String(150), nullable=True)
    delai_jours = Column(Integer, nullable=False, default=0)
    quantite_min = Column(Numeric, nullable=True)
    synced_at = Column(TIMESTAMP, server_default=func.now())


class CapaciteLigneProduit(Base):
    """F1 -- capacité démontrée par (ligne, produit), à partir de l'historique réel des
    OF terminés (production_date). N'apparaît à l'écran que si nb_jours_observes >= 5
    (seuil acté) -- en dessous, "pas encore assez d'historique" plutôt qu'un chiffre
    peu fiable."""
    __tablename__ = "labo_capacite_ligne_produit"
    __table_args__ = (UniqueConstraint("ligne_id", "produit_id", name="uq_capacite_ligne_produit"),)

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False)
    nb_jours_observes = Column(Integer, nullable=False)
    mediane_jour = Column(Numeric, nullable=True)
    p90_jour = Column(Numeric, nullable=True)
    dernier_jour_observe = Column(Date, nullable=True)
    nb_jours_atypiques = Column(Integer, nullable=False, default=0)
    calcule_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class LigneProduitEligible(Base):
    """Quelles lignes peuvent physiquement produire quel produit -- base de F8.
    product_section_id/packaging_line_id sur product.template écartés (vides à 100%
    sur les 1164 produits finis actifs, vérifié le 22/09) : seule source retenue en V1
    = l'historique réel des OF ('historique'). Une entrée ajoutée à la main par l'admin
    ('manuel') n'est jamais retirée par le recalcul automatique nocturne."""
    __tablename__ = "labo_lignes_eligibles_produit"
    __table_args__ = (UniqueConstraint("ligne_id", "produit_id", name="uq_ligne_eligible_produit"),)

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False)
    source = Column(String(20), nullable=False)  # 'historique' | 'manuel'
    calcule_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class PrevisionVolume(Base):
    """F7 -- prévision de VOLUME de production à venir PAR PRODUIT (toutes lignes
    confondues), pas une prévision de demande commerciale (hors périmètre, décision
    actée) -- proxy interne fondé sur l'historique réellement produit. Calculée par
    services/ingestors/labo_predict_ingestor.py (Prophet).

    *** MODIFIÉ 2026-09-23 *** : grain (ligne, produit) -> produit seul. La colonne
    ligne_id a été supprimée : la répartition entre lignes est le rôle de F8 (plan
    optimisé), pas de F7. Agréger les lignes donne des séries plus longues et moins
    bruitées (beaucoup plus de produits franchissent le seuil d'historique minimal)."""
    __tablename__ = "labo_prevision_volume"

    id = Column(Integer, primary_key=True)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False, index=True)
    jour_horizon = Column(Date, nullable=False)
    qte_prevue = Column(Numeric, nullable=True)
    intervalle_bas = Column(Numeric, nullable=True)
    intervalle_haut = Column(Numeric, nullable=True)
    calcule_at = Column(TIMESTAMP, server_default=func.now())

    produit = relationship("ProduitCache")


class ExplicationCache(Base):
    """*** AJOUT 2026-09-23 (F4) *** : mémoire des analyses déjà générées par le LLM,
    pour ne jamais payer deux fois la même analyse (coût OpenRouter) et pour que
    l'analyse reste visible après un rafraîchissement de page ou pour un autre
    utilisateur -- jusqu'à ce que les chiffres sous-jacents changent réellement (cf.
    donnees_hash : recalculé à chaque appel, comparé à la dernière valeur connue).

    Une ligne = une analyse pour une combinaison (domaine, cle). `cle_signature` est une
    sérialisation déterministe de la clé (ex. "ligne_id=12&produit_id=45"). Le prochain
    recalcul nocturne des ingestors change les chiffres -> donnees_hash change -> la
    prochaine demande d'analyse régénère automatiquement, sans purge explicite à faire
    ici."""
    __tablename__ = "labo_explication_cache"
    __table_args__ = (UniqueConstraint("domaine", "cle_signature", name="uq_explication_domaine_cle"),)

    id = Column(Integer, primary_key=True)
    domaine = Column(String(50), nullable=False)
    cle_signature = Column(String(200), nullable=False)
    donnees_hash = Column(String(64), nullable=False)  # sha256 des chiffres analysés
    contenu = Column(Text, nullable=False)  # JSON structuré (synthese/points_attention/action)
    modele = Column(String(100), nullable=True)  # LLM_MODEL au moment de la génération
    genere_le = Column(TIMESTAMP, server_default=func.now())
    mis_a_jour_le = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class PlanOptimise(Base):
    """F8 -- recommandation de réaffectation produit -> ligne -> jour (MILP, PuLP),
    portage de optimize_pp_ingestor.py (SIVOX). NE remplace jamais le planning Odoo
    (Vusine reste en lecture seule sur Odoo) : affichage d'écart uniquement, décision
    humaine. Calculée par services/ingestors/labo_optimize_pp_ingestor.py."""
    __tablename__ = "labo_plan_optimise"

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=True)  # NULL si déficit sans ligne
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False)
    jour = Column(Date, nullable=False)
    qte_recommandee = Column(Numeric, nullable=False)
    qte_planning_reel = Column(Numeric, nullable=True)
    deficit_residuel = Column(Numeric, nullable=False, default=0)
    calcule_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class BesoinMatiereProjete(Base):
    """F9a -- besoin matière projeté (F7 x labo_formules_explosion) contre stock actuel
    (stock_matieres_cache). Une ligne uniquement quand stock_projete < 0 (tension à
    venir), pas un état permanent de toutes les matières."""
    __tablename__ = "labo_besoin_matiere_projete"

    id = Column(Integer, primary_key=True)
    matiere_code = Column(String(30), nullable=False, index=True)
    date_rupture_projetee = Column(Date, nullable=True)
    stock_projete = Column(Numeric, nullable=False)
    calcule_at = Column(TIMESTAMP, server_default=func.now())


class AlerteAchatProjete(Base):
    """F9b -- combine F9a (besoin) et labo_fournisseurs_matiere (délai) : date limite
    de commande = date de rupture projetée - meilleur délai connu. Sans prix ni choix
    de fournisseur automatique (décision actée) : liste les fournisseurs disponibles,
    la décision reste humaine."""
    __tablename__ = "labo_alertes_achat"

    id = Column(Integer, primary_key=True)
    matiere_code = Column(String(30), nullable=False)
    date_rupture_projetee = Column(Date, nullable=False)
    quantite_manquante = Column(Numeric, nullable=False)
    meilleur_delai_jours = Column(Integer, nullable=True)  # NULL si aucun fournisseur connu
    date_limite_commande = Column(Date, nullable=True)     # NULL si meilleur_delai_jours NULL
    nb_fournisseurs_disponibles = Column(Integer, nullable=False, default=0)
    calcule_at = Column(TIMESTAMP, server_default=func.now())


class AlerteEmballageLigne(Base):
    """F6 -- priorise les alertes d'achat (F9b) selon l'historique réel des arrêts
    "Manque MP"/"Manque emballage" sur chaque ligne (table arrets, causes_arret).
    N'est pas un doublon de F9a/F9b : F9b dit "cette matière va manquer, voici les
    fournisseurs" ; F6 ajoute "et cette ligne en a déjà souffert X fois", ce qui
    hiérarchise l'attention entre plusieurs alertes F9b simultanées."""
    __tablename__ = "labo_alertes_emballage_ligne"

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    matiere_code = Column(String(30), nullable=False)
    nb_arrets_manque_historique = Column(Integer, nullable=False, default=0)
    date_limite_commande = Column(Date, nullable=True)  # repris de labo_alertes_achat
    priorite = Column(String(10), nullable=False, default="normale")  # 'haute' | 'normale'
    calcule_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")


class SimulationProductible(Base):
    """F10 -- avec le stock matières actuel, combien d'unités de ce produit fini
    peut-on encore fabriquer, et quel composant limite en premier. Prédictif, distinct
    de labo_ecarts_inventaire (constatatif, F10b) -- jamais fusionnés."""
    __tablename__ = "labo_simulation_productible"
    __table_args__ = (UniqueConstraint("produit_fini_code", name="uq_simulation_produit"),)

    id = Column(Integer, primary_key=True)
    produit_fini_code = Column(String(30), nullable=False)
    # *** CORRIGÉ 2026-09-22 (erreur réelle : integer out of range en prod, cf.
    # labo_simulation_ingestor.py) *** : BigInteger en défense supplémentaire -- le
    # vrai correctif est le clamp à 0 des ratios négatifs côté ingestor, mais cette
    # colonne reste plus tolérante en cas de futur ratio positif inhabituellement
    # grand. Nécessite un ALTER TABLE sur une base déjà créée (CREATE TABLE IF NOT
    # EXISTS ne modifie jamais une colonne existante) :
    #   ALTER TABLE labo_simulation_productible ALTER COLUMN quantite_productible TYPE BIGINT;
    quantite_productible = Column(BigInteger, nullable=False)
    composant_limitant_code = Column(String(30), nullable=True)
    stock_limitant = Column(Numeric, nullable=True)
    besoin_limitant_par_unite = Column(Numeric, nullable=True)
    nb_composants_sans_stock_connu = Column(Integer, nullable=False, default=0)
    calcule_at = Column(TIMESTAMP, server_default=func.now())


class EcritureOdooProposee(Base):
    """F5 (export uniquement, PAS d'écriture réelle dans Odoo -- ODOO_WRITEBACK_ENABLED
    reste False) : ce que Vusine écrirait dans production.entry/mrp.production si F5
    était actif, reconstitué chaque nuit depuis les PALETTES réellement scannées
    (jamais depuis le planning, théorique)."""
    __tablename__ = "labo_ecritures_odoo_proposees"
    __table_args__ = (UniqueConstraint("ligne_id", "jour", "produit_id", name="uq_ecriture_proposee"),)

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=False)
    jour = Column(Date, nullable=False)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=False)
    quantite_reelle = Column(Integer, nullable=False)       # somme Palette.quantite_totale
    nb_palettes = Column(Integer, nullable=False)
    nb_palettes_partielles = Column(Integer, nullable=False, default=0)
    calculee_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class ComparaisonEcritureOdoo(Base):
    """Écart entre ce que Vusine aurait écrit (palettes réelles) et ce qu'Odoo contient
    réellement (of_cache, saisi par l'agent le lendemain) -- mesure continue de la
    fiabilité, alimente la décision d'activer F5 un jour. FULL OUTER en amont (cf.
    labo_ecritures_ingestor.py) pour ne perdre ni les palettes sans OF correspondant ni
    les OF sans palette."""
    __tablename__ = "labo_comparaison_ecritures"
    __table_args__ = (UniqueConstraint("ligne_id", "jour", "produit_id", name="uq_comparaison_ecriture"),)

    id = Column(Integer, primary_key=True)
    ligne_id = Column(Integer, ForeignKey("lignes_cache.id"), nullable=True)
    jour = Column(Date, nullable=False)
    produit_id = Column(Integer, ForeignKey("produits_cache.id"), nullable=True)
    quantite_vusine = Column(Integer, nullable=True)   # NULL si aucune palette ce jour-là
    quantite_odoo = Column(Integer, nullable=True)      # NULL si aucun OF Odoo ce jour-là
    ecart_qte = Column(Integer, nullable=True)
    ecart_pct = Column(Numeric, nullable=True)
    calculee_at = Column(TIMESTAMP, server_default=func.now())

    ligne = relationship("LigneCache")
    produit = relationship("ProduitCache")


class ReceptionMagasin(Base):
    """Réception Magasin, version allégée (slide 11/17) -- pas de rôle "Magasin" dédié
    (confirmé par le CDC, slide 16 : seulement 4 profils listés), accessible à tout
    compte tablette. Une réception par palette (contrainte unique)."""
    __tablename__ = "receptions_magasin"

    id = Column(Integer, primary_key=True)
    palette_id = Column(Integer, ForeignKey("palettes.id"), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receptionne_at = Column(TIMESTAMP, server_default=func.now())

    palette = relationship("Palette")
    utilisateur = relationship("User")


class SuiviIndividuelAcces(Base):
    """*** AJOUT 2026-09-24 (Palier 2) *** : journal des consultations du suivi individuel
    (cf. schema.sql). Une ligne par consultation, écrite par scoring_routes."""
    __tablename__ = "suivi_individuel_acces"

    id = Column(Integer, primary_key=True)
    consulte_par = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    periode_debut = Column(Date, nullable=False)
    periode_fin = Column(Date, nullable=False)
    consulte_le = Column(TIMESTAMP, server_default=func.now())

