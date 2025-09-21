from flask import Blueprint, request, jsonify, current_app, Response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import os
import os.path
from . import db
import io
from .models import User, Dataset, Profil, Action, ProfilsTypesChamps, ChampSensible
import json
import csv
from datetime import datetime
import uuid 
import pandas as pd
import re

user_bp = Blueprint('user_bp', __name__, url_prefix='/api/user')

# Configuration pour l'upload de photos
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_csv_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'csv'

def get_user_permissions(user):
    """Récupère les permissions d'un utilisateur depuis MongoDB"""
    if not user or not user.profil_id:
        return {'actions': [], 'types_champs_visibles': []}
    
    profil = Profil.query.get(user.profil_id)
    if not profil:
        return {'actions': [], 'types_champs_visibles': []}
    
    rules = current_app.mongo_db['profils_rules'].find_one({'profil_nom': profil.nom})
    if not rules:
        rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': user.profil_id})
    
    if rules:
        xacml_actions = rules.get('actions_permises', [])
        action_mapping = {
            'Add data': ['upload_dataset', 'create_data'],
            'Analyze data': ['view_datasets', 'view_activity'],
            'Annotate data': ['view_datasets'],
            'Anonymize data': ['anonymize_data'],
            'Archive data': ['manage_datasets'],
            'Clean data': ['process_data'],
            'Cluster data': ['analyze_data'],
            'Collect data': ['upload_dataset'],
            'Compare data': ['view_datasets'],
            'Convert data': ['process_data'],
            'Create data': ['upload_dataset', 'create_data'],
            'Encrypt data': ['secure_data'],
            'Filter data': ['view_datasets', 'process_data'],
            'Import data': ['upload_dataset'],
            'Index data': ['organize_data'],
            'Integrate data': ['process_data'],
            'Link data': ['link_data'],
            'Merge data': ['process_data'],
            'Normalize data': ['process_data'],
            'Organize data': ['organize_data'],
            'Process data': ['process_data'],
            'Protect data': ['secure_data'],
            'Pseudonymize data': ['anonymize_data'],
            'Secure data': ['secure_data', 'manage_settings']
        }
        
        frontend_actions = []
        for xacml_action in xacml_actions:
            if xacml_action in action_mapping:
                frontend_actions.extend(action_mapping[xacml_action])
        
        return {
            'actions': list(set(frontend_actions)),
            'types_champs_visibles': rules.get('types_champs_visibles', [])
        }
    
    return {'actions': [], 'types_champs_visibles': []}


import random
import logging

def apply_anonymization(value, field_name, technique, strength=1):
    str_val = str(value) if value is not None else ''

    match technique:
        case 'Masking':
            if 'email' in field_name.lower() and '@' in str_val:
                name, domain = str_val.split('@', 1)
                mask_ratio = 0.3 + (strength * 0.2)
                mask_count = int(len(name) * mask_ratio)
                masked_name = name[:max(1, len(name) - mask_count)] + '*' * mask_count
                return f"{masked_name}@{domain}"
            else:
                keep_chars = max(1, 3 - strength)
                if len(str_val) > keep_chars * 2:
                    return str_val[:keep_chars] + '*' * (len(str_val) - keep_chars * 2) + str_val[-keep_chars:]
                else:
                    return '*' * len(str_val)

        case 'K-Anonymity':
            if isinstance(value, (int, float)):
                if 'age' in field_name.lower():
                    ranges = [20, 30, 40, 50] if strength == 1 else [25, 50, 75] if strength == 2 else [30, 60]
                    for i in range(len(ranges) - 1):
                        if ranges[i] <= value < ranges[i + 1]:
                            return f"{ranges[i]}-{ranges[i + 1] - 1}"
                    return f"{ranges[-1]}+" if value >= ranges[-1] else f"<{ranges[0]}"
                else:
                    factor = 100 if strength == 1 else 1000
                    return int(value // factor * factor)
            return str_val[0] + '***' if str_val else '***'

        case 'Aggregation':
            if isinstance(value, (int, float)):
                range_size = 10000 if strength == 1 else 20000 if strength == 2 else 30000
                lower = int(value // range_size * range_size)
                return f"{lower}-{lower + range_size - 1}"
            return value

        case 'Generalization':
            if isinstance(value, str):
                keep_chars = max(1, 3 - strength)
                return value[:keep_chars] + '***' if value else '***'
            elif isinstance(value, (int, float)):
                factor = 5 if strength == 1 else 10
                return int(value // factor * factor)
            return value

        case 'Randomization':
            if isinstance(value, (int, float)):
                noise_level = 0.05 + (strength * 0.4)
                noise = value * noise_level * (random.uniform(-1, 1))
                return round(value + noise)
            return value

        case 'Suppression':
            return '[SUPPRIMÉ]'

        case 'Shuffling':
            return random.randint(0, 999) if isinstance(value, (int, float)) else \
                   'shuffled_' + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))

        case 'Pseudonymization':
            return 'pseudo_' + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))

        case 'PCA':
            if isinstance(value, (int, float)):
                return round(value * 0.8 + random.uniform(0, 10))
            return value

        case _:
            return value


