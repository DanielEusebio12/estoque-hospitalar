from fastapi.testclient import TestClient

import auth
import main
from conftest import SENHA_NOVA, entrar


def test_rotas_exigem_login():
    cliente = TestClient(main.app)
    assert cliente.get("/materiais").status_code == 401
    assert cliente.post("/movimentacoes", json={}).status_code in (401, 422)


def test_pagina_inicial_sem_login_vai_para_o_login():
    cliente = TestClient(main.app)
    resposta = cliente.get("/", follow_redirects=False)
    assert resposta.status_code == 307
    assert resposta.headers["location"] == "/login"


def test_senha_errada_e_usuario_inexistente_dao_a_mesma_mensagem():
    cliente = TestClient(main.app)
    senha_errada = cliente.post("/login", json={"usuario": "daniel.eusebio", "senha": "errada"})
    usuario_inexistente = cliente.post("/login", json={"usuario": "ninguem", "senha": "errada"})
    assert senha_errada.status_code == usuario_inexistente.status_code == 401
    # Mensagem igual para não revelar quais usuários existem
    assert senha_errada.json() == usuario_inexistente.json()


def test_cookie_de_sessao_e_httponly():
    cliente = TestClient(main.app)
    resposta = cliente.post("/login", json={"usuario": "daniel.eusebio", "senha": auth.SENHA_PADRAO})
    assert "httponly" in resposta.headers["set-cookie"].lower()


def test_senha_padrao_obriga_troca_antes_de_usar_o_sistema():
    cliente = TestClient(main.app)
    cliente.post("/login", json={"usuario": "daniel.eusebio", "senha": auth.SENHA_PADRAO})
    assert cliente.get("/materiais").status_code == 403

    resposta = cliente.post(
        "/trocar-senha", json={"senha_atual": auth.SENHA_PADRAO, "nova_senha": auth.SENHA_PADRAO}
    )
    assert resposta.status_code == 422  # não pode "trocar" pela própria senha padrão

    cliente.post("/trocar-senha", json={"senha_atual": auth.SENHA_PADRAO, "nova_senha": SENHA_NOVA})
    assert cliente.get("/materiais").status_code == 200


def test_logout_encerra_a_sessao(admin):
    assert admin.post("/logout").status_code == 200
    assert admin.get("/materiais").status_code == 401


def test_bloquear_derruba_a_sessao_na_hora(admin, criar_colaborador):
    ana = criar_colaborador("ana.lima", "Enfermeiro")
    assert ana.get("/materiais").status_code == 200

    id_ana = next(c["id"] for c in admin.get("/colaboradores").json() if c["usuario"] == "ana.lima")
    admin.patch(f"/colaboradores/{id_ana}/acesso", json={"ativo": False})

    assert ana.get("/materiais").status_code == 401
    novo_login = TestClient(main.app).post("/login", json={"usuario": "ana.lima", "senha": SENHA_NOVA})
    assert novo_login.status_code == 403


def test_resetar_senha_volta_para_a_padrao_com_troca_obrigatoria(admin, criar_colaborador):
    criar_colaborador("ana.lima", "Enfermeiro")
    id_ana = next(c["id"] for c in admin.get("/colaboradores").json() if c["usuario"] == "ana.lima")

    assert admin.post(f"/colaboradores/{id_ana}/resetar-senha").status_code == 200

    cliente = TestClient(main.app)
    resposta = cliente.post("/login", json={"usuario": "ana.lima", "senha": auth.SENHA_PADRAO})
    assert resposta.json()["trocar_senha"] is True


def test_senha_guardada_como_hash():
    senha_hash = auth.gerar_hash_senha("Minha#Senha1")
    assert "Minha#Senha1" not in senha_hash
    assert auth.verificar_senha("Minha#Senha1", senha_hash)
    assert not auth.verificar_senha("outra", senha_hash)
    # Mesmo texto gera hashes diferentes por causa do sal aleatório
    assert auth.gerar_hash_senha("Minha#Senha1") != senha_hash


def test_login_aceita_usuario_em_maiusculas():
    entrar("Daniel.Eusebio")
