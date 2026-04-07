import sqlite3
from werkzeug.security import generate_password_hash

connection = sqlite3.connect('database.db')
connection.execute("PRAGMA foreign_keys = ON")

with open('schema.sql') as f:
    connection.executescript(f.read())

cur = connection.cursor()

# Gebruikers
cur.execute("INSERT INTO users (username, password_hash, nom, role) VALUES (?, ?, ?, ?)",
            ('admin', generate_password_hash('admin123'), 'Administrateur', 'admin'))
cur.execute("INSERT INTO users (username, password_hash, nom, role) VALUES (?, ?, ?, ?)",
            ('employe', generate_password_hash('emp123'), 'Employé', 'employee'))

# Types d'élément
cur.execute("INSERT INTO types_element (nom) VALUES (?)", ('Sutures',))
cur.execute("INSERT INTO types_element (nom) VALUES (?)", ('Instruments',))
cur.execute("INSERT INTO types_element (nom) VALUES (?)", ('Implants',))
cur.execute("INSERT INTO types_element (nom) VALUES (?)", ('Consommables',))

# Catégories
cur.execute("INSERT INTO categories (nom) VALUES (?)", ('DACLON',))
cur.execute("INSERT INTO categories (nom) VALUES (?)", ('CHIRURGIE',))
cur.execute("INSERT INTO categories (nom) VALUES (?)", ('ORTHOPÉDIE',))
cur.execute("INSERT INTO categories (nom) VALUES (?)", ('CARDIOLOGIE',))

# Clients / Hôpitaux
cur.execute("INSERT INTO clients (nom, type, adresse, ville, telephone) VALUES (?, ?, ?, ?, ?)",
            ('CHU Ibn Sina', 'Hôpital', 'Avenue Ibn Sina', 'Rabat', '+212 537 000 000'))
cur.execute("INSERT INTO clients (nom, type, adresse, ville, telephone) VALUES (?, ?, ?, ?, ?)",
            ('Clinique Al Farabi', 'Clinique', 'Rue Al Farabi', 'Casablanca', '+212 522 000 000'))
cur.execute("INSERT INTO clients (nom, type, adresse, ville, telephone) VALUES (?, ?, ?, ?, ?)",
            ('Hôpital Avicenne', 'Hôpital', 'Boulevard Avicenne', 'Rabat', '+212 537 111 111'))

# Produits
cur.execute("""
    INSERT INTO produits (reference, nom, description, code_barres, prix_revient_ttc,
                          prix_dernier_achat, stock_min_securite, type_element_id,
                          tag, categorie_id, marque, emplacement, bloc, rangee,
                          statut, tva, no_fiche, prix_tarif_1, prix_tarif_2, prix_tarif_3)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('000235', 'DACLON NYLON USP 1 3/8c 36MM CT 90CM',
      'DACLON NYLON USP 1 3/8c 36MM CT 90CM',
      '', 0, 4.88, 0, 1, '', 1, 'SMI', 'Babylon', 'Bloc 1', 'Rangée 1',
      'Actif', 20, '9601536', 20.0, 14.15, 75.0))

cur.execute("""
    INSERT INTO produits (reference, nom, description, prix_dernier_achat, stock_min_securite,
                          type_element_id, categorie_id, marque, emplacement, statut, tva,
                          prix_tarif_1, prix_tarif_2, prix_tarif_3)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('000236', 'Scalpelhouder Nr. 4', 'Scalpelhouder voor gebruik in chirurgie',
      8.50, 5, 2, 2, 'SurgeTech', 'Babylon', 'Actif', 20, 20.0, 14.15, 75.0))

