"""Dados de demonstração para o site publicado.

O plano gratuito do Render apaga o disco a cada reinício, então, com DADOS_DEMO=1, o sistema
preenche o banco vazio com itens, colaboradores e 30 dias de movimentações. As movimentações
seguem as mesmas regras da API (saldo nunca negativo, FEFO e bloqueio de vencidos), para os
números da tela baterem com o que o sistema calcula.
"""

import os
import random
from datetime import date, timedelta

import auth
from database import conectar

# (código, nome, categoria, unidade, mínimo, tem validade, estoque inicial, maior saída, peso no sorteio)
ITENS = [
    ("MED-1221", "Dipirona 500mg", "Medicamento", "comprimido", 200, True, 900, 30, 10),
    ("MED-1305", "Paracetamol 750mg", "Medicamento", "comprimido", 150, True, 700, 24, 8),
    ("MED-2040", "Amoxicilina 500mg", "Medicamento", "cápsula", 100, True, 300, 21, 5),
    ("MED-3110", "Omeprazol 20mg", "Medicamento", "cápsula", 80, True, 350, 14, 4),
    ("MED-4502", "Insulina NPH", "Medicamento", "frasco-ampola", 30, True, 70, 3, 3),
    ("MED-5120", "Dipirona injetável", "Medicamento", "ampola", 60, True, 160, 6, 2),
    ("SOR-0100", "Soro fisiológico 0,9% 500ml", "Soro e solução", "bolsa", 120, True, 400, 12, 7),
    ("SOR-0200", "Soro glicosado 5% 500ml", "Soro e solução", "bolsa", 60, True, 90, 8, 4),
    ("MAT-0310", "Luva de procedimento M", "Material hospitalar", "caixa", 40, True, 160, 6, 6),
    ("MAT-0420", "Seringa 10ml", "Material hospitalar", "unidade", 300, True, 1500, 40, 7),
    ("MAT-0530", "Gaze estéril", "Material hospitalar", "pacote", 100, True, 450, 15, 5),
    ("ANT-0610", "Álcool 70% 1L", "Antisséptico", "frasco", 30, True, 110, 4, 3),
    ("ANT-0620", "Clorexidina 2%", "Antisséptico", "frasco", 20, True, 50, 3, 2),
    ("LIM-0710", "Pano de limpeza", "Material de limpeza", "unidade", 50, False, 220, 8, 3),
    ("LIM-0720", "Desinfetante hospitalar", "Material de limpeza", "frasco", 15, True, 60, 3, 2),
    ("LIM-0730", "Rodo", "Material de limpeza", "unidade", 5, False, 12, 1, 1),
]

# (nome, usuário, cargo, perfil)
COLABORADORES = [
    ("Humberto Amigo", "humberto.amigo", "Farmacêutico", "admin"),
    ("Beatriz Rocha", "beatriz.rocha", "Farmacêutico", "comum"),
    ("Ana Lima", "ana.lima", "Enfermeiro", "comum"),
    ("Carlos Souza", "carlos.souza", "Técnico de enfermagem", "comum"),
    ("Joana Pereira", "joana.pereira", "Auxiliar de limpeza", "comum"),
]

# Pronto-socorro e UTIs aparecem mais vezes porque consomem mais
SETORES = [
    "Pronto-socorro", "Pronto-socorro", "Pronto-socorro", "UTI Adulto", "UTI Adulto",
    "UTI Neonatal", "Centro cirúrgico", "Centro cirúrgico", "Clínica médica",
    "Clínica médica", "Pediatria", "Maternidade", "Ambulatório",
]

# Saldo final de alguns itens, para a demonstração ter alertas de estoque baixo e sem estoque
SALDO_FINAL = {"SOR-0200": 0, "MED-4502": 22, "ANT-0620": 12, "LIM-0730": 3}


def popular_se_vazio():
    with conectar() as conn:
        if conn.execute("SELECT 1 FROM materiais LIMIT 1").fetchone():
            return
        ids_colaboradores = criar_colaboradores(conn)
        ids_itens = criar_itens(conn)
        for evento in gerar_movimentacoes(date.today()):
            conn.execute(
                "INSERT INTO movimentacoes "
                "(material_id, colaborador_id, tipo, quantidade, validade, setor, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ids_itens[evento["codigo"]],
                    ids_colaboradores[evento["usuario"]],
                    evento["tipo"],
                    evento["quantidade"],
                    evento["validade"],
                    evento["setor"],
                    evento["data"],
                ),
            )


def criar_colaboradores(conn) -> dict:
    # Mesma senha do admin quando ela vem do ambiente; senão a padrão, com troca obrigatória
    senha = os.environ.get("SENHA_ADMIN_INICIAL") or auth.SENHA_PADRAO
    trocar_senha = 0 if os.environ.get("SENHA_ADMIN_INICIAL") else 1
    super_admin = conn.execute("SELECT id FROM colaboradores WHERE perfil = 'super_admin'").fetchone()
    ids = {"daniel.eusebio": super_admin["id"]}
    for matricula, (nome, usuario, cargo, perfil) in enumerate(COLABORADORES, start=100):
        cursor = conn.execute(
            "INSERT INTO colaboradores "
            "(nome, matricula, cargo, usuario, senha_hash, perfil, trocar_senha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nome, str(matricula), cargo, usuario, auth.gerar_hash_senha(senha), perfil, trocar_senha),
        )
        ids[usuario] = cursor.lastrowid
    return ids


