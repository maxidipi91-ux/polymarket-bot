"""
agentes/clob.py — Ejecución real de órdenes en Polymarket CLOB

Wrapper sobre py-clob-client para colocar órdenes Fill-or-Kill (FOK).
Solo se activa cuando estado["modo"] == "real".

Setup:
  1. Crear API key en https://clob.polymarket.com con tu wallet MetaMask
  2. Agregar al .env:
       POLYMARKET_PK=0x<tu_private_key>
       POLYMARKET_API_KEY=<api_key>
       POLYMARKET_API_SECRET=<api_secret>
       POLYMARKET_API_PASSPHRASE=<api_passphrase>
  3. Cambiar modo a "real" desde el dashboard
"""

import requests
from config_loader import CONFIG
from core.estado import addlog

GAMMA_URL  = "https://gamma-api.polymarket.com"
DATA_API   = "https://data-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
CHAIN_ID   = 137  # Polygon mainnet

# Conditional Token Framework (CTF) — donde se redimen tokens ganadores
CTF_ADDRESS   = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS  = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e en Polygon
CTF_ABI_REDEEM = [
    {
        "name": "redeemPositions",
        "type": "function",
        "inputs": [
            {"name": "collateralToken",     "type": "address"},
            {"name": "parentCollectionId",  "type": "bytes32"},
            {"name": "conditionId",         "type": "bytes32"},
            {"name": "indexSets",           "type": "uint256[]"},
        ],
        "outputs": [],
    }
]


def _get_client():
    """Inicializa el cliente CLOB con las credenciales del .env."""
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    pk          = CONFIG.get("polymarket_pk", "")
    api_key     = CONFIG.get("polymarket_api_key", "")
    api_secret  = CONFIG.get("polymarket_api_secret", "")
    passphrase  = CONFIG.get("polymarket_api_passphrase", "")

    if not pk or not api_key:
        raise ValueError("Faltan credenciales POLYMARKET_PK / POLYMARKET_API_KEY en .env")

    creds = ApiCreds(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=passphrase,
    )
    return ClobClient(CLOB_HOST, key=pk, chain_id=CHAIN_ID, creds=creds)


def obtener_token_id(polymarket_id, outcome):
    """
    Obtiene el token ID del CLOB para un mercado y outcome dado.
    El token ID es necesario para colocar la orden.
    """
    try:
        r = requests.get(f"{GAMMA_URL}/markets/{polymarket_id}", timeout=10)
        m = r.json()
        outcomes      = m.get("outcomes", "[]")
        clob_token_ids = m.get("clobTokenIds", "[]")

        if isinstance(outcomes, str):
            import json
            outcomes       = json.loads(outcomes)
            clob_token_ids = json.loads(clob_token_ids)

        for o, tid in zip(outcomes, clob_token_ids):
            if o.lower() == outcome.lower():
                return tid
    except Exception as e:
        addlog(f"[CLOB] Error obteniendo token_id: {e}", "error")
    return None


def ejecutar_orden(polymarket_id, outcome, precio, monto_usdc, token_id_directo=None):
    """
    Coloca una orden FOK (Fill-or-Kill) en el CLOB de Polymarket.

    Args:
        polymarket_id:    ID numérico del mercado en Gamma API
        outcome:          "Yes" o "No"
        precio:           float entre 0 y 1 (ej: 0.65)
        monto_usdc:       float en USDC (ej: 20.0)
        token_id_directo: si se conoce el token_id de antemano, se usa directamente
                          (evita la llamada a Gamma API)

    Returns:
        dict con resultado o None si falló
    """
    try:
        client   = _get_client()
        token_id = token_id_directo or obtener_token_id(polymarket_id, outcome)

        if not token_id:
            addlog(f"[CLOB] No se encontró token_id para mercado {polymarket_id} outcome {outcome}", "error")
            return None

        # Calcular size en shares: monto / precio
        size = round(monto_usdc / precio, 2)

        from py_clob_client.clob_types import OrderArgs, OrderType

        order_args = OrderArgs(
            token_id=token_id,
            price=precio,
            size=size,
            side="BUY",
        )

        orden    = client.create_order(order_args)
        respuesta = client.post_order(orden, OrderType.FOK)

        addlog(
            f"[CLOB] 🔴 ORDEN REAL enviada — {outcome} @ {round(precio*100,1)}% "
            f"| size={size} shares | ${monto_usdc} USDC",
            "win"
        )
        return respuesta

    except Exception as e:
        addlog(f"[CLOB] Error ejecutando orden: {e}", "error")
        return None


def cancelar_ordenes_abiertas():
    """
    Cancela todas las órdenes LIVE en el CLOB.
    Llamar al cerrar una posición para liberar liquidez atascada.
    Retorna la cantidad de órdenes canceladas.
    """
    try:
        client = _get_client()
        orders = client.get_orders()
        if not orders:
            return 0
        ids = [o["id"] for o in orders if o.get("status") == "LIVE"]
        if ids:
            client.cancel_orders(ids)
            addlog(f"[CLOB] Canceladas {len(ids)} ordenes abiertas", "info")
        return len(ids)
    except Exception as e:
        addlog(f"[CLOB] Error cancelando ordenes: {e}", "error")
        return 0


