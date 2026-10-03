from conftest import inserir_movimentacao_direto


def registrar(cliente, item, tipo, quantidade, **extras):
    dados = {"material_id": item, "tipo": tipo, "quantidade": quantidade, **extras}
    if tipo == "entrada":
        dados.setdefault("validade", "2099-01-01")
    else:
        dados.setdefault("setor", "UTI Adulto")
    return cliente.post("/movimentacoes", json=dados)


def saldo(cliente, item):
    return cliente.get(f"/materiais/{item}/saldo").json()["saldo"]


def test_saldo_e_entradas_menos_saidas(admin, criar_item):
    item = criar_item("Dipirona")
    registrar(admin, item, "entrada", 100)
    registrar(admin, item, "entrada", 50)
    registrar(admin, item, "saida", 30)
    assert saldo(admin, item) == 120


def test_saida_maior_que_o_saldo_e_recusada(admin, criar_item):
    item = criar_item("Dipirona")
    registrar(admin, item, "entrada", 10)
    resposta = registrar(admin, item, "saida", 11)
    assert resposta.status_code == 409
    assert saldo(admin, item) == 10  # nada foi gravado


def test_saida_exige_setor_e_entrada_exige_validade(admin, criar_item):
    item = criar_item("Dipirona")
    assert registrar(admin, item, "entrada", 10, validade=None).status_code == 422
    registrar(admin, item, "entrada", 10)
    assert registrar(admin, item, "saida", 1, setor=None).status_code == 422


def test_item_sem_validade_entra_sem_data(admin, criar_item):
    vassoura = criar_item("Vassoura", "Material de limpeza", controla_validade=False)
    assert registrar(admin, vassoura, "entrada", 5, validade=None).status_code == 201


def test_medicamento_nao_pode_ser_sem_validade(admin):
    resposta = admin.post(
        "/materiais",
        json={"codigo": "D1", "nome": "Dipirona", "categoria": "Medicamento", "unidade": "cp", "controla_validade": False},
    )
    assert resposta.status_code == 422


def test_codigo_e_normalizado_e_unico(admin, criar_item):
    criar_item("Dipirona", codigo=" med-1221 ")
    item = admin.get("/materiais?busca=MED-1221").json()[0]
    assert item["codigo"] == "MED-1221"

    repetido = admin.post(
        "/materiais",
        json={"codigo": "MED-1221", "nome": "Outro", "categoria": "Medicamento", "unidade": "cp"},
    )
    assert repetido.status_code == 409


def test_item_com_movimentacao_nao_pode_ser_excluido(admin, criar_item):
    usado = criar_item("Dipirona")
    sem_uso = criar_item("Cadastro errado", codigo="ERRO")
    registrar(admin, usado, "entrada", 1)

    assert admin.delete(f"/materiais/{usado}").status_code == 409
    assert admin.delete(f"/materiais/{sem_uso}").status_code == 204


def test_desativar_exige_saldo_zero_e_bloqueia_movimentacao(admin, criar_item):
    item = criar_item("Dipirona")
    registrar(admin, item, "entrada", 2)
    assert admin.patch(f"/materiais/{item}/ativo", json={"ativo": False}).status_code == 409

    registrar(admin, item, "saida", 2)
    assert admin.patch(f"/materiais/{item}/ativo", json={"ativo": False}).status_code == 200
    assert registrar(admin, item, "entrada", 1).status_code == 409


def test_unidade_nao_muda_depois_de_movimentar(admin, criar_item):
    item = criar_item("Dipirona")
    registrar(admin, item, "entrada", 1)
    resposta = admin.put(
        f"/materiais/{item}",
        json={"codigo": "DIPI", "nome": "Dipirona", "categoria": "Medicamento", "unidade": "caixa"},
    )
    assert resposta.status_code == 409


def test_alerta_de_estoque_baixo(admin, criar_item):
    baixo = criar_item("Dipirona", estoque_minimo=10)
    ok = criar_item("Soro", "Soro e solução", estoque_minimo=1)
    registrar(admin, baixo, "entrada", 3)
    registrar(admin, ok, "entrada", 5)

    alertas = admin.get("/alertas/estoque-baixo").json()
    assert [(a["nome"], a["quantidade_para_repor"]) for a in alertas] == [("Dipirona", 7)]


def test_painel_conta_registros_por_setor(admin, criar_item):
    item = criar_item("Dipirona")
    registrar(admin, item, "entrada", 10)
    registrar(admin, item, "saida", 3, setor="UTI Adulto")
    registrar(admin, item, "saida", 1, setor="UTI Adulto")
    registrar(admin, item, "saida", 1, setor="Pediatria")

    painel = admin.get("/painel?dias=7").json()
    assert painel["total_entradas"] == 1
    assert painel["total_saidas"] == 3
    assert painel["por_setor"][0] == {"setor": "UTI Adulto", "saidas": 2}
    assert painel["mais_retirados"][0]["quantidade"] == 5
    assert len(painel["por_dia"]) == 7


def test_movimentacao_antiga_sem_responsavel_aparece_no_historico(admin, criar_item):
    item = criar_item("Dipirona")
    inserir_movimentacao_direto(item, "entrada", 5, "2099-01-01")
    assert admin.get("/movimentacoes").json()[0]["quantidade"] == 5
