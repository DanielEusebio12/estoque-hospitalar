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

// Ids dos itens que aparecem no alerta de vencimento (preenchido por carregarVencimentos)
let idsComVencimento = new Set();

// Mesmas regras dos cards de resumo, para o número do card bater com a quantidade de linhas
function combinaComSituacao(material, situacao) {
    switch (situacao) {
        case "abaixo":
            return material.ativo && material.saldo < material.estoque_minimo;
        case "zerado":
            return material.ativo && material.saldo === 0;
        case "vencimento":
            return idsComVencimento.has(material.id);
        case "desativado":
            return !material.ativo;
        default:
            return true;
    }
}

// Data da validade que vence primeiro; embaixo, o prazo quando ele merece atenção
function criarCelulaValidade(material) {
    const celula = document.createElement("td");
    if (!material.controla_validade) {
        celula.appendChild(criarElemento("span", "Sem validade", "texto-suave"));
        return celula;
    }
    if (!material.proxima_validade) {
        celula.appendChild(criarElemento("span", "—", "texto-suave"));
        return celula;
    }
    celula.appendChild(criarElemento("span", formatarValidade(material.proxima_validade)));
    const dias = material.dias_para_vencer;
    if (dias < 0) {
        celula.appendChild(criarElemento("small", `vencido há ${-dias} dia${dias === -1 ? "" : "s"}`, "prazo vencido"));
    } else if (dias <= DIAS_ALERTA_VENCIMENTO) {
        const texto = dias === 0 ? "vence hoje" : `vence em ${dias} dia${dias === 1 ? "" : "s"}`;
        celula.appendChild(criarElemento("small", texto, "prazo perto"));
    }
    return celula;
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
    const situacao = document.getElementById("filtro-situacao").value;
    const materiais = (await chamarApi("/materiais?" + parametros)).filter((material) =>
        combinaComSituacao(material, situacao),
    );

    const tabela = document.getElementById("tabela-materiais");
    tabela.replaceChildren();
    if (materiais.length === 0) {
        let mensagem = "Nenhum item cadastrado ainda.";
        if (situacao) {
            mensagem = "Nenhum item nesta situação.";
        } else if (busca) {
            mensagem = "Nenhum item encontrado.";
        }
        const celula = criarElemento("td", mensagem, "vazio");
        celula.colSpan = ehAdmin() ? 9 : 8;
        const linha = document.createElement("tr");
        linha.appendChild(celula);
        tabela.appendChild(linha);
        return;
    }
    for (const material of materiais) {
        const linha = document.createElement("tr");
        linha.appendChild(criarElemento("td", material.codigo ?? "—", "codigo"));
        linha.appendChild(criarElemento("td", material.nome));
        linha.appendChild(criarElemento("td", material.categoria));
        linha.appendChild(criarElemento("td", material.unidade));
        linha.appendChild(criarElemento("td", material.estoque_minimo, "numero"));
        linha.appendChild(criarElemento("td", material.saldo, "numero"));
        linha.appendChild(criarCelulaValidade(material));
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

// Guardada para a busca por código e o painel não precisarem chamar a API a cada tecla
let materiaisAtivos = [];

// Código exato, digitado ou lido pelo leitor de código de barras
function encontrarPorCodigo(texto) {
    const codigo = texto.trim().toUpperCase();
    return codigo ? materiaisAtivos.find((item) => item.codigo === codigo) ?? null : null;
}

function itemSelecionado() {
    const id = Number(document.getElementById("select-material").value);
    return materiaisAtivos.find((item) => item.id === id);
}

// Chamado quando o item muda, venha ele do campo de código ou da caixa
function aoMudarItem() {
    atualizarDicaItem();
    atualizarCamposMovimentacao();
    atualizarPainelItem().catch((erro) => mostrarMensagem(erro.message, "erro"));
}

function atualizarDicaItem() {
    const dica = document.getElementById("item-encontrado");
    const material = itemSelecionado();
    const codigoDigitado = document.getElementById("busca-item").value.trim();
    if (material) {
        let validade = "";
        if (material.proxima_validade) {
            const verbo = material.dias_para_vencer < 0 ? "venceu" : "vence";
            validade = ` · ${verbo} em ${formatarValidade(material.proxima_validade)}`;
        }
        dica.textContent = `✓ ${material.nome} · saldo ${material.saldo} ${material.unidade}${validade}`;
        dica.className = "dica ok";
    } else if (codigoDigitado) {
        dica.textContent = "Nenhum item com esse código.";
        dica.className = "dica erro";
    } else {
        dica.textContent = "";
    }
}

// Usa a lista completa, sem o filtro da busca, para a caixa de itens e os indicadores
async function carregarListaCompleta() {
    const materiais = await chamarApi("/materiais");
    materiaisAtivos = materiais;
    const select = document.getElementById("select-material");
    const selecionado = select.value;
    select.replaceChildren(criarElemento("option", "Selecione o item..."));
    select.firstChild.value = "";
    for (const material of materiais) {
        const codigo = material.codigo ? `${material.codigo} — ` : "";
        const opcao = criarElemento("option", `${codigo}${material.nome} (saldo: ${material.saldo} ${material.unidade})`);
        opcao.value = material.id;
        select.appendChild(opcao);
    }
    select.value = selecionado;

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

        linha.appendChild(criarElemento("td", mov.codigo ? `${mov.codigo} · ${mov.material}` : mov.material));
        linha.appendChild(criarElemento("td", `${mov.tipo === "entrada" ? "+" : "−"}${mov.quantidade} ${mov.unidade}`, "numero"));
        const destino = mov.tipo === "entrada"
            ? (mov.validade ? "Validade " + formatarValidade(mov.validade) : "—")
            : (mov.setor ?? "—");
        linha.appendChild(criarElemento("td", destino));
        // Movimentações de antes do login não têm responsável registrado
        linha.appendChild(criarElemento("td", mov.colaborador ?? "Não registrado"));
        tabela.appendChild(linha);
    }
}

// "2027-05-01" vira "01/05/2027"
function formatarValidade(iso) {
    return iso.split("-").reverse().join("/");
}

// Mesmo prazo do alerta na API (DIAS_ALERTA_VENCIMENTO)
const DIAS_ALERTA_VENCIMENTO = 30;

function criarEtiquetaPrazo(item) {
    const dias = item.dias_restantes;
    if (dias === null) {
        return criarElemento("span", "Sem validade", "etiqueta neutra");
    }
    if (dias < 0) {
        return criarElemento("span", `Vencido há ${-dias} dia${dias === -1 ? "" : "s"}`, "etiqueta perigo");
    }
    const texto = dias === 0 ? "Vence hoje" : `Vence em ${dias} dia${dias === 1 ? "" : "s"}`;
    return criarElemento("span", texto, dias <= DIAS_ALERTA_VENCIMENTO ? "etiqueta alerta" : "etiqueta neutra");
}

async function carregarVencimentos() {
    const vencimentos = await chamarApi("/alertas/vencimento");
    // Um item pode ter várias validades no alerta; o card conta itens para bater com o filtro do estoque
    idsComVencimento = new Set(vencimentos.map((vencimento) => vencimento.material_id));
    mostrarIndicador("total-vencimento", idsComVencimento.size);
    const contador = document.getElementById("contador-vencimentos");
    contador.textContent = vencimentos.length;
    contador.hidden = vencimentos.length === 0;

    const lista = document.getElementById("lista-vencimentos");
    lista.replaceChildren();
    if (vencimentos.length === 0) {
        lista.appendChild(criarElemento("li", "✓ Nenhum item vencido ou vencendo nos próximos 30 dias", "sem-alerta"));
        return;
    }
    for (const vencimento of vencimentos) {
        const item = document.createElement("li");
        if (vencimento.vencido) {
            item.className = "vencido";
        }
        const textos = document.createElement("div");
        textos.appendChild(criarElemento("span", vencimento.nome, "alerta-nome"));
        textos.appendChild(
            criarElemento(
                "span",
                `Validade ${formatarValidade(vencimento.validade)} · ${vencimento.quantidade} ${vencimento.unidade}`,
                "alerta-detalhe",
            ),
        );
        item.appendChild(textos);
        item.appendChild(criarEtiquetaPrazo(vencimento));
        lista.appendChild(item);
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
    const material = itemSelecionado();
    document.getElementById("painel-vazio").hidden = Boolean(material);
    // Sem item escolhido não quer dizer sem itens cadastrados; a mensagem diferencia os dois casos
    document.getElementById("painel-vazio-texto").textContent = materiaisAtivos.length
        ? "Digite o código ou escolha um item para ver o saldo, as validades e as últimas movimentações."
        : "Nenhum item cadastrado ainda. Cadastre um item para começar.";
    document.getElementById("painel-conteudo").hidden = !material;
    if (!material) {
        return;
    }

    document.getElementById("painel-nome").textContent = material.nome;
    document.getElementById("painel-categoria").textContent =
        `${material.codigo ? "Código " + material.codigo + " · " : ""}${material.categoria} · ${material.unidade}`;
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

    const [validades, movimentacoes] = await Promise.all([
        chamarApi(`/materiais/${material.id}/validades`),
        chamarApi(`/movimentacoes?material_id=${material.id}`),
    ]);

    // Já vem na ordem FEFO: a primeira é a que deve sair primeiro
    const listaValidades = document.getElementById("painel-validades");
    listaValidades.replaceChildren();
    if (validades.length === 0) {
        listaValidades.appendChild(criarElemento("li", "Nada em estoque.", "vazio"));
    }
    validades.forEach((validade, indice) => {
        const item = document.createElement("li");
        if (indice === 0) {
            item.className = "proxima";
        }
        const texto = document.createElement("div");
        texto.className = "movimento-texto";
        texto.appendChild(
            criarElemento("span", validade.validade ? formatarValidade(validade.validade) : "Sem validade"),
        );
        texto.appendChild(criarElemento("small", `${validade.quantidade} ${material.unidade}`));
        item.appendChild(texto);
        item.appendChild(criarEtiquetaPrazo(validade));
        listaValidades.appendChild(item);
    });

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
    const carregamentos = [
        carregarMateriais(),
        carregarListaCompleta(),
        carregarAlertas(),
        carregarVencimentos(),
        carregarHistorico(),
    ];
    if (ehAdmin()) {
        carregamentos.push(carregarColaboradores());
    }
    try {
        await Promise.all(carregamentos);
        // O filtro "vencidos ou a vencer" depende dos vencimentos, que carregaram em paralelo com a tabela
        if (document.getElementById("filtro-situacao").value === "vencimento") {
            await carregarMateriais();
        }
        // Depois das listas, porque o painel e os campos usam os itens que acabaram de ser carregados
        atualizarCamposMovimentacao();
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
    for (const campo of ["codigo", "nome", "categoria", "unidade", "estoque_minimo"]) {
        form.elements[campo].value = material[campo] ?? "";
    }
    form.elements.sem_validade.checked = !material.controla_validade;
    atualizarCheckboxValidade();
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
    atualizarCheckboxValidade();
}

document.getElementById("cancelar-edicao-material").addEventListener("click", cancelarEdicaoMaterial);

// Espelha CATEGORIAS_COM_VALIDADE_OBRIGATORIA da API
const CATEGORIAS_COM_VALIDADE_OBRIGATORIA = ["Medicamento", "Soro e solução"];
const DICA_SEM_VALIDADE = "Ex.: pano, bucha, rodo, vassoura. A entrada não vai pedir data.";

function atualizarCheckboxValidade() {
    const form = document.getElementById("form-material");
    const categoria = form.elements.categoria.value;
    const obrigatoria = CATEGORIAS_COM_VALIDADE_OBRIGATORIA.includes(categoria);
    const checkbox = form.elements.sem_validade;
    checkbox.disabled = obrigatoria;
    if (obrigatoria) {
        checkbox.checked = false;
    }
    document.getElementById("dica-sem-validade").textContent = obrigatoria
        ? `${categoria} sempre precisa ter validade.`
        : DICA_SEM_VALIDADE;
}

document.getElementById("form-material").elements.categoria.addEventListener("change", atualizarCheckboxValidade);

document.getElementById("form-material").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const dados = Object.fromEntries(new FormData(evento.target));
    dados.estoque_minimo = Number(dados.estoque_minimo);
    // Checkbox marcado só aparece no FormData como "on"; a API espera o booleano controla_validade
    dados.controla_validade = !evento.target.elements.sem_validade.checked;
    delete dados.sem_validade;
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
        // Volta para a busca com o texto selecionado: o próximo código digitado ou lido substitui o atual
        campoBuscaItem.focus();
        campoBuscaItem.select();
        atualizarDicaItem();
    } catch (erro) {
        mostrarMensagem(erro.message, "erro");
    }
});

