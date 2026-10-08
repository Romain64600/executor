"use strict";
// ---- FR / EN (Romain, 07/10/2026 : « comme t'as fait pour le guide, avoir une version anglaise et une version française »).
// The interface is translated; the reports (the monitor's reasons, the notes, Claude's answers) stay in their language.
// French is the source text and the key: T("…") gives English when the page is in English. The choice is kept per
// browser (aks-lang); switching reloads the page. The fixed texts of the page exist in both languages (lang="fr" /
// lang="en", pricecheck.css shows one).
// English by default since 07/10/2026 (« tout l'outil en anglais ») ; French one click away
const LANG = (() => { try { return localStorage.getItem("aks-lang") === "fr" ? "fr" : "en"; } catch (e) { return "en"; } })();
const EN = {
 "les tops : 10 premiers Popular, 5 premiers Coming soon PC": "the tops: first 10 Popular, first 5 Coming soon PC",
 "Aucun report sur les tops pour ces filtres.": "No report on the tops for these filters.",
 "toute la homepage : widgets de la home, TOP 50 de chaque plateforme": "the whole homepage: home widgets, TOP 50 of every platform",
 "Aucun report sur la homepage pour ces filtres.": "No report on the homepage for these filters.",
 "💬 À discuter": "💬 To discuss",
 "en attente d'une décision finale : Vrai positif ou Faux positif": "waiting for a final decision: True or False positive",
 "Aucun report à discuter.": "No report to discuss.",
 "Aucun report": "No report",
 "Aucun report archivé": "No archived report",
 "« À discuter », en tête de la liste": "« To discuss », at the top of the list",
 "« Price check top »": "« Price check top »",
 "« Price check homepage »": "« Price check homepage »",
 "Price check top : la page est dans les tops (10 premiers Popular, 5 premiers Coming soon PC)": "Price check top: the page is in the tops (first 10 Popular, first 5 Coming soon PC)",
 "Price check homepage : la page est dans les listes de la homepage (top clics, TOP 50)": "Price check homepage: the page is in the homepage lists (top clicks, TOP 50)",
 "à traiter": "to handle",
 "à discuter": "to discuss",
 "à corriger": "to fix",
 "premiers prix en erreur": "first prices wrong",
 "tops à trancher": "tops to decide",
 "homepage à trancher": "homepage to decide",
 "réparées": "repaired",
 "faux positifs levés": "false positives cleared",
 "vérifiées OK": "verified OK",
 "faux positifs jugés": "false positives judged",
 "Vrai positif": "True",
 "Faux positif": "False positive",
 "À discuter": "To discuss",
 "Vrai positif : alerter": "True: alert",
 "Faux positif : ne pas alerter": "False positive: do not alert",
 "💬 Mis à discuter par ": "💬 Put to discuss by ",
 " le ": " on ",
 " : en attente d'une décision finale, Vrai positif ou Faux positif": ": waiting for a final decision, True or False positive",
 "✔ Traité par ": "✔ Handled by ",
 " : ": ": ",
 " — la carte quitte cette liste dans quelques secondes": " — the card leaves this list in a few seconds",
 " — dans quelques secondes, la carte passe dans les archives": " — in a few seconds, the card moves to the archive",
 " — dans quelques secondes, la carte revient en cours, dans ": " — in a few seconds, the card comes back in progress, in ",
 " — dans quelques secondes, la carte passe dans ": " — in a few seconds, the card moves to ",
 " — la carte reste en cours, « à corriger », jusqu'à ce que l'offre change": " — the card stays in progress, « to fix », until the offer changes",
 "l'erreur est réelle": "the error is real",
 "l'offre est correcte": "the offer is right",
 "seulement si besoin, ex. « la fiche du marchand dit ROW »": "only if needed, e.g. « the merchant's page says ROW »",
 "Pourquoi ? (note, seulement si besoin)": "Why? (note, only if needed)",
 "Mettre à jour la note": "Update the note",
 "Enregistre la note modifiée avec la décision déjà prise (": "Saves the changed note with the decision already taken (",
 "Note modifiée, pas encore enregistrée : « Mettre à jour la note » ou Entrée": "Note changed, not saved yet: « Update the note » or Enter",
 "Note pas encore enregistrée : elle part avec ta décision ②": "Note not saved yet: it leaves with your decision ②",
 "région AKS : ": "AKS region: ",
 "plateforme : ": "platform: ",
 "contrôle : ": "check: ",
 "offre ": "offer ",
 " (était ": " (was ",
 "Faux positif levé par une règle le ": "False positive cleared by a rule on ",
 "rien n'a changé dans l'offre": "nothing changed in the offer",
 "Vérifiée OK au recontrôle le ": "Verified OK at the re-check on ",
 "vérifiée OK": "verified OK",
 "Réparée le ": "Repaired on ",
 "recontrôle OK": "re-check OK",
 "Toujours en erreur au recontrôle du ": "Still wrong at the re-check of ",
 "FAUX POSITIF LEVÉ": "FALSE POSITIVE CLEARED",
 "VÉRIFIÉE OK": "VERIFIED OK",
 "RÉPARÉE": "REPAIRED",
 "✔ Décision enregistrée : ": "✔ Decision saved: ",
 "Traité par ": "Handled by ",
 "💬 À discuter (": "💬 To discuss (",
 " · à corriger": " · to fix",
 "À traiter": "To handle",
 "sortie des tops le ": "left the tops on ",
 "La page n'est plus dans les tops : le report reste dans « Price check top » jusqu'à sa décision": "The page is no longer in the tops: the report stays in « Price check top » until it is decided",
 "PREMIER PRIX": "FIRST PRICE",
 "L'une des 3 offres de clé les moins chères de son édition : un SUSPECT part sur le salon des urgences": "One of the 3 cheapest key offers of its edition: a SUSPECT goes to the emergency channel",
 "Commentaire de ": "Comment by ",
 "pas de note, à voir ensemble.": "no note, to see together.",
 "🔧 À corriger : l'erreur est confirmée, l'offre n'a pas encore changé sur ": "🔧 To fix: the error is confirmed, the offer has not changed yet on ",
 " (toujours en erreur au recontrôle du ": " (still wrong at the re-check of ",
 "Plus vu en premier prix depuis le ": "Not seen as first price since ",
 " : l'offre n'est plus en tête.": ": the offer is no longer first.",
 "Page AllKeyShop": "AllKeyShop page",
 "Offre marchand": "Merchant offer",
 "Fil Discord": "Discord thread",
 "Pourquoi ? (seulement si besoin)": "Why? (only if needed)",
 "Ta décision": "Your decision",
 "Pour clore la discussion, tranche sur l'offre, pas sur le commentaire : Vrai positif si l'erreur est réelle, Faux ": "To close the discussion, decide on the offer, not on the comment: True if the error is real, False ",
 "positif si l'offre est correcte (par exemple quand le commentaire montre que la région est juste). La note suit ta décision.": "positive if the offer is right (for instance when the comment shows the region is right). The note follows your decision.",
 "Pour changer la note : modifie-la, puis « Mettre à jour la note ». Pour changer d'avis : clique une autre décision, la note la suit.": "To change the note: edit it, then « Update the note ». To change your mind: click another decision, the note follows it.",
 "D'accord avec l'erreur décrite ? Clique directement ta décision, sans note. La note sert à dire pourquoi tu ": "Agree with the error described? Click your decision right away, no note. The note is for saying why you ",
 "n'es pas d'accord ou à préciser : écrite avant le clic, elle part avec ta décision.": "disagree or for a detail: written before the click, it leaves with your decision.",
 "Avant : ": "Before: ",
 "Non enregistrée : ": "Not saved: ",
 "Tous": "All",
 "Personne (à traiter)": "Nobody (to handle)",
 "Traités par : ": "Handled by: ",
 "Aucun report traité pour l'instant.": "No report handled yet.",
 "En cours (": "In progress (",
 "Archives (": "Archive (",
 "Les reports réglés : réparés, faux positifs levés par une règle, vérifiés OK, et les faux positifs jugés. Mis « À discuter », un report revient en cours, en tête.": "The settled reports: repaired, false positives cleared by a rule, verified OK, and the false positives judged. Put « To discuss », a report comes back in progress, at the top.",
 "Ce qui reste à faire : les reports à discuter, à traiter, et à corriger (vrai positif dont l'offre n'a pas encore changé). Réparé ou jugé faux positif, un report passe dans les archives.": "What is left to do: the reports to discuss, to handle, and to fix (decided true, the offer has not changed yet). Repaired or judged a false positive, a report moves to the archive.",
 "Aucun report : le moniteur n'a rien signalé.": "No report: the monitor flagged nothing.",
 ", dont ": ", including ",
 " à traiter": " to handle",
 " à corriger": " to fix",
 " et ": " and ",
 " masqué par les filtres": " hidden by the filters",
 " masqués par les filtres": " hidden by the filters",
 "Masqués par les filtres : ": "Hidden by the filters: ",
 " à discuter.": " to discuss.",
 "— export du ": "— export of ",
 "Dernier export du moniteur ": "Last monitor export ",
 " : le service price-check est peut-être arrêté (systemctl status price-check).": ": the price-check service may be stopped (systemctl status price-check).",
 "Lecture des reports…": "Reading the reports…",
 " report(s) lus dans ": " report(s) read from ",
 "Reports illisibles : ": "Reports unreadable: ",
 "Erreur : ": "Error: ",
 "Enregistrement de la note…": "Saving the note…",
 "Enregistrement de la décision…": "Saving the decision…",
 "réponse inattendue du serveur": "unexpected server answer",
 "Note enregistrée : ": "Note saved: ",
 "Décision enregistrée : ": "Decision saved: ",
 "Décision non enregistrée : ": "Decision not saved: ",
 "Enregistrement du fee / error…": "Saving the fee / error…",
 "Fee / error enregistré : ": "Fee / error saved: ",
 "Fee / error effacé : ": "Fee / error cleared: ",
 "Fee / error non enregistré : ": "Fee / error not saved: ",
 "Fee / error chez ": "Fee / error at ",
 "chez ": "at ",
 "par ": "by ",
 "Effacer le fee / error saisi chez ": "Clear the fee / error typed at ",
 "dont fee / error ": "incl. fee / error ",
 " affiché)": " shown)",
 "page console, non comparée": "console page, not compared",
 "introuvable": "not found",
 " (compte)": " (account)",
 "pas de compte sur AKS": "no account on AKS",
 "Jeu": "Game",
 "Meilleur compte ": "Best account at ",
 "Meilleure clé ": "Best key at ",
 "Ce que l'opérateur a vu au panier du concurrent : frais, ou prix faux, en euros, + ou −": "What the operator saw in the competitor's cart: fees, or a wrong price, in euros, + or −",
 "Premier compte AKS": "AKS first account",
 "Première clé AKS": "AKS first key",
 "bloqué": "blocked",
 " AKS moins cher · ": " AKS cheaper · ",
 " même prix · ": " same price · ",
 " concurrent moins cher": " competitor cheaper",
 " introuvable": " not found",
 " introuvables": " not found",
 " page console non comparée": " console page not compared",
 " pages console non comparées": " console pages not compared",
 "Clés": "Keys",
 "Comptes ": "Accounts ",
 "— relevé du ": "— check of ",
 "Pas encore de relevé des concurrents : le moniteur le fait toutes les 30 min pour les pages des tops.": "No competitor check yet: the monitor runs one every 30 min for the top pages.",
 "— état du moniteur ": "— monitor state ",
 "État du moniteur inconnu (status.json absent) : le bouton dépose quand même la demande.": "Monitor state unknown (no status.json): the button still files the request.",
 " Demande en attente.": " Request waiting.",
 "Mode non suivi par le moniteur.": "Mode not followed by the monitor.",
 "En cours": "Running",
 " : page ": ": page ",
 " (demandé par ": " (requested by ",
 " pages lues": " pages read",
 "lancé depuis l'admin par ": "started from the admin by ",
 "Dernier passage ": "Last pass ",
 " nouvelle(s) offre(s) contrôlée(s)": " new offer(s) checked",
 "aucune nouvelle offre à contrôler": "no new offer to check",
 " alerte(s)": " alert(s)",
 "Recontrôle complet ": "Full re-check ",
 "Recontrôle des offres signalées ": "Re-check of the flagged offers ",
 " offre(s), ": " offer(s), ",
 " réparée(s), ": " repaired, ",
 " faux positif(s) levé(s) par une règle, ": " false positive(s) cleared by a rule, ",
 " vérifiée(s) OK, ": " verified OK, ",
 " nouvelle(s) erreur(s), ": " new error(s), ",
 " toujours en erreur": " still wrong",
 "prochain passage ": "next pass ",
 "demande en attente": "request waiting",
 "Aucun passage encore.": "No pass yet.",
 " par ": " by ",
 "Demande déposée": "Request filed",
 " : le moniteur la lit dans les secondes qui viennent.": ": the monitor reads it within seconds.",
 "Refusé : ": "Refused: ",
 " : question pour Romain, dans l'onglet ": ": question for Romain, in the tab ",
 " : questions pour Romain, dans l'onglet ": ": questions for Romain, in the tab ",
 " réglée": " settled",
 " réglées": " settled",
 "Pas encore de message : écris à Claude ci-dessous.": "No message yet: write to Claude below.",
 "Le service de la console (price-check-console) n'a pas encore répondu.": "The console service (price-check-console) has not answered yet.",
 "— Claude répond à ": "— Claude is answering ",
 " en attente": " waiting",
 "Console : ": "Console: ",
 "Message envoyé : Claude répond dans la console": "Message sent: Claude answers in the console",
 "Récolte demandée : Claude relit les décisions ; ses points à trancher iront dans l'onglet Romain": "Harvest requested: Claude reviews the decisions; its points to decide will go to the Romain tab",
 "Nouvelle session demandée : Claude repart de zéro": "New session requested: Claude starts afresh",
 "Relire les reports du moniteur": "Read the monitor's reports again",
 "Guide de l'équipe : salons Discord, lire une alerte, trancher (FR / EN)": "Team guide: Discord channels, reading an alert, deciding (FR / EN)",
 "Basculer le thème": "Switch the theme",
 "Lancer un passage sur les top games maintenant": "Run a pass on the top games now",
 "Lancer un passage sur la homepage maintenant": "Run a pass on the homepage now",
 "Claude relit les décisions sur les reports et propose une action pour chacune ; chaque point à trancher va dans l'onglet Romain": "Claude reviews the decisions on the reports and proposes an action for each; every point to decide goes to the Romain tab",
 "Claude repart de zéro (les messages restent affichés)": "Claude starts afresh (the messages stay on screen)",
 "Message pour Claude": "Message for Claude",
 "Écrire à Claude… (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)": "Write to Claude… (Enter sends, Shift+Enter for a new line)",
 "jeu, marchand, raison…": "game, merchant, reason…",
 "Réparées": "Repaired",
 "Faux positifs levés par une règle": "False positives cleared by a rule",
 "Vérifiées OK (n'avaient pas pu être vérifiées)": "Verified OK (could not be verified before)",
 "Toutes": "All",
 "Sans décision": "No decision",
 "Recalcul en cours": "Recalculation running",
 "Dernier recalcul ": "Last recalculation ",
 " au démarrage du moniteur": " at the monitor's start",
 " sans conclusion": " without a conclusion",
 "Aucun recalcul encore.": "No recalculation yet.",
 "Recontrôler tout de suite les reports ouverts, sur leur page, avec les règles du moment": "Re-check the open reports right away, on their page, with the current rules"
};
const T = (fr) => (LANG === "en" && typeof fr === "string" && Object.prototype.hasOwnProperty.call(EN, fr) ? EN[fr] : fr);

