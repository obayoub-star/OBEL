import sqlite3
import csv
import io
import datetime
import functools
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'medicatronic_secret_2024'

VALID_SORT_COLS = {
    'reference':   'p.reference',
    'nom':         'p.nom',
    'marque':      'p.marque',
    'categorie':   'c.nom',
    'prix_achat':  'p.prix_dernier_achat',
    'stock_total': 'stock_calc',
}
NUM_SORT_COLS = {'prix_achat', 'stock_total'}


# ─── DB ───────────────────────────────────────────────────────────────────────
def migrate_db():
    """Add any missing columns to existing database (safe to run multiple times)."""
    conn = sqlite3.connect('database.db')
    migrations = [
        ('clients', 'adresse',   'TEXT'),
        ('clients', 'ville',     'TEXT'),
        ('clients', 'telephone', 'TEXT'),
        ('clients', 'email',     'TEXT'),
        ('clients', 'code_client',          'TEXT'),
        ('clients', 'ice',                  'TEXT'),
        ('clients', 'identifiant_fiscal',   'TEXT'),
        ('clients', 'code_postal',          'TEXT'),
        ('clients', 'region',               'TEXT'),
        ('clients', 'pays',                 'TEXT DEFAULT "Maroc"'),
        ('clients', 'gsm',                  'TEXT'),
        ('clients', 'contact',              'TEXT'),
        ('clients', 'tarification',         'TEXT DEFAULT "T1"'),
        ('clients', 'categorie_client',     'TEXT'),
        ('clients', 'latitude',             'TEXT'),
        ('clients', 'longitude',            'TEXT'),
        ('clients', 'adresse_facturation',  'TEXT'),
        ('clients', 'ville_facturation',    'TEXT'),
        ('clients', 'region_facturation',   'TEXT'),
        ('clients', 'code_postal_facturation', 'TEXT'),
        ('clients', 'pays_facturation',     'TEXT'),
        ('clients', 'adresse_livraison',    'TEXT'),
        ('clients', 'ville_livraison',      'TEXT'),
        ('clients', 'region_livraison',     'TEXT'),
        ('clients', 'code_postal_livraison','TEXT'),
        ('clients', 'pays_livraison',       'TEXT'),
        ('clients', 'actif',                'INTEGER DEFAULT 1'),
        ('clients', 'est_fournisseur',      'INTEGER DEFAULT 0'),
        ('factures', 'type_document',       "TEXT DEFAULT 'Facture'"),
        ('factures', 'client_ref',          'TEXT'),
        ('factures', 'date_peremption_souhaitee', 'TEXT'),
        ('factures', 'date_livraison_souhaitee',  'TEXT'),
    ]
    for table, col, col_type in migrations:
        try:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}')
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.close()

migrate_db()


