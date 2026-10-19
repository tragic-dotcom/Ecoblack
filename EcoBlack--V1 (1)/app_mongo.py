"""MongoDB Atlas backend for EcoBlack V13.

The route response contracts intentionally match static/js/app.js.
Production configuration comes from environment variables; never commit secrets.
"""
from __future__ import annotations

import os
import time
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, jsonify, request, session
from pymongo import MongoClient, ReturnDocument, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.security import generate_password_hash, check_password_hash

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "ecoblack").strip() or "ecoblack"
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI no está configurada. Usa app.py en local o configura MongoDB Atlas.")

app = Flask(__name__)
if (os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")) and not os.getenv("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY es obligatoria en Render. Configúrala en Environment.")
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "local-development-only-change-me"),
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
)

client = MongoClient(
    MONGODB_URI,
    appname="EcoBlack",
    serverSelectionTimeoutMS=12000,
    connectTimeoutMS=12000,
    retryWrites=True,
    w="majority",
)
db = client[MONGODB_DB]
users = db["users"]
modules = db["modules"]
module_sessions = db["module_sessions"]
balance_transactions = db["balance_transactions"]
admin_account = db["admin_account"]
admin_revenue_transactions = db["admin_revenue_transactions"]
counters = db["counters"]

WELCOME_BALANCE = 100.0
DEFAULT_MODULES = [
    {"id": "EB-001", "name": "EcoBlack Centro", "lat": 21.1619, "lng": -86.8515, "status": "available", "power": "30 W", "connectors": ["USB-C", "Lightning", "Inalámbrico"], "created_by": "system"},
    {"id": "EB-002", "name": "EcoBlack Plaza", "lat": 21.1638, "lng": -86.8460, "status": "available", "power": "45 W", "connectors": ["USB-C", "Lightning"], "created_by": "system"},
    {"id": "EB-003", "name": "EcoBlack Zona Hotelera", "lat": 21.1357, "lng": -86.7416, "status": "available", "power": "65 W", "connectors": ["USB-C", "Inalámbrico"], "created_by": "system"},
    {"id": "EB-004", "name": "EcoBlack Puerto", "lat": 21.1743, "lng": -86.8234, "status": "available", "power": "25 W", "connectors": ["USB-C", "Micro-USB"], "created_by": "system"},
]
PACKAGES = {
    "basic": {"id": "basic", "name": "Básico", "minutes": 15, "price": 15.0, "max_watts": 10, "description": "Hasta 15 min de sesión y potencia limitada a 10 W."},
    "fast": {"id": "fast", "name": "Rápido", "minutes": 30, "price": 25.0, "max_watts": 20, "description": "Hasta 30 min de sesión y potencia limitada a 20 W."},
    "power": {"id": "power", "name": "Power", "minutes": 45, "price": 40.0, "max_watts": 45, "description": "Hasta 45 min de sesión y potencia limitada a 45 W."},
    "custom": {"id": "custom", "name": "Personalizado", "minutes": 25, "price": 25.0, "max_watts": 30, "description": "Elige una duración de 10 a 120 minutos, con un límite de 30 W."},
}
CONNECTOR_WATT_LIMITS = {"USB-C": 240, "Lightning": 20, "Micro-USB": 12, "Inalámbrico": 15}
CONNECTOR_EFFICIENCY = {"USB-C": 0.78, "Lightning": 0.75, "Micro-USB": 0.70, "Inalámbrico": 0.68}

class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def next_id(name: str, mongo_session=None) -> int:
    doc = counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER, session=mongo_session,
    )
    return int(doc["seq"])