// The monitor's texts in English (Romain, 07/10/2026 : « traduis aussi les raisons, faut que tout soit traduit ») : its
// reasons, notes, re-checks and methods come from a known set of sentences (price_check.py, bot/console.py); the words
// it quotes (« … », the games' names, the merchants' words) stay as they are.
const VERDICT_EN = { "À VÉRIFIER": "TO CHECK", "NON VÉRIFIABLE": "UNVERIFIABLE" };
const CHANGED_EN = { "édition": "edition", "région": "region", "plateforme": "platform", "page marchand": "merchant page" };
const orEn = (s) => s.split(" ou ").join(" or ");
const MONITOR_EN = [
  [/^en doute : (.+)$/, (m, a) => "in doubt: " + TM(a)],
  [/^(.+) ; chez (.+), une clé (.+) peut s'activer en (.+) : vérifier les pays d'activation sur la page du marchand$/,
    (m, a, b, c, d) => TM(a) + "; at " + b + ", a " + c + " key can activate in " + d + ": check the activation countries on the merchant's page"],
  [/^mots en plus après le nom : (.+)$/, "extra words after the name: $1"],
  [/^mots en plus déjà jugés comme une erreur sur cette page : (.+) \(offre (\d+)\)$/, "extra words already judged an error on this page: $1 (offer $2)"],
  [/^mots en plus acceptés pour ce jeu : (.+) \(offre (\d+) jugée faux positif\)$/, "extra words accepted for this game: $1 (offer $2 judged a false positive)"],
  [/^mots en plus acceptés pour cette page : (.+) \(offre (\d+) jugée faux positif\)$/, "extra words accepted for this page: $1 (offer $2 judged a false positive)"],
  [/^même doute que l'offre (\d+) : une seule alerte par page et par mots$/, "same doubt as offer $1: one alert per page and per words"],
  [/^premier prix anormalement bas : (.+?), (\d+) % du deuxième prix de la page \((.+)\)$/, "abnormally low first price: $1, $2 % of the page's second price ($3)"],
  [/^édition : rangée en (.+), le marchand vend (.+) \(la page a une édition (.+)\)$/,
    (m, a, b, c) => "edition: filed under " + a + ", the merchant sells " + b + " (the page has the edition " + orEn(c) + ")"],
  [/^édition : AllKeyShop (.+), marchand (.+)$/, "edition: AllKeyShop $1, merchant $2"],
  [/^autre produit chez le marchand : (« .+ ») au lieu de (« .+ ») \((.+)\)$/,
    (m, a, b, c) => "another product at the merchant: " + a + " instead of " + b + " (" + TM(c) + ")"],
  [/^nom du produit introuvable \((.+)\)$/, (m, a) => "product name not found (" + TM(a) + ")"],
  [/^nom du produit introuvable dans l'URL(?: \(elle nomme (« .+ »)\))?, page marchand illisible$/,
    (m, a) => "product name not found in the URL" + (a ? " (it names " + a + ")" : "") + ", merchant page unreadable"],
  [/^édition (.+) : nom non contrôlé dans l'URL(?: \(elle nomme (« .+ »)\))?, page marchand illisible$/,
    (m, e, a) => "edition " + e + ": name not checked in the URL" + (a ? " (it names " + a + ")" : "") + ", merchant page unreadable"],
  [/^URL sans nom du produit et page marchand illisible$/, "URL without the product name and merchant page unreadable"],
  [/^nom du produit non vérifiable \(page marchand illisible\)$/, "product name not verifiable (merchant page unreadable)"],
  [/^titre du marchand dans une autre langue, nom non reconnu : (.*)$/, "merchant title in another language, name not recognized: $1"],
  [/^compte chez le marchand, saisi en clé$/, "account at the merchant, entered as a key"],
  [/^région interdite : (.+)$/, "forbidden region: $1"],
  [/^région : AllKeyShop (.+), marchand (.+)$/, "region: AllKeyShop $1, merchant $2"],
  [/^gift chez le marchand, affiché en clé (.+)$/, "gift at the merchant, shown as a key $1"],
  [/^plateforme : page AllKeyShop (.+), marchand (.+)$/, "platform: AllKeyShop page $1, merchant $2"],
  [/^plateforme : AllKeyShop (.+), marchand (.+)$/, "platform: AllKeyShop $1, merchant $2"],
  [/^contenu additionnel : (.+)$/, "additional content: $1"],
  [/^monnaie de jeu chez le marchand : (.+)$/, "in-game currency at the merchant: $1"],
  [/^offre en rupture chez le marchand : le lien redirige vers une autre fiche \((.+)\), mais le prix reste dans le feed$/,
    "offer out of stock at the merchant: the link redirects to another page ($1), but the price stays in the feed"],
  // the notes
  [/^nom partiel$/, "partial name"],
  [/^titre court contenu dans le nom$/, "short title contained in the name"],
  [/^édition (.+) : nom non contrôlé en entier \(un mot du nom présent\)$/, "edition $1: name not fully checked (one word of the name present)"],
  [/^édition (.+) : nom non contrôlé$/, "edition $1: name not checked"],
  [/^région lue dans le paramètre (.+) de l'URL$/, "region read from the URL parameter $1"],
  [/^région lue sur la variante choisie par le lien : (.+)$/, "region read on the variant chosen by the link: $1"],
  [/^variante choisie par le lien non lue \(page illisible\) : région de l'URL seule$/, "variant chosen by the link not read (page unreadable): the URL's region alone"],
  [/^région lue sur la page, d'après les pays d'activation de la clé : (.+)$/, "region read on the page, from the key's activation countries: $1"],
  [/^pays d'activation non lus \(page illisible\) : région de l'URL seule$/, "activation countries not read (page unreadable): the URL's region alone"],
  [/^région lue sur la fiche servie, qui correspond à l'affichage$/, "region read on the page served, which matches the display"],
  [/^nom contrôlé sur (.+)$/, "name checked on $1"],
  [/^fiche renommée chez le marchand : (.+)$/, "page renamed at the merchant: $1"],
  [/^confirmé par la page : (.+)$/, "confirmed by the page: $1"],
  [/^URL contredite par la page : (.+)$/, "URL contradicted by the page: $1"],
  [/^la page ne dit rien sur ce point : (.+)$/, "the page says nothing on this point: $1"],
  [/^redirection vers une page d'étape ignorée : (.+)$/, "redirect to an intermediate page ignored: $1"],
  [/^boutique qui ne vend que (.+) \(config marchand\)$/, "shop that sells only $1 (merchant config)"],
  [/^passage complet du (.+?) \(doc\)( : option choisie lue sur la page)?$/,
    (m, a, b) => "full pass of " + a + " (doc)" + (b ? ": chosen option read on the page" : "")],
  [/^recontrôle du (.+) sans conclusion \((.+)\) : (.+) du (.+) rétabli$/, "re-check of $1 without a conclusion ($2): $3 of $4 restored"],
  [/^faux positif \(étude du (.+)\) : (.+)$/, (m, a, b) => "false positive (study of " + a + "): " + b.split("slug trompeur").join("misleading slug")],
  [/^rejugé le (.+) : nom reconnu \(alias (« .+ »), préfixe (« .+ ») facultatif\)$/, "judged again on $1: name recognized (alias $2, optional prefix $3)"],
  // the re-checks (fixed_how)
  [/^offre retirée de la page$/, "offer removed from the page"],
  [/^ancien faux positif : rien n'a changé, levé par une règle$/, "old false positive: nothing changed, cleared by a rule"],
  [/^recontrôle OK, l'offre a changé \((.+)\)$/, (m, a) => "re-check OK, the offer changed (" + a.split(", ").map((w) => CHANGED_EN[w] || w).join(", ") + ")"],
  [/^vérifiée OK au recontrôle$/, "verified OK at the re-check"],
  // the methods (« contrôle : … », and in the reasons)
  [/^URL après 301 marchand$/, "URL after the merchant's 301"],
  [/^URL après redirection du marchand$/, "URL after the merchant's redirect"],
  [/^URL de la version (.+)$/, "URL of the $1 version"],
  [/^URL et variante de la page \((.+)\)$/, (m, a) => "URL and the page's variant (" + TM(a) + ")"],
  [/^URL et pays d'activation de la page \((.+)\)$/, (m, a) => "URL and the page's activation countries (" + TM(a) + ")"],
  [/^titre de la page$/, "page title"],
  [/^aucune$/, "none"],
  // the passes (status.json)
  [/^(.+) \(reprise après redémarrage\)$/, "$1 (resumed after a restart)"],
  // the competitors' widgets
  [/^clé de l'API gg\.deals pas encore active : confirmer l'adresse e-mail du compte gg\.deals$/,
    "gg.deals API key not active yet: confirm the email address of the gg.deals account"],
  [/^clé de l'API gg\.deals absente \(GGDEALS_API_KEY dans \.env\)$/, "gg.deals API key missing (GGDEALS_API_KEY in .env)"],
  [/^API gg\.deals injoignable \((.+)\)$/, "gg.deals API unreachable ($1)"],
  [/^réponse de l'API gg\.deals illisible \(HTTP (.+)\)$/, "gg.deals API answer unreadable (HTTP $1)"],
  [/^API gg\.deals : (.+)$/, "gg.deals API: $1"],
  // the console service (bot/console.py)
  [/^(.+) a réglé (Q\d+) : (.+)$/, "$1 settled $2: $3"],
  [/^(.+) a ouvert une nouvelle session : Claude repart de zéro\.$/, "$1 opened a new session: Claude starts afresh."],
  [/^(.+) : seul (.+) peut le faire\.$/, "$1: only $2 can do it."],
  [/^Le message de (.+) n'a pas reçu de réponse \(service redémarré\) : renvoie-le si besoin\.$/,
    "$1's message got no answer (service restarted): send it again if needed."],
  [/^La demande a échoué \(voir le journal du service\)\.$/, "The request failed (see the service's log)."],
  [/^Récolte des décisions sur les feedbacks des reports$/, "Harvest of the decisions on the reports' feedback"],
];
function TM(text) {
  if (LANG !== "en" || typeof text !== "string") return text;
  for (const [re, to] of MONITOR_EN) if (re.test(text)) return text.replace(re, to);
  return text;
}
// "Price check" — the reports of the first-price monitor (price-check repository). Each card is
// an offer leading an AllKeyShop page, judged SUSPECT, À VÉRIFIER or NON VÉRIFIABLE, with its
// AllKeyShop URL, its merchant URL and its reason. The operator decides (true / false positive /
// to discuss): the decision is appended to decisions.jsonl, which the monitor re-reads
// before its next pass. Nothing else is written, nothing is sent.
const $ = (s) => document.querySelector(s);
function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") n.className = attrs[k];
    else if (k === "text") n.textContent = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c);
  return n;
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "X-AKS-Admin": "1", "Content-Type": "application/json" } }, opts || {}));
  const t = await r.text();
  let d = null; try { d = t ? JSON.parse(t) : null; } catch (e) {}
  if (!r.ok) throw new Error((d && d.error && d.error.message) || ("HTTP " + r.status));
  return d;
}
const setStatus = (t, busy) => { const f = $("#status"); f.textContent = t; f.className = busy ? "busy" : "idle"; };

// ---- theme + doc ----
(function () {
  const saved = localStorage.getItem("aks-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem("aks-theme", cur);
  });
})();
$("#doc-btn").addEventListener("click", () => $("#doc-modal").showModal());
$("#doc-modal").addEventListener("click", (e) => { if (e.target.id === "doc-modal") e.target.close(); });

const STALE_SECONDS = 45 * 60;  // export older than this: the monitor may be stopped
const GONE_SECONDS = 60 * 60;   // offer not seen as first price for this long when exported
const REFRESH_MS = 2 * 60 * 1000;
const VERDICT_CLASS = { "SUSPECT": "v-suspect", "À VÉRIFIER": "v-verifier", "NON VÉRIFIABLE": "v-nv" };
// re-check (Romain, 02/10/2026: « on saura si elles sont réparées ou pas »): a flagged offer found OK again, or gone
// from its page, carries fixed_at; one found wrong again carries still_wrong_at. fixed_kind tells why it is OK:
// "repaired", the offer changed (URL, region, platform, edition) or left its page; "rule", nothing changed and a
// rule added since clears it: the alert was a false positive; "verified", it could not be verified before and is now
// verified OK (neither repaired nor a false positive). An entry fixed before fixed_kind existed is "repaired".
const isFixed = (r) => !!r.fixed_at;
const isRuleCleared = (r) => isFixed(r) && r.fixed_kind === "rule";
const isVerified = (r) => isFixed(r) && r.fixed_kind === "verified";
const isRepaired = (r) => isFixed(r) && r.fixed_kind !== "rule" && r.fixed_kind !== "verified";
// Romain, 03/10/2026: « que le report des problèmes sur les tops soit identifié des problèmes home page ». The monitor
// exports `mode`: "top-games" when the offer's page is in the tops right now (first 10 Popular, first 5 Coming soon PC since 06/10/2026),
// otherwise "homepage"; a top page is also in the homepage TOP 50 (`modes` lists both). An older export has no mode.
const MODE_BADGE = { "top-games": ["TOP", "m-top"], "homepage": ["HOMEPAGE", "m-home"] };
// Romain, 05/10/2026 : « je voudrais que les reports top soient différenciables des reports homepage » : la liste en
// deux parties (les tops d'abord), chacune sous son titre ; une carte des tops porte une bande et un badge pleins.
const MODE_CARD = { "top-games": "mode-top", "homepage": "mode-home" };
const MODE_GROUPS = [
  ["top-games", "g-top", "Price check top", T("les tops : 10 premiers Popular, 5 premiers Coming soon PC"), T("Aucun report sur les tops pour ces filtres.")],
  ["homepage", "g-home", "Price check homepage", T("toute la homepage : widgets de la home, TOP 50 de chaque plateforme"),
    T("Aucun report sur la homepage pour ces filtres.")],
];
// Romain, 06/10/2026 : « dans l'admin, il faudrait qu'on ait les tops, les home et la partie à discuter. Il faut pas
// qu'on l'oublie, donc faut que ce soit bien visible ». A report put « à discuter » waits for a final decision (Vrai
// positif or Faux positif): it leaves its mode's part for « À discuter », the first part of the list, in the colour of
// that decision. The part always shows; the reports to discuss that the filters hide are counted, never silently gone.
const PARTS = [
  ["discuss", "g-discuss", T("💬 À discuter"), T("en attente d'une décision finale : Vrai positif ou Faux positif"), T("Aucun report à discuter.")],
  ...MODE_GROUPS,
];
// Romain, 06/10/2026 : « et une fois que ça a été traité, il faudrait les archiver sur un autre onglet ». Two tabs:
// « En cours », what is left to do (to discuss, to handle), and « Archives », the reports decided Vrai positif or Faux
// positif, or found repaired (cleared by a rule, verified OK) by the monitor. A report to discuss is never archived.
const ARCHIVE_PARTS = MODE_GROUPS.map(([mode, cls, label, what, none]) =>
  [mode, cls, label, what, none.replace(T("Aucun report"), T("Aucun report archivé"))]);
let TAB = "current";  // "current" | "archive"
const PART_LABEL = { "discuss": T("« À discuter », en tête de la liste"), "top-games": T("« Price check top »"),
  "homepage": T("« Price check homepage »") };
const MODE_TITLE = {
  "top-games": T("Price check top : la page est dans les tops (10 premiers Popular, 5 premiers Coming soon PC)"),
  "homepage": T("Price check homepage : la page est dans les listes de la homepage (top clics, TOP 50)"),
};
const isOpen = (r) => !decisionKey(r) && !isFixed(r);
// Romain, 03/10/2026: « je voudrais séparer les problèmes de premiers prix … premier prix = les 3 prix les moins chers
// par édition ». The monitor exports `first_price`; an older export: the rank in the edition (not an account offer).
const isFirstPrice = (r) => (typeof r.first_price === "boolean" ? r.first_price
  : Number.isInteger(r.edition_rank) && r.edition_rank >= 1 && r.edition_rank <= 3 && !r.account);

let DATA = null;         // last answer of api/price-check/reports
let LOADING = false;
const NOTES = {};        // notes being typed, per offer — they survive a re-render / refresh
const ERRORS = {};       // last refused decision, per offer
const BUSY = new Set();  // offers whose decision is being sent

// "2026-10-01 10:48" or "2026-10-01T12:45:00+02:00" → "01/10 10:48": the wall clock the
// server wrote (Europe/Berlin, the clock of the monitor's logs), never re-zoned by the browser.
function stamp(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(s || ""));
  return m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : String(s || "");
}
function ago(sec) {
  const [n, unit] = sec < 90 ? [Math.max(0, Math.round(sec)), "s"] : sec < 90 * 60 ? [Math.round(sec / 60), "min"]
    : sec < 48 * 3600 ? [Math.round(sec / 3600), "h"] : [Math.round(sec / 86400), LANG === "en" ? "d" : "j"];
  return LANG === "en" ? n + " " + unit + " ago" : "il y a " + n + " " + unit;
}
const price = (p) => (typeof p === "number" ? p.toFixed(2).replace(".", ",") + " €" : "");
const shortLabel = (label) => String(label).split(/ ?: /)[0];
const decisionKey = (r) => (r.decision && r.decision.decision) || "";
const isToDiscuss = (r) => decisionKey(r) === "a_discuter";
// the part a report belongs in ("" : an older export, without mode); a report just decided stays a few seconds in the
// part it was decided in, so that nothing moves under the cursor (05/10/2026)
const partOf = (r) => (isToDiscuss(r) ? "discuss" : MODE_CARD[r.mode] ? r.mode : "");
const shownPart = (r) => { const j = JUST_DONE.get(String(r.offer)); return j && j.part != null ? j.part : partOf(r); };
// Romain, 06/10/2026 : « les stats semblent fausses » (En cours 0, Archives 69, mais 8 SUSPECT) : un vrai positif dont l'offre
// n'a pas encore changé est une erreur confirmée qui reste à corriger : il reste en cours. Chaque report a un seul état, et
// les compteurs en sont la somme : en cours = à traiter + à discuter + à corriger ; archives = réparées + faux positifs
// levés par une règle + vérifiées OK + faux positifs jugés.
function stateOf(r) {
  if (isToDiscuss(r)) return "discuss";  // jusqu'à sa décision finale, même réparé
  if (isRuleCleared(r)) return "rule";
  if (isVerified(r)) return "verified";
  if (isFixed(r)) return "fixed";
  if (decisionKey(r) === "faux") return "faux";
  if (decisionKey(r) === "vrai") return "tofix";
  return "open";
}
const ARCHIVED = new Set(["fixed", "rule", "verified", "faux"]);
const isArchived = (r) => ARCHIVED.has(stateOf(r));
const isToFix = (r) => stateOf(r) === "tofix";
const tabOf = (r) => (isArchived(r) ? "archive" : "current");
const shownTab = (r) => { const j = JUST_DONE.get(String(r.offer)); return j && j.tab ? j.tab : tabOf(r); };
// The decisions' labels are the admin's own, in the page's language: since 07/10/2026 the monitor writes its labels in
// English, which the page in French showed as they were. Romain, 07/10/2026 : « true », pas « true positive ».
const DECISION_TEXT = { vrai: "Vrai positif", faux: "Faux positif", a_discuter: "À discuter" };
const DECISION_TITLE = { vrai: "Vrai positif : alerter", faux: "Faux positif : ne pas alerter", a_discuter: "À discuter" };
const labelOf = (key) => T(DECISION_TEXT[key] || shortLabel((DATA && DATA.decisions && DATA.decisions[key]) || key));
const isGone = (r) => typeof r.seen_lag_seconds === "number" && r.seen_lag_seconds > GONE_SECONDS;
// "2e prix de l'édition (compte)": the offer's rank in its edition when it was checked (Top Offers / Full Page).
const ordinal = (n) => (LANG === "en" ? n + (n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd"
  : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th") : n === 1 ? "1er" : n + "e");
const rankLabel = (r) => (r.edition_rank ? ordinal(r.edition_rank) + (LANG === "en" ? " price of the edition" : " prix de l'édition") +
  (r.account ? (LANG === "en" ? " (account)" : T(" (compte)")) : "") : "");

// A link only for an http(s) URL: a value read from a file never becomes a clickable
// "javascript:" URL.
function link(label, url) {
  const safe = /^https?:\/\//i.test(String(url || ""));
  return el("div", { class: "pc-link" }, [
    el("span", { class: "pc-link-l", text: label }),
    !url ? el("span", { class: "pc-raw", text: "—" })
      : safe ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: url })
        : el("span", { class: "pc-raw", text: url }),
  ]);
}

// Romain, 05/10/2026 : « lorsqu'on a traité une offre, elle disparaît trop vite … je me suis retrouvé à valider l'autre
// sans la lire en pensant que c'était toujours la même ». A report just decided stays in place, marked, for a few
// seconds even when the filters no longer keep it; then it fades out, and only then do the cards below move up.
const JUST_DONE_MS = 4000;
const FADE_MS = 600;
const JUST_DONE = new Map();  // offer -> { state: "kept" | "leaving", token }

function keepJustDone(offer, part, tab) {
  const token = {};
  JUST_DONE.set(offer, { state: "kept", token, part, tab });
  setTimeout(() => {
    const cur = JUST_DONE.get(offer);
    if (!cur || cur.token !== token) return;  // decided again meanwhile: its own timer runs
    cur.state = "leaving";
    const card = $("#offer-" + offer);
    if (card && card.classList) card.classList.add("pc-leaving");
    setTimeout(() => {
      const now = JUST_DONE.get(offer);
      if (now && now.token === token) { JUST_DONE.delete(offer); render(); }
    }, FADE_MS);
  }, JUST_DONE_MS);
}

function matchesFilters(r, strict) {
  if (!strict && JUST_DONE.has(String(r.offer))) return true;
  const v = $("#f-verdict").value;
  const d = $("#f-decision").value;
  const q = String($("#f-text").value || "").trim().toLowerCase();
  const m = $("#f-mode").value;
  if (m && r.mode !== m) return false;
  if ($("#f-first").checked && !isFirstPrice(r)) return false;
  if (v === "fixed" ? !isRepaired(r) : v === "rule" ? !isRuleCleared(r) : v === "verified" ? !isVerified(r)
    : v && (r.verdict !== v || isFixed(r))) return false;
  if (d === "none" && decisionKey(r)) return false;
  if (d && d !== "none" && decisionKey(r) !== d) return false;
  if ($("#f-live").checked && isGone(r)) return false;
  const by = $("#f-by").value;
  if (by === "none" ? !isOpen(r) : by && handledBy(r) !== by) return false;
  if (q) {
    const hay = [r.offer, r.product, r.edition, r.merchant, r.region, r.region_filter, r.list,
      r.merchant_url, ...(r.reasons || [])].join(" ").toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderSummary(reports) {
  const n = (f) => reports.filter(f).length;
  const kpi = (cls, value, label) => el("div", { class: "kpi " + cls }, [
    el("div", { class: "kpi-n", text: String(value) }), el("div", { class: "kpi-l", text: label })]);
  const state = (s) => (r) => stateOf(r) === s;
  $("#pc-summary").replaceChildren(
    // en cours
    kpi("k-open", n(state("open")), T("à traiter")),
    kpi("k-discuss" + (n(isToDiscuss) ? " hot" : ""), n(isToDiscuss), T("à discuter")),
    kpi("k-tofix", n(isToFix), T("à corriger")),
    kpi("k-first", n((r) => !isArchived(r) && !isFixed(r) && r.verdict === "SUSPECT" && isFirstPrice(r)), T("premiers prix en erreur")),
    kpi("k-top", n((r) => isOpen(r) && r.mode === "top-games"), T("tops à trancher")),
    kpi("k-home", n((r) => isOpen(r) && r.mode === "homepage"), T("homepage à trancher")),
    // archives
    kpi("k-fixed", n(state("fixed")), T("réparées")),
    kpi("k-rule", n(state("rule")), T("faux positifs levés")),
    kpi("k-verified", n(state("verified")), T("vérifiées OK")),
    kpi("k-faux", n(state("faux")), T("faux positifs jugés")),
    kpi("", reports.length, "reports"));
}

// Romain, 05/10/2026 : « rend plus clair le fait qu'une tâche a été traitée par un opérateur et quel
// opérateur l'a traitée » : « ✔ Traité par <opérateur> » en tête de carte et sous la décision, un
// filtre « Traité par » et le décompte par opérateur.
function decisionLine(d) {
  if (d.decision === "a_discuter") return el("div", { class: "pc-decision" }, [T("💬 Mis à discuter par "), el("b", { text: d.by || "?" }),
    (d.at ? T(" le ") + stamp(d.at) : "") + T(" : en attente d'une décision finale, Vrai positif ou Faux positif")]);
  return el("div", { class: "pc-decision" }, [T("✔ Traité par "), el("b", { text: d.by || "?" }),
    (d.at ? T(" le ") + stamp(d.at) : "") + T(" : ") + labelOf(d.decision) + (d.note ? " — « " + d.note + " »" : "")]);
}
const handledBy = (r) => (r.decision && r.decision.by) || "";

// A note typed and not saved yet (Romain, 05/10/2026 : Rémy typed his comments AFTER clicking the
// decision; the note had left, empty, with the click, and his comments stayed in the fields, never
// saved). On a decided report it is saved on its own: Entrée or « Mettre à jour la note » records
// the same decision again, with the note. The card says a note is not saved, and leaving the page
// asks. The field shows the saved note: a note changed (or emptied) is a note not saved yet.
function unsavedNote(offer, r) {
  if (NOTES[offer] == null) return false;
  return String(NOTES[offer]).trim() !== String((r && r.decision && r.decision.note) || "").trim();
}

// where a report just decided goes once its few seconds are over (05/10 and 06/10/2026)
function doneWhere(r, just) {
  if (!matchesFilters(r, true)) return T(" — la carte quitte cette liste dans quelques secondes");
  if (just.tab && tabOf(r) !== just.tab) return tabOf(r) === "archive" ? T(" — dans quelques secondes, la carte passe dans les archives")
    : T(" — dans quelques secondes, la carte revient en cours, dans ") + PART_LABEL[partOf(r)];
  if (PART_LABEL[partOf(r)] && partOf(r) !== just.part) return T(" — dans quelques secondes, la carte passe dans ") + PART_LABEL[partOf(r)];
  if (isToFix(r)) return T(" — la carte reste en cours, « à corriger », jusqu'à ce que l'offre change");
  return "";
}

// Romain, 06/10/2026 : sur deux reports « à discuter », il a cliqué « Vrai positif » pour valider le commentaire de Rémy,
// qui montrait que l'offre était juste. On tranche sur l'offre, pas sur le commentaire : sur une carte à discuter, le
// sens de chaque bouton est écrit en clair.
const MEANING = { vrai: T("l'erreur est réelle"), faux: T("l'offre est correcte") };

const step = (n, title) => el("div", { class: "pc-step-title" }, [el("span", { class: "pc-num", text: String(n) }), title]);

function renderItem(r) {
  const offer = String(r.offer);
  const labels = (DATA && DATA.decisions) || {};
  const cur = decisionKey(r);
  // Romain, 05/10/2026 : « mettre le texte à gauche, les boutons à droite et spécifier ça dans
  // l'admin » : ① Pourquoi ? (the note) on the left, ② Ta décision on the right, one click sends both.
  const note = el("textarea", { class: "pc-note", rows: "2", maxlength: "1000", autocomplete: "off",
    placeholder: T("seulement si besoin, ex. « la fiche du marchand dit ROW »"), "aria-label": T("Pourquoi ? (note, seulement si besoin)") });
  note.value = NOTES[offer] != null ? NOTES[offer] : ((r.decision && r.decision.note) || "");
  const saveNote = cur ? el("button", { type: "button", class: "pc-save-note", text: T("Mettre à jour la note"),
    title: T("Enregistre la note modifiée avec la décision déjà prise (") + labelOf(cur) + ")", onclick: () => decide(offer, cur) }) : null;
  const pending = el("span", { class: "pc-unsaved", text: cur
    ? T("Note modifiée, pas encore enregistrée : « Mettre à jour la note » ou Entrée")
    : T("Note pas encore enregistrée : elle part avec ta décision ②") });
  const showPending = () => {
    const open = unsavedNote(offer, r);
    note.classList.toggle("unsaved", open);
    pending.hidden = !open;
    if (saveNote) saveNote.hidden = !open;
  };
  showPending();
  note.addEventListener("input", () => { NOTES[offer] = note.value; showPending(); });
  note.addEventListener("keydown", (ev) => {
    if (!ev || ev.key !== "Enter" || ev.shiftKey) return;  // Maj+Entrée : à la ligne
    if (ev.preventDefault) ev.preventDefault();
    if (cur && unsavedNote(offer, r)) decide(offer, cur);
  });
  if (saveNote) saveNote.disabled = BUSY.has(offer);
  const buttons = Object.keys(labels).map((k) => {
    const b = el("button", { type: "button", class: "d-" + k + (cur === k ? " on" : ""), title: T(DECISION_TITLE[k] || labels[k]),
      text: labelOf(k) + (cur === "a_discuter" && MEANING[k] ? T(" : ") + MEANING[k] : ""), onclick: () => decide(offer, k) });
    b.disabled = BUSY.has(offer);
    return b;
  });
  const where = [r.list, r.rank ? "#" + r.rank : "", r.at ? "· " + stamp(r.at) : ""].filter(Boolean).join(" ");
  const meta = [
    r.region ? T("région AKS : ") + r.region + (r.region_filter ? " (" + r.region_filter + ")" : "") : "",
    r.platform ? T("plateforme : ") + r.platform : "",
    r.method ? T("contrôle : ") + TM(r.method) : "",
    T("offre ") + offer,
  ].filter(Boolean).join(" · ");
  const before = (r.history || []).slice(0, -1).reverse();
  const was = r.fixed_from ? T(" (était ") + r.fixed_from + ")" : "";
  const recheck = isRuleCleared(r)
    ? el("div", { class: "pc-rule", text: T("Faux positif levé par une règle le ") + stamp(r.fixed_at) + T(" : ") +
      (TM(r.fixed_how) || T("rien n'a changé dans l'offre")) + was })
    : isVerified(r) ? el("div", { class: "pc-fixed", text: T("Vérifiée OK au recontrôle le ") + stamp(r.fixed_at) + T(" : ") +
      (TM(r.fixed_how) || T("vérifiée OK")) + was })
    : isFixed(r) ? el("div", { class: "pc-fixed", text: T("Réparée le ") + stamp(r.fixed_at) + T(" : ") + (TM(r.fixed_how) || T("recontrôle OK")) + was })
    : r.still_wrong_at ? el("div", { class: "pc-still", text: T("Toujours en erreur au recontrôle du ") + stamp(r.still_wrong_at) }) : null;
  const pill = isRuleCleared(r) ? T("FAUX POSITIF LEVÉ") : isVerified(r) ? T("VÉRIFIÉE OK") : isFixed(r) ? T("RÉPARÉE") : LANG === "en" && VERDICT_EN[r.verdict] ? VERDICT_EN[r.verdict] : (r.verdict || "?");
  const tone = isRuleCleared(r) ? "v-rule" : isFixed(r) ? "v-fixed" : (VERDICT_CLASS[r.verdict] || "v-nv");
  const just = JUST_DONE.get(offer);
  return el("article", { class: "pc-item " + tone + (cur ? " decided" : "") + (MODE_CARD[r.mode] ? " " + MODE_CARD[r.mode] : "") +
    (just ? " pc-just-done" + (just.state === "leaving" ? " pc-leaving" : "") : ""),
    id: "offer-" + offer }, [
    just && cur ? el("div", { class: "pc-done-banner", role: "status", text: T("✔ Décision enregistrée : ") + labelOf(cur) +
      doneWhere(r, just) }) : null,
    el("div", { class: "pc-head" }, [
      el("span", { class: "pc-verdict", text: pill }),
      cur ? el("span", { class: "pc-done d-" + cur, title: T("Traité par ") + (handledBy(r) || "?") +
        (r.decision.at ? T(" le ") + stamp(r.decision.at) : ""), text: cur === "a_discuter"
          ? T("💬 À discuter (") + (handledBy(r) || "?") + (r.decision.at ? ", " + stamp(r.decision.at) : "") + ")"
          : T("✔ Traité par ") + (handledBy(r) || "?") + " · " + labelOf(cur) + (isToFix(r) ? T(" · à corriger") : "") })
        : isOpen(r) ? el("span", { class: "pc-todo", text: T("À traiter") }) : null,
      MODE_BADGE[r.mode] ? el("span", { class: "pc-mode " + MODE_BADGE[r.mode][1], title: MODE_TITLE[r.mode],
        text: MODE_BADGE[r.mode][0] }) : null,
      // 06/10/2026 : une page sortie des tops garde ses reports ouverts dans « Price check top », jusqu'à leur décision
      r.left_tops_at ? el("span", { class: "pc-left-tops", text: T("sortie des tops le ") + stamp(r.left_tops_at),
        title: T("La page n'est plus dans les tops : le report reste dans « Price check top » jusqu'à sa décision") }) : null,
      isFirstPrice(r) ? el("span", { class: "pc-mode m-first", text: T("PREMIER PRIX"),
        title: T("L'une des 3 offres de clé les moins chères de son édition : un SUSPECT part sur le salon des urgences") }) : null,
      el("span", { class: "pc-product", text: (r.product || "?") + (r.edition ? " · " + r.edition : "") }),
      rankLabel(r) ? el("span", { class: "pc-rank", text: rankLabel(r) }) : null,
      el("span", { class: "pc-merchant", text: [r.merchant, price(r.price)].filter(Boolean).join(" · ") }),
      el("span", { class: "pc-where", text: where }),
    ]),
    cur === "a_discuter" ? el("div", { class: "pc-question" }, [el("b", { text: T("Commentaire de ") + (handledBy(r) || "?") + T(" : ") }),
      r.decision.note ? "« " + r.decision.note + " »" : T("pas de note, à voir ensemble.")]) : null,
    (r.reasons || []).length ? el("ul", { class: "pc-reasons" }, r.reasons.map((x) => el("li", { text: TM(x) }))) : null,
    recheck,
    isToFix(r) ? el("div", { class: "pc-tofix", text: T("🔧 À corriger : l'erreur est confirmée, l'offre n'a pas encore changé sur ")
      + "AllKeyShop" + (r.still_wrong_at ? T(" (toujours en erreur au recontrôle du ") + stamp(r.still_wrong_at) + ")" : "") }) : null,
    el("div", { class: "pc-meta", text: meta }),
    isGone(r) ? el("div", { class: "pc-gone",
      text: T("Plus vu en premier prix depuis le ") + stamp(r.seen_at) + T(" : l'offre n'est plus en tête.") }) : null,
    (r.notes || []).length ? el("ul", { class: "pc-notes" }, r.notes.map((x) => el("li", { text: TM(x) }))) : null,
    link(T("Page AllKeyShop"), r.page_url),
    link(T("Offre marchand"), r.merchant_url),
    // 03/10/2026 : le fil de feedback Discord de l'alerte (le bot l'ouvre ; on peut y trancher aussi)
    r.discord_thread ? link(T("Fil Discord"), r.discord_thread) : null,
    el("div", { class: "pc-decide" }, [
      el("div", { class: "pc-step pc-step-note" }, [step(1, T("Pourquoi ? (seulement si besoin)")), note, pending, saveNote]),
      el("div", { class: "pc-step pc-step-decision" }, [step(2, T("Ta décision")), el("div", { class: "pc-buttons" }, buttons)]),
      el("p", { class: "pc-howto", text: cur === "a_discuter"
        ? T("Pour clore la discussion, tranche sur l'offre, pas sur le commentaire : Vrai positif si l'erreur est réelle, Faux ")
          + T("positif si l'offre est correcte (par exemple quand le commentaire montre que la région est juste). La note suit ta décision.")
        : cur ? T("Pour changer la note : modifie-la, puis « Mettre à jour la note ». Pour changer d'avis : clique une autre décision, la note la suit.")
        : T("D'accord avec l'erreur décrite ? Clique directement ta décision, sans note. La note sert à dire pourquoi tu ")
          + T("n'es pas d'accord ou à préciser : écrite avant le clic, elle part avec ta décision.") }),
    ]),
    r.decision ? decisionLine(r.decision) : null,
    before.length ? el("div", { class: "pc-history", text: T("Avant : ") + before.map((h) =>
      labelOf(h.decision) + (h.by ? " (" + h.by + (h.at ? ", " + stamp(h.at) : "") + ")" : "")).join(" ; ") }) : null,
    ERRORS[offer] ? el("div", { class: "pc-msg", text: T("Non enregistrée : ") + ERRORS[offer] }) : null,
  ]);
}

// Who handled what: the « Traité par » options (the choice is kept across refreshes) and the count.
function renderOperators(reports) {
  const count = {};
  for (const r of reports) if (handledBy(r)) count[handledBy(r)] = (count[handledBy(r)] || 0) + 1;
  const names = Object.keys(count).sort((a, b) => count[b] - count[a] || a.localeCompare(b));
  const sel = $("#f-by");
  const keep = sel.value;
  const opt = (value, text) => el("option", { value, text });
  sel.replaceChildren(opt("", T("Tous")), opt("none", T("Personne (à traiter)")), ...names.map((n) => opt(n, n)));
  sel.value = keep === "none" || names.includes(keep) ? keep : "";
  $("#pc-by").textContent = names.length
    ? T("Traités par : ") + names.map((n) => n + " " + count[n]).join(" · ") : T("Aucun report traité pour l'instant.");
}

// the two tabs, with their counts (all reports, whatever the filters)
function renderTabs(reports) {
  const current = reports.filter((r) => !isArchived(r)).length;
  for (const [tab, text] of [["current", T("En cours (") + current + ")"], ["archive", T("Archives (") + (reports.length - current) + ")"]]) {
    const b = $("#tab-" + tab);
    b.textContent = text;
    b.classList.toggle("on", TAB === tab);
    b.setAttribute("aria-pressed", String(TAB === tab));
  }
  $("#pc-tab-note").textContent = TAB === "archive"
    ? T("Les reports réglés : réparés, faux positifs levés par une règle, vérifiés OK, et les faux positifs jugés. Mis « À discuter », un report revient en cours, en tête.")
    : T("Ce qui reste à faire : les reports à discuter, à traiter, et à corriger (vrai positif dont l'offre n'a pas encore changé). Réparé ou jugé faux positif, un report passe dans les archives.");
}

function render() {
  if (!DATA) return;
  const reports = DATA.reports || [];
  renderSummary(reports);
  renderOperators(reports);
  renderTabs(reports);
  // never `filter(matchesFilters)`: the index would be taken for `strict` (audit Codex, 06/10/2026)
  const shown = reports.filter((r) => matchesFilters(r)).filter((r) => shownTab(r) === TAB);
  if (!reports.length) {
    $("#pc-list").replaceChildren(el("div", { class: "pc-empty", text: T("Aucun report : le moniteur n'a rien signalé.") }));
    return;
  }
  const only = $("#f-mode").value;
  const parts = [];
  for (const [part, cls, label, what, none] of (TAB === "archive" ? ARCHIVE_PARTS : PARTS)) {
    const discuss = part === "discuss";
    if (only && !discuss && only !== part) continue;  // « À discuter » always shows (06/10/2026)
    const items = shown.filter((r) => shownPart(r) === part);
    const open = items.filter(isOpen).length;
    const tofix = items.filter(isToFix).length;
    const hidden = discuss ? reports.filter((r) => shownPart(r) === part && shownTab(r) === TAB).length - items.length : 0;
    parts.push(el("h3", { class: "pc-group-title " + cls, id: discuss ? "pc-discuss" : null }, [
      el("span", { class: "pc-group-name", text: label }),
      el("span", { class: "pc-group-what", text: " · " + what }),
      el("span", { class: "pc-group-count", text: " — " + items.length + " report" + (items.length > 1 ? "s" : "") +
        (open || tofix ? T(", dont ") + [open ? open + T(" à traiter") : "", tofix ? tofix + T(" à corriger") : ""].filter(Boolean).join(T(" et ")) : "")
        + (hidden ? " · " + hidden + (hidden > 1 ? T(" masqués par les filtres") : T(" masqué par les filtres")) : "") }),
    ]));
    parts.push(...(items.length ? items.map(renderItem) : [el("div", { class: "pc-empty", text: hidden
      ? T("Masqués par les filtres : ") + hidden + " report" + (hidden > 1 ? "s" : "") + T(" à discuter.") : none })]));
  }
  // un export plus ancien, sans mode : après les parties
  parts.push(...shown.filter((r) => shownPart(r) === "").map(renderItem));
  $("#pc-list").replaceChildren(...parts);
}

function renderFreshness() {
  const age = DATA.age_seconds;
  $("#pc-fresh").textContent = T("— export du ") + stamp(DATA.generated_at) +
    (typeof age === "number" ? " (" + ago(age) + ")" : "");
  const stale = typeof age === "number" && age > STALE_SECONDS;
  $("#pc-stale").classList.toggle("hidden", !stale);
  $("#pc-stale").textContent = stale ? T("Dernier export du moniteur ") + ago(age) +
    T(" : le service price-check est peut-être arrêté (systemctl status price-check).") : "";
}

async function load() {
  if (LOADING) return;
  LOADING = true;
  setStatus(T("Lecture des reports…"), true);
  try {
    DATA = await api("api/price-check/reports");
    if (HASH_OFFER) {  // a link to one report opens the tab it is in
      const target = (DATA.reports || []).find((r) => String(r.offer) === HASH_OFFER);
      if (target) TAB = tabOf(target);
      HASH_OFFER = null;
    }
    $("#pc-error").classList.add("hidden");
    renderFreshness();
    render();
    setStatus((DATA.reports || []).length + T(" report(s) lus dans ") + DATA.dir, false);
  } catch (e) {
    $("#pc-error").textContent = T("Reports illisibles : ") + e.message;
    $("#pc-error").classList.remove("hidden");
    setStatus(T("Erreur : ") + e.message, false);
  } finally {
    LOADING = false;
  }
}

async function decide(offer, key) {
  if (BUSY.has(offer)) return;
  BUSY.add(offer);
  delete ERRORS[offer];
  const current = ((DATA && DATA.reports) || []).find((x) => String(x.offer) === offer) || {};
  const was = decisionKey(current);
  const part = shownPart(current), tab = shownTab(current);  // where the card is: it stays there a few seconds once decided
  // the note in the field: typed, or the saved one (another decision keeps it)
  const note = NOTES[offer] != null ? NOTES[offer] : ((current.decision && current.decision.note) || "");
  const typed = NOTES[offer];  // the field as it leaves: a note changed while saving is kept (audit Codex, 06/10/2026)
  render();
  setStatus(was === key ? T("Enregistrement de la note…") : T("Enregistrement de la décision…"), true);
  try {
    const res = await api("api/price-check/decision", { method: "POST",
      body: JSON.stringify({ offer, decision: key, note }) });
    const rec = res && res.recorded;
    if (!rec || rec.offer !== offer || rec.decision !== key) throw new Error(T("réponse inattendue du serveur"));
    const target = ((DATA && DATA.reports) || []).find((x) => String(x.offer) === offer);
    if (target) {
      target.history = [...(target.history || []), rec];
      target.decision = rec;
    }
    if (NOTES[offer] === typed) delete NOTES[offer];
    keepJustDone(offer, part, tab);
    setStatus((was === key ? T("Note enregistrée : ") : T("Décision enregistrée : ")) + ((target && target.product) || offer) +
      " — " + labelOf(key) + (note.trim() ? " — « " + note.trim() + " »" : ""), false);
  } catch (e) {
    ERRORS[offer] = e.message;
    setStatus(T("Décision non enregistrée : ") + e.message, false);
  } finally {
    BUSY.delete(offer);
    render();
  }
}

for (const id of ["#f-verdict", "#f-mode", "#f-decision", "#f-by", "#f-live", "#f-first"]) $(id).addEventListener("change", render);
$("#f-text").addEventListener("input", render);
$("#refresh").addEventListener("click", load);

// A link to one report (…/price-check#offer-<id>) opens the page filtered on that offer, in its tab.
let HASH_OFFER = null;
if (typeof location !== "undefined" && /^#offer-\d+$/.test(location.hash || "")) {
  HASH_OFFER = location.hash.slice("#offer-".length);
  $("#f-text").value = HASH_OFFER;
}
for (const tab of ["current", "archive"]) $("#tab-" + tab).addEventListener("click", () => { TAB = tab; render(); });

// Refresh in the background, but never under the operator's fingers: not while a note has
// the focus, not while a decision is being sent (typed notes survive a refresh anyway).
setInterval(() => {
  const a = document.activeElement;
  if (BUSY.size || (a && a.classList && a.classList.contains("pc-note"))) return;
  if (document.visibilityState === "hidden") return;
  load();
}, REFRESH_MS);

load();

// The « Comment trancher » box (05/10/2026): folded once, it stays folded on this browser.
(() => {
  const box = $("#pc-howto");
  if (!box) return;
  try { if (localStorage.getItem("pc-howto") === "closed") box.open = false; } catch (e) { /* no storage */ }
  box.addEventListener("toggle", () => {
    try { localStorage.setItem("pc-howto", box.open ? "open" : "closed"); } catch (e) { /* no storage */ }
  });
})();

// Leaving or reloading the page with a typed note not saved yet: the browser asks first (05/10/2026).
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("beforeunload", (ev) => {
    const reports = (DATA && DATA.reports) || [];
    if (!reports.some((r) => unsavedNote(String(r.offer), r))) return undefined;
    ev.preventDefault();
    ev.returnValue = "";
    return "";
  });
}

// ---- Concurrents (Romain, 06/10/2026) : « un widget par concurrent », pour les pages des tops ----
// « le meilleur prix en vert si AllKeyShop est moins cher, le meilleur prix du concurrent en rouge si AllKeyShop est plus
// cher, le premier prix AKS à côté » ; « couleur orange quand on est au même prix que le concurrent » ; « on compare clé
// avec clé et compte avec compte. On ne mélange pas. C'est une règle importante ». The monitor writes competitors.json
// every 30 min: for each top page, AllKeyShop's cheapest key (card fees included, as the page shows it) against each competitor's cheapest
// key (rows), and the accounts apart (accounts), when the competitor sells accounts. « Fee / error » : what an operator
// saw in the competitor's cart, + or − euros, kept in competitor-fees.jsonl for monitoring only.
let COMPETITORS = null;
const FEE_DRAFTS = {};  // fees typed and not saved yet, kept across a refresh
const euros = (n) => (typeof n === "number" ? n.toFixed(2).replace(".", ",") + " €" : "—");
const safeLink = (url, text) => (/^https?:\/\//i.test(String(url || ""))
  ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text }) : el("span", { text }));
const TONE = { "aks": "pc-win", "same": "pc-even", "competitor": "pc-lose" };
const cents = (n) => Math.round(n * 100);
// The competitor's offers, the cheapest of each seller, with the fee / error typed for that seller, the cheapest first
// (Romain, 06/10/2026 : « j'ai ajouté 20 € et ça ne se reflète pas sur le prix du concurrent » ; « pourquoi est-ce que va
// toujours Instant Gaming, premier prix, alors que j'y ai rajouté 20 € ? ») : the best offer once the fees are counted
// is the competitor's price, its colour and the counts follow it.
function offersOf(r) {
  const c = r.competitor;
  if (!c || typeof c.price !== "number") return [];
  const fees = r.fees || {};
  const base = (c.offers || []).filter((o) => o && typeof o.price === "number");
  return (base.length ? base : [{ price: c.price, seller: c.seller }]).map((o) => {
    const f = fees[o.seller] && typeof fees[o.seller].value === "number" ? fees[o.seller] : null;
    return { price: o.price, seller: o.seller, fee: f, total: f ? Math.round((o.price + f.value) * 100) / 100 : o.price };
  }).sort((x, y) => x.total - y.total || x.price - y.price);
}
// the same price to the cent is "same", even in an export written before the orange (it said "aks" for a tie)
function outcome(r) {
  const best = offersOf(r)[0];
  if (!best || !r.aks || typeof r.aks.price !== "number") return r.cheaper;
  return cents(r.aks.price) === cents(best.total) ? "same" : cents(r.aks.price) < cents(best.total) ? "aks" : "competitor";
}

const feeText = (v) => (typeof v === "number" ? (v > 0 ? "+" : "") + v.toFixed(2).replace(".", ",") : "");

// Fee / error (Romain, 06/10/2026 : « dans le prix concurrent, on puisse rajouter un fee à la main » ; « on peut l'appeler
// fee ou error, parce que si le prix du concurrent peut être inégal, on peut lui ajouter plus ou moins d'euros »)
// the box is for the seller of the offer shown; the fees typed for the other sellers stay listed, each can be cleared
function feeCell(site, kind, r) {
  const offers = offersOf(r), best = offers[0];
  if (!best) return el("td", { class: "pc-comp-fee" });
  const key = site.id + "|" + kind + "|" + r.page_url + "|" + best.seller;
  const box = el("input", { type: "text", inputmode: "decimal", class: "pc-fee", size: "6", maxlength: "9",
    placeholder: "± €", "aria-label": T("Fee / error chez ") + (best.seller || "?") + ", " + (r.product || "") });
  box.value = FEE_DRAFTS[key] != null ? FEE_DRAFTS[key] : (best.fee ? feeText(best.fee.value) : "");
  box.addEventListener("input", () => { FEE_DRAFTS[key] = box.value; });
  box.addEventListener("change", () => saveFee(site.id, kind, r, best.seller, box.value, key));
  const kids = [el("span", { class: "pc-fee-for", text: T("chez ") + (best.seller || "?") }), box];
  if (best.fee) kids.push(el("span", { class: "pc-fee-by", text: T("par ") + (best.fee.by || "?") + ", " + stamp(best.fee.at) }));
  for (const o of offers.slice(1).filter((x) => x.fee)) {
    kids.push(el("button", { type: "button", class: "pc-fee-clear", title: T("Effacer le fee / error saisi chez ") + o.seller,
      text: "✕ " + o.seller + " " + feeText(o.fee.value) + " €", onclick: () => saveFee(site.id, kind, r, o.seller, "", null) }));
  }
  return el("td", { class: "pc-comp-fee" }, kids);
}

async function saveFee(siteId, kind, r, seller, value, draftKey) {
  setStatus(T("Enregistrement du fee / error…"), true);
  try {
    const res = await api("api/price-check/competitors/fee", { method: "POST",
      body: JSON.stringify({ site: siteId, page_url: r.page_url, kind, seller, value }) });
    const rec = res && res.recorded;
    if (!rec || rec.page_url !== r.page_url || rec.site !== siteId || rec.seller !== seller) throw new Error(T("réponse inattendue du serveur"));
    r.fees = r.fees || {};
    if (typeof rec.value === "number") r.fees[seller] = rec; else delete r.fees[seller];
    if (draftKey) delete FEE_DRAFTS[draftKey];
    setStatus(typeof rec.value === "number" ? T("Fee / error enregistré : ") + (r.product || "") + ", " + seller + " " + feeText(rec.value) + " €"
      : T("Fee / error effacé : ") + (r.product || "") + ", " + seller, false);
  } catch (e) {
    setStatus(T("Fee / error non enregistré : ") + e.message, false);
  }
  renderCompetitors();
}

function compTable(site, rows, kind) {
  const account = kind === "account";
  const body = rows.map((r) => {
    const a = r.aks, c = r.competitor, tone = TONE[outcome(r)] || "";
    const offers = offersOf(r), best = offers[0];
    // « à la place de l'écart, mets le prix AKS » (Romain, 06/10/2026) : AllKeyShop's first price beside the competitor's
    return el("tr", {}, [
      el("td", {}, [safeLink(r.page_url, r.product || "?")]),
      el("td", { class: "pc-comp-price " + tone }, c && best ? [safeLink(c.url, euros(best.total)), " · " + (best.seller || "?"),
        best.fee ? el("span", { class: "pc-fee-total", text: T("dont fee / error ") + feeText(best.fee.value) + " € (" + euros(best.price) + T(" affiché)") }) : null,
        ...offers.slice(1).filter((o) => o.fee).map((o) => el("span", { class: "pc-fee-passed",
          text: o.seller + T(" : ") + euros(o.price) + " " + feeText(o.fee.value) + " € = " + euros(o.total) }))]
        : [r.skipped === "console" ? T("page console, non comparée") : T("introuvable")]),
      feeCell(site, kind, r),
      el("td", { class: "pc-comp-aks", text: a ? euros(a.price) + " · " + (a.merchant || "?") + (a.account && !account ? T(" (compte)") : "")
        : account ? T("pas de compte sur AKS") : "—" }),
    ]);
  });
  return el("div", { class: "table-wrap" }, [el("table", { class: "pc-comp-table" }, [
    el("thead", {}, [el("tr", {}, [el("th", { text: T("Jeu") }),
      el("th", { text: (account ? T("Meilleur compte ") : T("Meilleure clé ")) + (site.label || site.id) }),
      el("th", { text: "Fee / error", title: T("Ce que l'opérateur a vu au panier du concurrent : frais, ou prix faux, en euros, + ou −") }),
      el("th", { text: account ? T("Premier compte AKS") : T("Première clé AKS") })])]),
    el("tbody", {}, body)])]);
}

function competitorWidget(site) {
  const rows = site.rows || [];
  const won = rows.filter((r) => outcome(r) === "aks").length;
  const even = rows.filter((r) => outcome(r) === "same").length;
  const lost = rows.filter((r) => outcome(r) === "competitor").length;
  // a console page is not compared (the competitors give no price per console): not "introuvable"
  const consoles = rows.filter((r) => r.skipped === "console").length;
  const missing = rows.filter((r) => !r.competitor && !r.skipped).length;
  const blocked = site.status === "blocked";
  const head = el("div", { class: "pc-comp-head" }, [
    safeLink(site.home, site.label || site.id),
    blocked ? el("span", { class: "pc-comp-blocked", text: T("bloqué") })
      : el("span", { class: "pc-comp-score" }, [el("b", { class: "pc-win", text: String(won) }), T(" AKS moins cher · "),
        el("b", { class: "pc-even", text: String(even) }), T(" même prix · "),
        el("b", { class: "pc-lose", text: String(lost) }), T(" concurrent moins cher") +
        (missing ? " · " + missing + (missing > 1 ? T(" introuvables") : T(" introuvable")) : "") +
        (consoles ? " · " + consoles + (consoles > 1 ? T(" pages console non comparées") : T(" page console non comparée")) : "")]),
  ]);
  if (blocked) return el("section", { class: "pc-comp-card blocked" }, [head, el("p", { class: "pc-comp-msg", text: TM(site.message) || "" })]);
  // clé contre clé ; compte contre compte, à part, seulement quand le concurrent vend des comptes
  const kids = [head, el("h4", { class: "pc-comp-sub", text: T("Clés") }), compTable(site, rows, "key")];
  const accounts = site.accounts || [];
  if (accounts.length) {
    const count = (k) => String(accounts.filter((r) => outcome(r) === k).length);
    kids.push(el("h4", { class: "pc-comp-sub" }, [T("Comptes "), el("span", { class: "pc-comp-score" }, [
      el("b", { class: "pc-win", text: count("aks") }), T(" AKS moins cher · "), el("b", { class: "pc-even", text: count("same") }),
      T(" même prix · "), el("b", { class: "pc-lose", text: count("competitor") }), T(" concurrent moins cher")])]),
      compTable(site, accounts, "account"));
  }
  return el("section", { class: "pc-comp-card" }, kids);
}

function renderCompetitors() {
  const d = COMPETITORS;
  $("#pc-comp-note").textContent = d && d.available ? T("— relevé du ") + stamp(d.generated_at) +
    (typeof d.age_seconds === "number" ? " (" + ago(d.age_seconds) + ")" : "") : "";
  if (!d || !d.available) {
    $("#pc-competitors").replaceChildren(el("p", { class: "pc-empty",
      text: T("Pas encore de relevé des concurrents : le moniteur le fait toutes les 30 min pour les pages des tops.") }));
    return;
  }
  $("#pc-competitors").replaceChildren(...(d.sites || []).map(competitorWidget));
}

async function loadCompetitors() {
  try { COMPETITORS = await api("api/price-check/competitors"); } catch (e) { COMPETITORS = null; }
  renderCompetitors();
}
setInterval(() => { if (document.visibilityState !== "hidden") loadCompetitors(); }, REFRESH_MS);
loadCompetitors();

// ---- the two run buttons (Romain, 02/10/2026: « Price check top », « Price check homepage ») ----
// The admin never runs anything itself: it drops run-<mode>.request in the shared directory and the
// monitor (its own root process) reads it within seconds. status.json, written by the monitor, feeds the state.
const RUN_MODES = ["top-games", "homepage"];
const STATUS_MS = 10 * 1000;
let STATUS = null;

// "2026-10-02T17:55:21+0200" → seconds since midnight, as the server wrote it (no re-zoning)
function clockSeconds(s) {
  const m = /T(\d{2}):(\d{2}):(\d{2})/.exec(String(s || ""));
  return m ? (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) : null;
}
function duration(start, end) {
  const a = clockSeconds(start), b = clockSeconds(end);
  if (a == null || b == null) return "";
  let d = b - a;
  if (d < 0) d += 86400;
  if (d < 60) return d + " s";
  if (d < 3600) return Math.floor(d / 60) + " min " + String(d % 60).padStart(2, "0") + " s";
  return Math.floor(d / 3600) + " h " + String(Math.floor((d % 3600) / 60)).padStart(2, "0") + " min";
}

function renderRuns() {
  const st = STATUS;
  $("#pc-runs-note").textContent = st && st.available ? T("— état du moniteur ") + ago(st.age_seconds) : "";
  for (const mode of RUN_MODES) {
    const state = $("#state-" + mode), btn = $("#launch-" + mode);
    const pending = st && st.pending && st.pending[mode];
    if (!st || !st.available) {
      state.textContent = T("État du moniteur inconnu (status.json absent) : le bouton dépose quand même la demande.") +
        (pending ? T(" Demande en attente.") : "");
      btn.disabled = !!pending;
      continue;
    }
    const m = st.modes[mode];
    if (!m) { state.textContent = T("Mode non suivi par le moniteur."); btn.disabled = true; continue; }
    const parts = [];
    if (m.running) {
      parts.push(T("En cours") + (m.progress ? T(" : page ") + m.progress[0] + " / " + m.progress[1] : "") +
        (m.requested_by ? T(" (demandé par ") + TM(m.requested_by) + ")" : ""));
    } else if (m.last_end) {
      // a pass only checks offers never seen before: a quiet pass is the normal case, say so
      const about = [duration(m.last_start, m.last_end), m.pages ? m.pages + T(" pages lues") : "",
        m.last_requested_by ? T("lancé depuis l'admin par ") + TM(m.last_requested_by) : ""].filter(Boolean).join(", ");
      parts.push(T("Dernier passage ") + stamp(m.last_start) + (about ? " (" + about + ")" : "") + T(" : ") +
        (m.last_checked ? m.last_checked + T(" nouvelle(s) offre(s) contrôlée(s)") : T("aucune nouvelle offre à contrôler")) +
        ", " + (m.last_alerts || 0) + T(" alerte(s)"));
    }
    const rc = m.last_recheck;
    if (rc && rc.at) {
      parts.push((rc.kind === "all" ? T("Recontrôle complet ") : T("Recontrôle des offres signalées ")) + stamp(rc.at) + T(" : ") +
        (rc.checked || 0) + T(" offre(s), ") + (rc.fixed || 0) + T(" réparée(s), ") +
        (rc.rules ? rc.rules + T(" faux positif(s) levé(s) par une règle, ") : "") +
        (rc.verified ? rc.verified + T(" vérifiée(s) OK, ") : "") + (rc.new || 0) + T(" nouvelle(s) erreur(s), ") +
        (rc.still || 0) + T(" toujours en erreur"));
    }
    if (!m.running && m.next_at) parts.push(T("prochain passage ") + stamp(m.next_at));
    if (pending) parts.push(T("demande en attente") + (pending.by ? " (" + pending.by + ")" : ""));
    state.textContent = parts.join(" · ") || T("Aucun passage encore.");
    btn.disabled = !!pending || !!m.running;
  }
}

// Romain, 08/10/2026 : « un bouton Recalcule ou, toi, penser à recalculer lorsqu'on fait une modification » : the monitor
// re-checks the open reports at each start (a rule change restarts it) and on this request; its state is status.recalc.
const RECALC_AT_START = "the monitor's start";

function renderRecalc() {
  const st = STATUS, state = $("#state-recalc"), btn = $("#launch-recalc");
  const pending = st && st.pending_recalc;
  const rc = st && st.available ? st.recalc : null;
  const parts = [];
  if (rc && rc.running) {
    parts.push(T("Recalcul en cours") + (rc.by && rc.by !== RECALC_AT_START ? T(" (demandé par ") + TM(rc.by) + ")" : ""));
  } else if (rc && rc.end) {
    parts.push(T("Dernier recalcul ") + stamp(rc.at) +
      (rc.by === RECALC_AT_START ? T(" au démarrage du moniteur") : T(" (demandé par ") + TM(rc.by || "?") + ")") + T(" : ") +
      (rc.offers || 0) + T(" offre(s), ") + (rc.fixed || 0) + T(" réparée(s), ") +
      (rc.rules ? rc.rules + T(" faux positif(s) levé(s) par une règle, ") : "") +
      (rc.verified ? rc.verified + T(" vérifiée(s) OK, ") : "") + (rc.still || 0) + T(" toujours en erreur") +
      (rc.unknown ? ", " + rc.unknown + T(" sans conclusion") : ""));
  }
  if (pending) parts.push(T("demande en attente") + (pending.by ? " (" + pending.by + ")" : ""));
  state.textContent = parts.join(" · ") || T("Aucun recalcul encore.");
  btn.disabled = !!pending || !!(rc && rc.running);
}

async function loadStatus() {
  try { STATUS = await api("api/price-check/status"); } catch (e) { STATUS = null; }
  renderRuns();
  renderRecalc();
}

async function launchRecalc() {
  const btn = $("#launch-recalc"), msg = $("#msg-recalc");
  btn.disabled = true;
  msg.textContent = "";
  try {
    const r = await api("api/price-check/recalc", { method: "POST", body: JSON.stringify({}) });
    const who = r && r.requested && r.requested.by ? T(" par ") + r.requested.by : "";
    msg.textContent = T("Demande déposée") + who + T(" : le moniteur la lit dans les secondes qui viennent.");
  } catch (e) {
    msg.textContent = T("Refusé : ") + e.message;
    btn.disabled = false;
  }
  await loadStatus();
}

async function launch(mode) {
  const btn = $("#launch-" + mode), msg = $("#msg-" + mode);
  btn.disabled = true;
  msg.textContent = "";
  try {
    const r = await api("api/price-check/run", { method: "POST", body: JSON.stringify({ mode }) });
    const who = r && r.requested && r.requested.by ? T(" par ") + r.requested.by : "";
    msg.textContent = T("Demande déposée") + who + T(" : le moniteur la lit dans les secondes qui viennent.");
  } catch (e) {
    msg.textContent = T("Refusé : ") + e.message;
    btn.disabled = false;
  }
  await loadStatus();
}

for (const mode of RUN_MODES) $("#launch-" + mode).addEventListener("click", () => launch(mode));
$("#launch-recalc").addEventListener("click", launchRecalc);
setInterval(() => { if (document.visibilityState !== "hidden") loadStatus(); }, STATUS_MS);
loadStatus();

// ---- Console Claude (Romain, 06/10/2026) ----
// « une console pour pouvoir en discuter en temps réel depuis l'admin, sur ce même onglet Price check » ; Romain, Rémy,
// Garance et Lionel ; « pour les modifications sur le code, il faudra passer par moi ». The admin runs nothing: a message
// becomes a request file for the console service (price-check-console, root), which answers into console.json. Anyone
// else gets a 403 and the card stays hidden. A question for Romain goes to the Romain tab.
let CHAT = null, CHAT_TIMER = null;
const CHAT_FAST_MS = 3000, CHAT_SLOW_MS = 20000;
const CHAT_KIND = { "claude": "from-claude", "console": "from-console" };

function chatMessage(m) {
  const kids = [el("div", { class: "pc-chat-head" }, [el("b", { text: m.label || m.user || "?" }), " · " + stamp(m.at)]),
    el("div", { class: "pc-chat-text", text: (m.user === "console" || m.text === "Récolte des décisions sur les feedbacks des reports" ? TM(m.text) : m.text) || "" })];
  if (m.error) kids.push(el("div", { class: "pc-chat-error", text: m.error }));
  const q = m.questions || {};
  if ((q.opened || []).length) {
    kids.push(el("div", { class: "pc-chat-q" }, ["→ " + q.opened.join(", ") + (q.opened.length > 1
      ? T(" : questions pour Romain, dans l'onglet ") : T(" : question pour Romain, dans l'onglet ")), el("a", { href: "romain", text: "Romain" })]));
  }
  if ((q.closed || []).length) {
    kids.push(el("div", { class: "pc-chat-q", text: "✓ " + q.closed.join(", ") + (q.closed.length > 1 ? T(" réglées") : T(" réglée")) }));
  }
  return el("div", { class: "pc-chat-msg " + (CHAT_KIND[m.user] || "from-team") + (m.kind === "error" ? " is-error" : "") }, kids);
}

function renderChat() {
  const d = CHAT;
  $("#pc-console").classList.toggle("hidden", !d);
  if (!d) return;
  const owner = d.role === "owner";
  $("#pc-harvest").classList.toggle("hidden", !owner);
  $("#pc-new-session").classList.toggle("hidden", !owner);
  const msgs = d.messages || [];
  $("#pc-console-log").replaceChildren(...(msgs.length ? msgs.map(chatMessage) : [el("p", { class: "pc-empty",
    text: d.available ? T("Pas encore de message : écris à Claude ci-dessous.")
      : T("Le service de la console (price-check-console) n'a pas encore répondu.") })]));
  $("#pc-console-log").scrollTop = 1e9;
  const waiting = (d.pending || []).length;
  $("#pc-console-note").textContent = d.busy ? T("— Claude répond à ") + (d.busy.label || d.busy.user) +
    (d.busy.progress ? " (" + d.busy.progress + ")" : "") + "…"
    : waiting ? "— " + waiting + " message" + (waiting > 1 ? "s" : "") + T(" en attente") : "";
}

async function loadChat() {
  try { CHAT = await api("api/price-check/console"); } catch (e) { CHAT = null; }
  renderChat();
  clearTimeout(CHAT_TIMER);
  if (CHAT) CHAT_TIMER = setTimeout(loadChat, CHAT.busy || (CHAT.pending || []).length ? CHAT_FAST_MS : CHAT_SLOW_MS);
}

async function sendChat(path, body, done) {
  try {
    await api(path, { method: "POST", body: JSON.stringify(body || {}) });
  } catch (e) {
    setStatus(T("Console : ") + e.message, false);
    return false;
  }
  setStatus(done, false);
  loadChat();
  return true;
}

async function sendChatMessage() {
  const box = $("#pc-console-text"), send = $("#pc-console-send"), text = box.value.trim();
  if (!text || send.disabled) return;
  send.disabled = true;
  if (await sendChat("api/price-check/console", { text, lang: LANG }, T("Message envoyé : Claude répond dans la console"))) box.value = "";
  send.disabled = false;
}
$("#pc-console-form").addEventListener("submit", (ev) => { ev.preventDefault(); sendChatMessage(); });
$("#pc-console-text").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendChatMessage(); }
});
$("#pc-harvest").addEventListener("click", () => sendChat("api/price-check/console/harvest", { lang: LANG },
  T("Récolte demandée : Claude relit les décisions ; ses points à trancher iront dans l'onglet Romain")));