def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash("Accès réservé à l'administrateur.", 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ─── FACTURE HELPERS ──────────────────────────────────────────────────────────
DOC_PREFIXES = {
    'Facture':          'F',
    'Devis':            'D',
    'Bon de travail':   'BT',
    'Bon de livraison': 'BL',
    'Avoir':            'A',
}

def generate_numero_document(conn, type_document='Facture'):
    """Generate document number like F2026-04-000001, D2026-04-000001, etc."""
    today  = datetime.date.today()
    code   = DOC_PREFIXES.get(type_document, 'F')
    prefix = f"{code}{today.year}-{today.month:02d}-"
    last   = conn.execute(
        "SELECT numero FROM factures WHERE numero LIKE ? ORDER BY numero DESC LIMIT 1",
        (f"{prefix}%",)
    ).fetchone()
    seq = int(last['numero'].rsplit('-', 1)[-1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def generate_numero_facture(conn):
    """Backward compatible wrapper."""
    return generate_numero_document(conn, 'Facture')


def recalculate_facture(conn, facture_id):
    lignes  = conn.execute(
        'SELECT montant_ht, tva FROM facture_lignes WHERE facture_id = ?',
        (facture_id,)
    ).fetchall()
    ht      = sum(l['montant_ht'] for l in lignes)
    tva_amt = sum(l['montant_ht'] * l['tva'] / 100 for l in lignes)
    facture = conn.execute(
        'SELECT remise_globale, ajustement FROM factures WHERE id = ?',
        (facture_id,)
    ).fetchone()
    remise  = facture['remise_globale'] if facture else 0
    ajust   = facture['ajustement']     if facture else 0
    ttc     = ht + tva_amt - remise + ajust
    conn.execute('''
        UPDATE factures SET montant_ht=?, montant_tva=?, montant_ttc=? WHERE id=?
    ''', (round(ht, 4), round(tva_amt, 4), round(ttc, 4), facture_id))


# ─── SORT HELPERS ─────────────────────────────────────────────────────────────
def parse_sorts(sorts_str):
    if not sorts_str:
        return []
    result = []
    for part in sorts_str.split(','):
        parts = part.strip().split(':')
        if len(parts) == 2:
            col, direction = parts[0].strip(), parts[1].strip()
            if col in VALID_SORT_COLS and direction in ('asc', 'desc'):
                result.append((col, direction))
    return result


def build_sort_url(current_sorts_str, col):
    sorts       = parse_sorts(current_sorts_str)
    default_dir = 'desc' if col in NUM_SORT_COLS else 'asc'
    for i, (c, d) in enumerate(sorts):
        if c == col:
            sorts[i] = (col, 'asc' if d == 'desc' else 'desc')
            return ','.join(f"{c}:{d}" for c, d in sorts)
    sorts.append((col, default_dir))
    return ','.join(f"{c}:{d}" for c, d in sorts)


def get_sort_icon(sorts, col):
    for c, d in sorts:
        if c == col:
            return 'fa-sort-up' if d == 'asc' else 'fa-sort-down'
    return 'fa-sort'


# ─── LOGIN / LOGOUT ───────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn     = get_db_connection()
        user     = conn.execute(
            'SELECT * FROM users WHERE username = ? AND actif = 1', (username,)
        ).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['nom']      = user['nom']
            session['role']     = user['role']
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        error = "Nom d'utilisateur ou mot de passe incorrect."
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    conn   = get_db_connection()
    today  = datetime.date.today()
    month  = today.strftime('%Y-%m')

    # KPI stats
    total_produits = conn.execute('SELECT COUNT(*) AS n FROM produits').fetchone()['n']
    stock_critique = conn.execute('''
        SELECT COUNT(*) AS n FROM produits p
        WHERE COALESCE((SELECT SUM(l.quantite) FROM lots l WHERE l.produit_id=p.id),0)
              <= p.stock_min_securite
    ''').fetchone()['n']
    ventes_mois_ttc = conn.execute('''
        SELECT COALESCE(SUM(montant_ttc),0) AS s FROM factures
        WHERE statut != 'Annulé' AND date_facture LIKE ?
    ''', (f'{month}%',)).fetchone()['s']
    nb_clients = conn.execute('SELECT COUNT(*) AS n FROM clients').fetchone()['n']

    # Marques for dropdown filter
    marques = conn.execute(
        'SELECT DISTINCT marque FROM produits WHERE marque IS NOT NULL AND marque != "" ORDER BY marque'
    ).fetchall()

    conn.close()
    return render_template('index.html',
                           total_produits=total_produits,
                           stock_critique=stock_critique,
                           ventes_mois_ttc=ventes_mois_ttc,
                           nb_clients=nb_clients,
                           marques=marques)


# ─── DASHBOARD API ────────────────────────────────────────────────────────────
@app.route('/api/dashboard/stock-par-marque')
@login_required
def api_stock_par_marque():
    marque_filter = request.args.get('marque', '')
    conn  = get_db_connection()
    query = '''
        SELECT p.marque,
               COALESCE(SUM(l.quantite), 0) AS total_stock
        FROM produits p
        LEFT JOIN lots l ON l.produit_id = p.id
    '''
    params = []
    if marque_filter:
        query += ' WHERE p.marque = ?'
        params.append(marque_filter)
    query += ' GROUP BY p.marque ORDER BY total_stock DESC LIMIT 15'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify({'labels': [r['marque'] or 'Inconnu' for r in rows],
                    'data':   [r['total_stock'] for r in rows]})


@app.route('/api/dashboard/top-ventes')
@login_required
def api_top_ventes():
    periode = request.args.get('periode', 'mois')   # 'mois' or 'annee'
    today   = datetime.date.today()
    prefix  = today.strftime('%Y-%m') if periode == 'mois' else str(today.year)
    conn    = get_db_connection()
    rows    = conn.execute('''
        SELECT fl.designation,
               COALESCE(SUM(fl.quantite), 0) AS total_qte,
               COALESCE(SUM(fl.montant_ht), 0) AS total_ht
        FROM facture_lignes fl
        JOIN factures f ON fl.facture_id = f.id
        WHERE f.date_facture LIKE ? AND f.statut != 'Annulé'
        GROUP BY fl.designation
        ORDER BY total_qte DESC
        LIMIT 8
    ''', (f'{prefix}%',)).fetchall()
    conn.close()
    return jsonify({'labels': [r['designation'] or '—' for r in rows],
                    'data':   [float(r['total_qte']) for r in rows],
                    'data_ht': [float(r['total_ht']) for r in rows]})


@app.route('/api/dashboard/top-clients')
@login_required
def api_top_clients():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT cl.nom,
               COUNT(f.id)           AS nb_factures,
               COALESCE(SUM(f.montant_ttc), 0) AS total_ttc
        FROM factures f
        JOIN clients cl ON f.client_id = cl.id
        WHERE f.statut != 'Annulé'
        GROUP BY cl.id, cl.nom
        ORDER BY total_ttc DESC
        LIMIT 8
    ''').fetchall()
    conn.close()
    return jsonify({'labels': [r['nom'] for r in rows],
                    'data':   [float(r['total_ttc']) for r in rows],
                    'nb':     [r['nb_factures'] for r in rows]})


@app.route('/api/dashboard/evolution-ventes')
@login_required
def api_evolution_ventes():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT strftime('%Y-%m', date_facture) AS mois,
               COALESCE(SUM(montant_ttc), 0) AS total
        FROM factures
        WHERE statut != 'Annulé' AND date_facture IS NOT NULL
        GROUP BY mois
        ORDER BY mois
        LIMIT 12
    ''').fetchall()
    conn.close()
    return jsonify({'labels': [r['mois'] for r in rows],
                    'data':   [float(r['total']) for r in rows]})


# ─── OVERZICHT VERKOPEN / STOCK ───────────────────────────────────────────────
@app.route('/overview')
@login_required
def overview():
    conn   = get_db_connection()
    filtre = request.args.get('type', 'all')  # all | vendu | stock | mouvement

    # Verkochte producten (via factuurlijnen)
    ventes_rows = conn.execute('''
        SELECT fl.designation, fl.reference, fl.quantite, fl.prix_unitaire,
               fl.montant_ht, f.date_facture, f.numero AS facture_num,
               cl.nom AS client_nom, f.statut,
               p.marque
        FROM facture_lignes fl
        JOIN factures f ON fl.facture_id = f.id
        LEFT JOIN clients cl ON f.client_id = cl.id
        LEFT JOIN produits p ON fl.produit_id = p.id
        ORDER BY f.date_facture DESC
        LIMIT 200
    ''').fetchall()

    # Stock huidige stand per warehouse
    stock_rows = conn.execute('''
        SELECT p.nom, p.reference, p.marque,
               l.lot_numero, l.warehouse, l.bloc, l.rangee,
               l.quantite, l.date_expiration
        FROM lots l
        JOIN produits p ON l.produit_id = p.id
        WHERE l.quantite > 0
        ORDER BY p.marque, p.nom
    ''').fetchall()

    # Bewegingen
    mvt_rows = conn.execute('''
        SELECT m.*, p.nom AS produit_nom, p.reference AS produit_ref, p.marque
        FROM mouvements m
        JOIN produits p ON m.produit_id = p.id
        ORDER BY m.date_mvt DESC
        LIMIT 200
    ''').fetchall()

    conn.close()
    return render_template('overview.html',
                           ventes_rows=ventes_rows,
                           stock_rows=stock_rows,
                           mvt_rows=mvt_rows,
                           filtre=filtre)


# ─── PRODUCTEN LIJST ──────────────────────────────────────────────────────────
@app.route('/producten')
@login_required
def producten():
    search    = request.args.get('search', '').strip()
    sorts_str = request.args.get('sorts', '')
    sorts     = parse_sorts(sorts_str)
    conn      = get_db_connection()

    base_query = '''
        SELECT p.*,
               c.nom  AS categorie_nom,
               te.nom AS type_element_nom,
               COALESCE((SELECT SUM(l.quantite) FROM lots l WHERE l.produit_id = p.id), 0) AS stock_calc,
               (SELECT COUNT(*)    FROM prix_vente pv WHERE pv.produit_id = p.id) AS nb_prix,
               (SELECT MIN(pv.prix) FROM prix_vente pv WHERE pv.produit_id = p.id) AS prix_min,
               (SELECT MAX(pv.prix) FROM prix_vente pv WHERE pv.produit_id = p.id) AS prix_max
        FROM produits p
        LEFT JOIN categories    c  ON p.categorie_id    = c.id
        LEFT JOIN types_element te ON p.type_element_id = te.id
    '''
    params = []
    if search:
        base_query += ' WHERE (p.nom LIKE ? OR p.reference LIKE ? OR p.marque LIKE ?)'
        params      = [f'%{search}%', f'%{search}%', f'%{search}%']

    if sorts:
        order_parts = [f"{VALID_SORT_COLS[col]} {d.upper()}" for col, d in sorts if col in VALID_SORT_COLS]
        base_query += ' ORDER BY ' + (', '.join(order_parts) if order_parts else 'p.marque ASC, p.nom ASC')
    else:
        base_query += ' ORDER BY p.marque ASC, p.nom ASC'

    items = conn.execute(base_query, params).fetchall()
    conn.close()

    sort_urls  = {col: build_sort_url(sorts_str, col) for col in VALID_SORT_COLS}
    sort_icons = {col: get_sort_icon(sorts, col)      for col in VALID_SORT_COLS}
    return render_template('producten.html',
                           items=items, search_query=search,
                           sorts_str=sorts_str,
                           sort_urls=sort_urls, sort_icons=sort_icons)


# ─── PRODUCT TOEVOEGEN ────────────────────────────────────────────────────────
@app.route('/produit/nouveau', methods=['GET'])
@login_required
def nouveau_produit():
    conn = get_db_connection()
    types_element = conn.execute('SELECT * FROM types_element ORDER BY nom').fetchall()
    categories    = conn.execute('SELECT * FROM categories    ORDER BY nom').fetchall()
    conn.close()
    return render_template('product_new.html',
                           types_element=types_element, categories=categories)


@app.route('/add', methods=['POST'])
@login_required
def add():
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO produits (nom, marque, reference, code_barres, description,
                              stock_min_securite, statut, tva, no_fiche, tag,
                              categorie_id, type_element_id,
                              emplacement, bloc, rangee,
                              prix_tarif_1, prix_tarif_2, prix_tarif_3)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        request.form.get('nom', ''),
        request.form.get('marque', ''),
        request.form.get('reference', ''),
        request.form.get('code_barres', ''),
        request.form.get('description', ''),
        request.form.get('stock_min_securite') or 0,
        request.form.get('statut', 'Actif'),
        request.form.get('tva') or 20,
        request.form.get('no_fiche', ''),
        request.form.get('tag', ''),
        request.form.get('categorie_id') or None,
        request.form.get('type_element_id') or None,
        request.form.get('emplacement', ''),
        request.form.get('bloc', ''),
        request.form.get('rangee', ''),
        request.form.get('prix_tarif_1') or 20,
        request.form.get('prix_tarif_2') or 14.15,
        request.form.get('prix_tarif_3') or 75,
    ))
    new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('produit_detail', id=new_id, tab='informations'))


