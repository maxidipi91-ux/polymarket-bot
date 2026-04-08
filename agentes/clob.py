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

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID  = 137  # Polygon mainnet


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


def ejecutar_orden(polymarket_id, outcome, precio, monto_usdc):
    """
    Coloca una orden FOK (Fill-or-Kill) en el CLOB de Polymarket.

    Args:
        polymarket_id: ID numérico del mercado en Gamma API
        outcome: "Yes" o "No"
        precio: float entre 0 y 1 (ej: 0.65)
        monto_usdc: float en USDC (ej: 20.0)

    Returns:
        dict con resultado o None si falló
    """
    try:
        client   = _get_client()
        token_id = obtener_token_id(polymarket_id, outcome)

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
