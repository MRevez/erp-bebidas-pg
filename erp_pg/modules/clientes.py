"""
ERP Bebidas - Módulo de Clientes (PostgreSQL)
"""
from core.database import get_connection

PENALIZACAO_INCUMPRIMENTO = 20
BONUS_PAGAMENTO_PONTUAL   = 5
LIMIAR_BLOQUEIO           = 2


def _q(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchall()

def _q1(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchone()


def listar_clientes(incluir_bloqueados=True):
    conn = get_connection()
    sql = "SELECT * FROM clientes" + ("" if incluir_bloqueados else " WHERE bloqueado=0") + " ORDER BY nome"
    rows = _q(conn, sql); conn.close()
    return [dict(r) for r in rows]


def obter_cliente(cliente_id):
    conn = get_connection()
    row = _q1(conn, "SELECT * FROM clientes WHERE id=%s", (cliente_id,)); conn.close()
    return dict(row) if row else None


def historico_cliente(cliente_id):
    conn = get_connection()
    rows = _q(conn, """SELECT ca.*,u.nome as utilizador_nome
                       FROM cliente_avaliacoes ca
                       LEFT JOIN utilizadores u ON ca.utilizador_id=u.id
                       WHERE ca.cliente_id=%s ORDER BY ca.data DESC""", (cliente_id,))
    conn.close(); return [dict(r) for r in rows]


def criar_cliente(dados):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO clientes (nome,nif,telefone,morada,email,limite_credito)
                     VALUES (%(nome)s,%(nif)s,%(telefone)s,%(morada)s,%(email)s,%(limite_credito)s)
                     RETURNING id""", dados)
        cid = c.fetchone()["id"]; conn.commit(); conn.close()
        return {"ok": True, "id": cid}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def atualizar_cliente(cliente_id, dados):
    conn = get_connection()
    try:
        dados["id"] = cliente_id
        c = conn.cursor()
        c.execute("""UPDATE clientes SET nome=%(nome)s,nif=%(nif)s,telefone=%(telefone)s,
                     morada=%(morada)s,email=%(email)s,limite_credito=%(limite_credito)s,
                     atualizado_em=NOW() WHERE id=%(id)s""", dados)
        conn.commit(); conn.close(); return {"ok": True}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def _registar_avaliacao(conn, cliente_id, tipo, descricao, valor, score_antes, score_depois, utilizador_id):
    c = conn.cursor()
    c.execute("""INSERT INTO cliente_avaliacoes
                 (cliente_id,tipo,descricao,valor,score_antes,score_depois,utilizador_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)""",
              (cliente_id, tipo, descricao, valor, score_antes, score_depois, utilizador_id))


def registar_pagamento(cliente_id, valor, utilizador_id, pontual=True):
    conn = get_connection()
    try:
        cl = _q1(conn, "SELECT * FROM clientes WHERE id=%s", (cliente_id,))
        if not cl: return {"ok": False, "erro": "Cliente não encontrado"}
        score_antes = cl["score"]
        novo_score = min(100, score_antes + BONUS_PAGAMENTO_PONTUAL) if pontual else score_antes
        tipo = "pagamento" if pontual else "atraso"
        desc = f"Pagamento {'pontual' if pontual else 'com atraso'} de €{valor:.2f}"
        c = conn.cursor()
        c.execute("UPDATE clientes SET score=%s,atualizado_em=NOW() WHERE id=%s", (novo_score, cliente_id))
        _registar_avaliacao(conn, cliente_id, tipo, desc, valor, score_antes, novo_score, utilizador_id)
        conn.commit(); conn.close()
        return {"ok": True, "score_antes": score_antes, "score_depois": novo_score}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def registar_incumprimento(cliente_id, descricao, utilizador_id):
    conn = get_connection()
    try:
        cl = _q1(conn, "SELECT * FROM clientes WHERE id=%s", (cliente_id,))
        if not cl: return {"ok": False, "erro": "Cliente não encontrado"}
        score_antes = cl["score"]
        novos_inc = cl["incumprimentos"] + 1
        novo_score = max(0, score_antes - PENALIZACAO_INCUMPRIMENTO)
        bloqueado = novos_inc >= LIMIAR_BLOQUEIO
        motivo = f"{novos_inc} incumprimentos de pagamento" if bloqueado else cl["motivo_bloqueio"]
        c = conn.cursor()
        c.execute("""UPDATE clientes SET score=%s,incumprimentos=%s,bloqueado=%s,
                     motivo_bloqueio=%s,atualizado_em=NOW() WHERE id=%s""",
                  (novo_score, novos_inc, 1 if bloqueado else cl["bloqueado"], motivo, cliente_id))
        _registar_avaliacao(conn, cliente_id, "incumprimento",
                            f"Incumprimento #{novos_inc}: {descricao}",
                            None, score_antes, novo_score, utilizador_id)
        conn.commit(); conn.close()
        return {"ok": True, "bloqueado": bloqueado, "incumprimentos": novos_inc,
                "score_antes": score_antes, "score_depois": novo_score,
                "mensagem": "⚠️ Cliente bloqueado automaticamente após 2 incumprimentos." if bloqueado else "Incumprimento registado."}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def desbloquear_cliente(cliente_id, motivo, utilizador_id):
    conn = get_connection()
    try:
        cl = _q1(conn, "SELECT * FROM clientes WHERE id=%s", (cliente_id,))
        if not cl: return {"ok": False, "erro": "Cliente não encontrado"}
        score_antes = cl["score"]
        novo_score = max(score_antes, 50)
        c = conn.cursor()
        c.execute("UPDATE clientes SET bloqueado=0,motivo_bloqueio=NULL,score=%s,atualizado_em=NOW() WHERE id=%s",
                  (novo_score, cliente_id))
        _registar_avaliacao(conn, cliente_id, "desbloqueio", f"Desbloqueio manual: {motivo}",
                            None, score_antes, novo_score, utilizador_id)
        conn.commit(); conn.close()
        return {"ok": True, "score_depois": novo_score}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def adicionar_nota(cliente_id, nota, utilizador_id):
    conn = get_connection()
    try:
        cl = _q1(conn, "SELECT score FROM clientes WHERE id=%s", (cliente_id,))
        _registar_avaliacao(conn, cliente_id, "nota", nota, None, cl["score"], cl["score"], utilizador_id)
        conn.commit(); conn.close(); return {"ok": True}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def verificar_bloqueio(cliente_id):
    cl = obter_cliente(cliente_id)
    if not cl: return {"pode_encomendar": False, "motivo": "Cliente não encontrado"}
    if cl["bloqueado"]:
        return {"pode_encomendar": False, "motivo": cl["motivo_bloqueio"] or "Cliente bloqueado",
                "score": cl["score"], "incumprimentos": cl["incumprimentos"]}
    return {"pode_encomendar": True, "score": cl["score"]}


def estatisticas_clientes():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as t, SUM(CASE WHEN bloqueado=1 THEN 1 ELSE 0 END) as b, AVG(score) as s FROM clientes")
    r = c.fetchone(); conn.close()
    return {"total": r["t"] or 0, "ativos": (r["t"] or 0)-(r["b"] or 0),
            "bloqueados": r["b"] or 0, "score_medio": round(r["s"] or 0, 1)}


def pesquisar_clientes(termo):
    conn = get_connection()
    rows = _q(conn, "SELECT * FROM clientes WHERE nome ILIKE %s OR nif LIKE %s ORDER BY nome",
              (f"%{termo}%", f"%{termo}%"))
    conn.close(); return [dict(r) for r in rows]
