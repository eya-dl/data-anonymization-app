from flask import Blueprint, jsonify, request, current_app, send_from_directory
from werkzeug.utils import secure_filename
from .models import User, Dataset, Profil, Action , ProfilsTypesChamps , ChampSensible
from . import db
import os
import json
from flask import Response


main = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main.route('/')
def home():
    return "API Flask fonctionne !"

# --- USERS ---

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
    if 'profil_id' in data:
        user.profil_id = data['profil_id']

    try:
        db.session.commit()
        return jsonify({'message': 'Utilisateur mis à jour avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la mise à jour : {str(e)}'}), 500

# --- DATASETS ---

@main.route('/api/datasets', methods=['GET'])
def get_datasets():
    datasets = Dataset.query.all()
    return jsonify([
        {
            "id": d.id,
            "titre": d.titre,
            "date_creation": d.date_creation.isoformat() if d.date_creation else None,
            "data_owner": d.data_owner,
            "status": d.status
        }
        for d in datasets
    ])

@main.route('/api/datasets', methods=['POST'])
def create_dataset():
    data = request.get_json()
    titre = data.get('titre')
    data_owner = data.get('data_owner')
    status = data.get('status')

    if not titre:
        return jsonify({'error': 'Le champ titre est requis'}), 400

    new_dataset = Dataset(
        titre=titre,
        data_owner=data_owner,
        status=status
    )
    db.session.add(new_dataset)
    db.session.commit()

    return jsonify({'message': 'Dataset ajouté avec succès', 'id': new_dataset.id}), 201

@main.route('/api/datasets/upload', methods=['POST'])
def upload_dataset_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'Pas de fichier envoyé'}), 400

    file = request.files['file']
    data_owner = request.form.get('data_owner')
    status = request.form.get('status')

    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        titre = os.path.splitext(filename)[0]
        new_dataset = Dataset(
            titre=titre,
            data_owner=data_owner,
            status=status
        )
        db.session.add(new_dataset)
        db.session.commit()

        return jsonify({'message': 'Fichier CSV uploadé et dataset créé', 'id': new_dataset.id}), 201

    return jsonify({'error': 'Type de fichier non autorisé'}), 400