def init_db():
    client.admin.command("ping")
    users.create_index([("username", ASCENDING)], unique=True, name="username_unique")
    modules.create_index([("id", ASCENDING)], unique=True, name="module_id_unique")
    modules.create_index([("status", ASCENDING), ("lat", ASCENDING), ("lng", ASCENDING)], name="module_status_coords")
    module_sessions.create_index([("username", ASCENDING), ("active", ASCENDING), ("id", DESCENDING)], name="session_user_active")
    module_sessions.create_index([("module_id", ASCENDING), ("active", ASCENDING)], name="session_module_active")
    # Stop two concurrent requests from opening simultaneous sessions for one user.
    duplicates = list(module_sessions.aggregate([
        {"$match": {"active": True}},
        {"$sort": {"id": -1}},
        {"$group": {"_id": "$username", "ids": {"$push": "$id"}}},
        {"$match": {"ids.1": {"$exists": True}}},
    ]))
    for duplicate in duplicates:
        stale_ids = duplicate["ids"][1:]
        stale = list(module_sessions.find({"id": {"$in": stale_ids}}, {"module_id": 1}))
        for item in stale:
            modules.update_one({"id": item["module_id"], "occupied_by": duplicate["_id"]}, {"$set": {"status": "available", "occupied_by": None, "occupied_until": None}})
        module_sessions.update_many({"id": {"$in": stale_ids}}, {"$set": {"active": False, "ended_at": time.time()}})
    module_sessions.create_index([("username", ASCENDING)], unique=True, partialFilterExpression={"active": True}, name="one_active_session_per_user")
    balance_transactions.create_index([("username", ASCENDING), ("id", DESCENDING)], name="balance_user_id")
    admin_revenue_transactions.create_index([("id", DESCENDING)], name="revenue_id_desc")
    admin_revenue_transactions.create_index([("session_id", ASCENDING)], unique=True, partialFilterExpression={"session_id": {"$type": "number"}}, name="revenue_session_unique")
    admin_revenue_transactions.create_index([("collected", ASCENDING), ("collected_at", DESCENDING)], name="revenue_collected_date")

    admin_username = os.getenv("ADMIN_USERNAME", "tragic").strip().lower() or "tragic"
    admin_password = os.getenv("ADMIN_PASSWORD", "69")
    if (os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")) and not os.getenv("ADMIN_PASSWORD") and not users.find_one({"username": admin_username}):
        raise RuntimeError("Configura ADMIN_PASSWORD en Render antes del primer despliegue; no se creará un admin con contraseña predecible.")
    if not users.find_one({"username": admin_username}):
        users.insert_one({
            "_id": admin_username, "id": next_id("users"), "username": admin_username,
            "password_hash": generate_password_hash(admin_password), "role": "admin",
            "usage": "Administración de módulos", "balance": 0.0, "discount_percent": 0.0,
            "blocked": False, "avatar_data": None, "display_name": admin_username,
            "created_at": now_iso(),
        })
    admin_account.update_one(
        {"_id": 1},
        {"$setOnInsert": {"owner_username": admin_username, "balance": 0.0, "updated_at": time.time()}},
        upsert=True,
    )
    if modules.count_documents({}) == 0:
        for item in DEFAULT_MODULES:
            doc = {**item, "_id": item["id"], "created_at": now_iso(), "occupied_by": None, "occupied_until": None}
            modules.insert_one(doc)
    # Initialize counters from documents so imported SQLite records don't collide.
    for collection_name, collection in (
        ("users", users), ("module_sessions", module_sessions),
        ("balance_transactions", balance_transactions),
        ("admin_revenue_transactions", admin_revenue_transactions),
    ):
        max_id = collection.find_one(sort=[("id", DESCENDING)])
        if max_id and isinstance(max_id.get("id"), int):
            counters.update_one({"_id": collection_name}, {"$max": {"seq": max_id["id"]}}, upsert=True)


def release_expired_modules():
    now = time.time()
    expired = list(modules.find(
        {"status": "busy", "occupied_until": {"$ne": None, "$lte": now}},
        {"id": 1},
    ))
    ids = [item["id"] for item in expired]
    if not ids:
        return
    modules.update_many(
        {"id": {"$in": ids}, "status": "busy", "occupied_until": {"$lte": now}},
        {"$set": {"status": "available", "occupied_by": None, "occupied_until": None}},
    )
    module_sessions.update_many(
        {"module_id": {"$in": ids}, "active": True},
        {"$set": {"active": False, "ended_at": now}},
    )


def user_public(user):
    if not user:
        return None
    result = {key: value for key, value in user.items() if key not in ("_id", "password_hash")}
    result["balance"] = round(float(result.get("balance") or 0), 2)
    result["discount_percent"] = round(float(result.get("discount_percent") or 0), 2)
    result["blocked"] = bool(result.get("blocked", False))
    return result


def current_user():
    username = session.get("username")
    if not username:
        return None
    user = users.find_one({"username": username})
    if not user or (user.get("blocked") and user.get("role") != "admin"):
        session.clear()
        return None
    return user_public(user)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify({"ok": False, "error": "Necesitas iniciar sesión."}), 401
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"ok": False, "error": "Necesitas iniciar sesión."}), 401
        if user.get("role") != "admin":
            return jsonify({"ok": False, "error": "Solo el administrador puede hacer esto."}), 403
        return fn(*args, **kwargs)
    return wrapped


def module_payload(row, admin=False):
    if not row:
        return None
    item = {key: value for key, value in row.items() if key != "_id"}
    connectors = item.get("connectors") or "USB-C"
    if isinstance(connectors, str):
        connectors = [value.strip() for value in connectors.split(",") if value.strip()]
    item["connectors"] = connectors
    item["remaining_seconds"] = max(0, int(item["occupied_until"] - time.time())) if item.get("occupied_until") else 0
    if not admin:
        item.pop("occupied_by", None)
    return item


