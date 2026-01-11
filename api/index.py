import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
# Configuração de CORS para permitir que o seu Front-end acesse a API na Vercel
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- INICIALIZAÇÃO FIREBASE ---
if not firebase_admin._apps:
    cred_json = os.environ.get('FIREBASE_CONFIG')
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- 1. OPERAÇÕES DE EMPRESA (PAINEL ADMIN) ---

@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json
        nova_empresa = {
            "nome_fantasia": dados.get('nome'),
            "cnpj": dados.get('cnpj'),
            "responsavel": dados.get('responsavel'), # Abstração Legal
            "plano": dados.get('plano', 'basico'),
            "status": "ativo", # Padrão ao criar
            "data_cadastro": datetime.now()
        }
        doc_ref = db.collection('clientes').add(nova_empresa)
        return jsonify({"id": doc_ref[1].id, "status": "Empresa registrada"}), 201

    # Retorna todas as empresas cadastradas
    docs = db.collection('clientes').order_by("nome_fantasia").stream()
    return jsonify([{**d.to_dict(), "id": d.id} for d in docs]), 200

@app.route('/api/clientes/<id>', methods=['PUT', 'DELETE'])
def acoes_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    
    if request.method == 'DELETE':
        # Exclui a empresa (Cuidado: Isso é permanente no Firebase)
        doc_ref.delete()
        return jsonify({"status": "Registro removido"}), 200
    
    # Atualiza Status (Bloqueio/Desbloqueio) ou dados cadastrais
    dados = request.json
    doc_ref.update(dados)
    return jsonify({"status": "Registro atualizado"}), 200

# --- 2. OPERAÇÕES DE PONTO (TABLET) ---

@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json
        id_cliente = dados.get('id_cliente')
        
        # VALIDAÇÃO DE FLUXO: A empresa está ativa?
        emp_doc = db.collection('clientes').document(id_cliente).get()
        if not emp_doc.exists:
            return jsonify({"erro": "Empresa não encontrada"}), 404
        
        status_empresa = emp_doc.to_dict().get('status')
        if status_empresa != 'ativo':
            return jsonify({"erro": f"Acesso negado: Empresa com status {status_empresa}"}), 403

        # REGISTRO DO PONTO
        ponto = {
            "funcionario_id": str(dados.get('id_funcionario')),
            "timestamp_local": dados.get('timestamp_local'), # Enviado pelo tablet
            "data_hora_servidor": datetime.now(),            # Hora oficial p/ auditoria
            "geo": dados.get('geo'),                        # Latitude/Longitude
            "metadados": {
                "user_agent": request.headers.get('User-Agent'),
                "ip": request.remote_addr
            }
        }

        # Salva na sub-coleção específica (Isolamento de dados)
        db.collection('clientes').document(id_cliente).collection('registros_ponto').add(ponto)
        return jsonify({"status": "Ponto validado com sucesso"}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 400

# --- 3. OPERAÇÕES DE AUDITORIA (EXPORTAÇÃO AFD) ---

@app.route('/api/clientes/<id_cliente>/afd', methods=['GET'])
def exportar_afd(id_cliente):
    # Busca registros de ponto da empresa solicitada
    registros = db.collection('clientes').document(id_cliente).collection('registros_ponto').order_by("data_hora_servidor").stream()
    
    # Montagem do arquivo conforme Portaria 671 (Simplificado para este exemplo)
    linhas_afd = []
    for reg in registros:
        d = reg.to_dict()
        data_ponto = d['data_hora_servidor']
        # Layout: Sequencial(9) + Tipo(1) + Data(8) + Hora(4) + PIS/ID(12)
        linha = f"0000000013{data_ponto.strftime('%d%m%Y%H%M')}{str(d['funcionario_id']).zfill(12)}"
        linhas_afd.append(linha)
    
    conteudo = "\n".join(linhas_afd)
    response = make_response(conteudo)
    response.headers["Content-Disposition"] = f"attachment; filename=AFD_CLIENTE_{id_cliente}.txt"
    response.headers["Content-type"] = "text/plain"
    return response

if __name__ == '__main__':
    app.run(debug=True)
