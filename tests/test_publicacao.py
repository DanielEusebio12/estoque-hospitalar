from fastapi.testclient import TestClient

import auth
import dados_demo
import database
import main


def recriar_banco(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "NOME_BANCO", str(tmp_path / "publicado.db"))
    database.criar_tabelas()
    auth.criar_super_admin_inicial()


def test_senha_do_ambiente_substitui_a_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("SENHA_ADMIN_INICIAL", "Segredo#2026")
    recriar_banco(tmp_path, monkeypatch)
    cliente = TestClient(main.app)

    padrao = cliente.post("/login", json={"usuario": "daniel.eusebio", "senha": auth.SENHA_PADRAO})
    assert padrao.status_code == 401

    secreta = cliente.post("/login", json={"usuario": "daniel.eusebio", "senha": "Segredo#2026"})
    assert secreta.status_code == 200
    assert secreta.json()["trocar_senha"] is False


def test_cookie_seguro_quando_publicado(monkeypatch):
    monkeypatch.setenv("COOKIE_SEGURO", "1")
    resposta = TestClient(main.app).post(
        "/login", json={"usuario": "daniel.eusebio", "senha": auth.SENHA_PADRAO}
    )
    assert "secure" in resposta.headers["set-cookie"].lower()


def test_dados_demo_seguem_as_regras_do_sistema(admin):
    dados_demo.popular_se_vazio()

    materiais = admin.get("/materiais").json()
    assert len(materiais) == len(dados_demo.ITENS)
    assert all(material["saldo"] >= 0 for material in materiais)
    # O que sobrou de cada validade (FEFO) soma exatamente o saldo
    for material in materiais:
        validades = admin.get(f"/materiais/{material['id']}/validades").json()
        assert sum(item["quantidade"] for item in validades) == material["saldo"]

    # A demonstração precisa ter algo para mostrar em cada alerta
    assert admin.get("/alertas/estoque-baixo").json()
    vencimentos = admin.get("/alertas/vencimento").json()
    assert any(item["vencido"] for item in vencimentos)
    assert any(not item["vencido"] for item in vencimentos)


def test_dados_demo_nao_duplicam(admin):
    dados_demo.popular_se_vazio()
    dados_demo.popular_se_vazio()
    assert len(admin.get("/materiais").json()) == len(dados_demo.ITENS)
