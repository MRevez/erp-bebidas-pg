"""
ERP Bebidas - Interface principal (Streamlit)
v1.4 - Correções: volume vendas formatado, dashboard igual para todos, encomendas visíveis,
       editar/apagar referência produto, exportar Excel, confirmação score manual, hora PT
"""

import streamlit as st
import pandas as pd
import io
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from core.database import init_database, get_connection
from core.auth import login, tem_permissao, listar_utilizadores, listar_armazens, listar_produtos, criar_utilizador
from modules.clientes import (
    listar_clientes, obter_cliente, criar_cliente, atualizar_cliente,
    registar_incumprimento, desbloquear_cliente, registar_pagamento,
    adicionar_nota, historico_cliente, estatisticas_clientes, verificar_bloqueio
)
from modules.stock import (
    stock_armazem, stock_consolidado, alertas_stock_minimo, alertas_validade,
    registar_entrada, transferir_stock, historico_movimentos
)
from modules.vendas import (
    listar_encomendas, criar_encomenda, atualizar_estado,
    registar_pagamento_encomenda, estatisticas_vendas
)

# ── Configuração ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="ERP Bebidas", page_icon="🍺", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2%sfamily=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    h1, h2, h3 { font-family: 'Syne', sans-serif !important; }
    [data-testid="stSidebar"] {
        background: linear-gradient(160deg, #0f1923 0%, #1a2a3a 100%);
        border-right: 1px solid #2a3a4a;
    }
    [data-testid="stSidebar"] * { color: #e8f0f8 !important; }
    [data-testid="stSidebar"] p { color: #8aaccc !important; }
    .metric-card { background: linear-gradient(135deg,#1a2a3a,#243040); border:1px solid #2e4060;
        border-radius:12px; padding:1.2rem 1.5rem; text-align:center; }
    .metric-card .value { font-family:'Syne',sans-serif; font-size:1.6rem; font-weight:800;
        color:#4db8ff; word-break:break-all; line-height:1.2; }
    .metric-card .label { font-size:0.75rem; color:#8aaccc; text-transform:uppercase;
        letter-spacing:0.08em; margin-top:0.3rem; }
    .badge-ok    { background:#1a4a2a; color:#4ade80; padding:2px 10px; border-radius:20px; font-size:0.78rem; font-weight:600; }
    .badge-block { background:#4a1a1a; color:#f87171; padding:2px 10px; border-radius:20px; font-size:0.78rem; font-weight:600; }
    .badge-warn  { background:#4a3a1a; color:#fbbf24; padding:2px 10px; border-radius:20px; font-size:0.78rem; font-weight:600; }
    .alerta-box  { background:#4a1a1a; border-left:4px solid #ef4444; padding:0.8rem 1rem; border-radius:6px; margin-bottom:0.5rem; }
    .info-box    { background:#1a2a4a; border-left:4px solid #3b82f6; padding:0.8rem 1rem; border-radius:6px; margin-bottom:0.5rem; }
    .sucesso-box { background:#1a3a2a; border-left:4px solid #22c55e; padding:0.8rem 1rem; border-radius:6px; margin-bottom:0.5rem; }
    div[data-testid="stForm"] { background:#141e28; border-radius:10px; padding:1rem; }
    .stButton > button { background:linear-gradient(135deg,#1d6fa4,#1a5a8a); color:white; border:none;
        border-radius:8px; font-family:'Syne',sans-serif; font-weight:600; transition:all 0.2s; }
    .stButton > button:hover { background:linear-gradient(135deg,#2589c4,#1d6fa4); transform:translateY(-1px); }
    .score-bar  { height:8px; border-radius:4px; background:#1a2a3a; margin-top:4px; }
    .score-fill { height:100%; border-radius:4px; }
</style>
""", unsafe_allow_html=True)

# ── Inicialização ──────────────────────────────────────────────────────────────
init_database()
if "utilizador" not in st.session_state:
    st.session_state.utilizador = None


# ── Helpers ────────────────────────────────────────────────────────────────────
def hora_pt():
    """Hora atual em Portugal (UTC+1 inverno / UTC+2 verão)."""
    return datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%d %H:%M")

def converter_hora_pt(data_str):
    """Converte timestamp UTC da BD para hora portuguesa (UTC+1)."""
    if not data_str:
        return ""
    try:
        s = str(data_str)[:19]
        dt_utc = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_pt  = dt_utc + timedelta(hours=1)
        return dt_pt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(data_str)[:16]

def formatar_euro(valor):
    """Formata valor em euros de forma compacta para caber nos cards."""
    if valor >= 1_000_000:
        return f"€{valor/1_000_000:.1f}M"
    if valor >= 1_000:
        return f"€{valor/1_000:.1f}k"
    return f"€{valor:.0f}"

def notificar(ok, msg_ok, msg_erro=None):
    if ok:
        st.success(f"✅ {msg_ok}")
    else:
        st.error(f"❌ {msg_erro or 'Ocorreu um erro. Tente novamente.'}")

def _badge(cl):
    if cl["bloqueado"]:   return "<span class='badge-block'>🔒 Bloqueado</span>"
    if cl["score"] < 60:  return "<span class='badge-warn'>⚠️ Risco</span>"
    return "<span class='badge-ok'>✅ Ativo</span>"

def _barra(score):
    cor = "#4ade80" if score >= 70 else "#fbbf24" if score >= 40 else "#f87171"
    return f"<div class='score-bar'><div class='score-fill' style='width:{score}%;background:{cor}'></div></div>"

def _stock_disponivel(produto_id, armazem_id):
    dados = stock_armazem(armazem_id)
    return sum(r["quantidade"] for r in dados if r["produto_id"] == produto_id)

def _para_excel(df, nome_folha="Dados"):
    """Converte DataFrame para bytes Excel."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=nome_folha)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
def pagina_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div style='text-align:center;margin-bottom:2rem;'>
                <span style='font-family:Syne;font-size:2.8rem;font-weight:800;color:#4db8ff;'>🍺 ERP</span>
                <span style='font-family:Syne;font-size:2.8rem;font-weight:800;color:#e8f0f8;'> Bebidas</span>
                <p style='color:#8aaccc;margin-top:0.3rem;font-size:0.9rem;'>Sistema de Gestão de Armazéns</p>
            </div>""", unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("👤 Utilizador", placeholder="username")
            password = st.text_input("🔒 Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Entrar →", use_container_width=True)
        if submitted:
            res = login(username, password)
            if res["ok"]:
                st.session_state.utilizador = res["utilizador"]
                st.rerun()
            else:
                st.error("❌ Credenciais inválidas. Verifique e tente novamente.")
        st.markdown("""
            <div style='text-align:center;margin-top:2rem;color:#4a6a8a;font-size:0.78rem;'>
                Demo: <code>admin/admin123</code> · <code>carlos/enc123</code> · <code>joao/mot123</code>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def sidebar():
    u = st.session_state.utilizador
    st.sidebar.markdown(f"""
        <div style='padding:1rem 0 1.5rem;'>
            <div style='font-family:Syne;font-size:1.4rem;font-weight:800;'>🍺 ERP Bebidas</div>
            <div style='font-size:0.78rem;color:#4a7aaa;margin-top:0.2rem;'>v1.6 · Sistema modular</div>
            <hr style='border-color:#2a3a4a;margin:1rem 0;'/>
            <div style='font-size:0.85rem;'>👤 <b>{u['nome']}</b></div>
            <div style='font-size:0.75rem;color:#4a7aaa;'>{u['perfil'].capitalize()} · {u.get('armazem_nome') or 'Todos os armazéns'}</div>
        </div>""", unsafe_allow_html=True)
    menus = ["🏠 Dashboard", "📦 Stock", "👥 Clientes", "🛒 Encomendas"]
    if u["perfil"] in ("admin","encarregado"): menus.append("🍺 Produtos")
    if u["perfil"] in ("admin","encarregado"): menus.append("📊 Relatórios")
    if u["perfil"] == "admin":                 menus.append("⚙️ Administração")
    escolha = st.sidebar.radio("Navegação", menus, label_visibility="collapsed")
    st.sidebar.markdown("<hr style='border-color:#2a3a4a;'/>", unsafe_allow_html=True)
    if st.sidebar.button("🚪 Sair", use_container_width=True):
        st.session_state.utilizador = None
        st.rerun()
    return escolha


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — igual para todos os perfis, filtrado pelo armazém do utilizador
# ══════════════════════════════════════════════════════════════════════════════
def pagina_dashboard():
    u = st.session_state.utilizador
    st.markdown("## 🏠 Dashboard")
    st.markdown(f"Bem-vindo, **{u['nome']}**!")

    # Admin vê tudo; encarregado e condutor veem só o seu armazém
    armazem_id = None if u["perfil"] == "admin" else u["armazem_id"]

    stats_cl = estatisticas_clientes()
    stats_v  = estatisticas_vendas(armazem_id)
    alertas  = alertas_stock_minimo()
    venc     = alertas_validade(60)

    # Filtrar alertas pelo armazém do utilizador (se não for admin)
    if armazem_id:
        alertas = [a for a in alertas if a["armazem_id"] == armazem_id]
        venc    = [v for v in venc    if v["armazem_id"] == armazem_id]

    c1,c2,c3,c4,c5 = st.columns(5)
    for col, valor, label in [
        (c1, stats_cl["total"],           "Clientes"),
        (c2, stats_cl["bloqueados"],      "Bloqueados"),
        (c3, stats_v["total_encomendas"], "Encomendas"),
        (c4, stats_v["pendentes"],        "Pendentes"),
        (c5, formatar_euro(stats_v["total_valor"]), "Volume Vendas"),
    ]:
        col.markdown(
            f"<div class='metric-card'><div class='value'>{valor}</div>"
            f"<div class='label'>{label}</div></div>",
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### ⚠️ Alertas de Stock Mínimo")
        if alertas:
            for a in alertas[:6]:
                st.markdown(f"<div class='alerta-box'><b>{a['nome']}</b> — {a['armazem']}<br>"
                            f"<span style='color:#fca5a5'>Stock: {a['quantidade']} / Mínimo: {a['stock_minimo']}</span></div>",
                            unsafe_allow_html=True)
        else:
            st.markdown("<div class='info-box'>✅ Sem alertas de stock mínimo.</div>", unsafe_allow_html=True)
    with col_b:
        st.markdown("### 📅 Validades a Expirar (60 dias)")
        if venc:
            for v in venc[:6]:
                dias = v.get("dias_restantes")
                if dias is None:
                    dias_str = "data inválida"
                elif int(dias) < 0:
                    dias_str = f"⚠️ EXPIRADO há {abs(int(dias))} dias"
                else:
                    dias_str = f"{int(dias)} dias"
                st.markdown(
                    f"<div class='alerta-box'><b>{v['nome']}</b> — {v['armazem_nome']}<br>"
                    f"<span style='color:#fca5a5'>Validade: {v['validade']} ({dias_str}) · Qty: {v['quantidade']}</span></div>",
                    unsafe_allow_html=True)
        else:
            st.markdown("<div class='info-box'>✅ Sem produtos a expirar nos próximos 60 dias.</div>", unsafe_allow_html=True)

    # Últimas encomendas — visíveis para TODOS os perfis
    st.markdown("### 🛒 Últimas Encomendas")
    encs = listar_encomendas(armazem_id, limite=8)
    if encs:
        df = pd.DataFrame(encs)[["numero","cliente_nome","armazem_nome","estado","total","paga","data_encomenda"]]
        df.columns = ["Nº","Cliente","Armazém","Estado","Total (€)","Paga","Data"]
        df["Total (€)"] = df["Total (€)"].apply(lambda x: f"€{x:.2f}")
        df["Paga"] = df["Paga"].apply(lambda x: "✅" if x else "❌")
        df["Data"] = df["Data"].apply(lambda x: str(x)[:10])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Sem encomendas registadas.")


# ══════════════════════════════════════════════════════════════════════════════
# STOCK
# ══════════════════════════════════════════════════════════════════════════════
def pagina_stock():
    u = st.session_state.utilizador
    st.markdown("## 📦 Gestão de Stock")
    armazens = listar_armazens()
    tab1,tab2,tab3,tab4 = st.tabs(["📋 Stock atual","⬆️ Entrada","↔️ Transferência","📜 Histórico"])

    with tab1:
        c1, c2 = st.columns([2,2])
        with c1:
            sel = st.selectbox("Armazém", ["Todos os armazéns"] + [a["nome"] for a in armazens])
        with c2:
            pesquisa_stock = st.text_input("🔍 Pesquisar produto (nome, referência ou categoria)", "")
        arm_id = None if sel == "Todos os armazéns" else next(a["id"] for a in armazens if a["nome"] == sel)
        dados = stock_armazem(arm_id)
        if pesquisa_stock:
            termo = pesquisa_stock.lower()
            dados = [d for d in dados if
                     termo in d["nome"].lower() or
                     termo in (d["referencia"] or "").lower() or
                     termo in (d["categoria"] or "").lower()]

        if not dados:
            st.info("Sem dados de stock.")
        else:
            from datetime import date
            hoje = date.today()

            def dias_val(v):
                if not v or str(v).strip() == "": return "N/D"
                try:
                    d = date.fromisoformat(str(v)[:10])
                    diff = (d - hoje).days
                    if diff < 0:    return f"EXPIRADO ({abs(diff)}d)"
                    if diff <= 30:  return f"⚠️ {diff}d"
                    return str(v)[:10]
                except Exception:
                    return str(v)[:10]

            df = pd.DataFrame(dados)

            # ── Visão consolidada: total por produto + armazém ──────────────
            consolidado = (
                df.groupby(["produto_id","armazem_id","nome","referencia","categoria","unidade","stock_minimo","armazem_nome"])
                  .agg(total=("quantidade","sum"), n_lotes=("lote","count"))
                  .reset_index()
            )
            consolidado["estado"] = consolidado.apply(
                lambda r: "⚠️ Abaixo mínimo" if r["total"] <= r["stock_minimo"] else "✅ OK", axis=1
            )

            # Agrupar por categoria para melhor leitura
            categorias = sorted(consolidado["categoria"].dropna().unique())
            if not categorias:
                categorias = ["Sem categoria"]

            for cat in categorias:
                st.markdown(f"### {cat}")
                prods_cat = consolidado[consolidado["categoria"] == cat]

                for _, row in prods_cat.iterrows():
                    estado_icon = "⚠️" if "Abaixo" in row["estado"] else "✅"
                    label = (f"{estado_icon} **{row['referencia']}** · {row['nome']} "
                             f"— {row['armazem_nome']} "
                             f"— Total: **{int(row['total'])} {row['unidade']}** "
                             f"(mín: {int(row['stock_minimo'])}) "
                             f"— {int(row['n_lotes'])} lote(s)")

                    with st.expander(label):
                        # Lotes deste produto neste armazém
                        lotes = df[
                            (df["produto_id"] == row["produto_id"]) &
                            (df["armazem_id"] == row["armazem_id"])
                        ].copy()

                        # Ordenar: primeiro com stock, depois vazios; dentro de cada grupo por validade
                        lotes["_com_stock"] = lotes["quantidade"] > 0
                        lotes = lotes.sort_values(["_com_stock","validade"], ascending=[False, True])

                        lotes["Validade"] = lotes["validade"].apply(dias_val)
                        lotes["Estado lote"] = lotes["quantidade"].apply(
                            lambda q: "✅ Com stock" if q > 0 else "⬜ Esgotado"
                        )

                        df_lotes = lotes[["lote","quantidade","Validade","Estado lote"]].copy()
                        df_lotes.columns = ["Lote","Quantidade","Validade","Estado"]
                        st.dataframe(df_lotes, use_container_width=True, hide_index=True)

    with tab2:
        if not tem_permissao(u["perfil"],"stock","entrada"):
            st.warning("⚠️ Sem permissão para registar entradas.")
        else:
            produtos = listar_produtos()

            # Estado da confirmação pendente
            if "entrada_pendente" not in st.session_state:
                st.session_state.entrada_pendente = None

            # Se há uma entrada pendente de confirmação, mostrar resumo
            if st.session_state.entrada_pendente:
                ep = st.session_state.entrada_pendente
                st.markdown("#### ⚠️ Confirmar entrada de mercadoria")
                st.markdown(f"""
                <div class='alerta-box' style='background:#1a3a2a;border-color:#22c55e;'>
                    <b>Por favor confirma os dados antes de registar:</b><br><br>
                    📦 <b>Produto:</b> {ep['prod_sel']}<br>
                    🏭 <b>Armazém:</b> {ep['arm_sel']}<br>
                    🔢 <b>Quantidade:</b> {ep['qty']} unidade(s)<br>
                    🏷️ <b>Lote:</b> {ep['lote']}<br>
                    📅 <b>Validade:</b> {ep['val_str'] or 'Sem data de validade'}<br>
                    📄 <b>Referência doc.:</b> {ep['ref_doc'] or '—'}<br>
                    💬 <b>Observações:</b> {ep['obs'] or '—'}
                </div>
                """, unsafe_allow_html=True)
                col_conf, col_cancel = st.columns(2)
                with col_conf:
                    if st.button("✅ Confirmar e registar", use_container_width=True):
                        res = registar_entrada(ep["prod_id"], ep["arm_id"], ep["qty"],
                                               ep["lote"], ep["val_str"], u["id"],
                                               ep["ref_doc"], ep["obs"])
                        notificar(res["ok"],
                                  f"Entrada de {ep['qty']} unidade(s) de '{ep['prod_sel']}' registada com sucesso no {ep['arm_sel']}."
                                  + (f" Validade: {ep['val_str']}." if ep['val_str'] else " Sem data de validade."),
                                  res.get("erro"))
                        st.session_state.entrada_pendente = None
                        if res["ok"]: st.rerun()
                with col_cancel:
                    if st.button("❌ Cancelar e corrigir", use_container_width=True):
                        st.session_state.entrada_pendente = None
                        st.rerun()

            else:
                with st.form("entrada_stock"):
                    st.markdown("#### Registar entrada de mercadoria")
                    c1,c2 = st.columns(2)
                    with c1:
                        prod_nomes = [f"{p['referencia']} · {p['nome']}" for p in produtos]
                        prod_sel = st.selectbox("Produto", prod_nomes)
                        if u["perfil"] == "admin":
                            arm_sel = st.selectbox("Armazém", [a["nome"] for a in armazens])
                        else:
                            arm_sel = u["armazem_nome"]
                            st.text_input("Armazém", value=arm_sel, disabled=True)
                        qty = st.number_input("Quantidade", min_value=1, value=1)
                    with c2:
                        lote = st.text_input("Lote", value="L001")
                        from datetime import date
                        sem_validade = st.checkbox("Produto sem data de validade")
                        if sem_validade:
                            st.markdown("<div class='alerta-box'>⚠️ Tem a certeza que este produto não tem data de validade impressa na embalagem%s</div>", unsafe_allow_html=True)
                            validade = None
                        else:
                            validade = st.date_input("Data de validade do lote *",
                                                     value=None,
                                                     min_value=date.today(),
                                                     help="Introduz a data de validade impressa na embalagem/lote.")
                        ref_doc = st.text_input("Referência documento (opcional)")
                    obs = st.text_area("Observações", height=60)
                    if st.form_submit_button("🔍 Pré-visualizar entrada", use_container_width=True):
                        if not sem_validade and validade is None:
                            st.error("❌ Introduz a data de validade ou assinala 'Produto sem data de validade'.")
                        else:
                            prod_id = produtos[prod_nomes.index(prod_sel)]["id"]
                            arm_id  = next(a["id"] for a in armazens if a["nome"] == arm_sel)
                            st.session_state.entrada_pendente = {
                                "prod_id":  prod_id,
                                "arm_id":   arm_id,
                                "prod_sel": prod_sel,
                                "arm_sel":  arm_sel,
                                "qty":      qty,
                                "lote":     lote,
                                "val_str":  str(validade) if validade else "",
                                "ref_doc":  ref_doc,
                                "obs":      obs,
                            }
                            st.rerun()

    with tab3:
        if not tem_permissao(u["perfil"],"stock","transferencia"):
            st.warning("⚠️ Sem permissão para transferências.")
        else:
            produtos = listar_produtos()
            with st.form("transf_stock"):
                st.markdown("#### Transferência entre armazéns")
                c1,c2 = st.columns(2)
                with c1:
                    prod_nomes = [f"{p['referencia']} · {p['nome']}" for p in produtos]
                    prod_sel  = st.selectbox("Produto", prod_nomes)
                    arm_orig  = st.selectbox("Armazém origem", [a["nome"] for a in armazens])
                with c2:
                    arm_dest = st.selectbox("Armazém destino", [a["nome"] for a in armazens])
                    qty      = st.number_input("Quantidade", min_value=1, value=1)
                obs = st.text_area("Observações", height=60)
                if st.form_submit_button("↔️ Transferir", use_container_width=True):
                    if arm_orig == arm_dest:
                        st.error("❌ Origem e destino não podem ser iguais.")
                    else:
                        prod_id = produtos[prod_nomes.index(prod_sel)]["id"]
                        orig_id = next(a["id"] for a in armazens if a["nome"] == arm_orig)
                        dest_id = next(a["id"] for a in armazens if a["nome"] == arm_dest)
                        res = transferir_stock(prod_id, orig_id, dest_id, qty, u["id"], obs)
                        notificar(res["ok"],
                                  f"Transferência de {qty} unidade(s) de '{prod_sel}' realizada com sucesso: {arm_orig} → {arm_dest}.",
                                  res.get("erro"))

    with tab4:
        st.markdown("#### Histórico de movimentos")
        c1, c2 = st.columns(2)
        with c1:
            arm_fil = st.selectbox("Filtrar por armazém", ["Todos"] + [a["nome"] for a in armazens], key="hist_arm")
        with c2:
            pesq_hist = st.text_input("🔍 Pesquisar produto", "", key="pesq_hist")
        arm_id_fil = None if arm_fil == "Todos" else next(a["id"] for a in armazens if a["nome"] == arm_fil)
        movs = historico_movimentos(armazem_id=arm_id_fil, limite=60)
        if pesq_hist:
            termo = pesq_hist.lower()
            movs = [m for m in movs if termo in (m["produto_nome"] or "").lower()
                    or termo in (m["referencia"] or "").lower()]
        if movs:
            df = pd.DataFrame(movs)[["data","tipo","produto_nome","quantidade","armazem_nome","armazem_dest_nome","utilizador_nome","observacoes"]]
            df.columns = ["Data","Tipo","Produto","Qty","Armazém","Destino","Utilizador","Obs"]
            df["Data"] = df["Data"].apply(converter_hora_pt)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Anulação de entradas — só para admin/encarregado
            if tem_permissao(u["perfil"], "stock", "entrada"):
                st.markdown("---")
                st.markdown("#### 🔄 Anular entrada incorrecta")
                st.caption("Só é possível anular entradas que ainda não tiveram consumo (saída) associado ao mesmo lote.")

                entradas = [m for m in movs if m["tipo"] == "entrada"]
                if entradas:
                    # Obter IDs já anulados (entradas que já têm um ajuste de anulação)
                    conn_chk = get_connection()
                    ja_anulados = set(
                        row[0] for row in conn_chk.execute("""
                            SELECT CAST(REPLACE(REPLACE(observacoes,'ANULADO:',''),' ','') AS INTEGER)
                            FROM movimentos_stock
                            WHERE tipo='ajuste' AND observacoes LIKE 'ANULADO:%'
                        """).fetchall() if row[0]
                    )
                    conn_chk.close()

                    # Filtrar entradas ainda não anuladas
                    entradas_anulaveis = [m for m in entradas if m["id"] not in ja_anulados]

                    if not entradas_anulaveis:
                        st.info("Todas as entradas visíveis já foram anuladas.")
                    else:
                        ent_labels = [
                            f"{converter_hora_pt(m['data'])} | {m['produto_nome']} | {m['quantidade']} un. | {m['armazem_nome']}"
                            for m in entradas_anulaveis
                        ]
                        sel_ent = st.selectbox("Seleccionar entrada a anular", ent_labels, key="sel_anular")
                        mov_sel = entradas_anulaveis[ent_labels.index(sel_ent)]

                        # Verificar se já houve saída deste produto/armazém após esta entrada
                        conn_chk = get_connection()
                        saidas_posteriores = conn_chk.execute("""
                            SELECT COUNT(*) FROM movimentos_stock
                            WHERE produto_id=%s AND armazem_id=%s AND tipo='saida'
                            AND data > %s
                        """, (mov_sel["produto_id"], mov_sel["armazem_id"], str(mov_sel["data"]))).fetchone()[0]
                        conn_chk.close()

                        if saidas_posteriores > 0:
                            st.markdown("<div class='alerta-box'>⚠️ Não é possível anular esta entrada — já existem saídas posteriores. Faz um ajuste manual de stock em vez disso.</div>",
                                        unsafe_allow_html=True)
                        else:
                            motivo_anul = st.text_input("Motivo da anulação *", key="motivo_anul")
                            confirmar_anul = st.checkbox(
                                f"✅ Confirmo que pretendo anular a entrada de **{mov_sel['quantidade']} unidade(s)** "
                                f"de **{mov_sel['produto_nome']}** em **{mov_sel['armazem_nome']}**.",
                                key="conf_anul"
                            )
                            if st.button("🔄 Anular esta entrada", key="btn_anular"):
                                if not motivo_anul:
                                    st.error("❌ Indica o motivo da anulação.")
                                elif not confirmar_anul:
                                    st.warning("⚠️ Confirma a anulação assinalando a caixa de confirmação.")
                                else:
                                    conn_an = get_connection()
                                    try:
                                        # Extrair lote das observações do movimento de entrada
                                        # Formato guardado: "Lotes: L001 (10)" ou referencia_doc
                                        obs_entrada = mov_sel.get("observacoes") or ""
                                        ref_entrada = mov_sel.get("referencia_doc") or ""
                                        lote_entrada = None

                                        # Extrair lote das observações (formato "Lote: L001")
                                        import re
                                        match = re.search(r'Lote:\s*([^\s|,]+)', obs_entrada)
                                        if match:
                                            lote_entrada = match.group(1)

                                        # Descontar apenas na linha de stock correcta (por lote)
                                        if lote_entrada:
                                            _cur_an = conn_an.cursor()
                                            _cur_an.execute("""
                                                UPDATE stock SET quantidade = quantidade - %s,
                                                atualizado_em = NOW()
                                                WHERE produto_id=%s AND armazem_id=%s AND lote=%s
                                            """, (mov_sel["quantidade"], mov_sel["produto_id"],
                                                  mov_sel["armazem_id"], lote_entrada))
                                        else:
                                            # Sem lote identificável — descontar do lote com mais stock (mais seguro)
                                            lote_row = conn_an.execute("""
                                                SELECT id FROM stock
                                                WHERE produto_id=%s AND armazem_id=%s
                                                ORDER BY quantidade DESC LIMIT 1
                                            """, (mov_sel["produto_id"], mov_sel["armazem_id"])).fetchone()
                                            if lote_row:
                                                _cur_an = conn_an.cursor()
                                                _cur_an.execute("""
                                                    UPDATE stock SET quantidade = quantidade - %s,
                                                    atualizado_em = NOW()
                                                    WHERE id=%s
                                                """, (mov_sel["quantidade"], lote_row["id"]))

                                        # Registar ajuste com ID da entrada original
                                        _cur_an = conn_an.cursor()
                                        _cur_an.execute("""
                                            INSERT INTO movimentos_stock
                                            (produto_id, armazem_id, tipo, quantidade, observacoes, utilizador_id)
                                            VALUES (%s,%s,%s,%s,%s,%s)
                                        """, (mov_sel["produto_id"], mov_sel["armazem_id"], "ajuste",
                                              -mov_sel["quantidade"],
                                              f"ANULADO:{mov_sel['id']} | Lote: {lote_entrada or 'N/D'} | Motivo: {motivo_anul}",
                                              u["id"]))
                                        conn_an.commit()
                                        conn_an.close()
                                        st.success(f"✅ Entrada anulada com sucesso. Stock do lote '{lote_entrada or 'N/D'}' corrigido em -{mov_sel['quantidade']} unidade(s).")
                                        st.rerun()
                                    except Exception as e:
                                        conn_an.rollback()
                                        conn_an.close()
                                        st.error(f"❌ {e}")
                else:
                    st.info("Sem entradas disponíveis para anular.")
        else:
            st.info("Sem movimentos registados.")


# ══════════════════════════════════════════════════════════════════════════════
# CLIENTES
# ══════════════════════════════════════════════════════════════════════════════
def pagina_clientes():
    u = st.session_state.utilizador
    st.markdown("## 👥 Gestão de Clientes")
    tab1,tab2,tab3 = st.tabs(["📋 Lista","➕ Novo cliente","📈 Avaliação"])

    with tab1:
        c1,c2 = st.columns([3,1])
        with c1: pesquisa = st.text_input("🔍 Pesquisar (nome ou NIF)", "")
        with c2: mostrar_bloq = st.checkbox("Mostrar bloqueados", value=True)
        clientes = listar_clientes(mostrar_bloq)
        if pesquisa:
            clientes = [c for c in clientes if pesquisa.lower() in c["nome"].lower()
                        or (c["nif"] and pesquisa in c["nif"])]
        if not clientes:
            st.info("Sem clientes encontrados.")
        for cl in clientes:
            with st.expander(f"{cl['nome']}  |  NIF: {cl['nif'] or 'N/D'}  |  Score: {cl['score']}/100"):
                c1,c2,c3 = st.columns([2,2,1])
                with c1:
                    st.markdown(f"📞 {cl['telefone'] or 'N/D'}")
                    st.markdown(f"📧 {cl['email'] or 'N/D'}")
                    st.markdown(f"📍 {cl['morada'] or 'N/D'}")
                with c2:
                    st.markdown(f"💳 Limite crédito: **€{cl['limite_credito']:,.0f}**")
                    st.markdown(f"⚠️ Incumprimentos: **{cl['incumprimentos']}**")
                    st.markdown(_badge(cl), unsafe_allow_html=True)
                    st.markdown(_barra(cl["score"]), unsafe_allow_html=True)
                    st.caption(f"Score: {cl['score']}/100")
                with c3:
                    if cl["bloqueado"] and tem_permissao(u["perfil"],"clientes","desbloquear"):
                        if st.button("🔓 Desbloquear", key=f"db_{cl['id']}"):
                            st.session_state[f"db_modal_{cl['id']}"] = True
                if st.session_state.get(f"db_modal_{cl['id']}"):
                    motivo = st.text_input("Motivo do desbloqueio", key=f"mot_{cl['id']}")
                    if st.button("✅ Confirmar desbloqueio", key=f"conf_{cl['id']}"):
                        res = desbloquear_cliente(cl["id"], motivo, u["id"])
                        notificar(res["ok"], f"Cliente '{cl['nome']}' desbloqueado com sucesso. Score reposto para {res.get('score_depois','%s')}/100.")
                        if res["ok"]:
                            st.session_state[f"db_modal_{cl['id']}"] = False
                            st.rerun()
                hist = historico_cliente(cl["id"])
                if hist:
                    st.markdown("**Histórico:**")
                    for h in hist[:5]:
                        ic = {"pagamento":"💚","atraso":"🟡","incumprimento":"🔴","desbloqueio":"🔓","nota":"📝"}.get(h["tipo"],"•")
                        data_str = converter_hora_pt(h['data'])
                        st.caption(f"{ic} {data_str} — {h['descricao']} (score: {h['score_antes']}→{h['score_depois']})")

    with tab2:
        if not tem_permissao(u["perfil"],"clientes","criar"):
            st.warning("⚠️ Sem permissão para criar clientes.")
        else:
            with st.form("novo_cliente"):
                st.markdown("#### Novo cliente")
                c1,c2 = st.columns(2)
                with c1:
                    nome   = st.text_input("Nome *")
                    nif    = st.text_input("NIF")
                    tel    = st.text_input("Telefone")
                with c2:
                    email  = st.text_input("Email")
                    morada = st.text_input("Morada")
                    limite = st.number_input("Limite de crédito (€)", min_value=0.0, value=1000.0, step=100.0)
                if st.form_submit_button("✅ Criar cliente", use_container_width=True):
                    if not nome:
                        st.error("❌ O nome é obrigatório.")
                    else:
                        res = criar_cliente({"nome":nome,"nif":nif,"telefone":tel,
                                             "email":email,"morada":morada,"limite_credito":limite})
                        notificar(res["ok"], f"Cliente '{nome}' criado com sucesso!", res.get("erro"))
                        if res["ok"]: st.rerun()

    with tab3:
        st.markdown("#### Registar avaliação / ocorrência")
        clientes_todos = listar_clientes(True)
        cl_nomes = [f"{c['nome']} (NIF: {c['nif'] or 'N/D'})" for c in clientes_todos]
        sel  = st.selectbox("Selecionar cliente", cl_nomes)
        idx  = cl_nomes.index(sel)
        cl_sel = clientes_todos[idx]
        st.markdown(f"**Score atual:** {cl_sel['score']}/100  |  Incumprimentos: {cl_sel['incumprimentos']}")
        st.markdown(_badge(cl_sel), unsafe_allow_html=True)

        if tem_permissao(u["perfil"],"clientes","avaliar"):
            tipo_acao = st.radio("Tipo de ocorrência",
                                 ["💚 Pagamento pontual","🔴 Incumprimento","📝 Nota"]
                                 + (["🎯 Definir score manualmente"] if u["perfil"] == "admin" else []))
            desc  = st.text_area("Descrição / motivo")
            valor = None

            if "Pagamento" in tipo_acao:
                valor = st.number_input("Valor pago (€)", min_value=0.0)

            if "Definir score" in tipo_acao:
                novo_score_manual = st.slider(
                    "Novo score",
                    min_value=0, max_value=100,
                    value=max(cl_sel["score"], 50),
                    help="Define o score após regularização completa da situação."
                )
                # Caixa de confirmação obrigatória antes de aplicar
                confirmar_score = st.checkbox(
                    f"✅ Confirmo que pretendo alterar o score de **{cl_sel['nome']}** "
                    f"de **{cl_sel['score']}** para **{novo_score_manual}** pontos."
                )

            if st.button("Registar", use_container_width=True):
                if "Pagamento" in tipo_acao:
                    res = registar_pagamento(cl_sel["id"], valor, u["id"], pontual=True)
                    notificar(res["ok"],
                              f"Pagamento de €{valor:.2f} registado para '{cl_sel['nome']}'. Score: {res.get('score_antes','%s')} → {res.get('score_depois','%s')}/100.",
                              res.get("erro"))
                elif "Incumprimento" in tipo_acao:
                    res = registar_incumprimento(cl_sel["id"], desc, u["id"])
                    if res["ok"]:
                        if res.get("bloqueado"):
                            st.error(f"🔒 {res['mensagem']}")
                        else:
                            st.success(f"✅ Incumprimento registado para '{cl_sel['nome']}'. Score: {res['score_antes']} → {res['score_depois']}/100.")
                    else:
                        st.error(f"❌ {res.get('erro','Erro')}")
                    st.rerun()
                elif "Nota" in tipo_acao:
                    res = adicionar_nota(cl_sel["id"], desc, u["id"])
                    notificar(res["ok"], f"Nota adicionada ao cliente '{cl_sel['nome']}' com sucesso.", res.get("erro"))
                elif "Definir score" in tipo_acao:
                    if not confirmar_score:
                        st.warning("⚠️ Por favor confirma a alteração assinalando a caixa de confirmação.")
                    else:
                        conn = get_connection()
                        try:
                            score_antes = cl_sel["score"]
                            _cur = conn.cursor()
                            _cur.execute("UPDATE clientes SET score=%s, atualizado_em=NOW() WHERE id=%s",
                                         (novo_score_manual, cl_sel["id"]))
                            _cur = conn.cursor()
                            _cur.execute("""INSERT INTO cliente_avaliacoes
                                            (cliente_id,tipo,descricao,score_antes,score_depois,utilizador_id)
                                            VALUES (%s,'nota',%s,%s,%s,%s)""",
                                         (cl_sel["id"],
                                          f"Score definido manualmente pelo admin: {desc or 'sem motivo'}",
                                          score_antes, novo_score_manual, u["id"]))
                            conn.commit(); conn.close()
                            st.success(f"✅ Score de '{cl_sel['nome']}' atualizado de {score_antes} para {novo_score_manual}/100.")
                            st.rerun()
                        except Exception as e:
                            conn.close(); st.error(f"❌ {e}")
        else:
            st.warning("⚠️ Sem permissão para registar avaliações.")


# ══════════════════════════════════════════════════════════════════════════════
# ENCOMENDAS
# ══════════════════════════════════════════════════════════════════════════════
def pagina_encomendas():
    u = st.session_state.utilizador
    st.markdown("## 🛒 Encomendas")
    tab1,tab2 = st.tabs(["📋 Lista de encomendas","➕ Nova encomenda"])

    with tab1:
        armazens = listar_armazens()
        c1,c2 = st.columns(2)
        with c1: arm_fil    = st.selectbox("Armazém", ["Todos"] + [a["nome"] for a in armazens])
        with c2: estado_fil = st.selectbox("Estado", ["Todos","pendente","confirmada","expedida","entregue","cancelada","bloqueada"])
        arm_id_fil  = None if arm_fil == "Todos" else next(a["id"] for a in armazens if a["nome"] == arm_fil)
        estado_fil2 = None if estado_fil == "Todos" else estado_fil
        encs = listar_encomendas(arm_id_fil, estado_fil2)

        if not encs:
            st.info("Sem encomendas encontradas.")
        for enc in encs:
            ic = {"pendente":"🟡","confirmada":"🔵","expedida":"🚚","entregue":"✅","cancelada":"❌","bloqueada":"🔒"}.get(enc["estado"],"•")
            data_str = str(enc['data_encomenda'])[:10]
            pago_str = "✅ Pago" if enc["paga"] else "❌ Por pagar"
            with st.expander(f"{ic} {enc['numero']} — {enc['cliente_nome']} — €{enc['total']:.2f} — {data_str} — {pago_str}"):
                c1,c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Armazém:** {enc['armazem_nome']}")
                    st.markdown(f"**Estado:** {enc['estado'].capitalize()}")
                    st.markdown(f"**Pagamento:** {pago_str}")
                    if enc.get("condutor_nome"):
                        st.markdown(f"**Condutor:** {enc['condutor_nome']}")
                with c2:
                    if tem_permissao(u["perfil"],"vendas","editar"):
                        proximos = {"pendente":["confirmada","cancelada"],
                                    "confirmada":["expedida","cancelada"],
                                    "expedida":["entregue"]}.get(enc["estado"], [])
                        if proximos:
                            novo_est = st.selectbox("Novo estado", proximos, key=f"est_{enc['id']}")
                            if st.button("Atualizar estado", key=f"upd_{enc['id']}"):
                                res = atualizar_estado(enc["id"], novo_est, u["id"])
                                notificar(res["ok"],
                                          f"Encomenda {enc['numero']} atualizada para '{novo_est}' com sucesso."
                                          + (" O stock foi descontado automaticamente." if novo_est == "expedida" else ""),
                                          res.get("erro"))
                                if res["ok"]: st.rerun()

                    if not enc["paga"] and enc["estado"] == "entregue" and tem_permissao(u["perfil"],"vendas","pagar"):
                        st.markdown("---")
                        st.markdown("**💰 Registar pagamento**")
                        st.caption("Apenas disponível após entrega. Só encarregados e admins podem confirmar.")
                        if st.button("✅ Confirmar pagamento recebido", key=f"pag_{enc['id']}"):
                            res = registar_pagamento_encomenda(enc["id"], u["id"])
                            notificar(res["ok"],
                                      f"Pagamento da encomenda {enc['numero']} registado com sucesso.",
                                      res.get("erro"))
                            if res["ok"]: st.rerun()

    with tab2:
        if not tem_permissao(u["perfil"],"vendas","criar"):
            st.warning("⚠️ Sem permissão para criar encomendas.")
            return

        clientes = listar_clientes(incluir_bloqueados=False)
        armazens = listar_armazens()
        produtos = listar_produtos()

        c1,c2 = st.columns(2)
        with c1:
            cl_nomes    = [c["nome"] for c in clientes]
            cl_sel_nome = st.selectbox("Cliente *", cl_nomes)
            cl_sel      = clientes[cl_nomes.index(cl_sel_nome)]
            vf = verificar_bloqueio(cl_sel["id"])
            if not vf["pode_encomendar"]:
                st.markdown(f"<div class='alerta-box'>🔒 Cliente bloqueado: {vf['motivo']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='info-box'>✅ Cliente disponível · Score: {vf['score']}/100</div>", unsafe_allow_html=True)
        with c2:
            # Encarregado só pode criar encomendas pelo seu armazém
            if u["perfil"] == "admin":
                arm_nomes    = [a["nome"] for a in armazens]
                arm_sel_nome = st.selectbox("Armazém *", arm_nomes)
                arm_sel      = armazens[arm_nomes.index(arm_sel_nome)]
            else:
                arm_sel_nome = u["armazem_nome"]
                st.text_input("Armazém", value=arm_sel_nome, disabled=True)
                arm_sel = next((a for a in armazens if a["nome"] == arm_sel_nome), armazens[0])
            obs = st.text_area("Observações", height=68)

        st.markdown("#### Produtos da encomenda")
        if "linhas_enc" not in st.session_state:
            st.session_state.linhas_enc = []

        # Pesquisa de produto
        pesquisa_prod = st.text_input("🔍 Pesquisar produto (nome, referência ou categoria)", "",
                                       key="pesq_enc")
        todos_produtos = produtos
        if pesquisa_prod:
            termo = pesquisa_prod.lower()
            produtos_filtrados = [p for p in todos_produtos if
                                  termo in p["nome"].lower() or
                                  termo in (p["referencia"] or "").lower() or
                                  termo in (p["categoria"] or "").lower()]
        else:
            produtos_filtrados = todos_produtos

        if not produtos_filtrados:
            st.warning("⚠️ Nenhum produto encontrado para essa pesquisa.")
            prod_nomes = []
        else:
            prod_nomes = [f"{p['referencia']} · {p['nome']}" for p in produtos_filtrados]
        col_p,col_q,col_pr,col_add = st.columns([3,1,1,1])
        with col_p:  prod_sel_nome = st.selectbox("Produto", prod_nomes, label_visibility="collapsed") if prod_nomes else st.selectbox("Produto", ["—"], label_visibility="collapsed")
        with col_q:  qty_add = st.number_input("Qty", min_value=1, value=1, label_visibility="collapsed")
        with col_pr:
            prod_obj = produtos_filtrados[prod_nomes.index(prod_sel_nome)] if prod_nomes and prod_sel_nome != "—" else None
            preco_add = st.number_input("Preço", min_value=0.0,
                                        value=float(prod_obj["preco_venda"]) if prod_obj else 0.0,
                                        label_visibility="collapsed")

        # Mostrar lotes disponíveis ordenados por FIFO
        from datetime import date as _date
        if prod_obj:
            conn_lotes = get_connection()
            lotes_disp = conn_lotes.execute("""
                SELECT lote, quantidade, validade
                FROM stock
                WHERE produto_id=%s AND armazem_id=%s AND quantidade>0
                ORDER BY
                    CASE WHEN validade IS NULL OR validade='' THEN 1 ELSE 0 END,
                    validade ASC
            """, (prod_obj["id"], arm_sel["id"])).fetchall()
            conn_lotes.close()

            if lotes_disp:
                lotes_info = "  |  ".join([
                    f"Lote **{r['lote'] or 'S/L'}**: {r['quantidade']} un."
                    + (f" (val: {r['validade']})" if r['validade'] else "")
                    for r in lotes_disp
                ])
                st.markdown(f"<div class='info-box'>📦 Lotes disponíveis (ordem FIFO): {lotes_info}</div>",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='alerta-box'>⚠️ Sem stock disponível para este produto neste armazém.</div>",
                            unsafe_allow_html=True)

        with col_add:
            if st.button("➕ Adicionar"):
                if not prod_obj:
                    st.error("❌ Selecciona um produto válido.")
                else:
                    disponivel = _stock_disponivel(prod_obj["id"], arm_sel["id"])
                    ja_na_enc  = sum(l["quantidade"] for l in st.session_state.linhas_enc
                                     if l["produto_id"] == prod_obj["id"])
                    if qty_add > (disponivel - ja_na_enc):
                        st.error(f"❌ Stock insuficiente. Disponível em '{arm_sel['nome']}': {disponivel - ja_na_enc} unidade(s).")
                    else:
                        st.session_state.linhas_enc.append({
                            "produto_id":    prod_obj["id"],
                            "produto_nome":  prod_obj["nome"],
                            "quantidade":    qty_add,
                            "preco_unitario":preco_add
                        })

        if st.session_state.linhas_enc:
            df_linhas = pd.DataFrame(st.session_state.linhas_enc)
            df_linhas["subtotal"] = df_linhas["quantidade"] * df_linhas["preco_unitario"]
            st.dataframe(df_linhas[["produto_nome","quantidade","preco_unitario","subtotal"]],
                         use_container_width=True, hide_index=True)
            total = df_linhas["subtotal"].sum()
            st.markdown(f"**Total: €{total:.2f}**")

            col_criar,col_limpar = st.columns(2)
            with col_criar:
                if st.button("✅ Criar encomenda", use_container_width=True):
                    res = criar_encomenda(cl_sel["id"], arm_sel["id"],
                                          st.session_state.linhas_enc, u["id"], obs=obs)
                    if res["ok"]:
                        st.success(f"✅ Encomenda {res['numero']} criada com sucesso! Total: €{res['total']:.2f}")
                        st.session_state.linhas_enc = []
                        st.rerun()
                    elif res.get("bloqueado"):
                        st.error(f"🔒 {res['erro']}")
                    else:
                        st.error(f"❌ {res['erro']}")
            with col_limpar:
                if st.button("🗑️ Limpar", use_container_width=True):
                    st.session_state.linhas_enc = []
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# RELATÓRIOS — exportação Excel
# ══════════════════════════════════════════════════════════════════════════════
def pagina_relatorios():
    u = st.session_state.utilizador
    st.markdown("## 📊 Relatórios")
    tab1, tab2, tab3, tab4 = st.tabs([
        "📦 Stock consolidado",
        "👥 Clientes por score",
        "🛒 Histórico de encomendas",
        "📜 Movimentos de armazém"
    ])

    armazens = listar_armazens()

    with tab1:
        # Filtro por armazém
        c1, c2 = st.columns([2,2])
        with c1:
            arm_rel = st.selectbox("Armazém", ["Todos os armazéns"] + [a["nome"] for a in armazens], key="rel_arm")
        arm_rel_id = None if arm_rel == "Todos os armazéns" else next(a["id"] for a in armazens if a["nome"] == arm_rel)

        conn = get_connection()
        _cr = conn.cursor()
        if arm_rel_id:
            _cr.execute("""
                SELECT p.id, p.referencia, p.nome, p.categoria, p.unidade,
                       p.stock_minimo, COALESCE(SUM(s.quantidade),0) as total
                FROM produtos p
                LEFT JOIN stock s ON p.id=s.produto_id AND s.armazem_id=%s
                WHERE p.ativo=1
                GROUP BY p.id ORDER BY p.categoria, p.nome
            """, (arm_rel_id,))
        else:
            _cr.execute("""
                SELECT p.id, p.referencia, p.nome, p.categoria, p.unidade,
                       p.stock_minimo, COALESCE(SUM(s.quantidade),0) as total
                FROM produtos p
                LEFT JOIN stock s ON p.id=s.produto_id
                WHERE p.ativo=1
                GROUP BY p.id ORDER BY p.categoria, p.nome
            """)
        rows = _cr.fetchall()
        conn.close()

        df = pd.DataFrame([dict(r) for r in rows])
        if not df.empty:
            df["Estado"] = df.apply(lambda r: "⚠️ Abaixo mínimo" if r["total"] <= r["stock_minimo"] else "✅ OK", axis=1)
            df = df[["referencia","nome","categoria","total","unidade","stock_minimo","Estado"]]
            df.columns = ["Ref","Produto","Categoria","Stock Total","Unid","Stock Mín","Estado"]
            st.dataframe(df, use_container_width=True, hide_index=True)
            nome_ficheiro = f"stock_{arm_rel.replace(' ','_') if arm_rel_id else 'todos'}"
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇️ Exportar Excel", _para_excel(df,"Stock"),
                                   f"{nome_ficheiro}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with c2:
                st.download_button("⬇️ Exportar CSV", df.to_csv(index=False),
                                   f"{nome_ficheiro}.csv", "text/csv")

    with tab2:
        clientes = listar_clientes(True)
        df = pd.DataFrame(clientes)[["nome","nif","score","incumprimentos","bloqueado","limite_credito"]]
        df.columns = ["Nome","NIF","Score","Incumprimentos","Bloqueado","Limite €"]
        df["Bloqueado"] = df["Bloqueado"].apply(lambda x: "Sim" if x else "Não")
        df = df.sort_values("Score")
        st.dataframe(df, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ Exportar Excel", _para_excel(df,"Clientes"),
                               "clientes_score.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with c2:
            st.download_button("⬇️ Exportar CSV", df.to_csv(index=False),
                               "clientes_score.csv", "text/csv")

    with tab3:
        st.markdown("#### Histórico de encomendas por período")
        from datetime import date, timedelta
        c1, c2, c3 = st.columns(3)
        with c1:
            dt_ini = st.date_input("Data início", value=date.today() - timedelta(days=30), key="enc_ini")
        with c2:
            dt_fim = st.date_input("Data fim", value=date.today(), key="enc_fim")
        with c3:
            arm_enc = st.selectbox("Armazém", ["Todos"] + [a["nome"] for a in armazens], key="enc_arm")

        arm_enc_id = None if arm_enc == "Todos" else next(a["id"] for a in armazens if a["nome"] == arm_enc)

        conn = get_connection()
        params = [str(dt_ini), str(dt_fim) + " 23:59:59"]
        filtro_arm = ""
        if arm_enc_id:
            filtro_arm = " AND e.armazem_id=%s"
            params.append(arm_enc_id)

        _c = conn.cursor()
        _c.execute(f"""
            SELECT e.numero, c.nome as cliente, a.nome as armazem,
                   e.estado, e.total, e.paga,
                   e.data_encomenda, u.nome as condutor
            FROM encomendas e
            JOIN clientes c ON e.cliente_id=c.id
            JOIN armazens a ON e.armazem_id=a.id
            LEFT JOIN utilizadores u ON e.condutor_id=u.id
            WHERE e.data_encomenda BETWEEN %s AND %s
            {filtro_arm}
            ORDER BY e.data_encomenda DESC
        """, params)
        rows = _c.fetchall()
        conn.close()

        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            df["data_encomenda"] = df["data_encomenda"].apply(converter_hora_pt)
            df["paga"] = df["paga"].apply(lambda x: "✅ Sim" if x else "❌ Não")
            df["total"] = df["total"].apply(lambda x: f"€{x:.2f}")
            df = df[["numero","cliente","armazem","estado","total","paga","data_encomenda","condutor"]]
            df.columns = ["Nº","Cliente","Armazém","Estado","Total","Paga","Data Encomenda","Condutor"]
            st.markdown(f"**{len(df)} encomendas** — Total: **€{sum(float(v[1:]) for v in df['Total']):,.2f}**")
            st.dataframe(df, use_container_width=True, hide_index=True)
            nome_f = f"encomendas_{dt_ini}_{dt_fim}"
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇️ Exportar Excel", _para_excel(df,"Encomendas"),
                                   f"{nome_f}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with c2:
                st.download_button("⬇️ Exportar CSV", df.to_csv(index=False),
                                   f"{nome_f}.csv", "text/csv")
        else:
            st.info("Sem encomendas no período seleccionado.")

    with tab4:
        st.markdown("#### Movimentos de armazém por período")
        from datetime import date, timedelta
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            dt_ini_m = st.date_input("Data início", value=date.today() - timedelta(days=30), key="mov_ini")
        with c2:
            dt_fim_m = st.date_input("Data fim", value=date.today(), key="mov_fim")
        with c3:
            arm_mov = st.selectbox("Armazém", ["Todos"] + [a["nome"] for a in armazens], key="mov_arm")
        with c4:
            tipo_mov = st.selectbox("Tipo", ["Todos","entrada","saida","transferencia","ajuste"], key="mov_tipo")

        arm_mov_id = None if arm_mov == "Todos" else next(a["id"] for a in armazens if a["nome"] == arm_mov)

        conn = get_connection()
        params_m = [str(dt_ini_m), str(dt_fim_m) + " 23:59:59"]
        filtros = ""
        if arm_mov_id:
            filtros += " AND m.armazem_id=%s"
            params_m.append(arm_mov_id)
        if tipo_mov != "Todos":
            filtros += " AND m.tipo=%s"
            params_m.append(tipo_mov)

        _cm = conn.cursor()
        _cm.execute(f"""
            SELECT m.data, m.tipo, p.referencia, p.nome as produto, m.quantidade,
                   a.nome as armazem,
                   CASE
                       WHEN m.tipo='transferencia' THEN ad.nome
                       WHEN m.tipo='saida' AND e.cliente_id IS NOT NULL THEN c.nome
                       ELSE '—'
                   END as destino,
                   u.nome as utilizador, m.observacoes
            FROM movimentos_stock m
            JOIN produtos p ON m.produto_id=p.id
            JOIN armazens a ON m.armazem_id=a.id
            LEFT JOIN armazens ad ON m.armazem_dest_id=ad.id
            LEFT JOIN encomendas e ON m.referencia_doc=e.numero
            LEFT JOIN clientes c ON e.cliente_id=c.id
            LEFT JOIN utilizadores u ON m.utilizador_id=u.id
            WHERE m.data BETWEEN %s AND %s
            {filtros}
            ORDER BY m.data DESC
        """, params_m)
        rows_m = _cm.fetchall()
        conn.close()

        if rows_m:
            df_m = pd.DataFrame([dict(r) for r in rows_m])
            df_m["data"] = df_m["data"].apply(converter_hora_pt)
            df_m.columns = ["Data","Tipo","Ref","Produto","Qty","Armazém","Destino","Utilizador","Obs"]
            st.markdown(f"**{len(df_m)} movimentos** no período")
            st.dataframe(df_m, use_container_width=True, hide_index=True)
            nome_f = f"movimentos_{dt_ini_m}_{dt_fim_m}"
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇️ Exportar Excel", _para_excel(df_m,"Movimentos"),
                                   f"{nome_f}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with c2:
                st.download_button("⬇️ Exportar CSV", df_m.to_csv(index=False),
                                   f"{nome_f}.csv", "text/csv")
        else:
            st.info("Sem movimentos no período seleccionado.")


# ══════════════════════════════════════════════════════════════════════════════
# PRODUTOS — com edição de referência e opção de apagar
# ══════════════════════════════════════════════════════════════════════════════
def pagina_produtos():
    u = st.session_state.utilizador
    st.markdown("## 🍺 Gestão de Produtos")
    tab1, tab2, tab3 = st.tabs(["📋 Lista de produtos","➕ Novo produto","✏️ Editar / Apagar produto"])

    with tab1:
        col1, col2 = st.columns([3,1])
        with col1: pesquisa = st.text_input("🔍 Pesquisar produto","")
        with col2: mostrar_inativos = st.checkbox("Mostrar inativos", value=False)

        conn = get_connection()
        sql = "SELECT * FROM produtos" + ("" if mostrar_inativos else " WHERE ativo=1") + " ORDER BY categoria, nome"
        _cp = conn.cursor()
        _cp.execute(sql)
        produtos = [dict(r) for r in _cp.fetchall()]
        conn.close()

        if pesquisa:
            produtos = [p for p in produtos if pesquisa.lower() in p["nome"].lower()
                        or pesquisa.lower() in (p["referencia"] or "").lower()
                        or pesquisa.lower() in (p["categoria"] or "").lower()]

        if not produtos:
            st.info("Sem produtos encontrados.")
        else:
            categorias = sorted(set(p["categoria"] or "Sem categoria" for p in produtos))
            for cat in categorias:
                st.markdown(f"### {cat}")
                for p in [x for x in produtos if (x["categoria"] or "Sem categoria") == cat]:
                    estado_badge = "✅ Ativo" if p["ativo"] else "❌ Inativo"
                    with st.expander(f"{p['referencia']} · {p['nome']} — €{p['preco_venda']:.2f}/{p['unidade']}  |  {estado_badge}"):
                        c1,c2,c3 = st.columns(3)
                        with c1:
                            st.markdown(f"**Referência:** {p['referencia']}")
                            st.markdown(f"**Categoria:** {p['categoria'] or 'N/D'}")
                            st.markdown(f"**Unidade:** {p['unidade']}")
                        with c2:
                            st.markdown(f"**Preço venda:** €{p['preco_venda']:.2f}")
                            st.markdown(f"**Preço compra:** €{p['preco_compra']:.2f}")
                            margem = p['preco_venda'] - p['preco_compra']
                            pct    = (margem/p['preco_venda']*100) if p['preco_venda'] > 0 else 0
                            st.markdown(f"**Margem:** €{margem:.2f} ({pct:.1f}%)")
                        with c3:
                            st.markdown(f"**Stock mínimo:** {p['stock_minimo']} {p['unidade']}")
                            st.markdown(f"**Estado:** {estado_badge}")
                            if u["perfil"] == "admin":
                                label = "❌ Desativar" if p["ativo"] else "✅ Ativar"
                                if st.button(label, key=f"tog_{p['id']}"):
                                    conn = get_connection()
                                    _cur = conn.cursor()
                                    _cur.execute("UPDATE produtos SET ativo=%s WHERE id=%s",
                                                 (0 if p["ativo"] else 1, p["id"]))
                                    conn.commit(); conn.close()
                                    st.success(f"✅ Produto '{p['nome']}' {'desativado' if p['ativo'] else 'ativado'} com sucesso.")
                                    st.rerun()

    with tab2:
        if u["perfil"] not in ("admin","encarregado"):
            st.warning("⚠️ Sem permissão para criar produtos.")
        else:
            with st.form("novo_produto"):
                st.markdown("#### Novo produto")
                c1,c2 = st.columns(2)
                with c1:
                    ref      = st.text_input("Referência *", placeholder="Ex: CX-SB-33")
                    nome     = st.text_input("Nome *", placeholder="Ex: Super Bock 33cl cx24")
                    categoria = st.selectbox("Categoria",
                                             ["Cerveja","Vinho","Água","Refrigerantes","Sumos","Espirituosas","Sidra","Outro"])
                    unidade  = st.selectbox("Unidade de venda",
                                            ["cx","un","fardo","palete","barril","garrafa","pack"])
                with c2:
                    preco_venda  = st.number_input("Preço de venda (€)", min_value=0.0, value=0.0, step=0.5)
                    preco_compra = st.number_input("Preço de compra (€)", min_value=0.0, value=0.0, step=0.5)
                    stock_min    = st.number_input("Stock mínimo de alerta", min_value=0, value=5)
                if preco_venda > 0:
                    margem = preco_venda - preco_compra
                    pct    = margem/preco_venda*100
                    cor    = "#4ade80" if pct >= 20 else "#fbbf24" if pct >= 10 else "#f87171"
                    st.markdown(f"<div class='info-box'>Margem estimada: <b style='color:{cor}'>€{margem:.2f} ({pct:.1f}%)</b></div>",
                                unsafe_allow_html=True)
                if st.form_submit_button("✅ Criar produto", use_container_width=True):
                    if not ref or not nome:
                        st.error("❌ Referência e nome são obrigatórios.")
                    elif preco_venda <= 0:
                        st.error("❌ O preço de venda tem de ser superior a zero.")
                    else:
                        conn = get_connection()
                        try:
                            _cur = conn.cursor()
                            _cur.execute("""INSERT INTO produtos (referencia,nome,categoria,unidade,
                                            preco_venda,preco_compra,stock_minimo)
                                            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                                         (ref,nome,categoria,unidade,preco_venda,preco_compra,stock_min))
                            conn.commit(); conn.close()
                            st.success(f"✅ Produto '{nome}' (ref: {ref}) criado com sucesso!")
                        except Exception as e:
                            conn.close()
                            st.error("❌ Já existe um produto com essa referência." if "UNIQUE" in str(e) else f"❌ {e}")

    with tab3:
        if u["perfil"] not in ("admin","encarregado"):
            st.warning("⚠️ Sem permissão para editar produtos.")
        else:
            conn = get_connection()
            _cpt = conn.cursor()
            _cpt.execute("SELECT * FROM produtos ORDER BY categoria, nome")
            produtos_todos = [dict(r) for r in _cpt.fetchall()]
            conn.close()

            if not produtos_todos:
                st.info("Sem produtos disponíveis.")
            else:
                prod_nomes = [f"{p['referencia']} · {p['nome']}" for p in produtos_todos]
                sel = st.selectbox("Selecionar produto a editar", prod_nomes)
                p   = produtos_todos[prod_nomes.index(sel)]

                with st.form("editar_produto"):
                    st.markdown(f"#### Editar: {p['nome']}")
                    c1,c2 = st.columns(2)
                    with c1:
                        # Referência agora é editável
                        ref_e      = st.text_input("Referência *", value=p["referencia"])
                        nome_e     = st.text_input("Nome *", value=p["nome"])
                        cat_ops    = ["Cerveja","Vinho","Água","Refrigerantes","Sumos","Espirituosas","Sidra","Outro"]
                        cat_idx    = cat_ops.index(p["categoria"]) if p["categoria"] in cat_ops else 0
                        categoria_e = st.selectbox("Categoria", cat_ops, index=cat_idx)
                        und_ops    = ["cx","un","fardo","palete","barril","garrafa","pack"]
                        und_idx    = und_ops.index(p["unidade"]) if p["unidade"] in und_ops else 1
                        unidade_e  = st.selectbox("Unidade de venda", und_ops, index=und_idx)
                    with c2:
                        preco_v_e  = st.number_input("Preço de venda (€)", min_value=0.0, value=float(p["preco_venda"]), step=0.5)
                        preco_c_e  = st.number_input("Preço de compra (€)", min_value=0.0, value=float(p["preco_compra"]), step=0.5)
                        stock_m_e  = st.number_input("Stock mínimo", min_value=0, value=int(p["stock_minimo"]))

                    if preco_v_e > 0:
                        margem = preco_v_e - preco_c_e
                        pct    = margem/preco_v_e*100
                        cor    = "#4ade80" if pct >= 20 else "#fbbf24" if pct >= 10 else "#f87171"
                        st.markdown(f"<div class='info-box'>Margem: <b style='color:{cor}'>€{margem:.2f} ({pct:.1f}%)</b></div>",
                                    unsafe_allow_html=True)

                    col_guardar, col_apagar = st.columns(2)
                    with col_guardar:
                        guardar = st.form_submit_button("💾 Guardar alterações", use_container_width=True)
                    with col_apagar:
                        # Apagar só disponível para admin e só se não houver stock nem encomendas
                        apagar = st.form_submit_button("🗑️ Apagar produto", use_container_width=True,
                                                        type="secondary") if u["perfil"] == "admin" else False

                    if guardar:
                        if not ref_e or not nome_e:
                            st.error("❌ Referência e nome são obrigatórios.")
                        elif preco_v_e <= 0:
                            st.error("❌ O preço de venda tem de ser superior a zero.")
                        else:
                            conn = get_connection()
                            try:
                                _cur = conn.cursor()
                                _cur.execute("""UPDATE produtos
                                               SET referencia=%s,nome=%s,categoria=%s,unidade=%s,
                                                   preco_venda=%s,preco_compra=%s,stock_minimo=%s
                                               WHERE id=%s""",
                                             (ref_e,nome_e,categoria_e,unidade_e,
                                              preco_v_e,preco_c_e,stock_m_e,p["id"]))
                                conn.commit(); conn.close()
                                st.success(f"✅ Produto '{nome_e}' atualizado com sucesso!")
                                st.rerun()
                            except Exception as e:
                                conn.close()
                                st.error("❌ Já existe outro produto com essa referência." if "UNIQUE" in str(e) else f"❌ {e}")

                    if apagar:
                        conn = get_connection()
                        # Verifica se tem stock ou encomendas associadas
                        tem_stock = conn.execute(
                            "SELECT SUM(quantidade) FROM stock WHERE produto_id=%s", (p["id"],)
                        ).fetchone()[0] or 0
                        tem_enc = conn.execute(
                            "SELECT COUNT(*) FROM encomenda_linhas WHERE produto_id=%s", (p["id"],)
                        ).fetchone()[0]
                        if tem_stock > 0:
                            conn.close()
                            st.error(f"❌ Não é possível apagar '{p['nome']}' — ainda tem {tem_stock} unidades em stock. Desative-o em vez de apagar.")
                        elif tem_enc > 0:
                            conn.close()
                            st.error(f"❌ Não é possível apagar '{p['nome']}' — está associado a {tem_enc} linha(s) de encomenda. Desative-o em vez de apagar.")
                        else:
                            _cur = conn.cursor()
                            _cur.execute("DELETE FROM produtos WHERE id=%s", (p["id"],))
                            conn.commit(); conn.close()
                            st.success(f"✅ Produto '{p['nome']}' apagado com sucesso.")
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ADMINISTRAÇÃO
# ══════════════════════════════════════════════════════════════════════════════
def pagina_admin():
    st.markdown("## ⚙️ Administração")
    tab1,tab2,tab3 = st.tabs(["👤 Utilizadores","✏️ Editar utilizador","🔌 Módulos"])

    with tab1:
        users = listar_utilizadores()
        df = pd.DataFrame(users)[["nome","username","perfil","armazem_nome","ativo"]]
        df.columns = ["Nome","Username","Perfil","Armazém","Ativo"]
        df["Ativo"] = df["Ativo"].apply(lambda x: "✅" if x else "❌")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("#### Criar novo utilizador")
        armazens = listar_armazens()
        with st.form("novo_user"):
            c1,c2 = st.columns(2)
            with c1:
                nome_u     = st.text_input("Nome")
                username_u = st.text_input("Username")
                password_u = st.text_input("Password", type="password")
            with c2:
                perfil_u = st.selectbox("Perfil", ["condutor","encarregado","admin"])
                arm_u    = st.selectbox("Armazém", [a["nome"] for a in armazens])
            if st.form_submit_button("✅ Criar utilizador", use_container_width=True):
                arm_id_u = next(a["id"] for a in armazens if a["nome"] == arm_u)
                res = criar_utilizador({"nome":nome_u,"username":username_u,"password":password_u,
                                        "perfil":perfil_u,"armazem_id":arm_id_u})
                notificar(res["ok"], f"Utilizador '{nome_u}' criado com sucesso!", res.get("erro"))
                if res["ok"]: st.rerun()

    with tab2:
        st.markdown("#### Editar colaborador")
        armazens = listar_armazens()
        users    = listar_utilizadores()
        if not users:
            st.info("Sem utilizadores disponíveis.")
        else:
            user_nomes = [f"{u['nome']} ({u['perfil']} · {u['armazem_nome'] or 'Todos'})" for u in users]
            sel_u  = st.selectbox("Selecionar colaborador", user_nomes)
            u_sel  = users[user_nomes.index(sel_u)]
            st.markdown(f"**Username:** `{u_sel['username']}`")
            with st.form("editar_user"):
                c1,c2 = st.columns(2)
                with c1:
                    nome_e   = st.text_input("Nome *", value=u_sel["nome"])
                    perfis   = ["condutor","encarregado","admin"]
                    perf_idx = perfis.index(u_sel["perfil"]) if u_sel["perfil"] in perfis else 0
                    perfil_e = st.selectbox("Perfil", perfis, index=perf_idx)
                with c2:
                    arm_nomes = [a["nome"] for a in armazens]
                    arm_idx   = next((i for i,a in enumerate(armazens) if a["id"] == u_sel["armazem_id"]),0)
                    arm_e     = st.selectbox("Armazém", arm_nomes, index=arm_idx)
                    ativo_e   = st.selectbox("Estado", ["Ativo","Inativo"], index=0 if u_sel["ativo"] else 1)
                st.markdown("---")
                st.markdown("**Alterar password** *(deixar em branco para não alterar)*")
                nova_pass = st.text_input("Nova password", type="password")
                conf_pass = st.text_input("Confirmar password", type="password")
                if st.form_submit_button("💾 Guardar alterações", use_container_width=True):
                    if not nome_e:
                        st.error("❌ O nome é obrigatório.")
                    elif nova_pass and nova_pass != conf_pass:
                        st.error("❌ As passwords não coincidem.")
                    else:
                        arm_id_e = next(a["id"] for a in armazens if a["nome"] == arm_e)
                        conn = get_connection()
                        try:
                            _cur = conn.cursor()
                            _cur.execute("""UPDATE utilizadores SET nome=%s,perfil=%s,armazem_id=%s,ativo=%s WHERE id=%s""",
                                         (nome_e,perfil_e,arm_id_e,1 if ativo_e=="Ativo" else 0,u_sel["id"]))
                            if nova_pass:
                                from core.database import hash_password
                                _cur = conn.cursor()
                                _cur.execute("UPDATE utilizadores SET password_hash=%s WHERE id=%s",
                                             (hash_password(nova_pass),u_sel["id"]))
                            conn.commit(); conn.close()
                            msg = f"Colaborador '{nome_e}' atualizado com sucesso."
                            if nova_pass: msg += " Password alterada."
                            st.success(f"✅ {msg}")
                            st.rerun()
                        except Exception as e:
                            conn.close(); st.error(f"❌ {e}")

    with tab3:
        conn = get_connection()
        _cmod = conn.cursor()
        _cmod.execute("SELECT * FROM modulos ORDER BY nome")
        modulos = _cmod.fetchall()
        conn.close()
        st.markdown("#### Módulos instalados")
        for m in modulos:
            st.markdown(f"✅ **{m['nome'].capitalize()}** v{m['versao']} — instalado em {str(m['instalado_em'])[:10]}")
        st.markdown("---")
        st.markdown("#### ➕ Registar novo módulo")
        st.info("Coloque o ficheiro em `/modules/` e registe o nome aqui.")
        novo_modulo = st.text_input("Nome do módulo")
        if st.button("Registar módulo"):
            if novo_modulo:
                conn = get_connection()
                try:
                    _cur = conn.cursor()
                    _cur.execute("INSERT INTO modulos (nome) VALUES (%s)", (novo_modulo,))
                    conn.commit(); conn.close()
                    st.success(f"✅ Módulo '{novo_modulo}' registado com sucesso!")
                except Exception as e:
                    conn.close(); st.error(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# ROTEADOR
# ══════════════════════════════════════════════════════════════════════════════
def main():
    if not st.session_state.utilizador:
        pagina_login(); return
    pagina = sidebar()
    if   "Dashboard"     in pagina: pagina_dashboard()
    elif "Stock"         in pagina: pagina_stock()
    elif "Clientes"      in pagina: pagina_clientes()
    elif "Encomendas"    in pagina: pagina_encomendas()
    elif "Produtos"      in pagina: pagina_produtos()
    elif "Relatórios"    in pagina: pagina_relatorios()
    elif "Administração" in pagina:
        if st.session_state.utilizador["perfil"] == "admin": pagina_admin()
        else: st.error("❌ Acesso negado.")

if __name__ == "__main__":
    main()
