from cryptography.fernet import Fernet

# IMPORTANT: paste the SAME key from your .env here
key = b"fCnx9bRy3Yq3NM98sG5FM7WqFRjoRySmlU8kPmfcs8I="


fernet = Fernet(key)

# read json
with open("clients.json", "rb") as f:
    data = f.read() 

# encrypt
encrypted = fernet.encrypt(data)

# save encrypted file
with open("clients.enc", "wb") as f:
    f.write(encrypted)

print("✅ clients.enc created successfully!")
