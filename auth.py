import hashlib
import hmac
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from database import conectar

# Senha dada a todo usuário novo; a troca é obrigatória no primeiro acesso
SENHA_PADRAO = "Mudar@123"
NOME_COOKIE = "sessao"
# Um plantão de 12h sem precisar logar de novo
DURACAO_SESSAO_HORAS = 12

PERFIS_ADMIN = ("admin", "super_admin")

router = APIRouter()


def gerar_hash_senha(senha: str) -> str:
    # scrypt é lento de propósito, para dificultar testar milhões de senhas; o sal evita hashes iguais para senhas iguais
    sal = secrets.token_bytes(16)
    hash_senha = hashlib.scrypt(senha.encode(), salt=sal, n=2**14, r=8, p=1)
    return f"{sal.hex()}${hash_senha.hex()}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    sal_hex, hash_hex = senha_hash.split("$")
    calculado = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal_hex), n=2**14, r=8, p=1)
    # compare_digest leva o mesmo tempo acerte ou erre, para não dar pistas da senha
    return hmac.compare_digest(calculado.hex(), hash_hex)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dados_publicos(usuario) -> dict:
    # Nunca devolver o senha_hash para o navegador
    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "usuario": usuario["usuario"],
        "cargo": usuario["cargo"],
        "perfil": usuario["perfil"],
        "trocar_senha": bool(usuario["trocar_senha"]),
    }


def criar_super_admin_inicial():
    # Sem isso ninguém conseguiria entrar num banco novo para cadastrar os outros usuários
    with conectar() as conn:
        existe = conn.execute(
            "SELECT 1 FROM colaboradores WHERE perfil = 'super_admin'"
        ).fetchone()
        if existe:
            return
        conn.execute(
            "INSERT INTO colaboradores "
            "(nome, matricula, cargo, usuario, senha_hash, perfil, trocar_senha) "
            "VALUES (?, ?, ?, ?, ?, 'super_admin', 1)",
            ("Daniel Eusebio", "ADM-0001", "Administrador", "daniel.eusebio", gerar_hash_senha(SENHA_PADRAO)),
        )


def usuario_autenticado(sessao: str | None = Cookie(default=None)) -> dict:
    """Usuário da sessão, mesmo que ainda precise trocar a senha."""
    if not sessao:
        raise HTTPException(status_code=401, detail="Faça login para continuar")
    with conectar() as conn:
        linha = conn.execute(
            "SELECT c.* FROM sessoes s JOIN colaboradores c ON c.id = s.colaborador_id "
            "WHERE s.token_hash = ? AND s.expira_em > datetime('now') AND c.ativo = 1",
            (hash_token(sessao),),
        ).fetchone()
    if linha is None:
        raise HTTPException(status_code=401, detail="Sessão expirada, faça login novamente")
    return dict(linha)


def usuario_logado(usuario: dict = Depends(usuario_autenticado)) -> dict:
    """Usuário liberado para usar o sistema (já trocou a senha padrão)."""
    if usuario["trocar_senha"]:
        raise HTTPException(status_code=403, detail="Troque a senha padrão antes de continuar")
    return usuario


def exigir_admin(usuario: dict = Depends(usuario_logado)) -> dict:
    if usuario["perfil"] not in PERFIS_ADMIN:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return usuario


class LoginEntrada(BaseModel):
    usuario: str
    senha: str


class TrocaSenhaEntrada(BaseModel):
    senha_atual: str
    nova_senha: str = Field(min_length=8)


@router.post("/login")
def login(dados: LoginEntrada, response: Response):
    with conectar() as conn:
        usuario = conn.execute(
            "SELECT * FROM colaboradores WHERE usuario = ?", (dados.usuario.strip().lower(),)
        ).fetchone()
        # Mesma mensagem para usuário inexistente e senha errada, para não revelar quais usuários existem
        if usuario is None or not verificar_senha(dados.senha, usuario["senha_hash"]):
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
        if not usuario["ativo"]:
            raise HTTPException(status_code=403, detail="Acesso bloqueado. Procure um administrador")

        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessoes (token_hash, colaborador_id, expira_em) "
            "VALUES (?, ?, datetime('now', ?))",
            (hash_token(token), usuario["id"], f"+{DURACAO_SESSAO_HORAS} hours"),
        )

    # httponly: o JavaScript não lê o cookie; samesite: outro site não consegue usá-lo
    response.set_cookie(
        NOME_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        max_age=DURACAO_SESSAO_HORAS * 3600,
    )
    return dados_publicos(usuario)


@router.post("/logout")
def logout(response: Response, sessao: str | None = Cookie(default=None)):
    if sessao:
        with conectar() as conn:
            conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (hash_token(sessao),))
    response.delete_cookie(NOME_COOKIE)
    return {"mensagem": "Sessão encerrada"}


@router.get("/eu")
def eu(usuario: dict = Depends(usuario_autenticado)):
    return dados_publicos(usuario)


@router.post("/trocar-senha")
def trocar_senha(dados: TrocaSenhaEntrada, usuario: dict = Depends(usuario_autenticado)):
    if not verificar_senha(dados.senha_atual, usuario["senha_hash"]):
        raise HTTPException(status_code=422, detail="Senha atual incorreta")
    if dados.nova_senha in (SENHA_PADRAO, dados.senha_atual):
        raise HTTPException(
            status_code=422, detail="A nova senha precisa ser diferente da atual e da senha padrão"
        )
    with conectar() as conn:
        conn.execute(
            "UPDATE colaboradores SET senha_hash = ?, trocar_senha = 0 WHERE id = ?",
            (gerar_hash_senha(dados.nova_senha), usuario["id"]),
        )
    return {"mensagem": "Senha alterada"}
