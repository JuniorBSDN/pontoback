import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app)

# --- CONFIGURAÇÃO FIREBASE ---
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        # Para teste local
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- ROTAS ADMIN (index.html) ---

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
        return jsonify({"id": doc_ref[1].id, "status": "sucesso"}), 201

    docs = db.collection('clientes').stream()
    return jsonify([{**d.to_dict(), "id": d.id} for d in docs]), 200

@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def acoes_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "removido"}), 200
    
    dados = request.json
    doc_ref.update(dados)
    return jsonify({"status": "atualizado"}), 200

# --- ROTAS TABLET (tablet.html) ---

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        id_farmacia = dados.get('id_cliente')
        
        # Validação de Status da Empresa
        doc = db.collection('clientes').document(id_farmacia).get()
        if not doc.exists or doc.to_dict().get('status') != 'ativo':
            return jsonify({"erro": "Empresa bloqueada ou não encontrada"}), 403

        ponto = {
            "funcionario_id": str(dados.get('id_funcionario')),
            "data_hora_servidor": datetime.now(),
            "timestamp_local": dados.get('timestamp_local'),
            "geo": dados.get('geo'),
            "status": "OK"
        }

        db.collection('clientes').document(id_farmacia).collection('registros_ponto').add(ponto)
        return jsonify({"status": "Ponto registrado com sucesso"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 400

# --- RELATÓRIO AFD (PORTARIA 671) ---
@app.route('/api/clientes/<id_farmacia>/afd', methods=['GET'])
def gerar_afd(id_farmacia):
    docs = db.collection('clientes').document(id_farmacia).collection('registros_ponto').order_by("data_hora_servidor").stream()
    
    linhas = []
    for d in docs:
        data = d.to_dict()
        dt = data['data_hora_servidor']
        # Formato simplificado AFD: ID(12 digitos) + Data/Hora
        linha = f"0000000013{dt.strftime('%d%m%Y%H%M')}{str(data['funcionario_id']).zfill(12)}"
        linhas.append(linha)
    
    response = make_response("\n".join(linhas))
    response.headers["Content-Disposition"] = f"attachment; filename=AFD_{id_farmacia}.txt"
    response.headers["Content-type"] = "text/plain"
    return response

if __name__ == '__main__':
    app.run(debug=True)
