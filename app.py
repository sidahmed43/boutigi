from flask import Flask, render_template, request, session, redirect, url_for, flash,jsonify  
from flask_babel import Babel, _
from datetime import datetime,timedelta
import mysql.connector
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'votre_clé_secrète_super_compliquée'
app.config.update({
    'BABEL_DEFAULT_LOCALE': 'fr',
    'BABEL_SUPPORTED_LOCALES': ['fr', 'en', 'ar'],
    'BABEL_TRANSLATION_DIRECTORIES': 'translations'
})

babel = Babel(app)

# Configuration MySQL directe
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",      # Remplacez par votre host MySQL
        user="root",           # Remplacez par votre utilisateur MySQL
        password="",           # Remplacez par votre mot de passe
        database="stocks",     # Vérifiez que la base existe
        port=3306              # Port par défaut MySQL
    )

@babel.localeselector
def get_locale():
    print("Session content:", dict(session))
    if 'lang' in session:
        return session['lang']
    return request.accept_languages.best_match(app.config['BABEL_SUPPORTED_LOCALES'])

@app.context_processor
def inject_conf_var():
    return {
        'current_locale': get_locale(),
        'now': datetime.utcnow()
    }

@app.route('/change_lang/<lang>')
def change_lang(lang):
    if lang in app.config['BABEL_SUPPORTED_LOCALES']:
        session.clear()
        session['lang'] = lang
        session.modified = True
    return redirect(url_for('dashboard'))
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d/%m/%Y %H:%M'):
    try:
        if isinstance(value, str):
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return value.strftime(format)
    except:
        return "N/A"
    
@app.route('/')
def dashboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Date actuelle
        current_date = datetime.now()

        # Statistiques principales
        cursor.execute("SELECT COUNT(*) AS total FROM produits")
        total_produits = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) AS total FROM clients")
        total_clients = cursor.fetchone()['total']

        cursor.execute("""
            SELECT SUM(total) AS total 
            FROM ventes 
            WHERE DATE(date) = CURDATE()
        """)
        ventes_jour = cursor.fetchone()['total'] or 0

        # Produits à faible stock
        cursor.execute("""
            SELECT * FROM produits 
            WHERE quantite < seuil_alerte
            ORDER BY quantite ASC 
            LIMIT 5
        """)
        low_stock_products = cursor.fetchall()

        # Données pour le graphique (7 derniers jours)
        start_date = datetime.now() - timedelta(days=7)
        cursor.execute("""
            SELECT DATE(date) as sale_date, SUM(total) as total 
            FROM ventes 
            WHERE date >= %s
            GROUP BY DATE(date)
            ORDER BY DATE(date) ASC
        """, (start_date,))
        sales_data = cursor.fetchall()

        # Préparation des données pour le graphique
        sales_dates = []
        sales_amounts = []
        for i in range(7):
            date = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            sales_dates.append(date)
            amount = next((item['total'] for item in sales_data if item['sale_date'].strftime('%Y-%m-%d') == date), 0)
            sales_amounts.append(float(amount))

        # Activité récente
        cursor.execute("""
            SELECT v.*, c.nom as client_nom 
            FROM ventes v
            LEFT JOIN clients c ON v.client_id = c.id
            ORDER BY v.date DESC 
            LIMIT 10
        """)
        activites = cursor.fetchall()

        return render_template('dashboard.html',
                             current_date=current_date,
                             total_produits=total_produits,
                             total_clients=total_clients,
                             ventes_jour=ventes_jour,
                             low_stock_products=low_stock_products,
                             sales_dates=sales_dates,
                             sales_amounts=sales_amounts,
                             activites=activites)
    
    except Exception as e:
        flash(_('Erreur de chargement du tableau de bord: ') + str(e), 'error')
        return render_template('dashboard.html',
                               ventes_jour=ventes_jour,
                             current_date=datetime.now())  # <-- Même en cas d'erreur
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route('/api/sales-data')
def sales_data():
    period = request.args.get('period', 'week')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if period == 'week':
            start_date = datetime.now() - timedelta(days=7)
            group_by = "DAY(date)"
        elif period == 'month':
            start_date = datetime.now() - timedelta(days=30)
            group_by = "WEEK(date)"
        else: # year
            start_date = datetime.now() - timedelta(days=365)
            group_by = "MONTH(date)"

        cursor.execute(f"""
            SELECT {group_by} as period, SUM(total) as total 
            FROM ventes 
            WHERE date >= %s
            GROUP BY {group_by}
            ORDER BY date ASC
        """, (start_date,))
        
        data = cursor.fetchall()
        dates = [item['period'] for item in data]
        amounts = [float(item['total']) for item in data]

        return jsonify({'dates': dates, 'amounts': amounts})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route('/produits')
