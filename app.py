import os
import time
import hmac
import json
import base64
import hashlib
import logging
from functools import wraps

import bcrypt
import requests
from flask import Flask, request, jsonify

from database import (
    init_db,
    get_connection,
    get_user_by_username,
)


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

SESSION_SECRET = os.environ.get("SESSION_SECRET")

if not SESSION_SECRET:
    SESSION_SECRET = "CAMBIAR_ESTA_CLAVE_EN_RENDER"

SESSION_TTL_SECONDS = int(
    os.environ.get("SESSION_TTL_SECONDS", "86400")
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_ADMIN_CHAT_ID = os.environ.get(
    "TELEGRAM_ADMIN_CHAT_ID"
)


# ==========================================================
# ESTADO DEL PROTOCOLO DE ASISTENCIA
# ==========================================================
#
# Esto NO contiene saldos.
# El saldo siempre sale de users.balance.
#

estado_sistema = {
    "modo_seguridad": False,
    "ultimo_nodo": "CoinCrypto_X9",
    "ultima_ubicacion": "Sin registro GPS",
}


# ==========================================================
# BASE DE DATOS
# ==========================================================

try:
    init_db()
    logger.info("Base de datos inicializada.")
except Exception:
    logger.exception(
        "No se pudo inicializar la base de datos."
    )


# ==========================================================
# RESPUESTAS
# ==========================================================

def json_success(data=None, status_code=200):

    response = {
        "status": "success"
    }

    if data:
        response.update(data)

    return jsonify(response), status_code


def json_error(message, status_code=400):

    return jsonify({
        "status": "error",
        "message": message
    }), status_code


def get_json():

    data = request.get_json(silent=True)

    if isinstance(data, dict):
        return data

    return {}


# ==========================================================
# USUARIOS
# ==========================================================

def normalize_username(username):

    if not isinstance(username, str):
        return ""

    return username.strip()


def serialize_user(user):

    if not user:
        return None

    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "balance": float(
            user.get("balance") or 0
        ),
        "is_temp_password": bool(
            user.get("is_temp_password")
        ),
        "bank_name": user.get("bank_name"),
        "account_number": user.get("account_number"),
        "account_holder": user.get("account_holder"),
        "telegram_chat_id": user.get(
            "telegram_chat_id"
        ),
    }


# ==========================================================
# SESIONES
# ==========================================================

def b64_encode(value):

    return base64.urlsafe_b64encode(
        value
    ).decode("utf-8").rstrip("=")


def b64_decode(value):

    padding = "=" * (-len(value) % 4)

    return base64.urlsafe_b64decode(
        value + padding
    )


def create_session(username):

    now = int(time.time())

    payload = {
        "username": username,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }

    encoded_payload = b64_encode(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )

    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return (
        f"{encoded_payload}."
        f"{b64_encode(signature)}"
    )


def decode_session(token):

    try:

        parts = token.split(".")

        if len(parts) != 2:
            return None

        encoded_payload = parts[0]
        encoded_signature = parts[1]

        expected_signature = hmac.new(
            SESSION_SECRET.encode("utf-8"),
            encoded_payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        received_signature = b64_decode(
            encoded_signature
        )

        if not hmac.compare_digest(
            expected_signature,
            received_signature
        ):
            return None

        payload = json.loads(
            b64_decode(
                encoded_payload
            ).decode("utf-8")
        )

        if int(payload.get("exp", 0)) < int(
            time.time()
        ):
            return None

        username = normalize_username(
            payload.get("username")
        )

        if not username:
            return None

        return payload

    except Exception:
        return None


def get_bearer_token():

    authorization = request.headers.get(
        "Authorization",
        ""
    )

    if not authorization:
        return None

    parts = authorization.split(" ", 1)

    if len(parts) != 2:
        return None

    if parts[0].lower() != "bearer":
        return None

    return parts[1].strip()


def require_auth(route):

    @wraps(route)
    def wrapper(*args, **kwargs):

        token = get_bearer_token()

        if not token:
            return json_error(
                "Token de sesión requerido.",
                401
            )

        session = decode_session(token)

        if not session:
            return json_error(
                "Sesión inválida o expirada.",
                401
            )

        username = session["username"]

        user = get_user_by_username(
            username
        )

        if not user:
            return json_error(
                "Usuario no encontrado.",
                401
            )

        request.current_user = user

        return route(*args, **kwargs)

    return wrapper


# ==========================================================
# TELEGRAM
# ==========================================================

def notify_admin(message):

    if not TELEGRAM_BOT_TOKEN:
        logger.warning(
            "TELEGRAM_BOT_TOKEN no configurado."
        )
        return False

    if not TELEGRAM_ADMIN_CHAT_ID:
        logger.warning(
            "TELEGRAM_ADMIN_CHAT_ID no configurado."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        if response.ok:
            return True

        logger.warning(
            "Telegram HTTP %s",
            response.status_code
        )

    except Exception:
        logger.exception(
            "Error enviando mensaje a Telegram."
        )

    return False


# ==========================================================
# INICIO
# ==========================================================

@app.route("/", methods=["GET"])
def index():

    return jsonify({
        "status": "success",
        "service": "CoinCrypto API",
        "message": "CoinCrypto Cloud Server Operational"
    })


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok"
    })