# ─── PRODUCTS IMPORTEREN VIA CSV ──────────────────────────────────────────────
def _detect_csv_delimiter(sample):
    """Detect whether CSV uses comma or semicolon as delimiter."""
    semicolons = sample.count(';')
    commas     = sample.count(',')
    return ';' if semicolons > commas else ','


@app.route('/import-produits', methods=['POST'])
@login_required
def import_produits():
    file = request.files.get('csv_file')
    if not file:
        return redirect(url_for('producten'))
    raw    = file.stream.read().decode('utf-8-sig')
    delim  = _detect_csv_delimiter(raw[:2000])
    stream = io.StringIO(raw)
    reader = csv.DictReader(stream, delimiter=delim)
    # Normalize headers: strip whitespace and lowercase for matching
    conn   = get_db_connection()
    count  = 0
    for row in reader:
        # Strip whitespace from all keys and values
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        # Skip completely empty rows
        nom = row.get('nom') or row.get('Nom') or row.get('NOM') or ''
        if not nom.strip():
            continue
        ref   = row.get('reference') or row.get('Reference') or row.get('REF') or row.get('ref') or ''
        marq  = row.get('marque') or row.get('Marque') or row.get('MARQUE') or ''
        cb    = row.get('code_barres') or row.get('code barres') or row.get('Code Barres') or ''
        desc  = row.get('description') or row.get('Description') or ''
        stmin = row.get('stock_min_securite') or row.get('stock_min') or row.get('Stock Min') or 0
        tag   = row.get('tag') or row.get('Tag') or ''
        cat_n = row.get('categorie') or row.get('Categorie') or row.get('Catégorie') or ''
        type_n = row.get('type_element') or row.get('Type Element') or row.get('type') or ''
        t1    = row.get('prix_tarif_1') or row.get('prix_vente') or row.get('Prix Vente') or 20
        t2    = row.get('prix_tarif_2') or 14.15
        t3    = row.get('prix_tarif_3') or 75
        tva   = row.get('tva') or row.get('TVA') or 20

        categorie_id = None
        type_elem_id = None
        if str(cat_n).strip():
            cat = conn.execute('SELECT id FROM categories WHERE nom=?', (cat_n.strip(),)).fetchone()
            if not cat:
                conn.execute('INSERT INTO categories (nom) VALUES (?)', (cat_n.strip(),))
                categorie_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            else:
                categorie_id = cat['id']
        if str(type_n).strip():
            te = conn.execute('SELECT id FROM types_element WHERE nom=?', (type_n.strip(),)).fetchone()
            if not te:
                conn.execute('INSERT INTO types_element (nom) VALUES (?)', (type_n.strip(),))
                type_elem_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            else:
                type_elem_id = te['id']
        try:
            stmin = int(float(stmin))
        except (ValueError, TypeError):
            stmin = 0
        try:
            t1 = float(t1)
        except (ValueError, TypeError):
            t1 = 20
        try:
            t2 = float(t2)
        except (ValueError, TypeError):
            t2 = 14.15
        try:
            t3 = float(t3)
        except (ValueError, TypeError):
            t3 = 75
        try:
            tva = float(tva)
        except (ValueError, TypeError):
            tva = 20
        conn.execute('''
            INSERT INTO produits (nom, reference, marque, code_barres, description,
                                  stock_min_securite, tag, categorie_id, type_element_id,
                                  statut, tva, prix_tarif_1, prix_tarif_2, prix_tarif_3)
            VALUES (?,?,?,?,?,?,?,?,?,'Actif',?,?,?,?)
        ''', (nom.strip(), ref, marq, cb, desc, stmin, tag, categorie_id, type_elem_id,
              tva, t1, t2, t3))
        count += 1
    conn.commit()
    conn.close()
    flash(f'{count} produit(s) importé(s) avec succès.', 'success')
    return redirect(url_for('producten'))


