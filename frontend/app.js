// Chama a API e transforma respostas de erro em exceção com a mensagem do servidor
async function chamarApi(caminho, opcoes = {}) {
    const resposta = await fetch(caminho, {
        headers: { "Content-Type": "application/json" },
        ...opcoes,
    });
    // Sessão expirou ou o acesso foi bloqueado: volta para o login
    if (resposta.status === 401) {
        window.location.href = "/login";
        throw new Error("Sessão encerrada");
    }
    // 204 (exclusão) responde sem corpo
    if (resposta.status === 204) {
        return null;
    }
    const dados = await resposta.json();
    if (!resposta.ok) {
        throw new Error(traduzirErro(dados.detail));
    }
    return dados;
}

const NOMES_PERFIL = { super_admin: "Super admin", admin: "Administrador", comum: "Comum" };
let usuarioAtual = null;

function ehAdmin() {
    return usuarioAtual.perfil === "admin" || usuarioAtual.perfil === "super_admin";
}

// 409/404 vêm como texto; 422 (Pydantic) vem como lista de erros
function traduzirErro(detalhe) {
    if (Array.isArray(detalhe)) {
        return detalhe.map((erro) => erro.msg.replace("Value error, ", "")).join("; ");
    }
    return detalhe;
}

let temporizadorMensagem;

function mostrarMensagem(texto, tipo) {
    const caixa = document.getElementById("mensagem");
    caixa.textContent = texto;
    caixa.className = "mensagem " + tipo;
    caixa.hidden = false;
    // Reinicia o tempo se chegar outra mensagem antes da anterior sumir
    clearTimeout(temporizadorMensagem);
    temporizadorMensagem = setTimeout(() => (caixa.hidden = true), 4000);
}

// Cria elementos com textContent (e não innerHTML) para um nome com HTML não virar código na página
function criarElemento(tag, texto, classe) {
    const elemento = document.createElement(tag);
    if (texto !== undefined) {
        elemento.textContent = texto;
    }
    if (classe) {
        elemento.className = classe;
    }
    return elemento;
}

function criarEtiqueta(material) {
    if (!material.ativo) {
        return criarElemento("span", "Desativado", "etiqueta neutra");
    }
    if (material.saldo === 0) {
        return criarElemento("span", "Sem estoque", "etiqueta perigo");
    }
    if (material.saldo < material.estoque_minimo) {
        return criarElemento("span", "Abaixo do mínimo", "etiqueta alerta");
    }
    return criarElemento("span", "Normal", "etiqueta ok");
}

