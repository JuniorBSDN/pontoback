import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
# Permite que o Tablet e o navegador acedam à API sem bloqueios de segurança
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
            print("Erro: serviceAccountKey.json não encontrado. Configure as variáveis de ambiente.")
    firebase_admin.initialize_app(cred)

db = firestore.client()


# --- ROTAS DE CLIENTES (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        try:
            dados = request.json
            res = db.collection('clientes').add(dados)
            return jsonify({"id": res[1].id}), 201
        except Exception as e:
            return jsonify({"erro": str(e)}), 500
    else:
        docs = db.collection('clientes').stream()
        return jsonify([{"id": d.id, **d.to_dict()} for d in docs]), 200


@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def cliente_detalhe(id):
    if request.method == 'PUT':
        db.collection('clientes').document(id).update(request.json)
        return jsonify({"status": "atualizado"}), 200
    else:
        db.collection('clientes').document(id).delete()
        return jsonify({"status": "removido"}), 200


# --- LOGIN DO TABLET ---

@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_tablet():
    try:
        dados = request.json
        cnpj = dados.get('cnpj')
        senha = dados.get('senha')
        docs = db.collection('clientes').where('cnpj', '==', cnpj).where('senha_acesso', '==', senha).limit(1).get()
        if docs:
            return jsonify({"id": docs[0].id, "nome": docs[0].to_dict().get('nome_fantasia')}), 200
        return jsonify({"erro": "Acesso negado"}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- GESTÃO DE FUNCIONÁRIOS (Sincronizado com Gestor.html) ---

@app.route('/api/funcionarios', methods=['POST'])
def criar_funcionario():
    try:
        dados = request.json
        cpf = "".join(filter(str.isdigit, str(dados.get('cpf'))))
        db.collection('funcionarios').document(cpf).set(dados)
        return jsonify({"status": "sucesso"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/funcionarios/<cliente_id>', methods=['GET'])
def listar_funcionarios(cliente_id):
    try:
        docs = db.collection('funcionarios').where('cliente_id', '==', cliente_id).stream()
        return jsonify([doc.to_dict() for doc in docs]), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/funcionarios/detalhe/<cpf>', methods=['PUT', 'DELETE'])
def detalhe_funcionario(cpf):
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    if request.method == 'PUT':
        db.collection('funcionarios').document(cpf_limpo).update(request.json)
        return jsonify({"status": "atualizado"}), 200
    else:
        db.collection('funcionarios').document(cpf_limpo).delete()
        return jsonify({"status": "removido"}), 200


# --- LÓGICA DE PONTO INTELIGENTE (Sincronizado com Tablet.html) ---

@app.route('/api/ponto', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        # O tablet envia 'cpf' e 'cliente_id'. Vamos garantir que pegamos os valores certos.
        cpf = "".join(filter(str.isdigit, str(dados.get('cpf'))))
        cliente_id = dados.get('cliente_id')
        agora = datetime.now()

        # 1. Verifica se o funcionário existe
        doc_func = db.collection('funcionarios').document(cpf).get()
        if not doc_func.exists:
            return jsonify({"erro": "Funcionário não encontrado no banco de dados"}), 404
        
        func_data = doc_func.to_dict()

        # 2. Busca a última batida deste funcionário para decidir se é Entrada ou Saída
        ultimo_ponto_query = db.collection('registros_ponto')\
            .where('id_funcionario', '==', cpf)\
            .order_by('timestamp_servidor', direction=firestore.Query.DESCENDING)\
            .limit(1).get()

        tipo = "ENTRADA"
        horas_ciclo = 0

        if ultimo_ponto_query:
            ultimo = ultimo_ponto_query[0].to_dict()
            # Se o último foi ENTRADA, este agora será SAÍDA
            if ultimo.get('tipo') == "ENTRADA":
                tipo = "SAÍDA"
                ts_entrada = ultimo.get('timestamp_servidor')
                
                # Converte timestamp do Firestore para objeto Python para calcular
                if hasattr(ts_entrada, 'replace'): 
                    ts_entrada = ts_entrada.replace(tzinfo=None)
                elif isinstance(ts_entrada, str):
                    ts_entrada = datetime.fromisoformat(ts_entrada).replace(tzinfo=None)
                
                diff = agora - ts_entrada
                horas_ciclo = round(diff.total_seconds() / 3600, 2)

        # 3. Salva o novo registro
        novo_registro = {
            "id_funcionario": cpf,
            "nome_funcionario": func_data.get('nome', 'Funcionário'),
            "timestamp_servidor": agora,
            "tipo": tipo,
            "cliente_id": cliente_id,
            "horas_trabalhadas": horas_ciclo
        }
        
        db.collection('registros_ponto').add(novo_registro)

        return jsonify({
            "status": "sucesso",
            "tipo": tipo,
            "funcionario": func_data.get('nome'),
            "horas": horas_ciclo
        }), 201

    except Exception as e:
        print(f"Erro no Servidor: {str(e)}")
        return jsonify({"erro": str(e)}), 500

@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def historico_ponto(cpf):
    try:
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
        query = db.collection('registros_ponto') \
            .where('id_funcionario', '==', cpf_limpo) \
            .order_by('timestamp_servidor', direction=firestore.Query.DESCENDING).stream()

        pontos = []
        for doc in query:
            item = doc.to_dict()
            if 'timestamp_servidor' in item:
                item['timestamp_servidor'] = item['timestamp_servidor'].isoformat()
            pontos.append(item)
        return jsonify(pontos), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == '__main__':
    # host 0.0.0.0 é fundamental para o Tablet na mesma rede conectar ao PC
    app.run(host='0.0.0.0', port=5000, debug=True)
