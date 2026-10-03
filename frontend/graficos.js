// Gráficos em SVG e HTML puro, sem biblioteca: só o que o painel precisa (linhas e barras).
// As cores ficam no CSS (classes .entrada / .saida), junto com o resto do visual.

const SVG_NS = "http://www.w3.org/2000/svg";

function criarSvg(tag, atributos = {}) {
    const elemento = document.createElementNS(SVG_NS, tag);
    for (const [nome, valor] of Object.entries(atributos)) {
        elemento.setAttribute(nome, valor);
    }
    return elemento;
}

function formatarNumero(valor) {
    return valor.toLocaleString("pt-BR");
}

// Eixo com números redondos (0, 5, 10, 15...) para ser fácil de ler
function escalaRedonda(maiorValor, divisoes = 4) {
    if (maiorValor <= 0) {
        return { maximo: divisoes, passo: 1 };
    }
    const bruto = maiorValor / divisoes;
    const potencia = 10 ** Math.floor(Math.log10(bruto));
    // Contagens são inteiras, então o passo nunca é menor que 1
    const passo = Math.max(1, [1, 2, 5, 10].map((fator) => fator * potencia).find((p) => p >= bruto));
    return { maximo: Math.ceil(maiorValor / passo) * passo, passo };
}

// ---------- Balão de informação (tooltip) ----------

const tooltipGrafico = document.getElementById("tooltip-grafico");

// linhas: [{ classe, rotulo, valor }]; o valor vem em destaque e o nome da série depois
function mostrarTooltip(titulo, linhas, x, y) {
    tooltipGrafico.replaceChildren();
    const cabecalho = document.createElement("div");
    cabecalho.className = "tooltip-titulo";
    cabecalho.textContent = titulo;
    tooltipGrafico.appendChild(cabecalho);

    for (const linha of linhas) {
        const item = document.createElement("div");
        item.className = "tooltip-linha";
        const chave = document.createElement("span");
        chave.className = `chave-linha ${linha.classe}`;
        const valor = document.createElement("strong");
        valor.textContent = linha.valor;
        const rotulo = document.createElement("span");
        rotulo.textContent = linha.rotulo;
        item.append(chave, valor, rotulo);
        tooltipGrafico.appendChild(item);
    }

    tooltipGrafico.hidden = false;
    // Perto do ponteiro, mas sem sair da tela
    const largura = tooltipGrafico.offsetWidth;
    const altura = tooltipGrafico.offsetHeight;
    const esquerda = Math.max(8, Math.min(x + 14, window.innerWidth - largura - 8));
    const topo = y - altura - 12 < 8 ? y + 16 : y - altura - 12;
    tooltipGrafico.style.left = `${esquerda}px`;
    tooltipGrafico.style.top = `${topo}px`;
}

function esconderTooltip() {
    tooltipGrafico.hidden = true;
}

// ---------- Gráfico de linhas ----------

