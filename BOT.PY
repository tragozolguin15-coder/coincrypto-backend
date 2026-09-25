import os
import logging
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configuración de registros del sistema
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Token real de tu Bot de Telegram
BOT_TOKEN = "8454516611:AAFU6B0LU_1ToHQ3P89jz_GB2oWWdiBuczI"

# Memoria temporal en el servidor (simulando base de datos en la nube)
estado_sistema = {
    "modo_seguridad": False,
    "ultimo_nodo": "CoinCrypto_X9",
    "saldo": "$45,850.00 MXN",
    "ultima_ubicacion": "Sin registro GPS"
}

# ==========================================================
#        🌐 ENDPOINTS PARA LA APLICACIÓN DE ANDROID
# ==========================================================

@app.route('/', methods=['GET'])
def index():
    return "CoinCrypto Cloud Server Operational", 200

@app.route('/api/status', methods=['GET'])
def api_get_status():
    """La app de Android consulta esto por internet para verificar protocolos."""
    return jsonify({
        "status": "success",
        "modo_seguridad": estado_sistema["modo_seguridad"],
        "saldo": estado_sistema["saldo"]
    })

@app.route('/api/report', methods=['POST'])
def api_report():
    """La app de Android envía datos (ubicación, telemetría) hacia la nube."""
    data = request.json
    if data and "ubicacion" in data:
        estado_sistema["ultima_ubicacion"] = data["ubicacion"]
    return jsonify({"status": "received"}), 200


# ==========================================================
#       🤖 COMANDOS DEL BOT DE TELEGRAM
# ==========================================================

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "⚡️ [ CLÚSTER DE CONTROL EN LA NUBE ] ⚡️\n"
        "--------------------------------------------------\n"
        "👉 `/status` - Ver estado actual de los nodos.\n"
        "👉 `/activ` - Activar modo auxilio de forma remota.\n"
        "👉 `/desactiv` - Desactivar protocolo de seguridad.\n"
        "👉 `/ubi` - Consultar última ubicación reportada por la app."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seg = "🚨 ACTIVADO (ALERTA)" if estado_sistema["modo_seguridad"] else "🟢 SEGURO (IDLE)"
    reporte = (
        f"📊 [ ESTADO DEL NODO EN VIVO ]\n"
        f"----------------------------------\n"
        f"👤 Nodo Activo: {estado_sistema['ultimo_nodo']}\n"
        f"🛡️ Protocolo: {seg}\n"
        f"💰 Saldo Ledger: {estado_sistema['saldo']}"
    )
    await update.message.reply_text(reporte)

async def cmd_activ(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado_sistema["modo_seguridad"] = True
    await update.message.reply_text("🚨 [NUBE] Protocolo de auxilio activado. La próxima vez que la app sincronice, entrará en alerta.")

async def cmd_desactiv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado_sistema["modo_seguridad"] = False
    await update.message.reply_text("✅ [NUBE] Protocolo de seguridad desactivado.")

async def cmd_ubi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📍 Última ubicación en servidor:\n👉 {estado_sistema['ultima_ubicacion']}")


# ==========================================================
#               ⚙️ INICIALIZACIÓN DEL SISTEMA
# ==========================================================

def configurar_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("activ", cmd_activ))
    application.add_handler(CommandHandler("desactiv", cmd_desactiv))
    application.add_handler(CommandHandler("ubi", cmd_ubi))
    return application

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)