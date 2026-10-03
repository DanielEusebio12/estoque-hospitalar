# from fastapi import FastAPI

# app = FastAPI()

# @app.get("/")
# def raiz():
#     return {"mensagem": "Estoque funcionando"}
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

import auth
import dados_demo
from auth import PERFIS_ADMIN, exigir_admin, usuario_autenticado, usuario_logado
from database import conectar, criar_tabelas

# Caminho a partir deste arquivo, para funcionar de qualquer pasta onde o servidor for iniciado
PASTA_FRONTEND = Path(__file__).parent / "frontend"

app = FastAPI(title="Controle de estoque hospitalar")
app.mount("/static", StaticFiles(directory=PASTA_FRONTEND), name="static")
app.include_router(auth.router)

criar_tabelas()
auth.criar_super_admin_inicial()
# Site de demonstração: o disco é apagado a cada reinício, então ele se preenche sozinho
if os.environ.get("DADOS_DEMO") == "1":
    dados_demo.popular_se_vazio()


# Lista fechada porque as permissões dependem do nome exato da categoria
Categoria = Literal[
    "Medicamento", "Material hospitalar", "Soro e solução", "Antisséptico", "Material de limpeza"
]
Cargo = Literal[
    "Farmacêutico", "Enfermeiro", "Técnico de enfermagem", "Auxiliar de limpeza", "Administrador"
]

CATEGORIAS_ENFERMAGEM = {"Medicamento", "Material hospitalar", "Soro e solução", "Antisséptico"}

# Categorias que cada cargo pode retirar; o farmacêutico pode tudo e é o único que registra entrada
PERMISSOES_SAIDA = {
    "Enfermeiro": CATEGORIAS_ENFERMAGEM,
    "Técnico de enfermagem": CATEGORIAS_ENFERMAGEM,
    "Auxiliar de limpeza": {"Material de limpeza"},
}


# Itens de uso no paciente sempre têm validade; o "sem validade" é para pano, vassoura, rodo...
CATEGORIAS_COM_VALIDADE_OBRIGATORIA = {"Medicamento", "Soro e solução"}


class MaterialEntrada(BaseModel):
    # Texto e não número: códigos podem ter zero à esquerda ou letras (ex.: 00123, MED-1221)
    codigo: str = Field(min_length=1, max_length=30)
    nome: str = Field(min_length=2)
    categoria: Categoria
    unidade: str = Field(min_length=1)
    estoque_minimo: int = Field(default=0, ge=0)
    controla_validade: bool = True

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]+", valor):
            raise ValueError("Código deve ter só letras, números, ponto ou hífen")
        return valor

    @model_validator(mode="after")
    def validar_validade_obrigatoria(self):
        if not self.controla_validade and self.categoria in CATEGORIAS_COM_VALIDADE_OBRIGATORIA:
            raise ValueError(f"{self.categoria} precisa ter controle de validade")
        return self


