import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Inicialização do Firebase
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- ROTAS DE CLIENTES (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        # Correção: Garantir campo único no banco
        senha_final = dados.get('senha_acesso') or dados.get('senha')

        nova_empresa = {
            "nome_fantasia": dados.get('nome'),
            "cnpj": dados.get('cnpj'),
            "responsavel": dados.get('responsavel'),
            "email": dados.get('email'),
            "telefone": dados.get('telefone'),
            "endereco": dados.get('endereco'),
            "senha_acesso": senha_final,
            "status": "ativo",
            "data_cadastro": datetime.now()
        }
        db.collection('clientes').add(nova_empresa)
        return jsonify({"status": "sucesso"}), 201

    clientes = []
    for doc in db.collection('clientes').stream():
        item = doc.to_dict()
        item['id'] = doc.id
        clientes.append(item)
    return jsonify(clientes)


@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def detalhe_cliente(id):
    ref = db.collection('clientes').document(id)
    if request.method == 'PUT':
        dados = request.json
        ref.update({
            "nome_fantasia": dados.get('nome'),
            "cnpj": dados.get('cnpj'),
            "responsavel": dados.get('responsavel'),
            "email": dados.get('email'),
            "telefone": dados.get('telefone'),
            "endereco": dados.get('endereco'),
            "senha_acesso": dados.get('senha_acesso') or dados.get('senha')
        })
        return jsonify({"status": "atualizado"})

    if request.method == 'DELETE':
        ref.delete()
        return jsonify({"status": "removido"})


# --- ROTAS DE FUNCIONÁRIOS (GESTÃO DA UNIDADE) ---

@app.route('/api/funcionarios', methods=['POST'])
def cadastrar_funcionario():
    try:
        dados = request.json
        # Limpeza rigorosa do CPF para evitar IDs de documento inválidos
        raw_cpf = str(dados.get('cpf', ''))
        cpf = "".join(filter(str.isdigit, raw_cpf))

        if not cpf:
            return jsonify({"erro": "CPF é obrigatório"}), 400

        novo_func = {
            "nome": dados.get('nome'),
            "cpf": cpf,
            "setor": dados.get('setor'),
            "salario_base": float(dados.get('salario_base') or 0),
            "tipo_contrato": dados.get('tipo_contrato'),
            "cliente_id": str(dados.get('cliente_id')),
            "data_cadastro": datetime.now()
        }

        db.collection('funcionarios').document(cpf).set(novo_func)
        return jsonify({"status": "sucesso"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/funcionarios/<cliente_id>', methods=['GET'])
def listar_funcionarios(cliente_id):
    funcs = []
    query = db.collection('funcionarios').where('cliente_id', '==', cliente_id).stream()
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        funcs.append(item)
    return jsonify(funcs), 200


@app.route('/api/funcionarios/<id>', methods=['DELETE'])
def excluir_funcionario(id):
    db.collection('funcionarios').document(id).delete()
    return jsonify({"status": "removido"}), 200


# --- ROTAS DO TABLET E REGISTRO DE PONTO ---

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    dados = request.json
    cnpj = dados.get('cnpj')
    senha_enviada = dados.get('senha')

    query = db.collection('clientes').where('cnpj', '==', cnpj).where('senha_acesso', '==', senha_enviada).get()

    if not query:
        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401

    empresa = query[0].to_dict()
    return jsonify({
        "id": query[0].id,
        "nome": empresa.get('nome_fantasia')
    }), 200


@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    dados = request.json
    cliente_id = dados.get('cliente_id')
    machine_id = dados.get('machine_id')

    if not cliente_id or not machine_id:
        return jsonify({"erro": "Dados incompletos"}), 400

    dispositivo_ref = db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id)
    dispositivo_ref.set({
        "machine_id": machine_id,
        "modelo": dados.get('modelo', 'Tablet Terminal'),
        "data_ativacao": datetime.now(),
        "ultimo_acesso": datetime.now(),
        "status": "autorizado"
    })
    return jsonify({"status": "Dispositivo ativado"}), 200


@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    dados = request.json
    cliente_id = dados.get('id_cliente')
    machine_id = dados.get('machine_id')
    cpf_funcionario = dados.get('id_funcionario')

    # Validação do Dispositivo
    disp_ref = db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id).get()
    if not disp_ref.exists:
        return jsonify({"erro": "Tablet não autorizado!"}), 403

    # Validação do Funcionário
    func_ref = db.collection('funcionarios').document(cpf_funcionario).get()
    if not func_ref.exists:
        return jsonify({"erro": "Funcionário não cadastrado nesta rede"}), 404

    # Registro do Ponto
    ponto = {
        "id_funcionario": cpf_funcionario,
        "nome_funcionario": func_ref.to_dict().get('nome'),
        "timestamp_local": dados.get('timestamp_local'),
        "timestamp_servidor": datetime.now(),
        "geolocalizacao": dados.get('geo'),
        "machine_id": machine_id,
        "cliente_id": cliente_id
    }

    db.collection('registros_ponto').add(ponto)

    # Atualiza status do tablet
    db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id).update({
        "ultimo_acesso": datetime.now()
    })

    return jsonify({"status": "Ponto registrado"}), 201


# Rota para o Gestor ver o histórico
@app.route('/api/ponto/historico/<cliente_id>', methods=['GET'])
def historico_pontos(cliente_id):
    pontos = []
    query = db.collection('registros_ponto').where('cliente_id', '==', cliente_id).order_by('timestamp_servidor',
                                                                                            direction='DESCENDING').limit(
        100).stream()
    for doc in query:
        item = doc.to_dict()
        item['id'] = doc.id
        pontos.append(item)
    return jsonify(pontos), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