// Cada botão de aba guarda em data-aba o id da seção que ele mostra
function abrirAba(botao) {
    document.querySelectorAll(".aba").forEach((outro) => {
        outro.classList.toggle("ativa", outro === botao);
        // Saída e Entrada apontam para a mesma seção, então compara pelo id e não pelo botão
        document.getElementById(outro.dataset.aba).hidden = outro.dataset.aba !== botao.dataset.aba;
    });
    if (botao.dataset.tipo) {
        definirTipo(botao.dataset.tipo);
    }
    // Nas abas de consulta e gestão os alertas só ocupariam espaço
    document.querySelectorAll(".alertas").forEach((cartao) => {
        cartao.hidden = botao.hasAttribute("data-sem-alertas");
    });
    // O painel só busca dados quando é aberto, para não pesar nas outras abas
    if (botao.dataset.aba === "aba-painel") {
        carregarPainel().catch((erro) => mostrarMensagem(erro.message, "erro"));
    }
}

// ---------- Painel (gráficos) ----------

let diasPainel = 30;
// Guardado para redesenhar o gráfico de linhas quando a largura da tela muda
let ultimoPainel = null;

const SERIES_POR_DIA = [
    { chave: "entradas", nome: "entradas", classe: "entrada" },
    { chave: "saidas", nome: "saídas", classe: "saida" },
];