class ColaboradorEntrada(BaseModel):
    nome: str = Field(min_length=2)
    matricula: str = Field(min_length=1)
    cargo: Cargo
    usuario: str
    # super_admin fica de fora: só existe o criado na instalação
    perfil: Literal["comum", "admin"] = "comum"

    @field_validator("usuario")
    @classmethod
    def validar_usuario(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(\.[a-z0-9]+)*", valor):
            raise ValueError("Usuário deve ser no formato nome.sobrenome, sem acentos ou espaços")
        return valor


# Usado para ativar/desativar tanto colaboradores quanto materiais
class AtivoEntrada(BaseModel):
    ativo: bool


class MovimentacaoEntrada(BaseModel):
    material_id: int
    tipo: Literal["entrada", "saida"]
    quantidade: int = Field(gt=0)
    lote: str | None = None
    validade: date | None = None
    setor: str | None = None

    @model_validator(mode="after")
    def validar_campos_por_tipo(self):
        # Se a entrada exige validade depende do item, então isso é conferido no endpoint
        if self.tipo == "entrada" and self.validade and self.validade < date.today():
            raise ValueError("Não é possível dar entrada em item já vencido")
        if self.tipo == "saida" and not self.setor:
            raise ValueError("Saída exige o setor de destino")
        return self


# Fórmula única do saldo, reaproveitada em todas as consultas para não divergirem
SQL_SALDO = (
    "COALESCE(SUM(CASE WHEN mv.tipo = 'entrada' THEN mv.quantidade ELSE -mv.quantidade END), 0)"
)

# LEFT JOIN para material sem movimentação aparecer com saldo 0
SQL_MATERIAIS_COM_SALDO = (
    f"SELECT m.*, {SQL_SALDO} AS saldo "
    "FROM materiais m LEFT JOIN movimentacoes mv ON mv.material_id = m.id"
)


def tem_movimentacoes(conn, material_id: int) -> bool:
    linha = conn.execute(
        "SELECT 1 FROM movimentacoes WHERE material_id = ? LIMIT 1", (material_id,)
    ).fetchone()
    return linha is not None


def calcular_saldo(conn, material_id: int) -> int:
    linha = conn.execute(
        f"SELECT {SQL_SALDO} FROM movimentacoes mv WHERE mv.material_id = ?",
        (material_id,),
    ).fetchone()
    return linha[0]


# ---------- Validades (FEFO) ----------

# Itens vencidos ou que vencem nesse prazo entram no alerta
DIAS_ALERTA_VENCIMENTO = 30
# Saída para esse setor é o descarte de vencidos; é a única liberada quando há unidades vencidas
SETOR_DESCARTE = "Descarte"


def ordem_fefo(validade: str | None) -> tuple:
    # Sem validade vai para o fim: nunca vence, então é a última a sair
    return (validade is None, validade or "")


def distribuir_fefo(movimentacoes: list) -> list[dict]:
    """Quanto sobra de cada validade, supondo que cada saída levou primeiro o que vencia primeiro.

    `movimentacoes` precisa vir em ordem de registro: uma saída só pode consumir
    o que já tinha entrado até aquele momento.
    """
    estoque = {}  # validade -> quantidade disponível
    for mov in movimentacoes:
        if mov["tipo"] == "entrada":
            estoque[mov["validade"]] = estoque.get(mov["validade"], 0) + mov["quantidade"]
            continue
        a_descontar = mov["quantidade"]
        for validade in sorted(estoque, key=ordem_fefo):
            consumido = min(estoque[validade], a_descontar)
            estoque[validade] -= consumido
            a_descontar -= consumido
            if a_descontar == 0:
                break
    return [
        {"validade": validade, "quantidade": quantidade}
        for validade, quantidade in sorted(estoque.items(), key=lambda item: ordem_fefo(item[0]))
        if quantidade > 0
    ]


def descrever_validade(item: dict, hoje: date) -> dict:
    dias = (date.fromisoformat(item["validade"]) - hoje).days if item["validade"] else None
    return {**item, "dias_restantes": dias, "vencido": dias is not None and dias < 0}


# Ordem do id = ordem em que foram registradas
SQL_MOVIMENTACOES_EM_ORDEM = (
    "SELECT material_id, tipo, quantidade, validade FROM movimentacoes {filtro} "
    "ORDER BY material_id, id"
)


def calcular_validades(conn, material_id: int) -> list[dict]:
    movimentacoes = conn.execute(
        SQL_MOVIMENTACOES_EM_ORDEM.format(filtro="WHERE material_id = ?"), (material_id,)
    ).fetchall()
    hoje = date.today()
    return [descrever_validade(item, hoje) for item in distribuir_fefo(movimentacoes)]


def calcular_validades_de_todos(conn) -> dict[int, list[dict]]:
    """Validades em estoque de cada item, com uma consulta só em vez de uma por item."""
    movimentacoes = conn.execute(SQL_MOVIMENTACOES_EM_ORDEM.format(filtro="")).fetchall()
    por_material = {}
    for mov in movimentacoes:
        por_material.setdefault(mov["material_id"], []).append(mov)
    hoje = date.today()
    return {
        material_id: [descrever_validade(item, hoje) for item in distribuir_fefo(lista)]
        for material_id, lista in por_material.items()
    }


def verificar_permissao(usuario: dict, tipo: str, categoria: str):
    if usuario["perfil"] == "super_admin" or usuario["cargo"] == "Farmacêutico":
        return
    if tipo == "entrada":
        raise HTTPException(status_code=403, detail="Só o farmacêutico pode registrar entradas")
    if categoria not in PERMISSOES_SAIDA.get(usuario["cargo"], set()):
        raise HTTPException(
            status_code=403, detail=f"{usuario['cargo']} não tem permissão para retirar {categoria}"
        )


def verificar_pode_gerenciar(gestor: dict, alvo) -> None:
    # Admin só gerencia usuários comuns; super admin gerencia todos, menos ele mesmo
    if alvo["id"] == gestor["id"]:
        raise HTTPException(status_code=403, detail="Você não pode alterar o seu próprio acesso")
    if alvo["perfil"] == "super_admin":
        raise HTTPException(status_code=403, detail="O super admin não pode ser alterado")
    if alvo["perfil"] == "admin" and gestor["perfil"] != "super_admin":
        raise HTTPException(
            status_code=403, detail="Só o super admin pode alterar o acesso de administradores"
        )


def verificar_pode_dar_perfil(gestor: dict, perfil: str) -> None:
    if perfil == "admin" and gestor["perfil"] != "super_admin":
        raise HTTPException(status_code=403, detail="Só o super admin pode dar o perfil de administrador")


# ---------- Páginas ----------


@app.get("/")
def raiz(sessao: str | None = Cookie(default=None)):
    # Redireciona no servidor para a página do sistema nem aparecer sem login
    try:
        usuario = usuario_autenticado(sessao)
    except HTTPException:
        return RedirectResponse("/login")
    if usuario["trocar_senha"]:
        return RedirectResponse("/trocar-senha")
    return FileResponse(PASTA_FRONTEND / "index.html")


@app.get("/login")
def pagina_login():
    return FileResponse(PASTA_FRONTEND / "login.html")


@app.get("/trocar-senha")
def pagina_trocar_senha():
    return FileResponse(PASTA_FRONTEND / "trocar-senha.html")


# ---------- Materiais ----------


@app.post("/materiais", status_code=201)
def criar_material(material: MaterialEntrada, usuario: dict = Depends(exigir_admin)):
    try:
        with conectar() as conn:
            cursor = conn.execute(
                "INSERT INTO materiais "
                "(codigo, nome, categoria, unidade, estoque_minimo, controla_validade) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    material.codigo,
                    material.nome,
                    material.categoria,
                    material.unidade,
                    material.estoque_minimo,
                    int(material.controla_validade),
                ),
            )
            novo_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Já existe um item com esse nome ou código")
    return {"id": novo_id, **material.model_dump()}


