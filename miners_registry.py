from datetime import datetime, timezone, timedelta

miners_registry: dict[str, dict] = {}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def touch_miner(miner_id: str, miner_pub: str, ip: str | None):
    existing = miners_registry.get(miner_id)

    if not existing:
        miners_registry[miner_id] = {
            "miner_id": miner_id,
            "miner_pub": miner_pub,
            "enabled": True,
            "created_at": now_iso(),
            "last_seen_at": now_iso(),
            "last_mine_at": None,
            "total_blocks_mined": 0,
            "total_rewards": 0.0,
            "last_ip": ip,
        }
        return

    existing["last_seen_at"] = now_iso()
    existing["last_ip"] = ip

def mark_block_mined(miner_id: str, reward: float):
    existing = miners_registry.get(miner_id)
    if not existing:
        return

    existing["last_mine_at"] = now_iso()
    existing["total_blocks_mined"] += 1
    existing["total_rewards"] += float(reward)

def compute_miner_stats():
    now = datetime.now(timezone.utc)
    active_15m = 0
    active_24h = 0

    for miner in miners_registry.values():
        last_seen_raw = miner.get("last_seen_at")
        if not last_seen_raw:
            continue

        try:
            last_seen = datetime.fromisoformat(last_seen_raw)
        except Exception:
            continue

        if now - last_seen <= timedelta(minutes=15):
            active_15m += 1

        if now - last_seen <= timedelta(hours=24):
            active_24h += 1

    return {
        "total_registered": len(miners_registry),
        "active_15m": active_15m,
        "active_24h": active_24h,
        "miners": list(miners_registry.values()),
    }