# ─── PRODUCT DETAIL ───────────────────────────────────────────────────────────
@app.route('/produit/<int:id>')
@login_required
def produit_detail(id):
    tab  = request.args.get('tab', 'informations')
    conn = get_db_connection()
    produit = conn.execute('''
        SELECT p.*, c.nom AS categorie_nom, te.nom AS type_element_nom,
               COALESCE((SELECT SUM(l.quantite) FROM lots l WHERE l.produit_id=p.id),0) AS stock_total
        FROM produits p
        LEFT JOIN categories    c  ON p.categorie_id    = c.id
        LEFT JOIN types_element te ON p.type_element_id = te.id
        WHERE p.id = ?
    ''', (id,)).fetchone()
    if not produit:
        conn.close()
        return redirect(url_for('producten'))

    types_element   = conn.execute('SELECT * FROM types_element ORDER BY nom').fetchall()
    categories      = conn.execute('SELECT * FROM categories    ORDER BY nom').fetchall()
    clients         = conn.execute('SELECT * FROM clients WHERE (est_fournisseur IS NULL OR est_fournisseur = 0) ORDER BY nom').fetchall()
    prix_vente_list = conn.execute('''
        SELECT pv.*, cl.nom AS client_nom
        FROM prix_vente pv JOIN clients cl ON pv.client_id = cl.id
        WHERE pv.produit_id = ? ORDER BY cl.nom
    ''', (id,)).fetchall()
    historique      = conn.execute(
        'SELECT * FROM historique_achats WHERE produit_id=? ORDER BY date_achat DESC', (id,)
    ).fetchall()
    lots            = conn.execute(
        'SELECT * FROM lots WHERE produit_id=? ORDER BY date_expiration ASC', (id,)
    ).fetchall()
    mouvements      = conn.execute(
        'SELECT * FROM mouvements WHERE produit_id=? ORDER BY date_mvt DESC LIMIT 100', (id,)
    ).fetchall()
    pieces_jointes  = conn.execute(
        'SELECT * FROM pieces_jointes WHERE produit_id=? ORDER BY date_ajout DESC', (id,)
    ).fetchall()
    stock_par_warehouse = conn.execute('''
        SELECT warehouse, SUM(quantite) AS total, COUNT(*) AS nb_lots
        FROM lots WHERE produit_id=? GROUP BY warehouse ORDER BY warehouse
    ''', (id,)).fetchall()
    conn.close()
    return render_template('product_detail.html',
                           produit=produit, tab=tab,
                           types_element=types_element, categories=categories,
                           clients=clients, prix_vente_list=prix_vente_list,
                           historique=historique, lots=lots,
                           mouvements=mouvements, pieces_jointes=pieces_jointes,
                           stock_par_warehouse=stock_par_warehouse)


# ─── PRODUCT BEWERKEN ────────────────────────────────────────────────────────
@app.route('/produit/<int:id>/edit', methods=['POST'])
@login_required
def edit_produit(id):
    conn = get_db_connection()
    conn.execute('''
        UPDATE produits SET
            nom=?, reference=?, code_barres=?, description=?,
            stock_min_securite=?,
            type_element_id=?, tag=?, categorie_id=?,
            marque=?, emplacement=?, bloc=?, rangee=?,
            statut=?, tva=?, no_fiche=?,
            prix_tarif_1=?, prix_tarif_2=?, prix_tarif_3=?
        WHERE id=?
    ''', (
        request.form.get('nom'),
        request.form.get('reference'),
        request.form.get('code_barres'),
        request.form.get('description'),
        request.form.get('stock_min_securite') or 0,
        request.form.get('type_element_id')    or None,
        request.form.get('tag'),
        request.form.get('categorie_id')       or None,
        request.form.get('marque'),
        request.form.get('emplacement'),
        request.form.get('bloc'),
        request.form.get('rangee'),
        request.form.get('statut', 'Actif'),
        request.form.get('tva') or 20,
        request.form.get('no_fiche'),
        request.form.get('prix_tarif_1') or 20,
        request.form.get('prix_tarif_2') or 14.15,
        request.form.get('prix_tarif_3') or 75,
        id,
    ))
    conn.commit()
    conn.close()
    if request.form.get('_redirect') == 'producten':
        return redirect(url_for('producten'))
    return redirect(url_for('produit_detail', id=id, tab='informations'))


# ─── PRIX DE VENTE ────────────────────────────────────────────────────────────
@app.route('/produit/<int:id>/add-prix-vente', methods=['POST'])
@login_required
def add_prix_vente(id):
    client_id = request.form.get('client_id')
    prix      = request.form.get('prix', 0)
    if client_id:
        conn     = get_db_connection()
        # Auto-determine price based on client tarification if no custom price given
        client = conn.execute('SELECT tarification FROM clients WHERE id=?', (client_id,)).fetchone()
        produit = conn.execute('SELECT prix_tarif_1, prix_tarif_2, prix_tarif_3 FROM produits WHERE id=?', (id,)).fetchone()
        if client and produit:
            tarif = client['tarification'] or 'T1'
            if tarif == 'T1':
                auto_prix = produit['prix_tarif_1'] or 20
            elif tarif == 'T2':
                auto_prix = produit['prix_tarif_2'] or 14.15
            else:
                auto_prix = produit['prix_tarif_3'] or 75
            # Use auto price if form submitted default T1 price or user didn't change it
            if float(prix) == float(produit['prix_tarif_1'] or 20):
                prix = auto_prix
        existing = conn.execute('SELECT id FROM prix_vente WHERE produit_id=? AND client_id=?',
                                (id, client_id)).fetchone()
        if existing:
            conn.execute('UPDATE prix_vente SET prix=? WHERE id=?', (prix, existing['id']))
        else:
            conn.execute('INSERT INTO prix_vente (produit_id, client_id, prix) VALUES (?,?,?)',
                         (id, client_id, prix))
        conn.commit()
        conn.close()
    return redirect(url_for('produit_detail', id=id, tab='informations'))


@app.route('/prix-vente/<int:pv_id>/update', methods=['POST'])
@login_required
def update_prix_vente(pv_id):
    conn    = get_db_connection()
    produit = conn.execute('SELECT produit_id FROM prix_vente WHERE id=?', (pv_id,)).fetchone()
    conn.execute('UPDATE prix_vente SET prix=? WHERE id=?', (request.form.get('prix', 0), pv_id))
    conn.commit()
    conn.close()
    if produit:
        return redirect(url_for('produit_detail', id=produit['produit_id'], tab='informations'))
    return redirect(url_for('producten'))


@app.route('/prix-vente/<int:pv_id>/delete', methods=['POST'])
@login_required
def delete_prix_vente(pv_id):
    conn    = get_db_connection()
    produit = conn.execute('SELECT produit_id FROM prix_vente WHERE id=?', (pv_id,)).fetchone()
    conn.execute('DELETE FROM prix_vente WHERE id=?', (pv_id,))
    conn.commit()
    conn.close()
    if produit:
        return redirect(url_for('produit_detail', id=produit['produit_id'], tab='informations'))
    return redirect(url_for('producten'))


