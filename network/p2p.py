import asyncio
import json
import requests

# Ces variables seront écrasées par les variables d'environnement au lancement
P2P_HOST = "0.0.0.0"
P2P_PORT = 9000
P2P_PEERS = []
NODE_PORT = 8000

async def p2p_handle_client(reader, writer):
    """Gère les messages entrants envoyés par d'autres nœuds de la communauté."""
    try:
        while True:
            raw = await reader.readline()
            if not raw:
                break

            msg = json.loads(raw.decode())
            msg_type = msg.get("type")
            data = msg.get("data")

            if msg_type == "ping":
                writer.write((json.dumps({"type": "pong"}) + "\n").encode())
                await writer.drain()

            elif msg_type == "new_tx":
                # On redirige la transaction reçue en P2P vers notre API locale pour validation
                try:
                    requests.post(
                        f"http://127.0.0.1:{NODE_PORT}/transaction/receive",
                        json=data,
                        timeout=2,
                    )
                except Exception:
                    pass

            elif msg_type == "new_block":
                # On redirige le bloc reçu en P2P vers notre API locale pour validation et inscription
                try:
                    requests.post(
                        f"http://127.0.0.1:{NODE_PORT}/block/receive",
                        json=data,
                        timeout=2,
                    )
                except Exception:
                    pass

            elif msg_type == "sync_request":
                # Un autre nœud demande l'historique de notre chaîne
                try:
                    # On fait une requête interne à notre propre nœud pour récupérer la chaîne sérialisée
                    res = requests.get(f"http://127.0.0.1:{NODE_PORT}/chain", timeout=2)
                    if res.status_code == 200:
                        chain = res.json()
                        writer.write((json.dumps({"type": "chain", "data": chain}) + "\n").encode())
                        await writer.drain()
                except Exception:
                    pass

    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()
        
async def p2p_start_server(host: str, port: int, node_port: int, p2p_peers: list):
    """Démarre le serveur d'écoute P2P."""
    global P2P_HOST, P2P_PORT, NODE_PORT, P2P_PEERS
    P2P_HOST = host
    P2P_PORT = port
    NODE_PORT = node_port
    P2P_PEERS = p2p_peers

    server = await asyncio.start_server(p2p_handle_client, P2P_HOST, P2P_PORT)
    print(f"🌐 Serveur P2P CMIA actif sur {P2P_HOST}:{P2P_PORT}")
    async with server:
        await server.serve_forever()

async def p2p_send_message(host: str, port: int, message: dict):
    """Envoie un message unique à un pair spécifique."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

def parse_p2p_peer(peer: str):
    """Découpe une chaîne 'IP:PORT'."""
    host, port = peer.split(":")
    return host, int(port)

def p2p_broadcast_tx(tx_dict: dict):
    """Diffuse une transaction à tout le réseau P2P."""
    async def _run():
        tasks = []
        for peer in P2P_PEERS:
            try:
                host, port = parse_p2p_peer(peer)
                tasks.append(p2p_send_message(host, port, {"type": "new_tx", "data": tx_dict}))
            except Exception:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        pass

def p2p_broadcast_block(block_dict: dict):
    """Diffuse un bloc à tout le réseau P2P."""
    async def _run():
        tasks = []
        for peer in P2P_PEERS:
            try:
                host, port = parse_p2p_peer(peer)
                tasks.append(p2p_send_message(host, port, {"type": "new_block", "data": block_dict}))
            except Exception:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        pass