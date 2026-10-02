function mostrarErro(texto) {
    const erro = document.getElementById("erro");
    erro.textContent = texto;
    erro.hidden = false;
}

// Sem sessão não há senha para trocar; volta para o login
fetch("/eu").then(async (resposta) => {
    if (!resposta.ok) {
        window.location.href = "/login";
        return;
    }
    const usuario = await resposta.json();
    document.getElementById("aviso-primeiro-acesso").hidden = !usuario.trocar_senha;
});

document.getElementById("form-senha").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    document.getElementById("erro").hidden = true;
    const dados = Object.fromEntries(new FormData(evento.target));

    // Conferir a repetição é só na tela: é para evitar erro de digitação, a API não precisa saber
    if (dados.nova_senha !== dados.confirmacao) {
        mostrarErro("As duas senhas novas não são iguais.");
        return;
    }

    const resposta = await fetch("/trocar-senha", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ senha_atual: dados.senha_atual, nova_senha: dados.nova_senha }),
    });
    const corpo = await resposta.json();
    if (!resposta.ok) {
        mostrarErro(Array.isArray(corpo.detail) ? "A nova senha precisa ter pelo menos 8 caracteres." : corpo.detail);
        return;
    }
    window.location.href = "/";
});

document.getElementById("sair").addEventListener("click", async () => {
    await fetch("/logout", { method: "POST" });
    window.location.href = "/login";
});
