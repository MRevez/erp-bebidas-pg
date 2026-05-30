"""
ERP Bebidas - Módulo de Vendas (PostgreSQL)
"""
from core.database import get_connection, release_connection
from modules.clientes import verificar_bloqueio
import datetime


def _q(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchall()

def _q1(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchone()


def _gerar_numero(conn):
    ano = datetime.datetime.now().year
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as n FROM encomendas WHERE data_encomenda >= %s", (f"{ano}-01-01",))
    n = c.fetchone()["n"]
    return f"ENC-{ano}-{n+1:04d}"


def listar_encomendas(armazem_id=None, estado=None, limite=50):
    conn = get_connection()
    where, params = [], []
    if armazem_id: where.append("e.armazem_id=%s"); params.append(armazem_id)
    if estado: where.append("e.estado=%s"); params.append(estado)
    sql = f"""SELECT e.*,c.nome as cliente_nome,c.bloqueado as cliente_bloqueado,
              a.nome as armazem_nome,u.nome as condutor_nome
              FROM encomendas e JOIN clientes c ON e.cliente_id=c.id
              JOIN armazens a ON e.armazem_id=a.id
              LEFT JOIN utilizadores u ON e.condutor_id=u.id
              {'WHERE '+' AND '.join(where) if where else ''}
              ORDER BY e.data_encomenda DESC LIMIT %s"""
    params.append(limite)
    rows = _q(conn, sql, params); release_connection(conn)
    return [dict(r) for r in rows]


def criar_encomenda(cliente_id, armazem_id, linhas, utilizador_id, condutor_id=None, obs=None):
    vf = verificar_bloqueio(cliente_id)
    if not vf["pode_encomendar"]:
        return {"ok": False, "bloqueado": True, "motivo": vf["motivo"],
                "erro": f"Encomenda bloqueada: {vf['motivo']}"}
    conn = get_connection()
    try:
        numero = _gerar_numero(conn)
        total  = sum(l["quantidade"] * l["preco_unitario"] for l in linhas)
        c = conn.cursor()
        c.execute("""INSERT INTO encomendas (numero,cliente_id,armazem_id,total,observacoes,condutor_id)
                     VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (numero,cliente_id,armazem_id,total,obs,condutor_id))
        enc_id = c.fetchone()["id"]
        for l in linhas:
            c.execute("""INSERT INTO encomenda_linhas
                         (encomenda_id,produto_id,quantidade,preco_unitario,subtotal)
                         VALUES (%s,%s,%s,%s,%s)""",
                      (enc_id,l["produto_id"],l["quantidade"],l["preco_unitario"],
                       l["quantidade"]*l["preco_unitario"]))
        conn.commit(); release_connection(conn)
        return {"ok": True, "encomenda_id": enc_id, "numero": numero, "total": total}
    except Exception as e:
        release_connection(conn); return {"ok": False, "erro": str(e)}


def atualizar_estado(encomenda_id, novo_estado, utilizador_id):
    estados_validos = ['pendente','confirmada','expedida','entregue','cancelada','bloqueada']
    if novo_estado not in estados_validos:
        return {"ok": False, "erro": "Estado inválido"}
    conn = get_connection()
    try:
        enc = _q1(conn, "SELECT * FROM encomendas WHERE id=%s", (encomenda_id,))
        if not enc:
            release_connection(conn); return {"ok": False, "erro": "Encomenda não encontrada"}

        if novo_estado == "expedida" and enc["estado"] == "confirmada":
            linhas = _q(conn, "SELECT * FROM encomenda_linhas WHERE encomenda_id=%s", (encomenda_id,))
            c = conn.cursor()
            for l in linhas:
                produto_id = l["produto_id"]
                armazem_id = enc["armazem_id"]
                quantidade = l["quantidade"]

                total_disp = _q1(conn,
                    "SELECT COALESCE(SUM(quantidade),0) as q FROM stock WHERE produto_id=%s AND armazem_id=%s AND quantidade>0",
                    (produto_id, armazem_id))["q"]
                if total_disp < quantidade:
                    conn.rollback(); release_connection(conn)
                    nome_prod = _q1(conn, "SELECT nome FROM produtos WHERE id=%s", (produto_id,))
                    return {"ok": False, "erro": f"Stock insuficiente para '{nome_prod['nome'] if nome_prod else produto_id}'."}

                lotes = _q(conn, """SELECT id,lote,quantidade FROM stock
                                    WHERE produto_id=%s AND armazem_id=%s AND quantidade>0
                                    ORDER BY
                                        CASE WHEN validade IS NULL OR validade='' THEN 1 ELSE 0 END,
                                        validade ASC, atualizado_em ASC""", (produto_id, armazem_id))
                restante = quantidade
                lotes_usados = []
                for lote_row in lotes:
                    if restante <= 0: break
                    tirar = min(restante, lote_row["quantidade"])
                    c.execute("UPDATE stock SET quantidade=quantidade-%s,atualizado_em=NOW() WHERE id=%s",
                              (tirar, lote_row["id"]))
                    lotes_usados.append(f"{lote_row['lote'] or 'S/L'}({tirar})")
                    restante -= tirar

                c.execute("""INSERT INTO movimentos_stock
                             (produto_id,armazem_id,tipo,quantidade,referencia_doc,observacoes,utilizador_id)
                             VALUES (%s,%s,'saida',%s,%s,%s,%s)""",
                          (produto_id, armazem_id, quantidade, enc["numero"],
                           f"Expedição | Lotes: {', '.join(lotes_usados)}", utilizador_id))

        c = conn.cursor()
        c.execute("UPDATE encomendas SET estado=%s WHERE id=%s", (novo_estado, encomenda_id))
        conn.commit(); release_connection(conn); return {"ok": True}
    except Exception as e:
        conn.rollback(); release_connection(conn); return {"ok": False, "erro": str(e)}


def registar_pagamento_encomenda(encomenda_id, utilizador_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE encomendas SET paga=1,data_pagamento=NOW() WHERE id=%s", (encomenda_id,))
        conn.commit(); release_connection(conn); return {"ok": True}
    except Exception as e:
        release_connection(conn); return {"ok": False, "erro": str(e)}


def estatisticas_vendas(armazem_id=None):
    conn = get_connection()
    c = conn.cursor()
    p = [armazem_id] if armazem_id else []
    f = "WHERE e.armazem_id=%s" if armazem_id else ""
    c.execute(f"SELECT COUNT(*) as n,COALESCE(SUM(total),0) as v FROM encomendas e {f}", p)
    r = c.fetchone()
    c.execute(f"SELECT COUNT(*) as n FROM encomendas e {f} {'AND' if f else 'WHERE'} estado='pendente'", p)
    pend = c.fetchone()["n"]
    c.execute(f"SELECT COUNT(*) as n FROM encomendas e {f} {'AND' if f else 'WHERE'} paga=0 AND estado NOT IN ('cancelada','bloqueada')", p)
    ppag = c.fetchone()["n"]
    release_connection(conn)
    return {"total_encomendas": r["n"], "total_valor": round(r["v"],2),
            "pendentes": pend, "por_pagar": ppag}
