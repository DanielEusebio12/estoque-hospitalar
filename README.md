# Estoque da Farmácia Hospitalar

Sistema web para controlar o estoque da farmácia de um hospital: entrada e saída de medicamentos e materiais, saldo em tempo real, alertas de estoque baixo e de vencimento, controle de acesso por cargo e rastreabilidade de quem retirou cada item.

Feito com **Python + FastAPI + SQLite** no back-end e **HTML, CSS e JavaScript puro** no front-end, sem frameworks nem bibliotecas de gráficos.

## Funcionalidades

- **Entrada e saída de itens**: busca pelo código (pensada para leitor de código de barras) ou pela lista de itens, com validade na entrada e setor de destino na saída.
- **Saldo sempre calculado** a partir das movimentações; nunca fica um número solto guardado no banco.
- **Controle de validade (FEFO)**: o sistema mostra o que sobrou de cada validade e a ordem de retirada (primeiro o que vence primeiro).
- **Alertas** de estoque abaixo do mínimo e de itens vencidos ou que vencem nos próximos 30 dias.
- **Bloqueio de vencidos**: se um item tem unidades vencidas, só o descarte é liberado até elas saírem do estoque.
- **Login com perfis e cargos**: cada pessoa só faz o que o cargo permite (ex.: auxiliar de limpeza não retira medicamento).
- **Histórico** de todas as movimentações com o responsável, que vem do login e não de um campo do formulário.
- **Painel com gráficos**: movimentações por dia, retiradas por setor e itens mais retirados, com filtro de período.
- **Gestão de itens e colaboradores** pelos administradores: editar, desativar, bloquear acesso e redefinir senha.

## Como rodar

Pré-requisito: Python 3.12 ou mais recente.

```bash
git clone https://github.com/DanielEusebio12/estoque-hospitalar.git
cd estoque-hospitalar

python -m venv .venv
source .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn main:app --reload
```

Abra **http://localhost:8000**. O banco (`estoque.db`) é criado automaticamente na primeira execução.

### Primeiro acesso

| Usuário | Senha |
|---|---|
| `daniel.eusebio` | `Mudar@123` |

É o super admin criado na instalação. No primeiro login o sistema obriga a trocar a senha. Todo colaborador novo recebe essa mesma senha padrão, também com troca obrigatória.

A documentação interativa da API fica em **http://localhost:8000/docs**.

## Versão publicada (Render)

O arquivo [`render.yaml`](render.yaml) descreve o site de demonstração no [Render](https://render.com). Ele usa estas variáveis de ambiente:

| Variável | Para que serve |
|---|---|
| `SENHA_ADMIN_INICIAL` | Senha do `daniel.eusebio` (e dos colaboradores de exemplo). No site publicado substitui a senha padrão, que é pública neste README |
| `DADOS_DEMO=1` | Preenche um banco vazio com itens, colaboradores e 30 dias de movimentações, seguindo as mesmas regras da API |
| `COOKIE_SEGURO=1` | Cookie de sessão só por HTTPS |
| `ESTOQUE_BANCO` | Caminho do arquivo do banco (padrão: `estoque.db`) |

No plano gratuito o disco é apagado a cada reinício, então o site volta sempre aos dados de exemplo. Colaboradores de exemplo: `humberto.amigo` (admin, farmacêutico), `beatriz.rocha` (farmacêutica), `ana.lima` (enfermeira), `carlos.souza` (técnico de enfermagem) e `joana.pereira` (auxiliar de limpeza).

## Perfis e permissões

| Perfil | O que pode |
|---|---|
| **Super admin** | Tudo, inclusive criar, promover e bloquear administradores |
| **Admin** | Cadastrar e corrigir itens, gerenciar colaboradores comuns, ver o painel |
| **Comum** | Registrar movimentações conforme o cargo e ver o próprio histórico |

| Cargo | Entrada | Saída permitida |
|---|---|---|
| Farmacêutico | ✅ | todas as categorias |
| Enfermeiro / Técnico de enfermagem | ❌ | medicamento, material hospitalar, soro e solução, antisséptico |
| Auxiliar de limpeza | ❌ | material de limpeza |

A tela esconde o que a pessoa não pode usar, mas quem garante a regra é a API: uma chamada direta também é recusada.

## Decisões técnicas

**Saldo calculado, não armazenado.** O saldo é sempre a soma das entradas menos as saídas da tabela `movimentacoes`. Assim ele nunca fica fora de sincronia com o histórico, e toda alteração de estoque deixa um registro de quem fez e quando.

**FEFO calculado a partir do histórico.** Em vez de uma tabela de lotes, o sistema percorre as movimentações em ordem e supõe que cada saída levou o que vencia primeiro entre o que já estava em estoque naquele momento (*First Expired, First Out*, a regra padrão de farmácia hospitalar). A tela de saída mostra essa ordem, para a prática bater com o cálculo.

**Excluir x desativar.** Um item que já teve movimentação não pode ser excluído, só desativado: apagá-lo apagaria a prova de quem retirou o quê. Excluir só vale para cadastro feito por engano. Pelo mesmo motivo, a unidade de um item não muda depois que ele foi movimentado.

**Segurança do login.**
- Senhas guardadas com `scrypt` e sal aleatório (biblioteca padrão do Python).
- Sessão em cookie `HttpOnly` e `SameSite=Strict`; o banco guarda só o hash do token.
- Mesma mensagem para usuário inexistente e senha errada, para não revelar quem tem cadastro.
- Bloquear um colaborador encerra as sessões dele na hora.

**Concorrência.** O registro de movimentação abre a transação com `BEGIN IMMEDIATE`, para duas saídas ao mesmo tempo não deixarem o saldo negativo.

**SQL sempre com parâmetros** (`?`), nunca montado com texto vindo do usuário.

**Gráficos sem biblioteca.** Feitos em SVG e HTML com JavaScript puro. As cores das séries foram validadas para daltonismo, cada gráfico tem a tabela equivalente ("Ver em tabela") e os valores também podem ser lidos pelo teclado. Os gráficos que misturam itens diferentes contam registros, não quantidades: somar comprimidos com caixas não teria sentido.

## Testes

```bash
pytest
```

São 40 testes cobrindo autenticação, permissões, regras de estoque, painel, cálculo de validades e a configuração do site publicado. Cada teste roda num banco temporário próprio, então o `estoque.db` nunca é alterado.

Um deles é um teste de regressão: uma primeira versão do cálculo de validades descontava as saídas de lotes que ainda nem tinham entrado, e o alerta de vencimento deixava de aparecer. O erro foi encontrado testando com dados reais, corrigido, e o teste garante que ele não volte.

## Estrutura

```
main.py           rotas da API e regras de negócio
auth.py           login, sessões, senhas e perfis
database.py       conexão com o SQLite, criação e atualização das tabelas
frontend/
  index.html      tela principal (abas)
  app.js          lógica da tela
  graficos.js     gráficos do painel
  estilo.css      visual
  login.html, trocar-senha.html (+ .js)
tests/            testes automatizados (pytest)
```

## Limitações e próximos passos

- **SQLite** atende bem um projeto deste tamanho; com muitos acessos simultâneos o natural seria migrar para PostgreSQL. As consultas usam SQL padrão, então a troca é pequena.
- O cookie de sessão ainda não usa `Secure` (exige HTTPS em produção) e não há limite de tentativas de login.
- O controle por lote assume FEFO; registrar a validade exata em cada saída deixaria o número exato mesmo quando alguém não segue a ordem.
- O histórico mostra as 200 movimentações mais recentes; paginação seria o próximo passo.