async function alterarAtivoMaterial(material) {
    const ativar = !material.ativo;
    if (!ativar && !confirm(`Desativar "${material.nome}"? Ele some da entrada e saída, mas o histórico continua.`)) {
        return;
    }
    try {
        await chamarApi(`/materiais/${material.id}/ativo`, {
            method: "PATCH",
            body: JSON.stringify({ ativo: ativar }),
        });
        mostrarMensagem(`"${material.nome}" ${ativar ? "reativado" : "desativado"}.`, "sucesso");
        await atualizarTela();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
}

async function excluirMaterial(material) {
    if (!confirm(`Excluir "${material.nome}" definitivamente?`)) {
        return;
    }
    try {
        await chamarApi(`/materiais/${material.id}`, { method: "DELETE" });
        mostrarMensagem(`"${material.nome}" excluído.`, "sucesso");
        await atualizarTela();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
}

function criarAcoesMaterial(material) {
    const acoes = document.createElement("div");
    acoes.className = "acoes tabela";
    acoes.appendChild(criarBotao("Editar", "botao-secundario", () => iniciarEdicaoMaterial(material)));
    acoes.appendChild(
        criarBotao(material.ativo ? "Desativar" : "Reativar", "botao-secundario", () => alterarAtivoMaterial(material)),
    );
    acoes.appendChild(criarBotao("Excluir", "botao-secundario perigo", () => excluirMaterial(material)));
    return acoes;
}

async function carregarMateriais() {
    const parametros = new URLSearchParams();
    const busca = document.getElementById("busca").value.trim();
    if (busca) {
        parametros.set("busca", busca);
    }
    // Admin precisa ver os desativados para poder reativar
    if (ehAdmin()) {
        parametros.set("incluir_inativos", "true");
    }
    const materiais = await chamarApi("/materiais?" + parametros);

    const tabela = document.getElementById("tabela-materiais");
    tabela.replaceChildren();
    if (materiais.length === 0) {
        const celula = criarElemento("td", busca ? "Nenhum item encontrado." : "Nenhum item cadastrado ainda.", "vazio");
        celula.colSpan = ehAdmin() ? 7 : 6;
        const linha = document.createElement("tr");
        linha.appendChild(celula);
        tabela.appendChild(linha);
        return;
    }
    for (const material of materiais) {
        const linha = document.createElement("tr");
        linha.appendChild(criarElemento("td", material.nome));
        linha.appendChild(criarElemento("td", material.categoria));
        linha.appendChild(criarElemento("td", material.unidade));
        linha.appendChild(criarElemento("td", material.estoque_minimo, "numero"));
        linha.appendChild(criarElemento("td", material.saldo, "numero"));
        const celulaSituacao = document.createElement("td");
        celulaSituacao.appendChild(criarEtiqueta(material));
        linha.appendChild(celulaSituacao);
        if (ehAdmin()) {
            const celulaAcoes = document.createElement("td");
            celulaAcoes.appendChild(criarAcoesMaterial(material));
            linha.appendChild(celulaAcoes);
        }
        if (!material.ativo) {
            linha.className = "inativo";
        }
        tabela.appendChild(linha);
    }
}

function mostrarIndicador(id, valor) {
    const elemento = document.getElementById(id);
    elemento.textContent = valor;
    elemento.classList.toggle("tem-valor", valor > 0);
}

// Guardada para o painel do item não precisar buscar na API a cada troca do select
let materiaisAtivos = [];

// Usa a lista completa, sem o filtro da busca, para o select e os indicadores
async function carregarListaCompleta() {
    const materiais = await chamarApi("/materiais");
    materiaisAtivos = materiais;
    const select = document.getElementById("select-material");
    const selecionado = select.value;
    select.replaceChildren();
    for (const material of materiais) {
        const opcao = document.createElement("option");
        opcao.value = material.id;
        opcao.textContent = `${material.nome} (saldo: ${material.saldo} ${material.unidade})`;
        select.appendChild(opcao);
    }
    select.value = selecionado || select.value;

    const filtro = document.getElementById("filtro-material");
    const filtroSelecionado = filtro.value;
    filtro.replaceChildren(criarElemento("option", "Todos os itens"));
    filtro.firstChild.value = "";
    for (const material of materiais) {
        const opcao = criarElemento("option", material.nome);
        opcao.value = material.id;
        filtro.appendChild(opcao);
    }
    filtro.value = filtroSelecionado;

    mostrarIndicador("total-materiais", materiais.length);
    mostrarIndicador("total-zerados", materiais.filter((material) => material.saldo === 0).length);
}

async function carregarAlertas() {
    const alertas = await chamarApi("/alertas/estoque-baixo");
    // O total vem da API para a regra de "abaixo do mínimo" ficar só no servidor
    mostrarIndicador("total-alertas", alertas.length);
    const contador = document.getElementById("contador-alertas");
    contador.textContent = alertas.length;
    contador.hidden = alertas.length === 0;

    const lista = document.getElementById("lista-alertas");
    lista.replaceChildren();
    if (alertas.length === 0) {
        lista.appendChild(criarElemento("li", "✓ Nenhum item abaixo do estoque mínimo", "sem-alerta"));
        return;
    }
    for (const alerta of alertas) {
        const item = document.createElement("li");
        const textos = document.createElement("div");
        textos.appendChild(criarElemento("span", alerta.nome, "alerta-nome"));
        textos.appendChild(
            criarElemento("span", `Saldo ${alerta.saldo} de mínimo ${alerta.estoque_minimo}`, "alerta-detalhe"),
        );
        item.appendChild(textos);
        item.appendChild(
            criarElemento("span", `Repor ${alerta.quantidade_para_repor} ${alerta.unidade}`, "etiqueta alerta"),
        );
        lista.appendChild(item);
    }
}

// Espelha a regra da API (verificar_pode_gerenciar) só para não mostrar botões que dariam erro
function podeGerenciar(colaborador) {
    if (colaborador.id === usuarioAtual.id || colaborador.perfil === "super_admin") {
        return false;
    }
    return colaborador.perfil === "comum" || usuarioAtual.perfil === "super_admin";
}

function criarBotao(texto, classe, aoClicar) {
    const botao = criarElemento("button", texto, classe);
    botao.type = "button";
    botao.addEventListener("click", aoClicar);
    return botao;
}

async function alterarAcesso(colaborador) {
    const liberar = !colaborador.ativo;
    try {
        await chamarApi(`/colaboradores/${colaborador.id}/acesso`, {
            method: "PATCH",
            body: JSON.stringify({ ativo: liberar }),
        });
        mostrarMensagem(`Acesso de ${colaborador.nome} ${liberar ? "liberado" : "bloqueado"}.`, "sucesso");
        await carregarColaboradores();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
}

async function resetarSenha(colaborador) {
    try {
        await chamarApi(`/colaboradores/${colaborador.id}/resetar-senha`, { method: "POST" });
        mostrarMensagem(`Senha de ${colaborador.nome} voltou para a padrão.`, "sucesso");
        await carregarColaboradores();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
}

async function carregarColaboradores() {
    const colaboradores = await chamarApi("/colaboradores");
    const lista = document.getElementById("lista-colaboradores");
    lista.replaceChildren();
    for (const colaborador of colaboradores) {
        const item = document.createElement("li");
        const textos = document.createElement("div");
        textos.appendChild(criarElemento("span", colaborador.nome, "alerta-nome"));
        const login = colaborador.usuario ? colaborador.usuario : "sem login";
        textos.appendChild(
            criarElemento("span", `${login} · ${colaborador.cargo} · Matrícula ${colaborador.matricula}`, "alerta-detalhe"),
        );
        item.appendChild(textos);

        const acoes = document.createElement("div");
        acoes.className = "acoes";
        acoes.appendChild(criarElemento("span", NOMES_PERFIL[colaborador.perfil], "etiqueta neutra"));
        if (!colaborador.ativo) {
            acoes.appendChild(criarElemento("span", "Bloqueado", "etiqueta perigo"));
        } else if (colaborador.trocar_senha) {
            acoes.appendChild(criarElemento("span", "Senha padrão", "etiqueta alerta"));
        }
        if (podeGerenciar(colaborador)) {
            acoes.appendChild(criarBotao("Editar", "botao-secundario", () => iniciarEdicao(colaborador)));
        }
        // Bloquear e resetar só fazem sentido para quem já tem login
        if (podeGerenciar(colaborador) && colaborador.usuario) {
            acoes.appendChild(
                criarBotao(
                    colaborador.ativo ? "Bloquear" : "Liberar",
                    colaborador.ativo ? "botao-secundario perigo" : "botao-secundario",
                    () => alterarAcesso(colaborador),
                ),
            );
            acoes.appendChild(criarBotao("Resetar senha", "botao-secundario", () => resetarSenha(colaborador)));
        }
        item.appendChild(acoes);
        lista.appendChild(item);
    }
}

// O banco guarda "2026-10-02 18:30:12"; corta o texto em vez de usar Date para não mexer no fuso
function formatarData(texto) {
    const [data, hora] = texto.split(" ");
    const [ano, mes, dia] = data.split("-");
    return `${dia}/${mes}/${ano} ${hora.slice(0, 5)}`;
}

async function carregarHistorico() {
    const parametros = new URLSearchParams();
    const materialId = document.getElementById("filtro-material").value;
    const tipo = document.getElementById("filtro-tipo").value;
    if (materialId) {
        parametros.set("material_id", materialId);
    }
    if (tipo) {
        parametros.set("tipo", tipo);
    }
    const movimentacoes = await chamarApi("/movimentacoes?" + parametros);

    const tabela = document.getElementById("tabela-historico");
    tabela.replaceChildren();
    if (movimentacoes.length === 0) {
        const celula = criarElemento("td", "Nenhuma movimentação encontrada.", "vazio");
        celula.colSpan = 6;
        const linha = document.createElement("tr");
        linha.appendChild(celula);
        tabela.appendChild(linha);
        return;
    }
    for (const mov of movimentacoes) {
        const linha = document.createElement("tr");
        linha.appendChild(criarElemento("td", formatarData(mov.data)));

        const celulaTipo = document.createElement("td");
        celulaTipo.appendChild(
            mov.tipo === "entrada"
                ? criarElemento("span", "Entrada", "etiqueta ok")
                : criarElemento("span", "Saída", "etiqueta alerta"),
        );
        linha.appendChild(celulaTipo);

        linha.appendChild(criarElemento("td", mov.material));
        linha.appendChild(criarElemento("td", `${mov.tipo === "entrada" ? "+" : "−"}${mov.quantidade} ${mov.unidade}`, "numero"));
        const destino = mov.tipo === "entrada"
            ? (mov.validade ? "Validade " + mov.validade.split("-").reverse().join("/") : "—")
            : (mov.setor ?? "—");
        linha.appendChild(criarElemento("td", destino));
        // Movimentações de antes do login não têm responsável registrado
        linha.appendChild(criarElemento("td", mov.colaborador ?? "Não registrado"));
        tabela.appendChild(linha);
    }
}

// Barra cheia = o dobro do mínimo, então a marca do mínimo fica sempre no meio
function calcularNivel(material) {
    if (material.estoque_minimo === 0) {
        return material.saldo > 0 ? 100 : 0;
    }
    return Math.min(100, (material.saldo / (material.estoque_minimo * 2)) * 100);
}

async function atualizarPainelItem() {
    const id = Number(document.getElementById("select-material").value);
    const material = materiaisAtivos.find((item) => item.id === id);
    document.getElementById("painel-vazio").hidden = Boolean(material);
    document.getElementById("painel-conteudo").hidden = !material;
    if (!material) {
        return;
    }

    document.getElementById("painel-nome").textContent = material.nome;
    document.getElementById("painel-categoria").textContent = `${material.categoria} · ${material.unidade}`;
    document.getElementById("painel-saldo").textContent = material.saldo;
    document.getElementById("painel-minimo").textContent = material.estoque_minimo;
    document.getElementById("painel-situacao").replaceChildren(criarEtiqueta(material));

    const barra = document.getElementById("painel-barra");
    barra.style.width = calcularNivel(material) + "%";
    barra.className = "barra-preenchida";
    if (material.saldo === 0) {
        barra.classList.add("perigo");
    } else if (material.saldo < material.estoque_minimo) {
        barra.classList.add("alerta");
    }

    const movimentacoes = await chamarApi(`/movimentacoes?material_id=${material.id}`);
    const lista = document.getElementById("painel-ultimas");
    lista.replaceChildren();
    if (movimentacoes.length === 0) {
        lista.appendChild(criarElemento("li", "Nenhuma movimentação ainda.", "vazio"));
        return;
    }
    for (const mov of movimentacoes.slice(0, 5)) {
        const item = document.createElement("li");
        const entrada = mov.tipo === "entrada";
        item.appendChild(criarElemento("span", entrada ? "↓" : "↑", `seta-movimento ${mov.tipo}`));

        const texto = document.createElement("div");
        texto.className = "movimento-texto";
        texto.appendChild(criarElemento("span", entrada ? "Entrada" : `Saída · ${mov.setor ?? "—"}`));
        texto.appendChild(criarElemento("small", `${formatarData(mov.data)} · ${mov.colaborador ?? "Não registrado"}`));
        item.appendChild(texto);

        item.appendChild(
            criarElemento("span", `${entrada ? "+" : "−"}${mov.quantidade}`, "movimento-quantidade"),
        );
        lista.appendChild(item);
    }
}

async function atualizarTela() {
    const carregamentos = [carregarMateriais(), carregarListaCompleta(), carregarAlertas(), carregarHistorico()];
    if (ehAdmin()) {
        carregamentos.push(carregarColaboradores());
    }
    try {
        await Promise.all(carregamentos);
        // Depois das listas, porque o painel usa o saldo que acabou de ser carregado
        await atualizarPainelItem();
    } catch (erro) {
        mostrarMensagem("Erro ao carregar dados: " + erro.message, "erro");
    }
}

// Mesmo esquema dos colaboradores: null quer dizer "cadastrando"
let materialEmEdicao = null;

function iniciarEdicaoMaterial(material) {
    materialEmEdicao = material;
    const form = document.getElementById("form-material");
    // Item antigo pode ter uma unidade fora da lista atual; adiciona a opção para não aparecer em branco
    const selectUnidade = form.elements.unidade;
    if (![...selectUnidade.options].some((opcao) => opcao.value === material.unidade)) {
        selectUnidade.appendChild(criarElemento("option", material.unidade));
    }
    for (const campo of ["nome", "categoria", "unidade", "estoque_minimo"]) {
        form.elements[campo].value = material[campo];
    }
    document.getElementById("material-em-edicao").textContent = material.nome;
    document.getElementById("aviso-edicao-material").hidden = false;
    document.getElementById("botao-salvar-material").textContent = "Salvar alterações";
    abrirAba(document.querySelector('[data-aba="aba-cadastro"]'));
    form.scrollIntoView({ behavior: "smooth", block: "center" });
}

function cancelarEdicaoMaterial() {
    materialEmEdicao = null;
    document.getElementById("form-material").reset();
    document.getElementById("aviso-edicao-material").hidden = true;
    document.getElementById("botao-salvar-material").textContent = "Cadastrar";
}

document.getElementById("cancelar-edicao-material").addEventListener("click", cancelarEdicaoMaterial);

document.getElementById("form-material").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const dados = Object.fromEntries(new FormData(evento.target));
    dados.estoque_minimo = Number(dados.estoque_minimo);
    const editando = materialEmEdicao !== null;
    try {
        const material = await chamarApi(
            editando ? `/materiais/${materialEmEdicao.id}` : "/materiais",
            { method: editando ? "PUT" : "POST", body: JSON.stringify(dados) },
        );
        mostrarMensagem(`"${material.nome}" ${editando ? "atualizado" : "cadastrado com sucesso"}.`, "sucesso");
        cancelarEdicaoMaterial();
        await atualizarTela();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
});

// O mesmo formulário serve para cadastrar e editar; null quer dizer "cadastrando"
let colaboradorEmEdicao = null;

function iniciarEdicao(colaborador) {
    colaboradorEmEdicao = colaborador;
    const form = document.getElementById("form-colaborador");
    for (const campo of ["nome", "matricula", "usuario", "cargo", "perfil"]) {
        form.elements[campo].value = colaborador[campo] ?? "";
    }
    document.getElementById("nome-em-edicao").textContent = colaborador.nome;
    document.getElementById("aviso-edicao").hidden = false;
    document.getElementById("botao-salvar-colaborador").textContent = "Salvar alterações";
    // A dica da senha padrão só vale para quem ainda vai ganhar login
    document.getElementById("dica-senha-padrao").hidden = Boolean(colaborador.usuario);
    form.scrollIntoView({ behavior: "smooth", block: "center" });
}

function cancelarEdicao() {
    colaboradorEmEdicao = null;
    document.getElementById("form-colaborador").reset();
    document.getElementById("aviso-edicao").hidden = true;
    document.getElementById("botao-salvar-colaborador").textContent = "Cadastrar colaborador";
    document.getElementById("dica-senha-padrao").hidden = false;
}

document.getElementById("cancelar-edicao").addEventListener("click", cancelarEdicao);

document.getElementById("form-colaborador").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const dados = Object.fromEntries(new FormData(evento.target));
    const editando = colaboradorEmEdicao !== null;
    try {
        const colaborador = await chamarApi(
            editando ? `/colaboradores/${colaboradorEmEdicao.id}` : "/colaboradores",
            { method: editando ? "PUT" : "POST", body: JSON.stringify(dados) },
        );
        mostrarMensagem(
            editando ? `Dados de ${colaborador.nome} atualizados.` : `Cadastro de ${colaborador.nome} (${colaborador.cargo}) concluído.`,
            "sucesso",
        );
        cancelarEdicao();
        await carregarColaboradores();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
});

document.getElementById("form-movimentacao").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const form = evento.target;
    const dados = Object.fromEntries(new FormData(form));
    dados.material_id = Number(dados.material_id);
    dados.quantidade = Number(dados.quantidade);
    // Envia só os campos do tipo escolhido; campo vazio vira null para o Pydantic validar
    if (dados.tipo === "entrada") {
        delete dados.setor;
    } else {
        delete dados.validade;
    }
    for (const campo in dados) {
        if (dados[campo] === "") {
            dados[campo] = null;
        }
    }
    try {
        await chamarApi("/movimentacoes", { method: "POST", body: JSON.stringify(dados) });
        mostrarMensagem(`${dados.tipo === "entrada" ? "Entrada" : "Saída"} registrada.`, "sucesso");
        form.querySelector("[name=quantidade]").value = "";
        await atualizarTela();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
});

// Cada botão de aba guarda em data-aba o id da seção que ele mostra
function abrirAba(botao) {
    document.querySelectorAll(".aba").forEach((outro) => {
        const ativo = outro === botao;
        outro.classList.toggle("ativa", ativo);
        document.getElementById(outro.dataset.aba).hidden = !ativo;
    });
    // Nas abas de consulta e gestão os alertas só ocupariam espaço
    document.querySelector(".alertas").hidden = botao.hasAttribute("data-sem-alertas");
}

document.querySelectorAll(".aba").forEach((botao) => {
    botao.addEventListener("click", () => abrirAba(botao));
});

// Mostra validade na entrada e setor na saída
function atualizarCamposPorTipo() {
    const ehEntrada = document.querySelector("input[name=tipo]:checked").value === "entrada";
    document.getElementById("campos-entrada").hidden = !ehEntrada;
    document.getElementById("campos-saida").hidden = ehEntrada;
}

document.querySelectorAll("input[name=tipo]").forEach((opcao) => {
    opcao.addEventListener("change", atualizarCamposPorTipo);
});
// O navegador pode restaurar "Saída" ao recarregar a página, então ajusta os campos já na abertura
atualizarCamposPorTipo();

document.getElementById("busca").addEventListener("input", () => {
    carregarMateriais().catch((erro) => mostrarMensagem(erro.message, "erro"));
});

document.getElementById("select-material").addEventListener("change", () => {
    atualizarPainelItem().catch((erro) => mostrarMensagem(erro.message, "erro"));
});

for (const id of ["filtro-material", "filtro-tipo"]) {
    document.getElementById(id).addEventListener("change", () => {
        carregarHistorico().catch((erro) => mostrarMensagem(erro.message, "erro"));
    });
}

document.getElementById("botao-sair").addEventListener("click", async () => {
    await fetch("/logout", { method: "POST" });
    window.location.href = "/login";
});

// Descobre quem está logado antes de montar a tela, porque o que aparece depende do perfil
async function iniciar() {
    usuarioAtual = await chamarApi("/eu");
    if (usuarioAtual.trocar_senha) {
        window.location.href = "/trocar-senha";
        return;
    }
    document.getElementById("usuario-nome").textContent = usuarioAtual.nome;
    document.getElementById("usuario-perfil").textContent =
        `${NOMES_PERFIL[usuarioAtual.perfil]} · ${usuarioAtual.cargo}`;
    // Iniciais do primeiro e do último nome: "Daniel Eusebio" vira "DE"
    const partesNome = usuarioAtual.nome.trim().split(/\s+/);
    document.getElementById("usuario-avatar").textContent =
        (partesNome[0][0] + (partesNome.length > 1 ? partesNome.at(-1)[0] : "")).toUpperCase();

    if (ehAdmin()) {
        document.querySelectorAll(".so-admin").forEach((elemento) => (elemento.hidden = false));
    }
    document.getElementById("aviso-historico").textContent = ehAdmin()
        ? "Todas as movimentações, das mais recentes para as mais antigas."
        : "Suas movimentações, das mais recentes para as mais antigas.";
    if (usuarioAtual.perfil === "super_admin") {
        const opcao = criarElemento("option", "Administrador");
        opcao.value = "admin";
        document.getElementById("select-perfil").appendChild(opcao);
    }
    await atualizarTela();
}

iniciar().catch((erro) => mostrarMensagem(erro.message, "erro"));