def calculate_charging_plan(package_id, battery_start, capacity_mah, device_max_watts, module_power, connector, package_limit_minutes):
    """Estimate a session using the package, module, phone and connector caps.

    This is a software estimate, not control of physical charger hardware. The
    returned session_minutes is the exact server-side occupied time; the target
    estimate can exceed that package's maximum duration.
    """
    if package_id not in PACKAGES:
        raise ValueError('Selecciona un paquete válido.')
    package = PACKAGES[package_id]
    battery = max(1, min(99, int(battery_start)))
    capacity = max(1000, min(30000, int(capacity_mah)))
    phone_watts = max(3, min(300, int(device_max_watts)))
    module_watts = max(3.0, min(300.0, float(module_power)))
    package_watts = int(package['max_watts'])
    connector = connector if connector in CONNECTOR_WATT_LIMITS else 'USB-C'
    effective_watts = max(3.0, min(package_watts, phone_watts, module_watts, CONNECTOR_WATT_LIMITS[connector]))
    efficiency = CONNECTOR_EFFICIENCY[connector]
    # Average-rate/taper factor is lower at higher state of charge.
    taper = 0.78 if battery < 50 else (0.68 if battery < 75 else 0.56)
    capacity_wh = capacity * 3.85 / 1000.0
    energy_needed_wh = capacity_wh * max(0, 90 - battery) / 100.0
    if energy_needed_wh <= 0:
        target_minutes = 1
        session_minutes = 1
        end_battery = battery
    else:
        battery_watts = max(0.1, effective_watts * efficiency * taper)
        target_minutes = max(1, int(__import__('math').ceil((energy_needed_wh / battery_watts) * 60.0 + 2.0)))
        try:
            session_limit = max(10, min(120, int(package_limit_minutes))) if package_id == 'custom' else int(package['minutes'])
        except (TypeError, ValueError):
            session_limit = int(package['minutes'])
        session_minutes = max(1, min(target_minutes, session_limit))
        charge_minutes = max(0, session_minutes - 2)
        delivered_wh = (charge_minutes / 60.0) * battery_watts
        end_battery = min(90, max(battery, int(battery + delivered_wh / capacity_wh * 100)))
    return {
        'package_max_watts': package_watts,
        'module_max_watts': round(module_watts, 1),
        'device_max_watts': phone_watts,
        'effective_watts': round(effective_watts, 1),
        'minutes_to_target': target_minutes,
        'session_minutes': session_minutes,
        'package_limit_minutes': session_limit if energy_needed_wh > 0 else (max(10, min(120, int(package_limit_minutes))) if package_id == 'custom' else int(package['minutes'])),
        'battery_end_estimate': end_battery,
        'target_reached_in_session': target_minutes <= (session_limit if energy_needed_wh > 0 else 1),
    }


def calculate_price(package_id, minutes, discount_percent):
    if package_id not in PACKAGES:
        raise ValueError('Selecciona un paquete válido.')
    package = PACKAGES[package_id]
    if package_id == 'custom':
        try:
            duration = max(10, min(120, int(minutes)))
        except (TypeError, ValueError):
            duration = package['minutes']
        base = float(duration)  # $1 MXN per minute for the custom package
    else:
        duration, base = int(package['minutes']), float(package['price'])
    discount = min(90.0, max(0.0, float(discount_percent or 0)))
    final_price = round(base * (1 - discount / 100), 2)
    return duration, round(base, 2), discount, final_price


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    try:
        client.admin.command("ping")
        return jsonify({"ok": True, "database": "connected"})
    except PyMongoError:
        return jsonify({"ok": False, "database": "disconnected"}), 503


@app.get("/api/network/ping")
def network_ping():
    return jsonify({"ok": True, "server_time": time.time()})


@app.get("/api/modules")
def get_modules():
    release_expired_modules()
    user = current_user() or {}
    rows = list(modules.find().sort("name", ASCENDING))
    return jsonify([module_payload(row, user.get("role") == "admin") for row in rows])


@app.get("/api/packages")
@login_required
def get_packages():
    user = current_user()
    items = []
    for package in PACKAGES.values():
        minutes, base, discount, final = calculate_price(package["id"], package["minutes"], user["discount_percent"])
        items.append({**package, "minutes": minutes, "base_price": base, "discount_percent": discount, "final_price": final})
    return jsonify({"packages": items, "balance": user["balance"], "discount_percent": user["discount_percent"]})


@app.get("/api/auth/me")
def auth_me():
    user = current_user()
    return jsonify({"authenticated": bool(user), "user": user})


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    user = users.find_one({"username": username})
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos."}), 401
    if user.get("blocked") and user.get("role") != "admin":
        return jsonify({"ok": False, "error": "Tu cuenta está bloqueada. Contacta al administrador."}), 403
    session["username"] = username
    session.permanent = True
    return jsonify({"ok": True, "user": current_user()})


