import os
import base64
import requests

USE_VAULT = os.getenv("USE_VAULT", "false").lower() == "true"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
VAULT_KEY_NAME = os.getenv("VAULT_KEY_NAME", "wallet-key")


def encrypt_wallet_secret(secret: str) -> str:
    if not secret:
        raise ValueError("Secret vide")

    # Fallback DEV / Render sans Vault
    if not USE_VAULT:
        return secret

    plaintext_b64 = base64.b64encode(secret.encode()).decode()

    res = requests.post(
        f"{VAULT_ADDR}/v1/transit/encrypt/{VAULT_KEY_NAME}",
        headers={"X-Vault-Token": VAULT_TOKEN},
        json={"plaintext": plaintext_b64},
        timeout=5,
    )
    res.raise_for_status()

    data = res.json()
    ciphertext = data.get("data", {}).get("ciphertext")
    if not ciphertext:
        raise RuntimeError("Vault encrypt: ciphertext manquant")

    return ciphertext


def decrypt_wallet_secret(ciphertext: str) -> str:
    if not ciphertext:
        raise ValueError("Ciphertext vide")

    # Fallback DEV / Render sans Vault
    if not USE_VAULT:
        return ciphertext

    res = requests.post(
        f"{VAULT_ADDR}/v1/transit/decrypt/{VAULT_KEY_NAME}",
        headers={"X-Vault-Token": VAULT_TOKEN},
        json={"ciphertext": ciphertext},
        timeout=5,
    )
    res.raise_for_status()

    data = res.json()
    plaintext_b64 = data.get("data", {}).get("plaintext")
    if not plaintext_b64:
        raise RuntimeError("Vault decrypt: plaintext manquant")

    return base64.b64decode(plaintext_b64).decode()


# Compatibilité avec ton code existant
def vault_encrypt(secret: str) -> str:
    return encrypt_wallet_secret(secret)


def vault_decrypt(ciphertext: str) -> str:
    return decrypt_wallet_secret(ciphertext)