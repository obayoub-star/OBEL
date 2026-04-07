PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS facture_lignes;
DROP TABLE IF EXISTS factures;
DROP TABLE IF EXISTS pieces_jointes;
DROP TABLE IF EXISTS mouvements;
DROP TABLE IF EXISTS lots;
DROP TABLE IF EXISTS prix_vente;
DROP TABLE IF EXISTS historique_achats;
DROP TABLE IF EXISTS produits;
DROP TABLE IF EXISTS clients;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS types_element;
DROP TABLE IF EXISTS voorraad;

PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    nom           TEXT,
    role          TEXT    DEFAULT 'employee',
    actif         INTEGER DEFAULT 1
);

CREATE TABLE types_element (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom  TEXT NOT NULL UNIQUE
);

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom  TEXT NOT NULL UNIQUE
);

CREATE TABLE clients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nom       TEXT NOT NULL,
    type      TEXT DEFAULT 'Hôpital',
    adresse   TEXT,
    ville     TEXT,
    telephone TEXT,
    email     TEXT
);

CREATE TABLE produits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT,
    nom                 TEXT NOT NULL,
    description         TEXT,
    code_barres         TEXT,
    prix_revient_ttc    REAL    DEFAULT 0,
    prix_dernier_achat  REAL    DEFAULT 0,
    stock_min_securite  INTEGER DEFAULT 0,
    type_element_id     INTEGER,
    tag                 TEXT,
    categorie_id        INTEGER,
    marque              TEXT,
    emplacement         TEXT,
    bloc                TEXT,
    rangee              TEXT,
    statut              TEXT    DEFAULT 'Actif',
    tva                 REAL    DEFAULT 20,
    no_fiche            TEXT,
    prix_tarif_1        REAL    DEFAULT 20,
    prix_tarif_2        REAL    DEFAULT 14.15,
    prix_tarif_3        REAL    DEFAULT 75,
    FOREIGN KEY (type_element_id) REFERENCES types_element(id),
    FOREIGN KEY (categorie_id)    REFERENCES categories(id)
);

CREATE TABLE prix_vente (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id INTEGER NOT NULL,
    client_id  INTEGER NOT NULL,
    prix       REAL    DEFAULT 0,
    FOREIGN KEY (produit_id) REFERENCES produits(id)  ON DELETE CASCADE,
    FOREIGN KEY (client_id)  REFERENCES clients(id)
);

CREATE TABLE historique_achats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id  INTEGER NOT NULL,
    date_achat  TEXT,
    prix        REAL    DEFAULT 0,
    fournisseur TEXT,
    quantite    INTEGER DEFAULT 1,
    FOREIGN KEY (produit_id) REFERENCES produits(id) ON DELETE CASCADE
);

CREATE TABLE lots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id      INTEGER NOT NULL,
    lot_numero      TEXT,
    site            TEXT,
    date_production TEXT,
    date_expiration TEXT,
    warehouse       TEXT,
    bloc            TEXT,
    rangee          TEXT,
    quantite        INTEGER DEFAULT 0,
    FOREIGN KEY (produit_id) REFERENCES produits(id) ON DELETE CASCADE
);

CREATE TABLE mouvements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id  INTEGER NOT NULL,
    type_mvt    TEXT,
    quantite    INTEGER,
    date_mvt    TEXT,
    reference   TEXT,
    note        TEXT,
    FOREIGN KEY (produit_id) REFERENCES produits(id) ON DELETE CASCADE
);

CREATE TABLE factures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    numero              TEXT UNIQUE,
    client_id           INTEGER,
    date_facture        TEXT,
    date_echeance       TEXT,
    devise              TEXT    DEFAULT 'MAD',
    emplacement_stock   TEXT,
    contact_commercial  TEXT,
    modele              TEXT,
    objet               TEXT,
    remarques           TEXT,
    conditions          TEXT,
    statut              TEXT    DEFAULT 'En instance',
    montant_ht          REAL    DEFAULT 0,
    remise_globale      REAL    DEFAULT 0,
    montant_tva         REAL    DEFAULT 0,
    ajustement          REAL    DEFAULT 0,
    montant_ttc         REAL    DEFAULT 0,
    FOREIGN KEY (client_id) REFERENCES clients(id)
);

CREATE TABLE facture_lignes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    facture_id     INTEGER NOT NULL,
    produit_id     INTEGER,
    lot_id         INTEGER,
    reference      TEXT,
    designation    TEXT,
    quantite       REAL    DEFAULT 1,
    prix_unitaire  REAL    DEFAULT 0,
    tva            REAL    DEFAULT 20,
    remise         REAL    DEFAULT 0,
    montant_ht     REAL    DEFAULT 0,
    FOREIGN KEY (facture_id) REFERENCES factures(id)  ON DELETE CASCADE,
    FOREIGN KEY (produit_id) REFERENCES produits(id),
    FOREIGN KEY (lot_id)     REFERENCES lots(id)
);

CREATE TABLE pieces_jointes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id  INTEGER NOT NULL,
    nom_fichier TEXT,
    chemin      TEXT,
    date_ajout  TEXT,
    FOREIGN KEY (produit_id) REFERENCES produits(id) ON DELETE CASCADE
);
