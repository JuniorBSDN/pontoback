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
    # Local: certifique-se de ter o ficheiro serviceAccountKey.json
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

def get_agora_br():
    # Retorna hora de Brasília
    return datetime.now(timezone(timedelta(hours=-3)))

# --- ROTA DE LOGIN (CORREÇÃO DEFINITIVA) ---
@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_unidade():
    try:
        dados = request.json
        # 1. Limpa o CNPJ digitado pelo utilizador
        cnpj_input = "".join(filter(str.isdigit, str(dados.get('cnpj', ''))))
        senha_input = str(dados.get('senha', '')).strip()

        if not cnpj_input or not senha_input:
            return jsonify({"erro": "Preencha CNPJ e Senha"}), 400

        # 2. Procura na coleção 'clientes'
        docs = db.collection('clientes').stream()
        for doc in docs:
            c = doc.to_dict()
            # Limpa o CNPJ que está gravado no banco
            cnpj_banco = "".join(filter(str.isdigit, str(c.get('cnpj', ''))))
            # O campo no seu banco (via index.html) chama-se 'senha_acesso'
            senha_banco = str(c.get('senha_acesso', '')).strip()

            if cnpj_banco == cnpj_input and senha_banco == senha_input:
                return jsonify({
                    "id": c.get('id', doc.id), 
                    "nome": c.get('nome_fantasia', c.get('nome', 'Unidade'))
                }), 200
        
        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# --- ROTAS DE FUNCIONÁRIOS (gestor.html) ---
@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados['cpf'])))
    dados['cpf'] = cpf
    db.collection('funcionarios').document(cpf).set(dados)
    return jsonify(dados), 201

@app.route('/api/funcionarios/<param>', methods=['GET', 'PUT', 'DELETE'])
def gerenciar_funcionarios(param):
    if request.method == 'GET':
        # Lista funcionários da unidade específica
        docs = db.collection('funcionarios').where('cliente_id', '==', param).stream()
        return jsonify([doc.to_dict() for doc in docs])
    
    doc_ref = db.collection('funcionarios').document(param)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"})
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"})

# --- REGISTO DE PONTO (tablet.html) ---
@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))
    
    f_ref = db.collection('funcionarios').document(cpf).get()
    if not f_ref.exists:
        return jsonify({"erro": "Funcionário não encontrado"}), 404
    
    func_data = f_ref.to_dict()
    agora = get_agora_br()

    # Busca pontos e ordena no Python (evita erro de índice no Firestore)
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

# --- OUTRAS ROTAS NECESSÁRIAS ---
@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
        doc_ref.set(dados)
        return jsonify(dados), 201
    docs = db.collection('clientes').stream()
    return jsonify([doc.to_dict() for doc in docs])

@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio_ponto(cpf):
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    docs = db.collection('pontos').where('id_funcionario', '==', cpf_limpo).get()
    lista = [d.to_dict() for d in docs]
    lista.sort(key=lambda x: x['timestamp_servidor'])
    return jsonify(lista)

if __name__ == '__main__':
    app.run(debug=True)