def filter_content_by_field_types(content_data, visible_field_types, dataset_id):
    """
    Filtre le contenu d'un dataset selon les types de champs visibles pour l'utilisateur.
    Pour les champs non visibles (même non sensibles), applique la technique d'anonymisation définie.
    """
    if not content_data:
        return []

    try:
        # Récupérer la configuration des champs sensibles pour ce dataset
        champs_config = ChampSensible.query.filter_by(dataset_id=dataset_id).all()
        
        # Créer un mapping nom_champ -> (type_champ, technique_associee, est_visible)
        field_info_mapping = {}
        for champ in champs_config:
            field_info_mapping[champ.nom] = {
                'type': champ.type_champ,
                'technique': champ.technique_associee,
                'visible': champ.est_visible
            }

        strength = 2  # Paramètre ajustable

        # Si le contenu est une liste de dictionnaires (format JSON)
        if isinstance(content_data[0], dict):
            headers = list(content_data[0].keys())
            filtered_data = []

            for row in content_data:
                filtered_row = {}
                for header in headers:
                    field_info = field_info_mapping.get(header, {
                        'type': 'Champ non sensible',
                        'technique': None,
                        'visible': True
                    })
                    value = row.get(header, '')

                    if field_info['type'] in visible_field_types:
                        filtered_row[header] = value
                    else:
                        filtered_row[header] = apply_anonymization(value, header, field_info['technique'], strength)

                filtered_data.append(filtered_row)
            return filtered_data

        # Si le contenu est une liste de listes (CSV avec headers en première ligne)
        else:
            headers = content_data[0]
            filtered_content = [headers.copy()]

            for row in content_data[1:]:
                if isinstance(row, list):
                    filtered_row = []
                    for i, value in enumerate(row):
                        if i >= len(headers):
                            continue
                        header = headers[i]
                        field_info = field_info_mapping.get(header, {
                            'type': 'Champ non sensible',
                            'technique': None,
                            'visible': True
                        })

                        if field_info['type'] in visible_field_types:
                            filtered_row.append(value)
                        else:
                            filtered_row.append(apply_anonymization(value, header, field_info['technique'], strength))

                    filtered_content.append(filtered_row)
            return filtered_content

    except Exception as e:
        logging.error(f"Erreur lors du filtrage des champs: {str(e)}")
        return content_data  # Retourne les données originales en cas d'erreur

def json_to_csv_format(json_data, limit=20):
    """
    Convertit des données JSON en format CSV-like pour l'affichage
    """
    if not json_data:
        return []
    
    # Limiter le nombre de lignes
    limited_data = json_data[:limit] if len(json_data) > limit else json_data
    
    if not limited_data:
        return []
    
    # Si c'est une liste de dictionnaires
    if isinstance(limited_data[0], dict):
        headers = list(limited_data[0].keys())
        rows = [headers]  # Première ligne = headers
        
        for item in limited_data:
            row = []
            for key in headers:
                value = item.get(key, '')
                # Convertir en string et gérer les valeurs nulles
                if value is None:
                    row.append('')
                elif isinstance(value, (dict, list)):
                    row.append(str(value))
                else:
                    row.append(str(value))
            rows.append(row)
        
        return rows
    
    # Si c'est déjà un format tableau
    else:
        return limited_data

# ================================
# ROUTES D'AUTHENTIFICATION
# ================================