@app.put("/materiais/{material_id}")
def editar_material(
    material_id: int, material: MaterialEntrada, usuario: dict = Depends(exigir_admin)
):
    try:
        with conectar() as conn:
            atual = conn.execute(
                "SELECT unidade FROM materiais WHERE id = ?", (material_id,)
            ).fetchone()
            if atual is None:
                raise HTTPException(status_code=404, detail="Material não encontrado")
            # Trocar "comprimido" por "caixa" mudaria o sentido de todas as quantidades já registradas
            if material.unidade != atual["unidade"] and tem_movimentacoes(conn, material_id):
                raise HTTPException(
                    status_code=409,
                    detail="Não é possível mudar a unidade de um item que já tem movimentações",
                )
            conn.execute(
                "UPDATE materiais SET codigo = ?, nome = ?, categoria = ?, unidade = ?, "
                "estoque_minimo = ?, controla_validade = ? WHERE id = ?",
                (
                    material.codigo,
                    material.nome,
                    material.categoria,
                    material.unidade,
                    material.estoque_minimo,
                    int(material.controla_validade),
                    material_id,
                ),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Já existe um item com esse nome ou código")
    return {"id": material_id, **material.model_dump()}


@app.patch("/materiais/{material_id}/ativo")
def alterar_ativo_material(
    material_id: int, dados: AtivoEntrada, usuario: dict = Depends(exigir_admin)
):
    with conectar() as conn:
        existe = conn.execute("SELECT 1 FROM materiais WHERE id = ?", (material_id,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        if not dados.ativo:
            # Desativar com saldo esconderia um estoque que ainda existe fisicamente
            saldo = calcular_saldo(conn, material_id)
            if saldo > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Não é possível desativar um item com saldo ({saldo}). Registre a saída antes",
                )
        conn.execute(
            "UPDATE materiais SET ativo = ? WHERE id = ?", (int(dados.ativo), material_id)
        )
    return {"id": material_id, "ativo": dados.ativo}


@app.delete("/materiais/{material_id}", status_code=204)
def excluir_material(material_id: int, usuario: dict = Depends(exigir_admin)):
    with conectar() as conn:
        existe = conn.execute("SELECT 1 FROM materiais WHERE id = ?", (material_id,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        # Excluir só serve para cadastro errado; com movimentações apagaria o histórico
        if tem_movimentacoes(conn, material_id):
            raise HTTPException(
                status_code=409,
                detail="Item com movimentações não pode ser excluído. Use desativar",
            )
        conn.execute("DELETE FROM materiais WHERE id = ?", (material_id,))


@app.get("/materiais")
def listar_materiais(
    busca: str | None = None,
    incluir_inativos: bool = False,
    usuario: dict = Depends(usuario_logado),
):
    sql = SQL_MATERIAIS_COM_SALDO
    condicoes = []
    parametros = []
    if not incluir_inativos:
        condicoes.append("m.ativo = 1")
    if busca:
        # Busca pelo nome ou pelo código exato
        condicoes.append("(m.nome LIKE ? OR m.codigo = ?)")
        parametros.extend([f"%{busca}%", busca.strip().upper()])
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " GROUP BY m.id ORDER BY m.nome"
    with conectar() as conn:
        linhas = conn.execute(sql, parametros).fetchall()
        validades_por_material = calcular_validades_de_todos(conn)
    resultado = []
    for linha in linhas:
        # A primeira validade da lista FEFO é a que vence antes (e a que deve sair primeiro)
        com_data = [v for v in validades_por_material.get(linha["id"], []) if v["validade"]]
        proxima = com_data[0] if com_data else None
        resultado.append(
            {
                **dict(linha),
                "proxima_validade": proxima["validade"] if proxima else None,
                "dias_para_vencer": proxima["dias_restantes"] if proxima else None,
            }
        )
    return resultado


@app.get("/materiais/{material_id}")
def buscar_material(material_id: int, usuario: dict = Depends(usuario_logado)):
    with conectar() as conn:
        linha = conn.execute(
            SQL_MATERIAIS_COM_SALDO + " WHERE m.id = ? GROUP BY m.id", (material_id,)
        ).fetchone()
    if linha is None:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    return dict(linha)


@app.get("/materiais/{material_id}/saldo")
def consultar_saldo(material_id: int, usuario: dict = Depends(usuario_logado)):
    with conectar() as conn:
        material = conn.execute(
            "SELECT id, nome, unidade FROM materiais WHERE id = ?", (material_id,)
        ).fetchone()
        if material is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        saldo = calcular_saldo(conn, material_id)
    return {
        "material_id": material["id"],
        "nome": material["nome"],
        "unidade": material["unidade"],
        "saldo": saldo,
    }


@app.get("/materiais/{material_id}/validades")
def consultar_validades(material_id: int, usuario: dict = Depends(usuario_logado)):
    with conectar() as conn:
        existe = conn.execute("SELECT 1 FROM materiais WHERE id = ?", (material_id,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        return calcular_validades(conn, material_id)


@app.get("/alertas/vencimento")
def alertas_vencimento(
    dias: int = Query(default=DIAS_ALERTA_VENCIMENTO, ge=0, le=365),
    usuario: dict = Depends(usuario_logado),
):
    with conectar() as conn:
        materiais = {
            linha["id"]: linha
            for linha in conn.execute("SELECT id, nome, unidade FROM materiais WHERE ativo = 1")
        }
        validades_por_material = calcular_validades_de_todos(conn)

    alertas = []
    for material_id, validades in validades_por_material.items():
        material = materiais.get(material_id)
        if material is None:  # item desativado
            continue
        for validade in validades:
            if validade["dias_restantes"] is not None and validade["dias_restantes"] <= dias:
                alertas.append(
                    {
                        "material_id": material_id,
                        "nome": material["nome"],
                        "unidade": material["unidade"],
                        **validade,
                    }
                )
    return sorted(alertas, key=lambda alerta: alerta["validade"])


@app.get("/alertas/estoque-baixo")
def alertas_estoque_baixo(usuario: dict = Depends(usuario_logado)):
    # HAVING porque o saldo só existe depois do agrupamento
    sql = (
        SQL_MATERIAIS_COM_SALDO
        + " WHERE m.ativo = 1 GROUP BY m.id HAVING saldo < m.estoque_minimo ORDER BY m.nome"
    )
    with conectar() as conn:
        linhas = conn.execute(sql).fetchall()
    return [
        {**dict(linha), "quantidade_para_repor": linha["estoque_minimo"] - linha["saldo"]}
        for linha in linhas
    ]


# ---------- Colaboradores ----------


@app.post("/colaboradores", status_code=201)
def criar_colaborador(colaborador: ColaboradorEntrada, gestor: dict = Depends(exigir_admin)):
    verificar_pode_dar_perfil(gestor, colaborador.perfil)
    try:
        with conectar() as conn:
            cursor = conn.execute(
                "INSERT INTO colaboradores "
                "(nome, matricula, cargo, usuario, senha_hash, perfil, trocar_senha) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (
                    colaborador.nome,
                    colaborador.matricula,
                    colaborador.cargo,
                    colaborador.usuario,
                    auth.gerar_hash_senha(auth.SENHA_PADRAO),
                    colaborador.perfil,
                ),
            )
            novo_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Já existe um colaborador com essa matrícula ou usuário")
    return {"id": novo_id, **colaborador.model_dump()}


@app.get("/colaboradores")
def listar_colaboradores(gestor: dict = Depends(exigir_admin)):
    with conectar() as conn:
        linhas = conn.execute(
            "SELECT id, nome, matricula, cargo, usuario, perfil, ativo, trocar_senha "
            "FROM colaboradores ORDER BY nome"
        ).fetchall()
    return [dict(linha) for linha in linhas]


@app.put("/colaboradores/{colaborador_id}")
def editar_colaborador(
    colaborador_id: int, dados: ColaboradorEntrada, gestor: dict = Depends(exigir_admin)
):
    try:
        with conectar() as conn:
            alvo = conn.execute(
                "SELECT id, perfil, senha_hash FROM colaboradores WHERE id = ?", (colaborador_id,)
            ).fetchone()
            if alvo is None:
                raise HTTPException(status_code=404, detail="Colaborador não encontrado")
            verificar_pode_gerenciar(gestor, alvo)
            verificar_pode_dar_perfil(gestor, dados.perfil)

            conn.execute(
                "UPDATE colaboradores SET nome = ?, matricula = ?, cargo = ?, usuario = ?, perfil = ? "
                "WHERE id = ?",
                (dados.nome, dados.matricula, dados.cargo, dados.usuario, dados.perfil, colaborador_id),
            )
            # Cadastros antigos não tinham senha; ao ganhar usuário recebem a padrão, com troca obrigatória
            if alvo["senha_hash"] is None:
                conn.execute(
                    "UPDATE colaboradores SET senha_hash = ?, trocar_senha = 1 WHERE id = ?",
                    (auth.gerar_hash_senha(auth.SENHA_PADRAO), colaborador_id),
                )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Já existe um colaborador com essa matrícula ou usuário")
    return {"id": colaborador_id, **dados.model_dump()}


@app.patch("/colaboradores/{colaborador_id}/acesso")
def alterar_acesso(colaborador_id: int, dados: AtivoEntrada, gestor: dict = Depends(exigir_admin)):
    with conectar() as conn:
        alvo = conn.execute(
            "SELECT id, perfil FROM colaboradores WHERE id = ?", (colaborador_id,)
        ).fetchone()
        if alvo is None:
            raise HTTPException(status_code=404, detail="Colaborador não encontrado")
        verificar_pode_gerenciar(gestor, alvo)

        conn.execute(
            "UPDATE colaboradores SET ativo = ? WHERE id = ?", (int(dados.ativo), colaborador_id)
        )
        if not dados.ativo:
            # Derruba as sessões abertas para o bloqueio valer na hora, não só no próximo login
            conn.execute("DELETE FROM sessoes WHERE colaborador_id = ?", (colaborador_id,))
    return {"id": colaborador_id, "ativo": dados.ativo}


@app.post("/colaboradores/{colaborador_id}/resetar-senha")
def resetar_senha(colaborador_id: int, gestor: dict = Depends(exigir_admin)):
    with conectar() as conn:
        alvo = conn.execute(
            "SELECT id, perfil FROM colaboradores WHERE id = ?", (colaborador_id,)
        ).fetchone()
        if alvo is None:
            raise HTTPException(status_code=404, detail="Colaborador não encontrado")
        verificar_pode_gerenciar(gestor, alvo)

        conn.execute(
            "UPDATE colaboradores SET senha_hash = ?, trocar_senha = 1 WHERE id = ?",
            (auth.gerar_hash_senha(auth.SENHA_PADRAO), colaborador_id),
        )
        conn.execute("DELETE FROM sessoes WHERE colaborador_id = ?", (colaborador_id,))
    return {"mensagem": "Senha redefinida para a padrão"}


# ---------- Painel (gráficos) ----------

# Quantos itens aparecem no gráfico de mais retirados
LIMITE_ITENS_PAINEL = 8


@app.get("/painel")
def painel(
    dias: int = Query(default=30, ge=1, le=365), gestor: dict = Depends(exigir_admin)
):
    inicio = date.today() - timedelta(days=dias - 1)
    # date(data) corta a hora; comparar texto ISO funciona porque a ordem alfabética é a cronológica
    filtro_periodo = "date(mv.data) >= ?"

    with conectar() as conn:
        # Conta registros, e não quantidades: somar comprimidos com caixas não teria sentido
        por_dia = conn.execute(
            "SELECT date(mv.data) AS dia, "
            "SUM(mv.tipo = 'entrada') AS entradas, SUM(mv.tipo = 'saida') AS saidas "
            f"FROM movimentacoes mv WHERE {filtro_periodo} GROUP BY dia",
            (inicio.isoformat(),),
        ).fetchall()
        por_setor = conn.execute(
            "SELECT mv.setor, COUNT(*) AS saidas FROM movimentacoes mv "
            f"WHERE mv.tipo = 'saida' AND {filtro_periodo} "
            "GROUP BY mv.setor ORDER BY saidas DESC, mv.setor",
            (inicio.isoformat(),),
        ).fetchall()
        # Aqui somar quantidade faz sentido: cada linha é um item só, com uma unidade só
        mais_retirados = conn.execute(
            "SELECT m.codigo, m.nome, m.unidade, SUM(mv.quantidade) AS quantidade "
            "FROM movimentacoes mv JOIN materiais m ON m.id = mv.material_id "
            f"WHERE mv.tipo = 'saida' AND mv.setor != ? AND {filtro_periodo} "
            "GROUP BY m.id ORDER BY quantidade DESC, m.nome LIMIT ?",
            (SETOR_DESCARTE, inicio.isoformat(), LIMITE_ITENS_PAINEL),
        ).fetchall()

    # Preenche os dias sem movimentação com zero, para o gráfico não "pular" datas
    contagens = {linha["dia"]: linha for linha in por_dia}
    dias_periodo = []
    for deslocamento in range(dias):
        dia = (inicio + timedelta(days=deslocamento)).isoformat()
        linha = contagens.get(dia)
        dias_periodo.append(
            {
                "dia": dia,
                "entradas": linha["entradas"] if linha else 0,
                "saidas": linha["saidas"] if linha else 0,
            }
        )

    return {
        "dias": dias,
        "inicio": inicio.isoformat(),
        "total_entradas": sum(dia["entradas"] for dia in dias_periodo),
        "total_saidas": sum(dia["saidas"] for dia in dias_periodo),
        "por_dia": dias_periodo,
        "por_setor": [dict(linha) for linha in por_setor],
        "mais_retirados": [dict(linha) for linha in mais_retirados],
    }


# ---------- Movimentações ----------

# Limite para a tela não travar quando o histórico crescer; paginação seria o próximo passo
LIMITE_HISTORICO = 200


@app.get("/movimentacoes")
def listar_movimentacoes(
    material_id: int | None = None,
    tipo: Literal["entrada", "saida"] | None = None,
    usuario: dict = Depends(usuario_logado),
):
    # LEFT JOIN em colaboradores porque movimentações antigas não têm responsável
    sql = (
        "SELECT mv.id, mv.data, mv.tipo, mv.quantidade, mv.validade, mv.setor, "
        "m.codigo, m.nome AS material, m.unidade, c.nome AS colaborador "
        "FROM movimentacoes mv "
        "JOIN materiais m ON m.id = mv.material_id "
        "LEFT JOIN colaboradores c ON c.id = mv.colaborador_id"
    )
    condicoes = []
    parametros = []
    # Admin audita tudo; os demais só veem o que eles mesmos registraram
    if usuario["perfil"] not in PERFIS_ADMIN:
        condicoes.append("mv.colaborador_id = ?")
        parametros.append(usuario["id"])
    if material_id is not None:
        condicoes.append("mv.material_id = ?")
        parametros.append(material_id)
    if tipo is not None:
        condicoes.append("mv.tipo = ?")
        parametros.append(tipo)
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY mv.data DESC, mv.id DESC LIMIT ?"
    parametros.append(LIMITE_HISTORICO)

    with conectar() as conn:
        linhas = conn.execute(sql, parametros).fetchall()
    return [dict(linha) for linha in linhas]


@app.post("/movimentacoes", status_code=201)
def registrar_movimentacao(mov: MovimentacaoEntrada, usuario: dict = Depends(usuario_logado)):
    with conectar() as conn:
        # Trava a escrita já no início para duas saídas simultâneas não deixarem o saldo negativo
        conn.execute("BEGIN IMMEDIATE")
        material = conn.execute(
            "SELECT categoria, unidade, ativo, controla_validade FROM materiais WHERE id = ?",
            (mov.material_id,),
        ).fetchone()
        if material is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        if not material["ativo"]:
            raise HTTPException(status_code=409, detail="Este item está desativado")

        # O responsável vem da sessão, e não do formulário, para ninguém registrar em nome de outro
        verificar_permissao(usuario, mov.tipo, material["categoria"])

        if mov.tipo == "entrada":
            if not material["controla_validade"]:
                # Item sem validade (pano, vassoura...): ignora data enviada por engano
                mov.validade = None
            elif not mov.validade:
                raise HTTPException(status_code=422, detail="Entrada exige a validade")

        if mov.tipo == "saida" and mov.setor != SETOR_DESCARTE:
            # Pelo FEFO, a saída consumiria as unidades vencidas como se fossem para um paciente
            vencidas = sum(
                item["quantidade"]
                for item in calcular_validades(conn, mov.material_id)
                if item["vencido"]
            )
            if vencidas > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Há {vencidas} {material['unidade']} vencido(s) deste item. "
                    f"Registre o descarte (setor {SETOR_DESCARTE}) antes de uma nova saída",
                )

        if mov.tipo == "saida":
            saldo = calcular_saldo(conn, mov.material_id)
            if mov.quantidade > saldo:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo insuficiente: disponível {saldo}, solicitado {mov.quantidade}",
                )

        cursor = conn.execute(
            "INSERT INTO movimentacoes "
            "(material_id, colaborador_id, tipo, quantidade, lote, validade, setor) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                mov.material_id,
                usuario["id"],
                mov.tipo,
                mov.quantidade,
                mov.lote,
                mov.validade.isoformat() if mov.validade else None,
                mov.setor,
            ),
        )
        novo_id = cursor.lastrowid
    return {"id": novo_id, "colaborador_id": usuario["id"], **mov.model_dump()}
