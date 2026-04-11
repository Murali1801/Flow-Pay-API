import os

import firebase_admin
from firebase_admin import credentials, firestore

from app.config import settings


def get_firestore():
    if firebase_admin._apps:
        return firestore.client()
    if settings.firebase_service_account_json:
        import json
        try:
            cred_dict = json.loads(settings.firebase_service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            raise RuntimeError(f"Failed to load firebase_service_account_json: {e}")

    path = settings.firebase_credentials_path.strip()
    if not path or not os.path.isfile(path):
        raise RuntimeError(
            "Set FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_CREDENTIALS_PATH in backend/.env for Firebase credentials. "
            "Firebase Console → Project settings → Service accounts → Generate new private key."
        )
    cred = credentials.Certificate(path)
    firebase_admin.initialize_app(cred)
    return firestore.client()
