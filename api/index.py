import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
# Configuração de CORS para permitir acesso do Tablet e do Painel Admin
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Inicialização do Firebase
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        # Certifique-se de que este arquivo existe no seu servidor/diretório
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- ROTAS DE CLIENTES (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        senha_final = dados.get('senha') or dados.get('senha_acesso')

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
        senha_final = dados.get('senha') or dados.get('senha_acesso')
        ref.update({
            "nome_fantasia": dados.get('nome'),
            "cnpj": dados.get('cnpj'),
            "responsavel": dados.get('responsavel'),
            "email": dados.get('email'),
            "telefone": dados.get('telefone'),
            "endereco": dados.get('endereco'),
            "senha_acesso": senha_final
        })
        return jsonify({"status": "atualizado"})

    if request.method == 'DELETE':
        ref.delete()
        return jsonify({"status": "removido"})


# --- ROTAS DO TABLET (OPERAÇÃO E ATIVAÇÃO) ---

@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    """Vincula um tablet específico a uma empresa via Machine ID"""
    dados = request.json
    cliente_id = dados.get('cliente_id')
    machine_id = dados.get('machine_id')

    if not cliente_id or not machine_id:
        return jsonify({"erro": "Dados incompletos"}), 400

    # Salva o dispositivo na sub-coleção da empresa
    dispositivo_ref = db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id)

    dispositivo_ref.set({
        "machine_id": machine_id,
        "modelo": dados.get('modelo'),
        "data_ativacao": datetime.now(),
        "ultimo_acesso": datetime.now(),
        "status": "autorizado"
    })

    return jsonify({"status": "Dispositivo ativado com sucesso"}), 200


@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    """Recebe a batida de ponto do Tablet (QR Code do funcionário)"""
    dados = request.json
    cliente_id = dados.get('id_cliente')
    machine_id = dados.get('machine_id')

    # 1. Validação básica de segurança: Verifica se o tablet está autorizado
    disp_ref = db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id).get()

    if not disp_ref.exists:
        return jsonify({"erro": "Dispositivo não autorizado. Reative o tablet."}), 403

    # 2. Prepara o registro do ponto
    ponto = {
        "id_funcionario": dados.get('id_funcionario'),
        "timestamp_local": dados.get('timestamp_local'),  # Hora que o tablet registrou
        "timestamp_servidor": datetime.now(),
        "geolocalizacao": dados.get('geo'),
        "machine_id": machine_id,
        "cliente_id": cliente_id
    }

    # 3. Salva no banco de dados (Coleção Geral de Pontos)
    db.collection('registros_ponto').add(ponto)

    # Atualiza último acesso do dispositivo
    db.collection('clientes').document(cliente_id).collection('dispositivos').document(machine_id).update({
        "ultimo_acesso": datetime.now()
    })

    return jsonify({"status": "Ponto registrado"}), 201


@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    dados = request.json
    cnpj = dados.get('cnpj')
    # O tablet envia como 'senha', mas o banco guarda como 'senha_acesso'
    senha_enviada = dados.get('senha')

    # A query DEVE comparar com o nome exato da coluna no Firestore
    query = db.collection('clientes').where('cnpj', '==', cnpj).where('senha_acesso', '==', senha_enviada).get()

    if not query:
        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401

    empresa = query[0].to_dict()
    return jsonify({
        "id": query[0].id,
        "nome": empresa.get('nome_fantasia')
    }), 200
if __name__ == '__main__':
    # Em produção (Vercel/Heroku), o Flask usa o host 0.0.0.0
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
