import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
# Configuração do CORS para permitir que o site acesse a API
CORS(app)

# 1. Configuração do Firebase
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")

if FIREBASE_CONFIG:
    cred_dict = json.loads(FIREBASE_CONFIG)
    cred = credentials.Certificate(cred_dict)
else:
    # Verifique se o arquivo serviceAccountKey.json está na mesma pasta
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred)
db = firestore.client()


# --- ROTAS DE CLIENTES (UNIDADES) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
        # Garante que 'nome_fantasia' seja salvo conforme esperado pelo frontend
        if 'nome' in dados and 'nome_fantasia' not in dados:
            dados['nome_fantasia'] = dados['nome']
        doc_ref.set(dados)
        return jsonify(dados), 201

    docs = db.collection('clientes').stream()
    return jsonify([doc.to_dict() for doc in docs])


@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def editar_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'PUT':
        dados = request.json
        if 'nome' in dados: dados['nome_fantasia'] = dados['nome']
        doc_ref.update(dados)
        return jsonify({"status": "atualizado"})
    doc_ref.delete()
    return jsonify({"status": "excluido"})


@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    dados = request.json
    docs = db.collection('clientes') \
        .where('cnpj', '==', dados['cnpj']) \
        .where('senha_acesso', '==', dados['senha']) \
        .limit(1).get()

    if not docs:
        return jsonify({"erro": "Acesso Negado"}), 401

    cliente = docs[0].to_dict()
    # Retorna o nome_fantasia para o frontend
    return jsonify({"id": cliente['id'], "nome": cliente.get('nome_fantasia', cliente.get('nome'))})


@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    # Rota exigida pelo tablet.html para registrar o dispositivo
    dados = request.json
    cliente_id = dados.get('cliente_id')
    db.collection('clientes').document(cliente_id).collection('dispositivos').add(dados)
    return jsonify({"status": "dispositivo_ativado"}), 200


# --- ROTAS DE FUNCIONÁRIOS ---

@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    dados = request.json
    # O gestor.html usa o CPF como identificador único
    db.collection('funcionarios').document(dados['cpf']).set(dados)
    return jsonify(dados), 201


@app.route('/api/funcionarios/<param>', methods=['GET', 'PUT', 'DELETE'])
def gerenciar_funcionarios(param):
    if request.method == 'GET':
        # Corrigido: O gestor.html envia o ID da UNIDADE nesta rota
        docs = db.collection('funcionarios').where('cliente_id', '==', param).stream()
        return jsonify([doc.to_dict() for doc in docs])

    doc_ref = db.collection('funcionarios').document(param)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"})

    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"})


# --- ROTAS DE PONTO ---

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cpf = dados['id_funcionario']

    func_ref = db.collection('funcionarios').document(cpf).get()
    if not func_ref.exists:
        return jsonify({"erro": "Funcionário não cadastrado"}), 404

    func_data = func_ref.to_dict()

    # BUSCA SEM ORDER_BY (Para evitar erro de índice no Firestore)
    pontos_ref = db.collection('pontos').where('id_funcionario', '==', cpf).get()

    # Ordenamos manualmente no Python pelo timestamp
    pontos_lista = [p.to_dict() for p in pontos_ref]
    pontos_lista.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

    tipo = "ENTRADA"
    horas_trabalhadas = 0
    agora = datetime.now()

    if pontos_lista:
        ultimo = pontos_lista[0]  # O primeiro após o sort reverse é o último registro
        if ultimo['tipo'] == "ENTRADA":
            tipo = "SAÍDA"
            inicio = datetime.fromisoformat(ultimo['timestamp_servidor'])
            diff = agora - inicio
            horas_trabalhadas = round(diff.total_seconds() / 3600, 2)

    novo_ponto = {
        "id_funcionario": cpf,
        "funcionario": func_data['nome'],
        "id_cliente": dados['id_cliente'],
        "tipo": tipo,
        "timestamp_servidor": agora.isoformat(),
        "horas_trabalhadas": horas_trabalhadas
    }
    db.collection('pontos').add(novo_ponto)

    return jsonify({"tipo": tipo, "funcionario": func_data['nome'], "horas": horas_trabalhadas})


@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio_ponto(cpf):
    # Busca apenas pelo filtro de CPF
    docs = db.collection('pontos').where('id_funcionario', '==', cpf).get()

    # Transforma em lista e ordena por data (do mais antigo para o mais novo)
    lista_pontos = [doc.to_dict() for doc in docs]
    lista_pontos.sort(key=lambda x: x['timestamp_servidor'])

    return jsonify(lista_pontos)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