# ==========================================================
# LOGIN
# ==========================================================

@app.route("/api/login", methods=["POST"])
def api_login():

    data = get_json()

    username = normalize_username(
        data.get("username")
    )

    password = data.get("password")

    if not username or not isinstance(
        password,
        str
    ):
        return json_error(
            "Usuario y contraseña son obligatorios.",
            400
        )

    try:

        user = get_user_by_username(
            username
        )

        if not user:
            return json_error(
                "Usuario o contraseña incorrectos.",
                401
            )

        password_hash = user.get(
            "password_hash"
        )

        if not password_hash:
            return json_error(
                "La cuenta no tiene contraseña válida.",
                401
            )

        valid = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8")
        )

        if not valid:
            return json_error(
                "Usuario o contraseña incorrectos.",
                401
            )

        token = create_session(
            user["username"]
        )

        return json_success({
            "message": "Inicio de sesión correcto.",
            "token": token,
            "expires_in": SESSION_TTL_SECONDS,
            "user": serialize_user(user),
        })

    except Exception:

        logger.exception(
            "Error durante login."
        )

        return json_error(
            "Error interno del servidor.",
            500
        )


# ==========================================================
# PERFIL
# ==========================================================

@app.route("/api/me", methods=["GET"])
@require_auth
def api_me():

    user = get_user_by_username(
        request.current_user["username"]
    )

    return json_success({
        "user": serialize_user(user)
    })


# ==========================================================
# SALDO REAL
# ==========================================================

@app.route("/api/balance", methods=["GET"])
@require_auth
def api_balance():

    user = get_user_by_username(
        request.current_user["username"]
    )

    if not user:
        return json_error(
            "Usuario no encontrado.",
            404
        )

    balance = float(
        user.get("balance") or 0
    )

    return json_success({
        "username": user["username"],
        "balance": balance,
        "currency": "MXN",
    })


# ==========================================================
# STATUS PARA ANDROID
# ==========================================================

@app.route("/api/status", methods=["GET"])
@require_auth
def api_status():

    user = get_user_by_username(
        request.current_user["username"]
    )

    if not user:
        return json_error(
            "Usuario no encontrado.",
            404
        )

    balance = float(
        user.get("balance") or 0
    )

    return json_success({

        "username": user["username"],

        "saldo": (
            f"${balance:,.2f} MXN"
        ),

        "balance": balance,

        "currency": "MXN",

        "modo_seguridad":
            estado_sistema[
                "modo_seguridad"
            ],

        "ultima_ubicacion":
            estado_sistema[
                "ultima_ubicacion"
            ],
    })


# ==========================================================
# HISTORIAL
# ==========================================================

