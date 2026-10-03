def test_so_farmaceutico_registra_entrada(criar_item, criar_colaborador):
    item = criar_item("Dipirona")
    farmaceutica = criar_colaborador("bia.souza", "Farmacêutico")
    enfermeiro = criar_colaborador("caio.reis", "Enfermeiro")
    entrada = {"material_id": item, "tipo": "entrada", "quantidade": 10, "validade": "2099-01-01"}

    assert farmaceutica.post("/movimentacoes", json=entrada).status_code == 201
    assert enfermeiro.post("/movimentacoes", json=entrada).status_code == 403


def test_cada_cargo_so_retira_as_categorias_permitidas(admin, criar_item, criar_colaborador):
    remedio = criar_item("Dipirona", "Medicamento")
    vassoura = criar_item("Vassoura", "Material de limpeza", controla_validade=False)
    for item in (remedio, vassoura):
        admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 10, "validade": "2099-01-01"})

    enfermeiro = criar_colaborador("caio.reis", "Enfermeiro")
    limpeza = criar_colaborador("duda.alves", "Auxiliar de limpeza")

    def retirar(cliente, item):
        return cliente.post(
            "/movimentacoes",
            json={"material_id": item, "tipo": "saida", "quantidade": 1, "setor": "UTI Adulto"},
        ).status_code

    assert retirar(enfermeiro, remedio) == 201
    assert retirar(enfermeiro, vassoura) == 403
    assert retirar(limpeza, vassoura) == 201
    assert retirar(limpeza, remedio) == 403


def test_responsavel_da_movimentacao_vem_da_sessao(admin, criar_item, criar_colaborador):
    item = criar_item("Dipirona")
    admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 5, "validade": "2099-01-01"})
    enfermeiro = criar_colaborador("caio.reis", "Enfermeiro")

    # Mesmo mandando outro colaborador_id no corpo, vale quem está logado
    resposta = enfermeiro.post(
        "/movimentacoes",
        json={"material_id": item, "tipo": "saida", "quantidade": 1, "setor": "Pediatria", "colaborador_id": 1},
    )
    historico = admin.get("/movimentacoes").json()
    assert resposta.status_code == 201
    assert historico[0]["colaborador"] == "Caio Reis"


def test_comum_nao_acessa_rotas_de_admin(criar_colaborador):
    enfermeiro = criar_colaborador("caio.reis", "Enfermeiro")
    assert enfermeiro.get("/colaboradores").status_code == 403
    assert enfermeiro.get("/painel").status_code == 403
    novo_item = {"codigo": "X1", "nome": "Luva", "categoria": "Material hospitalar", "unidade": "par"}
    assert enfermeiro.post("/materiais", json=novo_item).status_code == 403


def test_comum_ve_so_o_proprio_historico(admin, criar_item, criar_colaborador):
    item = criar_item("Dipirona")
    admin.post("/movimentacoes", json={"material_id": item, "tipo": "entrada", "quantidade": 5, "validade": "2099-01-01"})
    enfermeiro = criar_colaborador("caio.reis", "Enfermeiro")
    enfermeiro.post("/movimentacoes", json={"material_id": item, "tipo": "saida", "quantidade": 1, "setor": "Pediatria"})

    assert len(admin.get("/movimentacoes").json()) == 2
    assert [m["colaborador"] for m in enfermeiro.get("/movimentacoes").json()] == ["Caio Reis"]


def test_admin_nao_cria_admin_nem_mexe_no_super_admin(criar_colaborador):
    humberto = criar_colaborador("humberto.amigo", "Farmacêutico", perfil="admin")
    novo_admin = {
        "nome": "Outro Admin",
        "matricula": "99",
        "cargo": "Farmacêutico",
        "usuario": "outro.admin",
        "perfil": "admin",
    }
    assert humberto.post("/colaboradores", json=novo_admin).status_code == 403
    assert humberto.patch("/colaboradores/1/acesso", json={"ativo": False}).status_code == 403


def test_ninguem_altera_o_proprio_acesso(admin):
    assert admin.patch("/colaboradores/1/acesso", json={"ativo": False}).status_code == 403
