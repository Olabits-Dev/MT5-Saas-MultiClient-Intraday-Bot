import json
from cryptography.fernet import Fernet

# IMPORTANT: Use the SAME key you used when creating clients.enc
KEY = b'fCnx9bRy3Yq3NM98sG5FM7WqFRjoRySmlU8kPmfcs8I='

def load_clients(filename):
    with open(filename, "rb") as f:
        encrypted = f.read()

    fernet = Fernet(KEY)
    decrypted = fernet.decrypt(encrypted)

    return json.loads(decrypted.decode())


def save_clients(filename, clients):
    data = json.dumps(clients, indent=4).encode()

    fernet = Fernet(KEY)
    encrypted = fernet.encrypt(data)

    with open(filename, "wb") as f:
        f.write(encrypted)