@app.post("/api/auth/register")
def auth_register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    usage = str(data.get("usage", "")).strip()
    if len(username) < 3 or len(username) > 30:
        return jsonify({"ok": False, "error": "El usuario debe tener entre 3 y 30 caracteres."}), 400
    if len(password) < 4:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 4 caracteres."}), 400
    if not usage:
        return jsonify({"ok": False, "error": "Selecciona dónde usarás EcoBlack."}), 400
    try:
        user_id = next_id("users")
        users.insert_one({
            "_id": username, "id": user_id, "username": username,
            "password_hash": generate_password_hash(password), "role": "user", "usage": usage,
            "balance": WELCOME_BALANCE, "discount_percent": 0.0, "blocked": False,
            "avatar_data": None, "display_name": username, "created_at": now_iso(),
        })
    except DuplicateKeyError:
        return jsonify({"ok": False, "error": "Ese usuario ya existe."}), 409
    tx_id = next_id("balance_transactions")
    balance_transactions.insert_one({
        "_id": tx_id, "id": tx_id,
        "username": username, "kind": "welcome", "amount": WELCOME_BALANCE,
        "balance_after": WELCOME_BALANCE, "description": "Saldo de bienvenida de EcoBlack", "created_at": now_iso(),
    })
    session["username"] = username
    session.permanent = True
    return jsonify({"ok": True, "user": current_user()})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/profile")
@login_required
def profile_get():
    user = current_user()
    transactions = list(balance_transactions.find({"username": user["username"]}).sort("id", DESCENDING).limit(25))
    for item in transactions:
        item.pop("_id", None)
    user["transactions"] = transactions
    return jsonify({"profile": user})


@app.put("/api/profile")
@login_required
def profile_update():
    user = current_user(); data = request.get_json(silent=True) or {}
    display_name = str(data.get("display_name", user.get("display_name") or user["username"])).strip()[:40]
    avatar = data.get("avatar_data", user.get("avatar_data"))
    if avatar is not None:
        if not isinstance(avatar, str) or (avatar and not avatar.startswith("data:image/")):
            return jsonify({"ok": False, "error": "La foto debe ser una imagen."}), 400
        if len(avatar) > 2_500_000:
            return jsonify({"ok": False, "error": "La imagen pesa demasiado; elige una más pequeña."}), 413
    users.update_one({"username": user["username"]}, {"$set": {"display_name": display_name or user["username"], "avatar_data": avatar}})
    return jsonify({"ok": True, "profile": user_public(users.find_one({"username": user["username"]}))})


@app.get("/api/profile/transactions")
@login_required
def profile_transactions():
    user = current_user(); rows = list(balance_transactions.find({"username": user["username"]}).sort("id", DESCENDING).limit(50))
    for item in rows: item.pop("_id", None)
    return jsonify({"transactions": rows})


@app.post("/api/modules")
@admin_required
def create_module():
    data = request.get_json(silent=True) or {}; name = str(data.get("name", "")).strip()
    try: lat, lng = float(data.get("lat")), float(data.get("lng"))
    except (TypeError, ValueError): return jsonify({"ok": False, "error": "Latitud y longitud inválidas."}), 400
    if not name or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return jsonify({"ok": False, "error": "Completa un nombre y coordenadas válidas."}), 400
    connectors = data.get("connectors", ["USB-C"])
    if isinstance(connectors, str): connectors = [connectors]
    connectors = [str(value).strip() for value in connectors if str(value).strip()] or ["USB-C"]
    module_id = f"EB-{int(time.time()*1000)%100000:05d}"
    while modules.find_one({"id": module_id}): module_id = f"EB-{secrets.randbelow(90000)+10000}"
    status = data.get("status", "available")
    if status not in ("available", "busy"): status = "available"
    doc = {"_id": module_id, "id": module_id, "name": name, "lat": lat, "lng": lng,
           "status": status, "power": str(data.get("power", "30 W")), "connectors": connectors,
           "created_by": session["username"], "occupied_by": None, "occupied_until": None, "created_at": now_iso()}
    modules.insert_one(doc)
    return jsonify({"ok": True, "module": module_payload(doc, True)}), 201


@app.put("/api/modules/<module_id>")
@admin_required
def update_module(module_id):
    data = request.get_json(silent=True) or {}; release_expired_modules()
    row = modules.find_one({"id": module_id})
    if not row: return jsonify({"ok": False, "error": "Módulo no encontrado."}), 404
    if row.get("occupied_until") and row["occupied_until"] > time.time():
        return jsonify({"ok": False, "error": "Ese módulo está ocupado por una sesión activa."}), 409
    connectors = data.get("connectors", row.get("connectors", ["USB-C"]))
    if isinstance(connectors, str): connectors = [v.strip() for v in connectors.split(",") if v.strip()]
    try: lat, lng = float(data.get("lat", row["lat"])), float(data.get("lng", row["lng"]))
    except (TypeError, ValueError): return jsonify({"ok": False, "error": "Coordenadas inválidas."}), 400
    status = str(data.get("status", row.get("status", "available")))
    if status not in ("available", "busy"): status = row.get("status", "available")
    modules.update_one({"id": module_id}, {"$set": {
        "name": str(data.get("name", row["name"])).strip(), "lat": lat, "lng": lng,
        "status": status, "power": str(data.get("power", row["power"])),
        "connectors": connectors, "updated_at": now_iso(),
    }})
    return jsonify({"ok": True, "module": module_payload(modules.find_one({"id": module_id}), True)})


