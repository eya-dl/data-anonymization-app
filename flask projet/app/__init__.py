from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from urllib.parse import urlparse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from app.config import Config
from app.models import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Init base de données SQLAlchemy
    db.init_app(app)

    # Autoriser les requêtes Cross-Origin
    CORS(app)

    # Connexion MongoDB sécurisée
    try:
        mongo_uri = app.config.get('MONGO_URI', 'mongodb://localhost:27017/anonymization_rules')
        mongo_client = MongoClient(mongo_uri)
        mongo_client.admin.command('ping')  # Test de connexion
        parsed_uri = urlparse(mongo_uri)
        db_name = parsed_uri.path.lstrip('/') or 'anonymization_rules'
        app.mongo_db = mongo_client[db_name]
        app.logger.info(f"Connexion MongoDB réussie à la base : {db_name}")
    except ConnectionFailure:
        app.logger.error("Impossible de se connecter à MongoDB")
        app.mongo_db = None

    # Import et enregistrement des Blueprints
    from app.routes import main as main_blueprint
    from app.routes_user import user_bp
    from app.ai_routes import ai_bp


    app.register_blueprint(main_blueprint)
    app.register_blueprint(user_bp)
    app.register_blueprint(ai_bp)

    return app
