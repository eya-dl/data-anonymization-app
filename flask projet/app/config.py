import os

class Config:
    # Connexion PostgreSQL
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:1234@localhost/anonymization_app"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    UPLOAD_FOLDER_ANONYMIZED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads_anonymized')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # limite taille upload 16 Mo
    
    MONGO_URI = "mongodb://localhost:27017/anonymization_app_mongo"
    

