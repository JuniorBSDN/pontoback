import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
# CORS configurado para permitir a comunicação com os ficheiros HTML locais ou alojados
CORS(app, resources={r"/*": {"origins": "*"}})

# --- INICIALIZAÇÃO DO FIREBASE ---
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        try:
            cred = credentials.Certificate("serviceAccountKey.json")
        except:
            print("Erro: serviceAccountKey.json não encontrado.")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- ROTAS DE CLIENTES (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        try:
            dados = request.json
            nova_empresa = {
                "nome_fantasia": dados.get('nome'),
                "cnpj": dados.get('cnpj'),
                "responsavel": dados.get('responsavel'),
                "email": dados.get('email'),
                "telefone": dados.get('telefone'),
                "endereco": dados.get('endereco'),
                "senha_acesso": str(dados.get('senha_acesso') or dados.get('senha')),
                "status": "ativo",
                "data_cadastro": datetime.now()
            }
            db.collection('clientes').add(nova_empresa)
            return jsonify({"status": "sucesso"}), 201
        except Exception as e:
            return jsonify({"erro": str(e)}), 500

    # Listar todos os clientes
    clientes = []
    for doc in db.collection('clientes').stream():
        item = doc.to_dict()
        item['id'] = doc.id
        if 'data_cadastro' in item and hasattr(item['data_cadastro'], 'isoformat'):
            item['data_cadastro'] = item['data_cadastro'].isoformat()
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
            "senha_acesso": str(dados.get('senha_acesso'))
        })
        return jsonify({"status": "atualizado"})

    if request.method == 'DELETE':
        ref.delete()
        return jsonify({"status": "removido"})


# --- ROTAS DE FUNCIONÁRIOS (PAINEL GESTOR) ---

@app.route('/api/funcionarios', methods=['POST'])
def cadastrar_funcionario():
    try:
        dados = request.json
        cpf = "".join(filter(str.isdigit, str(dados.get('cpf', ''))))
        novo_func = {
            "nome": dados.get('nome'),
            "cpf": cpf,
            "setor": dados.get('setor'),
            "salario_base": float(dados.get('salario_base') or 0),
            "tipo_contrato": dados.get('tipo_contrato'),
            "cliente_id": str(dados.get('cliente_id')),
            "data_cadastro": datetime.now()
        }
        db.collection('funcionarios').document(cpf).set(novo_func, merge=True)
        return jsonify({"status": "sucesso"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/funcionarios/<cliente_id>', methods=['GET'])
def listar_funcionarios(cliente_id):
    try:
        funcs = []
        query = db.collection('funcionarios').where('cliente_id', '==', str(cliente_id)).stream()
        for doc in query:
            item = doc.to_dict()
            item['id'] = doc.id
            funcs.append(item)
        return jsonify(funcs), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- NOVAS ROTAS PARA GESTÃO DE FUNCIONÁRIOS ---

@app.route('/api/funcionarios/<cpf>', methods=['PUT'])
def alterar_funcionario(cpf):
    try:
        dados = request.json
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
        # Atualiza os dados no Firestore
        db.collection('funcionarios').document(cpf_limpo).update(dados)
        return jsonify({"status": "atualizado"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/funcionarios/<cpf>', methods=['DELETE'])
def excluir_funcionario(cpf):
    try:
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
        # 1. Exclui o funcionário
        db.collection('funcionarios').document(cpf_limpo).delete()
        # 2. Opcional: Excluir também os pontos vinculados a este CPF
        pontos = db.collection('registros_ponto').where('id_funcionario', '==', cpf_limpo).stream()
        for p in pontos:
            p.reference.delete()
            
        return jsonify({"status": "removido"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- ROTAS DE PONTO (TABLET E RELATÓRIO) ---

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    dados = request.json
    cnpj = dados.get('cnpj')
    senha = str(dados.get('senha'))
    query = db.collection('clientes').where('cnpj', '==', cnpj).where('senha_acesso', '==', senha).get()
    if not query:
        return jsonify({"erro": "Credenciais incorretas"}), 401
    empresa = query[0].to_dict()
    return jsonify({"id": query[0].id, "nome": empresa.get('nome_fantasia')})


@app.route('/api/ponto', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        cpf = "".join(filter(str.isdigit, str(dados.get('cpf'))))
        cliente_id = dados.get('cliente_id')
        agora = datetime.now()

        # 1. Buscar dados do funcionário
        doc_func = db.collection('funcionarios').document(cpf).get()
        if not doc_func.exists:
            return jsonify({"erro": "Funcionário não encontrado"}), 404
        
        func = doc_func.to_dict()

        # 2. Verificar o último registro deste funcionário para decidir se é ENTRADA ou SAÍDA
        ultimo_ponto_query = db.collection('registros_ponto')\
            .where('id_funcionario', '==', cpf)\
            .order_by('timestamp_servidor', direction=firestore.Query.DESCENDING)\
            .limit(1).get()

        tipo = "ENTRADA"
        horas_ciclo = 0
        
        if ultimo_ponto_query:
            ultimo_ponto = ultimo_ponto_query[0].to_dict()
            # Se o último foi ENTRADA, este agora será SAÍDA
            if ultimo_ponto.get('tipo') == "ENTRADA":
                tipo = "SAÍDA"
                # Cálculo de horas trabalhadas
                ts_entrada = ultimo_ponto.get('timestamp_servidor')
                # Garantir que ts_entrada é um objeto datetime
                if isinstance(ts_entrada, str):
                    ts_entrada = datetime.fromisoformat(ts_entrada)
                
                diff = agora - ts_entrada.replace(tzinfo=None)
                horas_ciclo = round(diff.total_seconds() / 3600, 2)

        # 3. Criar o novo registro
        novo_ponto = {
            "id_funcionario": cpf,
            "nome_funcionario": func['nome'],
            "timestamp_servidor": agora,
            "tipo": tipo,
            "cliente_id": cliente_id,
            "horas_trabalhadas": horas_ciclo
        }

        db.collection('registros_ponto').add(novo_ponto)

        return jsonify({
            "status": "sucesso",
            "tipo": tipo,
            "horas": horas_ciclo,
            "nome": func['nome']
        }), 201

    except Exception as e:
        print(f"Erro no ponto: {str(e)}")
        return jsonify({"erro": str(e)}), 500


@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def historico_ponto(cpf):
    try:
        pontos = []
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
        query = db.collection('registros_ponto').where('id_funcionario', '==', cpf_limpo).stream()
        for doc in query:
            item = doc.to_dict()
            item['id'] = doc.id
            if 'timestamp_servidor' in item:
                item['timestamp_servidor'] = item['timestamp_servidor'].isoformat()
            pontos.append(item)
        pontos.sort(key=lambda x: x.get('timestamp_servidor', ''), reverse=True)
        return jsonify(pontos), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/ponto/registro/<id>', methods=['DELETE'])
def excluir_ponto(id):
    try:
        db.collection('registros_ponto').document(id).delete()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
