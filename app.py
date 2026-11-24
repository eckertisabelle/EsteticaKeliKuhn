from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
import psycopg2
import os
from functools import wraps
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env localizado junto deste bd.py.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
CORS(app)



DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "EsteticaKeliKuhn"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    **({"sslmode": os.getenv("DB_SSLMODE")} if os.getenv("DB_SSLMODE") else {}),
}


def get_db_connection():
    """Conecta à Neon pela DATABASE_URL ou usa DB_CONFIG para PostgreSQL local."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return psycopg2.connect(database_url, sslmode="require")
    if not os.getenv("DB_HOST"):
        raise RuntimeError(
            "DATABASE_URL não configurada. Defina DATABASE_URL no Render "
            "ou no arquivo .env local."
        )
    return psycopg2.connect(**DB_CONFIG)

FUNCIONARIAS_DB = {
    "keli": {"senha": os.getenv("KELI_PASSWORD", "123"), "nome": "Keli Kuhn", "funcao": "Cabeleireira & Maquiadora", "cpf": os.getenv("KELI_CPF", ""), "emoji": "💇‍♀️"},
    "amanda": {"senha": os.getenv("AMANDA_PASSWORD", "123"), "nome": "Amanda Rauber", "funcao": "Esteticista", "cpf": "", "emoji": "💆‍♀️"}
}


def usuario_autenticado():
    """Retorna o usuário autenticado na sessão do navegador."""
    return str(session.get("funcionaria_usuario", "")).strip().lower()


def requer_keli(funcao):
    """Restringe uma rota administrativa exclusivamente à sessão da Keli."""
    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if usuario_autenticado() != "keli":
            return jsonify({"erro": "Acesso restrito: somente Keli pode acessar esta função."}), 403
        return funcao(*args, **kwargs)
    return wrapper


def bloquear_operacao_venda_para_amanda():
    """Mantém a compra pública, mas impede Amanda de cadastrar vendas pelo painel."""
    usuario = usuario_autenticado()
    if usuario and usuario != "keli":
        return jsonify({"erro": "Acesso negado: somente Keli pode cadastrar ou administrar vendas pelo painel."}), 403
    return None


def garantir_tabela_funcionarias(conn):
    """Cria a tabela de funcionárias adicionais caso ainda não exista."""
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS funcionaria (
                usuario VARCHAR(50) PRIMARY KEY,
                cpf CHAR(11) NOT NULL UNIQUE,
                nome VARCHAR(120) NOT NULL,
                especialidades TEXT NOT NULL,
                emoji VARCHAR(16) NOT NULL DEFAULT '👩‍💼',
                senha_hash TEXT NOT NULL,
                criada_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("ALTER TABLE funcionaria ADD COLUMN IF NOT EXISTS usuario VARCHAR(50)")
        cursor.execute("ALTER TABLE funcionaria ADD COLUMN IF NOT EXISTS especialidades TEXT")
        cursor.execute("ALTER TABLE funcionaria ADD COLUMN IF NOT EXISTS emoji VARCHAR(20) DEFAULT '👩‍💼'")
        cursor.execute("ALTER TABLE funcionaria ADD COLUMN IF NOT EXISTS senha_hash TEXT")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_funcionaria_usuario ON funcionaria(usuario)")
    conn.commit()


def funcionaria_publica(row):
    return {
        "usuario": row["usuario"],
        "cpf": str(row["cpf"]).strip(),
        "nome": row["nome"],
        "funcao": row["especialidades"],
        "emoji": row["emoji"] or "👩‍💼"
    }


def autorizar_keli(dados):
    """Validação adicional no servidor para operações administrativas."""
    usuario = str(dados.get("usuario_login", "")).strip().lower()
    senha = str(dados.get("senha_solicitante", ""))
    return usuario == "keli" and senha == FUNCIONARIAS_DB["keli"]["senha"]


def produto_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "nome": row["nome"],
        "preco": float(row["preco"]) if row["preco"] is not None else 0,
        "desc": row["descricao"] or "",
        "estoque": int(row.get("estoque") or 0),
        "imagem": row.get("imagem") or "",
        "disponivel": bool(row.get("disponivel", True)),
    }

@app.route("/", methods=["GET"])
def pagina_inicial():
    pasta = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(pasta, "index.html")


@app.route("/funcionarias/logout", methods=["POST"])
def logout_funcionaria():
    session.clear()
    return jsonify({"mensagem": "Sessão encerrada."}), 200


@app.route("/funcionarias", methods=["GET"])
def obter_funcionarias():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT usuario, cpf, nome, especialidades, emoji
            FROM funcionaria ORDER BY nome;
        """)
        adicionais = [funcionaria_publica(row) for row in cursor.fetchall()]
        principais = [
            {"usuario": usuario, "cpf": dados.get("cpf", ""),
             "nome": dados["nome"], "funcao": dados["funcao"],
             "emoji": dados.get("emoji", "👩‍💼")}
            for usuario, dados in FUNCIONARIAS_DB.items()
        ]
        return jsonify(principais + adicionais), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/funcionarias/login", methods=["POST"])