// "2026-10-02" vira "02/10" no eixo e "02/10/2026" no balão
const diaCurto = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7);

function plural(quantidade, singular, pluralTexto) {
    return `${formatarNumero(quantidade)} ${quantidade === 1 ? singular : pluralTexto}`;
}

function desenharLinhasPainel() {
    if (ultimoPainel) {
        desenharGraficoLinhas(
            document.getElementById("grafico-dias"),
            ultimoPainel.por_dia,
            SERIES_POR_DIA,
            diaCurto,
            formatarValidade,
        );
    }
}

async function carregarPainel() {
    const aba = document.getElementById("aba-painel");
    aba.classList.add("carregando");
    try {
        ultimoPainel = await chamarApi(`/painel?dias=${diasPainel}`);
    } finally {
        aba.classList.remove("carregando");
    }
    const painel = ultimoPainel;

    document.getElementById("painel-total-entradas").textContent = formatarNumero(painel.total_entradas);
    document.getElementById("painel-total-saidas").textContent = formatarNumero(painel.total_saidas);
    const lider = painel.por_setor[0];
    document.getElementById("painel-setor-lider").textContent = lider ? lider.setor : "—";
    document.getElementById("painel-setor-lider-detalhe").textContent = lider
        ? plural(lider.saidas, "saída", "saídas")
        : "Nenhuma saída no período";

    desenharLinhasPainel();
    desenharTabela(
        document.getElementById("tabela-dias"),
        ["Dia", "Entradas", "Saídas"],
        painel.por_dia.map((dia) => [formatarValidade(dia.dia), dia.entradas, dia.saidas]),
        [1, 2],
    );

    desenharGraficoBarras(
        document.getElementById("grafico-setores"),
        painel.por_setor.map((setor) => ({
            rotulo: setor.setor,
            valor: setor.saidas,
            textoValor: formatarNumero(setor.saidas),
            descricao: setor.saidas === 1 ? "saída" : "saídas",
        })),
        "saida",
        "Nenhuma saída no período.",
    );
    desenharTabela(
        document.getElementById("tabela-setores"),
        ["Setor", "Saídas"],
        painel.por_setor.map((setor) => [setor.setor, setor.saidas]),
        [1],
    );

    desenharGraficoBarras(
        document.getElementById("grafico-itens"),
        painel.mais_retirados.map((item) => ({
            rotulo: item.codigo ? `${item.codigo} · ${item.nome}` : item.nome,
            valor: item.quantidade,
            textoValor: `${formatarNumero(item.quantidade)} ${item.unidade}`,
            descricao: "retirados",
        })),
        "saida",
        "Nenhum item retirado no período.",
    );
    desenharTabela(
        document.getElementById("tabela-itens"),
        ["Item", "Quantidade", "Unidade"],
        painel.mais_retirados.map((item) => [
            item.codigo ? `${item.codigo} · ${item.nome}` : item.nome,
            item.quantidade,
            item.unidade,
        ]),
        [1],
    );
}