@user_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    mot_de_passe = data.get('mot_de_passe')

    if not email or not mot_de_passe:
        return jsonify({'error': 'Email et mot de passe requis'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404

    if user.mot_de_passe != mot_de_passe:
        return jsonify({'error': 'Mot de passe incorrect'}), 401

    profil = Profil.query.get(user.profil_id)
    if not profil:
        return jsonify({'error': 'Profil non trouvé'}), 404

    print(f"Recherche des règles pour profil_nom: {profil.nom}")
    rules = current_app.mongo_db['profils_rules'].find_one({'profil_nom': profil.nom})

    if not rules:
        print(f"Pas trouvé par nom, essai avec profil_id: {user.profil_id}")
        rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': user.profil_id})

    if rules:
        print(f"Règles trouvées dans MongoDB: {rules}")

        xacml_actions = rules.get('actions_permises', [])
        action_mapping = {
            'Add data': ['upload_dataset', 'create_data'],
            'Analyze data': ['view_datasets', 'view_activity'],
            'Annotate data': ['view_datasets'],
            'Anonymize data': ['anonymize_data'],
            'Archive data': ['manage_datasets'],
            'Clean data': ['process_data'],
            'Cluster data': ['analyze_data'],
            'Collect data': ['upload_dataset'],
            'Compare data': ['view_datasets'],
            'Convert data': ['process_data'],
            'Create data': ['upload_dataset', 'create_data'],
            'Encrypt data': ['secure_data'],
            'Filter data': ['view_datasets', 'process_data'],
            'Import data': ['upload_dataset'],
            'Index data': ['organize_data'],
            'Integrate data': ['process_data'],
            'Link data': ['link_data'],
            'Merge data': ['process_data'],
            'Normalize data': ['process_data'],
            'Organize data': ['organize_data'],
            'Process data': ['process_data'],
            'Protect data': ['secure_data'],
            'Pseudonymize data': ['anonymize_data'],
            'Secure data': ['secure_data', 'manage_settings']
        }

        frontend_actions = []
        for xacml_action in xacml_actions:
            if xacml_action in action_mapping:
                frontend_actions.extend(action_mapping[xacml_action])

        actions = list(set(frontend_actions))
        types_champs_visibles = rules.get('types_champs_visibles', [])

        print(f"Actions XACML: {xacml_actions}")
        print(f"Actions frontend mappées: {actions}")

    else:
        print(f"Aucune règle trouvée pour profil_nom: {profil.nom} ou profil_id: {user.profil_id}")
        actions = []
        types_champs_visibles = []

    response_data = {
        'id': user.id,
        'nom': user.nom,
        'email': user.email,
        'profil_id': user.profil_id,
        'profil_nom': profil.nom,
        'actions': actions,
        'types_champs_visibles': types_champs_visibles
    }

    print(f"Réponse envoyée au frontend: {response_data}")
    return jsonify(response_data)

# ================================
# ROUTES DE DEBUG
# ================================

@user_bp.route('/debug/profil/<int:profil_id>', methods=['GET'])
def debug_profil_rules(profil_id):
    rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': profil_id})
    return jsonify({
        'profil_id': profil_id,
        'rules_found': rules is not None,
        'rules': rules
    })

@user_bp.route('/debug/all-profils', methods=['GET'])
def debug_all_profils():
    try:
        all_rules = list(current_app.mongo_db['profils_rules'].find({}))
        for rule in all_rules:
            if '_id' in rule:
                rule['_id'] = str(rule['_id'])
        return jsonify({
            'total': len(all_rules),
            'rules': all_rules
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ================================
# ROUTES UTILISATEUR
# ================================

@user_bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
    return jsonify({
        'id': user.id,
        'nom': user.nom,
        'email': user.email,
        'profil_id': user.profil_id,
        'profil_nom': user.profil.nom if user.profil else None
    })

@user_bp.route('/profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    """Récupérer le profil utilisateur avec permissions"""
    
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Utilisateur non trouvé'}), 404

        # Récupérer le profil
        profil = Profil.query.get(user.profil_id) if user.profil_id else None
        
        # Récupérer les permissions
        permissions = get_user_permissions(user)

        # Préparer les données utilisateur (sans mot de passe)
        user_data = {
            'id': user.id,
            'nom': user.nom,
            'email': user.email,
            'photo': getattr(user, 'photo', None),
            'profil_id': user.profil_id,
            'profil_nom': profil.nom if profil else None,
            'created_at': user.created_at.isoformat() if hasattr(user, 'created_at') and user.created_at else None,
            'updated_at': user.updated_at.isoformat() if hasattr(user, 'updated_at') and user.updated_at else None
        }

        return jsonify({
            'success': True,
            'user': user_data,
            'permissions': permissions
        }), 200

    except Exception as e:
        print(f"Erreur lors de la récupération du profil: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Erreur lors de la récupération du profil'
        }), 500

@user_bp.route('/update_info', methods=['PUT'])
def update_user_info():
    # Debug: Vérifiez le content-type
    print("Content-Type:", request.content_type)
    
    try:
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            user_id = request.form.get('id')
            nom = request.form.get('nom')
            email = request.form.get('email')
            mot_de_passe = request.form.get('mot_de_passe')
            photo = request.files.get('photo')
        else:
            data = request.get_json()
            user_id = data.get('id')
            nom = data.get('nom')
            email = data.get('email')
            mot_de_passe = data.get('mot_de_passe')
            photo = None

        # Validation
        if not user_id:
            return jsonify({'success': False, 'message': 'ID utilisateur manquant'}), 400

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Utilisateur non trouvé'}), 404

        # Mise à jour
        if nom: user.nom = nom
        if email: user.email = email
        if mot_de_passe:
            user.mot_de_passe = generate_password_hash(mot_de_passe)

        db.session.commit()

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'nom': user.nom,
                'email': user.email
            }
        })

    except Exception as e:
        db.session.rollback()
        print("Error:", str(e))  # Debug
        return jsonify({'success': False, 'message': str(e)}), 500

@user_bp.route('/update_info2', methods=['PUT'])
def update_user_info_v2():
    """Route optimisée pour mettre à jour seulement les champs modifiés"""
    
    try:
        # Gestion du multipart/form-data et JSON
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            user_id = request.form.get('id')
            nom = request.form.get('nom')
            email = request.form.get('email')
            mot_de_passe = request.form.get('mot_de_passe')
            photo = request.files.get('photo')
        else:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'Données manquantes'}), 400
            
            user_id = data.get('id')
            nom = data.get('nom')
            email = data.get('email')
            mot_de_passe = data.get('mot_de_passe')
            photo = None

        # Validation de l'ID utilisateur
        if not user_id:
            return jsonify({'success': False, 'message': 'ID utilisateur requis'}), 400

        # Récupérer l'utilisateur existant
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Utilisateur non trouvé'}), 404

        # Détecter les champs modifiés
        modified_fields = []
        updated_data = {}

        # Vérification nom
        if nom is not None and nom.strip() != (user.nom or ''):
            if not nom.strip():
                return jsonify({'success': False, 'message': 'Le nom ne peut pas être vide'}), 400
            
            updated_data['nom'] = nom.strip()
            modified_fields.append('nom')

        # Vérification email
        if email is not None and email.strip().lower() != (user.email or '').lower():
            email_clean = email.strip().lower()
            
            if not email_clean:
                return jsonify({'success': False, 'message': 'L\'email ne peut pas être vide'}), 400
            
            # Validation format email
            email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
            if not re.match(email_regex, email_clean):
                return jsonify({'success': False, 'message': 'Format d\'email invalide'}), 400
            
            # Vérifier unicité de l'email
            existing_user = User.query.filter(User.email == email_clean, User.id != user_id).first()
            if existing_user:
                return jsonify({'success': False, 'message': 'Cet email est déjà utilisé par un autre utilisateur'}), 400
            
            updated_data['email'] = email_clean
            modified_fields.append('email')

        # Vérification mot de passe
        if mot_de_passe and mot_de_passe.strip():
            password_clean = mot_de_passe.strip()
            
            if len(password_clean) < 6:
                return jsonify({'success': False, 'message': 'Le mot de passe doit contenir au moins 6 caractères'}), 400
            
            updated_data['mot_de_passe'] = generate_password_hash(password_clean)
            modified_fields.append('mot de passe')

        # Gestion de la photo
        old_photo_path = None
        if photo and photo.filename:
            # Validation du fichier
            if not allowed_file(photo.filename):
                return jsonify({'success': False, 'message': 'Format de fichier non autorisé. Utilisez JPG, PNG ou GIF.'}), 400
            
            # Vérification de la taille (Flask gère automatiquement MAX_CONTENT_LENGTH)
            photo.seek(0, 2)  # Aller à la fin du fichier
            file_size = photo.tell()
            photo.seek(0)  # Revenir au début
            
            if file_size > MAX_FILE_SIZE:
                return jsonify({'success': False, 'message': 'Le fichier est trop volumineux (max 5MB)'}), 400
            
            # Créer le dossier d'upload s'il n'existe pas
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profile_photos')
            os.makedirs(upload_folder, exist_ok=True)
            
            # Générer un nom de fichier unique
            filename = secure_filename(photo.filename)
            name, ext = os.path.splitext(filename)
            unique_filename = f"profile_{user_id}_{uuid.uuid4().hex[:8]}{ext}"
            
            # Sauvegarder le fichier
            filepath = os.path.join(upload_folder, unique_filename)
            photo.save(filepath)
            
            # Préparer le chemin pour la base de données
            photo_path = f'/static/uploads/profile_photos/{unique_filename}'
            updated_data['photo'] = photo_path
            modified_fields.append('photo de profil')
            
            # Marquer l'ancienne photo pour suppression
            if hasattr(user, 'photo') and user.photo and not user.photo.startswith('http'):
                old_photo_path = os.path.join(current_app.root_path, user.photo.lstrip('/'))

        # Vérifier qu'il y a au moins un champ modifié
        if not modified_fields:
            return jsonify({'success': False, 'message': 'Aucune modification détectée'}), 400

        # Appliquer les modifications
        for field, value in updated_data.items():
            setattr(user, field, value)
        
        # Mettre à jour la date de modification si elle existe
        if hasattr(user, 'updated_at'):
            user.updated_at = datetime.utcnow()

        # Sauvegarder en base de données
        db.session.commit()
        
        print(f"Utilisateur {user_id} mis à jour - Champs modifiés: {modified_fields}")

        # Supprimer l'ancienne photo après succès
        if old_photo_path and os.path.exists(old_photo_path):
            try:
                os.remove(old_photo_path)
                print(f"Ancienne photo supprimée: {old_photo_path}")
            except OSError as e:
                print(f"Impossible de supprimer l'ancienne photo: {e}")

        # Récupérer les données utilisateur mises à jour avec profil
        profil = Profil.query.get(user.profil_id) if user.profil_id else None
        permissions = get_user_permissions(user)

        # Préparer la réponse
        user_data = {
            'id': user.id,
            'nom': user.nom,
            'email': user.email,
            'photo': getattr(user, 'photo', None),
            'profil_id': user.profil_id,
            'profil_nom': profil.nom if profil else None,
            'created_at': user.created_at.isoformat() if hasattr(user, 'created_at') and user.created_at else None,
            'updated_at': user.updated_at.isoformat() if hasattr(user, 'updated_at') and user.updated_at else None
        }

        # Message de succès personnalisé
        success_message = f"{', '.join(modified_fields)} mis à jour avec succès"

        return jsonify({
            'success': True,
            'message': success_message,
            'user': user_data,
            'permissions': permissions,
            'modified_fields': modified_fields
        }), 200

    except Exception as e:
        # Rollback en cas d'erreur
        db.session.rollback()
        
        # Supprimer le fichier uploadé en cas d'erreur
        if 'photo' in locals() and 'filepath' in locals() and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        
        print(f"Erreur lors de la mise à jour utilisateur: {str(e)}")
        
        # Gestion des erreurs spécifiques
        if 'Duplicate entry' in str(e) or 'UNIQUE constraint failed' in str(e):
            return jsonify({'success': False, 'message': 'Cet email est déjà utilisé'}), 400
        
        return jsonify({
            'success': False, 
            'message': f'Erreur lors de la mise à jour: {str(e)}'
        }), 500

