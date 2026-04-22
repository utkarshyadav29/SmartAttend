import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'smartattend-dev-secret-2024')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///smartattend.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
