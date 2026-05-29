import os
import json
import time
import datetime
import uuid
from typing import Optional, List

from fastapi import FastAPI, Header, HTTPException, Depends, Response, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

# --- Importations de tes modules locaux d'origine ---
from db import (
    init_db, SessionLocal, get_db, WalletModel, BlockModel, TransactionModel,
    TransactionInputModel, TransactionOutputModel, UTXOModel, NetworkStateModel,
    OrderModel, MarketData, SignalModel, MinerModel
)
from vault_client import vault_encrypt, vault_decrypt 
from miners_registry import touch_miner, mark_block_mined, compute_miner_stats
# from workers.telegram_bot import send_cmia_signal

# --- Importations des briques que nous venons de créer ---
from core.blockchain import (
    now_ts, tx_hash_of, block_hash_of, strict_tx_hash_of, recalc_reward_for_height,
    verify_strict_signature, mine_pow, validate_block_full, is_valid_chain_payload,
    block_meets_target, current_height, last_block_hash, get_balance,
    load_wallet_by_pub, decrypt_private_key_hex, sign_message_with_private_hex,
    find_utxo, get_tx_inputs, get_tx_outputs, select_utxos_for_amount,
    is_input_reserved_in_mempool, spending_intent_message, create_genesis_block,
    validate_strict_transaction, normalize_tx_inputs, normalize_tx_outputs, json_size_bytes,
    mempool_size, sender_pending_count
)
from network.p2p import p2p_broadcast_tx, p2p_broadcast_block

# ================== INITIALISATION DE L'API ==================
app = FastAPI(title="CMIA Node API")
router = APIRouter()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.cryptomonnaiesia.com", "https://cryptomonnaiesia.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration via variables d'environnement
NODE_PORT = int(os.getenv("NODE_PORT", "8000"))
DIFFICULTY = int(os.getenv("DIFFICULTY", "3"))
MAX_SUPPLY = int(os.getenv("MAX_SUPPLY", "10000000"))
INITIAL_REWARD = int(os.getenv("INITIAL_REWARD", "25"))
HALVING_EVERY_BLOCKS = int(os.getenv("HALVING_EVERY_BLOCKS", "5000"))
NETWORK_NAME = os.getenv("NETWORK_NAME", "CMIA Network")
NETWORK_ID = os.getenv("NETWORK_ID", "cmia-mainnet-v1")
SYMBOL = os.getenv("SYMBOL", "CMIA")
TX_VERSION = int(os.getenv("TX_VERSION", "1"))
MAX_BLOCK_TX = int(os.getenv("MAX_BLOCK_TX", "200"))
MAX_MEMPOOL_TX = int(os.getenv("MAX_MEMPOOL_TX", "5000"))
MAX_TX_PER_SENDER_IN_MEMPOOL = int(os.getenv("MAX_TX_PER_SENDER_IN_MEMPOOL", "50"))
MAX_TX_BYTES = int(os.getenv("MAX_TX_BYTES", "25000"))
FAUCET_PUBLIC_KEY = os.getenv("FAUCET_PUBLIC_KEY", "")
FAUCET_PRIVATE_KEY = os.getenv("FAUCET_PRIVATE_KEY", "")
FAUCET_AMOUNT = int(os.getenv("FAUCET_AMOUNT", "10"))
TREASURY_API_SECRET = os.environ.get("TREASURY_API_SECRET")
TREASURY_PUBLIC_KEY = os.environ.get("TREASURY_PUBLIC_KEY")
TREASURY_PRIVATE_KEY = os.environ.get("TREASURY_PRIVATE_KEY")

SEEN_TX = set()
SEEN_BLOCKS = set()

# --- Pydantic Models ---
class MineRequest(BaseModel):
    miner_id: str
    miner_pub: str

class SendStrictTxRequest(BaseModel):
    sender_pub: str
    recipient_pub: str
    amount: int

class TreasurySendRequest(BaseModel):
    recipient_pub: str
    amount: int
    
class CreateOrderRequest(BaseModel):
    cmia_address: str
    btc_address: str
    expected_btc: str
    expected_cmia: str
    expires_in_seconds: int = 3600

class CompleteOrderRequest(BaseModel):
    btc_txid: str

