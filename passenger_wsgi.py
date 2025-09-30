import sys, os

# Ajouter le dossier courant au chemin Python
sys.path.insert(0, os.path.dirname(__file__))

# Importer l'application Flask
from app import app as application
