from flask import Blueprint, jsonify, request, current_app, send_from_directory
from werkzeug.utils import secure_filename
from .models import User, Dataset, Profil, Action, ProfilsTypesChamps, ChampSensible
from . import db
import os
import json
import pandas as pd
import uuid
from .xacml import generate_xacml_file_from_profil, generate_and_save_all_xacml_from_mongo



main = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_profil_rules_in_mongo(profil_id):
    profil = Profil.query.get(profil_id)
    if not profil:
        return {"error": "Profil introuvable"}, 404

    actions = [action.nom for action in profil.actions]
    types_champs = [t.type_champ for t in profil.types_champs]

    profil_data = {
        "profil_id": profil.id,
        "profil_nom": profil.nom,
        "actions_permises": actions,
        "types_champs_visibles": types_champs
    }

    mongo_db = current_app.mongo_db
    collection = mongo_db['profils_rules']
    collection.delete_one({"profil_id": profil.id})
    collection.insert_one(profil_data)
    
    output_dir = os.path.join(current_app.root_path, 'xacml_rules')
    generate_xacml_file_from_profil(profil_data, output_dir)
    return {"message": "Règles du profil mises à jour dans MongoDB et fichier XACML généré"}

def sync_mongo_after_action_update(func):
    def wrapper(profil_id, *args, **kwargs):
        response = func(profil_id, *args, **kwargs)
        # On force la mise à jour des règles MongoDB + génération XACML après la route
        update_profil_rules_in_mongo(profil_id)
        return response
    wrapper.__name__ = func.__name__
    return wrapper

# --- ROUTES UTILISATEURS ---

@main.route('/api/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([
        {
            "id": u.id,
            "nom": u.nom,
            "email": u.email,
            "profil_id": u.profil_id,
            "profil_nom": u.profil.nom if u.profil else None
        }
        for u in users
    ])

@main.route('/api/users', methods=['POST'])
def create_user():
    data = request.get_json()
    nom = data.get('nom')
    email = data.get('email')
    mot_de_passe = data.get('mot_de_passe', 'changeme123')
    profil_id = data.get('profil_id')

    if not nom or not email or not profil_id:
        return jsonify({'error': 'Champs requis manquants'}), 400

    profil = Profil.query.get(profil_id)
    if not profil:
        return jsonify({'error': f'Profil avec id {profil_id} introuvable'}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'error': 'Email déjà utilisé'}), 409

    new_user = User(nom=nom, email=email, mot_de_passe=mot_de_passe, profil_id=profil_id)
    db.session.add(new_user)
    db.session.commit()

    return jsonify(new_user.to_dict()), 201

@main.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'Utilisateur supprimé avec succès'}), 200

@main.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    # Mise à jour du nom
    if 'nom' in data:
        nom = data['nom'].strip()
        if not nom:
            return jsonify({'error': 'Le nom ne peut pas être vide'}), 400
        user.nom = nom

    # Mise à jour de l'email (avec vérification unicité)
    if 'email' in data:
        email = data['email'].strip()
        if not email:
            return jsonify({'error': 'L\'email ne peut pas être vide'}), 400

        existing_user = User.query.filter(User.email == email, User.id != user_id).first()
        if existing_user:
            return jsonify({'error': 'Cet email est déjà utilisé'}), 409

        user.email = email

    # Mise à jour du profil
    if 'profil_id' in data:
        profil_id = data['profil_id']
        profil = Profil.query.get(profil_id)
        if not profil:
            return jsonify({'error': 'Profil invalide'}), 400
        user.profil_id = profil_id

    try:
        db.session.commit()
        return jsonify({'message': 'Utilisateur mis à jour avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la mise à jour : {str(e)}'}), 500


# --- ROUTES DATASETS ---# Routes Admin mises à jour pour les nouveaux modèles

# Routes corrigées - Plus de référence à data_owner