# ─── LOTS ────────────────────────────────────────────────────────────────────
@app.route('/produit/<int:id>/add-lot', methods=['POST'])
@login_required
def add_lot(id):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO lots (produit_id, lot_numero, site, date_production, date_expiration,
                          warehouse, bloc, rangee, quantite)
        VALUES (?,?,?,?,?,?,?,?,?)
    ''', (id, request.form.get('lot_numero'), request.form.get('site'),
          request.form.get('date_production'), request.form.get('date_expiration'),
          request.form.get('warehouse'), request.form.get('bloc'), request.form.get('rangee'),
          request.form.get('quantite', 0) or 0))
    conn.commit()
    conn.close()
    return redirect(url_for('produit_detail', id=id, tab='lots'))


@app.route('/lot/<int:lot_id>/delete', methods=['POST'])
@login_required
def delete_lot(lot_id):
    conn = get_db_connection()
    lot  = conn.execute('SELECT produit_id FROM lots WHERE id=?', (lot_id,)).fetchone()
    conn.execute('DELETE FROM lots WHERE id=?', (lot_id,))
    conn.commit()
    conn.close()
    if lot:
        return redirect(url_for('produit_detail', id=lot['produit_id'], tab='lots'))
    return redirect(url_for('producten'))


@app.route('/produit/<int:id>/import-lots-csv', methods=['POST'])
@login_required
def import_lots_csv(id):
    file = request.files.get('csv_file')
    if not file:
        return redirect(url_for('produit_detail', id=id, tab='lots'))
    stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
    reader = csv.DictReader(stream)
    conn   = get_db_connection()
    for row in reader:
        conn.execute('''
            INSERT INTO lots (produit_id, lot_numero, site, date_production, date_expiration,
                              warehouse, bloc, rangee, quantite)
            VALUES (?,?,?,?,?,?,?,?,?)
        ''', (id, row.get('lot_numero', ''), row.get('site', ''),
              row.get('date_production', ''), row.get('date_expiration', ''),
              row.get('warehouse', ''), row.get('bloc', ''), row.get('rangee', ''),
              row.get('quantite', 0) or 0))
    conn.commit()
    conn.close()
    return redirect(url_for('produit_detail', id=id, tab='lots'))


# ─── TYPES / CATEGORIES / CLIENTS ─────────────────────────────────────────────
@app.route('/types-element/add', methods=['POST'])
@login_required
def add_type_element():
    nom        = request.form.get('nom', '').strip()
    produit_id = request.form.get('produit_id')
    if nom:
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO types_element (nom) VALUES (?)', (nom,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
    return redirect(url_for('produit_detail', id=produit_id, tab='informations'))


@app.route('/types-element/<int:te_id>/delete', methods=['POST'])
@admin_required
def delete_type_element(te_id):
    produit_id = request.form.get('produit_id')
    conn       = get_db_connection()
    conn.execute('DELETE FROM types_element WHERE id=?', (te_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('produit_detail', id=produit_id, tab='informations'))


@app.route('/categories/add', methods=['POST'])
@login_required
def add_category():
    nom        = request.form.get('nom', '').strip()
    produit_id = request.form.get('produit_id')
    if nom:
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO categories (nom) VALUES (?)', (nom,))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
    return redirect(url_for('produit_detail', id=produit_id, tab='informations'))


@app.route('/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def delete_category(cat_id):
    produit_id = request.form.get('produit_id')
    conn       = get_db_connection()
    conn.execute('DELETE FROM categories WHERE id=?', (cat_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('produit_detail', id=produit_id, tab='informations'))


def _f(val):
    """Return None for empty/whitespace strings, stripped value otherwise."""
    v = (val or '').strip()
    return v if v else None


def _generate_client_code(conn):
    """Generate next client code like LC0001, LC0002, ..."""
    row = conn.execute("SELECT code_client FROM clients WHERE code_client IS NOT NULL ORDER BY code_client DESC LIMIT 1").fetchone()
    if row and row['code_client']:
        try:
            num = int(row['code_client'].replace('LC', '')) + 1
        except ValueError:
            num = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()['n'] + 1
    else:
        num = 1
    return f"LC{num:04d}"


# ─── CLIENTS : LIST ─────────────────────────────────────────────────────────
@app.route('/clients')
@login_required
def clients_list():
    conn   = get_db_connection()
    search = request.args.get('search', '').strip()
    query  = 'SELECT * FROM clients WHERE (est_fournisseur IS NULL OR est_fournisseur = 0)'
    params = []
    if search:
        query += ' AND (nom LIKE ? OR code_client LIKE ? OR email LIKE ? OR telephone LIKE ? OR ville LIKE ? OR ice LIKE ?)'
        params = [f'%{search}%'] * 6
    query += ' ORDER BY nom'
    clients = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('clients.html', clients=clients, search_query=search)


# ─── CLIENTS : ADD (page) ───────────────────────────────────────────────────
@app.route('/clients/new', methods=['GET', 'POST'])
@login_required
def new_client():
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        if nom:
            conn = get_db_connection()
            code = _generate_client_code(conn)
            g = lambda k, d=None: _f(request.form.get(k, '')) or d
            conn.execute('''
                INSERT INTO clients
                    (nom, code_client, type, adresse, ville, telephone, email,
                     ice, identifiant_fiscal, code_postal, region, pays, gsm, contact,
                     tarification, categorie_client, latitude, longitude,
                     adresse_facturation, ville_facturation, region_facturation,
                     code_postal_facturation, pays_facturation,
                     adresse_livraison, ville_livraison, region_livraison,
                     code_postal_livraison, pays_livraison, actif)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            ''', (
                nom, code,
                g('type', 'Hôpital'), g('adresse'), g('ville'),
                g('telephone'), g('email'), g('ice'), g('identifiant_fiscal'),
                g('code_postal'), g('region'), g('pays', 'Maroc'),
                g('gsm'), g('contact'), g('tarification', 'T1'),
                g('categorie_client'), g('latitude'), g('longitude'),
                g('adresse_facturation'), g('ville_facturation'), g('region_facturation'),
                g('code_postal_facturation'), g('pays_facturation'),
                g('adresse_livraison'), g('ville_livraison'), g('region_livraison'),
                g('code_postal_livraison'), g('pays_livraison'),
            ))
            conn.commit()
            new_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
            conn.close()
            return redirect(url_for('client_detail', id=new_id))
        return redirect(url_for('new_client'))
    return render_template('client_detail.html', client=None, is_new=True)


# ─── CLIENTS : DETAIL / EDIT ────────────────────────────────────────────────
@app.route('/clients/<int:id>')
@login_required
def client_detail(id):
    conn   = get_db_connection()
    tab    = request.args.get('tab', 'general')
    client = conn.execute('SELECT * FROM clients WHERE id=?', (id,)).fetchone()
    if not client:
        conn.close()
        return redirect(url_for('clients_list'))
    # Get invoices for this client
    factures = conn.execute('''
        SELECT * FROM factures WHERE client_id=? ORDER BY date_facture DESC
    ''', (id,)).fetchall()
    # Get pricing assignments
    prix_vente = conn.execute('''
        SELECT pv.*, p.nom AS produit_nom, p.reference AS produit_ref
        FROM prix_vente pv JOIN produits p ON pv.produit_id = p.id
        WHERE pv.client_id=? ORDER BY p.nom
    ''', (id,)).fetchall()
    conn.close()
    return render_template('client_detail.html', client=client, is_new=False,
                           tab=tab, factures=factures, prix_vente=prix_vente)


@app.route('/clients/<int:id>/edit', methods=['POST'])
@login_required
def edit_client(id):
    conn = get_db_connection()
    g = lambda k, d=None: _f(request.form.get(k, '')) or d
    conn.execute('''
        UPDATE clients SET
            nom=?, type=?, adresse=?, ville=?, telephone=?, email=?,
            ice=?, identifiant_fiscal=?, code_postal=?, region=?, pays=?,
            gsm=?, contact=?, tarification=?, categorie_client=?,
            latitude=?, longitude=?,
            adresse_facturation=?, ville_facturation=?, region_facturation=?,
            code_postal_facturation=?, pays_facturation=?,
            adresse_livraison=?, ville_livraison=?, region_livraison=?,
            code_postal_livraison=?, pays_livraison=?
        WHERE id=?
    ''', (
        request.form.get('nom', '').strip(),
        g('type', 'Hôpital'), g('adresse'), g('ville'),
        g('telephone'), g('email'), g('ice'), g('identifiant_fiscal'),
        g('code_postal'), g('region'), g('pays', 'Maroc'),
        g('gsm'), g('contact'), g('tarification', 'T1'),
        g('categorie_client'), g('latitude'), g('longitude'),
        g('adresse_facturation'), g('ville_facturation'), g('region_facturation'),
        g('code_postal_facturation'), g('pays_facturation'),
        g('adresse_livraison'), g('ville_livraison'), g('region_livraison'),
        request.form.get('code_postal_livraison', ''),
        request.form.get('pays_livraison', ''),
        id,
    ))
    # Auto-update all prix_vente when tarification changes
    new_tarif = g('tarification', 'T1')
    tarif_col = {'T1': 'prix_tarif_1', 'T2': 'prix_tarif_2', 'T3': 'prix_tarif_3'}
    col = tarif_col.get(new_tarif, 'prix_tarif_1')
    conn.execute(f'''
        UPDATE prix_vente SET prix = (
            SELECT COALESCE(p.{col}, p.prix_tarif_1, 20)
            FROM produits p WHERE p.id = prix_vente.produit_id
        )
        WHERE client_id = ?
    ''', (id,))

    conn.commit()
    conn.close()
    if request.form.get('redirect') == 'list':
        return redirect(url_for('clients_list'))
    return redirect(url_for('client_detail', id=id, tab=request.form.get('tab', 'general')))


@app.route('/clients/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_client(id):
    conn = get_db_connection()
    client = conn.execute('SELECT actif FROM clients WHERE id=?', (id,)).fetchone()
    if client:
        conn.execute('UPDATE clients SET actif=? WHERE id=?', (0 if client['actif'] else 1, id))
        conn.commit()
    conn.close()
    return redirect(url_for('clients_list'))


@app.route('/clients/<int:id>/delete', methods=['POST'])
@admin_required
def delete_client(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM prix_vente WHERE client_id=?', (id,))
    conn.execute('DELETE FROM clients WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('clients_list'))


@app.route('/clients/import', methods=['POST'])
@login_required
def import_clients():
    f = request.files.get('csv_file')
    if not f:
        return redirect(url_for('clients_list'))
    stream = io.StringIO(f.read().decode('utf-8-sig'))
    reader = csv.reader(stream, delimiter=',')
    conn   = get_db_connection()
    for row in reader:
        if not row or not row[0].strip():
            continue
        nom = row[0].strip()
        code = _generate_client_code(conn)
        conn.execute(
            'INSERT INTO clients (nom, code_client, telephone, email, ville, actif) VALUES (?,?,?,?,?,1)',
            (nom, code, row[1].strip() if len(row) > 1 else '',
             row[2].strip() if len(row) > 2 else '',
             row[3].strip() if len(row) > 3 else '')
        )
        conn.commit()
    conn.close()
    return redirect(url_for('clients_list'))


# ─── CLIENTS : ADD (quick, from product page) ───────────────────────────────
@app.route('/clients/add', methods=['POST'])
@login_required
def add_client():
    nom        = request.form.get('nom', '').strip()
    produit_id = request.form.get('produit_id')
    if nom:
        conn = get_db_connection()
        code = _generate_client_code(conn)
        conn.execute(
            'INSERT INTO clients (nom, code_client, type, adresse, ville, telephone, email, tarification, actif) VALUES (?,?,?,?,?,?,?,?,1)',
            (nom, code, request.form.get('type', 'Hôpital'),
             request.form.get('adresse', ''), request.form.get('ville', ''),
             request.form.get('telephone', ''), request.form.get('email', ''),
             request.form.get('tarification', 'T1'))
        )
        conn.commit()
        conn.close()
    return redirect(url_for('produit_detail', id=produit_id, tab='informations') if produit_id
                    else url_for('clients_list'))


def _generate_fournisseur_code(conn):
    row = conn.execute("SELECT code_client FROM clients WHERE est_fournisseur=1 AND code_client IS NOT NULL ORDER BY code_client DESC LIMIT 1").fetchone()
    if row and row['code_client']:
        try:
            num = int(row['code_client'].replace('LF', '')) + 1
        except ValueError:
            num = conn.execute("SELECT COUNT(*) AS n FROM clients WHERE est_fournisseur=1").fetchone()['n'] + 1
    else:
        num = 1
    return f"LF{num:04d}"


# ─── FOURNISSEURS : LIST ────────────────────────────────────────────────────
@app.route('/fournisseurs')
@login_required
def fournisseurs_list():
    conn   = get_db_connection()
    search = request.args.get('search', '').strip()
    query  = 'SELECT * FROM clients WHERE est_fournisseur = 1'
    params = []
    if search:
        query += ' AND (nom LIKE ? OR code_client LIKE ? OR email LIKE ? OR telephone LIKE ? OR ville LIKE ?)'
        params = [f'%{search}%'] * 5
    query += ' ORDER BY nom'
    fournisseurs = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('fournisseurs.html', fournisseurs=fournisseurs, search_query=search)


# ─── FOURNISSEURS : ADD ─────────────────────────────────────────────────────
@app.route('/fournisseurs/new', methods=['GET', 'POST'])
@login_required
def new_fournisseur():
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        if nom:
            conn = get_db_connection()
            code = _generate_fournisseur_code(conn)
            g = lambda k, d=None: _f(request.form.get(k, '')) or d
            conn.execute('''
                INSERT INTO clients
                    (nom, code_client, type, adresse, ville, telephone, email,
                     ice, identifiant_fiscal, code_postal, region, pays, gsm, contact,
                     categorie_client, actif, est_fournisseur)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)
            ''', (
                nom, code, g('type'), g('adresse'), g('ville'),
                g('telephone'), g('email'), g('ice'), g('identifiant_fiscal'),
                g('code_postal'), g('region'), g('pays', 'Maroc'),
                g('gsm'), g('contact'), g('categorie_client'),
            ))
            conn.commit()
            new_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
            conn.close()
            return redirect(url_for('fournisseur_detail', id=new_id))
        return redirect(url_for('new_fournisseur'))
    return render_template('fournisseur_detail.html', fournisseur=None, is_new=True)


# ─── FOURNISSEURS : DETAIL ──────────────────────────────────────────────────
@app.route('/fournisseurs/<int:id>')
@login_required
def fournisseur_detail(id):
    conn = get_db_connection()
    fournisseur = conn.execute('SELECT * FROM clients WHERE id=? AND est_fournisseur=1', (id,)).fetchone()
    if not fournisseur:
        conn.close()
        return redirect(url_for('fournisseurs_list'))
    conn.close()
    return render_template('fournisseur_detail.html', fournisseur=fournisseur, is_new=False)


@app.route('/fournisseurs/<int:id>/edit', methods=['POST'])
@login_required
def edit_fournisseur(id):
    conn = get_db_connection()
    g = lambda k, d=None: _f(request.form.get(k, '')) or d
    conn.execute('''
        UPDATE clients SET
            nom=?, type=?, adresse=?, ville=?, telephone=?, email=?,
            ice=?, identifiant_fiscal=?, code_postal=?, region=?, pays=?,
            gsm=?, contact=?, categorie_client=?
        WHERE id=?
    ''', (
        request.form.get('nom', '').strip(),
        g('type'), g('adresse'), g('ville'),
        g('telephone'), g('email'), g('ice'), g('identifiant_fiscal'),
        g('code_postal'), g('region'), g('pays', 'Maroc'),
        g('gsm'), g('contact'), g('categorie_client'),
        id,
    ))
    conn.commit()
    conn.close()
    if request.form.get('redirect') == 'list':
        return redirect(url_for('fournisseurs_list'))
    return redirect(url_for('fournisseur_detail', id=id))


@app.route('/fournisseurs/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_fournisseur(id):
    conn = get_db_connection()
    client = conn.execute('SELECT actif FROM clients WHERE id=?', (id,)).fetchone()
    if client:
        conn.execute('UPDATE clients SET actif=? WHERE id=?', (0 if client['actif'] else 1, id))
        conn.commit()
    conn.close()
    return redirect(url_for('fournisseurs_list'))


@app.route('/fournisseurs/<int:id>/delete', methods=['POST'])
@admin_required
def delete_fournisseur(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM clients WHERE id=? AND est_fournisseur=1', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('fournisseurs_list'))


# ─── DELETE PRODUIT ───────────────────────────────────────────────────────────
@app.route('/delete/<int:id>')
@admin_required
def delete(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM produits WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('producten'))


# ─── VENTES : LISTE ───────────────────────────────────────────────────────────
@app.route('/ventes')
@app.route('/ventes/<type_doc>')
@login_required
def ventes(type_doc=None):
    conn      = get_db_connection()
    search    = request.args.get('search', '').strip()
    statut    = request.args.get('statut', '')
    type_document = type_doc or request.args.get('type', 'Facture')
    if type_document not in DOC_PREFIXES:
        type_document = 'Facture'

    query  = '''
        SELECT f.*, cl.nom AS client_nom
        FROM factures f LEFT JOIN clients cl ON f.client_id = cl.id
    '''
    params, wheres = [], []
    # Filter by document type
    wheres.append("(f.type_document = ? OR (f.type_document IS NULL AND ? = 'Facture'))")
    params += [type_document, type_document]
    if search:
        wheres.append('(f.numero LIKE ? OR cl.nom LIKE ? OR f.objet LIKE ?)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    if statut:
        wheres.append('f.statut = ?')
        params.append(statut)
    if wheres:
        query += ' WHERE ' + ' AND '.join(wheres)
    query   += ' ORDER BY f.date_facture DESC'
    factures = conn.execute(query, params).fetchall()

    # Stats for this document type only
    stats_query = "SELECT statut, COUNT(*) AS nb, SUM(montant_ttc) AS total FROM factures WHERE (type_document = ? OR (type_document IS NULL AND ? = 'Facture')) GROUP BY statut"
    stats    = conn.execute(stats_query, (type_document, type_document)).fetchall()
    total_all = sum(s['nb'] for s in stats)
    total_ttc = sum(s['total'] or 0 for s in stats)
    conn.close()
    stats_dict = {s['statut']: {'nb': s['nb'], 'total': s['total']} for s in stats}
    return render_template('ventes.html',
                           factures=factures, stats=stats_dict,
                           total_all=total_all, total_ttc=total_ttc,
                           search_query=search, statut_filtre=statut,
                           type_document=type_document)


# ─── VENTES : NOUVELLE FACTURE / DOCUMENT ─────────────────────────────────────
@app.route('/ventes/new', methods=['GET', 'POST'])
@app.route('/ventes/new/<type_doc>', methods=['GET', 'POST'])
@login_required
def new_facture(type_doc=None):
    conn  = get_db_connection()
    today = datetime.date.today().isoformat()
    type_document = type_doc or request.form.get('type_document', 'Facture')
    if type_document not in DOC_PREFIXES:
        type_document = 'Facture'
    if request.method == 'POST':
        numero    = generate_numero_document(conn, type_document)
        client_id = request.form.get('client_id') or None
        conn.execute('''
            INSERT INTO factures
                (numero, client_id, date_facture, date_echeance, devise,
                 emplacement_stock, objet, statut, type_document,
                 client_ref, date_peremption_souhaitee, date_livraison_souhaitee,
                 montant_ht, remise_globale, montant_tva, ajustement, montant_ttc)
            VALUES (?,?,?,?,?,?,?,'En instance',?,?,?,?,0,0,0,0,0)
        ''', (numero, client_id, today,
              request.form.get('date_echeance') or today,
              request.form.get('devise', 'MAD'),
              request.form.get('emplacement_stock', ''),
              request.form.get('objet', ''),
              type_document,
              _f(request.form.get('client_ref', '')),
              _f(request.form.get('date_peremption_souhaitee', '')),
              _f(request.form.get('date_livraison_souhaitee', '')),
              ))
        conn.commit()
        fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return redirect(url_for('edit_facture', id=fid))
    clients = conn.execute('SELECT * FROM clients WHERE (est_fournisseur IS NULL OR est_fournisseur = 0) ORDER BY nom').fetchall()
    conn.close()
    return render_template('facture_new.html', clients=clients, today=today, type_document=type_document)


# ─── VENTES : ÉDITER FACTURE ──────────────────────────────────────────────────
@app.route('/facture/<int:id>')
@login_required
def edit_facture(id):
    conn    = get_db_connection()
    facture = conn.execute('''
        SELECT f.*, cl.nom AS client_nom, cl.type AS client_type,
               cl.adresse AS client_adresse, cl.ville AS client_ville,
               cl.telephone AS client_telephone, cl.email AS client_email
        FROM factures f LEFT JOIN clients cl ON f.client_id = cl.id
        WHERE f.id = ?
    ''', (id,)).fetchone()
    if not facture:
        conn.close()
        return redirect(url_for('ventes'))
    lignes   = conn.execute('''
        SELECT fl.*, p.nom AS produit_nom, p.reference AS produit_ref, l.lot_numero
        FROM facture_lignes fl
        LEFT JOIN produits p ON fl.produit_id = p.id
        LEFT JOIN lots     l ON fl.lot_id     = l.id
        WHERE fl.facture_id = ? ORDER BY fl.id
    ''', (id,)).fetchall()
    clients  = conn.execute('SELECT * FROM clients WHERE (est_fournisseur IS NULL OR est_fournisseur = 0) ORDER BY nom').fetchall()
    produits = conn.execute('''
        SELECT p.*,
               COALESCE((SELECT SUM(l.quantite) FROM lots l WHERE l.produit_id=p.id),0) AS stock_total
        FROM produits p ORDER BY p.nom
    ''').fetchall()
    conn.close()
    return render_template('facture_edit.html',
                           facture=facture, lignes=lignes,
                           clients=clients, produits=produits)


# ─── VENTES : ENTÊTE FACTURE ──────────────────────────────────────────────────
@app.route('/facture/<int:id>/update-header', methods=['POST'])
@login_required
def update_facture_header(id):
    conn = get_db_connection()
    # date_facture wordt NIET gewijzigd (altijd de originele aanmaakdatum)
    conn.execute('''
        UPDATE factures SET
            client_id=?, date_echeance=?, devise=?,
            emplacement_stock=?, contact_commercial=?, modele=?,
            objet=?, remarques=?, conditions=?,
            remise_globale=?, ajustement=?
        WHERE id=?
    ''', (
        request.form.get('client_id') or None,
        request.form.get('date_echeance'),
        request.form.get('devise', 'MAD'),
        request.form.get('emplacement_stock', ''),
        request.form.get('contact_commercial', ''),
        request.form.get('modele', ''),
        request.form.get('objet', ''),
        request.form.get('remarques', ''),
        request.form.get('conditions', ''),
        request.form.get('remise_globale', 0) or 0,
        request.form.get('ajustement', 0) or 0,
        id,
    ))
    recalculate_facture(conn, id)
    conn.commit()
    conn.close()
    return redirect(url_for('edit_facture', id=id))


# ─── VENTES : STATUT ──────────────────────────────────────────────────────────
@app.route('/facture/<int:id>/statut', methods=['POST'])
@login_required
def update_facture_statut(id):
    conn = get_db_connection()
    conn.execute('UPDATE factures SET statut=? WHERE id=?',
                 (request.form.get('statut', 'En instance'), id))
    conn.commit()
    conn.close()
    return redirect(url_for('edit_facture', id=id))


# ─── VENTES : AJOUTER LIGNE ───────────────────────────────────────────────────
@app.route('/facture/<int:id>/add-ligne', methods=['POST'])
@login_required
def add_facture_ligne(id):
    produit_id  = request.form.get('produit_id') or None
    lot_id      = request.form.get('lot_id')     or None
    quantite    = float(request.form.get('quantite',      1)  or 1)
    prix        = float(request.form.get('prix_unitaire', 0)  or 0)
    tva         = float(request.form.get('tva',           20) or 20)
    remise      = float(request.form.get('remise',        0)  or 0)
    designation = request.form.get('designation', '').strip()
    reference   = request.form.get('reference',  '').strip()

    if not designation and produit_id:
        conn_tmp = get_db_connection()
        p = conn_tmp.execute('SELECT nom, reference FROM produits WHERE id=?', (produit_id,)).fetchone()
        if p:
            designation = p['nom']
            if not reference:
                reference = p['reference'] or ''
        if lot_id:
            l = conn_tmp.execute('SELECT lot_numero FROM lots WHERE id=?', (lot_id,)).fetchone()
            if l and l['lot_numero']:
                designation += f" LOT:{l['lot_numero']}"
        conn_tmp.close()

    montant_ht = round(quantite * prix * (1 - remise / 100), 4)
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO facture_lignes
            (facture_id, produit_id, lot_id, reference, designation,
             quantite, prix_unitaire, tva, remise, montant_ht)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    ''', (id, produit_id, lot_id, reference, designation,
          quantite, prix, tva, remise, montant_ht))
    recalculate_facture(conn, id)
    conn.commit()
    conn.close()
    return redirect(url_for('edit_facture', id=id))


