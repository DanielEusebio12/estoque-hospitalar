// Chama a API e transforma respostas de erro em exceção com a mensagem do servidor
async function chamarApi(caminho, opcoes = {}) {
    const resposta = await fetch(caminho, {
        headers: { "Content-Type": "application/json" },
        ...opcoes,
    });
    const dados = await resposta.json();
    if (!resposta.ok) {
        throw new Error(traduzirErro(dados.detail));
    }
    return dados;
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
    if (material.saldo === 0) {
        return criarElemento("span", "Sem estoque", "etiqueta perigo");
    }
    if (material.saldo < material.estoque_minimo) {
        return criarElemento("span", "Abaixo do mínimo", "etiqueta alerta");
    }
    return criarElemento("span", "Normal", "etiqueta ok");
}

async function carregarMateriais() {
    const busca = document.getElementById("busca").value.trim();
    const caminho = busca ? "/materiais?busca=" + encodeURIComponent(busca) : "/materiais";
    const materiais = await chamarApi(caminho);

    const tabela = document.getElementById("tabela-materiais");
    tabela.replaceChildren();
    if (materiais.length === 0) {
        const celula = criarElemento("td", busca ? "Nenhum item encontrado." : "Nenhum item cadastrado ainda.", "vazio");
        celula.colSpan = 6;
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
        tabela.appendChild(linha);
    }
}

function mostrarIndicador(id, valor) {
    const elemento = document.getElementById(id);
    elemento.textContent = valor;
    elemento.classList.toggle("tem-valor", valor > 0);
}

// Usa a lista completa, sem o filtro da busca, para o select e os indicadores
async function carregarListaCompleta() {
    const materiais = await chamarApi("/materiais");
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

    mostrarIndicador("total-materiais", materiais.length);
    mostrarIndicador("total-zerados", materiais.filter((material) => material.saldo === 0).length);
}

async function carregarAlertas() {
    const alertas = await chamarApi("/alertas/estoque-baixo");
    // O total vem da API para a regra de "abaixo do mínimo" ficar só no servidor
    mostrarIndicador("total-alertas", alertas.length);

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

async function atualizarTela() {
    try {
        await Promise.all([carregarMateriais(), carregarListaCompleta(), carregarAlertas()]);
    } catch (erro) {
        mostrarMensagem("Erro ao carregar dados: " + erro.message, "erro");
    }
}

document.getElementById("form-material").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const form = evento.target;
    const dados = Object.fromEntries(new FormData(form));
    dados.estoque_minimo = Number(dados.estoque_minimo);
    try {
        const material = await chamarApi("/materiais", { method: "POST", body: JSON.stringify(dados) });
        mostrarMensagem(`"${material.nome}" cadastrado com sucesso.`, "sucesso");
        form.reset();
        await atualizarTela();
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
document.querySelectorAll(".aba").forEach((botao) => {
    botao.addEventListener("click", () => {
        document.querySelectorAll(".aba").forEach((outro) => {
            const ativo = outro === botao;
            outro.classList.toggle("ativa", ativo);
            document.getElementById(outro.dataset.aba).hidden = !ativo;
        });
    });
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

atualizarTela();