@app.route("/api/history", methods=["GET"])
@require_auth
def api_history():

    username = (
        request.current_user["username"]
    )

    try:

        with get_connection() as conn:

            rows = conn.execute(
                """
                SELECT
                    id,
                    fecha,
                    hora,
                    tipo_operacion,
                    cripto,
                    inversion_tramo,
                    rendimiento
                FROM user_movements
                WHERE username = ?
                ORDER BY id DESC
                LIMIT 500
                """,
                (username,)
            ).fetchall()

        movements = []

        for row in rows:

            movements.append({
                "id": row["id"],
                "fecha": row["fecha"],
                "hora": row["hora"],
                "tipo_operacion":
                    row["tipo_operacion"],
                "cripto": row["cripto"],
                "inversion_tramo":
                    row["inversion_tramo"],
                "rendimiento":
                    row["rendimiento"],
            })

        return json_success({
            "movements": movements
        })

    except Exception:

        logger.exception(
            "Error consultando historial."
        )

        return json_error(
            "No se pudo consultar el historial.",
            500
        )


# ==========================================================
# DATOS BANCARIOS
# ==========================================================

@app.route("/api/bank-details", methods=["GET"])
@require_auth
def api_bank_details():

    user = request.current_user

    return json_success({
        "bank": {
            "bank_name":
                user.get("bank_name"),

            "account_number":
                user.get("account_number"),

            "account_holder":
                user.get("account_holder"),
        }
    })


# ==========================================================
# CREAR RETIRO
# ==========================================================