class FaucetRequest(BaseModel):
    recipient_pub: str

# ================== ROUTE / UTILS LOCALES ==================
def get_current_difficulty(db) -> int:
    last_block = db.query(BlockModel).order_by(BlockModel.height.desc()).first()
    return int(last_block.difficulty) if last_block else DIFFICULTY

def get_or_create_network_state(db: Session):
    state = db.query(NetworkStateModel).filter(NetworkStateModel.id == 1).first()
    if not state:
        state = NetworkStateModel(
            id=1,
            # On retire "height=0" car la colonne n'existe pas dans ton modèle DB
            coins_minted=0,
            current_reward=INITIAL_REWARD,
            max_supply=MAX_SUPPLY,
            halving_every_blocks=HALVING_EVERY_BLOCKS,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state
    
def recompute_network_state(db):
    state = get_or_create_network_state(db)
    blocks = db.query(BlockModel).order_by(BlockModel.height.asc()).all()
    minted = sum(int(tx.get("base_reward", tx["amount"])) for b in blocks for tx in b.transactions if tx["sender_pub"] == "NETWORK")
    height = len(blocks) - 1
    state.coins_minted = minted
    state.current_reward = recalc_reward_for_height(max(height + 1, 0))
    db.commit()

# ================== ENDPOINTS WALLET ==================
@app.post("/wallet/create")
def api_create_wallet(name: str, db: Session = Depends(get_db)):
    from core.blockchain import SigningKey, SECP256k1
    key = SigningKey.generate(curve=SECP256k1)
    public_key = key.get_verifying_key().to_string().hex()
    private_hex = key.to_string().hex()
    encrypted = vault_encrypt(private_hex)

    if db.query(WalletModel).filter(WalletModel.public_key == public_key).first():
        raise HTTPException(status_code=400, detail="Wallet déjà existant")

    row = WalletModel(name=name, public_key=public_key, private_encrypted=encrypted, created_at=now_ts())
    db.add(row)
    db.commit()
    return {"name": name, "address": public_key, "private_encrypted": encrypted}

@app.get("/wallets")
def api_wallets(db: Session = Depends(get_db)):
    rows = db.query(WalletModel).order_by(WalletModel.id.asc()).all()
    return [{"id": w.id, "name": w.name, "public_key": w.public_key, "created_at": w.created_at, "balance": get_balance(db, w.public_key)} for w in rows]

# ================== ENDPOINTS TRANSACTIONS & MEMPOOL ==================
@app.get("/mempool")
def api_mempool(db: Session = Depends(get_db)):
    rows = db.query(TransactionModel).filter(TransactionModel.status == "pending").order_by(TransactionModel.created_at.asc()).all()
    return [{
        "tx_hash": t.tx_hash, "sender_pub": t.sender_pub, "signature": t.signature, "status": t.status, "created_at": t.created_at,
        "inputs": [{"prev_tx_hash": i.prev_tx_hash, "output_index": i.output_index, "signature": i.signature} for i in get_tx_inputs(db, t.tx_hash)],
        "outputs": [{"output_index": o.output_index, "recipient_pub": o.recipient_pub, "amount": o.amount} for o in get_tx_outputs(db, t.tx_hash)]
    } for t in rows]

@app.post("/transaction/send-strict")
def api_send_strict_transaction(req: SendStrictTxRequest, db: Session = Depends(get_db)):
    if req.amount <= 0 or req.sender_pub == req.recipient_pub:
        raise HTTPException(status_code=400, detail="Paramètres invalides")
    
    wallet = db.query(WalletModel).filter(WalletModel.public_key == req.sender_pub).first()
    if not wallet: raise HTTPException(status_code=404, detail="Wallet introuvable")

    selected_utxos, total_in = select_utxos_for_amount(db, req.sender_pub, req.amount)
    inputs_unsigned = [{"prev_tx_hash": u.tx_hash, "output_index": u.output_index} for u in selected_utxos]
    outputs = [{"recipient_pub": req.recipient_pub, "amount": req.amount}]
    
    change = total_in - req.amount
    if change > 0: outputs.append({"recipient_pub": req.sender_pub, "amount": change})
    
    fee = total_in - sum(int(o["amount"]) for o in outputs)
    private_hex = vault_decrypt(wallet.private_encrypted)
    message = spending_intent_message(NETWORK_ID, TX_VERSION, req.sender_pub, inputs_unsigned, outputs, fee)
    signature = sign_message_with_private_hex(private_hex, message)
    
    inputs = [{"prev_tx_hash": u.tx_hash, "output_index": u.output_index, "signature": signature} for u in selected_utxos]
    created_at = now_ts()
    tx_hash = strict_tx_hash_of(req.sender_pub, inputs, outputs, signature, created_at)

    validate_strict_transaction(db, req.sender_pub, inputs, outputs, signature)
    
    row = TransactionModel(tx_hash=tx_hash, sender_pub=req.sender_pub, recipient_pub=req.recipient_pub, amount=req.amount, signature=signature, status="pending", created_at=created_at)
    db.add(row)
    db.commit()

    tx_payload = {"tx_hash": tx_hash, "sender_pub": req.sender_pub, "tx_version": TX_VERSION, "network_id": NETWORK_ID, "inputs": inputs, "outputs": outputs, "signature": signature, "created_at": created_at}
    p2p_broadcast_tx(tx_payload)
    return {"status": "transaction_created", "tx_hash": tx_hash}

# ================== ENDPOINTS MINAGE ==================
@app.post("/mine")
def api_mine(req: MineRequest, db: Session = Depends(get_db)):
    last_block = db.query(BlockModel).order_by(BlockModel.height.desc()).first()
    next_height = (last_block.height + 1) if last_block else 0
    base_reward = recalc_reward_for_height(next_height)
    
    # Construction d'un bloc de test avec les transactions de la mempool
    pending = db.query(TransactionModel).filter(TransactionModel.status == "pending").limit(MAX_BLOCK_TX).all()
    block_txs = []
    
    # Ajout de la coinbase reward pour le mineur
    coinbase_tx = {
        "tx_hash": tx_hash_of("NETWORK", req.miner_pub, base_reward, "", now_ts()),
        "sender_pub": "NETWORK", "recipient_pub": req.miner_pub, "amount": base_reward, "type": "coinbase"
    }
    block_txs.append(coinbase_tx)
    
    block_data = {
        "height": next_height, "prev_hash": last_block.hash if last_block else "0"*64,
        "transactions": block_txs, "nonce": 0, "timestamp": now_ts(), "difficulty": DIFFICULTY,
        "miner_id": req.miner_id, "miner_pub": req.miner_pub
    }
    
    block_mined = mine_pow(block_data, DIFFICULTY)
    
    new_block = BlockModel(
        height=block_mined["height"], hash=block_mined["hash"], prev_hash=block_mined["prev_hash"],
        nonce=block_mined["nonce"], timestamp=block_mined["timestamp"], difficulty=block_mined["difficulty"],
        transactions=block_mined["transactions"]
    )
    db.add(new_block)
    db.commit()
    
    p2p_broadcast_block(block_mined)
    return {"status": "block_mined", "hash": block_mined["hash"], "height": block_mined["height"]}

# ================== INFRASTRUCTURE & READ-ONLY API ==================
@app.get("/chain")
def api_chain(db: Session = Depends(get_db)):
    blocks = db.query(BlockModel).order_by(BlockModel.height.asc()).all()
    return [{"height": b.height, "hash": b.hash, "prev_hash": b.prev_hash, "nonce": b.nonce, "timestamp": b.timestamp, "difficulty": b.difficulty, "transactions": b.transactions} for b in blocks]

@app.get("/state")
def api_state(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    state = get_or_create_network_state(db)
    return {"coins_minted": state.coins_minted, "current_reward": state.current_reward, "height": db.query(BlockModel).count() - 1, "status": "online"}

@app.get("/info")
async def api_info(db: Session = Depends(get_db)):
    state = get_or_create_network_state(db)
    return {"network": NETWORK_NAME, "symbol": SYMBOL, "difficulty": float(get_current_difficulty(db)), "height": db.query(BlockModel).count()}

@app.get("/")
def read_root():
    return {"status": "CMIA Node Online", "version": "1.0.0"}

app.include_router(router)