def produits():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT produits.*, categories.nom as categorie_nom 
            FROM produits 
            LEFT JOIN categories ON produits.categorie_id = categories.id
        """)
        produits = cursor.fetchall()
        
        return render_template('produits.html', produits=produits)
    
    except Exception as e:
        flash(_('Erreur lors du chargement des produits: ') + str(e), 'error')
        return render_template('produits.html', produits=[])
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()


# Route pour modifier un produit
@app.route('/editer_produit/<int:id>', methods=['GET', 'POST'])
def editer_produit(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            nom = request.form['nom']
            prix_achat = float(request.form['prix_achat'])
            prix_vente = float(request.form['prix'])  # Garder le nom original 'prix'
            quantite = int(request.form['quantite'])
            categorie_id = request.form.get('categorie_id') or None

            # Validation des prix
            if prix_vente < prix_achat:
                flash(_('Le prix de vente doit être supérieur au prix d\'achat'), 'error')
                return redirect(url_for('editer_produit', id=id))
            
            if quantite < 0:
                flash(_('La quantité ne peut pas être négative'), 'error')
                return redirect(url_for('editer_produit', id=id))

            cursor.execute(
                """UPDATE produits SET 
                    nom = %s,
                    prix_achat = %s,
                    prix = %s, 
                    quantite = %s, 
                    categorie_id = %s 
                WHERE id = %s""",
                (nom, prix_achat, prix_vente, quantite, categorie_id, id))
            conn.commit()
            flash(_('Produit modifié avec succès!'), 'success')
            return redirect(url_for('produits'))
        
        except ValueError:
            flash(_('Valeurs numériques invalides'), 'error')
        except Exception as e:
            flash(_('Erreur de modification: ') + str(e), 'error')
            conn.rollback()
    
    # Récupération des données existantes
    cursor.execute("SELECT * FROM produits WHERE id = %s", (id,))
    produit = cursor.fetchone()
    
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('editer_produit.html', 
                         produit=produit, 
                         categories=categories)

# Route pour supprimer un produit
@app.route('/supprimer_produit/<int:id>', methods=['POST'])
def supprimer_produit(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produits WHERE id = %s", (id,))
        conn.commit()
        flash(_('Produit supprimé avec succès!'), 'success')
    except Exception as e:
        flash(_('Erreur de suppression: ') + str(e), 'error')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('produits'))

@app.route('/clients')
def clients():
    return render_template('clients.html')

# Route pour afficher les ventes
@app.route('/ventes')
def ventes():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT v.*, c.nom as client_nom 
            FROM ventes v
            LEFT JOIN clients c ON v.client_id = c.id
        """)
        ventes = cursor.fetchall()
        
        return render_template('ventes.html', ventes=ventes)
    
    except Exception as e:
        flash(_('Erreur de chargement des ventes: ') + str(e), 'error')
        return render_template('ventes.html', ventes=[])
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route('/vente/<int:id>')
def details_vente(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Récupération des infos de la vente
        cursor.execute("""
            SELECT v.*, c.nom as client_nom 
            FROM ventes v
            LEFT JOIN clients c ON v.client_id = c.id
            WHERE v.id = %s
        """, (id,))
        vente = cursor.fetchone()
        
        # Récupération des détails avec stock actuel
        cursor.execute("""
            SELECT dv.*, p.nom as produit_nom, p.quantite as stock_actuel 
            FROM details_vente dv
            JOIN produits p ON dv.produit_id = p.id
            WHERE dv.vente_id = %s
        """, (id,))
        details = cursor.fetchall()
        
        return render_template('details_vente.html', 
                             vente=vente, 
                             details=details)
    
    except Exception as e:
        flash(_('Erreur de chargement des détails: ') + str(e), 'error')
        return redirect(url_for('ventes'))
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# Route pour ajouter une vente
@app.route('/ajouter_vente', methods=['GET', 'POST'])
def ajouter_vente():
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id') or None
            total = float(request.form['total'])
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Insertion de la vente
            cursor.execute(
                "INSERT INTO ventes (date, client_id, total) VALUES (NOW(), %s, %s)",
                (client_id, total)
            )
            vente_id = cursor.lastrowid
            
            # Traitement des produits
            produits = zip(
                request.form.getlist('produit_id[]'),
                request.form.getlist('quantite[]'),
                request.form.getlist('prix_unitaire[]')
            )
            
            for produit_id, quantite_str, prix_str in produits:
                quantite = int(quantite_str)
                prix = float(prix_str)

                # Vérification du stock
                cursor.execute(
                    "SELECT quantite FROM produits WHERE id = %s FOR UPDATE",
                    (produit_id,)
                )
                stock_actuel = cursor.fetchone()[0]
                
                if stock_actuel < quantite:
                    conn.rollback()
                    flash(_('Stock insuffisant pour le produit ID {}').format(produit_id), 'error')
                    return redirect(url_for('ajouter_vente'))

                # Mise à jour du stock
                cursor.execute(
                    "UPDATE produits SET quantite = quantite - %s WHERE id = %s",
                    (quantite, produit_id)
                )
                
                # Insertion des détails
                cursor.execute(
                    """INSERT INTO details_vente 
                    (vente_id, produit_id, quantite, prix_unitaire)
                    VALUES (%s, %s, %s, %s)""",
                    (vente_id, produit_id, quantite, prix)
                )

            conn.commit()
            flash(_('Vente enregistrée avec succès!'), 'success')
            return redirect(url_for('ventes'))
            
        except Exception as e:
            conn.rollback()
            flash(_('Erreur lors de l\'enregistrement: ') + str(e), 'error')
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    # Récupération des données nécessaires
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM clients")
    clients = cursor.fetchall()
    
    cursor.execute("SELECT * FROM produits WHERE quantite > 0")
    produits = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('ajouter_vente.html', 
                         clients=clients, 
                         produits=produits)
@app.route('/supprimer_vente/<int:id>', methods=['POST'])
def supprimer_vente(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Récupération des détails avant suppression
        cursor.execute("SELECT * FROM details_vente WHERE vente_id = %s", (id,))
        details = cursor.fetchall()
        
        # Restauration du stock
        for detail in details:
            cursor.execute(
                "UPDATE produits SET quantite = quantite + %s WHERE id = %s",
                (detail['quantite'], detail['produit_id'])
            )
        
        # Suppression des détails
        cursor.execute("DELETE FROM details_vente WHERE vente_id = %s", (id,))
        
        # Suppression de la vente
        cursor.execute("DELETE FROM ventes WHERE id = %s", (id,))
        
        conn.commit()
        flash(_('Vente supprimée et stock restauré!'), 'success')
    
    except Exception as e:
        conn.rollback()
        flash(_('Erreur de suppression: ') + str(e), 'error')
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
    
    return redirect(url_for('ventes'))

@app.route('/statistiques')
def statistiques():
    # Valeurs par défaut en cas d'erreur
    stats_generales = {
        'total_clients': 0,
        'chiffre_affaire_total': 0.0,
        'panier_moyen': 0.0,
        'total_ventes': 0
    }
    tendances_mensuelles = []
    top_produits = []
    activite_clients = []
    mois = []
    ca_mensuel = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Statistiques générales
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT client_id) AS total_clients,
                SUM(total) AS chiffre_affaire_total,
                AVG(total) AS panier_moyen,
                COUNT(*)      AS total_ventes
            FROM ventes
        """)
        result = cursor.fetchone()
        if result:
            stats_generales = result

        # Tendances mensuelles (12 derniers mois)
        cursor.execute("""
            SELECT 
                DATE_FORMAT(date, '%%Y-%%m') AS mois,
                SUM(total) AS chiffre_affaire
            FROM ventes
            GROUP BY mois
            ORDER BY mois DESC
            LIMIT 12
        """)
        tendances_mensuelles = cursor.fetchall()

        # Top produits (depuis details_vente)
        cursor.execute("""
            SELECT 
                p.nom,
                SUM(dv.quantite) AS total_vendu,
                SUM(dv.quantite * dv.prix_unitaire) AS chiffre_affaire
            FROM details_vente dv
            JOIN produits p ON dv.produit_id = p.id
            GROUP BY p.id
            ORDER BY total_vendu DESC
            LIMIT 10
        """)
        top_produits = cursor.fetchall()

        # Activité clients
        cursor.execute("""
            SELECT
                c.nom,
                COUNT(v.id)     AS nombre_achats,
                SUM(v.total)    AS total_depense
            FROM clients c
            LEFT JOIN ventes v ON v.client_id = c.id
            GROUP BY c.id
            ORDER BY total_depense DESC
            LIMIT 10
        """)
        activite_clients = cursor.fetchall()

        # Préparation des séries pour le graphique
        mois = [row['mois'] for row in tendances_mensuelles]
        ca_mensuel = [float(row['chiffre_affaire']) for row in tendances_mensuelles]

    except Exception as e:
        app.logger.error(f"Erreur dans /statistiques : {e}")
        flash(_('Une erreur est survenue lors du chargement des statistiques'), 'error')

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

    return render_template('statistiques.html',
                           stats_generales=stats_generales,
                           tendances_mensuelles=tendances_mensuelles,
                           top_produits=top_produits,
                           activite_clients=activite_clients,
                           mois=mois,
                           ca_mensuel=ca_mensuel)

@app.route('/ajouter_produit', methods=['GET', 'POST'])
def ajouter_produit():
    if request.method == 'POST':
        try:
            nom = request.form['nom']
            prix = float(request.form['prix'])
            quantite = int(request.form['quantite'])
            categorie_id = request.form.get('categorie_id') or None

            # Validation de la quantité
            if quantite < 0:
                flash(_('La quantité ne peut pas être négative'), 'error')
                return redirect(url_for('ajouter_produit'))

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produits (nom, prix, quantite, categorie_id) VALUES (%s, %s, %s, %s)",
                (nom, prix, quantite, categorie_id)
            )
            conn.commit()
            flash(_('Produit ajouté avec succès!'), 'success')
            return redirect(url_for('produits'))
        
        except ValueError:
            flash(_('Veuillez entrer des valeurs numériques valides'), 'error')
        except Exception as e:
            flash(_('Erreur lors de l\'ajout du produit: ') + str(e), 'error')
            conn.rollback()
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('ajouter_produit.html', categories=categories)

@app.route('/parametres')
def settings():
    # Logique des paramètres
    return render_template('parametres.html')
@app.route('/vente/<int:id>/print')
def print_vente(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Récupérer les données de la vente
        cursor.execute("""
            SELECT v.*, c.nom AS client_nom 
            FROM ventes v
            LEFT JOIN clients c ON v.client_id = c.id 
            WHERE v.id = %s
        """, (id,))
        vente = cursor.fetchone()

        # Récupérer les détails
        cursor.execute("""
            SELECT dv.*, p.nom AS produit_nom 
            FROM details_vente dv
            JOIN produits p ON dv.produit_id = p.id
            WHERE vente_id = %s
        """, (id,))
        details = cursor.fetchall()

         # Récupérer les infos du supermarché
        cursor.execute("SELECT * FROM supermarket_info WHERE id = 1")
        supermarket = cursor.fetchone()

        return render_template('print_vente.html',
                             vente=vente,
                             details=details,
                             maintenant=datetime.now(),
                             supermarket=supermarket)

    except Exception as e:
        flash(f'Erreur : {str(e)}', 'error')
        return redirect(url_for('ventes'))
    
    finally:
        cursor.close()
        conn.close()

UPLOAD_FOLDER = 'static/logos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/admin/parametres', methods=['GET', 'POST'])
def parametres_supermarket():

    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
            nom = request.form['nom']
            telephone = request.form['telephone']
            adresse = request.form['adresse']
            file = request.files.get('logo')

            # Gestion du fichier
            logo_filename = None
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                logo_filename = filename
            
            # Mise à jour des informations
            if logo_filename:
                cursor.execute("""
                    UPDATE supermarket_info 
                    SET nom = %s, telephone = %s, adresse = %s, logo = %s
                    WHERE id = 1
                """, (nom, telephone, adresse, logo_filename))
            else:
                cursor.execute("""
                    UPDATE supermarket_info 
                    SET nom = %s, telephone = %s, adresse = %s
                    WHERE id = 1
                """, (nom, telephone, adresse))
            conn.commit()
            flash('Informations mises à jour avec succès!', 'success')
    
    # Récupération des informations existantes
    cursor.execute("SELECT * FROM supermarket_info WHERE id = 1")
    infos = cursor.fetchone() or {}
    
    cursor.close()
    conn.close()
    
    return render_template('admin/parametres.html', infos=infos)

@app.route('/categories')
def categories():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM categories ORDER BY nom ASC")
        categories = cursor.fetchall()
        
        return render_template('categories.html', categories=categories)
    
    except Exception as e:
        flash(_('Erreur de chargement des catégories: ') + str(e), 'error')
        return render_template('categories.html', categories=[])
    
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.route('/ajouter_categorie', methods=['GET', 'POST'])
def ajouter_categorie():
    if request.method == 'POST':
        try:
            nom = request.form['nom'].strip()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "INSERT INTO categories (nom) VALUES (%s)",
                (nom,)
            )
            conn.commit()
            
            flash(_('Catégorie ajoutée avec succès!'), 'success')
            return redirect(url_for('categories'))
            
        except mysql.connector.IntegrityError:
            flash(_('Cette catégorie existe déjà'), 'error')
        except Exception as e:
            flash(_('Erreur: ') + str(e), 'error')
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    return render_template('ajouter_categorie.html')

@app.route('/editer_categorie/<int:id>', methods=['GET', 'POST'])
def editer_categorie(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        if request.method == 'POST':
            nom = request.form['nom'].strip()
            
            cursor.execute(
                "UPDATE categories SET nom = %s WHERE id = %s",
                (nom, id)
            )
            conn.commit()
            flash(_('Catégorie modifiée avec succès!'), 'success')
            return redirect(url_for('categories'))
        
        cursor.execute("SELECT * FROM categories WHERE id = %s", (id,))
        categorie = cursor.fetchone()
        
        return render_template('editer_categorie.html', categorie=categorie)
    
    except mysql.connector.IntegrityError:
        flash(_('Ce nom existe déjà'), 'error')
    except Exception as e:
        flash(_('Erreur de modification: ') + str(e), 'error')
    finally:
        cursor.close()
        conn.close()


@app.route('/supprimer_categorie/<int:id>', methods=['POST'])
def supprimer_categorie(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM categories WHERE id = %s", (id,))
        conn.commit()
        
        flash(_('Catégorie supprimée avec succès!'), 'success')
    except Exception as e:
        flash(_('Erreur de suppression: ') + str(e), 'error')
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
    
    return redirect(url_for('categories'))

if __name__ == '__main__':
    app.run(debug=True)