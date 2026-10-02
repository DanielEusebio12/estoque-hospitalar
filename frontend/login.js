document.getElementById("form-login").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const erro = document.getElementById("erro");
    erro.hidden = true;

    const resposta = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(new FormData(evento.target))),
    });
    const dados = await resposta.json();

    if (!resposta.ok) {
        erro.textContent = dados.detail;
        erro.hidden = false;
        return;
    }
    // O cookie de sessão já veio na resposta; o servidor decide se manda para a troca de senha
    window.location.href = dados.trocar_senha ? "/trocar-senha" : "/";
});