# ================================
# ROUTES DATASET - UPLOAD
# ================================

@user_bp.route('/datasets/upload', methods=['POST'])
def upload_dataset_csv():
    print("request.files keys:", request.files.keys())
    print("request.form:", request.form)
    
    # Vérification de la présence du fichier
    if 'file' not in request.files:
        print("Erreur : pas de fichier dans request.files")
        return jsonify({'error': 'Pas de fichier envoyé'}), 400
    
    file = request.files['file']
    status = request.form.get('status', 'original')
    user_email = request.form.get('user_email')
    
    print("Fichier reçu:", file.filename)
    print("User email:", user_email)
    
    # Vérification user_email
    if not user_email:
        print("Erreur : user_email manquant dans request.form")
        return jsonify({'error': 'user_email requis'}), 400
    
    # Vérification utilisateur existe
    user = User.query.filter_by(email=user_email).first()
    if not user:
        print("Erreur : utilisateur introuvable pour email:", user_email)
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    
    # Vérification nom de fichier
    if file.filename == '':
        print("Erreur : nom de fichier vide")
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    # Vérification type de fichier
    if not allowed_csv_file(file.filename):
        print("Erreur : type de fichier non autorisé:", file.filename)
        return jsonify({'error': 'Type de fichier non autorisé'}), 400
    
    print("Toutes les vérifications passées, traitement du fichier...")
    
    # Traitement du fichier
    try:
        filename = secure_filename(file.filename)
        base, ext = os.path.splitext(filename)
        unique_suffix = str(uuid.uuid4())[:8]
        unique_filename = f"{base}_{unique_suffix}{ext}"
        
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, unique_filename)
        
        print("Sauvegarde du fichier vers:", filepath)
        file.save(filepath)
        
        # Lecture du CSV
        print("Lecture du fichier CSV...")
        df = pd.read_csv(filepath)
        
        if df.empty:
            print("Erreur : fichier CSV vide")
            return jsonify({'error': 'Fichier CSV vide'}), 400
        
        print("CSV lu avec succès, nombre de lignes:", len(df))
        
        # Conversion en JSON
        contenu_json = df.to_dict(orient='records')
        
        # Création du dataset
        titre = os.path.splitext(unique_filename)[0]
        new_dataset = Dataset(
            titre=titre,
            owner_id=user.id,
            status=status,
            contenu=contenu_json
        )
        
        print("Ajout du dataset à la base de données...")
        db.session.add(new_dataset)
        db.session.commit()
        
        print("Dataset créé avec succès, ID:", new_dataset.id)
        return jsonify({
            'message': 'Fichier CSV uploadé avec succès', 
            'id': new_dataset.id
        }), 201
        
    except Exception as e:
        print("Erreur lors du traitement:", str(e))
        return jsonify({'error': f'Erreur lors du traitement : {str(e)}'}), 500

