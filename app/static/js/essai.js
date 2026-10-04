// Bulle de discussion d'essai. Tout texte est inséré avec textContent : jamais interprété comme HTML.
(function () {
  const fil = document.getElementById("fil");
  const zoneChoix = document.getElementById("choix");
  const formulaire = document.getElementById("formulaire");
  const champ = document.getElementById("texte");

  function ajouterBulle(texte, sens, classe) {
    const bulle = document.createElement("div");
    bulle.className = "jeff-bulle jeff-" + sens + (classe ? " " + classe : "");
    bulle.textContent = texte;
    fil.appendChild(bulle);
    fil.scrollTop = fil.scrollHeight;
    return bulle;
  }

  function afficherChoix(choix) {
    zoneChoix.replaceChildren();
    (choix || []).forEach(function (c) {
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.textContent = c.valeur + ". " + c.libelle;
      bouton.addEventListener("click", function () { envoyer(c.valeur); });
      zoneChoix.appendChild(bouton);
    });
  }

  async function envoyer(texte) {
    texte = texte.trim();
    if (!texte) return;
    const invitation = document.getElementById("invitation");
    if (invitation) invitation.remove();
    ajouterBulle(texte, "entrant");
    afficherChoix([]);
    const attente = ajouterBulle("Jeff écrit…", "sortant", "jeff-attente");
    try {
      const reponse = await fetch("/essai/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texte: texte }),
      });
      const donnees = await reponse.json();
      attente.remove();
      if (!reponse.ok) {
        ajouterBulle(donnees.detail || "Une erreur est survenue. Réessayez.", "sortant", "jeff-erreur");
        return;
      }
      ajouterBulle(donnees.reponse, "sortant");
      afficherChoix(donnees.choix);
    } catch (e) {
      attente.remove();
      ajouterBulle("Connexion impossible. Vérifiez votre réseau et réessayez.", "sortant", "jeff-erreur");
    }
  }

  formulaire.addEventListener("submit", function (evenement) {
    evenement.preventDefault();
    const texte = champ.value;
    champ.value = "";
    envoyer(texte);
  });

  // Reprise de la conversation existante.
  fetch("/essai/historique")
    .then(function (r) { return r.json(); })
    .then(function (donnees) {
      if (donnees.messages && donnees.messages.length) {
        const invitation = document.getElementById("invitation");
        if (invitation) invitation.remove();
        donnees.messages.forEach(function (m) { ajouterBulle(m.texte, m.sens); });
      }
    })
    .catch(function () {});
})();
