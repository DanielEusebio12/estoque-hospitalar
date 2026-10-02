# from fastapi import FastAPI

# app = FastAPI()

# @app.get("/")
# def raiz():
#     return {"mensagem": "Estoque funcionando"}
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from database import conectar, criar_tabelas

app = FastAPI(title="Controle de estoque hospitalar")

criar_tabelas()


class MaterialEntrada(BaseModel):
    nome: str = Field(min_length=2)
    categoria: str = Field(min_length=2)
    unidade: str = Field(min_length=1)
    estoque_minimo: int = Field(default=0, ge=0)


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