document.querySelectorAll(".periodo").forEach((botao) => {
    botao.addEventListener("click", () => {
        document.querySelectorAll(".periodo").forEach((outro) => outro.classList.toggle("ativa", outro === botao));
        diasPainel = Number(botao.dataset.dias);
        carregarPainel().catch((erro) => mostrarMensagem(erro.message, "erro"));
    });
});

// Redesenha só quando a largura muda de verdade (ex.: janela redimensionada)
let larguraGrafico = 0;
new ResizeObserver((entradas) => {
    const largura = Math.round(entradas[0].contentRect.width);
    if (largura && largura !== larguraGrafico) {
        larguraGrafico = largura;
        desenharLinhasPainel();
    }
}).observe(document.getElementById("grafico-dias"));

document.querySelectorAll(".aba").forEach((botao) => {
    botao.addEventListener("click", () => abrirAba(botao));
});

// Mostra validade na entrada e setor na saída
function definirTipo(tipo) {
    document.getElementById("campo-tipo").value = tipo;
    document.getElementById("botao-registrar").textContent =
        tipo === "entrada" ? "Registrar entrada" : "Registrar saída";
    atualizarCamposMovimentacao();
}

// Os campos dependem do tipo e também do item: item sem validade não pede data na entrada
function atualizarCamposMovimentacao() {
    const ehEntrada = document.getElementById("campo-tipo").value === "entrada";
    const material = itemSelecionado();
    const semValidade = Boolean(material) && !material.controla_validade;

    document.getElementById("campos-saida").hidden = ehEntrada;
    document.getElementById("campos-entrada").hidden = !ehEntrada || semValidade;
    document.getElementById("aviso-sem-validade").hidden = !(ehEntrada && semValidade);
}

