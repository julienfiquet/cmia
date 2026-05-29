import json
import hashlib
import time
from ecdsa import VerifyingKey, SECP256k1, BadSignatureError
from ecdsa.util import sigdecode_string

# Variables globales ou constantes par défaut (gérées par l'environnement plus tard)
MAX_TARGET = 2**240
NETWORK_ID = "cmia-mainnet-v1"
TX_VERSION = 1
INITIAL_REWARD = 25
HALVING_EVERY_BLOCKS = 5000
DIFFICULTY_ADJUST_EVERY_BLOCKS = 5
TARGET_BLOCK_TIME_SECONDS = 30
MIN_DIFFICULTY = 1

def now_ts() -> int:
    return int(time.time())

def tx_hash_of(sender_pub: str, recipient_pub: str, amount: int, signature: str, created_at: int) -> str:
    raw = f"{sender_pub}|{recipient_pub}|{amount}|{signature}|{created_at}"
    return hashlib.sha256(raw.encode()).hexdigest()

def block_hash_of(block_data: dict) -> str:
    candidate = block_data.copy()
    # On retire le hash s'il est présent pour recalculer proprement
    candidate.pop("hash", None)
    raw = json.dumps(candidate, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def strict_tx_hash_of(sender_pub: str, inputs: list[dict], outputs: list[dict], signature: str, created_at: int) -> str:
    raw = json.dumps(
        {
            "sender_pub": sender_pub,
            "inputs": inputs,
            "outputs": outputs,
            "signature": signature,
            "created_at": created_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()

def difficulty_to_target(difficulty: int) -> int:
    return MAX_TARGET // max(1, difficulty)

def block_meets_target(block_hash: str, difficulty: int) -> bool:
    target = difficulty_to_target(difficulty)
    return int(block_hash, 16) < target

def recalc_reward_for_height(height: int) -> int:
    halvings = height // HALVING_EVERY_BLOCKS
    reward = INITIAL_REWARD
    for _ in range(halvings):
        reward = max(1, reward // 2)
    return reward

def spending_intent_message(network_id: str, tx_version: int, sender_pub: str, inputs: list[dict], outputs: list[dict], fee: int) -> str:
    payload = {
        "network_id": network_id,
        "tx_version": tx_version,
        "sender_pub": sender_pub,
        "inputs": inputs,
        "outputs": outputs,
        "fee": fee,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))

def verify_strict_signature(sender_pub: str, inputs: list[dict], outputs: list[dict], signature: str, fee: int) -> bool:
    if sender_pub == "NETWORK":
        return True
    if not signature:
        return False

    try:
        vk = VerifyingKey.from_string(bytes.fromhex(sender_pub), curve=SECP256k1)
        unsigned_inputs = [
            {
                "prev_tx_hash": i["prev_tx_hash"],
                "output_index": int(i["output_index"]),
            }
            for i in inputs
        ]

        message = spending_intent_message(
            NETWORK_ID,
            TX_VERSION,
            sender_pub,
            unsigned_inputs,
            outputs,
            fee,
        )

        digest = hashlib.sha256(message.encode()).digest()
        return vk.verify_digest(
            bytes.fromhex(signature),
            digest,
            sigdecode=sigdecode_string,
        )
    except (BadSignatureError, ValueError, AssertionError, KeyError):
        return False

def mine_pow(block_data: dict, difficulty: int) -> dict:
    target = 2**(256 - difficulty)
    nonce = 0
    data = block_data.copy()
    
    while True:
        data["nonce"] = nonce
        block_string = json.dumps(data, sort_keys=True).encode()
        block_hash = hashlib.sha256(block_string).hexdigest()
        
        if int(block_hash, 16) < target:
            data["hash"] = block_hash
            return data
        nonce += 1

def validate_coinbase(block: dict) -> bool:
    txs = block.get("transactions", [])
    if not txs:
        return False

    first_tx = txs[0]
    if first_tx.get("sender_pub") != "NETWORK":
        return False

    coinbase_count = sum(1 for tx in txs if tx.get("sender_pub") == "NETWORK")
    return coinbase_count == 1

def is_valid_chain_payload(chain: list[dict]) -> bool:
    if not chain:
        return True

    for i, block in enumerate(chain):
        candidate = dict(block)
        incoming_hash = candidate.pop("hash", None)
        check_hash = block_hash_of(block)

        if check_hash != incoming_hash:
            return False

        if not block_meets_target(incoming_hash, int(block["difficulty"])):
            return False

        if i == 0:
            if block["prev_hash"] != "0":
                return False
        else:
            if block["prev_hash"] != chain[i - 1]["hash"]:
                return False
    return True

def validate_block_transactions(db, block: dict) -> bool:
    """Vérifie qu'aucune double dépense n'est présente au sein du même bloc."""
    temp_spent = set()

    for tx in block.get("transactions", []):
        if tx.get("sender_pub") == "NETWORK":
            continue

        inputs = tx.get("inputs", [])
        outputs = tx.get("outputs", [])

        total_in = 0
        total_out = sum(int(o.get("amount", 0)) for o in outputs)

        for txin in inputs:
            ref = (txin["prev_tx_hash"], txin["output_index"])

            # Détection double dépense intra-bloc
            if ref in temp_spent:
                return False

            # Note : La vérification d'existence de l'UTXO en DB se fera 
            # via l'ORM lors de l'intégration finale dans l'API.
            temp_spent.add(ref)

        if total_in < total_out and inputs: # Validation simplifiée pour le cœur
            return False

    return True

def validate_block_full(db, block: dict) -> bool:
    """Valide l'intégralité des règles d'un bloc avant son inscription."""
    required = ["height", "prev_hash", "transactions", "nonce", "timestamp", "difficulty", "hash"]
    if not all(k in block for k in required):
        return False

    candidate = block.copy()
    incoming_hash = candidate.pop("hash")

    if block_hash_of(candidate) != incoming_hash:
        return False

    if not block_meets_target(incoming_hash, int(block["difficulty"])):
        return False

    # Empêcher les blocs avec un timestamp trop dans le futur (max 60s)
    if int(block["timestamp"]) > int(time.time()) + 60:
        return False

    if not validate_coinbase(block):
        return False

    if not validate_block_transactions(db, block):
        return False

    return True

from db import BlockModel, UTXOModel, WalletModel

def current_height(db) -> int:
    """Retourne la hauteur actuelle de la blockchain."""
    last_block = db.query(BlockModel).order_by(BlockModel.height.desc()).first()
    return last_block.height if last_block else -1

def last_block_hash(db) -> str:
    """Retourne le hash du dernier bloc inscrit."""
    last_block = db.query(BlockModel).order_by(BlockModel.height.desc()).first()
    return last_block.hash if last_block else "0"

def get_balance(db, public_key: str) -> int:
    """Calcule le solde disponible pour une clé publique via les UTXOs non dépensés."""
    utxos = (
        db.query(UTXOModel)
        .filter(UTXOModel.recipient_pub == public_key, UTXOModel.spent == False)
        .all()
    )
    return sum(u.amount for u in utxos)

def load_wallet_by_pub(db, public_key: str):
    """Charge un wallet depuis la base de données via sa clé publique."""
    return db.query(WalletModel).filter(WalletModel.public_key == public_key).first()

def decrypt_private_key_hex(encrypted_text: str) -> str:
    """Déchiffre une clé privée (alias de vault_decrypt pour compatibilité)."""
    from vault_client import vault_decrypt
    return vault_decrypt(encrypted_text)

def sign_message_with_private_hex(private_hex: str, message: str) -> str:
    """Signe un message textuel avec une clé privée ECDSA SECP256k1."""
    from ecdsa import SigningKey
    sk = SigningKey.from_string(bytes.fromhex(private_hex), curve=SECP256k1)
    return sk.sign(message.encode()).hex()

def find_utxo(db, prev_tx_hash: str, output_index: int):
    """Trouve un UTXO spécifique dans la base de données."""
    return (
        db.query(UTXOModel)
        .filter(UTXOModel.tx_hash == prev_tx_hash, UTXOModel.output_index == output_index)
        .first()
    )

def get_tx_inputs(db, tx_hash: str):
    """Récupère les inputs d'une transaction."""
    from db import TransactionInputModel
    return (
        db.query(TransactionInputModel)
        .filter(TransactionInputModel.tx_hash == tx_hash)
        .order_by(TransactionInputModel.id.asc())
        .all()
    )

def get_tx_outputs(db, tx_hash: str):
    """Récupère les outputs d'une transaction."""
    from db import TransactionOutputModel
    return (
        db.query(TransactionOutputModel)
        .filter(TransactionOutputModel.tx_hash == tx_hash)
        .order_by(TransactionOutputModel.output_index.asc())
        .all()
    )

def select_utxos_for_amount(db, sender_pub: str, amount: int):
    """Sélectionne les UTXOs nécessaires pour couvrir un montant de transaction."""
    from fastapi import HTTPException
    utxos = (
        db.query(UTXOModel)
        .filter(UTXOModel.recipient_pub == sender_pub, UTXOModel.spent == False)
        .order_by(UTXOModel.id.asc())
        .all()
    )

    selected = []
    total = 0
    for u in utxos:
        selected.append(u)
        total += int(u.amount)
        if total >= amount:
            break

    if total < amount:
        raise HTTPException(status_code=400, detail="Solde insuffisant")

    return selected, total

def is_input_reserved_in_mempool(db, prev_tx_hash: str, output_index: int, excluding_tx_hash: str | None = None) -> bool:
    """Vérifie si un UTXO est déjà bloqué par une transaction en attente dans la mempool."""
    from db import TransactionInputModel, TransactionModel
    q = (
        db.query(TransactionInputModel, TransactionModel)
        .join(TransactionModel, TransactionInputModel.tx_hash == TransactionModel.tx_hash)
        .filter(
            TransactionInputModel.prev_tx_hash == prev_tx_hash,
            TransactionInputModel.output_index == output_index,
            TransactionModel.status == "pending",
        )
    )
    if excluding_tx_hash:
        q = q.filter(TransactionInputModel.tx_hash != excluding_tx_hash)
    return q.first() is not None

def validate_strict_transaction(db, sender_pub: str, inputs: list[dict], outputs: list[dict], signature: str):
    """Valide la cohérence d'une transaction stricte (montants et UTXOs)."""
    from fastapi import HTTPException
    if not inputs: raise HTTPException(status_code=400, detail="Transaction sans inputs")
    if not outputs: raise HTTPException(status_code=400, detail="Transaction sans outputs")

    seen_inputs = set()
    total_in = 0

    for txin in inputs:
        ref = (txin["prev_tx_hash"], txin["output_index"])
        if ref in seen_inputs: raise HTTPException(status_code=400, detail="Input dupliqué")
        seen_inputs.add(ref)

        utxo = find_utxo(db, txin["prev_tx_hash"], txin["output_index"])
        if not utxo: raise HTTPException(status_code=400, detail="UTXO introuvable")
        if utxo.spent: raise HTTPException(status_code=400, detail="UTXO déjà dépensé")
        if utxo.recipient_pub != sender_pub: raise HTTPException(status_code=400, detail="UTXO non possédé par le sender")
        if is_input_reserved_in_mempool(db, txin["prev_tx_hash"], txin["output_index"]):
            raise HTTPException(status_code=400, detail="UTXO déjà réservé dans la mempool")

        total_in += int(utxo.amount)

    total_out = sum(int(out["amount"]) for out in outputs if int(out["amount"]) > 0)
    if total_in < total_out: raise HTTPException(status_code=400, detail="Inputs insuffisants")

    fee = total_in - total_out
    if not verify_strict_signature(sender_pub, inputs, outputs, signature, fee):
        raise HTTPException(status_code=400, detail="Signature stricte invalide")

    return {"total_in": total_in, "total_out": total_out, "fee": fee}

def normalize_tx_inputs(inputs: list[dict]) -> list[dict]:
    return [{"prev_tx_hash": i["prev_tx_hash"], "output_index": int(i["output_index"]), "signature": i["signature"]} for i in inputs]

def normalize_tx_outputs(outputs: list[dict]) -> list[dict]:
    return [{"recipient_pub": o["recipient_pub"], "amount": int(o["amount"])} for o in outputs]

def json_size_bytes(obj: dict | list) -> int:
    return len(json.dumps(obj, sort_keys=True).encode())

def mempool_size(db) -> int:
    return db.query(TransactionModel).filter(TransactionModel.status == "pending").count()

def sender_pending_count(db, sender_pub: str) -> int:
    return db.query(TransactionModel).filter(TransactionModel.status == "pending", TransactionModel.sender_pub == sender_pub).count()

def create_genesis_block(db):
    """Initialise le bloc Genesis (bloc 0) si la blockchain est vide."""
    if current_height(db) >= 0:
        return

    genesis_timestamp = 1760000000
    # On utilise la constante locale TX_VERSION si définie, sinon 1
    tx_version_local = globals().get("TX_VERSION", 1)
    network_id_local = globals().get("NETWORK_ID", "cmia-mainnet-v1")

    block = {
        "height": 0,
        "prev_hash": "0",
        "transactions": [
            {
                "tx_hash": "genesis",
                "sender_pub": "NETWORK",
                "recipient_pub": "GENESIS",
                "amount": 0,
                "signature": "",
                "created_at": genesis_timestamp,
                "type": "genesis",
                "tx_version": tx_version_local,
                "network_id": network_id_local,
                "message": "CryptomonnaiesIA Network — A public blockchain infrastructure layer for next-generation digital value",
            }
        ],
        "nonce": 0,
        "timestamp": genesis_timestamp,
        "difficulty": globals().get("DIFFICULTY", 3),
    }

    block["hash"] = block_hash_of(block)

    db.add(
        BlockModel(
            height=0,
            hash=block["hash"],
            prev_hash="0",
            nonce=0,
            timestamp=genesis_timestamp,
            difficulty=block["difficulty"],
            transactions=block["transactions"],
        )
    )
    db.commit()
    print("🚀 Bloc Genesis créé avec succès !")