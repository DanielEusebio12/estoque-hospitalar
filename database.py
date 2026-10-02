import sqlite3

NOME_BANCO = "estoque.db"


def conectar():
    conn = sqlite3.connect(NOME_BANCO)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_tabelas():
    with conectar() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS materiais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                categoria TEXT NOT NULL,
                unidade TEXT NOT NULL,
                estoque_minimo INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS movimentacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL REFERENCES materiais(id),
                tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
                quantidade INTEGER NOT NULL CHECK (quantidade > 0),
                lote TEXT,
                validade TEXT,
                setor TEXT,
                data TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS colaboradores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                matricula TEXT NOT NULL UNIQUE,
                cargo TEXT NOT NULL
            );

            -- Guarda só o hash do token: quem ler o banco não consegue usar a sessão de ninguém
            CREATE TABLE IF NOT EXISTS sessoes (
                token_hash TEXT PRIMARY KEY,
                colaborador_id INTEGER NOT NULL REFERENCES colaboradores(id),
                expira_em TEXT NOT NULL
            );
        """)

        # Colunas adicionadas depois; o ALTER TABLE atualiza bancos que já existiam sem perder dados
        adicionar_coluna(conn, "movimentacoes", "colaborador_id", "INTEGER REFERENCES colaboradores(id)")
        adicionar_coluna(conn, "materiais", "ativo", "INTEGER NOT NULL DEFAULT 1")
        adicionar_coluna(conn, "colaboradores", "usuario", "TEXT")
        adicionar_coluna(conn, "colaboradores", "senha_hash", "TEXT")
        adicionar_coluna(conn, "colaboradores", "perfil", "TEXT NOT NULL DEFAULT 'comum'")
        adicionar_coluna(conn, "colaboradores", "trocar_senha", "INTEGER NOT NULL DEFAULT 1")
        adicionar_coluna(conn, "colaboradores", "ativo", "INTEGER NOT NULL DEFAULT 1")
        # ALTER TABLE não aceita UNIQUE, então a unicidade do usuário vem por índice
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_colaboradores_usuario ON colaboradores(usuario)"
        )


def adicionar_coluna(conn, tabela, coluna, definicao):
    # Nomes de tabela/coluna não podem ir como parâmetro (?); aqui são fixos no código, nunca do usuário
    colunas = [linha["name"] for linha in conn.execute(f"PRAGMA table_info({tabela})")]
    if coluna not in colunas:
        conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")