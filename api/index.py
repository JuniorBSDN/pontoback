import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- CONFIGURAÇÃO FIREBASE ---
FIREBASE_CONFIG = os.getenv("FIREBASE_CONFIG")
if FIREBASE_CONFIG:
    cred = credentials.Certificate(json.loads(FIREBASE_CONFIG))
else:
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
    except:
        cred = None

if cred and not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

def get_agora_br():
    return datetime.now(timezone(timedelta(hours=-3)))

# ==========================================
# 1. ADMINISTRAÇÃO (index.html)
# ==========================================

@app.route('/api/admin/login', methods=['POST'])
def login_admin():
    dados = request.json
    senha_digitada = str(dados.get('senha', '')).strip()
    senha_mestra = os.getenv("ADMIN_PASSWORD", "admin123")
    if senha_digitada == senha_mestra:
        return jsonify({"auth": True}), 200
    return jsonify({"erro": "Senha incorreta"}), 401

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        id_cliente = dados.get('id')
        if id_cliente:
            doc_ref = db.collection('clientes').document(id_cliente)
        else:
            doc_ref = db.collection('clientes').document()
            dados['id'] = doc_ref.id
        
        if 'nome' in dados: dados['nome_fantasia'] = dados['nome']
        doc_ref.set(dados, merge=True)
        return jsonify(dados), 201

    docs = db.collection('clientes').stream()
    return jsonify([doc.to_dict() for doc in docs])

@app.route('/api/clientes/<id>', methods=['DELETE', 'PUT'])
def acoes_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"}), 200
    if request.method == 'PUT':
        dados = request.json
        doc_ref.update(dados)
        return jsonify({"status": "atualizado"}), 200

# =======================================================
# 2. LOGINS DE TOTENS (tablet.html e tabletAluno.html)
# =======================================================

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_unidade():
    try:
        dados = request.json
        cnpj_input = "".join(filter(str.isdigit, str(dados.get('cnpj', ''))))
        senha_input = str(dados.get('senha', '')).strip()

        docs = db.collection('clientes').stream()
        for doc in docs:
            c = doc.to_dict()
            cnpj_banco = "".join(filter(str.isdigit, str(c.get('cnpj', ''))))
            # Aceita qualquer campo de senha definido na criação da unidade
            senha_banco = str(c.get('senha_acesso') or c.get('senha') or '').strip()

            if cnpj_banco == cnpj_input and senha_banco == senha_input:
                # Retorna os campos id e cliente_id para garantir que ambos os frontends funcionem
                return jsonify({
                    "id": doc.id,
                    "cliente_id": doc.id,
                    "nome": c.get('nome_fantasia') or c.get('nome') or "Unidade",
                    "api": request.host_url.rstrip('/') # Útil para o totem saber onde bater
                }), 200

        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# =======================================================
# 3. FUNCIONÁRIOS (gestor.html e tablet.html)
# =======================================================

@app.route('/api/funcionarios', methods=['POST'])
def criar_func():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados['cpf'])))
    dados['cpf'] = cpf
    db.collection('funcionarios').document(cpf).set(dados)
    return jsonify(dados), 201

@app.route('/api/funcionarios/unidade/<cliente_id>', methods=['GET'])
def listar_funcs(cliente_id):
    docs = db.collection('funcionarios').where('cliente_id', '==', cliente_id).stream()
    return jsonify([doc.to_dict() for doc in docs])

@app.route('/api/funcionarios/<cpf>', methods=['PUT', 'DELETE'])
def gerenciar_func(cpf):
    doc_ref = db.collection('funcionarios').document(cpf)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"}), 200
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"}), 200

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))
    f_ref = db.collection('funcionarios').document(cpf).get()
    if not f_ref.exists: return jsonify({"erro": "CPF não encontrado"}), 404
    
    agora = get_agora_br()
    # Lógica de Entrada/Saída simplificada
    docs = db.collection('pontos').where('id_funcionario', '==', cpf).order_by('timestamp_servidor', direction=firestore.Query.DESCENDING).limit(1).get()
    
    tipo = "ENTRADA"
    horas = 0
    if docs:
        ultimo = docs[0].to_dict()
        if ultimo['tipo'] == "ENTRADA":
            tipo = "SAÍDA"
            inicio = datetime.fromisoformat(ultimo['timestamp_servidor'])
            horas = round((agora - inicio).total_seconds() / 3600, 2)

    novo_ponto = {
        "id_funcionario": cpf, "funcionario": f_ref.to_dict()['nome'],
        "id_cliente": dados.get('id_cliente'), "tipo": tipo,
        "timestamp_servidor": agora.isoformat(), "horas_trabalhadas": horas
    }
    db.collection('pontos').add(novo_ponto)
    return jsonify(novo_ponto), 200

# ============================================================
# 4. ALUNOS (gestaoAlunos.html e tabletAluno.html)
# ============================================================

@app.route('/api/alunos', methods=['POST'])
def cadastrar_aluno():
    dados = request.json
    mat = "".join(filter(str.isdigit, str(dados.get('matricula', ''))))
    dados['matricula'] = mat
    db.collection('alunos').document(mat).set(dados)
    return jsonify(dados), 201

@app.route('/api/alunos/unidade/<cliente_id>', methods=['GET'])
def listar_alunos(cliente_id):
    docs = db.collection('alunos').where('cliente_id', '==', cliente_id).stream()
    return jsonify([doc.to_dict() for doc in docs])

@app.route('/api/alunos/<matricula>', methods=['PUT', 'DELETE'])
def gerenciar_aluno(matricula):
    doc_ref = db.collection('alunos').document(matricula)
    if request.method == 'PUT':
        doc_ref.update(request.json)
        return jsonify({"status": "atualizado"}), 200
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"}), 200

@app.route('/api/presencas', methods=['POST'])
def registrar_presenca():
    dados = request.json
    id_aluno = str(dados.get('id_aluno'))
    aluno_ref = db.collection('alunos').document(id_aluno).get()
    if not aluno_ref.exists: return jsonify({"erro": "Não cadastrado"}), 404
    
    aluno_data = aluno_ref.to_dict()
    db.collection('presencas').add({
        "id_aluno": id_aluno, "cliente_id": dados.get('id_cliente'),
        "timestamp": get_agora_br().isoformat(), "status": "Presente"
    })
    return jsonify({"status": "sucesso", "aluno": aluno_data}), 201

if __name__ == '__main__':
    app.run(debug=True, port=5000)