# ─── VENTES : SUPPRIMER LIGNE ─────────────────────────────────────────────────
@app.route('/facture/<int:fid>/ligne/<int:lid>/delete', methods=['POST'])
@login_required
def delete_facture_ligne(fid, lid):
    conn = get_db_connection()
    conn.execute('DELETE FROM facture_lignes WHERE id=? AND facture_id=?', (lid, fid))
    recalculate_facture(conn, fid)
    conn.commit()
    conn.close()
    return redirect(url_for('edit_facture', id=fid))


# ─── API: LOTS PER PRODUIT ────────────────────────────────────────────────────
@app.route('/api/produit/<int:produit_id>/lots')
@login_required
def api_lots_produit(produit_id):
    conn    = get_db_connection()
    lots    = conn.execute(
        'SELECT id, lot_numero, quantite, warehouse FROM lots WHERE produit_id=? AND quantite>0',
        (produit_id,)
    ).fetchall()
    produit = conn.execute(
        'SELECT tva, prix_dernier_achat, prix_tarif_1, prix_tarif_2, prix_tarif_3 FROM produits WHERE id=?',
        (produit_id,)
    ).fetchone()
    conn.close()
    return jsonify({
        'lots':       [{'id': l['id'], 'lot_numero': l['lot_numero'],
                        'quantite': l['quantite'], 'warehouse': l['warehouse']} for l in lots],
        'prix':       produit['prix_dernier_achat'] if produit else 0,
        'prix_tarif_1': produit['prix_tarif_1'] if produit else 20,
        'prix_tarif_2': produit['prix_tarif_2'] if produit else 14.15,
        'prix_tarif_3': produit['prix_tarif_3'] if produit else 75,
        'tva':        produit['tva'] if produit else 20,
    })