// pontos: [{ dia, <chave da série>: valor }]; series: [{ chave, nome, classe }]
function desenharGraficoLinhas(container, pontos, series, formatarDiaCurto, formatarDiaLongo) {
    container.replaceChildren();
    const largura = container.clientWidth;
    // Aba escondida tem largura 0; o gráfico é desenhado quando ela aparece
    if (!largura || pontos.length === 0) {
        return;
    }

    const altura = 260;
    const margem = { topo: 12, direita: 16, baixo: 30, esquerda: 40 };
    const larguraPlot = largura - margem.esquerda - margem.direita;
    const alturaPlot = altura - margem.topo - margem.baixo;
    const ultimo = pontos.length - 1;
    const maiorValor = Math.max(0, ...pontos.flatMap((ponto) => series.map((serie) => ponto[serie.chave])));
    const escala = escalaRedonda(maiorValor);

    const posX = (indice) => margem.esquerda + (ultimo === 0 ? larguraPlot / 2 : (indice * larguraPlot) / ultimo);
    const posY = (valor) => margem.topo + alturaPlot - (valor / escala.maximo) * alturaPlot;

    const svg = criarSvg("svg", {
        width: largura,
        height: altura,
        viewBox: `0 0 ${largura} ${altura}`,
        class: "grafico-svg",
        role: "img",
        "aria-label": `Gráfico de linhas: ${series.map((serie) => serie.nome).join(" e ")} por dia`,
    });

    // Grade horizontal (linhas finas e discretas) com os valores do eixo
    for (let valor = 0; valor <= escala.maximo; valor += escala.passo) {
        svg.appendChild(
            criarSvg("line", {
                x1: margem.esquerda,
                x2: largura - margem.direita,
                y1: posY(valor),
                y2: posY(valor),
                class: valor === 0 ? "eixo" : "grade",
            }),
        );
        const rotulo = criarSvg("text", {
            x: margem.esquerda - 8,
            y: posY(valor),
            class: "rotulo-eixo",
            "text-anchor": "end",
            "dominant-baseline": "middle",
        });
        rotulo.textContent = formatarNumero(valor);
        svg.appendChild(rotulo);
    }

    // Datas no eixo de baixo: no máximo ~6, para não encavalar
    const intervalo = Math.max(1, Math.ceil(pontos.length / 6));
    pontos.forEach((ponto, indice) => {
        if (indice % intervalo !== 0) {
            return;
        }
        const rotulo = criarSvg("text", {
            x: posX(indice),
            y: altura - 8,
            class: "rotulo-eixo",
            "text-anchor": indice === 0 && ultimo > 0 ? "start" : "middle",
        });
        rotulo.textContent = formatarDiaCurto(ponto.dia);
        svg.appendChild(rotulo);
    });

    // Linhas de 2px e o ponto final de cada série (com anel da cor do fundo)
    for (const serie of series) {
        const caminho = pontos
            .map((ponto, indice) => `${indice === 0 ? "M" : "L"}${posX(indice)},${posY(ponto[serie.chave])}`)
            .join(" ");
        svg.appendChild(criarSvg("path", { d: caminho, class: `linha-serie ${serie.classe}` }));
        svg.appendChild(
            criarSvg("circle", {
                cx: posX(ultimo),
                cy: posY(pontos[ultimo][serie.chave]),
                r: 4,
                class: `ponto-serie ${serie.classe}`,
            }),
        );
    }

    // Mira vertical que acompanha o mouse e marca o dia mais próximo
    const mira = criarSvg("line", {
        y1: margem.topo,
        y2: margem.topo + alturaPlot,
        class: "mira",
        visibility: "hidden",
    });
    const destaques = series.map((serie) =>
        criarSvg("circle", { r: 5, class: `ponto-serie ${serie.classe}`, visibility: "hidden" }),
    );
    svg.append(mira, ...destaques);

    // Área invisível por cima de tudo: o mouse não precisa acertar a linha de 2px
    const area = criarSvg("rect", {
        x: margem.esquerda,
        y: margem.topo,
        width: larguraPlot,
        height: alturaPlot,
        class: "area-interativa",
        tabindex: 0,
        "aria-label": "Use as setas para ver os valores de cada dia",
    });
    svg.appendChild(area);

    let indiceAtual = ultimo;

    function destacar(indice, x, y) {
        indiceAtual = indice;
        mira.setAttribute("x1", posX(indice));
        mira.setAttribute("x2", posX(indice));
        mira.setAttribute("visibility", "visible");
        destaques.forEach((circulo, posicao) => {
            circulo.setAttribute("cx", posX(indice));
            circulo.setAttribute("cy", posY(pontos[indice][series[posicao].chave]));
            circulo.setAttribute("visibility", "visible");
        });
        mostrarTooltip(
            formatarDiaLongo(pontos[indice].dia),
            series.map((serie) => ({
                classe: serie.classe,
                rotulo: serie.nome,
                valor: formatarNumero(pontos[indice][serie.chave]),
            })),
            x,
            y,
        );
    }

    function limpar() {
        mira.setAttribute("visibility", "hidden");
        destaques.forEach((circulo) => circulo.setAttribute("visibility", "hidden"));
        esconderTooltip();
    }

    // Pelo teclado o balão aparece em cima do ponto mais alto do dia
    function destacarPeloTeclado(indice) {
        const caixa = svg.getBoundingClientRect();
        const maiorDoDia = Math.max(...series.map((serie) => pontos[indice][serie.chave]));
        destacar(indice, caixa.left + posX(indice), caixa.top + posY(maiorDoDia));
    }

    area.addEventListener("pointermove", (evento) => {
        const caixa = svg.getBoundingClientRect();
        const proporcao = (evento.clientX - caixa.left - margem.esquerda) / larguraPlot;
        const indice = Math.min(ultimo, Math.max(0, Math.round(proporcao * ultimo)));
        destacar(indice, evento.clientX, evento.clientY);
    });
    area.addEventListener("pointerleave", limpar);
    area.addEventListener("blur", limpar);
    area.addEventListener("focus", () => destacarPeloTeclado(indiceAtual));
    area.addEventListener("keydown", (evento) => {
        const passos = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
        if (!(evento.key in passos)) {
            return;
        }
        evento.preventDefault();
        destacarPeloTeclado(Math.min(ultimo, Math.max(0, indiceAtual + passos[evento.key])));
    });

    container.appendChild(svg);
}

