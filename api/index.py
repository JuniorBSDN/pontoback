import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
CORS(app)

# --- CONFIGURAÇÃO FIREBASE ---
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")
if FIREBASE_CONFIG:
    cred = credentials.Certificate(json.loads(FIREBASE_CONFIG))
else:
    # Local: certifique-se de ter o arquivo serviceAccountKey.json
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Helper para fuso horário de Brasília
def get_agora_br():
    return datetime.now(timezone(timedelta(hours=-3)))

# --- ROTAS DE CLIENTES (USADAS NO index.html e gestor.html) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
        # Garante nome_fantasia para o login do gestor
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
        return jsonify(doc.to_dict()) if doc.exists else ({'erro': 'n/a'}, 404)
    
    if request.method == 'PUT':
        dados = request.json
        doc_ref.update(dados)
        return jsonify({"status": "atualizado"})
    
    doc_ref.delete()
    return jsonify({"status": "excluido"})

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_unidade():
    dados = request.json
    cnpj_limpo = "".join(filter(str.isdigit, str(dados.get('cnpj', ''))))
    senha = str(dados.get('senha', ''))

    docs = db.collection('clientes').stream()
    for doc in docs:
        c = doc.to_dict()
        cnpj_banco = "".join(filter(str.isdigit, str(c.get('cnpj', ''))))
        if cnpj_banco == cnpj_limpo and str(c.get('senha_acesso')) == senha:
            return jsonify({"id": c['id'], "nome": c.get('nome_fantasia', c.get('nome'))})
    
    return jsonify({"erro": "Acesso Negado"}), 401

@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    # Rota chamada pelo tablet.html ao ler QR de ativação
    dados = request.json
    id_cliente = dados.get('cliente_id')
    db.collection('clientes').document(id_cliente).collection('dispositivos').add({
        **dados, "data_ativacao": get_agora_br().isoformat()
    })
    return jsonify({"status": "ativado"})

# --- ROTAS DE FUNCIONÁRIOS (USADAS NO gestor.html) ---

@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados['cpf'])))
    dados['cpf'] = cpf
    # O gestor.html precisa que o CPF seja a chave para o Tablet ler
    db.collection('funcionarios').document(cpf).set(dados)
    return jsonify(dados), 201

@app.route('/api/funcionarios/<identificador>', methods=['GET', 'PUT', 'DELETE'])
def gerenciar_funcionarios(identificador):
    # GET: Se o identificador for o cliente_id (lista funcionários da unidade)
    if request.method == 'GET':
        docs = db.collection('funcionarios').where('cliente_id', '==', identificador).stream()
        return jsonify([doc.to_dict() for doc in docs])

    doc_ref = db.collection('funcionarios').document(identificador)
    
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"})
    
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"})

# --- ROTAS DE PONTO (USADAS NO tablet.html e gestor.html) ---

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))
    id_cliente = dados.get('id_cliente')

    f_ref = db.collection('funcionarios').document(cpf).get()
    if not f_ref.exists:
        return jsonify({"erro": "CPF não cadastrado"}), 404
    
    func = f_ref.to_dict()
    agora = get_agora_br()

    # Ordenação manual para evitar erro de índice composto no Firestore
    pontos = db.collection('pontos').where('id_funcionario', '==', cpf).get()
    lista = [p.to_dict() for p in pontos]
    lista.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

    tipo = "ENTRADA"
    horas = 0
    if lista and lista[0]['tipo'] == "ENTRADA":
        tipo = "SAÍDA"
        inicio = datetime.fromisoformat(lista[0]['timestamp_servidor'])
        if inicio.tzinfo is None: inicio = inicio.replace(tzinfo=timezone(timedelta(hours=-3)))
        horas = round((agora - inicio).total_seconds() / 3600, 2)

    novo_ponto = {
        "id_funcionario": cpf,
        "funcionario": func['nome'],
        "id_cliente": id_cliente,
        "tipo": tipo,
        "timestamp_servidor": agora.isoformat(),
        "horas_trabalhadas": horas
    }
    db.collection('pontos').add(novo_ponto)
    return jsonify({"tipo": tipo, "funcionario": func['nome'], "horas": horas})

@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio(cpf):
    # Rota usada pelo modal de relatório no gestor.html
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    docs = db.collection('pontos').where('id_funcionario', '==', cpf_limpo).get()
    lista = [d.to_dict() for d in docs]
    lista.sort(key=lambda x: x['timestamp_servidor'])
    return jsonify(lista)

if __name__ == '__main__':
    app.run(debug=True)
