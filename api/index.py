import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
# Configuração de CORS para permitir acesso de qualquer origem
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- INICIALIZAÇÃO DO FIREBASE ---
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        # Certifique-se de que este ficheiro existe no seu diretório se estiver local
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- ROTAS DE CLIENTES (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
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


# --- ROTAS DE FUNCIONÁRIOS ---

@app.route('/api/funcionarios', methods=['POST'])
def cadastrar_funcionario():
    try:
        dados = request.json
        raw_cpf = str(dados.get('cpf', ''))
        cpf = "".join(filter(str.isdigit, raw_cpf))  # Limpa CPF

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


# --- ROTAS DO TABLET E REGISTRO DE PONTO (LÓGICA DE ENTRADA/SAÍDA) ---

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    dados = request.json
    cnpj = dados.get('cnpj')
    senha_enviada = dados.get('senha')
    query = db.collection('clientes').where('cnpj', '==', cnpj).where('senha_acesso', '==', senha_enviada).get()
    if not query:
        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401
    empresa = query[0].to_dict()
    return jsonify({"id": query[0].id, "nome": empresa.get('nome_fantasia')}), 200


@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        cliente_id = dados.get('id_cliente')
        machine_id = dados.get('machine_id')
        cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))

        # 1. Valida Funcionário
        func_ref = db.collection('funcionarios').document(cpf).get()
        if not func_ref.exists:
            return jsonify({"erro": "Funcionário não encontrado"}), 404

        # 2. Verifica último ponto de HOJE para decidir Tipo (Entrada/Saída)
        agora = datetime.now()
        inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

        ultimo_ponto = db.collection('registros_ponto') \
            .where('id_funcionario', '==', cpf) \
            .where('timestamp_servidor', '>=', inicio_dia) \
            .order_by('timestamp_servidor', direction='DESCENDING').limit(1).get()

        tipo = "ENTRADA"
        horas_ciclo = 0

        if ultimo_ponto:
            ultimo_dict = ultimo_ponto[0].to_dict()
            if ultimo_dict.get('tipo') == "ENTRADA":
                tipo = "SAÍDA"
                # Cálculo: Agora - Horário da Entrada
                inicio_turno = ultimo_dict['timestamp_servidor']
                diff = agora.replace(tzinfo=None) - inicio_turno.replace(tzinfo=None)
                horas_ciclo = round(diff.total_seconds() / 3600, 2)

        # 3. Salva o Registro
        novo_ponto = {
            "id_funcionario": cpf,
            "nome_funcionario": func_ref.to_dict().get('nome'),
            "timestamp_servidor": agora,
            "tipo": tipo,
            "horas_trabalhadas": horas_ciclo,
            "geolocalizacao": dados.get('geo', '0,0'),
            "machine_id": machine_id,
            "cliente_id": cliente_id
        }
        db.collection('registros_ponto').add(novo_ponto)

        return jsonify({"status": "sucesso", "tipo": tipo, "horas": horas_ciclo}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def historico_por_funcionario(cpf):
    try:
        pontos = []
        # Limpa o CPF para garantir a busca correta
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))

        # Busca os registros ordenados pelo mais recente
        query = db.collection('registros_ponto') \
            .where('id_funcionario', '==', cpf_limpo) \
            .order_by('timestamp_servidor', direction='DESCENDING').stream()

        for doc in query:
            item = doc.to_dict()
            item['id'] = doc.id
            # CONVERSÃO CRUCIAL: Transforma a data do Firebase em texto ISO
            if 'timestamp_servidor' in item:
                item['timestamp_servidor'] = item['timestamp_servidor'].isoformat()
            pontos.append(item)

        return jsonify(pontos), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
