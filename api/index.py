from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import os

app = Flask(__name__)
CORS(app)

# 🔥 Firestore
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# ================= UTIL =================

def doc_to_dict(doc):
    d = doc.to_dict()
    d["id"] = doc.id
    return d


# ================= ADMIN =================

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    if data.get("usuario") == "admin" and data.get("senha") == "1234":
        return jsonify({"ok": True})
    return jsonify({"erro": "Acesso negado"}), 401


# ================= CLIENTES =================

@app.route("/api/clientes", methods=["GET"])
def listar_clientes():
    docs = db.collection("clientes").stream()
    return jsonify([doc_to_dict(doc) for doc in docs])


@app.route("/api/clientes", methods=["POST"])
def criar_cliente():
    data = request.json
    ref = db.collection("clientes").add(data)
    return jsonify({"ok": True, "id": ref[1].id})


@app.route("/api/clientes/<id>", methods=["PUT"])
def atualizar_cliente(id):
    ref = db.collection("clientes").document(id)
    if not ref.get().exists:
        return jsonify({"erro": "Cliente não encontrado"}), 404
    ref.update(request.json)
    return jsonify({"ok": True})


@app.route("/api/clientes/<id>", methods=["DELETE"])
def deletar_cliente(id):
    ref = db.collection("clientes").document(id)
    if not ref.get().exists:
        return jsonify({"erro": "Cliente não encontrado"}), 404
    ref.delete()
    return jsonify({"ok": True})


@app.route("/api/clientes/login-tablet", methods=["POST"])
def login_tablet():
    data = request.json
    docs = db.collection("clientes") \
        .where("cnpj", "==", data["cnpj"]) \
        .where("senha", "==", data["senha"]) \
        .stream()

    for doc in docs:
        d = doc_to_dict(doc)
        return jsonify(d)

    return jsonify({"erro": "Unidade não encontrada"}), 404


@app.route("/api/clientes/ativar-dispositivo", methods=["POST"])
def ativar_dispositivo():
    data = request.json
    db.collection("dispositivos").add({
        "cliente_id": data["cliente_id"],
        "machine_id": data["machine_id"],
        "modelo": data.get("modelo"),
        "ativado_em": datetime.utcnow()
    })
    return jsonify({"ok": True})


# ================= FUNCIONÁRIOS =================

@app.route("/api/funcionarios/<cliente_id>", methods=["GET"])
def listar_funcionarios(cliente_id):
    docs = db.collection("funcionarios") \
        .where("cliente_id", "==", cliente_id) \
        .stream()
    return jsonify([doc_to_dict(doc) for doc in docs])


@app.route("/api/funcionarios", methods=["POST"])
def criar_funcionario():
    data = request.json
    db.collection("funcionarios").document(data["cpf"]).set(data)
    return jsonify({"ok": True})


@app.route("/api/funcionarios/detalhe/<cpf>", methods=["PUT"])
def atualizar_funcionario(cpf):
    ref = db.collection("funcionarios").document(cpf)
    if not ref.get().exists:
        return jsonify({"erro": "Funcionário não encontrado"}), 404
    ref.update(request.json)
    return jsonify({"ok": True})


@app.route("/api/funcionarios/detalhe/<cpf>", methods=["DELETE"])
def deletar_funcionario(cpf):
    ref = db.collection("funcionarios").document(cpf)
    if not ref.get().exists:
        return jsonify({"erro": "Funcionário não encontrado"}), 404
    ref.delete()
    return jsonify({"ok": True})


# ================= PONTO =================

@app.route("/api/ponto/registrar", methods=["POST"])
def registrar_ponto():
    data = request.json
    cpf = data["id_funcionario"]
    cliente_id = data["id_cliente"]

    agora = datetime.utcnow()

    pontos_ref = db.collection("pontos")
    ultimos = pontos_ref \
        .where("cpf", "==", cpf) \
        .order_by("data", direction=firestore.Query.DESCENDING) \
        .limit(1).stream()

    tipo = "ENTRADA"
    horas = 0

    for p in ultimos:
        ultimo = p.to_dict()
        if ultimo["tipo"] == "ENTRADA":
            tipo = "SAIDA"
            entrada = ultimo["data"]
            horas = round((agora - entrada).total_seconds() / 3600, 2)

    novo = {
        "cpf": cpf,
        "cliente_id": cliente_id,
        "data": agora,
        "tipo": tipo,
        "machine_id": data.get("machine_id"),
        "geo": data.get("geo"),
        "timestamp_local": data.get("timestamp_local"),
        "horas_trabalhadas": horas
    }

    pontos_ref.add(novo)

    return jsonify({
        "ok": True,
        "tipo": tipo,
        "horas": horas,
        "funcionario": cpf
    })


@app.route("/api/ponto/funcionario/<cpf>", methods=["GET"])
def relatorio_funcionario(cpf):
    docs = db.collection("pontos") \
        .where("cpf", "==", cpf) \
        .stream()

    return jsonify([doc_to_dict(doc) for doc in docs])
