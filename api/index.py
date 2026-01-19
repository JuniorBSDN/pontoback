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
        # set com merge=True permite criar novo ou editar existente sem duplicar
        db.collection('funcionarios').document(cpf).set(novo_func, merge=True)
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
    return jsonify({"id": query[0].id, "nome": empresa.get('nome_fantasia')}), 200

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        cliente_id = dados.get('id_cliente')
        machine_id = dados.get('machine_id')
        cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))

        func_ref = db.collection('funcionarios').document(cpf).get()
        if not func_ref.exists:
            return jsonify({"erro": "Funcionário não encontrado"}), 404

        agora = datetime.now()
        
        # BUSCA SEM ORDER_BY PARA EVITAR ERRO DE ÍNDICE
        docs = db.collection('registros_ponto').where('id_funcionario', '==', cpf).stream()
        lista_pontos = []
        for d in docs:
            p = d.to_dict()
            # Filtramos apenas pontos de hoje na memória para decidir Entrada/Saída
            if p['timestamp_servidor'].date() == agora.date():
                lista_pontos.append(p)
        
        # Ordenamos manualmente para pegar o último registro do dia
        lista_pontos.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

        tipo = "ENTRADA"
        horas_ciclo = 0

        if lista_pontos:
            ultimo_dict = lista_pontos[0]
            if ultimo_dict.get('tipo') == "ENTRADA":
                tipo = "SAÍDA"
                inicio_turno = ultimo_dict['timestamp_servidor']
                diff = agora.replace(tzinfo=None) - inicio_turno.replace(tzinfo=None)
                horas_ciclo = round(diff.total_seconds() / 3600, 2)

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

        return jsonify({"status": "sucesso", "tipo": tipo, "horas": horas_ciclo, "nome": novo_ponto["nome_funcionario"]}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def historico_por_funcionario(cpf):
    try:
        pontos = []
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))

        # REMOVIDO ORDER_BY PARA NÃO EXIGIR ÍNDICE MANUAL
        query = db.collection('registros_ponto').where('id_funcionario', '==', cpf_limpo).stream()

        for doc in query:
            item = doc.to_dict()
            item['id'] = doc.id
            if 'timestamp_servidor' in item:
                item['timestamp_servidor'] = item['timestamp_servidor'].isoformat()
            pontos.append(item)

        # ORDENAÇÃO MANUAL NO SERVIDOR (Python)
        pontos.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

        return jsonify(pontos), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
