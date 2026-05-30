"""
ERP Bebidas - Autenticação e permissões (PostgreSQL)
"""
from core.database import get_connection, hash_password

PERMISSOES = {
    "admin":       {"clientes":["ver","criar","editar","bloquear","desbloquear","avaliar"],
                    "stock":   ["ver","entrada","saida","transferencia","ajuste"],
                    "vendas":  ["ver","criar","editar","cancelar","pagar"],
                    "utilizadores":["ver","criar","editar"],"relatorios":["ver","exportar"]},
    "encarregado": {"clientes":["ver","editar","desbloquear","avaliar"],
                    "stock":   ["ver","entrada","saida","transferencia"],
                    "vendas":  ["ver","criar","editar","pagar"],
                    "utilizadores":["ver"],"relatorios":["ver","exportar"]},
    "condutor":    {"clientes":["ver"],"stock":["ver","saida"],"vendas":["ver"],
                    "utilizadores":[],"relatorios":[]},
}


def login(username, password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT u.*,a.nome as armazem_nome FROM utilizadores u
                 LEFT JOIN armazens a ON u.armazem_id=a.id
                 WHERE u.username=%s AND u.password_hash=%s AND u.ativo=1""",
              (username, hash_password(password)))
    user = c.fetchone(); conn.close()
    if user: return {"ok": True, "utilizador": dict(user)}
    return {"ok": False, "erro": "Credenciais inválidas"}


def tem_permissao(perfil, modulo, acao):
    return acao in PERMISSOES.get(perfil, {}).get(modulo, [])


def listar_utilizadores():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT u.*,a.nome as armazem_nome FROM utilizadores u
                 LEFT JOIN armazens a ON u.armazem_id=a.id ORDER BY u.perfil,u.nome""")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]


def criar_utilizador(dados):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO utilizadores (nome,username,password_hash,perfil,armazem_id)
                     VALUES (%(nome)s,%(username)s,%(password_hash)s,%(perfil)s,%(armazem_id)s)""",
                  {**dados, "password_hash": hash_password(dados["password"])})
        conn.commit(); conn.close(); return {"ok": True}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def listar_armazens():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM armazens WHERE ativo=1 ORDER BY nome")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]


def listar_produtos(apenas_ativos=True):
    conn = get_connection()
    c = conn.cursor()
    sql = "SELECT * FROM produtos" + (" WHERE ativo=1" if apenas_ativos else "") + " ORDER BY categoria,nome"
    c.execute(sql); rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]
