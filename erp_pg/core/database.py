"""
ERP Bebidas - Base de dados PostgreSQL (Supabase)
"""
import psycopg2
import psycopg2.extras
import hashlib
import streamlit as st


def get_connection():
    """Cria uma ligação directa ao Supabase."""
    return psycopg2.connect(
        st.secrets["DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10
    )


def release_connection(conn):
    """Fecha a ligação. Faz rollback se houver transacção pendente."""
    try:
        if conn and not conn.closed:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
    except Exception:
        pass


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def init_database():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS armazens (
        id SERIAL PRIMARY KEY, nome TEXT NOT NULL, morada TEXT,
        ativo INTEGER DEFAULT 1, criado_em TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS utilizadores (
        id SERIAL PRIMARY KEY, nome TEXT NOT NULL, username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        perfil TEXT NOT NULL CHECK(perfil IN ('admin','encarregado','condutor')),
        armazem_id INTEGER REFERENCES armazens(id),
        ativo INTEGER DEFAULT 1, criado_em TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY, nome TEXT NOT NULL, nif TEXT UNIQUE,
        telefone TEXT, morada TEXT, email TEXT,
        limite_credito REAL DEFAULT 0, score INTEGER DEFAULT 100,
        bloqueado INTEGER DEFAULT 0, motivo_bloqueio TEXT,
        incumprimentos INTEGER DEFAULT 0,
        criado_em TIMESTAMP DEFAULT NOW(), atualizado_em TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS cliente_avaliacoes (
        id SERIAL PRIMARY KEY, cliente_id INTEGER NOT NULL REFERENCES clientes(id),
        tipo TEXT NOT NULL CHECK(tipo IN ('pagamento','atraso','incumprimento','desbloqueio','nota')),
        descricao TEXT, valor REAL, score_antes INTEGER, score_depois INTEGER,
        utilizador_id INTEGER REFERENCES utilizadores(id),
        data TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS produtos (
        id SERIAL PRIMARY KEY, referencia TEXT UNIQUE NOT NULL, nome TEXT NOT NULL,
        categoria TEXT, unidade TEXT DEFAULT 'un',
        preco_venda REAL DEFAULT 0, preco_compra REAL DEFAULT 0,
        stock_minimo INTEGER DEFAULT 0, ativo INTEGER DEFAULT 1,
        criado_em TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS stock (
        id SERIAL PRIMARY KEY,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        armazem_id INTEGER NOT NULL REFERENCES armazens(id),
        quantidade INTEGER DEFAULT 0, lote TEXT, validade TEXT,
        atualizado_em TIMESTAMP DEFAULT NOW(),
        UNIQUE(produto_id, armazem_id, lote))""")

    c.execute("""CREATE TABLE IF NOT EXISTS movimentos_stock (
        id SERIAL PRIMARY KEY,
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        armazem_id INTEGER NOT NULL REFERENCES armazens(id),
        tipo TEXT NOT NULL CHECK(tipo IN ('entrada','saida','transferencia','ajuste')),
        quantidade INTEGER NOT NULL,
        armazem_dest_id INTEGER REFERENCES armazens(id),
        referencia_doc TEXT, observacoes TEXT,
        utilizador_id INTEGER REFERENCES utilizadores(id),
        data TIMESTAMP DEFAULT NOW())""")

    c.execute("""CREATE TABLE IF NOT EXISTS encomendas (
        id SERIAL PRIMARY KEY, numero TEXT UNIQUE NOT NULL,
        cliente_id INTEGER NOT NULL REFERENCES clientes(id),
        armazem_id INTEGER NOT NULL REFERENCES armazens(id),
        estado TEXT DEFAULT 'pendente'
            CHECK(estado IN ('pendente','confirmada','expedida','entregue','cancelada','bloqueada')),
        total REAL DEFAULT 0, observacoes TEXT,
        condutor_id INTEGER REFERENCES utilizadores(id),
        data_encomenda TIMESTAMP DEFAULT NOW(),
        data_entrega TIMESTAMP,
        paga INTEGER DEFAULT 0, data_pagamento TIMESTAMP)""")

    c.execute("""CREATE TABLE IF NOT EXISTS encomenda_linhas (
        id SERIAL PRIMARY KEY,
        encomenda_id INTEGER NOT NULL REFERENCES encomendas(id),
        produto_id INTEGER NOT NULL REFERENCES produtos(id),
        quantidade INTEGER NOT NULL, preco_unitario REAL NOT NULL, subtotal REAL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS modulos (
        id SERIAL PRIMARY KEY, nome TEXT UNIQUE NOT NULL,
        versao TEXT DEFAULT '1.0', ativo INTEGER DEFAULT 1,
        instalado_em TIMESTAMP DEFAULT NOW())""")

    conn.commit()
    _seed(conn)
    release_connection(conn)


def _seed(conn):
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM armazens")
    if c.fetchone()["count"] == 0:
        for row in [("Armazém Norte","Rua das Adegas, 10, Braga"),
                    ("Armazém Centro","Av. das Bebidas, 45, Coimbra"),
                    ("Armazém Sul","Rua do Vinho, 8, Évora")]:
            c.execute("INSERT INTO armazens (nome,morada) VALUES (%s,%s)", row)

    c.execute("SELECT COUNT(*) FROM utilizadores")
    if c.fetchone()["count"] == 0:
        for row in [
            ("Administrador","admin", hash_password("admin123"),"admin",None),
            ("Carlos Silva","carlos",hash_password("enc123"),"encarregado",1),
            ("Ana Ferreira","ana",   hash_password("enc123"),"encarregado",2),
            ("Rui Costa","rui",      hash_password("enc123"),"encarregado",3),
            ("João Motorista","joao",hash_password("mot123"),"condutor",1),
            ("Pedro Entrega","pedro",hash_password("mot123"),"condutor",1),
        ]:
            c.execute("INSERT INTO utilizadores (nome,username,password_hash,perfil,armazem_id) VALUES (%s,%s,%s,%s,%s)", row)

    c.execute("SELECT COUNT(*) FROM produtos")
    if c.fetchone()["count"] == 0:
        for row in [
            ("CX-SB-33","Super Bock 33cl cx24","Cerveja","cx",15.00,10.50,10),
            ("CX-SG-33","Sagres 33cl cx24","Cerveja","cx",14.50,10.00,10),
            ("CX-HN-33","Heineken 33cl cx24","Cerveja","cx",17.00,12.00,5),
            ("GAR-VV-75","Vinho Verde 75cl","Vinho","un",4.50,2.80,20),
            ("GAR-VT-75","Vinho Tinto Regional 75cl","Vinho","un",5.20,3.20,20),
            ("FD-AG-15","Água 1.5L fardo6","Água","fardo",2.80,1.60,30),
            ("FD-AG-05","Água 0.5L fardo12","Água","fardo",3.20,1.80,20),
            ("CX-CM-33","Coca-Cola 33cl cx24","Refrigerantes","cx",16.00,11.00,10),
        ]:
            c.execute("INSERT INTO produtos (referencia,nome,categoria,unidade,preco_venda,preco_compra,stock_minimo) VALUES (%s,%s,%s,%s,%s,%s,%s)", row)

    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()["count"] == 0:
        for row in [
            ("Restaurante O Barril","501234567","253 100 200","Braga","barril@email.pt",5000,100,0,None,0),
            ("Café Central","502345678","239 200 300","Coimbra","cafe@email.pt",2000,85,0,None,0),
            ("Hotel Alentejo","503456789","266 300 400","Évora","hotel@email.pt",10000,45,1,"2 incumprimentos de pagamento",2),
            ("Supermercado Silva","504567890","253 400 500","Braga","silva@email.pt",8000,100,0,None,0),
            ("Bar do Porto","505678901","222 500 600","Porto","bar@email.pt",3000,70,0,None,0),
        ]:
            c.execute("INSERT INTO clientes (nome,nif,telefone,morada,email,limite_credito,score,bloqueado,motivo_bloqueio,incumprimentos) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)

    c.execute("SELECT COUNT(*) FROM stock")
    if c.fetchone()["count"] == 0:
        for row in [
            (1,1,120,"L001","2026-12-31"),(1,2,80,"L001","2026-12-31"),(1,3,60,"L001","2026-12-31"),
            (2,1,100,"L002","2026-12-31"),(2,2,90,"L002","2026-12-31"),(2,3,70,"L002","2026-12-31"),
            (3,1,40,"L003","2026-12-31"),(3,2,30,"L003","2026-12-31"),(3,3,25,"L003","2026-12-31"),
            (4,1,200,"L004","2027-06-30"),(4,2,150,"L004","2027-06-30"),(4,3,180,"L004","2027-06-30"),
            (5,1,160,"L005","2027-06-30"),(5,2,140,"L005","2027-06-30"),(5,3,120,"L005","2027-06-30"),
            (6,1,300,"L006","2027-03-31"),(6,2,250,"L006","2027-03-31"),(6,3,280,"L006","2027-03-31"),
            (7,1,200,"L007","2027-03-31"),(7,2,180,"L007","2027-03-31"),(7,3,160,"L007","2027-03-31"),
            (8,1,90,"L008","2026-09-30"),(8,2,70,"L008","2026-09-30"),(8,3,60,"L008","2026-09-30"),
        ]:
            c.execute("INSERT INTO stock (produto_id,armazem_id,quantidade,lote,validade) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", row)

    for m in [("stock",),("clientes",),("vendas",),("compras",)]:
        c.execute("INSERT INTO modulos (nome) VALUES (%s) ON CONFLICT DO NOTHING", m)

    conn.commit()
