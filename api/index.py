import os
import json
import base64
import numpy as np
import face_recognition
from io import BytesIO
from PIL import Image
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify, Response
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


# --- MOTOR DE BIOMETRIA ---
def obter_vetor_facial(b64_str):
    """Converte imagem Base64 em um vetor matemático facial (128 dimensões)"""
    try:
        if ',' in b64_str:
            b64_str = b64_str.split(',')[1]
        image_data = base64.b64decode(b64_str)
        image = Image.open(BytesIO(image_data)).convert('RGB')
        image_np = np.array(image)
        encodings = face_recognition.face_encodings(image_np)
        return encodings[0].tolist() if len(encodings) > 0 else None
    except Exception:
        return None


# --- LOGIN ADMINISTRATIVO (DONO) ---
@app.route('/api/admin/login', methods=['POST'])
def login_admin():
    dados = request.json or {}
    senha_digitada = str(dados.get('senha', '')).strip()
    senha_mestra = os.getenv("ADMIN_PASSWORD", "admin123")

    if senha_digitada == senha_mestra:
        return jsonify({"auth": True}), 200
    return jsonify({"erro": "Senha incorreta"}), 401


# --- GERENCIAMENTO DE CLIENTES ---
@app.route('/api/clientes', methods=['GET', 'POST'])
def gerenciar_clientes():
    if request.method == 'POST':
        dados = request.json or {}
        doc_ref = db.collection('clientes').document()
        dados['id'] = doc_ref.id
        if 'nome' in dados: dados['nome_fantasia'] = dados['nome']
        doc_ref.set(dados)
        return jsonify(dados), 201
    docs = db.collection('clientes').stream()
    return jsonify([doc.to_dict() for doc in docs])


@app.route('/api/clientes/<id>', methods=['GET', 'PUT', 'DELETE'])
def detalhe_cliente(id):
    doc_ref = db.collection('clientes').document(id)
    if request.method == 'PUT':
        dados = request.json or {}
        dados['id'] = id
        doc_ref.update(dados)
        return jsonify({"status": "atualizado"}), 200
    if request.method == 'DELETE':
        doc_ref.delete()
        return jsonify({"status": "excluido"}), 200
    doc = doc_ref.get()
    return jsonify(doc.to_dict()) if doc.exists else ({'erro': '404'}, 404)