def criar_itens(conn) -> dict:
    ids = {}
    for codigo, nome, categoria, unidade, minimo, tem_validade, *_ in ITENS:
        cursor = conn.execute(
            "INSERT INTO materiais "
            "(codigo, nome, categoria, unidade, estoque_minimo, controla_validade) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (codigo, nome, categoria, unidade, minimo, int(tem_validade)),
        )
        ids[codigo] = cursor.lastrowid
    return ids


def gerar_movimentacoes(hoje: date) -> list[dict]:
    """Simula 30 dias de uso do estoque, em ordem cronológica (a ordem de gravação importa para o FEFO)."""
    sorteio = random.Random(42)  # semente fixa: os mesmos dados a cada reinício
    inicio = hoje - timedelta(days=29)
    itens = {item[0]: item for item in ITENS}
    estoque = {codigo: {} for codigo in itens}  # código -> {validade: quantidade}
    eventos = []

    def validade_em(dias):
        return (hoje + timedelta(days=dias)).isoformat()

    def entrada(dia, hora, codigo, quantidade, validade):
        if not itens[codigo][5]:
            validade = None
        lotes = estoque[codigo]
        lotes[validade] = lotes.get(validade, 0) + quantidade
        eventos.append(
            {"data": f"{dia} {hora}", "codigo": codigo, "tipo": "entrada", "quantidade": quantidade,
             "validade": validade, "setor": None, "usuario": "beatriz.rocha"}
        )

    def saida(dia, hora, codigo, quantidade, setor, usuario):
        lotes = estoque[codigo]
        saldo = sum(lotes.values())
        vencidas = any(v is not None and v < dia.isoformat() and q > 0 for v, q in lotes.items())
        # Mesmas regras da API: sem saldo negativo e, com vencidos, só o descarte sai
        if quantidade > saldo or (vencidas and setor != "Descarte"):
            return
        a_descontar = quantidade
        for validade in sorted(lotes, key=lambda v: (v is None, v or "")):
            consumido = min(lotes[validade], a_descontar)
            lotes[validade] -= consumido
            a_descontar -= consumido
        eventos.append(
            {"data": f"{dia} {hora}", "codigo": codigo, "tipo": "saida", "quantidade": quantidade,
             "validade": None, "setor": setor, "usuario": usuario}
        )

    def responsavel(codigo):
        categoria = itens[codigo][2]
        if categoria == "Material de limpeza":
            return "joana.pereira"
        return sorteio.choice(["ana.lima", "ana.lima", "carlos.souza", "beatriz.rocha"])

    codigos = list(itens)
    pesos = [itens[codigo][8] for codigo in codigos]

    for deslocamento in range(30):
        dia = inicio + timedelta(days=deslocamento)

        # Estoque inicial e reposições
        if deslocamento == 0:
            for codigo in codigos:
                entrada(dia, "07:30:00", codigo, itens[codigo][6], validade_em(sorteio.randint(150, 500)))
            # Lote que já venceu: aparece em vermelho e só pode sair como descarte
            entrada(dia, "07:45:00", "MED-5120", 40, validade_em(-2))
        if deslocamento == 14:
            for codigo, quantidade in [("MED-1221", 500), ("MED-1305", 300), ("MAT-0420", 800), ("MAT-0310", 60)]:
                entrada(dia, "08:00:00", codigo, quantidade, validade_em(sorteio.randint(200, 500)))
            entrada(dia, "08:10:00", "SOR-0100", 200, validade_em(20))
        if deslocamento == 26:
            # Lote que vence em poucos dias: aparece no alerta de vencimento
            entrada(dia, "08:00:00", "MED-2040", 90, validade_em(6))

        if deslocamento == 19:
            saida(dia, "16:00:00", "MAT-0530", 4, "Descarte", "beatriz.rocha")  # pacotes avariados

        # Saídas do dia: menos movimento no fim de semana
        quantidade_saidas = sorteio.randint(2, 4) if dia.weekday() >= 5 else sorteio.randint(5, 9)
        for _ in range(quantidade_saidas):
            codigo = sorteio.choices(codigos, weights=pesos)[0]
            hora = f"{sorteio.randint(7, 21):02d}:{sorteio.randint(0, 59):02d}:00"
            quantidade = sorteio.randint(1, itens[codigo][7])
            saida(dia, hora, codigo, quantidade, sorteio.choice(SETORES), responsavel(codigo))

    # Ajuste final para a demonstração ter itens abaixo do mínimo e sem estoque
    for codigo, alvo in SALDO_FINAL.items():
        excesso = sum(estoque[codigo].values()) - alvo
        if excesso > 0:
            saida(hoje, "18:30:00", codigo, excesso, "UTI Adulto", responsavel(codigo))

    # Gravar em ordem cronológica: o FEFO da API usa a ordem dos registros
    return sorted(eventos, key=lambda evento: evento["data"])
