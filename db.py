import os
import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Boolean,
    BigInteger,
    JSON,
    Float,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# --- Configuration de la base de données ---
NODE_PORT = os.getenv("NODE_PORT", "8000")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///./data/blockchain_{NODE_PORT}.db")

# Si on est sur PostgreSQL (Render), on ajuste l'URL pour SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {"sslmode": "require"},
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base = declarative_base()


# --- Modèles ---

class WalletModel(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    public_key = Column(Text, unique=True, nullable=False)
    private_encrypted = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class SignalModel(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(50), nullable=False)
    type = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    confidence = Column(Float, nullable=False)
    status = Column(String(20), default="ACTIVE")
    timestamp = Column(String(100), nullable=False)


class BlockModel(Base):
    __tablename__ = "blocks"
    id = Column(Integer, primary_key=True, index=True)
    height = Column(Integer, nullable=False, index=True)
    hash = Column(String(255), unique=True, nullable=False)
    prev_hash = Column(String(255), nullable=False, index=True)
    nonce = Column(BigInteger, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    difficulty = Column(Integer, nullable=False)
    transactions = Column(JSON, nullable=False)


class TransactionModel(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(255), unique=True, nullable=False)
    sender_pub = Column(Text, nullable=False)
    recipient_pub = Column(Text, nullable=False)
    amount = Column(BigInteger, nullable=False)
    signature = Column(Text, nullable=False, default="")
    status = Column(String(50), nullable=False, default="pending")
    block_hash = Column(String(255), nullable=True)
    created_at = Column(BigInteger, nullable=False)


class TransactionInputModel(Base):
    __tablename__ = "transaction_inputs"
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(255), nullable=False, index=True)
    prev_tx_hash = Column(String(255), nullable=False)
    output_index = Column(Integer, nullable=False)
    signature = Column(Text, nullable=False)


class TransactionOutputModel(Base):
    __tablename__ = "transaction_outputs"
    __table_args__ = (
        UniqueConstraint("tx_hash", "output_index", name="uq_transaction_output"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(255), nullable=False, index=True)
    output_index = Column(Integer, nullable=False)
    recipient_pub = Column(Text, nullable=False)
    amount = Column(BigInteger, nullable=False)


class UTXOModel(Base):
    __tablename__ = "utxos"
    __table_args__ = (
        UniqueConstraint("tx_hash", "output_index", name="uq_utxo_tx_output"),
    )
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(255), nullable=False)
    output_index = Column(Integer, nullable=False)
    recipient_pub = Column(Text, nullable=False)
    amount = Column(BigInteger, nullable=False)
    spent = Column(Boolean, nullable=False, default=False)
    spent_by_tx_hash = Column(String(255), nullable=True)


class NetworkStateModel(Base):
    __tablename__ = "network_state"
    id = Column(Integer, primary_key=True, index=True)
    coins_minted = Column(BigInteger, nullable=False, default=0)
    current_reward = Column(BigInteger, nullable=False)
    max_supply = Column(BigInteger, nullable=False)
    halving_every_blocks = Column(Integer, nullable=False)


class OrderModel(Base):
    __tablename__ = "orders"
    id = Column(String(64), primary_key=True, index=True)
    cmia_address = Column(Text, nullable=False, index=True)
    btc_address = Column(Text, nullable=False, index=True)
    expected_btc = Column(String(64), nullable=False)
    expected_cmia = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    btc_txid = Column(String(255), nullable=True, unique=True)
    cmia_tx_hash = Column(String(255), nullable=True, unique=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)


class MinerModel(Base):
    __tablename__ = "miners"
    id = Column(Integer, primary_key=True, index=True)
    miner_id = Column(String, unique=True, index=True)
    miner_pub = Column(String)
    ip = Column(String)
    last_seen = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    blocks_mined = Column(Integer, default=0)
    total_reward = Column(Float, default=0.0)


class MarketData(Base):
    __tablename__ = "market_data"
    id = Column(Integer, primary_key=True, index=True)
    pair = Column(String(50), nullable=False)
    price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    timestamp = Column(String(100), nullable=False)


# --- Fonctions utilitaires ---

def init_db():
    print("Initialisation de la base de données et création des tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Base de données prête.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()