$("#pc-new-session").addEventListener("click", () => sendChat("api/price-check/console/new-session", {},
  T("Nouvelle session demandée : Claude repart de zéro")));
loadChat();

// ---- FR / EN : the fixed texts of the page (07/10/2026) ----
// The texts exist in both languages in pricecheck.html (lang="fr" / lang="en"); pricecheck.css shows the page's own.
// The attributes (title, placeholder, aria-label) and the filters' options are translated here.
if (document.documentElement) {
  document.documentElement.setAttribute("data-lang", LANG);
  document.documentElement.setAttribute("lang", LANG);
}
const STATIC_ATTRS = { "refresh": ["title"], "guide-link": ["title"], "theme": ["title"], "launch-top-games": ["title"],
  "launch-homepage": ["title"], "launch-recalc": ["title"], "pc-harvest": ["title"], "pc-new-session": ["title"], "pc-console-text": ["placeholder", "aria-label"],
  "f-text": ["placeholder"] };
for (const [id, keys] of Object.entries(STATIC_ATTRS)) {
  const n = $("#" + id);
  for (const k of keys) if (n && n.getAttribute && n.getAttribute(k)) n.setAttribute(k, T(n.getAttribute(k)));
}
if (LANG === "en" && document.querySelectorAll) {
  try {
    for (const o of document.querySelectorAll("#f-verdict option, #f-mode option, #f-decision option")) o.textContent = VERDICT_EN[o.textContent] || T(o.textContent);
  } catch (e) { /* a page without them */ }
}
(() => {
  const btn = $("#lang");
  if (!btn) return;
  btn.textContent = LANG === "en" ? "FR" : "EN";
  btn.setAttribute("title", LANG === "en" ? "Passer en français" : "Switch to English");
  btn.addEventListener("click", () => {
    try { localStorage.setItem("aks-lang", LANG === "en" ? "fr" : "en"); } catch (e) { /* no storage */ }
    if (typeof location !== "undefined") location.reload();
  });
})();
