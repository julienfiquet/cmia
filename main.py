import os
import asyncio
import threading
import uvicorn
from dotenv import load_dotenv

# Chargement des variables d'environnement (.env)
load_dotenv()

from network.api import app, get_db, create_genesis_block, get_or_create_network_state, recompute_network_state
from network.p2p import p2p_start_server
from db import SessionLocal

NODE_PORT = int(os.getenv("NODE_PORT", "8000"))
P2P_HOST = os.getenv("P2P_HOST", "0.0.0.0")
P2P_PORT = int(os.getenv("P2P_PORT", "9000"))

# Récupération des pairs P2P configurés
P2P_PEERS_RAW = os.getenv("P2P_PEERS", "")
P2P_PEERS = [p.strip() for p in P2P_PEERS_RAW.split(",") if p.strip()]

def start_p2p_thread():
    """Lance le serveur P2P dans une boucle d'événements asynchrone dédiée."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(p2p_start_server(P2P_HOST, P2P_PORT, NODE_PORT, P2P_PEERS))

if __name__ == "__main__":
    # 1. Initialisation de la Blockchain au démarrage
    print("⚙️ Initialisation du réseau et de la blockchain CMIA...")
    
    # FORCER LA CRÉATION DES TABLES ICI
    from db import init_db
    try:
        init_db()
        print("📁 Tables SQLite créées ou vérifiées.")
    except Exception as e:
        print(f"⚠️ Note sur la création des tables : {e}")

    db = SessionLocal()
    try:
        create_genesis_block(db)
        get_or_create_network_state(db)
        recompute_network_state(db)
        print("✅ Base de données locale et état du réseau synchronisés.")
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation : {e}")
    finally:
        db.close()

    # 2. Démarrage du serveur P2P en tâche de fond
    print("🌐 Lancement du protocole Peer-to-Peer...")
    p2p_thread = threading.Thread(target=start_p2p_thread, daemon=True)
    p2p_thread.start()

    # 3. Démarrage de l'API HTTP principale
    print(f"🚀 Lancement de l'API Node sur http://localhost:{NODE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)