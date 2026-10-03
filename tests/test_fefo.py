from datetime import date, timedelta

from conftest import inserir_movimentacao_direto
from main import distribuir_fefo


def entrada(quantidade, validade):
    return {"tipo": "entrada", "quantidade": quantidade, "validade": validade}


def saida(quantidade):
    return {"tipo": "saida", "quantidade": quantidade, "validade": None}


def test_saida_consome_primeiro_o_que_vence_primeiro():
    movimentacoes = [entrada(50, "2027-05-01"), entrada(50, "2026-11-01"), saida(60)]
    assert distribuir_fefo(movimentacoes) == [{"validade": "2027-05-01", "quantidade": 40}]


def test_saida_nao_consome_lote_que_entrou_depois_dela():
    # Regressão do bug do Paractamol: as saídas aconteceram antes dos lotes de outubro existirem
    movimentacoes = [
        entrada(40, "2027-12-30"),
        saida(10),
        saida(10),
        entrada(10, "2026-10-12"),
        entrada(3, "2026-10-05"),
    ]
    assert distribuir_fefo(movimentacoes) == [
        {"validade": "2026-10-05", "quantidade": 3},
        {"validade": "2026-10-12", "quantidade": 10},
        {"validade": "2027-12-30", "quantidade": 20},
    ]


def test_item_sem_validade_sai_por_ultimo():
    movimentacoes = [entrada(5, None), entrada(5, "2027-01-01"), saida(7)]
    assert distribuir_fefo(movimentacoes) == [{"validade": None, "quantidade": 3}]


def test_validade_zerada_some_da_lista():
    assert distribuir_fefo([entrada(5, "2027-01-01"), saida(5)]) == []


def test_alerta_de_vencimento_mostra_o_que_vence_em_30_dias(admin, criar_item):
    item = criar_item("Dipirona")
    perto = (date.today() + timedelta(days=10)).isoformat()
    longe = (date.today() + timedelta(days=200)).isoformat()
    for validade in (perto, longe):
        admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 5, "validade": validade})

    alertas = admin.get("/alertas/vencimento").json()
    assert [(a["validade"], a["dias_restantes"]) for a in alertas] == [(perto, 10)]


def test_entrada_ja_vencida_e_recusada(admin, criar_item):
    item = criar_item("Dipirona")
    ontem = (date.today() - timedelta(days=1)).isoformat()
    resposta = admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 5, "validade": ontem})
    assert resposta.status_code == 422


def test_com_unidade_vencida_so_o_descarte_e_liberado(admin, criar_item):
    item = criar_item("Soro", "Soro e solução")
    vencido = (date.today() - timedelta(days=5)).isoformat()
    # A API não aceita entrada vencida, então o cenário é montado direto no banco
    inserir_movimentacao_direto(item, "entrada", 10, vencido)
    admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 10, "validade": "2099-01-01"})

    def retirar(setor, quantidade):
        return admin.post(
            "/movimentacoes",
            json={"material_id": item, "tipo": "saida", "quantidade": quantidade, "setor": setor},
        ).status_code

    assert retirar("Pediatria", 1) == 409
    assert retirar("Descarte", 10) == 201
    assert retirar("Pediatria", 1) == 201
    assert admin.get(f"/materiais/{item}/validades").json() == [
        {"validade": "2099-01-01", "quantidade": 9, "dias_restantes": (date(2099, 1, 1) - date.today()).days, "vencido": False}
    ]
