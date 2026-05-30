"""
ERP Bebidas - Módulo de Stock (PostgreSQL)
"""
from core.database import get_connection


def _q(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchall()

def _q1(conn, sql, params=None):
    c = conn.cursor(); c.execute(sql, params or ()); return c.fetchone()


def stock_armazem(armazem_id=None):
    conn = get_connection()
    if armazem_id:
        rows = _q(conn, """SELECT s.*,p.nome,p.referencia,p.categoria,p.unidade,
                           p.stock_minimo,a.nome as armazem_nome
                           FROM stock s JOIN produtos p ON s.produto_id=p.id
                           JOIN armazens a ON s.armazem_id=a.id
                           WHERE s.armazem_id=%s ORDER BY p.categoria,p.nome""", (armazem_id,))
    else:
        rows = _q(conn, """SELECT s.*,p.nome,p.referencia,p.categoria,p.unidade,
                           p.stock_minimo,a.nome as armazem_nome
                           FROM stock s JOIN produtos p ON s.produto_id=p.id
                           JOIN armazens a ON s.armazem_id=a.id
                           ORDER BY a.nome,p.categoria,p.nome""")
    conn.close(); return [dict(r) for r in rows]


def stock_consolidado():
    conn = get_connection()
    rows = _q(conn, """SELECT p.id,p.referencia,p.nome,p.categoria,p.unidade,
                       p.stock_minimo,COALESCE(SUM(s.quantidade),0) as total
                       FROM produtos p LEFT JOIN stock s ON p.id=s.produto_id
                       WHERE p.ativo=1 GROUP BY p.id ORDER BY p.categoria,p.nome""")
    conn.close(); return [dict(r) for r in rows]


def alertas_stock_minimo():
    conn = get_connection()
    rows = _q(conn, """SELECT p.nome,p.referencia,p.stock_minimo,a.nome as armazem,
                       SUM(s.quantidade) as quantidade, s.armazem_id
                       FROM stock s JOIN produtos p ON s.produto_id=p.id
                       JOIN armazens a ON s.armazem_id=a.id
                       WHERE p.ativo=1
                       GROUP BY p.id,p.nome,p.referencia,p.stock_minimo,s.armazem_id,a.nome
                       HAVING SUM(s.quantidade) <= p.stock_minimo
                       ORDER BY (SUM(s.quantidade)-p.stock_minimo),p.nome""")
    conn.close(); return [dict(r) for r in rows]


def alertas_validade(dias=60):
    conn = get_connection()
    rows = _q(conn, """SELECT s.*,p.nome,p.referencia,p.unidade,a.nome as armazem_nome,
                       (DATE(s.validade)-CURRENT_DATE) as dias_restantes
                       FROM stock s JOIN produtos p ON s.produto_id=p.id
                       JOIN armazens a ON s.armazem_id=a.id
                       WHERE s.validade IS NOT NULL AND s.validade!=''
                         AND s.quantidade>0
                         AND (DATE(s.validade)-CURRENT_DATE)<=%s
                       ORDER BY s.validade ASC""", (dias,))
    conn.close(); return [dict(r) for r in rows]


def registar_entrada(produto_id, armazem_id, quantidade, lote, validade, utilizador_id, ref_doc=None, obs=None):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO stock (produto_id,armazem_id,quantidade,lote,validade)
                     VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT(produto_id,armazem_id,lote)
                     DO UPDATE SET quantidade=stock.quantidade+%s,atualizado_em=NOW()""",
                  (produto_id,armazem_id,quantidade,lote,validade or None,quantidade))
        obs_final = f"Lote: {lote or 'S/L'}" + (f" | {obs}" if obs else "")
        c.execute("""INSERT INTO movimentos_stock
                     (produto_id,armazem_id,tipo,quantidade,referencia_doc,observacoes,utilizador_id)
                     VALUES (%s,%s,'entrada',%s,%s,%s,%s)""",
                  (produto_id,armazem_id,quantidade,ref_doc,obs_final,utilizador_id))
        conn.commit(); conn.close(); return {"ok": True}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def registar_saida(produto_id, armazem_id, quantidade, utilizador_id, ref_doc=None, obs=None):
    """Saída com FIFO — sai primeiro o lote com validade mais próxima."""
    conn = get_connection()
    try:
        total_disp = _q1(conn,
            "SELECT COALESCE(SUM(quantidade),0) as q FROM stock WHERE produto_id=%s AND armazem_id=%s AND quantidade>0",
            (produto_id, armazem_id))["q"]
        if total_disp < quantidade:
            conn.close(); return {"ok": False, "erro": f"Stock insuficiente. Disponível: {total_disp}"}

        lotes = _q(conn, """SELECT id,lote,quantidade FROM stock
                            WHERE produto_id=%s AND armazem_id=%s AND quantidade>0
                            ORDER BY
                                CASE WHEN validade IS NULL OR validade='' THEN 1 ELSE 0 END,
                                validade ASC, atualizado_em ASC""", (produto_id, armazem_id))
        restante = quantidade
        lotes_usados = []
        c = conn.cursor()
        for lote_row in lotes:
            if restante <= 0: break
            tirar = min(restante, lote_row["quantidade"])
            c.execute("UPDATE stock SET quantidade=quantidade-%s,atualizado_em=NOW() WHERE id=%s",
                      (tirar, lote_row["id"]))
            lotes_usados.append(f"{lote_row['lote'] or 'S/L'}({tirar})")
            restante -= tirar

        obs_final = f"{obs or ''} | Lotes: {', '.join(lotes_usados)}".strip(" |")
        c.execute("""INSERT INTO movimentos_stock
                     (produto_id,armazem_id,tipo,quantidade,referencia_doc,observacoes,utilizador_id)
                     VALUES (%s,%s,'saida',%s,%s,%s,%s)""",
                  (produto_id,armazem_id,quantidade,ref_doc,obs_final,utilizador_id))
        conn.commit(); conn.close()
        return {"ok": True, "stock_restante": total_disp-quantidade, "lotes": ", ".join(lotes_usados)}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def transferir_stock(produto_id, armazem_origem, armazem_destino, quantidade, utilizador_id, obs=None):
    conn = get_connection()
    try:
        atual = _q1(conn,
            "SELECT COALESCE(SUM(quantidade),0) as q FROM stock WHERE produto_id=%s AND armazem_id=%s",
            (produto_id, armazem_origem))["q"]
        if atual < quantidade:
            conn.close(); return {"ok": False, "erro": f"Stock insuficiente. Disponível: {atual}"}
        lote_row = _q1(conn,
            "SELECT lote,validade FROM stock WHERE produto_id=%s AND armazem_id=%s AND quantidade>0 LIMIT 1",
            (produto_id, armazem_origem))
        lote = lote_row["lote"] if lote_row else None
        validade = lote_row["validade"] if lote_row else None
        c = conn.cursor()
        c.execute("UPDATE stock SET quantidade=quantidade-%s,atualizado_em=NOW() WHERE produto_id=%s AND armazem_id=%s",
                  (quantidade,produto_id,armazem_origem))
        c.execute("""INSERT INTO stock (produto_id,armazem_id,quantidade,lote,validade)
                     VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT(produto_id,armazem_id,lote)
                     DO UPDATE SET quantidade=stock.quantidade+%s,atualizado_em=NOW()""",
                  (produto_id,armazem_destino,quantidade,lote,validade,quantidade))
        c.execute("""INSERT INTO movimentos_stock
                     (produto_id,armazem_id,tipo,quantidade,armazem_dest_id,observacoes,utilizador_id)
                     VALUES (%s,%s,'transferencia',%s,%s,%s,%s)""",
                  (produto_id,armazem_origem,quantidade,armazem_destino,obs,utilizador_id))
        conn.commit(); conn.close(); return {"ok": True}
    except Exception as e:
        conn.close(); return {"ok": False, "erro": str(e)}


def historico_movimentos(armazem_id=None, produto_id=None, limite=60):
    conn = get_connection()
    where, params = [], []
    if armazem_id: where.append("m.armazem_id=%s"); params.append(armazem_id)
    if produto_id: where.append("m.produto_id=%s"); params.append(produto_id)
    sql = f"""SELECT m.*,p.nome as produto_nome,p.referencia,
              a.nome as armazem_nome,u.nome as utilizador_nome,
              ad.nome as armazem_dest_nome
              FROM movimentos_stock m
              JOIN produtos p ON m.produto_id=p.id JOIN armazens a ON m.armazem_id=a.id
              LEFT JOIN armazens ad ON m.armazem_dest_id=ad.id
              LEFT JOIN utilizadores u ON m.utilizador_id=u.id
              {'WHERE '+' AND '.join(where) if where else ''}
              ORDER BY m.data DESC LIMIT %s"""
    params.append(limite)
    rows = _q(conn, sql, params); conn.close()
    return [dict(r) for r in rows]