# ================================
# ROUTES DATASET - LISTING ET ACCÈS
# ================================

@user_bp.route('/datasets', methods=['GET'])
def get_datasets_with_field_access():
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404

    # Récupérer les types de champs visibles pour cet utilisateur
    profil = Profil.query.get(user.profil_id)
    visible_field_types = []
    
    if profil:
        rules = current_app.mongo_db['profils_rules'].find_one({'profil_nom': profil.nom})
        if not rules:
            rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': user.profil_id})
        
        if rules:
            visible_field_types = rules.get('types_champs_visibles', [])

    # Récupérer tous les datasets
    datasets = Dataset.query.join(User, Dataset.owner_id == User.id).all()

    result = []
    for d in datasets:
        is_owner = d.owner_id == user.id
        
        # Déterminer le type d'accès
        if is_owner:
            access_type = 'full'
            visual = 'full'
        elif visible_field_types:
            access_type = 'field_filtered'
            visual = 'partial'
        elif d.contenu_anonymized:
            access_type = 'anonymized'
            visual = 'limited'
        else:
            access_type = 'none'
            visual = 'none'
        
        result.append({
            'id': d.id,
            'titre': d.titre,
            'owner_name': d.owner.nom if d.owner else "Inconnu",
            'owner_email': d.owner.email if d.owner else "Inconnu",
            'status': d.status,
            'is_owner': is_owner,
            'visual': visual,
            'access_type': access_type,
            'can_anonymize': is_owner,
            'can_configure_fields': is_owner,
            'visible_field_types': visible_field_types if not is_owner else None,
            'has_anonymized_version': d.contenu_anonymized is not None
        })

    return jsonify({'datasets': result})

@user_bp.route('/datasets/summary', methods=['GET'])
def get_datasets_summary():
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404

    # Statistiques globales
    total_datasets = Dataset.query.count()
    user_datasets = Dataset.query.filter_by(owner_id=user.id).count()
    anonymized_datasets = Dataset.query.filter(Dataset.contenu_anonymized.isnot(None)).count()

    return jsonify({
        'summary': {
            'total_datasets': total_datasets,
            'user_owned_datasets': user_datasets,
            'anonymized_datasets': anonymized_datasets,
            'accessible_datasets': total_datasets  # Tous sont accessibles (mais avec restrictions)
        }
    })

# ================================
# ROUTES DATASET - CONTENU AVEC FILTRAGE
# ================================

@user_bp.route('/datasets/<int:dataset_id>/content', methods=['GET'])
def get_dataset_content_with_field_filtering(dataset_id):
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404

    dataset = Dataset.query.get_or_404(dataset_id)
    is_owner = dataset.owner_id == user.id

    # Récupérer les types de champs visibles pour cet utilisateur
    profil = Profil.query.get(user.profil_id)
    visible_field_types = []
    
    if profil:
        rules = current_app.mongo_db['profils_rules'].find_one({'profil_nom': profil.nom})
        if not rules:
            rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': user.profil_id})
        
        if rules:
            visible_field_types = rules.get('types_champs_visibles', [])

    print(f"Types de champs visibles pour {user_email}: {visible_field_types}")

    try:
        if is_owner:
            # PROPRIÉTAIRE : Accès complet au contenu original
            mode = 'full'
            
            if dataset.contenu:
                content_data = dataset.contenu
                limited_content = content_data[:20] if len(content_data) > 20 else content_data
                
                if limited_content and isinstance(limited_content[0], dict):
                    headers = list(limited_content[0].keys())
                    rows = [headers]
                    
                    for item in limited_content:
                        row = [str(item.get(key, '')) for key in headers]
                        rows.append(row)
                else:
                    rows = limited_content
            else:
                return jsonify({'error': 'Contenu non disponible pour ce dataset'}), 404
                
        else:
            # NON-PROPRIÉTAIRE : Filtrage selon les types de champs visibles
            mode = 'filtered_by_field_types'
            
            if not dataset.contenu:
                return jsonify({'error': 'Contenu non disponible pour ce dataset'}), 404
            
            # Appliquer le filtrage par types de champs
            if visible_field_types:
                # Filtrer le contenu selon les types de champs autorisés
                filtered_content = filter_content_by_field_types(
                    dataset.contenu, 
                    visible_field_types, 
                    dataset_id
                )
                
                limited_content = filtered_content[:20] if len(filtered_content) > 20 else filtered_content
                
                if limited_content and isinstance(limited_content[0], dict):
                    headers = list(limited_content[0].keys())
                    rows = [headers]
                    for item in limited_content:
                        row = [str(item.get(key, '')) for key in headers]
                        rows.append(row)
                else:
                    rows = limited_content
            else:
                # Aucun type de champ visible -> accès aux données anonymisées seulement
                if not dataset.contenu_anonymized:
                    return jsonify({
                        'error': 'Accès refusé',
                        'message': 'Aucun type de champ autorisé et pas de données anonymisées disponibles'
                    }), 403

                try:
                    anonymized_data = json.loads(dataset.contenu_anonymized) if isinstance(dataset.contenu_anonymized, str) else dataset.contenu_anonymized
                except (json.JSONDecodeError, TypeError):
                    return jsonify({'error': 'Erreur lors du parsing des données anonymisées'}), 500
                
                limited_content = anonymized_data[:20] if len(anonymized_data) > 20 else anonymized_data
                
                if limited_content and isinstance(limited_content[0], dict):
                    headers = list(limited_content[0].keys())
                    rows = [headers]
                    for item in limited_content:
                        row = [str(item.get(key, '')) for key in headers]
                        rows.append(row)
                else:
                    rows = limited_content

        return jsonify({
            'mode': mode,
            'content': rows,
            'is_owner': is_owner,
            'dataset_owner': dataset.owner.nom if dataset.owner else "Inconnu",
            'total_rows': len(dataset.contenu) if dataset.contenu else 0,
            'displayed_rows': len(rows) - 1 if rows else 0,
            'visible_field_types': visible_field_types,
            'access_type': 'owner' if is_owner else ('field_filtered' if visible_field_types else 'anonymized')
        })
        
    except Exception as e:
        print(f"Erreur lors de la récupération du contenu du dataset {dataset_id}: {str(e)}")
        return jsonify({'error': f'Erreur lors du chargement du contenu: {str(e)}'}), 500