// ---------- Gráfico de barras horizontais ----------

// itens: [{ rotulo, valor, textoValor }]; feito em HTML para o nome longo quebrar linha sozinho
function desenharGraficoBarras(container, itens, classe, mensagemVazio) {
    container.replaceChildren();
    if (itens.length === 0) {
        const vazio = document.createElement("p");
        vazio.className = "texto-suave grafico-vazio";
        vazio.textContent = mensagemVazio;
        container.appendChild(vazio);
        return;
    }

    const maiorValor = Math.max(...itens.map((item) => item.valor));
    for (const item of itens) {
        const linha = document.createElement("div");
        linha.className = "linha-barra";
        linha.tabIndex = 0;

        const rotulo = document.createElement("span");
        rotulo.className = "rotulo-barra";
        rotulo.textContent = item.rotulo;

        const trilho = document.createElement("div");
        trilho.className = "trilho-barra";
        const barra = document.createElement("div");
        barra.className = `barra-grafico ${classe}`;
        // O comprimento é proporcional ao maior valor; o CSS reserva espaço para o número na ponta
        barra.style.setProperty("--fracao", item.valor / maiorValor);
        const valor = document.createElement("span");
        valor.className = "valor-barra";
        valor.textContent = item.textoValor;
        trilho.append(barra, valor);

        linha.append(rotulo, trilho);

        const linhasTooltip = [{ classe, rotulo: item.descricao, valor: item.textoValor }];
        linha.addEventListener("pointermove", (evento) => {
            mostrarTooltip(item.rotulo, linhasTooltip, evento.clientX, evento.clientY);
        });
        linha.addEventListener("focus", () => {
            const caixa = barra.getBoundingClientRect();
            mostrarTooltip(item.rotulo, linhasTooltip, caixa.right, caixa.top);
        });
        linha.addEventListener("pointerleave", esconderTooltip);
        linha.addEventListener("blur", esconderTooltip);

        container.appendChild(linha);
    }
}

// ---------- Tabela equivalente (para quem não enxerga bem as cores ou quer o número exato) ----------

function desenharTabela(container, cabecalhos, linhas, colunasNumericas = []) {
    const tabela = document.createElement("table");
    tabela.className = "tabela-compacta";
    const cabeca = document.createElement("thead");
    const linhaCabeca = document.createElement("tr");
    cabecalhos.forEach((texto, indice) => {
        const celula = document.createElement("th");
        celula.textContent = texto;
        if (colunasNumericas.includes(indice)) {
            celula.className = "numero";
        }
        linhaCabeca.appendChild(celula);
    });
    cabeca.appendChild(linhaCabeca);

    const corpo = document.createElement("tbody");
    for (const valores of linhas) {
        const linha = document.createElement("tr");
        valores.forEach((valor, indice) => {
            const celula = document.createElement("td");
            celula.textContent = valor;
            if (colunasNumericas.includes(indice)) {
                celula.className = "numero";
            }
            linha.appendChild(celula);
        });
        corpo.appendChild(linha);
    }
    tabela.append(cabeca, corpo);
    container.replaceChildren(tabela);
}
