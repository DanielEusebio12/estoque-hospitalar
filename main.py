# from fastapi import FastAPI

# app = FastAPI()

# @app.get("/")
# def raiz():
#     return {"mensagem": "Estoque funcionando"}
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

import auth
from auth import PERFIS_ADMIN, exigir_admin, usuario_autenticado, usuario_logado
from database import conectar, criar_tabelas

# Caminho a partir deste arquivo, para funcionar de qualquer pasta onde o servidor for iniciado
PASTA_FRONTEND = Path(__file__).parent / "frontend"

app = FastAPI(title="Controle de estoque hospitalar")
app.mount("/static", StaticFiles(directory=PASTA_FRONTEND), name="static")
app.include_router(auth.router)

criar_tabelas()
auth.criar_super_admin_inicial()


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


class MaterialEntrada(BaseModel):
    nome: str = Field(min_length=2)
    categoria: Categoria
    unidade: str = Field(min_length=1)
    estoque_minimo: int = Field(default=0, ge=0)


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


class AcessoEntrada(BaseModel):
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
        # Entrada precisa da validade para controle de vencimento; saída precisa do setor de destino
        if self.tipo == "entrada" and not self.validade:
            raise ValueError("Entrada exige a validade")
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


def calcular_saldo(conn, material_id: int) -> int:
    linha = conn.execute(
        f"SELECT {SQL_SALDO} FROM movimentacoes mv WHERE mv.material_id = ?",
        (material_id,),
    ).fetchone()
    return linha[0]


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
                "INSERT INTO materiais (nome, categoria, unidade, estoque_minimo) "
                "VALUES (?, ?, ?, ?)",
                (material.nome, material.categoria, material.unidade, material.estoque_minimo),
            )
            novo_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Já existe um material com esse nome")
    return {"id": novo_id, **material.model_dump()}


@app.get("/materiais")
def listar_materiais(busca: str | None = None, usuario: dict = Depends(usuario_logado)):
    sql = SQL_MATERIAIS_COM_SALDO
    parametros = []
    if busca:
        sql += " WHERE m.nome LIKE ?"
        parametros.append(f"%{busca}%")
    sql += " GROUP BY m.id ORDER BY m.nome"
    with conectar() as conn:
        linhas = conn.execute(sql, parametros).fetchall()
    return [dict(linha) for linha in linhas]


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


@app.get("/alertas/estoque-baixo")
def alertas_estoque_baixo(usuario: dict = Depends(usuario_logado)):
    # HAVING porque o saldo só existe depois do agrupamento
    sql = SQL_MATERIAIS_COM_SALDO + " GROUP BY m.id HAVING saldo < m.estoque_minimo ORDER BY m.nome"
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
def alterar_acesso(colaborador_id: int, dados: AcessoEntrada, gestor: dict = Depends(exigir_admin)):
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
        "m.nome AS material, m.unidade, c.nome AS colaborador "
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
            "SELECT categoria FROM materiais WHERE id = ?", (mov.material_id,)
        ).fetchone()
        if material is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        # O responsável vem da sessão, e não do formulário, para ninguém registrar em nome de outro
        verificar_permissao(usuario, mov.tipo, material["categoria"])

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
