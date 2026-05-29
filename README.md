# 🌐 CMIA Network Core (CryptomonnaiesIA)

CMIA est une couche d'infrastructure blockchain publique, expérimentale et décentralisée, combinant un consensus Proof of Work (PoW) basé sur le modèle UTXO et des connecteurs natifs pour l'intelligence artificielle (IA).

L'objectif de CMIA est de fournir une couche d'exécution hautement disponible, sécurisée et *permissionless* pour les agents et services d'IA de nouvelle génération.

---

## 🚀 Fonctionnalités actuelles
* **Modèle UTXO Strict :** Gestion sécurisée et robuste des transactions inspirée de Bitcoin.
* **Consensus Proof of Work (PoW) :** Difficulté dynamique auto-ajustable pour maintenir des temps de bloc stables.
* **Réseau Hybride :** API REST (FastAPI) pour l'intégration applicative et sockets P2P asynchrones pour la synchronisation entre nœuds.
* **Architecture Non-Custodial :** Chiffrement des clés et signature asymétrique native via la courbe SECP256k1.
* **IA-Ready :** Endpoints natifs dédiés au transit de signaux de marché et au monitoring d'infrastructure.

---

## ⚙️ Installation et Lancement d'un Nœud

### 1. Prérequis
Assurez-vous d'avoir Python 3.10+ installé.

### 2. Cloner le projet & Installer les dépendances
```bash
git clone [https://github.com/julienfiquet/cmia.git](https://github.com/julienfiquet/cmia.git)
cd cmia
pip install -r requirements.txt
