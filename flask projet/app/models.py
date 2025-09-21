from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()  # 👈 On définit db ici une seule fois

# Table de liaison Dataset <-> Profil
datasets_profils = db.Table(
    'datasets_profils',
    db.Column('dataset_id', db.Integer, db.ForeignKey('datasets.id'), primary_key=True),
    db.Column('profil_id', db.Integer, db.ForeignKey('profil.id'), primary_key=True)
)

# Table de liaison Profil <-> Action
profils_actions = db.Table(
    'profils_actions',
    db.Column('profil_id', db.Integer, db.ForeignKey('profil.id'), primary_key=True),
    db.Column('action_id', db.Integer, db.ForeignKey('actions.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    mot_de_passe = db.Column(db.String, nullable=False)
    profil_id = db.Column(db.Integer, db.ForeignKey('profil.id'), nullable=True)
    
    # Relation vers Dataset (un utilisateur peut avoir plusieurs datasets)
    datasets = db.relationship('Dataset', back_populates='owner', foreign_keys='Dataset.owner_id')

    def to_dict(self):
        return {
            "id": self.id,
            "nom": self.nom,
            "email": self.email,
            "profil_id": self.profil_id,
            "profil_nom": self.profil.nom if self.profil else None,
            "datasets_count": len(self.datasets)
        }

class Dataset(db.Model):
    __tablename__ = 'datasets'
    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50))
    contenu = db.Column(db.JSON, nullable=False)
    contenu_anonymized = db.Column(db.JSON)
    
    
    # Clé étrangère vers User
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    owner = db.relationship('User', back_populates='datasets', foreign_keys=[owner_id])
    
    # Relation many-to-many existante avec Profil
    profils = db.relationship('Profil', secondary=datasets_profils, back_populates='datasets')

    def to_dict(self):
        return {
            "id": self.id,
            "titre": self.titre,
            "date_creation": self.date_creation.isoformat(),
            "status": self.status,
            "owner_id": self.owner_id,
            "owner_name": self.owner.nom if self.owner else None,
            "profils": [p.nom for p in self.profils]
        }
class Profil(db.Model):
    __tablename__ = 'profil'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(50), unique=True, nullable=False)

    users = db.relationship('User', backref='profil', lazy=True)
    datasets = db.relationship('Dataset', secondary=datasets_profils, back_populates='profils')
    actions = db.relationship('Action', secondary=profils_actions, backref=db.backref('profils', lazy='dynamic'))
    types_champs = db.relationship('ProfilsTypesChamps', back_populates='profil', cascade='all, delete-orphan')

class Action(db.Model):
    __tablename__ = 'actions'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), unique=True, nullable=False)

class ChampSensible(db.Model):
    __tablename__ = 'champs_sensibles'

    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False)
    nom = db.Column(db.Text, nullable=False)
    technique_associee = db.Column(db.Text)
    est_visible = db.Column(db.Boolean, default=False)
    type_champ = db.Column(db.String(50))

    dataset = db.relationship('Dataset', backref=db.backref('champs_sensibles', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('dataset_id', 'nom', name='unique_champ_per_dataset'),
    )

class ProfilsTypesChamps(db.Model):
    __tablename__ = 'profils_types_champs'
    id = db.Column(db.Integer, primary_key=True)
    profil_id = db.Column(db.Integer, db.ForeignKey('profil.id', ondelete='CASCADE'), nullable=False)
    type_champ = db.Column(db.String(50), nullable=False)

    profil = db.relationship('Profil', back_populates='types_champs')