@user_bp.route('/datasets/<int:dataset_id>/content/robust', methods=['GET'])
def get_dataset_content_robust(dataset_id):
    """
    Version robuste de get_dataset_content avec meilleure gestion d'erreurs
    """
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    try:
        user = User.query.filter_by(email=user_email).first()
        if not user:
            return jsonify({'error': 'Utilisateur introuvable'}), 404

        dataset = Dataset.query.get(dataset_id)
        if not dataset:
            return jsonify({'error': 'Dataset introuvable'}), 404

        is_owner = dataset.owner_id == user.id
        
        # Récupérer les types de champs visibles
        profil = Profil.query.get(user.profil_id)
        visible_field_types = []
        
        if profil:
            rules = current_app.mongo_db['profils_rules'].find_one({'profil_nom': profil.nom})
            if not rules:
                rules = current_app.mongo_db['profils_rules'].find_one({'profil_id': user.profil_id})
            
            if rules:
                visible_field_types = rules.get('types_champs_visibles', [])
        
        print(f"Récupération contenu dataset {dataset_id} pour utilisateur {user_email} (owner: {is_owner})")

        if is_owner:
            # Propriétaire - accès au contenu original
            mode = 'full'
            
            if not dataset.contenu:
                return jsonify({'error': 'Aucun contenu disponible pour ce dataset'}), 404
            
            try:
                # Convertir en format CSV-like
                rows = json_to_csv_format(dataset.contenu, limit=20)
                
                if not rows:
                    return jsonify({'error': 'Impossible de formater le contenu du dataset'}), 500
                
                print(f"Contenu original récupéré: {len(rows)} lignes")
                
            except Exception as e:
                print(f"Erreur lors du formatage du contenu original: {str(e)}")
                return jsonify({'error': 'Erreur lors du formatage des données'}), 500
                
        else:
            # Non-propriétaire - filtrage par type de champs ou accès anonymisé
            if visible_field_types:
                mode = 'field_filtered'
                
                if not dataset.contenu:
                    return jsonify({'error': 'Contenu non disponible pour ce dataset'}), 404
                
                try:
                    # Appliquer le filtrage par types de champs
                    filtered_content = filter_content_by_field_types(
                        dataset.contenu, 
                        visible_field_types, 
                        dataset_id
                    )
                    
                    # Convertir en format CSV-like
                    rows = json_to_csv_format(filtered_content, limit=20)
                    
                    if not rows:
                        return jsonify({'error': 'Aucune donnée visible avec vos permissions'}), 404
                    
                    print(f"Contenu filtré par types de champs récupéré: {len(rows)} lignes")
                    
                except Exception as e:
                    print(f"Erreur lors du filtrage par types de champs: {str(e)}")
                    return jsonify({'error': 'Erreur lors du filtrage des données'}), 500
            
            else:
                # Accès aux données anonymisées seulement
                mode = 'anonymized'
                
                if not dataset.contenu_anonymized:
                    return jsonify({
                        'error': 'Contenu non accessible',
                        'message': 'Aucun type de champ autorisé et pas de données anonymisées disponibles'
                    }), 403
                
                try:
                    # Parser les données anonymisées
                    if isinstance(dataset.contenu_anonymized, str):
                        anonymized_data = json.loads(dataset.contenu_anonymized)
                    else:
                        anonymized_data = dataset.contenu_anonymized
                    
                    # Convertir en format CSV-like
                    rows = json_to_csv_format(anonymized_data, limit=20)
                    
                    if not rows:
                        return jsonify({'error': 'Aucune donnée anonymisée disponible'}), 404
                    
                    print(f"Contenu anonymisé récupéré: {len(rows)} lignes")
                    
                except json.JSONDecodeError as e:
                    print(f"Erreur JSON dans les données anonymisées: {str(e)}")
                    return jsonify({'error': 'Données anonymisées corrompues'}), 500
                except Exception as e:
                    print(f"Erreur lors du traitement des données anonymisées: {str(e)}")
                    return jsonify({'error': 'Erreur lors du traitement des données anonymisées'}), 500

        return jsonify({
            'mode': mode,
            'content': rows,
            'is_owner': is_owner,
            'dataset_owner': dataset.owner.nom if dataset.owner else "Inconnu",
            'dataset_title': dataset.titre,
            'total_rows': len(dataset.contenu) if dataset.contenu else 0,
            'displayed_rows': max(0, len(rows) - 1) if rows else 0,  # -1 pour exclure les headers
            'has_more': len(dataset.contenu) > 20 if dataset.contenu else False,
            'visible_field_types': visible_field_types,
            'access_type': mode
        })
        
    except Exception as e:
        print(f"Erreur générale lors de la récupération du dataset {dataset_id}: {str(e)}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500

# ================================
# ROUTES CONFIGURATION DES CHAMPS
# ================================

@user_bp.route('/datasets/<int:dataset_id>/fields-config', methods=['GET'])
def get_dataset_fields_config(dataset_id):
    """
    Récupère la configuration des types de champs pour un dataset
    """
    try:
        dataset = Dataset.query.get_or_404(dataset_id)
        
        # Récupérer la configuration des champs
        champs_config = ChampSensible.query.filter_by(dataset_id=dataset_id).all()
        
        fields_info = []
        for champ in champs_config:
            fields_info.append({
                'nom': champ.nom,
                'type_champ': champ.type_champ,
                'technique_associee': champ.technique_associee,
                'est_visible': champ.est_visible
            })
        
        # Si aucune configuration, analyser les champs du dataset
        if not fields_info and dataset.contenu:
            if isinstance(dataset.contenu[0], dict):
                headers = list(dataset.contenu[0].keys())
                for header in headers:
                    fields_info.append({
                        'nom': header,
                        'type_champ': 'Champ non sensible',  # Par défaut
                        'technique_associee': None,
                        'est_visible': True
                    })
        
        return jsonify({
            'dataset_id': dataset_id,
            'dataset_title': dataset.titre,
            'fields_config': fields_info
        })
        
    except Exception as e:
        print(f"Erreur lors de la récupération de la config des champs: {str(e)}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

@user_bp.route('/datasets/<int:dataset_id>/configure-fields', methods=['POST'])
def configure_dataset_fields(dataset_id):
    """
    Configure les types de champs pour un dataset (propriétaire seulement)
    """
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404

    dataset = Dataset.query.get_or_404(dataset_id)
    
    # Vérifier que l'utilisateur est le propriétaire
    if dataset.owner_id != user.id:
        return jsonify({
            'error': 'Accès refusé', 
            'message': 'Seul le propriétaire peut configurer les types de champs'
        }), 403

    data = request.get_json()
    if not data or 'fields_config' not in data:
        return jsonify({'error': 'Configuration des champs manquante'}), 400

    try:
        # Supprimer l'ancienne configuration
        ChampSensible.query.filter_by(dataset_id=dataset_id).delete()

        # Ajouter la nouvelle configuration
        for field_config in data['fields_config']:
            champ = ChampSensible(
                dataset_id=dataset_id,
                nom=field_config['nom'],
                type_champ=field_config.get('type_champ', 'Champ non sensible'),
                technique_associee=field_config.get('technique_associee'),
                est_visible=field_config.get('est_visible', True)
            )
            db.session.add(champ)

        db.session.commit()

        return jsonify({
            'message': 'Configuration des champs mise à jour avec succès',
            'dataset_id': dataset_id
        })

    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la configuration des champs: {str(e)}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

@user_bp.route('/field-types', methods=['GET'])
def get_available_field_types():
    """
    Retourne la liste des types de champs disponibles dans le système
    """
    try:
        # Récupérer tous les types de champs distincts depuis ProfilsTypesChamps
        types_champs = db.session.query(ProfilsTypesChamps.type_champ).distinct().all()
        
        field_types = [type_champ[0] for type_champ in types_champs]
        
        # Ajouter des types par défaut s'ils n'existent pas
        default_types = ['Champ non sensible', 'Identifiant direct', 'Identifiant indirect', 'Données sensibles']
        for default_type in default_types:
            if default_type not in field_types:
                field_types.append(default_type)
        
        return jsonify({
            'field_types': sorted(field_types)
        })
        
    except Exception as e:
        print(f"Erreur lors de la récupération des types de champs: {str(e)}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

# ================================
# ROUTES ANONYMISATION
# ================================

@user_bp.route('/datasets/<int:dataset_id>/anonymize', methods=['POST'])
def anonymize_dataset(dataset_id):
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Paramètre user_email manquant'}), 400

    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404

    dataset = Dataset.query.get_or_404(dataset_id)
    
    # VÉRIFIER QUE L'UTILISATEUR EST LE PROPRIÉTAIRE
    if dataset.owner_id != user.id:
        return jsonify({
            'error': 'Accès refusé', 
            'message': 'Seul le propriétaire peut anonymiser ce dataset'
        }), 403

    # TODO: Implémenter la logique d'anonymisation
    return jsonify({'message': 'Fonctionnalité d\'anonymisation à implémenter'}), 501

@user_bp.route('/api/datasets/<int:id>', methods=['GET'])
def get_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    # Supposons que Dataset a un champ 'fields' (liste de noms de colonnes)
    # et un champ 'preview' (stocké en JSON, ou autre)
    try:
        fields = json.loads(dataset.fields) if hasattr(dataset, 'fields') and dataset.fields else []
        preview = json.loads(dataset.preview) if hasattr(dataset, 'preview') and dataset.preview else []
    except Exception:
        fields = []
        preview = []

    return jsonify({
        'id': dataset.id,
        'titre': dataset.titre,
        'fields': fields,
        'preview': preview
    })

@user_bp.route('/api/datasets/<int:id>/champs_sensibles', methods=['POST'])
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

@user_bp.route('/api/datasets/<int:id>/anonymize', methods=['POST'])
def save_anonymized_dataset(id):
    """Sauvegarde le contenu anonymisé d'un dataset"""
    try:
        # Vérifier que le dataset existe
        dataset = Dataset.query.get(id)
        if not dataset:
            return jsonify({'error': 'Dataset non trouvé'}), 404

        # Récupérer les données JSON
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON manquantes ou mal formées'}), 400

        # Valider la présence des données anonymisées
        anonymized_data = data.get('anonymizedData')
        if anonymized_data is None:
            return jsonify({'error': 'Données anonymisées manquantes'}), 400

        # Valider que les données sont dans le bon format [headers, ...rows]
        if not isinstance(anonymized_data, list) or len(anonymized_data) < 1:
            return jsonify({'error': 'Format des données anonymisées invalide'}), 400

        # Récupérer la configuration (optionnelle)
        configuration = data.get('configuration', {})
        timestamp = data.get('timestamp', datetime.utcnow().isoformat())

        try:
            # Sérialiser les données anonymisées en JSON
            json_str = json.dumps(anonymized_data, ensure_ascii=False, indent=2)
            
            # Sauvegarder dans la base de données
            dataset.contenu_anonymized = json_str
            dataset.status = "completed"
            dataset.date_modification = datetime.utcnow()
            
            # Optionnel: sauvegarder aussi la configuration
            if configuration:
                config_str = json.dumps(configuration, ensure_ascii=False, indent=2)
                # Vous pouvez ajouter un champ configuration dans votre modèle Dataset
                # dataset.configuration_anonymisation = config_str
            
            db.session.commit()
            
            # Log pour debug
            print(f"Dataset {id} anonymisé sauvegardé avec succès")
            print(f"Taille des données: {len(anonymized_data)} lignes")
            print(f"Configuration: {configuration}")
            
            return jsonify({
                'message': 'Dataset anonymisé enregistré avec succès',
                'dataset_id': id,
                'rows_count': len(anonymized_data) - 1,  # -1 pour exclure l'en-tête
                'timestamp': timestamp
            }), 200
            
        except (TypeError, ValueError) as e:
            return jsonify({'error': f'Erreur de sérialisation JSON : {str(e)}'}), 400
            
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la sauvegarde du dataset anonymisé {id}: {str(e)}")
        return jsonify({'error': f'Erreur lors de l\'enregistrement : {str(e)}'}), 500

@user_bp.route('/api/datasets/<int:id>/anonymized', methods=['GET'])
def get_anonymized_dataset(id):
    """Récupère le contenu anonymisé d'un dataset"""
    try:
        dataset = Dataset.query.get(id)
        if not dataset:
            return jsonify({'error': 'Dataset non trouvé'}), 404

        if not dataset.contenu_anonymized:
            return jsonify({'error': 'Aucun contenu anonymisé disponible'}), 404

        try:
            # Désérialiser le contenu anonymisé
            anonymized_data = json.loads(dataset.contenu_anonymized)
            
            return jsonify({
                'dataset_id': id,
                'titre': dataset.titre,
                'anonymized_data': anonymized_data,
                'status': dataset.status,
                'date_modification': dataset.date_modification.isoformat() if dataset.date_modification else None
            }), 200
            
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Erreur de décodage JSON : {str(e)}'}), 500
            
    except Exception as e:
        print(f"Erreur lors de la récupération du dataset anonymisé {id}: {str(e)}")
        return jsonify({'error': f'Erreur lors de la récupération : {str(e)}'}), 500

@user_bp.route('/api/datasets/<int:id>/anonymized/download', methods=['GET'])
def download_anonymized_csv(id):
    """Télécharge le dataset anonymisé au format CSV"""
    try:
        dataset = Dataset.query.get(id)
        if not dataset:
            return jsonify({'error': 'Dataset non trouvé'}), 404

        if not dataset.contenu_anonymized:
            return jsonify({'error': 'Aucun contenu anonymisé disponible'}), 404

        try:
            # Désérialiser le contenu anonymisé
            anonymized_data = json.loads(dataset.contenu_anonymized)
            
            # Convertir en CSV
            csv_content = []
            for row in anonymized_data:
                # Échapper les guillemets et encadrer chaque cellule
                escaped_row = ['"' + str(cell).replace('"', '""') + '"' for cell in row]


                csv_content.append(','.join(escaped_row))
            
            csv_string = '\n'.join(csv_content)
            
            # Créer la réponse avec les en-têtes appropriés
            response = Response(
                csv_string,
                mimetype='text/csv',
                headers={
                    'Content-Disposition': f'attachment; filename=anonymized_{dataset.titre}_{id}.csv'
                }
            )
            
            return response
            
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Erreur de décodage JSON : {str(e)}'}), 500
            
    except Exception as e:
        print(f"Erreur lors du téléchargement du dataset anonymisé {id}: {str(e)}")
        return jsonify({'error': f'Erreur lors du téléchargement : {str(e)}'}), 500

# ================================
# ROUTES DASHBOARD
# ================================

@user_bp.route('/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    try:
        user_email = request.args.get('user', None)
        if not user_email:
            return jsonify({'error': 'Paramètre user manquant'}), 400

        user = User.query.filter_by(email=user_email).first()
        if not user:
            return jsonify({'error': 'Utilisateur introuvable'}), 404

        total_datasets = Dataset.query.count()
        user_datasets = Dataset.query.filter_by(owner_id=user.id).count()
        anonymized_datasets = Dataset.query.filter(Dataset.contenu_anonymized.isnot(None)).count()
        
        # Récupérer les permissions de l'utilisateur
        permissions = get_user_permissions(user)
        
        stats_data = {
            'totalDatasets': total_datasets,
            'userDatasets': user_datasets,
            'anonymizedDatasets': anonymized_datasets,
            'accessibleDatasets': total_datasets,  # Tous sont accessibles avec restrictions
            'userPermissions': permissions
        }

        return jsonify({'success': True, 'data': stats_data}), 200

    except Exception as e:
        current_app.logger.error(f"Erreur stats dashboard: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}',
            'data': {
                'totalDatasets': 0,
                'userDatasets': 0,
                'anonymizedDatasets': 0,
                'accessibleDatasets': 0
            }
        }), 200
##########################################################