@app.route("/api/withdrawals", methods=["POST"])
@require_auth
def api_create_withdrawal():

    data = get_json()

    try:
        amount = float(
            data.get("amount")
        )
    except (
        TypeError,
        ValueError
    ):
        return json_error(
            "Monto inválido.",
            400
        )

    amount = round(amount, 2)

    if amount <= 0:
        return json_error(
            "El monto debe ser mayor que cero.",
            400
        )

    username = (
        request.current_user["username"]
    )

    try:

        with get_connection() as conn:

            user = conn.execute(
                """
                SELECT
                    username,
                    balance,
                    bank_name,
                    account_number,
                    account_holder
                FROM users
                WHERE username = ?
                """,
                (username,)
            ).fetchone()

            if not user:
                return json_error(
                    "Usuario no encontrado.",
                    404
                )

            balance = float(
                user["balance"] or 0
            )

            if amount > balance:
                return json_error(
                    "Saldo insuficiente.",
                    400
                )

            if not user["account_number"]:
                return json_error(
                    "Primero configura tus datos bancarios.",
                    400
                )

            bank_info = (
                f"Banco: "
                f"{user['bank_name'] or 'No especificado'}\n"
                f"Cuenta: "
                f"{user['account_number']}\n"
                f"Titular: "
                f"{user['account_holder'] or username}"
            )

            cur = conn.execute(
                """
                INSERT INTO withdrawals
                (
                    username,
                    amount,
                    bank_info,
                    status,
                    previous_balance
                )
                VALUES
                (?, ?, ?, 'PENDIENTE', ?)
                """,
                (
                    username,
                    amount,
                    bank_info,
                    balance,
                )
            )

            withdrawal_id = int(
                cur.lastrowid
            )

            conn.execute(
                """
                INSERT INTO audit_log
                (
                    event_type,
                    username,
                    withdrawal_id,
                    details
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "WITHDRAWAL_CREATED",
                    username,
                    withdrawal_id,
                    f"amount={amount}",
                )
            )

        notify_admin(
            "💰 NUEVA SOLICITUD DE RETIRO\n\n"
            f"🆔 Solicitud: #{withdrawal_id}\n"
            f"👤 Usuario: {username}\n"
            f"💵 Monto: ${amount:,.2f} MXN\n"
            f"💰 Saldo actual: ${balance:,.2f} MXN\n\n"
            "Estado: PENDIENTE\n\n"
            f"Usa /siauto {withdrawal_id} "
            "para autorizar."
        )

        return json_success({

            "message":
                "Solicitud de retiro creada.",

            "withdrawal": {
                "id": withdrawal_id,
                "username": username,
                "amount": amount,
                "status": "PENDIENTE",
                "previous_balance": balance,
            }

        }, 201)

    except Exception:

        logger.exception(
            "Error creando retiro."
        )

        return json_error(
            "No se pudo crear la solicitud.",
            500
        )


# ==========================================================
# CONSULTAR RETIROS
# ==========================================================

@app.route("/api/withdrawals", methods=["GET"])
@require_auth
def api_get_withdrawals():

    username = (
        request.current_user["username"]
    )

    try:

        with get_connection() as conn:

            rows = conn.execute(
                """
                SELECT
                    id,
                    amount,
                    bank_info,
                    status,
                    created_at,
                    approved_at,
                    rejected_at,
                    previous_balance,
                    remaining_balance
                FROM withdrawals
                WHERE username = ?
                ORDER BY id DESC
                LIMIT 200
                """,
                (username,)
            ).fetchall()

        withdrawals = []

        for row in rows:

            withdrawals.append({
                "id": row["id"],
                "amount": row["amount"],
                "bank_info":
                    row["bank_info"],
                "status":
                    row["status"],
                "created_at":
                    row["created_at"],
                "approved_at":
                    row["approved_at"],
                "rejected_at":
                    row["rejected_at"],
                "previous_balance":
                    row["previous_balance"],
                "remaining_balance":
                    row["remaining_balance"],
            })

        return json_success({
            "withdrawals": withdrawals
        })

    except Exception:

        logger.exception(
            "Error consultando retiros."
        )

        return json_error(
            "No se pudieron consultar los retiros.",
            500
        )


# ==========================================================
# ACTIVAR PROTOCOLO
# ==========================================================

@app.route("/api/security/activate", methods=["POST"])
@require_auth
def api_activate_security():

    estado_sistema[
        "modo_seguridad"
    ] = True

    username = (
        request.current_user["username"]
    )

    logger.info(
        "Protocolo activado por %s",
        username
    )

    return json_success({
        "modo_seguridad": True,
        "message":
            "Protocolo de auxilio activado."
    })


# ==========================================================
# DESACTIVAR PROTOCOLO
# ==========================================================

@app.route("/api/security/deactivate", methods=["POST"])
@require_auth
def api_deactivate_security():

    estado_sistema[
        "modo_seguridad"
    ] = False

    username = (
        request.current_user["username"]
    )

    logger.info(
        "Protocolo desactivado por %s",
        username
    )

    return json_success({
        "modo_seguridad": False,
        "message":
            "Protocolo de seguridad desactivado."
    })


# ==========================================================
# REPORTAR UBICACIÓN / TELEMETRÍA
# ==========================================================

@app.route("/api/report", methods=["POST"])
@require_auth
def api_report():

    data = get_json()

    username = (
        request.current_user["username"]
    )

    ubicacion = data.get(
        "ubicacion"
    )

    if ubicacion:
        estado_sistema[
            "ultima_ubicacion"
        ] = str(ubicacion)

    try:

        with get_connection() as conn:

            conn.execute(
                """
                INSERT INTO audit_log
                (
                    event_type,
                    username,
                    details
                )
                VALUES (?, ?, ?)
                """,
                (
                    "ANDROID_REPORT",
                    username,
                    json.dumps(
                        data,
                        ensure_ascii=False
                    ),
                )
            )

        return json_success({
            "message":
                "Reporte recibido.",
            "ubicacion":
                estado_sistema[
                    "ultima_ubicacion"
                ]
        })

    except Exception:

        logger.exception(
            "Error guardando reporte."
        )

        return json_error(
            "No se pudo guardar el reporte.",
            500
        )


# ==========================================================
# INFORMACIÓN DE ASISTENCIA
# ==========================================================

@app.route("/api/security/status", methods=["GET"])
@require_auth
def api_security_status():

    return json_success({

        "modo_seguridad":
            estado_sistema[
                "modo_seguridad"
            ],

        "ultimo_nodo":
            estado_sistema[
                "ultimo_nodo"
            ],

        "ultima_ubicacion":
            estado_sistema[
                "ultima_ubicacion"
            ],
    })


# ==========================================================
# ERRORES
# ==========================================================

@app.errorhandler(404)
def error_404(error):

    return json_error(
        "Endpoint no encontrado.",
        404
    )


@app.errorhandler(405)
def error_405(error):

    return json_error(
        "Método HTTP no permitido.",
        405
    )


@app.errorhandler(500)
def error_500(error):

    logger.exception(
        "Error interno."
    )

    return json_error(
        "Error interno del servidor.",
        500
    )


# ==========================================================
# EJECUCIÓN
# ==========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