cur.execute("""
    INSERT INTO produits (reference, nom, description, prix_dernier_achat, stock_min_securite,
                          type_element_id, categorie_id, marque, emplacement, statut, tva,
                          prix_tarif_1, prix_tarif_2, prix_tarif_3)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('000237', 'Stethoscoop Pro', 'Professionele stethoscoop',
      45.00, 2, 2, 2, 'MedLine', 'Entrepôt B', 'Actif', 20, 20.0, 14.15, 75.0))

# Prix de vente per client
cur.execute("INSERT INTO prix_vente (produit_id, client_id, prix) VALUES (?, ?, ?)", (1, 1, 12.24))
cur.execute("INSERT INTO prix_vente (produit_id, client_id, prix) VALUES (?, ?, ?)", (1, 2, 11.50))
cur.execute("INSERT INTO prix_vente (produit_id, client_id, prix) VALUES (?, ?, ?)", (1, 3, 13.00))

# Historique achats
cur.execute("""
    INSERT INTO historique_achats (produit_id, date_achat, prix, fournisseur, quantite)
    VALUES (?, ?, ?, ?, ?)
""", (1, '2024-01-15', 4.88, 'SMI', 100))
cur.execute("""
    INSERT INTO historique_achats (produit_id, date_achat, prix, fournisseur, quantite)
    VALUES (?, ?, ?, ?, ?)
""", (1, '2023-06-10', 4.50, 'SMI', 200))

# Lots
cur.execute("""
    INSERT INTO lots (produit_id, lot_numero, site, date_production, date_expiration,
                      warehouse, bloc, rangee, quantite)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (1, 'Zilot', 'Site A', '1970-01-01', '2024-10-05', 'Babylon', 'Bloc 1', 'Rangée 1', 50))

cur.execute("""
    INSERT INTO lots (produit_id, lot_numero, site, date_production, date_expiration,
                      warehouse, bloc, rangee, quantite)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (2, 'LOT-001', 'Site B', '2023-05-01', '2025-05-01', 'Entrepôt A', 'Bloc 2', 'Rangée 3', 12))

# Mouvements
cur.execute("""
    INSERT INTO mouvements (produit_id, type_mvt, quantite, date_mvt, reference, note)
    VALUES (?, ?, ?, ?, ?, ?)
""", (1, 'Entrée', 100, '2024-01-15', 'BON-001', 'Réception commande'))
cur.execute("""
    INSERT INTO mouvements (produit_id, type_mvt, quantite, date_mvt, reference, note)
    VALUES (?, ?, ?, ?, ?, ?)
""", (1, 'Sortie', 50, '2024-02-20', 'BON-002', 'Livraison CHU Ibn Sina'))

# Factures (voorbeelddata)
cur.execute("""
    INSERT INTO factures (numero, client_id, date_facture, date_echeance, devise,
                          emplacement_stock, objet, statut,
                          montant_ht, remise_globale, montant_tva, montant_ttc)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('2026-04-000001', 1, '2026-03-31', '2026-03-31', 'MAD',
      'Babylon', 'SUTURE', 'Impayé',
      12508.23, 15.67, 2538.60, 15099.60))

cur.execute("""
    INSERT INTO factures (numero, client_id, date_facture, date_echeance, devise,
                          emplacement_stock, objet, statut,
                          montant_ht, remise_globale, montant_tva, montant_ttc)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('2026-04-000002', 2, '2026-03-28', '2026-04-28', 'MAD',
      'Babylon', 'SUTURE', 'Payé',
      875.20, 0, 175.04, 1050.24))

# Lignes de la facture 1
cur.execute("""
    INSERT INTO facture_lignes (facture_id, produit_id, lot_id, reference, designation,
                                quantite, prix_unitaire, tva, remise, montant_ht)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (1, 1, 1, '000235', 'DACLON NYLON USP 1 3/8c 36MM CT 90CM LOT:Zilot',
      24, 36.3, 20.0, 0, 871.20))
cur.execute("""
    INSERT INTO facture_lignes (facture_id, produit_id, lot_id, reference, designation,
                                quantite, prix_unitaire, tva, remise, montant_ht)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (1, 2, 2, '000236', 'Scalpelhouder Nr. 4',
      12, 29.04, 20.0, 0, 348.48))

# Lignes facture 2
cur.execute("""
    INSERT INTO facture_lignes (facture_id, produit_id, lot_id, reference, designation,
                                quantite, prix_unitaire, tva, remise, montant_ht)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (2, 3, None, '000237', 'Stethoscoop Pro',
      24, 36.3, 20.0, 0, 875.20))

connection.commit()
connection.close()
print("✅ Nieuwe database is klaar met alle tabellen!")