@main.route('/api/datasets', methods=['GET'])
def get_datasets():
    """Récupérer tous les datasets avec informations du propriétaire via jointure"""
    # Récupérer tous les datasets
    datasets = Dataset.query.all()
    print(f"Nombre de datasets trouvés: {len(datasets)}")
    
    result = []
    for dataset in datasets:
        print(f"Dataset ID: {dataset.id}, owner_id: {dataset.owner_id}")
        
        # Pour chaque dataset, essayer de récupérer le propriétaire
        owner = None
        if dataset.owner_id:
            owner = User.query.filter_by(id=dataset.owner_id).first()
            print(f"Recherche owner avec ID {dataset.owner_id}: {'trouvé' if owner else 'non trouvé'}")
            if owner:
                print(f"Owner trouvé: nom={owner.nom}, email={owner.email}")
        else:
            print("owner_id est None")
        
        dataset_info = {
            "id": dataset.id,
            "titre": dataset.titre,
            "date_creation": dataset.date_creation.isoformat() if dataset.date_creation else None,
            "owner_id": dataset.owner_id,
            "owner_name": owner.nom if owner else None,
            "owner_email": owner.email if owner else None,
            "status": dataset.status,
            "has_content": dataset.contenu is not None,
            "has_anonymized_content": dataset.contenu_anonymized is not None
        }
        
        print(f"Dataset final: {dataset_info}")
        result.append(dataset_info)
    
    return jsonify(result)