# ─── VENTES : SUPPRIMER FACTURE ───────────────────────────────────────────────
@app.route('/facture/<int:id>/delete', methods=['POST'])
@admin_required
def delete_facture(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM factures WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('ventes'))


# ─── VENTES : PRINT / PDF ────────────────────────────────────────────────────
@app.route('/facture/<int:id>/print')
@login_required
def print_facture(id):
    conn    = get_db_connection()
    facture = conn.execute('''
        SELECT f.*, cl.nom AS client_nom, cl.type AS client_type,
               cl.adresse AS client_adresse, cl.ville AS client_ville,
               cl.telephone AS client_telephone, cl.email AS client_email
        FROM factures f LEFT JOIN clients cl ON f.client_id = cl.id
        WHERE f.id=?
    ''', (id,)).fetchone()
    if not facture:
        conn.close()
        return redirect(url_for('ventes'))
    lignes = conn.execute(
        'SELECT * FROM facture_lignes WHERE facture_id=? ORDER BY id', (id,)
    ).fetchall()
    conn.close()
    return render_template('facture_print.html', facture=facture, lignes=lignes)


# ─── ADMIN: GEBRUIKERSBEHEER ──────────────────────────────────────────────────
@app.route('/admin/users')
@admin_required
def admin_users():
    conn  = get_db_connection()
    users = conn.execute('SELECT id, username, nom, role, actif FROM users ORDER BY nom').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/add', methods=['POST'])
@admin_required
def admin_add_user():
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (username, password_hash, nom, role) VALUES (?,?,?,?)',
            (request.form['username'],
             generate_password_hash(request.form['password']),
             request.form.get('nom', ''),
             request.form.get('role', 'employee'))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        flash("Ce nom d'utilisateur existe déjà.", 'danger')
    conn.close()
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    conn = get_db_connection()
    conn.execute('UPDATE users SET actif = 1 - actif WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(uid):
    new_pw = request.form.get('password', '')
    if new_pw:
        conn = get_db_connection()
        conn.execute('UPDATE users SET password_hash=? WHERE id=?',
                     (generate_password_hash(new_pw), uid))
        conn.commit()
        conn.close()
    return redirect(url_for('admin_users'))


if __name__ == '__main__':
    app.run(debug=True, port=5001)
