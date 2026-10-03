import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Antes de importar o main: ele cria as tabelas ao ser importado, e isso não pode tocar no estoque.db real
os.environ["ESTOQUE_BANCO"] = os.path.join(tempfile.mkdtemp(), "importacao.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402
import database  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SENHA_NOVA = "Senha#Nova123"


@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    """Cada teste começa com um banco vazio, só com o super admin criado na instalação."""
    monkeypatch.setattr(database, "NOME_BANCO", str(tmp_path / "teste.db"))
    database.criar_tabelas()
    auth.criar_super_admin_inicial()


def entrar(usuario, senha=auth.SENHA_PADRAO):
    """Faz login e, se for o primeiro acesso, troca a senha padrão. Devolve o cliente já logado."""
    cliente = TestClient(main.app)
    resposta = cliente.post("/login", json={"usuario": usuario, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    if resposta.json()["trocar_senha"]:
        troca = cliente.post("/trocar-senha", json={"senha_atual": senha, "nova_senha": SENHA_NOVA})
        assert troca.status_code == 200, troca.text
    return cliente


@pytest.fixture
def admin():
    """Cliente logado como o super admin (daniel.eusebio)."""
    return entrar("daniel.eusebio")


@pytest.fixture
def criar_colaborador(admin):
    """Cria um colaborador pelo super admin e devolve o cliente logado como ele."""

    def criar(usuario, cargo, perfil="comum"):
        resposta = admin.post(
            "/colaboradores",
            json={
                "nome": usuario.replace(".", " ").title(),
                "matricula": usuario,
                "cargo": cargo,
                "usuario": usuario,
                "perfil": perfil,
            },
        )
        assert resposta.status_code == 201, resposta.text
        return entrar(usuario)

    return criar


@pytest.fixture
def criar_item(admin):
    """Cadastra um item pelo admin e devolve o id."""

    def criar(nome, categoria="Medicamento", codigo=None, **extras):
        resposta = admin.post(
            "/materiais",
            json={
                "codigo": codigo or nome[:4].upper(),
                "nome": nome,
                "categoria": categoria,
                "unidade": "unidade",
                **extras,
            },
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    return criar


def inserir_movimentacao_direto(material_id, tipo, quantidade, validade=None, setor=None):
    """Grava direto no banco o que a API não aceitaria (ex.: entrada já vencida), para montar cenários."""
    with sqlite3.connect(database.NOME_BANCO) as conn:
        conn.execute(
            "INSERT INTO movimentacoes (material_id, colaborador_id, tipo, quantidade, validade, setor) "
            "VALUES (?, 1, ?, ?, ?, ?)",
            (material_id, tipo, quantidade, validade, setor),
        )
