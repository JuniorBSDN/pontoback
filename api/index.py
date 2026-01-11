from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os
import json
import base64

app = Flask(__name__)
CORS(app)

# --- INICIALIZAÇÃO FIREBASE ---
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- HELPER BASE64 ---
def btoa(s): return base64.b64encode(s.encode()).decode()


# --- 1. ROTAS DE GESTÃO (index.html) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        nova_empresa = {
            "nome_fantasia": dados.get('nome'),
            "cnpj": dados.get('cnpj'),
            "plano": dados.get('plano', 'basico'),
            "status": "ativo",
            "data_cadastro": datetime.now()
        }
        doc_ref = db.collection('clientes').add(nova_empresa)
        return jsonify({"id": doc_ref[1].id, "mensagem": "Sucesso"}), 201

    # GET: Listar todas
    docs = db.collection('clientes').stream()
    return jsonify([{**d.to_dict(), "id": d.id} for d in docs]), 200


@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def acoes_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "removido"}), 200

    # PUT: Atualizar status ou dados
    dados = request.json
    doc_ref.update(dados)
    return jsonify({"status": "atualizado"}), 200


# --- 2. ROTAS DO TABLET (tablet.html) ---

@app.route('/api/check-status/<id>', methods=['GET'])
def check_status(id):
    doc = db.collection('clientes').document(id).get()
    if not doc.exists:
        return jsonify({"erro": "Empresa não encontrada"}), 404
    return jsonify(doc.to_dict()), 200


@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        id_farmacia = dados.get('id_cliente')  # Ajustado para bater com tablet.html

        ponto = {
            "funcionario_id": dados.get('id_funcionario'),
            "data_hora_servidor": datetime.now(),
            "timestamp_local": dados.get('timestamp_local'),  # Enviado pelo tablet
            "geo": dados.get('geo', None),
            "status": "OK"
        }

        # Gravação na sub-coleção privada
        db.collection('clientes').document(id_farmacia).collection('registros_ponto').add(ponto)
        return jsonify({"status": "Ponto registrado"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 400


# --- 3. RELATÓRIO AFD (PORTARIA 671) ---
@app.route('/api/clientes/<id_farmacia>/afd', methods=['GET'])
def gerar_dados_afd(id_farmacia):
    docs = db.collection('clientes').document(id_farmacia).collection('registros_ponto').order_by(
        "data_hora_servidor").stream()
    registros = []
    for d in docs:
        data = d.to_dict()
        dt = data['data_hora_servidor']
        linha = f"0000000013{dt.strftime('%d%m%Y%H%M')}{data['funcionario_id'].zfill(12)}"
        registros.append(linha)
    return jsonify({"arquivo_afd": "\n".join(registros)}), 200


if __name__ == '__main__':
    app.run(debug=True)