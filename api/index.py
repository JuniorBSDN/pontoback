import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
CORS(app)

# 1. Configuração do Firebase
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")
if FIREBASE_CONFIG:
    cred = credentials.Certificate(json.loads(FIREBASE_CONFIG))
else:
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Função para garantir o horário de Brasília (UTC-3)
def get_agora_br():
    return datetime.now(timezone(timedelta(hours=-3)))

# --- ROTAS DE CLIENTES/UNIDADES (index.html) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
        # Garante que o campo usado no login exista
        if 'nome' in dados and 'nome_fantasia' not in dados:
            dados['nome_fantasia'] = dados['nome']
        doc_ref.set(dados)
        return jsonify(dados), 201
    
    docs = db.collection('clientes').stream()
    return jsonify([doc.to_dict() for doc in docs])

@app.route('/api/clientes/<id>', methods=['GET', 'PUT', 'DELETE'])
def detalhe_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'GET':
        doc = doc_ref.get()
        return jsonify(doc.to_dict()) if doc.exists else ({'erro': 'Não encontrado'}, 404)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"})
    doc_ref.delete()
    return jsonify({"status": "excluido"})

# --- ROTA DE LOGIN (gestor.html e tablet.html) ---

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_unidade():
    dados = request.json
    cnpj_input = "".join(filter(str.isdigit, str(dados.get('cnpj', ''))))
    senha_input = str(dados.get('senha', '')).strip()

    docs = db.collection('clientes').stream()
    for doc in docs:
        c = doc.to_dict()
        cnpj_banco = "".join(filter(str.isdigit, str(c.get('cnpj', ''))))
        # Verifica campo 'senha_acesso' conforme definido no seu index.html
        if cnpj_banco == cnpj_input and str(c.get('senha_acesso')) == senha_input:
            return jsonify({
                "id": c['id'], 
                "nome": c.get('nome_fantasia', c.get('nome'))
            })
    return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401

@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    dados = request.json # {cliente_id, machine_id, etc}
    id_cliente = dados.get('cliente_id')
    db.collection('clientes').document(id_cliente).collection('dispositivos').add(dados)
    return jsonify({"status": "ativado"})

# --- ROTAS DE FUNCIONÁRIOS (gestor.html) ---

@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados['cpf'])))
    dados['cpf'] = cpf
    # Salva com o CPF como ID para o tablet encontrar rápido
    db.collection('funcionarios').document(cpf).set(dados)
    return jsonify(dados), 201

@app.route('/api/funcionarios/<param>', methods=['GET', 'PUT', 'DELETE'])
def gerenciar_funcionarios(param):
    if request.method == 'GET':
        # Se o param for o ID da unidade, lista todos os funcionários dela
        docs = db.collection('funcionarios').where('cliente_id', '==', param).stream()
        return jsonify([doc.to_dict() for doc in docs])
    
    doc_ref = db.collection('funcionarios').document(param)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"})
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"})

# --- ROTAS DE PONTO (tablet.html e modal relatório) ---

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))
    
    func_ref = db.collection('funcionarios').document(cpf).get()
    if not func_ref.exists:
        return jsonify({"erro": "CPF não cadastrado"}), 404
    
    func_data = func_ref.to_dict()
    agora = get_agora_br()

    # Busca pontos sem order_by para evitar erro de índice
    docs = db.collection('pontos').where('id_funcionario', '==', cpf).get()
    pontos = [p.to_dict() for p in docs]
    pontos.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

    tipo = "ENTRADA"
    horas = 0
    if pontos and pontos[0]['tipo'] == "ENTRADA":
        tipo = "SAÍDA"
        inicio = datetime.fromisoformat(pontos[0]['timestamp_servidor'])
        if inicio.tzinfo is None: inicio = inicio.replace(tzinfo=timezone(timedelta(hours=-3)))
        horas = round((agora - inicio).total_seconds() / 3600, 2)

    novo_ponto = {
        "id_funcionario": cpf,
        "funcionario": func_data['nome'],
        "id_cliente": dados.get('id_cliente'),
        "tipo": tipo,
        "timestamp_servidor": agora.isoformat(),
        "horas_trabalhadas": horas
    }
    db.collection('pontos').add(novo_ponto)
    return jsonify({"tipo": tipo, "funcionario": func_data['nome'], "horas": horas})

@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio_ponto(cpf):
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    docs = db.collection('pontos').where('id_funcionario', '==', cpf_limpo).get()
    lista = [d.to_dict() for d in docs]
    lista.sort(key=lambda x: x['timestamp_servidor'])
    return jsonify(lista)

if __name__ == '__main__':
    app.run(debug=True)