definirTipo("saida");

document.getElementById("busca").addEventListener("input", () => {
    carregarMateriais().catch((erro) => mostrarMensagem(erro.message, "erro"));
});

document.getElementById("filtro-situacao").addEventListener("change", () => {
    carregarMateriais().catch((erro) => mostrarMensagem(erro.message, "erro"));
});

// Card de resumo: abre o Estoque já filtrado pela situação do card
document.querySelectorAll(".indicador[data-filtro]").forEach((card) => {
    card.addEventListener("click", () => {
        document.getElementById("filtro-situacao").value = card.dataset.filtro;
        document.getElementById("busca").value = "";
        abrirAba(document.querySelector('[data-aba="aba-estoque"]'));
        carregarMateriais().catch((erro) => mostrarMensagem(erro.message, "erro"));
        document.querySelector(".grade").scrollIntoView({ behavior: "smooth", block: "start" });
    });
});

const campoBuscaItem = document.getElementById("busca-item");
const selectMaterial = document.getElementById("select-material");

// Digitou o código: escolhe o item na caixa
campoBuscaItem.addEventListener("input", () => {
    const material = encontrarPorCodigo(campoBuscaItem.value);
    selectMaterial.value = material ? material.id : "";
    aoMudarItem();
});

// Escolheu na caixa: mostra o código do item no campo
selectMaterial.addEventListener("change", () => {
    const material = itemSelecionado();
    campoBuscaItem.value = material?.codigo ?? "";
    aoMudarItem();
});

// O leitor de código de barras "digita" o código e aperta Enter; sem isso o formulário seria enviado
campoBuscaItem.addEventListener("keydown", (evento) => {
    if (evento.key !== "Enter") {
        return;
    }
    evento.preventDefault();
    if (itemSelecionado()) {
        document.querySelector("#form-movimentacao [name=quantidade]").focus();
    }
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
    // Espelha verificar_permissao da API: só farmacêutico e super admin registram entrada
    if (usuarioAtual.perfil === "super_admin" || usuarioAtual.cargo === "Farmacêutico") {
        document.querySelectorAll(".so-entrada").forEach((elemento) => (elemento.hidden = false));
    }
    abrirAba(document.querySelector(".aba:not([hidden])"));
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
