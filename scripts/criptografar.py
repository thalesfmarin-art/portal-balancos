"""Criptografa os dados do site com a senha do segredo SITE_PASSWORD (AES-256-GCM + PBKDF2-SHA256).

Sem a senha, o site publicado não mostra nenhum número: os JSONs viram arquivos .bin ilegíveis.
Se o segredo não estiver configurado, os dados são apagados antes de publicar (nada fica exposto).
"""
import glob
import json
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "site", "data")
SAL = b"portal-balancos/thalesfmarin-art/v1"  # precisa ser igual ao do app.js
ITER = 600_000


def main():
    senha = os.environ.get("SITE_PASSWORD", "").strip()
    arquivos = glob.glob(os.path.join(DATA, "**", "*.json"), recursive=True)
    if not senha:
        for f in arquivos:
            os.remove(f)
        json.dump({"configurado": False}, open(os.path.join(DATA, "chave.json"), "w"))
        print("AVISO: segredo SITE_PASSWORD não configurado; dados não publicados.")
        return
    chave = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SAL, iterations=ITER).derive(senha.encode())
    aes = AESGCM(chave)
    for f in arquivos:
        iv = secrets.token_bytes(12)
        with open(f, "rb") as fh:
            dados = fh.read()
        with open(f[:-5] + ".bin", "wb") as fh:
            fh.write(iv + aes.encrypt(iv, dados, None))
        os.remove(f)
    json.dump({"configurado": True, "iter": ITER}, open(os.path.join(DATA, "chave.json"), "w"))
    print(f"{len(arquivos)} arquivos criptografados.")


if __name__ == "__main__":
    main()