@app.delete("/api/modules/<module_id>")
@admin_required
def delete_module(module_id):
    row = modules.find_one({"id": module_id})
    if not row: return jsonify({"ok": False, "error": "Módulo no encontrado."}), 404
    if row.get("occupied_until") and row["occupied_until"] > time.time():
        return jsonify({"ok": False, "error": "No puedes quitar un módulo ocupado."}), 409
    modules.delete_one({"id": module_id}); module_sessions.delete_many({"module_id": module_id})
    return jsonify({"ok": True})


@app.post("/api/modules/<module_id>/connect")
@login_required
def connect_module(module_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    if not user or user.get("blocked"):
        return jsonify({"ok": False, "error": "Tu cuenta no puede iniciar sesiones."}), 403

    package_id = str(data.get("package_id", "basic"))
    raw_discount = data.get("use_discount", True)
    use_discount = raw_discount is True or str(raw_discount).strip().lower() in ("true", "1", "yes", "si", "sí")
    payment_method = str(data.get("payment_method", "wallet")).strip().lower()
    if payment_method not in ("wallet", "card_demo", "cash"):
        return jsonify({"ok": False, "error": "Selecciona un método de pago válido."}), 400
    if payment_method == "card_demo":
        return jsonify({"ok": False, "error": "El pago con tarjeta aún no está conectado a una pasarela bancaria. Elige Saldo EcoBlack o Efectivo."}), 400

    try:
        discount_to_apply = float(user.get("discount_percent", 0)) if use_discount else 0.0
        package_limit_minutes, base_cost, discount_pct, payable = calculate_price(
            package_id, data.get("minutes", PACKAGES.get(package_id, {}).get("minutes", 15)), discount_to_apply
        )
        battery_start = max(1, min(99, int(data.get("battery_start", 35))))
        capacity_mah = max(1000, min(30000, int(data.get("device_capacity_mah", 4200))))
        device_max_watts = max(3, min(300, int(data.get("device_max_watts", 25))))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Revisa la configuración del dispositivo o el paquete."}), 400

    release_expired_modules()
    now = time.time()
    timestamp = now_iso()
    try:
        with client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                live_user = users.find_one({"username": user["username"]}, session=mongo_session)
                if not live_user or live_user.get("blocked"):
                    raise ApiError("Tu cuenta no puede iniciar sesiones.", 403)
                module = modules.find_one({"id": module_id}, session=mongo_session)
                if not module:
                    raise ApiError("Módulo no encontrado.", 404)
                if module.get("status") != "available":
                    raise ApiError("Este módulo está ocupado. Elige otro.", 409)

                requested_connector = str(data.get("connector", "USB-C")).strip()
                supported_connectors = module.get("connectors") or ["USB-C"]
                if isinstance(supported_connectors, str):
                    supported_connectors = [x.strip() for x in supported_connectors.split(",") if x.strip()]
                if requested_connector not in supported_connectors:
                    raise ApiError(
                        f"Este módulo no ofrece {requested_connector}. Conectores disponibles: {', '.join(supported_connectors)}.", 409
                    )
                if module_sessions.find_one({"username": user["username"], "active": True}, session=mongo_session):
                    raise ApiError("Ya tienes una sesión activa. Desconéctala antes de conectar otro módulo.", 409)

                try:
                    module_watts = float(str(module.get("power", "30 W")).lower().replace("w", "").strip().replace(",", "."))
                    charging_plan = calculate_charging_plan(
                        package_id, battery_start, capacity_mah, device_max_watts, module_watts,
                        requested_connector, package_limit_minutes,
                    )
                except (ValueError, TypeError) as exc:
                    raise ApiError(f"No se pudo calcular la carga: {exc}", 400)

                amount_paid = 0.0
                amount_due = 0.0
                current_balance = round(float(live_user.get("balance") or 0), 2)
                if payment_method == "wallet":
                    debited = users.update_one(
                        {"username": user["username"], "balance": {"$gte": payable}, "blocked": {"$ne": True}},
                        {"$inc": {"balance": -payable}}, session=mongo_session,
                    )
                    if debited.modified_count != 1:
                        raise ApiError(f"Saldo insuficiente. Tienes ${current_balance:.2f} y el paquete cuesta ${payable:.2f}.", 402)
                    amount_paid = payable
                    payment_status = "paid_wallet"
                else:
                    amount_due = payable
                    payment_status = "pending_cash"

                session_minutes = int(charging_plan["session_minutes"])
                until = now + session_minutes * 60
                reserved = modules.update_one(
                    {"id": module_id, "status": "available"},
                    {"$set": {"status": "busy", "occupied_by": user["username"], "occupied_until": until}},
                    session=mongo_session,
                )
                if reserved.modified_count != 1:
                    raise ApiError("Otro usuario acaba de ocupar este módulo. Actualiza el mapa e inténtalo de nuevo.", 409)

                session_id = next_id("module_sessions", mongo_session)
                session_payload = {
                    "_id": session_id, "id": session_id, "module_id": module_id,
                    "username": user["username"], "module_name": module["name"],
                    "device": str(data.get("device", "Dispositivo"))[:80],
                    "connector": requested_connector, "package_name": PACKAGES[package_id]["name"],
                    "minutes": session_minutes, "started_at": now, "ended_at": None, "active": True,
                    "amount_paid": amount_paid, "amount_due": amount_due,
                    "battery_start": battery_start, "device_capacity_mah": capacity_mah,
                    "device_max_watts": device_max_watts, "estimated_minutes": charging_plan["minutes_to_target"],
                    "minutes_to_target": charging_plan["minutes_to_target"],
                    "package_max_watts": charging_plan["package_max_watts"],
                    "effective_watts": charging_plan["effective_watts"],
                    "battery_end_estimate": charging_plan["battery_end_estimate"],
                    "package_limit_minutes": charging_plan["package_limit_minutes"],
                    "target_reached_in_session": charging_plan["target_reached_in_session"],
                    "payment_method": payment_method, "payment_status": payment_status,
                    "discount_percent": discount_pct, "use_discount": use_discount,
                    "occupied_until": until, "until": until, "created_at": timestamp,
                }
                module_sessions.insert_one(session_payload, session=mongo_session)
                balance_doc = users.find_one({"username": user["username"]}, session=mongo_session)
                balance_after = round(float(balance_doc.get("balance") or 0), 2)

                if payment_method == "wallet":
                    tx_id = next_id("balance_transactions", mongo_session)
                    balance_transactions.insert_one({
                        "_id": tx_id, "id": tx_id, "username": user["username"],
                        "kind": "charge", "amount": -payable, "balance_after": balance_after,
                        "description": f"Paquete {PACKAGES[package_id]['name']} · {module['name']} · descuento {discount_pct:.0f}%",
                        "created_at": timestamp,
                    }, session=mongo_session)

                if user.get("role") != "admin":
                    collected = payment_method == "wallet"
                    revenue_id = next_id("admin_revenue_transactions", mongo_session)
                    admin_revenue_transactions.insert_one({
                        "_id": revenue_id, "id": revenue_id, "session_id": session_id,
                        "payer_username": user["username"], "module_id": module_id,
                        "module_name": module["name"], "package_name": PACKAGES[package_id]["name"],
                        "gross_amount": base_cost, "discount_amount": max(0, round(base_cost-payable, 2)),
                        "amount": payable, "payment_method": payment_method,
                        "payment_status": payment_status, "collected": collected,
                        "created_at": now, "collected_at": now if collected else None,
                        "received_by": os.getenv("ADMIN_USERNAME", "tragic") if collected else None,
                    }, session=mongo_session)
                    if collected:
                        admin_account.update_one({"_id": 1}, {"$inc": {"balance": payable}, "$set": {"updated_at": now}}, session=mongo_session)

                updated_module = modules.find_one({"id": module_id}, session=mongo_session)
    except ApiError as error:
        current = users.find_one({"username": user["username"]}) or user
        return jsonify({"ok": False, "error": error.message, "balance": round(float(current.get("balance") or 0), 2), "price": payable if "payable" in locals() else 0}), error.status
    except DuplicateKeyError:
        return jsonify({"ok": False, "error": "Ya tienes una sesión activa o el módulo acaba de ocuparse. Actualiza el mapa e inténtalo de nuevo."}), 409
    except PyMongoError:
        app.logger.exception("Error en transacción MongoDB al conectar módulo")
        return jsonify({"ok": False, "error": "No se pudo completar la conexión. No se confirmó el cobro; inténtalo de nuevo."}), 503

    payload = {key: value for key, value in session_payload.items() if key != "_id"}
    payload["remaining_seconds"] = max(0, int(until - time.time()))
    return jsonify({
        "ok": True, "balance": balance_after, "charged": amount_paid, "amount_due": amount_due,
        "base_price": base_cost, "payable": payable, "payment_method": payment_method,
        "payment_status": payment_status, "discount_percent": discount_pct,
        "session": payload, "module": module_payload(updated_module, user.get("role") == "admin"),
    })

@app.post("/api/modules/<module_id>/disconnect")
@login_required
def disconnect_module(module_id):
    user = current_user(); row = modules.find_one({"id": module_id})
    if not row: return jsonify({"ok": False, "error": "Módulo no encontrado."}), 404
    if row.get("occupied_by") != user["username"] and user.get("role") != "admin":
        return jsonify({"ok": False, "error": "Solo la sesión que conectó el módulo puede desconectarlo."}), 403
    now = time.time()
    modules.update_one({"id": module_id}, {"$set": {"status": "available", "occupied_by": None, "occupied_until": None}})
    module_sessions.update_many({"module_id": module_id, "active": True}, {"$set": {"active": False, "ended_at": now}})
    updated = modules.find_one({"id": module_id})
    return jsonify({"ok": True, "module": module_payload(updated, user.get("role") == "admin")})


@app.get("/api/sessions/active")
@login_required
def active_session():
    user = current_user(); release_expired_modules()
    row = module_sessions.find_one({"username": user["username"], "active": True}, sort=[("id", DESCENDING)])
    if not row: return jsonify({"active": False})
    mod = modules.find_one({"id": row["module_id"]}) or {}
    payload = {key: value for key, value in row.items() if key != "_id"}
    payload["module_name"] = mod.get("name", row["module_id"]); payload["status"] = mod.get("status")
    payload["occupied_until"] = mod.get("occupied_until") or row.get("occupied_until")
    payload["remaining_seconds"] = max(0, int((payload.get("occupied_until") or time.time()) - time.time()))
    return jsonify({"active": True, "session": payload})


@app.get("/api/admin/revenue")
@admin_required
def admin_revenue():
    account = admin_account.find_one({"_id": 1}) or {"owner_username": "tragic", "balance": 0}
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    start_of_next_day = start_of_day + 86400
    pipeline = [{"$group": {"_id": None,
        "collected_total": {"$sum": {"$cond": ["$collected", {"$ifNull": ["$amount", 0]}, 0]}},
        "payments_total": {"$sum": {"$cond": ["$collected", 1, 0]}},
        "collected_today": {"$sum": {"$cond": [{"$and": ["$collected", {"$gte": ["$collected_at", start_of_day]}, {"$lt": ["$collected_at", start_of_next_day]}]}, {"$ifNull": ["$amount", 0]}, 0]}},
        "payments_today": {"$sum": {"$cond": [{"$and": ["$collected", {"$gte": ["$collected_at", start_of_day]}, {"$lt": ["$collected_at", start_of_next_day]}]}, 1, 0]}},
        "cash_pending": {"$sum": {"$cond": [{"$and": [{"$eq": ["$collected", False]}, {"$eq": ["$payment_status", "pending_cash"]}]}, {"$ifNull": ["$amount", 0]}, 0]}},
        "card_unprocessed": {"$sum": {"$cond": [{"$and": [{"$eq": ["$collected", False]}, {"$eq": ["$payment_status", "demo_not_processed"]}]}, {"$ifNull": ["$amount", 0]}, 0]}},
    }}]
    summary = next(db["admin_revenue_transactions"].aggregate(pipeline), {})
    keys = ("collected_today", "collected_total", "cash_pending", "card_unprocessed", "payments_today", "payments_total")
    normalized = {key: (round(float(summary.get(key) or 0), 2) if key in ("collected_today", "collected_total", "cash_pending", "card_unprocessed") else int(summary.get(key) or 0)) for key in keys}
    fields = ("id", "session_id", "payer_username", "module_id", "module_name", "package_name", "gross_amount", "discount_amount", "amount", "payment_method", "payment_status", "collected", "created_at", "collected_at", "received_by")
    rows = [{key: row.get(key) for key in fields} for row in admin_revenue_transactions.find().sort("id", DESCENDING).limit(50)]
    return jsonify({"ok": True, "account": {"owner_username": account.get("owner_username", "tragic"), "balance": round(float(account.get("balance") or 0), 2)}, "summary": normalized, "transactions": rows})


@app.post("/api/admin/revenue/<int:revenue_id>/collect")
@admin_required
def admin_collect_cash(revenue_id):
    row = admin_revenue_transactions.find_one({"id": revenue_id})
    if not row: return jsonify({"ok": False, "error": "Movimiento de cobro no encontrado."}), 404
    if row.get("collected"): return jsonify({"ok": False, "error": "Este pago ya fue confirmado."}), 409
    if row.get("payment_method") != "cash" or row.get("payment_status") != "pending_cash":
        return jsonify({"ok": False, "error": "Solo se pueden confirmar pagos en efectivo pendientes. La tarjeta necesita una pasarela real."}), 400
    now = time.time(); amount = round(float(row.get("amount") or 0), 2)
    try:
        with client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                result = admin_revenue_transactions.update_one({"id": revenue_id, "collected": False, "payment_status": "pending_cash"}, {"$set": {"collected": True, "payment_status": "paid_cash", "collected_at": now, "received_by": session["username"]}}, session=mongo_session)
                if result.modified_count != 1: raise ApiError("Este pago ya fue confirmado por otra operación.", 409)
                admin_account.update_one({"_id": 1}, {"$inc": {"balance": amount}, "$set": {"updated_at": now}}, session=mongo_session)
                if row.get("session_id") is not None:
                    module_sessions.update_one({"id": row["session_id"]}, {"$set": {"payment_status": "paid_cash", "amount_paid": amount, "amount_due": 0}}, session=mongo_session)
    except ApiError as error:
        return jsonify({"ok": False, "error": error.message}), error.status
    except PyMongoError:
        app.logger.exception("Error confirmando pago en efectivo")
        return jsonify({"ok": False, "error": "No se pudo confirmar el pago. Inténtalo de nuevo."}), 503
    acc = admin_account.find_one({"_id": 1}) or {"balance": 0}
    return jsonify({"ok": True, "collected": amount, "admin_balance": round(float(acc.get("balance") or 0), 2)})


@app.get("/api/admin/users")
@admin_required
def admin_users():
    rows = list(users.find().sort("created_at", DESCENDING))
    return jsonify({"users": [user_public(row) for row in rows]})


@app.post("/api/admin/users/<username>/balance")
@admin_required
def admin_add_balance(username):
    data = request.get_json(silent=True) or {}
    try: amount = round(float(data.get("amount", 0)), 2)
    except (TypeError, ValueError): amount = 0
    if not 0 < amount <= 100000: return jsonify({"ok": False, "error": "El saldo debe ser mayor que $0 y no superar $100,000."}), 400
    try:
        with client.start_session() as mongo_session:
            with mongo_session.start_transaction():
                row = users.find_one({"username": username}, session=mongo_session)
                if not row: raise ApiError("Usuario no encontrado.", 404)
                users.update_one({"username": username}, {"$inc": {"balance": amount}}, session=mongo_session)
                fresh = users.find_one({"username": username}, session=mongo_session)
                tx_id = next_id("balance_transactions", mongo_session)
                balance_transactions.insert_one({"_id": tx_id, "id": tx_id, "username": username, "kind": "admin_topup", "amount": amount, "balance_after": round(float(fresh.get("balance") or 0), 2), "description": f"Saldo agregado por {session['username']}", "created_at": now_iso()}, session=mongo_session)
    except ApiError as error: return jsonify({"ok": False, "error": error.message}), error.status
    except PyMongoError:
        app.logger.exception("Error al agregar saldo")
        return jsonify({"ok": False, "error": "No se pudo agregar saldo."}), 503
    return jsonify({"ok": True, "username": username, "balance": round(float(fresh.get("balance") or 0), 2)})


@app.put("/api/admin/users/<username>/discount")
@admin_required
def admin_set_discount(username):
    data = request.get_json(silent=True) or {}
    try: percent = float(data.get("discount_percent", 0))
    except (TypeError, ValueError): percent = -1
    if not 0 <= percent <= 90: return jsonify({"ok": False, "error": "El descuento debe estar entre 0% y 90%."}), 400
    result = users.update_one({"username": username}, {"$set": {"discount_percent": round(percent, 2)}})
    if not result.matched_count: return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404
    return jsonify({"ok": True, "username": username, "discount_percent": round(percent, 2)})


@app.put("/api/admin/users/<username>/blocked")
@admin_required
def admin_set_blocked(username):
    data = request.get_json(silent=True) or {}; blocked = bool(data.get("blocked", False))
    if username == os.getenv("ADMIN_USERNAME", "tragic").strip().lower(): return jsonify({"ok": False, "error": "La cuenta admin principal no se puede bloquear."}), 400
    row = users.find_one({"username": username})
    if not row: return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404
    if row.get("role") == "admin": return jsonify({"ok": False, "error": "No se puede bloquear otra cuenta administradora."}), 400
    users.update_one({"username": username}, {"$set": {"blocked": blocked}})
    if blocked:
        now = time.time()
        active = list(module_sessions.find({"username": username, "active": True}, {"module_id": 1}))
        ids = [item["module_id"] for item in active]
        if ids: modules.update_many({"id": {"$in": ids}}, {"$set": {"status": "available", "occupied_by": None, "occupied_until": None}})
        module_sessions.update_many({"username": username, "active": True}, {"$set": {"active": False, "ended_at": now}})
    return jsonify({"ok": True, "username": username, "blocked": blocked})


@app.get("/manifest.webmanifest")
def manifest(): return app.send_static_file("manifest.webmanifest")

@app.get("/sw.js")
def service_worker(): return app.send_static_file("sw.js")

@app.errorhandler(413)
def file_too_large(_): return jsonify({"ok": False, "error": "El archivo es demasiado grande."}), 413


try:
    init_db()
except Exception:
    app.logger.exception("No se pudo conectar con MongoDB Atlas. Revisa MONGODB_URI y la lista de acceso IP.")
    raise

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