# --- ATIVAÇÃO DE DISPOSITIVO (TABLET) ---
@app.route('/api/clientes/ativar-dispositivo', methods=['POST'])
def ativar_dispositivo():
    try:
        dados = request.json or {}
        cliente_id = dados.get('cliente_id')
        machine_id = dados.get('machine_id')
        if not cliente_id or not machine_id:
            return jsonify({"erro": "Parâmetros insuficientes"}), 400
        db.collection('dispositivos').document(machine_id).set({
            "cliente_id": cliente_id,
            "machine_id": machine_id,
            "modelo": dados.get('modelo', 'Terminal'),
            "ativado_em": get_agora_br().isoformat()
        }, merge=True)
        return jsonify({"status": "ativado"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- LOGIN DO TABLET / UNIDADE ---
@app.route('/api/clientes/login-tablet', methods=['POST'])
def login_unidade():
    try:
        dados = request.json or {}
        cnpj_input = "".join(filter(str.isdigit, str(dados.get('cnpj', ''))))
        senha_input = str(dados.get('senha', '')).strip()
        docs = db.collection('clientes').stream()
        for doc in docs:
            c = doc.to_dict()
            cnpj_banco = "".join(filter(str.isdigit, str(c.get('cnpj', ''))))
            senha_banco = str(c.get('senha_acesso') or c.get('senha') or '').strip()
            if cnpj_banco == cnpj_input and senha_banco == senha_input:
                return jsonify({"id": doc.id, "nome": c.get('nome_fantasia') or c.get('nome') or "Unidade"}), 200
        return jsonify({"erro": "CNPJ ou Senha incorretos"}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- REGISTRO DE PONTO POR QR CODE ---
@app.route('/api/ponto/registrar', methods=['POST'])
def registrar_ponto():
    try:
        dados = request.json or {}
        cpf = "".join(filter(str.isdigit, str(dados.get('id_funcionario', ''))))
        geo_recebido = dados.get('geo', '0,0')
        f_ref = db.collection('funcionarios').document(cpf).get()
        if not f_ref.exists:
            return jsonify({"erro": "CPF não encontrado"}), 404

        func = f_ref.to_dict()
        agora = get_agora_br()
        docs = db.collection('pontos').where('id_funcionario', '==', cpf).get()
        pontos = [p.to_dict() for p in docs]
        pontos.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

        tipo, horas = "ENTRADA", 0
        if pontos and pontos[0]['tipo'] == "ENTRADA":
            tipo = "SAÍDA"
            inicio = datetime.fromisoformat(pontos[0]['timestamp_servidor'])
            if inicio.tzinfo is None:
                inicio = inicio.replace(tzinfo=timezone(timedelta(hours=-3)))
            horas = round((agora - inicio).total_seconds() / 3600, 2)

        novo_ponto = {
            "id_funcionario": cpf, 
            "funcionario": func['nome'], 
            "id_cliente": dados.get('id_cliente'),
            "tipo": tipo, 
            "timestamp_servidor": agora.isoformat(), 
            "horas_trabalhadas": horas,
            "geo": geo_recebido,
            "metodo": "qrcode"
        }
        db.collection('pontos').add(novo_ponto)
        return jsonify({"tipo": tipo, "funcionario": func['nome'], "horas": horas}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- REGISTRO DE PONTO POR RECONHECIMENTO FACIAL ---
@app.route('/api/ponto/facial', methods=['POST'])
def registrar_ponto_facial():
    try:
        dados = request.json or {}
        cliente_id = dados.get('id_cliente')
        imagem_base64 = dados.get('imagem')
        geo_recebido = dados.get('geo', '0,0')

        if not cliente_id or not imagem_base64:
            return jsonify({"erro": "Dados insuficientes para reconhecimento"}), 400

        vetor_camera = obter_vetor_facial(imagem_base64)
        if not vetor_camera:
            return jsonify({"erro": "Nenhum rosto claro detectado na câmera."}), 400

        docs = db.collection('funcionarios').where('cliente_id', '==', cliente_id).stream()

        melhor_match = None
        menor_distancia = 0.55

        for doc in docs:
            f = doc.to_dict()
            vetor_salvo = f.get('face_encoding')
            if vetor_salvo:
                dist = face_recognition.face_distance([np.array(vetor_salvo)], np.array(vetor_camera))[0]
                if dist < menor_distancia:
                    menor_distancia = dist
                    melhor_match = f

        if not melhor_match:
            return jsonify({"erro": "Rosto desconhecido ou não cadastrado nesta unidade."}), 401

        cpf = melhor_match['cpf']
        agora = get_agora_br()

        docs_ponto = db.collection('pontos').where('id_funcionario', '==', cpf).get()
        pontos = [p.to_dict() for p in docs_ponto]
        pontos.sort(key=lambda x: x['timestamp_servidor'], reverse=True)

        tipo, horas = "ENTRADA", 0
        if pontos and pontos[0]['tipo'] == "ENTRADA":
            tipo = "SAÍDA"
            inicio = datetime.fromisoformat(pontos[0]['timestamp_servidor'])
            if inicio.tzinfo is None:
                inicio = inicio.replace(tzinfo=timezone(timedelta(hours=-3)))
            horas = round((agora - inicio).total_seconds() / 3600, 2)

        novo_ponto = {
            "id_funcionario": cpf, 
            "funcionario": melhor_match['nome'], 
            "id_cliente": cliente_id,
            "tipo": tipo, 
            "timestamp_servidor": agora.isoformat(), 
            "horas_trabalhadas": horas, 
            "metodo": "facial",
            "geo": geo_recebido
        }
        db.collection('pontos').add(novo_ponto)
        return jsonify({"tipo": tipo, "nome_funcionario": melhor_match['nome'], "horas_trabalhadas": horas}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- FUNCIONÁRIOS (GERENCIAMENTO COMPLETO E EXTRAÇÃO FACIAL) ---
@app.route('/api/funcionarios', methods=['POST'])
def criar_func():
    try:
        dados = request.json or {}
        cpf = "".join(filter(str.isdigit, str(dados.get('cpf', ''))))
        dados['cpf'] = cpf

        if dados.get('imagem_facial'):
            vetor = obter_vetor_facial(dados['imagem_facial'])
            if vetor:
                dados['face_encoding'] = vetor
                dados['possui_face'] = True
                del dados['imagem_facial']
            else:
                return jsonify({"erro": "Rosto não detectado na foto de cadastro."}), 400
        else:
            dados['possui_face'] = False

        db.collection('funcionarios').document(cpf).set(dados, merge=True)
        return jsonify(dados), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/funcionarios/unidade/<cliente_id>', methods=['GET'])
def listar_funcs(cliente_id):
    try:
        docs = db.collection('funcionarios').where('cliente_id', '==', cliente_id).stream()
        return jsonify([doc.to_dict() for doc in docs]), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/funcionarios/<cpf>', methods=['PUT', 'DELETE'])
def gerenciar_func(cpf):
    try:
        cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
        doc_ref = db.collection('funcionarios').document(cpf_limpo)

        if request.method == 'PUT':
            dados = request.json or {}
            if dados.get('imagem_facial'):
                vetor = obter_vetor_facial(dados['imagem_facial'])
                if vetor:
                    dados['face_encoding'] = vetor
                    dados['possui_face'] = True
                    del dados['imagem_facial']
                else:
                    return jsonify({"erro": "Rosto não detectado na nova foto."}), 400
            doc_ref.update(dados)
            return jsonify({"status": "atualizado"}), 200

        if request.method == 'DELETE':
            doc_ref.delete()
            return jsonify({"status": "excluido"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/api/ponto/funcionario/<cpf>', methods=['GET'])
def relatorio(cpf):
    try:
        docs = db.collection('pontos').where('id_funcionario', '==', cpf).get()
        lista = [d.to_dict() for d in docs]
        lista.sort(key=lambda x: x['timestamp_servidor'], reverse=True)
        return jsonify(lista), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# --- EXPORTAÇÃO AFD (MINISTÉRIO DO TRABALHO - PORTARIA 671) ---
@app.route('/api/ponto/exportar-afd/<cliente_id>', methods=['GET'])
def exportar_afd(cliente_id):
    try:
        docs = db.collection('pontos').where('id_cliente', '==', cliente_id).stream()
        registros = [d.to_dict() for d in docs]
        registros.sort(key=lambda x: x['timestamp_servidor'])

        linhas_afd = ["0000000003100000001PontoBack SaaS Ltda                        "]
        contador = 1
        for p in registros:
            dt = datetime.fromisoformat(p['timestamp_servidor'])
            data_str = dt.strftime("%d%m%Y")
            hora_str = dt.strftime("%H%M")
            cpf_str = str(p['id_funcionario']).zfill(11)
            tipo_reg = "E" if p['tipo'] == "ENTRADA" else "S"
            linhas_afd.append(f"{str(contador).zfill(9)}3{data_str}{hora_str}{cpf_str}{tipo_reg}")
            contador += 1

        return Response("\r\n".join(linhas_afd), mimetype="text/plain",
                        headers={"Content-Disposition": f"attachment;filename=AFD_{cliente_id}.txt"})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