@main.route('/api/datasets', methods=['POST'])
def create_dataset():
    """Créer un nouveau dataset"""
    data = request.get_json()
    titre = data.get('titre')
    owner_name = data.get('owner_name', 'admin')  # Utiliser owner_name au lieu d'owner_email
    status = data.get('status', 'original')

    if not titre:
        return jsonify({'error': 'Le champ titre est requis'}), 400

    # Trouver l'utilisateur par nom
    user = User.query.filter_by(nom=owner_name).first()
    if not user:
        return jsonify({'error': f'Utilisateur non trouvé avec le nom: {owner_name}'}), 404

    new_dataset = Dataset(
        titre=titre,
        owner_id=user.id,
        status=status,
        contenu=[]
    )
    
    try:
        db.session.add(new_dataset)
        db.session.commit()
        return jsonify({
            'message': 'Dataset ajouté avec succès', 
            'id': new_dataset.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la création : {str(e)}'}), 500



@main.route('/api/datasets/<int:id>', methods=['PUT'])
def update_dataset(id):
    """Mettre à jour un dataset"""
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    try:
        print(f"Mise à jour du dataset {id} avec les données: {data}")  # Debug
        
        # Mise à jour du titre
        if 'titre' in data:
            new_titre = data['titre'].strip()
            if not new_titre:
                return jsonify({'error': 'Le titre ne peut pas être vide'}), 400
            dataset.titre = new_titre
            print(f"Titre mis à jour: {new_titre}")

        # CORRECTION : Gestion du propriétaire
        # Si 'owner_email' contient en réalité un nom d'utilisateur
        if 'owner_email' in data:
            data_owner_name = data['owner_email']  # C'est en fait un nom
            print(f"Recherche utilisateur avec le nom: '{data_owner_name}'")
            
            # Chercher l'utilisateur par son NOM (pas email)
            user = User.query.filter_by(nom=data_owner_name).first()
            
            if not user:
                # Essayer une recherche insensible à la casse
                user = User.query.filter(
                    db.func.lower(User.nom) == data_owner_name.lower()
                ).first()
            
            if not user:
                # Lister les utilisateurs disponibles pour debug
                all_users = User.query.all()
                available_users = [{'id': u.id, 'nom': u.nom, 'email': u.email} for u in all_users]
                print(f"Utilisateurs disponibles: {available_users}")
                
                return jsonify({
                    'error': f'Utilisateur non trouvé avec le nom: "{data_owner_name}"',
                    'available_users': available_users
                }), 404
            
            dataset.owner_id = user.id
            print(f"Propriétaire trouvé: {user.nom} (ID: {user.id}, Email: {user.email})")

        # Alternative : si vous voulez renommer le champ pour plus de clarté
        elif 'owner_name' in data:
            owner_name = data['owner_name']
            print(f"Recherche utilisateur avec le nom: '{owner_name}'")
            
            user = User.query.filter_by(nom=owner_name).first()
            
            if not user:
                user = User.query.filter(
                    db.func.lower(User.nom) == owner_name.lower()
                ).first()
            
            if not user:
                all_users = User.query.all()
                available_users = [{'id': u.id, 'nom': u.nom, 'email': u.email} for u in all_users]
                
                return jsonify({
                    'error': f'Utilisateur non trouvé avec le nom: "{owner_name}"',
                    'available_users': available_users
                }), 404
            
            dataset.owner_id = user.id
            print(f"Propriétaire trouvé: {user.nom} (ID: {user.id}, Email: {user.email})")

        # Gestion de l'email réel (si fourni)
        elif 'owner_email_real' in data:
            owner_email = data['owner_email_real']
            print(f"Recherche utilisateur avec l'email: '{owner_email}'")
            
            user = User.query.filter_by(email=owner_email).first()
            
            if not user:
                return jsonify({
                    'error': f'Utilisateur non trouvé avec l\'email: "{owner_email}"'
                }), 404
            
            dataset.owner_id = user.id
            print(f"Propriétaire trouvé: {user.nom} (ID: {user.id}, Email: {user.email})")

        # Mise à jour du statut
        if 'status' in data:
            new_status = data['status']
            dataset.status = new_status
            print(f"Statut mis à jour: {new_status}")

        # Commit des changements
        db.session.commit()
        print(f"Dataset {id} mis à jour avec succès")
        
        # Retourner les informations mises à jour
        owner = User.query.get(dataset.owner_id) if dataset.owner_id else None
        
        return jsonify({
            'message': 'Dataset mis à jour avec succès',
            'dataset': {
                'id': dataset.id,
                'titre': dataset.titre,
                'status': dataset.status,
                'owner_id': dataset.owner_id,
                'owner_name': owner.nom if owner else None,
                'owner_email': owner.email if owner else None
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la mise à jour du dataset {id}: {str(e)}")
        return jsonify({
            'error': f'Erreur lors de la mise à jour : {str(e)}'
        }), 500


# Route utilitaire pour mapper nom -> email
@main.route('/api/users/by-name/<string:name>', methods=['GET'])
def get_user_by_name(name):
    """Récupérer un utilisateur par son nom"""
    try:
        user = User.query.filter_by(nom=name).first()
        
        if not user:
            # Essayer recherche insensible à la casse
            user = User.query.filter(
                db.func.lower(User.nom) == name.lower()
            ).first()
        
        if not user:
            return jsonify({
                'error': f'Utilisateur non trouvé avec le nom: "{name}"',
                'all_users': [{'nom': u.nom, 'email': u.email} for u in User.query.all()]
            }), 404
        
        return jsonify({
            'id': user.id,
            'nom': user.nom,
            'email': user.email,
            'profil_id': user.profil_id
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@main.route('/api/datasets/<int:id>', methods=['DELETE'])
def delete_dataset(id):
    """Supprimer un dataset"""
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    try:
        db.session.delete(dataset)
        db.session.commit()
        return jsonify({'message': 'Dataset supprimé avec succès'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la suppression : {str(e)}'}), 500

@main.route('/api/datasets/<int:id>/download', methods=['GET'])
def download_dataset(id):
    """Télécharger un dataset au format CSV"""
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    if not dataset.contenu:
        return jsonify({'error': 'Aucun contenu disponible pour ce dataset'}), 404

    try:
        # Convertir le contenu JSON en DataFrame puis CSV
        import pandas as pd
        df = pd.DataFrame(dataset.contenu)
        
        filename = secure_filename(f"{dataset.titre}.csv")
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        
        df.to_csv(filepath, index=False)
        
        return send_from_directory(upload_folder, filename, as_attachment=True)
        
    except Exception as e:
        return jsonify({'error': f'Erreur lors de la génération du fichier : {str(e)}'}), 500


###############################################

@main.route('/api/datasets/<int:id>', methods=['GET'])
def get_dataset_info(id):
    """Récupérer les informations détaillées d'un dataset"""
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    try:
        # Récupérer les informations du propriétaire
        owner = User.query.get(dataset.owner_id) if dataset.owner_id else None
        
        # Préparer le contenu JSON
        contenu_json = []
        if dataset.contenu:
            if isinstance(dataset.contenu, str):
                try:
                    contenu_json = json.loads(dataset.contenu)
                except json.JSONDecodeError:
                    contenu_json = []
            elif isinstance(dataset.contenu, list):
                contenu_json = dataset.contenu
        
        result = {
            'id': dataset.id,
            'titre': dataset.titre,
            'date_creation': dataset.date_creation.isoformat() if dataset.date_creation else None,
            'status': dataset.status,
            'owner_id': dataset.owner_id,
            'owner_name': owner.nom if owner else None,
            'owner_email': owner.email if owner else None,
            'has_content': len(contenu_json) > 0,
            'has_anonymized_content': dataset.contenu_anonymized is not None,
            'contenu': contenu_json  # CORRECTION : suppression de l'erreur de syntaxe
        }

        # Si le dataset a du contenu, fournir un aperçu et les champs
        if contenu_json and len(contenu_json) > 0:
            preview_data = contenu_json[:5]  # Aperçu des 5 premiers enregistrements
            fields = list(preview_data[0].keys()) if preview_data else []
            
            result.update({
                'fields': fields,
                'preview': preview_data,
                'total_records': len(contenu_json)
            })
        else:
            # Pas de données, on retourne des champs vides
            result.update({
                'fields': [],
                'preview': [],
                'total_records': 0
            })

        print(f"Dataset {id} info récupérée : {result}")  # Debug
        return jsonify(result)
        
    except Exception as e:
        print(f"Erreur lors de la récupération du dataset {id}: {str(e)}")  # Debug
        return jsonify({'error': f'Erreur lors de la lecture : {str(e)}'}), 500



# Ajoutez aussi cette route pour une meilleure gestion des erreurs
@main.route('/api/datasets/<int:id>/fields', methods=['GET'])
def get_dataset_fields(id):
    """Route spécialement pour récupérer les champs et aperçu d'un dataset"""
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    try:
        contenu_json = []
        if dataset.contenu:
            if isinstance(dataset.contenu, str):
                try:
                    contenu_json = json.loads(dataset.contenu)
                except json.JSONDecodeError:
                    contenu_json = []
            elif isinstance(dataset.contenu, list):
                contenu_json = dataset.contenu

        if not contenu_json or len(contenu_json) == 0:
            return jsonify({
                'error': 'Aucune donnée disponible dans ce dataset',
                'fields': [],
                'preview': []
            }), 400

        # Extraire les champs du premier enregistrement
        fields = list(contenu_json[0].keys()) if contenu_json else []
        preview = contenu_json[:10]  # Aperçu des 10 premiers enregistrements

        return jsonify({
            'id': dataset.id,
            'titre': dataset.titre,
            'fields': fields,
            'preview': preview,
            'total_records': len(contenu_json)
        })

    except Exception as e:
        print(f"Erreur lors de la récupération des champs du dataset {id}: {str(e)}")
        return jsonify({'error': f'Erreur lors de la lecture des champs : {str(e)}'}), 500
########################################################

@main.route('/api/datasets/upload', methods=['POST'])
def upload_dataset_csv():
    """Upload d'un fichier CSV pour créer un dataset"""
    if 'file' not in request.files:
        return jsonify({'error': 'Pas de fichier envoyé'}), 400

    file = request.files['file']
    owner_name = request.form.get('owner_name', 'admin')  # Valeur par défaut "admin"
    status = request.form.get('status', 'original')

    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400

    # Trouver l'utilisateur par nom
    user = User.query.filter_by(nom=owner_name).first()
    if not user:
        return jsonify({'error': f'Utilisateur non trouvé avec le nom: {owner_name}'}), 404

    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            base, ext = os.path.splitext(filename)
            unique_suffix = str(uuid.uuid4())[:8]
            unique_filename = f"{base}_{unique_suffix}{ext}"
            
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, unique_filename)
            file.save(filepath)

            titre = os.path.splitext(unique_filename)[0]

            # Lire le CSV
            import pandas as pd
            df = pd.read_csv(filepath)
            
            if df.empty:
                return jsonify({'error': 'Fichier CSV vide'}), 400

            # Convertir en JSON
            contenu_json = df.to_dict(orient='records')

            new_dataset = Dataset(
                titre=titre,
                owner_id=user.id,  # Seulement owner_id
                status=status,
                contenu=contenu_json
            )
            
            db.session.add(new_dataset)
            db.session.commit()

            return jsonify({
                'message': 'Fichier CSV uploadé avec succès', 
                'id': new_dataset.id
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Erreur lors du traitement : {str(e)}'}), 500

    return jsonify({'error': 'Type de fichier non autorisé'}), 400

#anonimization


# --- Enregistrer les champs sensibles et leurs techniques ---
@main.route('/api/datasets/<int:id>/champs_sensibles', methods=['POST'])
def save_champs_sensibles(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Données invalides : liste attendue'}), 400

    try:
        # Supposons que ChampSensible est lié au dataset par dataset_id
        # On supprime les anciennes configs pour ce dataset
        ChampSensible.query.filter_by(dataset_id=id).delete()

        for champ in data:
            nom = champ.get('nom')
            type_champ = champ.get('type_champ', 'Champ non sensible')
            technique_associee = champ.get('technique_associee')
            est_visible = champ.get('est_visible', True)

            if not nom:
                continue

            new_champ = ChampSensible(
                dataset_id=id,
                nom=nom,
                type_champ=type_champ,
                technique_associee=technique_associee,
                est_visible=est_visible
            )
            db.session.add(new_champ)

        db.session.commit()
        return jsonify({'message': 'Champs sensibles enregistrés avec succès'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la sauvegarde : {str(e)}'}), 500


# --- Enregistrer les données anonymisées ---
@main.route('/api/datasets/<int:id>/anonymize', methods=['POST'])
def save_anonymized_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données JSON manquantes ou mal formées'}), 400

    anonymized_data = data.get('anonymizedData')
    if anonymized_data is None:
        return jsonify({'error': 'Données anonymisées manquantes'}), 400

    try:
        json_str = json.dumps(anonymized_data)
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Données anonymisées invalides (JSON) : {str(e)}'}), 400

    try:
        dataset.contenu_anonymized = json_str
        dataset.status = "completed"
        db.session.commit()
        return jsonify({'message': 'Dataset anonymisé enregistré avec succès'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de l’enregistrement : {str(e)}'}), 500

# --- PROFILS & ACTIONS ---

@main.route('/api/profils', methods=['POST'])
def create_profil():
    data = request.get_json()
    nom = data.get('nom')
    if not nom:
        return jsonify({'error': 'Nom requis'}), 400
    if Profil.query.filter_by(nom=nom).first():
        return jsonify({'error': 'Profil déjà existant'}), 400
    p = Profil(nom=nom)
    db.session.add(p)
    db.session.commit()
    update_profil_rules_in_mongo(p.id)
    return jsonify({'id': p.id, 'nom': p.nom}), 201

@main.route('/api/profils/<int:profil_id>/actions', methods=['GET'])
def get_profil_actions(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    actions = [{'id': a.id, 'nom': a.nom} for a in profil.actions]
    return jsonify(actions)

@main.route('/api/profils/<int:profil_id>/actions', methods=['POST'])
@sync_mongo_after_action_update
def set_profil_actions(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    data = request.get_json()
    actions_names = data.get('actions', [])
    if not isinstance(actions_names, list):
        return jsonify({'error': 'Liste invalide'}), 400

    actions = Action.query.filter(Action.nom.in_(actions_names)).all()
    profil.actions = actions
    db.session.commit()
    return jsonify({'message': 'Actions mises à jour'})

@main.route('/api/profils/<int:profil_id>/types_champs', methods=['POST'])
@sync_mongo_after_action_update
def set_types_champs_for_profil(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    data = request.get_json()
    types_champs = data.get('types_champs')

    if not isinstance(types_champs, list):
        return jsonify({'error': 'La liste des types de champs est invalide'}), 400

    try:
        ProfilsTypesChamps.query.filter_by(profil_id=profil_id).delete()
        for type_champ in types_champs:
            ptc = ProfilsTypesChamps(profil_id=profil_id, type_champ=type_champ)
            db.session.add(ptc)
        db.session.commit()
        return jsonify({'message': 'Types de champs mis à jour'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la mise à jour : {str(e)}'}), 500

@main.route('/api/profils/<int:profil_id>', methods=['DELETE'])
def delete_profil(profil_id):
    profil = Profil.query.get(profil_id)
    if not profil:
        return jsonify({'error': 'Profil non trouvé'}), 404
    try:
        db.session.delete(profil)
        db.session.commit()
       
        # Suppression dans MongoDB
        mongo_db = current_app.mongo_db
        collection = mongo_db['profils_rules']
        collection.delete_one({"profil_id": profil_id})

        return jsonify({'message': 'Profil supprimé'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@main.route('/api/profils', methods=['GET'])
def get_profils():
    profils = Profil.query.all()
    profils_list = []
    for profil in profils:
        profils_list.append({
            'id': profil.id,
            'nom': profil.nom
        })
    return jsonify(profils_list)

# --- ROUTE POUR GENERER TOUS LES FICHIERS XACML ---

@main.route('/api/generate_xacml', methods=['GET'])
def generate_xacml():
    try:
        files = generate_and_save_all_xacml_from_mongo()
        return jsonify({"message": "Fichiers XACML générés", "fichiers": files}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

###dashboard connexion###################""

@main.route('/api/dashboard_stats', methods=['GET'])
def get_dashboard_stats():
    # Exemple : calculs basiques, adapter selon ta logique métier
    total_datasets = Dataset.query.count()
    
    # Exemple simple : nombre total utilisateurs
    total_users = User.query.count()
    
    # Par exemple : répartition techniques (simulée ici)
    techniques = [
        {'name': 'Aggregation', 'value': 40},
        {'name': 'Generalization', 'value': 30},
        {'name': 'Randomization', 'value': 20},
        {'name': 'Masking', 'value': 10},
    ]

    # Exemple : activité utilisateurs simulée
    user_activity = [
        {'name': 'Utilisateurs', 'value': total_users},
        {'name': 'Temps passé (heures)', 'value': 450},  # A adapter selon tes données
    ]

    # Exemple : autres metrics
    new_users = 12  # à calculer
    activity_rate = 78  # %
    success_rate = 94  # %

    return jsonify({
        'totalDatasets': total_datasets,
        'techniquesData': techniques,
        'userData': user_activity,
        'newUsers': new_users,
        'activityRate': activity_rate,
        'successRate': success_rate
    })



@main.route('/api/datasets/<int:id>/download_anonymized', methods=['GET'])
def download_anonymized(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    if not dataset.contenu_anonymized:
        return jsonify({'error': 'Données anonymisées non disponibles'}), 404

    json_data = json.loads(dataset.contenu_anonymized)
    df = pd.DataFrame(json_data)

    output_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f'dataset_{id}_anonymized.csv')
    df.to_csv(output_path, index=False)

    return send_from_directory(current_app.config['UPLOAD_FOLDER'], f'dataset_{id}_anonymized.csv', as_attachment=True)