def login_funcionaria():
    dados = request.get_json(silent=True) or {}
    usuario = str(dados.get("usuario", "")).strip().lower()
    senha = str(dados.get("senha", ""))
    if usuario in FUNCIONARIAS_DB:
        if senha != FUNCIONARIAS_DB[usuario]["senha"]:
            return jsonify({"erro": "Senha incorreta. Tente novamente!"}), 401
        principal = FUNCIONARIAS_DB[usuario]
        session.clear()
        session["funcionaria_usuario"] = usuario
        return jsonify({"funcionaria": {
            "usuario": usuario, "nome": principal["nome"],
            "funcao": principal["funcao"], "cpf": principal.get("cpf", ""),
            "emoji": principal.get("emoji", "👩‍💼")
        }}), 200

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT usuario, cpf, nome, especialidades, emoji, senha_hash
            FROM funcionaria WHERE usuario = %s;
        """, (usuario,))
        row = cursor.fetchone()
        if not row or not check_password_hash(row["senha_hash"], senha):
            return jsonify({"erro": "Usuário ou senha incorretos."}), 401
        session.clear()
        session["funcionaria_usuario"] = usuario
        return jsonify({"funcionaria": funcionaria_publica(row)}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/funcionarias", methods=["POST"])
@requer_keli
def adicionar_funcionaria():
    dados = request.get_json(silent=True) or {}
    if not autorizar_keli(dados):
        return jsonify({"erro": "Apenas Keli pode cadastrar funcionárias. Faça login novamente."}), 403

    usuario = str(dados.get("usuario", "")).strip().lower()
    cpf = "".join(filter(str.isdigit, str(dados.get("cpf", ""))))
    nome = str(dados.get("nome", "")).strip()
    especialidades = str(dados.get("funcao", dados.get("especialidades", ""))).strip()
    emoji = str(dados.get("emoji", "👩‍💼")).strip() or "👩‍💼"
    senha = str(dados.get("senha", ""))

    if not usuario or not nome or not especialidades or not senha or len(cpf) != 11:
        return jsonify({"erro": "Usuário, nome, CPF com 11 números, especialidades e senha são obrigatórios."}), 400
    if usuario in FUNCIONARIAS_DB:
        return jsonify({"erro": "Este usuário é reservado para uma profissional principal."}), 409

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            INSERT INTO funcionaria (usuario, cpf, nome, especialidades, emoji, senha_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING usuario, cpf, nome, especialidades, emoji;
        """, (usuario, cpf, nome, especialidades, emoji, generate_password_hash(senha)))
        nova = funcionaria_publica(cursor.fetchone())
        conn.commit()
        return jsonify({"mensagem": "Funcionária cadastrada com sucesso!", "funcionaria": nova}), 201
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Já existe uma funcionária com este usuário ou CPF."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/funcionarias/<string:usuario>", methods=["PUT"])
@requer_keli
def alterar_funcionaria(usuario):
    dados = request.get_json(silent=True) or {}
    if not autorizar_keli(dados):
        return jsonify({"erro": "Apenas Keli pode alterar funcionárias. Faça login novamente."}), 403
    if usuario in FUNCIONARIAS_DB:
        return jsonify({"erro": "Os cadastros principais não podem ser alterados por esta operação."}), 403

    cpf = "".join(filter(str.isdigit, str(dados.get("cpf", ""))))
    nome = str(dados.get("nome", "")).strip()
    especialidades = str(dados.get("funcao", dados.get("especialidades", ""))).strip()
    emoji = str(dados.get("emoji", "👩‍💼")).strip() or "👩‍💼"
    senha = str(dados.get("senha", ""))

    if len(cpf) != 11 or not nome or not especialidades:
        return jsonify({"erro": "Nome, CPF com 11 números e especialidades são obrigatórios."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if senha:
            cursor.execute("""
                UPDATE funcionaria
                SET cpf=%s, nome=%s, especialidades=%s, emoji=%s, senha_hash=%s
                WHERE usuario=%s
                RETURNING usuario, cpf, nome, especialidades, emoji;
            """, (cpf, nome, especialidades, emoji, generate_password_hash(senha), usuario))
        else:
            cursor.execute("""
                UPDATE funcionaria
                SET cpf=%s, nome=%s, especialidades=%s, emoji=%s
                WHERE usuario=%s
                RETURNING usuario, cpf, nome, especialidades, emoji;
            """, (cpf, nome, especialidades, emoji, usuario))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"erro": "Funcionária não encontrada."}), 404
        conn.commit()
        return jsonify({"mensagem": "Funcionária alterada com sucesso!", "funcionaria": funcionaria_publica(row)}), 200
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Este CPF já está cadastrado para outra funcionária."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/funcionarias/<string:usuario>", methods=["DELETE"])
@requer_keli
def excluir_funcionaria(usuario):
    dados = request.get_json(silent=True) or {}
    if not autorizar_keli(dados):
        return jsonify({"erro": "Apenas Keli pode excluir funcionárias. Faça login novamente."}), 403
    if usuario in FUNCIONARIAS_DB:
        return jsonify({"erro": "Keli e Amanda são profissionais principais e não podem ser excluídas."}), 403

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM funcionaria WHERE usuario=%s;", (usuario,))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Funcionária não encontrada."}), 404
        conn.commit()
        return jsonify({"mensagem": "Funcionária excluída com sucesso!"}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/produtos", methods=["GET"])
def obter_produtos():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("ALTER TABLE produtos ADD COLUMN IF NOT EXISTS estoque INTEGER NOT NULL DEFAULT 0")
        cursor.execute("ALTER TABLE produtos ADD COLUMN IF NOT EXISTS imagem TEXT")
        cursor.execute("ALTER TABLE produtos ADD COLUMN IF NOT EXISTS disponivel BOOLEAN NOT NULL DEFAULT TRUE")
        cursor.execute("""
            SELECT id_produto AS id, nome, valor AS preco, descricao, estoque, imagem, disponivel
            FROM produtos ORDER BY id_produto;
        """)
        return jsonify([produto_dict(row) for row in cursor.fetchall()]), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/produtos", methods=["POST"])
@requer_keli
def adicionar_produto():
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome", "")).strip()
    descricao = str(dados.get("descricao", dados.get("desc", ""))).strip()
    try:
        preco = float(dados.get("preco"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Preço inválido."}), 400

    if not nome or preco < 0 or not descricao:
        return jsonify({"erro": "Campos inválidos."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            INSERT INTO produtos (nome, valor, descricao, estoque, imagem, disponivel)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id_produto AS id, nome, valor AS preco, descricao, estoque, imagem, disponivel;
        """, (nome, preco, descricao, max(0, int(dados.get("estoque", 0))), str(dados.get("imagem", "")).strip(), bool(dados.get("disponivel", True))))
        novo = produto_dict(cursor.fetchone())
        conn.commit()
        return jsonify(novo), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/produtos/<int:produto_id>", methods=["PUT"])
@requer_keli
def alterar_produto(produto_id):
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome", "")).strip()
    descricao = str(dados.get("descricao", dados.get("desc", ""))).strip()
    try:
        preco = float(dados.get("preco"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Preço inválido."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            UPDATE produtos SET nome=%s, valor=%s, descricao=%s, estoque=%s, imagem=%s, disponivel=%s
            WHERE id_produto=%s
            RETURNING id_produto AS id, nome, valor AS preco, descricao, estoque, imagem, disponivel;
        """, (nome, preco, descricao, max(0, int(dados.get("estoque", 0))), str(dados.get("imagem", "")).strip(), bool(dados.get("disponivel", True)), produto_id))
        produto = cursor.fetchone()
        if not produto:
            conn.rollback()
            return jsonify({"erro": "Produto não encontrado."}), 404
        conn.commit()
        return jsonify(produto_dict(produto)), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/produtos/<int:produto_id>", methods=["DELETE"])
@requer_keli
def excluir_produto(produto_id):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (produto_id,))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Produto não encontrado."}), 404
        conn.commit()
        return jsonify({"mensagem": "Produto removido com sucesso!"}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()




@app.route("/clientes", methods=["GET"])
def obter_clientes():
    conn, cursor = None, None
    try:
        busca = request.args.get("busca", "").strip()
        nascimento_inicio = request.args.get("nascimento_inicio", "").strip()
        nascimento_fim = request.args.get("nascimento_fim", "").strip()

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        consulta = """
            SELECT cpf, nome, telefone, email, data_nascimento
            FROM cliente
            WHERE (
                %s = ''
                OR nome ILIKE %s
                OR CAST(cpf AS TEXT) ILIKE %s
                OR CAST(telefone AS TEXT) ILIKE %s
                OR email ILIKE %s
            )
            AND (%s = '' OR data_nascimento >= %s)
            AND (%s = '' OR data_nascimento <= %s)
            ORDER BY nome;
        """
        termo = f"%{busca}%"
        cursor.execute(consulta, (
            busca, termo, termo, termo, termo,
            nascimento_inicio, nascimento_inicio or "1900-01-01",
            nascimento_fim, nascimento_fim or "2999-12-31"
        ))

        clientes = cursor.fetchall()
        for c in clientes:
            c["cpf"] = str(c["cpf"]).zfill(11)
            c["telefone"] = str(c["telefone"])
            if c.get("data_nascimento"):
                c["data_nascimento"] = str(c["data_nascimento"])
        return jsonify(clientes), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/clientes", methods=["POST"])
def adicionar_cliente():
    dados = request.get_json(silent=True) or {}
    cpf = "".join(filter(str.isdigit, str(dados.get("cpf", ""))))
    nome = str(dados.get("nome", "")).strip()
    telefone = "".join(filter(str.isdigit, str(dados.get("telefone", ""))))
    email = str(dados.get("email", "")).strip()
    data_nascimento = str(dados.get("data_nascimento", "")).strip()

    if len(cpf) != 11:
        return jsonify({"erro": "CPF deve ter 11 dígitos numéricos."}), 400
    if not nome or not telefone or not email or not data_nascimento:
        return jsonify({"erro": "Todos os campos são obrigatórios."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            INSERT INTO cliente (cpf, nome, telefone, email, data_nascimento)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING cpf, nome, telefone, email, data_nascimento;
        """, (cpf, nome, telefone, email, data_nascimento))
        cliente = cursor.fetchone()
        conn.commit()
        cliente["cpf"] = str(cliente["cpf"]).zfill(11)
        cliente["telefone"] = str(cliente["telefone"])
        cliente["data_nascimento"] = str(cliente["data_nascimento"])
        return jsonify(cliente), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": f"Erro no banco de dados: {str(e)}"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
@app.route("/clientes/<cpf>", methods=["GET"])
def obter_cliente(cpf):
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT cpf, nome, telefone, email, data_nascimento FROM cliente WHERE cpf = %s;",
            (cpf_limpo,)
        )
        c = cursor.fetchone()
        if not c:
            return jsonify({"erro": "Cliente não encontrado."}), 404
        c["cpf"] = str(c["cpf"]).zfill(11)
        c["telefone"] = str(c["telefone"])
        c["data_nascimento"] = str(c["data_nascimento"])
        return jsonify(c), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
@app.route("/clientes/<cpf>", methods=["PUT"])
def alterar_cliente(cpf):
    dados = request.get_json(silent=True) or {}
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    nome = str(dados.get("nome", "")).strip()
    telefone = "".join(filter(str.isdigit, str(dados.get("telefone", ""))))
    email = str(dados.get("email", "")).strip()
    data_nascimento = str(dados.get("data_nascimento", "")).strip()

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            UPDATE cliente
            SET nome = %s, telefone = %s, email = %s, data_nascimento = %s
            WHERE cpf = %s
            RETURNING cpf, nome, telefone, email, data_nascimento;
        """, (nome, telefone, email, data_nascimento, cpf_limpo))
        cliente = cursor.fetchone()
        if not cliente:
            conn.rollback()
            return jsonify({"erro": "Cliente não encontrado."}), 404
        conn.commit()
        cliente["cpf"] = str(cliente["cpf"]).zfill(11)
        cliente["data_nascimento"] = str(cliente["data_nascimento"])
        return jsonify(cliente), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/clientes/<cpf>", methods=["DELETE"])
def excluir_cliente(cpf):
    cpf_limpo = "".join(filter(str.isdigit, str(cpf)))
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cliente WHERE cpf = %s;", (cpf_limpo,))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Cliente não encontrado."}), 404
        conn.commit()
        return jsonify({"mensagem": "Cliente removido com sucesso!"}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": "Não foi possível excluir: cliente possui vínculos ativos.", "detalhes": str(e)}), 409
    finally:
        if cursor: cursor.close()
        if conn: conn.close()




@app.route("/vendas", methods=["GET"])
@requer_keli
def obter_vendas():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT 
                v.id_venda,
                v.cpf_cliente,
                c.nome AS cliente,
                v.data_venda,
                v.valor_total,
                v.metodo_pagamento,
                COALESCE(string_agg(p.nome || ' x' || i.quantidade, ', ' ORDER BY p.nome), '') AS produtos,
                COALESCE(json_agg(json_build_object('id_produto', i.id_produto, 'quantidade', i.quantidade)) FILTER (WHERE i.id_produto IS NOT NULL), '[]') AS itens
            FROM venda v
             JOIN cliente c ON c.cpf = v.cpf_cliente
            LEFT JOIN item_venda i ON i.id_venda = v.id_venda
            LEFT JOIN produtos p ON p.id_produto = i.id_produto
            GROUP BY v.id_venda, v.cpf_cliente, c.nome, v.data_venda, v.valor_total, v.metodo_pagamento
            ORDER BY v.id_venda DESC;
        """)
        vendas = cursor.fetchall()
        for v in vendas:
            v["cpf_cliente"] = str(v["cpf_cliente"]).zfill(11)
            v["valor_total"] = float(v["valor_total"])
        return jsonify(vendas), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/vendas", methods=["POST"])
def adicionar_venda():
    bloqueio = bloquear_operacao_venda_para_amanda()
    if bloqueio:
        return bloqueio
    dados = request.get_json(silent=True) or {}
    cpf_cliente = "".join(filter(str.isdigit, str(dados.get("cpf_cliente", ""))))
    data_venda = str(dados.get("data_venda", "")).strip()
    metodo_pagamento = str(dados.get("metodo_pagamento", "")).strip()
    itens = dados.get("itens", [])

    if len(cpf_cliente) != 11:
        return jsonify({"erro": "CPF do cliente inválido."}), 400
    if not isinstance(itens, list) or not itens:
        return jsonify({"erro": "Adicione pelo menos um item à venda."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT cpf FROM cliente WHERE cpf = %s;", (cpf_cliente,))
        if not cursor.fetchone():
            conn.rollback()
            return jsonify({"erro": "Cliente não cadastrado no sistema."}), 404

        total = 0
        itens_proc = []
        for item in itens:
            id_p = int(item.get("id_produto"))
            qtd = int(item.get("quantidade", 1))
            if qtd <= 0:
                raise ValueError("A quantidade deve ser maior que zero.")
            cursor.execute("SELECT valor, estoque, disponivel FROM produtos WHERE id_produto = %s FOR UPDATE;", (id_p,))
            prod = cursor.fetchone()
            if not prod:
                raise ValueError(f"Produto {id_p} não encontrado.")
            if not prod["disponivel"]:
                raise ValueError(f"Produto {id_p} está indisponível.")
            if int(prod["estoque"]) < qtd:
                raise ValueError(f"Estoque insuficiente para o produto {id_p}. Disponível: {prod['estoque']}.")
            v_sub = float(prod["valor"]) * qtd
            total += v_sub
            itens_proc.append((id_p, qtd, v_sub))

        cursor.execute("""
            INSERT INTO venda (cpf_cliente, data_venda, valor_total, metodo_pagamento)
            VALUES (%s, %s, %s, %s) RETURNING id_venda;
        """, (cpf_cliente, data_venda, total, metodo_pagamento))
        
        id_venda = cursor.fetchone()["id_venda"]
        for id_p, qtd, v_sub in itens_proc:
            cursor.execute("""
                INSERT INTO item_venda (id_venda, id_produto, quantidade, valor_total)
                VALUES (%s, %s, %s, %s);
            """, (id_venda, id_p, qtd, v_sub))
            cursor.execute("UPDATE produtos SET estoque = estoque - %s WHERE id_produto = %s;", (qtd, id_p))

        conn.commit()
        return jsonify({"mensagem": "Venda realizada com sucesso!", "id_venda": id_venda, "valor_total": total}), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/vendas/<int:id_venda>", methods=["PUT"])
@requer_keli
def alterar_venda(id_venda):
    dados = request.get_json(silent=True) or {}
    cpf_cliente = "".join(filter(str.isdigit, str(dados.get("cpf_cliente", ""))))
    data_venda = str(dados.get("data_venda", "")).strip()
    metodo_pagamento = str(dados.get("metodo_pagamento", "")).strip()
    itens = dados.get("itens", [])

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT id_venda FROM venda WHERE id_venda = %s;", (id_venda,))
        if not cursor.fetchone():
            conn.rollback()
            return jsonify({"erro": "Venda não encontrada."}), 404

        cursor.execute("SELECT id_produto, quantidade FROM item_venda WHERE id_venda = %s FOR UPDATE;", (id_venda,))
        for antigo in cursor.fetchall():
            cursor.execute("UPDATE produtos SET estoque = estoque + %s WHERE id_produto = %s;", (antigo["quantidade"], antigo["id_produto"]))

        total = 0
        itens_proc = []
        for item in itens:
            id_p = int(item.get("id_produto"))
            qtd = int(item.get("quantidade", 1))
            if qtd <= 0:
                raise ValueError("A quantidade deve ser maior que zero.")
            cursor.execute("SELECT valor, estoque, disponivel FROM produtos WHERE id_produto = %s FOR UPDATE;", (id_p,))
            prod = cursor.fetchone()
            if not prod or not prod["disponivel"]:
                raise ValueError("Produto não encontrado ou indisponível.")
            if int(prod["estoque"]) < qtd:
                raise ValueError(f"Estoque insuficiente para o produto {id_p}.")
            v_sub = float(prod["valor"]) * qtd
            total += v_sub
            itens_proc.append((id_p, qtd, v_sub))

        cursor.execute("""
            UPDATE venda SET cpf_cliente=%s, data_venda=%s, valor_total=%s, metodo_pagamento=%s
            WHERE id_venda=%s;
        """, (cpf_cliente, data_venda, total, metodo_pagamento, id_venda))

        cursor.execute("DELETE FROM item_venda WHERE id_venda = %s;", (id_venda,))
        for id_p, qtd, v_sub in itens_proc:
            cursor.execute("""
                INSERT INTO item_venda (id_venda, id_produto, quantidade, valor_total)
                VALUES (%s, %s, %s, %s);
            """, (id_venda, id_p, qtd, v_sub))
            cursor.execute("UPDATE produtos SET estoque = estoque - %s WHERE id_produto = %s;", (qtd, id_p))

        conn.commit()
        return jsonify({"mensagem": "Venda atualizada com sucesso!"}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/vendas/<int:id_venda>", methods=["DELETE"])
@requer_keli
def excluir_venda(id_venda):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, quantidade FROM item_venda WHERE id_venda = %s;", (id_venda,))
        for item in cursor.fetchall():
            cursor.execute("UPDATE produtos SET estoque = estoque + %s WHERE id_produto = %s;", (item[1], item[0]))
        cursor.execute("DELETE FROM venda WHERE id_venda = %s;", (id_venda,))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Venda não encontrada."}), 404
        conn.commit()
        return jsonify({"mensagem": "Venda excluída com sucesso!"}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()




@app.route("/itens-venda", methods=["GET"])
@requer_keli
def obter_itens_venda():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                i.id_venda,
                i.id_produto,
                i.quantidade,
                i.retirado,
                CASE
                    WHEN i.quantidade > 0 THEN i.valor_total / i.quantidade
                    ELSE 0
                END AS valor_unitario,
                p.nome AS nome_produto
            FROM item_venda i
            INNER JOIN produtos p ON p.id_produto = i.id_produto
            ORDER BY i.id_venda DESC, p.nome;
        """)
        itens = cursor.fetchall()
        for item in itens:
            item["valor_unitario"] = float(item["valor_unitario"] or 0)
        return jsonify(itens), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/itens-venda", methods=["POST"])
@requer_keli
def adicionar_item_venda():
    dados = request.get_json(silent=True) or {}
    try:
        id_venda = int(dados.get("id_venda"))
        id_produto = int(dados.get("id_produto"))
        quantidade = int(dados.get("quantidade"))
        valor_unitario = float(dados.get("valor_unitario"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Venda, produto, quantidade e valor unitário são obrigatórios."}), 400

    if id_venda <= 0 or id_produto <= 0 or quantidade <= 0 or valor_unitario < 0:
        return jsonify({"erro": "Informe valores válidos."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id_venda FROM venda WHERE id_venda = %s;", (id_venda,))
        if not cursor.fetchone():
            return jsonify({"erro": "Venda não encontrada."}), 404

        cursor.execute("SELECT estoque, disponivel FROM produtos WHERE id_produto = %s FOR UPDATE;", (id_produto,))
        produto = cursor.fetchone()
        if not produto or not produto["disponivel"]:
            return jsonify({"erro": "Produto não encontrado ou indisponível."}), 404
        if int(produto["estoque"]) < quantidade:
            return jsonify({"erro": "Estoque insuficiente para esta quantidade."}), 409

        valor_total = round(valor_unitario * quantidade, 2)
        cursor.execute("""
            INSERT INTO item_venda (id_venda, id_produto, quantidade, valor_total)
            VALUES (%s, %s, %s, %s)
            RETURNING id_venda, id_produto, quantidade, valor_total;
        """, (id_venda, id_produto, quantidade, valor_total))
        item = cursor.fetchone()
        cursor.execute("UPDATE produtos SET estoque = estoque - %s WHERE id_produto = %s;", (quantidade, id_produto))

        cursor.execute("""
            UPDATE venda
            SET valor_total = (
                SELECT COALESCE(SUM(valor_total), 0)
                FROM item_venda
                WHERE id_venda = %s
            )
            WHERE id_venda = %s;
        """, (id_venda, id_venda))
        conn.commit()
        return jsonify({
            "mensagem": "Item adicionado à venda.",
            "id_venda": item["id_venda"],
            "id_produto": item["id_produto"],
            "quantidade": item["quantidade"],
            "valor_total": float(item["valor_total"])
        }), 201
    except psycopg2.IntegrityError:
        if conn: conn.rollback()
        return jsonify({"erro": "Este produto já está vinculado a essa venda. Edite o item existente."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/itens-venda/<int:id_venda>/<int:id_produto>/retirada", methods=["PATCH"])
@requer_keli
def atualizar_status_retirada(id_venda, id_produto):
    dados = request.get_json(silent=True) or {}
    retirado = dados.get("retirado")

    if not isinstance(retirado, bool):
        return jsonify({"erro": "Informe o status de retirada (true ou false)."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE item_venda
            SET retirado = %s
            WHERE id_venda = %s AND id_produto = %s;
        """, (retirado, id_venda, id_produto))

        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Item da venda não encontrado."}), 404

        conn.commit()
        return jsonify({
            "mensagem": "Status de retirada atualizado com sucesso.",
            "id_venda": id_venda,
            "id_produto": id_produto,
            "retirado": retirado
        }), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/itens-venda/<int:id_venda>/<int:id_produto>", methods=["PUT"])
@requer_keli
def alterar_item_venda(id_venda, id_produto):
    dados = request.get_json(silent=True) or {}
    try:
        quantidade = int(dados.get("quantidade"))
        valor_unitario = float(dados.get("valor_unitario"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Quantidade e valor unitário são obrigatórios."}), 400

    if quantidade <= 0 or valor_unitario < 0:
        return jsonify({"erro": "Informe quantidade e valor unitário válidos."}), 400

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT quantidade FROM item_venda WHERE id_venda=%s AND id_produto=%s FOR UPDATE", (id_venda,id_produto))
        antigo = cursor.fetchone()
        if not antigo:
            return jsonify({"erro": "Item da venda não encontrado."}), 404
        diferenca = quantidade - int(antigo[0])
        if diferenca > 0:
            cursor.execute("SELECT estoque FROM produtos WHERE id_produto=%s FOR UPDATE", (id_produto,))
            estoque_atual = cursor.fetchone()
            if not estoque_atual or int(estoque_atual[0]) < diferenca:
                return jsonify({"erro": "Estoque insuficiente para aumentar a quantidade."}), 409
            cursor.execute("UPDATE produtos SET estoque=estoque-%s WHERE id_produto=%s", (diferenca,id_produto))
        elif diferenca < 0:
            cursor.execute("UPDATE produtos SET estoque=estoque+%s WHERE id_produto=%s", (-diferenca,id_produto))
        valor_total = round(valor_unitario * quantidade, 2)
        cursor.execute("""
            UPDATE item_venda
            SET quantidade = %s, valor_total = %s
            WHERE id_venda = %s AND id_produto = %s;
        """, (quantidade, valor_total, id_venda, id_produto))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Item da venda não encontrado."}), 404

        cursor.execute("""
            UPDATE venda
            SET valor_total = (
                SELECT COALESCE(SUM(valor_total), 0)
                FROM item_venda
                WHERE id_venda = %s
            )
            WHERE id_venda = %s;
        """, (id_venda, id_venda))
        conn.commit()
        return jsonify({"mensagem": "Item da venda alterado com sucesso."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/itens-venda/<int:id_venda>/<int:id_produto>", methods=["DELETE"])
@requer_keli
def excluir_item_venda(id_venda, id_produto):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT quantidade FROM item_venda WHERE id_venda=%s AND id_produto=%s", (id_venda,id_produto))
        item_antigo = cursor.fetchone()
        if item_antigo:
            cursor.execute("UPDATE produtos SET estoque=estoque+%s WHERE id_produto=%s", (item_antigo[0],id_produto))
        cursor.execute(
            "DELETE FROM item_venda WHERE id_venda = %s AND id_produto = %s;",
            (id_venda, id_produto)
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Item da venda não encontrado."}), 404

        cursor.execute("""
            UPDATE venda
            SET valor_total = (
                SELECT COALESCE(SUM(valor_total), 0)
                FROM item_venda
                WHERE id_venda = %s
            )
            WHERE id_venda = %s;
        """, (id_venda, id_venda))
        conn.commit()
        return jsonify({"mensagem": "Item removido da venda com sucesso."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()




@app.route("/relatorio-produtos-2026", methods=["GET"])
@requer_keli
def relatorio_produtos_2026():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                p.id_produto,
                p.nome,
                COUNT(iv.id_venda) AS quantidade_vendas,
                SUM(iv.quantidade) AS unidades_vendidas,
                SUM(iv.valor_total) AS faturamento,
                MIN(iv.valor_total) AS menor_valor,
                MAX(iv.valor_total) AS maior_valor
            FROM produtos p
            INNER JOIN item_venda iv
                ON p.id_produto = iv.id_produto
            INNER JOIN venda v
                ON iv.id_venda = v.id_venda
            WHERE v.data_venda BETWEEN %s AND %s
            GROUP BY p.id_produto, p.nome
            ORDER BY unidades_vendidas DESC;
        """, ("2026-01-01", "2026-12-31"))

        resultados = cursor.fetchall()
        dados = []
        for linha in resultados:
            dados.append({
                "id_produto": linha["id_produto"],
                "nome": linha["nome"],
                "quantidade_vendas": int(linha["quantidade_vendas"] or 0),
                "unidades_vendidas": int(linha["unidades_vendidas"] or 0),
                "faturamento": float(linha["faturamento"] or 0),
                "menor_valor": float(linha["menor_valor"] or 0),
                "maior_valor": float(linha["maior_valor"] or 0)
            })

        return jsonify(dados), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()



@app.route("/relatorio-atendimentos-profissional", methods=["GET"])
def relatorio_atendimentos_profissional():
    profissional = request.args.get("profissional", "").strip().lower()
    data_inicio = request.args.get("data_inicio", "").strip()
    data_fim = request.args.get("data_fim", "").strip()

    mapeamento_profissionais = {
        "keli": "Keli Kuhn",
        "amanda": "Amanda Rauber"
    }
    nome_profissional = mapeamento_profissionais.get(profissional, profissional)

    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                a.id_atendimento,
                a.data_atendimento,
                a.hora_atendimento,
                c.nome AS cliente,
                c.telefone,
                a.servico,
                COALESCE(a.valor, 0) AS valor,
                COALESCE(a.status, 'Concluído') AS status,
                a.observacao
            FROM atendimento a
            LEFT JOIN cliente c ON c.cpf = a.cpf_cliente
            WHERE 1=1
        """
        params = []

        if nome_profissional:
            query += " AND LOWER(a.profissional) LIKE %s"
            params.append(f"%{nome_profissional.lower()}%")

        if data_inicio:
            query += " AND a.data_atendimento >= %s"
            params.append(data_inicio)

        if data_fim:
            query += " AND a.data_atendimento <= %s"
            params.append(data_fim)

        query += " ORDER BY a.data_atendimento DESC, a.hora_atendimento DESC;"

        cursor.execute(query, tuple(params))
        atendimentos = cursor.fetchall()

        total_atendimentos = len(atendimentos)
        concluidos = sum(1 for item in atendimentos if str(item.get("status", "")).lower() == "concluído")
        faturamento_total = sum(float(item.get("valor", 0)) for item in atendimentos)

        lista_formatada = []
        for a in atendimentos:
            lista_formatada.append({
                "id_atendimento": a["id_atendimento"],
                "data_atendimento": str(a["data_atendimento"]),
                "hora_atendimento": str(a["hora_atendimento"]),
                "cliente": a["cliente"] or "Não informado",
                "telefone": a["telefone"] or "-",
                "servico": a["servico"],
                "valor": float(a["valor"]),
                "status": a["status"],
                "observacao": a["observacao"] or "-"
            })

        return jsonify({
            "profissional": nome_profissional or "Todas",
            "total_atendimentos": total_atendimentos,
            "concluidos": concluidos,
            "faturamento_total": faturamento_total,
            "atendimentos": lista_formatada
        }), 200

    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()




def obter_cpf_funcionaria(cursor, usuario):
    """Localiza a profissional pela conta; CPF pode vir da base ou de variável de ambiente."""
    garantir_tabela_funcionarias(cursor.connection)
    env_cpf = "".join(ch for ch in os.getenv(f"{usuario.upper()}_CPF", FUNCIONARIAS_DB.get(usuario, {}).get("cpf", "")) if ch.isdigit())
    nome_profissional = FUNCIONARIAS_DB.get(usuario, {}).get("nome", usuario)
    cursor.execute("SELECT cpf FROM funcionaria WHERE LOWER(usuario)=%s OR LOWER(nome)=%s LIMIT 1", (usuario.lower(), nome_profissional.lower()))
    row = cursor.fetchone()
    if row:
        cpf_atual = "".join(ch for ch in str(row["cpf"]) if ch.isdigit())
        if len(env_cpf) == 11 and env_cpf != cpf_atual and usuario in FUNCIONARIAS_DB:
            cursor.execute("UPDATE funcionaria SET cpf=%s WHERE LOWER(usuario)=%s OR LOWER(nome)=%s", (env_cpf, usuario.lower(), nome_profissional.lower()))
            cursor.connection.commit()
            return env_cpf
        return cpf_atual

    if len(env_cpf) == 11 and usuario in FUNCIONARIAS_DB:
        profissional = FUNCIONARIAS_DB[usuario]
        cursor.execute("""INSERT INTO funcionaria (usuario, cpf, nome, especialidades, emoji, senha_hash)
                          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (cpf) DO UPDATE SET usuario=EXCLUDED.usuario
                          RETURNING cpf""", (usuario, env_cpf, profissional["nome"], profissional["funcao"], profissional.get("emoji", "👩‍💼"), generate_password_hash(profissional["senha"])))
        row = cursor.fetchone()
        return str(row["cpf"]).strip() if row else env_cpf
    return env_cpf


def garantir_coluna_status_agenda(cursor):
    """Adiciona status sem apagar os horários já cadastrados."""
    cursor.execute("ALTER TABLE agenda_funcionaria ADD COLUMN IF NOT EXISTS status VARCHAR(10) NOT NULL DEFAULT 'livre'")


def validar_data_horario(data, hora):
    from datetime import date, time
    try:
        d = date.fromisoformat(str(data))
        h = time.fromisoformat(str(hora))
    except (TypeError, ValueError):
        return False, "Informe uma data e um horário válidos."
    
    if d.weekday() not in (1, 2, 3, 4, 5):
        return False, "A agenda funciona somente de terça-feira a sábado."
    minutos = h.hour * 60 + h.minute
    inicio, fim = 7 * 60 + 30, 17 * 60 + 30
    if minutos < inicio or minutos > fim or (minutos - inicio) % 30 != 0 or h.second != 0:
        return False, "Escolha um horário de 30 em 30 minutos, entre 07:30 e 17:30. O expediente termina às 18:00."
    return True, ""




def garantir_tabela_servicos(conn):
    with conn.cursor() as cursor:
        cursor.execute("""CREATE TABLE IF NOT EXISTS servico_profissional (
            id SERIAL PRIMARY KEY,
            usuario_funcionaria VARCHAR(50) NOT NULL,
            nome VARCHAR(120) NOT NULL,
            descricao TEXT DEFAULT '',
            preco NUMERIC(10,2) NOT NULL DEFAULT 0,
            duracao_minutos INTEGER NOT NULL DEFAULT 60,
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(usuario_funcionaria, nome)
        )""")
    conn.commit()


@app.route("/servicos", methods=["GET", "POST"])
def servicos_profissionais():
    conn = cursor = None
    try:
        conn = get_db_connection()
        garantir_tabela_funcionarias(conn)
        garantir_tabela_servicos(conn)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if request.method == "GET":
            cursor.execute("""SELECT s.id, s.usuario_funcionaria AS usuario, s.nome, s.descricao,
                              s.preco, s.duracao_minutos, s.ativo,
                              COALESCE(f.nome, CASE s.usuario_funcionaria WHEN 'keli' THEN 'Keli Kuhn' WHEN 'amanda' THEN 'Amanda Rauber' END, s.usuario_funcionaria) AS profissional
                              FROM servico_profissional s LEFT JOIN funcionaria f ON f.usuario=s.usuario_funcionaria
                              WHERE s.ativo=TRUE ORDER BY profissional, s.nome""")
            rows = cursor.fetchall()
            return jsonify([{**dict(r), 'preco': float(r['preco'])} for r in rows]), 200

        usuario = usuario_autenticado()
        if not usuario:
            return jsonify({"erro": "Faça login para cadastrar serviços."}), 401
        dados = request.get_json(silent=True) or {}
        nome = str(dados.get('nome', '')).strip()
        descricao = str(dados.get('descricao', '')).strip()
        try:
            preco = float(dados.get('preco', 0))
            duracao = int(dados.get('duracao_minutos', 60))
        except (TypeError, ValueError):
            return jsonify({"erro": "Preço e duração devem ser numéricos."}), 400
        if not nome or preco < 0 or duracao < 1:
            return jsonify({"erro": "Informe nome, preço válido e duração maior que zero."}), 400
        cursor.execute("""INSERT INTO servico_profissional (usuario_funcionaria,nome,descricao,preco,duracao_minutos)
                          VALUES (%s,%s,%s,%s,%s) RETURNING id""", (usuario,nome,descricao,preco,duracao))
        novo_id = cursor.fetchone()['id']
        conn.commit()
        return jsonify({"mensagem": "Serviço cadastrado com sucesso!", "id": novo_id}), 201
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Você já cadastrou um serviço com esse nome."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/servicos/<int:servico_id>", methods=["PUT"])
def editar_servico_profissional(servico_id):
    usuario = usuario_autenticado()
    if not usuario:
        return jsonify({"erro": "Faça login para editar serviços."}), 401
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome", "")).strip()
    descricao = str(dados.get("descricao", "")).strip()
    try:
        preco = float(dados.get("preco", 0))
        duracao = int(dados.get("duracao_minutos", 0))
    except (TypeError, ValueError):
        return jsonify({"erro": "Preço e duração devem ser numéricos."}), 400
    if not nome or preco < 0 or duracao < 1:
        return jsonify({"erro": "Informe nome, preço válido e duração maior que zero."}), 400
    conn = cursor = None
    try:
        conn = get_db_connection()
        garantir_tabela_servicos(conn)
        cursor = conn.cursor()
        cursor.execute("UPDATE servico_profissional SET nome=%s, descricao=%s, preco=%s, duracao_minutos=%s WHERE id=%s AND usuario_funcionaria=%s", (nome, descricao, preco, duracao, servico_id, usuario))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Serviço não encontrado ou não pertence à sua conta."}), 404
        conn.commit()
        return jsonify({"mensagem": "Serviço atualizado com sucesso."}), 200
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Você já possui outro serviço com esse nome."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/servicos/<int:servico_id>", methods=["DELETE"])
def excluir_servico_profissional(servico_id):
    usuario = usuario_autenticado()
    if not usuario:
        return jsonify({"erro": "Faça login para excluir serviços."}), 401
    conn = cursor = None
    try:
        conn = get_db_connection()
        garantir_tabela_servicos(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM servico_profissional WHERE id=%s AND usuario_funcionaria=%s", (servico_id, usuario))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({"erro": "Serviço não encontrado ou não pertence à sua conta."}), 404
        conn.commit()
        return jsonify({"mensagem": "Serviço excluído."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/horarios", methods=["GET", "POST", "DELETE"])
def horarios_disponiveis():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("ALTER TABLE agendamento ADD COLUMN IF NOT EXISTS cpf_funcionaria VARCHAR(11)")
        garantir_coluna_status_agenda(cursor)
        usuario = str(request.args.get("usuario", "") if request.method == "GET" else (request.get_json(silent=True) or {}).get("usuario", "")).strip().lower()
        cpf_func = obter_cpf_funcionaria(cursor, usuario)
        if len(cpf_func) != 11:
            return jsonify({"erro": f"Cadastre o CPF de {usuario} na tabela funcionaria ou configure {usuario.upper()}_CPF no ambiente."}), 400

        if request.method == "GET":
            
            eh_painel = request.args.get("painel", "0") == "1"
            if eh_painel:
                cursor.execute("""SELECT af.id_agenda AS id, af.data, af.horario AS hora,
                                  CASE WHEN af.status='ocupado' OR EXISTS (
                                    SELECT 1 FROM agendamento a WHERE a.cpf_funcionaria=af.cpf_funcionaria
                                      AND a.data_atendimento=af.data AND a.hora=af.horario
                                  ) THEN 'ocupado' ELSE 'livre' END AS status
                                  FROM agenda_funcionaria af
                                  WHERE af.cpf_funcionaria=%s AND af.data >= CURRENT_DATE
                                  ORDER BY af.data, af.horario""", (cpf_func,))
            else:
                cursor.execute("""SELECT af.id_agenda AS id, af.data, af.horario AS hora
                                  FROM agenda_funcionaria af
                                  WHERE af.cpf_funcionaria=%s AND af.status='livre'
                                    AND (af.data > CURRENT_DATE OR (af.data=CURRENT_DATE AND af.horario > LOCALTIME))
                                    AND NOT EXISTS (SELECT 1 FROM agendamento a WHERE a.cpf_funcionaria=af.cpf_funcionaria
                                      AND a.data_atendimento=af.data AND a.hora=af.horario)
                                  ORDER BY af.data, af.horario""", (cpf_func,))
            rows = cursor.fetchall()
            for row in rows:
                row["data"] = str(row["data"])
                row["hora"] = str(row["hora"])
            return jsonify(rows), 200

        dados = request.get_json(silent=True) or {}
        if request.method == "DELETE":
            
            cursor.execute("""DELETE FROM agenda_funcionaria af
                              WHERE af.cpf_funcionaria=%s
                                AND NOT EXISTS (
                                  SELECT 1 FROM agendamento a
                                  WHERE a.cpf_funcionaria=af.cpf_funcionaria
                                    AND a.data_atendimento=af.data
                                    AND a.hora=af.horario
                                )""", (cpf_func,))
            removidos = cursor.rowcount
            cursor.execute("""SELECT COUNT(*) AS preservados FROM agenda_funcionaria af
                              WHERE af.cpf_funcionaria=%s
                                AND EXISTS (
                                  SELECT 1 FROM agendamento a
                                  WHERE a.cpf_funcionaria=af.cpf_funcionaria
                                    AND a.data_atendimento=af.data
                                    AND a.hora=af.horario
                                )""", (cpf_func,))
            preservados = int(cursor.fetchone()["preservados"])
            conn.commit()
            return jsonify({"mensagem": f"{removidos} horário(s) excluído(s). {preservados} horário(s) com agendamento confirmado foram preservados.", "removidos": removidos, "preservados": preservados}), 200

        
        if dados.get("acao") == "gerar_padrao":
            from datetime import date, timedelta
            try:
                inicio = date.fromisoformat(str(dados.get("data_inicio", "")))
                fim = date.fromisoformat(str(dados.get("data_fim", "")))
            except ValueError:
                return jsonify({"erro": "Informe as datas inicial e final."}), 400
            if fim < inicio:
                return jsonify({"erro": "A data final não pode ser anterior à inicial."}), 400
            if (fim - inicio).days > 365:
                return jsonify({"erro": "Gere no máximo um ano de agenda por vez."}), 400
            inseridos = 0
            dia = inicio
            while dia <= fim:
                if dia.weekday() in (1, 2, 3, 4, 5):
                    minutos = 7 * 60 + 30
                    while minutos <= 17 * 60 + 30:
                        hora = f"{minutos // 60:02d}:{minutos % 60:02d}"
                        cursor.execute("""INSERT INTO agenda_funcionaria (cpf_funcionaria,data,horario,status)
                                          VALUES (%s,%s,%s,'livre') ON CONFLICT DO NOTHING""", (cpf_func, dia.isoformat(), hora))
                        inseridos += cursor.rowcount
                        minutos += 30
                dia += timedelta(days=1)
            conn.commit()
            return jsonify({"mensagem": f"Agenda padrão criada. {inseridos} horários novos adicionados.", "inseridos": inseridos}), 201

        data = str(dados.get("data", "")); hora = str(dados.get("hora", ""))
        valido, erro = validar_data_horario(data, hora)
        if not valido:
            return jsonify({"erro": erro}), 400
        cursor.execute("INSERT INTO agenda_funcionaria (cpf_funcionaria,data,horario,status) VALUES (%s,%s,%s,'livre') RETURNING id_agenda", (cpf_func,data,hora))
        novo = cursor.fetchone(); conn.commit()
        return jsonify({"id": novo["id_agenda"], "data": data, "hora": hora, "status": "livre"}), 201
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Este horário já foi cadastrado para a profissional."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/horarios/<int:id_horario>", methods=["PUT", "DELETE"])
def alterar_ou_excluir_horario(id_horario):
    conn = cursor = None
    try:
        dados = request.get_json(silent=True) or {}
        usuario = str(dados.get("usuario", "")).strip().lower()
        conn = get_db_connection(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        garantir_coluna_status_agenda(cursor)
        cpf_func = obter_cpf_funcionaria(cursor, usuario)
        if request.method == "DELETE":
            cursor.execute("""DELETE FROM agenda_funcionaria af WHERE af.id_agenda=%s AND af.cpf_funcionaria=%s
                              AND NOT EXISTS (SELECT 1 FROM agendamento a WHERE a.cpf_funcionaria=af.cpf_funcionaria
                                AND a.data_atendimento=af.data AND a.hora=af.horario)""", (id_horario,cpf_func))
            if cursor.rowcount == 0:
                conn.rollback(); return jsonify({"erro": "Horário não encontrado ou já possui agendamento confirmado."}), 409
            conn.commit(); return jsonify({"mensagem": "Horário removido."}), 200

        cursor.execute("SELECT data, horario FROM agenda_funcionaria WHERE id_agenda=%s AND cpf_funcionaria=%s FOR UPDATE", (id_horario,cpf_func))
        atual = cursor.fetchone()
        if not atual:
            conn.rollback(); return jsonify({"erro": "Horário não encontrado."}), 404
        status = str(dados.get("status", "")).lower()
        data = str(dados.get("data", atual["data"]))
        hora = str(dados.get("hora", atual["horario"]))
        if status not in ("livre", "ocupado"):
            conn.rollback(); return jsonify({"erro": "Status inválido."}), 400
        valido, erro = validar_data_horario(data,hora)
        if not valido:
            conn.rollback(); return jsonify({"erro": erro}), 400
        if status == "livre":
            cursor.execute("SELECT 1 FROM agendamento WHERE cpf_funcionaria=%s AND data_atendimento=%s AND hora=%s", (cpf_func,data,hora))
            if cursor.fetchone():
                conn.rollback(); return jsonify({"erro": "Este horário possui um agendamento confirmado e não pode ser liberado."}), 409
        cursor.execute("UPDATE agenda_funcionaria SET data=%s, horario=%s, status=%s WHERE id_agenda=%s AND cpf_funcionaria=%s", (data,hora,status,id_horario,cpf_func))
        conn.commit(); return jsonify({"mensagem": "Horário atualizado."}), 200
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"erro": "Já existe outro horário nessa data e hora."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


def horarios_em_blocos(hora_inicio, duracao_minutos):
    """Retorna os horários de 30 min ocupados por um serviço."""
    from datetime import datetime, timedelta
    inicio = datetime.strptime(str(hora_inicio)[:5], "%H:%M")
    quantidade = max(1, (int(duracao_minutos) + 29) // 30)
    return [(inicio + timedelta(minutes=30 * i)).strftime("%H:%M") for i in range(quantidade)]

def reservar_blocos_agenda(cursor, cpf_func, data, hora, duracao_minutos, liberar_horarios=None):
    """Valida e marca como ocupados todos os blocos de 30 min do atendimento."""
    blocos = horarios_em_blocos(hora, duracao_minutos)
    if not blocos or any(int(x[:2]) * 60 + int(x[3:]) > 17 * 60 + 30 for x in blocos):
        raise ValueError("A duração do serviço ultrapassa o horário de funcionamento.")
    for bloco in blocos:
        cursor.execute("SELECT id_agenda, status FROM agenda_funcionaria WHERE cpf_funcionaria=%s AND data=%s AND horario=%s FOR UPDATE", (cpf_func, data, bloco))
        slot = cursor.fetchone()
        if not slot or (slot["status"] != "livre" and bloco not in (liberar_horarios or [])):
            raise ValueError("Não há horários consecutivos suficientes para a duração deste serviço.")
    for bloco in blocos:
        cursor.execute("UPDATE agenda_funcionaria SET status='ocupado' WHERE cpf_funcionaria=%s AND data=%s AND horario=%s", (cpf_func, data, bloco))
    return blocos

def liberar_blocos_agenda(cursor, cpf_func, data, hora, duracao_minutos):
    for bloco in horarios_em_blocos(hora, duracao_minutos):
        cursor.execute("UPDATE agenda_funcionaria SET status='livre' WHERE cpf_funcionaria=%s AND data=%s AND horario=%s", (cpf_func, data, bloco))


@app.route("/agendamentos", methods=["GET", "POST"])
def agendamentos_api():
    conn = cursor = None
    try:
        conn = get_db_connection(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("ALTER TABLE agendamento ADD COLUMN IF NOT EXISTS cpf_funcionaria VARCHAR(11)")
        if request.method == "GET":
            usuario = str(request.args.get("usuario", "")).strip().lower()
            cpf_func = obter_cpf_funcionaria(cursor, usuario)
            cursor.execute("""SELECT a.id_agendamento, a.data_atendimento, a.hora, c.nome AS cliente,
                              c.telefone, a.tipo_atendimento AS servico, a.observacoes
                              FROM agendamento a JOIN cliente c ON c.cpf=a.cpf
                              WHERE (%s='' OR a.cpf_funcionaria=%s)
                              ORDER BY a.data_atendimento, a.hora""", (usuario, cpf_func))
            rows = cursor.fetchall()
            for row in rows:
                row["data_atendimento"] = str(row["data_atendimento"]); row["hora"] = str(row["hora"])
                row["telefone"] = str(row["telefone"])
            return jsonify(rows), 200
        dados = request.get_json(silent=True) or {}
        usuario = str(dados.get("profissional", "")).strip().lower()
        cpf_func = obter_cpf_funcionaria(cursor, usuario)
        cpf_cliente = "".join(ch for ch in str(dados.get("cpf", "")) if ch.isdigit())
        nome = str(dados.get("nome", "")).strip(); telefone = "".join(ch for ch in str(dados.get("telefone", "")) if ch.isdigit())
        email = str(dados.get("email", "")).strip(); nascimento = str(dados.get("data_nascimento", "")); data = str(dados.get("data", "")); hora = str(dados.get("hora", ""))
        servico_id = dados.get("id_servico")
        obs = str(dados.get("observacoes", "")).strip()
        if len(cpf_func) != 11 or len(cpf_cliente) != 11 or not all([nome, telefone, email, nascimento, data, hora, servico_id]):
            return jsonify({"erro": "Preencha os dados obrigatórios e selecione um serviço cadastrado para a profissional."}), 400
        cursor.execute("SELECT nome, preco, duracao_minutos FROM servico_profissional WHERE id=%s AND usuario_funcionaria=%s AND ativo=TRUE", (servico_id, usuario))
        servico_row = cursor.fetchone()
        if not servico_row:
            return jsonify({"erro": "O serviço selecionado não pertence a esta profissional ou não está disponível."}), 400
        servico = servico_row["nome"]
        preco_servico = servico_row["preco"]
        duracao_servico = int(servico_row["duracao_minutos"] or 30)
        cursor.execute("INSERT INTO cliente (cpf,nome,telefone,email,data_nascimento) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (cpf) DO UPDATE SET nome=EXCLUDED.nome, telefone=EXCLUDED.telefone, email=EXCLUDED.email", (cpf_cliente,nome,telefone,email,nascimento))
        try:
            reservar_blocos_agenda(cursor, cpf_func, data, hora, duracao_servico)
        except ValueError as erro:
            conn.rollback(); return jsonify({"erro": str(erro)}), 409
        cursor.execute("""INSERT INTO agendamento (data_atendimento,hora,cpf,tipo_atendimento,observacoes,valor_total,cpf_funcionaria)
                          VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id_agendamento""", (data,hora,cpf_cliente,servico,obs,preco_servico,cpf_func))
        novo = cursor.fetchone(); conn.commit()
        return jsonify({"mensagem":"Agendamento confirmado!", "id_agendamento":novo["id_agendamento"]}), 201
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@app.route("/agendamentos/<int:id_agendamento>", methods=["PUT", "DELETE"])
def gerenciar_agendamento_api(id_agendamento):
    usuario = usuario_autenticado()
    if not usuario:
        return jsonify({"erro": "Faça login para gerenciar agendamentos."}), 401
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cpf_func = obter_cpf_funcionaria(cursor, usuario)
        if len(cpf_func) != 11:
            conn.rollback()
            return jsonify({"erro": "Não foi possível identificar a funcionária logada."}), 400
        cursor.execute("SELECT id_agendamento, data_atendimento, hora, tipo_atendimento FROM agendamento WHERE id_agendamento=%s AND cpf_funcionaria=%s FOR UPDATE", (id_agendamento, cpf_func))
        atual = cursor.fetchone()
        if not atual:
            conn.rollback()
            return jsonify({"erro": "Agendamento não encontrado ou não pertence à sua conta."}), 404

        cursor.execute("SELECT duracao_minutos FROM servico_profissional WHERE usuario_funcionaria=%s AND nome=%s ORDER BY id DESC LIMIT 1", (usuario, atual["tipo_atendimento"]))
        servico_antigo = cursor.fetchone()
        duracao_antiga = int(servico_antigo["duracao_minutos"] or 30) if servico_antigo else 30
        if request.method == "DELETE":
            liberar_blocos_agenda(cursor, cpf_func, atual["data_atendimento"], atual["hora"], duracao_antiga)
            cursor.execute("DELETE FROM agendamento WHERE id_agendamento=%s AND cpf_funcionaria=%s", (id_agendamento, cpf_func))
            conn.commit()
            return jsonify({"mensagem": "Agendamento excluído e horário liberado."}), 200

        dados = request.get_json(silent=True) or {}
        data = str(dados.get("data", "")).strip()
        hora = str(dados.get("hora", "")).strip()
        servico_id = dados.get("id_servico")
        obs = str(dados.get("observacoes", "")).strip()
        if not data or not hora or not servico_id:
            conn.rollback()
            return jsonify({"erro": "Informe data, horário e serviço."}), 400
        cursor.execute("SELECT nome, preco, duracao_minutos FROM servico_profissional WHERE id=%s AND usuario_funcionaria=%s AND ativo=TRUE", (servico_id, usuario))
        servico = cursor.fetchone()
        if not servico:
            conn.rollback()
            return jsonify({"erro": "Serviço inválido ou não pertence à sua conta."}), 400
        # Libera os blocos antigos dentro da transação para permitir manter o mesmo horário.
        liberar_blocos_agenda(cursor, cpf_func, atual["data_atendimento"], atual["hora"], duracao_antiga)
        try:
            reservar_blocos_agenda(cursor, cpf_func, data, hora, int(servico["duracao_minutos"] or 30))
        except ValueError as erro:
            conn.rollback()
            return jsonify({"erro": str(erro)}), 409
        cursor.execute("UPDATE agendamento SET data_atendimento=%s, hora=%s, tipo_atendimento=%s, valor_total=%s, observacoes=%s WHERE id_agendamento=%s AND cpf_funcionaria=%s", (data, hora, servico["nome"], servico["preco"], obs, id_agendamento, cpf_func))
        conn.commit()
        return jsonify({"mensagem": "Agendamento atualizado com sucesso."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
