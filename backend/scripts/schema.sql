-- =============================================================================
-- VUSINE -- schema.sql
-- Schéma complet de la base transactionnelle Vusine (auth + métier + Labo).
-- Fusionne ce qui était réparti en 4 fichiers (01_auth_schema.sql, 02_auth_seed_data.sql
-- avait sa part de données séparée dans params.sql, 03_business_schema.sql,
-- 04_labo_migration.sql) en un seul fichier DDL -- toutes les colonnes qui étaient
-- ajoutées après coup par ALTER (is_super_admin, of_cache.usine/production_date/
-- saisie_reference, arrets.neutralise_score, palettes.motif_partielle, users.section_scope)
-- sont désormais directement dans le CREATE TABLE correspondant : ce fichier décrit
-- l'état ACTUEL du schéma, pas son historique de migration.
--
-- Rejouable sans risque (CREATE TABLE IF NOT EXISTS). Les données de référence
-- (départements, seuils, causes d'arrêt, poste par défaut, sections, compte admin)
-- sont dans params.sql, à jouer APRÈS ce fichier.
--
-- Ordre de lecture : (1) authentification/config, (2) caches Odoo, (3) données propres
-- à Vusine (tablette/admin), (4) chantier Labo (F1-F10, F5).
-- =============================================================================

DO $$ BEGIN RAISE NOTICE '📥 Création du schéma Vusine (schema.sql)'; END; $$;

-- =============================================================
-- 1. AUTHENTIFICATION / CONFIGURATION
-- =============================================================

CREATE TABLE IF NOT EXISTS departements (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS params (
    key VARCHAR(50) PRIMARY KEY,
    value VARCHAR(255) NOT NULL
);

-- Table unique pour les deux usages de l'app : comptes "direction" (cockpit, PC) ET
-- personnel terrain (tablette, opérateur/ouvrier). Connexion unifiée via `identifiant`
-- (username ou matricule selon le type de compte, cf. crud.get_user_by_identifiant).
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(20) UNIQUE,             -- direction / cockpit
    matricule VARCHAR(20) UNIQUE,            -- personnel terrain
    password_hash VARCHAR(255) NOT NULL,
    nom VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE,
    telephone VARCHAR(100),
    user_type VARCHAR(20) NOT NULL DEFAULT 'direction',   -- 'direction' | 'operateur' | 'ouvrier' | 'kiosque' (écran d'atelier, 2026-09-24)
    categorie_personnel VARCHAR(20),         -- 'CDI' | 'CDD' | 'Journalier' | 'Ancien CDI' | NULL
    is_active BOOLEAN DEFAULT true,
    is_admin BOOLEAN DEFAULT false,
    -- *** Chantier Labo *** : drapeau orthogonal à is_admin, JAMAIS contourné par lui
    -- (cf. auth_routes.require_labo). Réservé à un seul compte -- Direction peut avoir
    -- is_admin=true sans jamais voir le Labo. Réglable uniquement en SQL direct, absent
    -- de tout schéma Pydantic modifiable par l'API.
    is_super_admin BOOLEAN NOT NULL DEFAULT false,
    departement_id INTEGER REFERENCES departements(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reset_token VARCHAR(255),
    reset_token_expires TIMESTAMP WITH TIME ZONE,
    -- Reliquat probable d'un script copié depuis SIVOX -- laissés tels quels (décision
    -- utilisateur : "ne gêne rien, peut-être exploitable plus tard" -- notamment les 4
    -- colonnes is_alert_* comme canaux de diffusion par utilisateur pour le moteur
    -- d'alertes). Absents du modèle ORM (app/core/models.py).
    user_rep VARCHAR(255),
    mailapi TEXT,
    telegramapi TEXT,
    whatsappapi VARCHAR(255),
    civilite VARCHAR(10),
    is_alert_mail BOOLEAN NOT NULL DEFAULT false,
    is_alert_telegram BOOLEAN NOT NULL DEFAULT false,
    is_alert_screen BOOLEAN NOT NULL DEFAULT false,
    last_alerts_seen_at TIMESTAMP,
    -- *** AJOUT 2026-09-24 (Palier 1, rapport matinal) *** : identifiant numérique du chat
    -- Telegram du destinataire (dédié -- telegramapi, reliquat SIVOX, garde un sens inconnu
    -- et n'est PAS utilisé). Le rapport n'est envoyé que si is_alert_telegram = true.
    telegram_chat_id VARCHAR(50),
    -- Rôle Chef d'équipe (CDC slide 16) : si renseigné, restreint la Vue Usine du
    -- compte à cette seule section (comparaison contre lignes_cache.section_nom).
    -- NULL = accès complet (comptes Production/Administrateur).
    section_scope VARCHAR(100)
);

-- Système de permissions générique : la PRÉSENCE d'une ligne (user_id, permission_key)
-- accorde l'accès -- l'ABSENCE refuse, par défaut. Concerne uniquement les comptes
-- "direction" -- le personnel terrain n'a jamais de ligne ici (accès déterminé par son
-- matricule + ses lignes affectées).
CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_key VARCHAR(50) NOT NULL,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, permission_key)
);
CREATE INDEX IF NOT EXISTS ix_user_permissions_user_id ON user_permissions (user_id);

-- =============================================================
-- 2. CACHE ODOO (lecture périodique, jamais écrit depuis la tablette)
-- =============================================================

-- product.section -- 28 sections réelles côté Odoo, 16 utilisées par les lignes de
-- production (cf. odoo_sync_service.sync_sections, tourne avant sync_lignes/sync_planning).
CREATE TABLE IF NOT EXISTS sections_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (product.section)
    code VARCHAR(10) NOT NULL,              -- ex: "SAV", "PAR"
    nom VARCHAR(100) NOT NULL,              -- ex: "SAVON", "PARFUM"
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lignes_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (mrp.packaging.line)
    code VARCHAR(20) NOT NULL,              -- ex: "CCL02"
    nom VARCHAR(255) NOT NULL,
    section_id INTEGER REFERENCES sections_cache(id),
    section_nom VARCHAR(100),               -- dénormalisé depuis sections_cache
    section_code VARCHAR(10),               -- identifiant stable, préféré pour toute
                                             -- comparaison programmatique
    -- mrp.packaging.line n'a pas de champ 'active' standard Odoo -- interrupteur géré
    -- côté Vusine à la place (admin) : True par défaut à la synchro, à décocher
    -- manuellement pour les entrées qui ne sont pas de vraies lignes de production.
    actif BOOLEAN NOT NULL DEFAULT true,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS produits_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (product.template)
    nom VARCHAR(255) NOT NULL,
    -- *** Chantier Labo *** : default_code Odoo -- indispensable pour rapprocher un
    -- produit fini de sa nomenclature (labo_formules_explosion) et du stock matières
    -- (stock_matieres_cache), qui raisonnent tous deux par code, pas par id Odoo.
    default_code VARCHAR(30),
    colisage_par_carton INTEGER,            -- product.template.packing
    cartons_par_palette INTEGER,            -- product.template.pallet_capacity
    duree_vie_mois INTEGER,                 -- manuel uniquement, aucune source Odoo confirmée
    -- True = vient d'un passage normal de sync_produits (final_product). False = inséré
    -- "à la volée" par sync_of/sync_cadence pour satisfaire une contrainte FK -- jamais
    -- confirmé comme un vrai produit fini. Ne bascule jamais de True à False.
    confirme_produit_fini BOOLEAN NOT NULL DEFAULT false,
    -- *** AJOUT 2026-09-24 (coût des pertes, Palier 0) *** : valeur d'UNE pièce en FCFA,
    -- saisie à la main (Administration > Valeur des produits) -- JAMAIS écrasée par la
    -- synchro Odoo (sync_produits ne touche que ses propres colonnes). NULL = pas de
    -- valeur propre : on retombe sur le paramètre global valeur_piece_defaut_fcfa. Ce que
    -- « valeur » représente (prix de vente, coût de revient, marge...) est un choix
    -- d'usage, pas de structure : cf. paramètre libelle_valeur_piece.
    valeur_unitaire_fcfa NUMERIC,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_produits_cache_default_code ON produits_cache (default_code);

CREATE TABLE IF NOT EXISTS of_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (mrp.production)
    reference VARCHAR(64),                  -- ex: "ENUPR/MO/38653"
    produit_id INTEGER REFERENCES produits_cache(id),
    produit_nom VARCHAR(255),               -- dénormalisé
    ligne_id INTEGER REFERENCES lignes_cache(id),
    qty_planifiee NUMERIC,
    date_debut TIMESTAMP,
    date_echeance TIMESTAMP,
    etat VARCHAR(64),
    -- *** Chantier Labo *** : filtre "ENUPR/%" appliqué à la source (usine plastique
    -- exclue) -- usine reste 'UPRINC' en pratique, écrit en dur plutôt que déduit, pour
    -- rester correct si ce filtre est un jour retiré (décision : garder la possibilité
    -- d'intégrer l'usine plastique plus tard). production_date = vrai jour de
    -- production (distinct de date_debut/date_echeance, prévisionnels). saisie_reference
    -- = référence production.entry (ex. 'PROC008552'), pour mesurer le délai réel de
    -- saisie (F3).
    usine VARCHAR(10),
    production_date DATE,
    saisie_reference VARCHAR(20),
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_of_cache_usine_production_date ON of_cache (usine, production_date);

CREATE TABLE IF NOT EXISTS cadence_reference (
    id SERIAL PRIMARY KEY,
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    -- Synchronisée depuis Odoo (mrp.packaging.pp.capacity) mais reste éditable à la
    -- main (pas un simple cache en lecture seule) -- confirmé inexploitable en l'état
    -- (charge médiane 12%, jusqu'à 58 824% mesuré) : donnée INFORMATIVE, ne pilote
    -- jamais le calcul de performance ni la capacité démontrée du Labo (F1, qui
    -- utilise l'historique réel des OF, pas ce champ).
    cadence_theorique_horaire NUMERIC,      -- pcs/h
    source_cadence VARCHAR(20) NOT NULL DEFAULT 'odoo_sync',  -- 'odoo_sync' | 'manuel'
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (produit_id, ligne_id)
);

-- Le pilotage réel se fait via un planning HEBDOMADAIRE (mrp.planning côté Odoo),
-- détaillé jour par jour et par ligne (mrp.detail.planning.line) -- c'est cette
-- source, pas of_cache, qui alimente le calcul du théorique (cf. performance_service.py).
CREATE TABLE IF NOT EXISTS planning_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (mrp.planning)
    reference VARCHAR(64),                  -- ex: "OPF01274"
    code VARCHAR(64),
    section_id INTEGER REFERENCES sections_cache(id),
    begin_date DATE,
    end_date DATE,
    etat VARCHAR(20),                       -- 'draft' | 'confirmed' | 'cancel'
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS planning_detail_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (mrp.detail.planning.line)
    planning_id INTEGER NOT NULL REFERENCES planning_cache(id),
    ligne_id INTEGER REFERENCES lignes_cache(id),
    produit_id INTEGER REFERENCES produits_cache(id),
    jour DATE NOT NULL,
    qty NUMERIC,
    colisage NUMERIC,
    contenance NUMERIC,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_planning_detail_ligne_jour ON planning_detail_cache (ligne_id, jour);

-- =============================================================
-- 3. DONNÉES PROPRES À VUSINE (saisies tablette / gérées par l'admin)
-- =============================================================

CREATE TABLE IF NOT EXISTS configuration_poste (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(50) UNIQUE NOT NULL,
    heure_debut TIME NOT NULL,
    heure_fin TIME NOT NULL,
    pause_debut TIME,
    pause_fin TIME,
    actif BOOLEAN NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_configuration_poste_actif
    ON configuration_poste (actif) WHERE actif = true;

CREATE TABLE IF NOT EXISTS jours_speciaux (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    type VARCHAR(30) NOT NULL DEFAULT 'ferie',  -- 'ferie' | 'horaire_special' | 'ferme'
    heure_debut TIME,
    heure_fin TIME,
    pause_debut TIME,
    pause_fin TIME,
    commentaire TEXT
);

CREATE TABLE IF NOT EXISTS equipements (
    id SERIAL PRIMARY KEY,
    -- Identité PHYSIQUE et IMMUABLE d'une machine (numero_interne ne change jamais),
    -- indépendante de la ligne où elle se trouve à un instant T -- cf.
    -- affectations_equipement_ligne pour "sur quelle ligne, depuis quand".
    type VARCHAR(50) NOT NULL,
    marque VARCHAR(100),
    modele VARCHAR(100),
    numero_interne VARCHAR(50) UNIQUE,
    capacite VARCHAR(100),
    statut VARCHAR(20) NOT NULL DEFAULT 'disponible',  -- disponible | en_panne | en_maintenance | retire
    derniere_maintenance DATE,
    prochaine_maintenance DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS affectations_equipement_ligne (
    id SERIAL PRIMARY KEY,
    equipement_id INTEGER NOT NULL REFERENCES equipements(id),
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    date_debut TIMESTAMP NOT NULL,
    date_fin TIMESTAMP,              -- NULL = affectation en cours
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS causes_arret (
    id SERIAL PRIMARY KEY,
    libelle VARCHAR(100) UNIQUE NOT NULL,
    actif BOOLEAN NOT NULL DEFAULT true,
    ordre_affichage INTEGER NOT NULL DEFAULT 0,
    -- *** AJOUT 2026-09-24 (Palier 2, scoring d'équipe) *** : true = l'arrêt peut être reproché
    -- à l'équipe de la ligne dans son score ; false (défaut) = arrêt NEUTRALISÉ (panne, manque
    -- de matière...). Défaut prudent : rien n'est reproché à une équipe tant que la Direction
    -- n'a pas décidé, cause par cause, qu'elle l'est.
    imputable_equipe BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS arrets (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    cause_id INTEGER NOT NULL REFERENCES causes_arret(id),
    equipement_id INTEGER REFERENCES equipements(id),  -- nullable : "Manque MP" ne pointe aucune machine
    commentaire TEXT,
    heure_debut TIMESTAMP NOT NULL,
    heure_fin TIMESTAMP,                    -- NULL = arrêt toujours en cours
    operateur_id INTEGER NOT NULL REFERENCES users(id),
    -- Un arrêt neutralisé compte toujours dans les statistiques (Rapports, TRS) mais
    -- est exclu du calcul de scoring CDI/CDD -- l'équipe n'est pas pénalisée pour une
    -- cause hors de son contrôle.
    neutralise_score BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS palettes (
    id SERIAL PRIMARY KEY,
    numero_palette VARCHAR(50) UNIQUE NOT NULL,  -- PAL-{code_ligne}-{YYYYMMDD}-{seq}
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    of_id INTEGER REFERENCES of_cache(id),            -- legacy, plus renseigné pour les nouvelles palettes
    planning_detail_id INTEGER REFERENCES planning_detail_cache(id),
    numero_lot VARCHAR(50) NOT NULL,
    date_expiration DATE,
    nb_cartons INTEGER NOT NULL,
    colisage_carton INTEGER NOT NULL,
    quantite_totale INTEGER NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT true,
    -- NULL si complete=true, texte libre côté tablette si complete=false (fin OF, fin
    -- poste, manque composants...).
    motif_partielle VARCHAR(100),
    -- *** AJOUT 2026-09-24 (Palier 1, TRS) *** : pièces REBUTÉES constatées pendant le
    -- remplissage de cette palette (déclarées par l'opérateur au scan, 0 par défaut). Elles
    -- ne sont PAS comptées dans quantite_totale (qui ne contient que les pièces conformes
    -- palettisées) : production brute = quantite_totale + nb_rebuts. Sert à la composante
    -- Qualité du TRS. 0 signifie « aucun rebut déclaré », pas forcément « vérifié ».
    nb_rebuts INTEGER NOT NULL DEFAULT 0 CHECK (nb_rebuts >= 0),
    operateur_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS affectations_ligne (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    date_debut TIMESTAMP NOT NULL,
    date_fin TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Snapshot quotidien de la performance de chaque ligne, figé chaque soir (jamais
-- recalculé rétroactivement) -- base du scoring CDI/CDD.
CREATE TABLE IF NOT EXISTS performance_ligne_jour (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    jour DATE NOT NULL,
    reel INTEGER NOT NULL,
    theorique INTEGER,
    performance_pct INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ligne_id, jour)
);

CREATE TABLE IF NOT EXISTS palettes_corrections (
    id SERIAL PRIMARY KEY,
    palette_id INTEGER NOT NULL REFERENCES palettes(id),
    corrige_par INTEGER NOT NULL REFERENCES users(id),
    champ_modifie VARCHAR(50) NOT NULL,
    ancienne_valeur TEXT,
    nouvelle_valeur TEXT,
    motif TEXT,
    corrige_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alertes (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL CHECK (type IN (
        'performance', 'silence_scan', 'ralentissement_progressif',
        'partielle_non_justifiee', 'of_termine_scan'
    )),
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    palette_id INTEGER REFERENCES palettes(id),
    message TEXT NOT NULL,
    niveau VARCHAR(20) NOT NULL CHECK (niveau IN ('info', 'orange', 'rouge')),
    resolue BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_alertes_ligne_type_resolue ON alertes (ligne_id, type, resolue);

CREATE TABLE IF NOT EXISTS receptions_magasin (
    id SERIAL PRIMARY KEY,
    palette_id INTEGER UNIQUE NOT NULL REFERENCES palettes(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    receptionne_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DO $$ BEGIN RAISE NOTICE '✅ Schéma métier Vusine créé.'; END; $$;

-- =============================================================================
-- 4. CHANTIER LABO (F1-F10, F5) -- calculs déterministes issus de SIVOX, visibles
-- uniquement par le compte is_super_admin (cf. auth_routes.require_labo).
-- =============================================================================

DO $$ BEGIN RAISE NOTICE '📥 Création du schéma Labo'; END; $$;

-- --- ETL v2 : référentiels et historique enrichi synchronisés depuis Odoo ---------

CREATE TABLE IF NOT EXISTS saisies_production_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (production.entry)
    reference VARCHAR(20),                  -- 'PROC...' (UPRINC) | 'PROP...' (UPLAST)
    usine VARCHAR(10),
    production_date DATE,
    create_date TIMESTAMP,
    write_date TIMESTAMP,
    etat VARCHAR(20),
    auteur_nom VARCHAR(100),
    synced_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corrections_cache (
    id INTEGER PRIMARY KEY,                 -- id Odoo (mrp.unbuild)
    of_id INTEGER REFERENCES of_cache(id),
    ligne_id INTEGER REFERENCES lignes_cache(id),
    origine VARCHAR(255),
    etat VARCHAR(20),
    date_correction DATE,
    synced_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS formules_cache (
    id SERIAL PRIMARY KEY,
    bom_id INTEGER NOT NULL,
    produit_fini_code VARCHAR(30) NOT NULL,
    composant_code VARCHAR(30) NOT NULL,
    quantite NUMERIC NOT NULL,
    synced_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_formule_composant UNIQUE (bom_id, produit_fini_code, composant_code)
);

CREATE TABLE IF NOT EXISTS stock_matieres_cache (
    id SERIAL PRIMARY KEY,
    produit_code VARCHAR(30) NOT NULL UNIQUE,
    quantite_disponible NUMERIC NOT NULL,
    synced_at TIMESTAMP DEFAULT now()
);

-- Fraîcheur par domaine synchronisé -- affiché en admin/Labo.
CREATE TABLE IF NOT EXISTS sync_state (
    domaine VARCHAR(50) PRIMARY KEY,
    derniere_synchro TIMESTAMP,
    nb_lignes INTEGER
);

CREATE TABLE IF NOT EXISTS labo_formules_explosion (
    id SERIAL PRIMARY KEY,
    produit_fini_code VARCHAR(30) NOT NULL,
    composant_code VARCHAR(30) NOT NULL,
    quantite_par_unite NUMERIC NOT NULL,
    explosion_complete BOOLEAN NOT NULL DEFAULT true,
    synced_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_explosion_produit_composant UNIQUE (produit_fini_code, composant_code)
);
CREATE INDEX IF NOT EXISTS ix_explosion_produit ON labo_formules_explosion (produit_fini_code);
CREATE INDEX IF NOT EXISTS ix_explosion_composant ON labo_formules_explosion (composant_code);

CREATE TABLE IF NOT EXISTS labo_ecarts_inventaire (
    id INTEGER PRIMARY KEY,                 -- id Odoo (stock.quant.entry.line)
    inventaire_reference VARCHAR(30),
    produit_code VARCHAR(30),
    emplacement_nom VARCHAR(100),
    date_validation DATE,
    stock_systeme NUMERIC,
    stock_compte NUMERIC,
    ecart_qte NUMERIC,
    ecart_valeur NUMERIC,
    synced_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ecarts_inventaire_produit ON labo_ecarts_inventaire (produit_code);

CREATE TABLE IF NOT EXISTS labo_fournisseurs_matiere (
    id INTEGER PRIMARY KEY,                 -- id Odoo (product.supplierinfo)
    matiere_code VARCHAR(30) NOT NULL,
    fournisseur_nom VARCHAR(150),
    delai_jours INTEGER NOT NULL DEFAULT 0,
    quantite_min NUMERIC,
    synced_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fournisseurs_matiere_code ON labo_fournisseurs_matiere (matiere_code);

-- --- Calculs Labo (recalculés par les ingestors, jamais édités à la main sauf
-- source='manuel' sur labo_lignes_eligibles_produit) ------------------------------

CREATE TABLE IF NOT EXISTS labo_capacite_ligne_produit (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    nb_jours_observes INTEGER NOT NULL,
    mediane_jour NUMERIC,
    p90_jour NUMERIC,
    dernier_jour_observe DATE,
    nb_jours_atypiques INTEGER NOT NULL DEFAULT 0,
    calcule_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_capacite_ligne_produit UNIQUE (ligne_id, produit_id)
);

CREATE TABLE IF NOT EXISTS labo_lignes_eligibles_produit (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    source VARCHAR(20) NOT NULL,  -- 'historique' | 'manuel'
    calcule_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_ligne_eligible_produit UNIQUE (ligne_id, produit_id)
);

-- *** AJOUT 2026-09-23 (F4) *** : mémoire des analyses LLM déjà générées, pour ne
-- jamais payer deux fois la même analyse et pour qu'elle reste visible après un
-- rafraîchissement -- jusqu'à ce que les chiffres sous-jacents changent (donnees_hash).
CREATE TABLE IF NOT EXISTS labo_explication_cache (
    id SERIAL PRIMARY KEY,
    domaine VARCHAR(50) NOT NULL,
    cle_signature VARCHAR(200) NOT NULL,
    donnees_hash VARCHAR(64) NOT NULL,
    contenu TEXT NOT NULL,
    modele VARCHAR(100),
    genere_le TIMESTAMP DEFAULT now(),
    mis_a_jour_le TIMESTAMP DEFAULT now(),
    UNIQUE (domaine, cle_signature)
);

CREATE TABLE IF NOT EXISTS labo_prevision_volume (
    id SERIAL PRIMARY KEY,
    -- Grain produit (toutes lignes confondues) depuis le 23/09 -- plus de ligne_id,
    -- la répartition entre lignes est le rôle de labo_plan_optimise (F8).
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    jour_horizon DATE NOT NULL,
    qte_prevue NUMERIC,
    intervalle_bas NUMERIC,
    intervalle_haut NUMERIC,
    calcule_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prevision_produit_jour ON labo_prevision_volume (produit_id, jour_horizon);

CREATE TABLE IF NOT EXISTS labo_plan_optimise (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER REFERENCES lignes_cache(id),
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    jour DATE NOT NULL,
    qte_recommandee NUMERIC NOT NULL,
    qte_planning_reel NUMERIC,
    deficit_residuel NUMERIC NOT NULL DEFAULT 0,
    calcule_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS labo_besoin_matiere_projete (
    id SERIAL PRIMARY KEY,
    matiere_code VARCHAR(30) NOT NULL,
    date_rupture_projetee DATE,
    stock_projete NUMERIC NOT NULL,
    calcule_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_besoin_matiere_code ON labo_besoin_matiere_projete (matiere_code);

CREATE TABLE IF NOT EXISTS labo_alertes_achat (
    id SERIAL PRIMARY KEY,
    matiere_code VARCHAR(30) NOT NULL,
    date_rupture_projetee DATE NOT NULL,
    quantite_manquante NUMERIC NOT NULL,
    meilleur_delai_jours INTEGER,
    date_limite_commande DATE,
    nb_fournisseurs_disponibles INTEGER NOT NULL DEFAULT 0,
    calcule_at TIMESTAMP DEFAULT now()
);

-- *** F6 (nouveau) *** : priorise les alertes d'achat (F9b) selon l'historique réel
-- des arrêts "Manque MP"/"Manque emballage" sur chaque ligne -- cf.
-- labo_emballage_ingestor.py pour le calcul.
CREATE TABLE IF NOT EXISTS labo_alertes_emballage_ligne (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    matiere_code VARCHAR(30) NOT NULL,
    nb_arrets_manque_historique INTEGER NOT NULL DEFAULT 0,
    date_limite_commande DATE,
    priorite VARCHAR(10) NOT NULL DEFAULT 'normale',  -- 'haute' | 'normale'
    calcule_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_alertes_emballage_ligne ON labo_alertes_emballage_ligne (ligne_id, priorite);

CREATE TABLE IF NOT EXISTS labo_simulation_productible (
    id SERIAL PRIMARY KEY,
    produit_fini_code VARCHAR(30) NOT NULL UNIQUE,
    -- BIGINT (pas INTEGER) : un stock/besoin_par_unite peut dépasser la portée d'un
    -- INTEGER même après clamp des ratios négatifs à 0 côté ingestor -- corrigé
    -- 2026-09-22 suite à un dépassement réel en prod (integer out of range).
    quantite_productible BIGINT NOT NULL,
    composant_limitant_code VARCHAR(30),
    stock_limitant NUMERIC,
    besoin_limitant_par_unite NUMERIC,
    nb_composants_sans_stock_connu INTEGER NOT NULL DEFAULT 0,
    calcule_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS labo_ecritures_odoo_proposees (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES lignes_cache(id),
    jour DATE NOT NULL,
    produit_id INTEGER NOT NULL REFERENCES produits_cache(id),
    quantite_reelle INTEGER NOT NULL,
    nb_palettes INTEGER NOT NULL,
    nb_palettes_partielles INTEGER NOT NULL DEFAULT 0,
    calculee_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_ecriture_proposee UNIQUE (ligne_id, jour, produit_id)
);

CREATE TABLE IF NOT EXISTS labo_comparaison_ecritures (
    id SERIAL PRIMARY KEY,
    ligne_id INTEGER REFERENCES lignes_cache(id),
    jour DATE NOT NULL,
    produit_id INTEGER REFERENCES produits_cache(id),
    quantite_vusine INTEGER,
    quantite_odoo INTEGER,
    ecart_qte INTEGER,
    ecart_pct NUMERIC,
    calculee_at TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_comparaison_ecriture UNIQUE (ligne_id, jour, produit_id)
);

-- =============================================================
-- ÉVOLUTIONS REJOUABLES (bases déjà existantes) -- idempotentes, sans effet sur une base
-- fraîche où les colonnes sont déjà dans les CREATE TABLE ci-dessus.
-- =============================================================
ALTER TABLE produits_cache ADD COLUMN IF NOT EXISTS valeur_unitaire_fcfa NUMERIC;  -- 2026-09-24
ALTER TABLE causes_arret ADD COLUMN IF NOT EXISTS imputable_equipe BOOLEAN NOT NULL DEFAULT false;   -- 2026-09-24 (Palier 2)
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(50);   -- 2026-09-24 (Palier 1)
ALTER TABLE palettes ADD COLUMN IF NOT EXISTS nb_rebuts INTEGER NOT NULL DEFAULT 0;   -- 2026-09-24 (Palier 1)

DO $$ BEGIN RAISE NOTICE '✅ Schéma Labo créé -- schema.sql terminé.'; END; $$;

-- *** AJOUT 2026-09-24 (Palier 2, scoring d'équipe) ***
-- Journal des consultations du suivi individuel (formation) : QUI a consulté le suivi de QUI,
-- et sur quelle période. Alimenté à chaque consultation, jamais modifié ni purgé par l'API.
CREATE TABLE IF NOT EXISTS suivi_individuel_acces (
    id SERIAL PRIMARY KEY,
    consulte_par INTEGER NOT NULL REFERENCES users(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    periode_debut DATE NOT NULL,
    periode_fin DATE NOT NULL,
    consulte_le TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_suivi_acces_date ON suivi_individuel_acces (consulte_le DESC);