@main.route('/api/datasets/<int:id>', methods=['GET'])
def get_dataset_info(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    filename = f"{dataset.titre}.csv"
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    filepath = os.path.join(upload_folder, filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier CSV introuvable'}), 404

    try:
        import pandas as pd
        df = pd.read_csv(filepath)
        fields = df.columns.tolist()
        preview = df.head(5).to_dict(orient='records')
        return jsonify({
            'fields': fields,
            'preview': preview
        })
    except Exception as e:
        return jsonify({'error': f'Erreur lors de la lecture du fichier : {str(e)}'}), 500

@main.route('/api/datasets/<int:id>', methods=['PUT'])
def update_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    for field in ['titre', 'data_owner', 'status']:
        if field in data:
            setattr(dataset, field, data[field])

    try:
        db.session.commit()
        return jsonify({'message': 'Dataset mis à jour avec succès'})
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur lors de la mise à jour'}), 500

@main.route('/api/datasets/<int:id>', methods=['DELETE'])
def delete_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    try:
        db.session.delete(dataset)
        db.session.commit()
        return jsonify({'message': 'Dataset supprimé avec succès'})
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur lors de la suppression'}), 500

@main.route('/api/datasets/<int:id>/download', methods=['GET'])
def download_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    filename = secure_filename(f"{dataset.titre}.csv")
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    filepath = os.path.join(upload_folder, filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier CSV introuvable'}), 404

    return send_from_directory(upload_folder, filename, as_attachment=True)

# --- ROUTE ANONYMISATION ---

@main.route('/api/datasets/<int:id>/anonymize', methods=['POST'])
def save_anonymized_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    anonymized_data = data.get('anonymizedData')
    if anonymized_data is None:
        return jsonify({'error': 'Données anonymisées manquantes'}), 400

    try:
        dataset.contenu_anonymized = json.dumps(anonymized_data)
        dataset.status = "completed"
        db.session.commit()
        return jsonify({'message': 'Dataset anonymisé enregistré avec succès'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de l’enregistrement : {str(e)}'}), 500

@main.route('/api/datasets/<int:id>/anonymized', methods=['GET'])
def get_anonymized_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404
    if not dataset.contenu_anonymized:
        return jsonify({'error': 'Aucune version anonymisée disponible'}), 404

    try:
        anonymized_data = json.loads(dataset.contenu_anonymized)
        return jsonify({'anonymized': anonymized_data})
    except Exception as e:
        return jsonify({'error': f'Erreur lors du chargement des données anonymisées : {str(e)}'}), 500




@main.route('/api/datasets/<int:id>/profils', methods=['POST'])
def associate_profils_to_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    profils_ids = data.get('profils_ids', [])

    if not isinstance(profils_ids, list):
        return jsonify({'error': 'La liste des profils est invalide'}), 400

    profils = Profil.query.filter(Profil.id.in_(profils_ids)).all()

    if not profils:
        return jsonify({'error': 'Aucun profil trouvé pour les IDs fournis'}), 400

    try:
        dataset.profils = profils  # remplace les associations précédentes
        db.session.commit()
        return jsonify({'message': 'Profils associés au dataset avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de l’association : {str(e)}'}), 500


# --- Upload / Download anonymized CSV files (optionnel) ---

@main.route('/api/datasets/<int:id>/upload_anonymized', methods=['POST'])
def upload_anonymized_csv(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    if 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Aucun fichier sélectionné'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'Type de fichier non autorisé'}), 400

        filename = secure_filename(file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER_ANONYMIZED', 'uploads_anonymized')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        dataset.status = "completed"
        db.session.commit()

        return jsonify({'message': 'Fichier CSV anonymisé uploadé avec succès', 'filename': filename}), 200

    data = request.get_json()
    contenu_anonymized = data.get('contenu_anonymized')
    if contenu_anonymized:
        upload_folder = current_app.config.get('UPLOAD_FOLDER_ANONYMIZED', 'uploads_anonymized')
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"{dataset.titre}_anonymized.csv"
        filepath = os.path.join(upload_folder, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(contenu_anonymized)
            dataset.status = "completed"
            db.session.commit()
            return jsonify({'message': 'Fichier CSV anonymisé sauvegardé avec succès', 'filename': filename}), 200
        except Exception as e:
            return jsonify({'error': f'Erreur lors de la sauvegarde du fichier : {str(e)}'}), 500

    return jsonify({'error': 'Pas de fichier ni contenu anonymisé fourni'}), 400


@main.route('/api/datasets/<int:id>/download_anonymized', methods=['GET'])
def download_anonymized_dataset(id):
    dataset = Dataset.query.get(id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    if not dataset.contenu_anonymized:
        return jsonify({'error': 'Aucune version anonymisée disponible'}), 404

    csv_content = dataset.contenu_anonymized
    filename = f"{dataset.titre}_anonymized.csv"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )

# --- PROFILS ET ACTIONS ---

@main.route('/api/profils', methods=['GET'])
def get_profils():
    profils = Profil.query.all()
    return jsonify([{'id': p.id, 'nom': p.nom} for p in profils])

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
    return jsonify({'id': p.id, 'nom': p.nom}), 201

@main.route('/api/profils/<int:profil_id>/actions', methods=['GET'])
def get_profil_actions(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    actions = [{'id': a.id, 'nom': a.nom} for a in profil.actions]
    return jsonify(actions)

@main.route('/api/profils/<int:profil_id>/actions', methods=['POST'])
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

@main.route('/api/profils/<int:profil_id>', methods=['DELETE'])
def delete_profil(profil_id):
    profil = Profil.query.get(profil_id)
    if not profil:
        return jsonify({'error': 'Profil non trouvé'}), 404

    if profil.users and len(profil.users) > 0:
        return jsonify({'error': 'Impossible de supprimer ce profil car des utilisateurs y sont associés'}), 400

    try:
        db.session.delete(profil)
        db.session.commit()
        return jsonify({'message': 'Profil supprimé avec succès'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la suppression : {str(e)}'}), 500

@main.route('/api/profils/<int:profil_id>/types_champs', methods=['GET'])
def get_types_champs_for_profil(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    types_champs = [tc.type_champ for tc in profil.types_champs]
    return jsonify({'types_champs': types_champs})
@main.route('/api/profils/<int:profil_id>/types_champs', methods=['POST'])
def set_types_champs_for_profil(profil_id):
    profil = Profil.query.get_or_404(profil_id)
    data = request.get_json()
    types_champs = data.get('types_champs')

    if not isinstance(types_champs, list):
        return jsonify({'error': 'La liste des types de champs est invalide'}), 400

    try:
        # Supprime les associations existantes
        ProfilsTypesChamps.query.filter_by(profil_id=profil_id).delete()

        # Ajoute les nouvelles associations
        for type_champ in types_champs:
            ptc = ProfilsTypesChamps(profil_id=profil_id, type_champ=type_champ)
            db.session.add(ptc)

        db.session.commit()
        return jsonify({'message': 'Types de champs mis à jour avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la mise à jour : {str(e)}'}), 500
@main.route('/api/profils/<int:profil_id>/types_champs/<string:type_champ>', methods=['DELETE'])
def delete_type_champ_for_profil(profil_id, type_champ):
    ptc = ProfilsTypesChamps.query.filter_by(profil_id=profil_id, type_champ=type_champ).first()
    if not ptc:
        return jsonify({'error': 'Association non trouvée'}), 404
    try:
        db.session.delete(ptc)
        db.session.commit()
        return jsonify({'message': 'Type de champ supprimé du profil avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la suppression : {str(e)}'}), 500

@main.route('/api/datasets/<int:dataset_id>/champs_sensibles', methods=['POST'])
def save_champs_sensibles(dataset_id):
    dataset = Dataset.query.get(dataset_id)
    if not dataset:
        return jsonify({'error': 'Dataset non trouvé'}), 404

    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({'error': 'Données invalides, un tableau JSON est attendu'}), 400

    try:
        # Récupérer la liste des noms des champs reçus
        noms_reçus = [champ.get('nom') for champ in data if 'nom' in champ]
        if not all(noms_reçus):
            return jsonify({'error': 'Chaque champ doit avoir un nom'}), 400

        # Charger en base les champs sensibles existants du dataset
        champs_existants = ChampSensible.query.filter_by(dataset_id=dataset_id).all()
        dict_champs_existants = {c.nom: c for c in champs_existants}

        # Supprimer les champs qui ne sont plus dans la liste reçue
        for champ in champs_existants:
            if champ.nom not in noms_reçus:
                db.session.delete(champ)

        # Ajouter ou mettre à jour les champs reçus
        for champ_data in data:
            nom = champ_data.get('nom')
            type_champ = champ_data.get('type_champ', None)
            technique_associee = champ_data.get('technique_associee', None)
            est_visible = champ_data.get('est_visible', False)

            if nom in dict_champs_existants:
                # Mise à jour
                champ = dict_champs_existants[nom]
                champ.type_champ = type_champ
                champ.technique_associee = technique_associee
                champ.est_visible = est_visible
            else:
                # Création
                champ = ChampSensible(
                    dataset_id=dataset_id,
                    nom=nom,
                    type_champ=type_champ,
                    technique_associee=technique_associee,
                    est_visible=est_visible
                )
                db.session.add(champ)

        db.session.commit()
        return jsonify({'message': 'Champs sensibles sauvegardés avec succès'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la sauvegarde : {str(e)}'}), 500
