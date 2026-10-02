# from fastapi import FastAPI

# app = FastAPI()

# @app.get("/")
# def raiz():
#     return {"mensagem": "Estoque funcionando"}
import sqlite3
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from database import conectar, criar_tabelas

app = FastAPI(title="Controle de estoque hospitalar")

criar_tabelas()


class MaterialEntrada(BaseModel):
    nome: str = Field(min_length=2)
    categoria: str = Field(min_length=2)
    unidade: str = Field(min_length=1)
    estoque_minimo: int = Field(default=0, ge=0)


class MovimentacaoEntrada(BaseModel):
    material_id: int
    tipo: Literal["entrada", "saida"]
    quantidade: int = Field(gt=0)
    lote: str | None = None
    validade: date | None = None
    setor: str | None = None

    @model_validator(mode="after")
    def validar_campos_por_tipo(self):
        # Entrada precisa de lote/validade para rastreio; saída precisa do setor de destino
        if self.tipo == "entrada" and (not self.lote or not self.validade):
            raise ValueError("Entrada exige lote e validade")
        if self.tipo == "saida" and not self.setor:
            raise ValueError("Saída exige o setor de destino")
        return self


def calcular_saldo(conn, material_id: int) -> int:
    linha = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'entrada' THEN quantidade ELSE -quantidade END), 0) "
        "FROM movimentacoes WHERE material_id = ?",
        (material_id,),
    ).fetchone()
    return linha[0]


@app.get("/")
def raiz():
    return {"mensagem": "Estoque funcionando"}


@app.post("/materiais", status_code=201)
def criar_material(material: MaterialEntrada):
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
def listar_materiais(busca: str | None = None):
    sql = "SELECT * FROM materiais"
    parametros = []
    if busca:
        sql += " WHERE nome LIKE ?"
        parametros.append(f"%{busca}%")
    sql += " ORDER BY nome"
    with conectar() as conn:
        linhas = conn.execute(sql, parametros).fetchall()
    return [dict(linha) for linha in linhas]


@app.get("/materiais/{material_id}")
def buscar_material(material_id: int):
    with conectar() as conn:
        linha = conn.execute(
            "SELECT * FROM materiais WHERE id = ?", (material_id,)
        ).fetchone()
    if linha is None:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    return dict(linha)


@app.post("/movimentacoes", status_code=201)
def registrar_movimentacao(mov: MovimentacaoEntrada):
    with conectar() as conn:
        # Trava a escrita já no início para duas saídas simultâneas não deixarem o saldo negativo
        conn.execute("BEGIN IMMEDIATE")
        existe = conn.execute(
            "SELECT 1 FROM materiais WHERE id = ?", (mov.material_id,)
        ).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        if mov.tipo == "saida":
            saldo = calcular_saldo(conn, mov.material_id)
            if mov.quantidade > saldo:
                raise HTTPException(
                    status_code=409,
                    detail=f"Saldo insuficiente: disponível {saldo}, solicitado {mov.quantidade}",
                )

        cursor = conn.execute(
            "INSERT INTO movimentacoes (material_id, tipo, quantidade, lote, validade, setor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                mov.material_id,
                mov.tipo,
                mov.quantidade,
                mov.lote,
                mov.validade.isoformat() if mov.validade else None,
                mov.setor,
            ),
        )
        novo_id = cursor.lastrowid
    return {"id": novo_id, **mov.model_dump()}