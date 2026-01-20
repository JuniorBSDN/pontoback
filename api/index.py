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
    cred_dict = json.loads(FIREBASE_CONFIG)
    cred = credentials.Certificate(cred_dict)
else:
    # Para teste local, certifique-se que o arquivo está na pasta
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred)
db = firestore.client()


# Helper para fuso horário de Brasília
def get_agora_br():
    fuso_br = timezone(timedelta(hours=-3))
    return datetime.now(fuso_br)


# --- ROTAS DE CLIENTES (UNIDADES) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
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
    cnpj_input = "".join(filter(str.isdigit, dados.get('cnpj', '')))
    senha_input = dados.get('senha')

    # Busca clientes e valida no Python para evitar erro de índice composto
    docs = db.collection('clientes').stream()
    for doc in docs:
        cliente = doc.to_dict()
        cnpj_banco = "".join(filter(str.isdigit, cliente.get('cnpj', '')))
        if cnpj_banco == cnpj_input and cliente.get('senha_acesso') == senha_input:
            return jsonify({
                "id": cliente['id'],
                "nome": cliente.get('nome_fantasia', cliente.get('nome'))
            })

    return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401


# --- ROTAS DE FUNCIONÁRIOS ---

@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    dados = request.json
    # Salva usando o CPF como ID do documento para facilitar a busca no ponto
    cpf = "".join(filter(str.isdigit, dados['cpf']))
    dados['cpf'] = cpf
    db.collection('funcionarios').document(cpf).set(dados)
    return jsonify(dados), 201


@app.route('/api/funcionarios/<param>', methods=['GET', 'PUT', 'DELETE'])
def gerenciar_funcionarios(param):
    if request.method == 'GET':
        # Busca funcionários de uma unidade específica
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
    cpf = "".join(filter(str.isdigit, dados.get('id_funcionario', '')))
    id_cliente = dados.get('id_cliente')

    func_ref = db.collection('funcionarios').document(cpf).get()
    if not func_ref.exists:
        return jsonify({"erro": "Funcionário não encontrado"}), 404

    func_data = func_ref.to_dict()
    agora = get_agora_br()

    # Busca histórico para decidir se é Entrada ou Saída sem exigir índice do Firestore
    pontos_ref = db.collection('pontos').where('id_funcionario', '==', cpf).get()
    pontos_lista = [p.to_dict() for p in pontos_ref]
    # Ordena pelo mais recente no Python
    pontos_lista.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

    tipo = "ENTRADA"
    horas_trabalhadas = 0

    if pontos_lista:
        ultimo = pontos_lista[0]
        if ultimo['tipo'] == "ENTRADA":
            tipo = "SAÍDA"
            inicio = datetime.fromisoformat(ultimo['timestamp_servidor'])
            # Garante que 'inicio' tenha timezone para o cálculo
            if inicio.tzinfo is None:
                inicio = inicio.replace(tzinfo=timezone(timedelta(hours=-3)))

            diff = agora - inicio
            horas_trabalhadas = round(diff.total_seconds() / 3600, 2)

    novo_ponto = {
        "id_funcionario": cpf,
        "funcionario": func_data['nome'],
        "id_cliente": id_cliente,
        "tipo": tipo,
        "timestamp_servidor": agora.isoformat(),
        "horas_trabalhadas": horas_trabalhadas
    }
    db.collection('pontos').add(novo_ponto)

    return jsonify({
        "tipo": tipo,
        "funcionario": func_data['nome'],
        "horas": horas_trabalhadas,
        "mensagem": "Ponto registrado com sucesso!"
    })


@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio_ponto(cpf):
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    docs = db.collection('pontos').where('id_funcionario', '==', cpf_limpo).get()

    lista_pontos = [doc.to_dict() for doc in docs]
    # Ordena do mais antigo para o mais novo para o relatório
    lista_pontos.sort(key=lambda x: x['timestamp_servidor'])

    return jsonify(lista_pontos)


if __name__ == '__main__':
    # Porta 5000 para local, Vercel ignora o __main__
    app.run(debug=True, port=5000)