def redimir_posicion(condition_id: str, outcome_index: int) -> bool:
    """
    Redime tokens ganadores en el CTF (Conditional Token Framework).
    Convierte shares ganadores en USDC.e.

    Args:
        condition_id:   bytes32 hex del mercado (ej: "0xabc123...")
        outcome_index:  0 para el primer outcome (Yes), 1 para el segundo (No)

    Returns:
        True si la tx fue exitosa, False si no.
    """
    try:
        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware

        pk = CONFIG.get("polymarket_pk", "")
        if not pk:
            addlog("[CLOB] Falta POLYMARKET_PK para redimir", "error")
            return False

        rpc = "https://polygon.drpc.org"
        w3  = Web3(Web3.HTTPProvider(rpc))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not w3.is_connected():
            addlog("[CLOB] Sin conexion RPC para redimir", "error")
            return False

        cuenta = w3.eth.account.from_key(pk)
        ctf    = w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=CTF_ABI_REDEEM
        )

        # indexSet = 1 << outcomeIndex  (0→1, 1→2)
        index_set = 1 << outcome_index

        # conditionId como bytes32
        if not condition_id.startswith("0x"):
            condition_id = "0x" + condition_id
        cid_bytes = bytes.fromhex(condition_id[2:].zfill(64))

        tx = ctf.functions.redeemPositions(
            Web3.to_checksum_address(USDC_ADDRESS),
            b"\x00" * 32,   # parentCollectionId = bytes32(0)
            cid_bytes,
            [index_set],
        ).build_transaction({
            "from":     cuenta.address,
            "nonce":    w3.eth.get_transaction_count(cuenta.address),
            "gas":      200_000,
            "gasPrice": w3.eth.gas_price,
            "chainId":  CHAIN_ID,
        })

        signed = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt.status == 1:
            addlog(f"[CLOB] ✅ Redimido conditionId {condition_id[:18]}... | tx {tx_hash.hex()[:18]}...", "win")
            return True
        else:
            addlog(f"[CLOB] ❌ Redencion revertida — conditionId {condition_id[:18]}...", "error")
            return False

    except Exception as e:
        addlog(f"[CLOB] Error redimiendo posicion: {e}", "error")
        return False


def buscar_y_redimir(pm_id_parcial: str, outcome: str) -> bool:
    """
    Busca en la API si hay tokens ganadores redeemable para este mercado
    y los redime automáticamente si es así.

    Args:
        pm_id_parcial: ID del mercado (puede ser parcial, se hace match por prefijo)
        outcome:       "Yes" o "No"

    Returns:
        True si redimió exitosamente, False si no había nada que redimir o falló.
    """
    try:
        pk = CONFIG.get("polymarket_pk", "")
        if not pk:
            return False

        # Derivar address de la PK
        from web3 import Web3
        cuenta = Web3().eth.account.from_key(pk)
        wallet = cuenta.address.lower()

        # Buscar posiciones redeemable para este mercado
        r = requests.get(
            f"{DATA_API}/positions",
            params={"user": wallet},
            timeout=10,
        )
        if r.status_code != 200:
            return False

        posiciones = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
        outcome_lower = outcome.lower()

        for pos in posiciones:
            # Verificar que es redeemable y corresponde al outcome
            if not pos.get("redeemable"):
                continue

            title = (pos.get("title") or pos.get("market", {}).get("question", "")).lower()
            pos_outcome = (pos.get("outcome") or "").lower()

            # Match por outcome (Yes/No)
            if pos_outcome not in (outcome_lower, outcome_lower[:1]):
                continue

            # Match por conditionId parcial si fue provisto
            condition_id = pos.get("conditionId") or pos.get("condition_id", "")
            if pm_id_parcial and pm_id_parcial not in condition_id and pm_id_parcial not in title:
                continue

            # Determinar outcomeIndex
            outcomes_list = pos.get("outcomes") or []
            if not outcomes_list:
                # Intentar por nombre: Yes=0, No=1
                idx = 0 if outcome_lower == "yes" else 1
            else:
                idx = next(
                    (i for i, o in enumerate(outcomes_list) if o.lower() == outcome_lower),
                    0
                )

            addlog(
                f"[CLOB] 🏆 Posicion redeemable: {title[:40]} | outcome={outcome} | "
                f"conditionId={condition_id[:18]}...",
                "win"
            )
            return redimir_posicion(condition_id, idx)

        addlog(f"[CLOB] Sin posiciones redeemable encontradas para {pm_id_parcial[:20]}", "info")
        return False

    except Exception as e:
        addlog(f"[CLOB] Error en buscar_y_redimir: {e}", "error")
        return False


def obtener_balance_clob() -> float:
    """
    Retorna el balance USDC.e disponible en el CLOB.
    Usado por el debugger para detectar desyncs de saldo.
    """
    try:
        client = _get_client()
        bal = client.get_balance()
        return float(bal)
    except Exception as e:
        addlog(f"[CLOB] Error obteniendo balance: {e}", "error")
        return -1.0


def verificar_credenciales():
    """Verifica que las credenciales estén configuradas y la conexión funcione."""
    try:
        client = _get_client()
        balance = client.get_balance()
        addlog(f"[CLOB] Conexión OK — balance USDC: ${balance}", "info")
        return True
    except ValueError as e:
        addlog(f"[CLOB] Credenciales no configuradas: {e}", "info")
        return False
    except Exception as e:
        addlog(f"[CLOB] Error de conexión: {e}", "error")
        return False
