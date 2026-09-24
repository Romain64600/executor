# API AKS « import-router » : notes pour le chantier prepaid

Romain, 2026-09-24 : « Prends bonne note pour le chantier prepaid qui arrive : API. »

**Statut : notes seulement.** Aucun code n'appelle cette API. Aucune requête n'a été envoyée, et
on n'a ni clé ni jeton. Ce document garde ce que l'équipe AKS a transmis, tel quel, avec la
lecture qu'on en fait et les questions à lui renvoyer avant d'écrire une ligne.

Pourquoi c'est important : aujourd'hui, **toute écriture passe par le navigateur**. On ouvre la
modale du feed marchand, on choisit la région et l'édition, on clique sur « Create offer », puis
on vérifie que la ligne a disparu du feed (`docs/SUBMITTER_SPEC.md`). Une API d'écriture
remplacerait ce chemin, au moins pour les prepaids. Elle n'enlèverait aucune des règles
d'`AGENTS.md` (fichier de validation, dry-run par défaut, fail-closed, journaux JSONL, preuve
après écriture).

---

## 1. Mettre à jour une offre existante : `bulk-update-record`

```
POST https://api.allkeyshop.com/import-router/router/bulk-update-record
```

Charge utile transmise (syntaxe PHP d'origine, **verbatim**) :

```php
[
    'model' => 'offer',
    'where' => ['id' => {offer id}],
    'data' => [
        'float_price' => 0
        'stock' => 'out_of_stock'
        'fees' => [
            'card' => 0,
            'paypal' => 0
        ],
        'coupon' => {coupon id}
    ],
]
```

La même chose en JSON, comme on l'enverrait (la virgule manque après `'float_price' => 0`
dans l'original) :

```json
{
  "model": "offer",
  "where": { "id": 123456 },
  "data": {
    "float_price": 0,
    "stock": "out_of_stock",
    "fees": { "card": 0, "paypal": 0 },
    "coupon": 789
  }
}
```

Lecture :

- `model: "offer"` : on modifie une **offre** AKS, pas une ligne du feed marchand.
- `where.id` : l'identifiant de l'**offre AKS**. Ce n'est pas l'`offer_id` du feed (par
  exemple `100614090`) que le pipeline manipule aujourd'hui.
- `data` : les champs à écrire. L'exemple met l'offre en rupture (`out_of_stock`, prix 0).
- `fees` a ici la forme **imbriquée** `{card, paypal}`, alors qu'à la création ce sont deux
  champs à plat, `fees_card` et `fees_paypal` (§2). Il faut confirmer que ce n'est pas une
  coquille.

## 2. Créer une offre : les paramètres

Tableau transmis, **verbatim** :

| Paramètre               | Type                            | Obligatoire | Description                       |
| ----------------------- | ------------------------------- | ----------- | ----------------------------------|
| url                     | string                          | Oui         |                                   |
| affiliate_url           | string                          | Oui         |                                   |
| price                   | int                             | Oui         | Prix en centimes                  |
| float_price             | float                           | Oui         | Prix décimal                      |
| product_type            | string                          | Oui         | "videogame" ou "product_prepaid"  |
| product_id              | int                             | Oui         | Id du produit                     |
| stock                   | string                          | Oui         | Slug du stock                     |
| store                   | int                             | Oui         | Id du store                       |
| currency                | string                          | Oui         | Code de la currency, sur 3 lettres|
| geo_preset_buyable      | int \| string                   |             | Id ou slug                        |
| geo_preset_activable    | int \| string                   |             | Id ou slug                        |
| geo_preset_usable       | int \| string                   |             | Id ou slug                        |
| coupon                  | int \| null                     |             | Id du coupon                      |
| delivery_type           | int \| string \| null           |             | Slug du type de livraison         |
| legacy_id               | int \| null                     |             | Id dans pt_product                |
| fees_card               | float                           |             | Exprimé en unité, pas en cents    |
| fees_paypal             | float                           |             | Exprimé en unité, pas en cents    |

Notes transmises avec le tableau :

- **`price` OU `float_price`** : au moins l'un des deux, **jamais les deux à la fois**.
  Le tableau marque pourtant les deux « Obligatoire : Oui » ; c'est la note qui fait foi.
- Certaines valeurs attendent des **slugs précis**, notamment `stock` et `delivery_type`. L'équipe
  AKS doit nous les donner.

### Ce que le pipeline sait déjà fournir

| Paramètre | D'où on le tirerait aujourd'hui | Certitude |
|---|---|---|
| `store` | le `store_id` du feed (Kinguin 58, GameSeal 126…) | à confirmer : même numérotation ? |
| `url` | l'URL marchand de la ligne du feed | probable |
| `affiliate_url` | inconnue : le feed ne la donne pas telle quelle | **à demander** |
| `product_id` | l'id produit lu sur la page AKS (`aks_product_id`, ex. 44053) | à confirmer, voir `legacy_id` |
| `price` / `float_price` | le prix de la ligne du feed (`price: "9.55"`) | probable, en `float_price` |
| `currency` | la devise du feed | **à demander** : le feed ne l'expose pas partout |
| `stock` | la colonne stock du feed (`u`, `n`…) → slug | slugs **à fournir** |
| `geo_preset_*` | la région qu'on choisit aujourd'hui dans la modale (Global 2, Europe, Steam Gift 25…) | **à demander** : correspondance inconnue |
| `product_type` | `videogame` pour les clés, `product_prepaid` pour le chantier | clair |

## 3. Questions à renvoyer à l'équipe AKS

Classées de la plus bloquante à la moins bloquante.

1. **L'URL de l'endpoint de création.** Seule `bulk-update-record` a été donnée.
2. **L'authentification.** En-tête, jeton, clé par utilisateur ? Où la ranger ? Chez nous ce
   sera `.env`, jamais le dépôt ni un journal (`AGENTS.md`).
3. **La réponse.** Quel format, quel code HTTP en cas de succès ou d'échec ? Est-ce qu'elle
   **rend l'id de l'offre créée** ? Il nous le faut pour `bulk-update-record` et pour la preuve.
4. **L'édition.** La modale actuelle demande une **région et une édition** (Standard 1, Deluxe 7,
   DLC 16…). Aucun paramètre d'édition n'apparaît. Est-ce que `product_id` désigne déjà
   l'édition ? Et pour un prepaid, la question se pose-t-elle ?
5. **Les trois `geo_preset`.** Que veulent dire *buyable*, *activable* et *usable* ? Quelle est
   la liste des ids et des slugs ? Quelle correspondance avec les régions de la modale
   (Steam Gift 25, GOG GLOBAL 6, Europe…) ? Que se passe-t-il si on n'en envoie aucun ?
6. **`product_id` et `legacy_id`.** L'id « du produit » est-il celui qu'on lit sur la page AKS ?
   Et `legacy_id`, « id dans pt_product », quand faut-il l'envoyer ?
7. **Le feed marchand.** Une offre créée par l'API **retire-t-elle la ligne en attente** du
   feed, comme le fait la modale (« The feed entry #… has been deleted ») ? Sinon, notre preuve
   de succès (la ligne disparue du feed) ne vaut plus, et il faut une relecture par l'API.
8. **Les doublons.** Créer deux fois la même offre (même store, même produit, même région) :
   refus, doublon ou mise à jour ? Nos balayages peuvent retomber sur une ligne déjà traitée.
9. **Les listes de valeurs.** Les slugs de `stock` et de `delivery_type`, et les codes
   `currency` acceptés.
10. **Les frais.** `fees_card` / `fees_paypal` sont-ils un montant ou un pourcentage ? À la
    mise à jour, `fees` est-il bien imbriqué (`{card, paypal}`) ?
11. **Le volume.** Une limite de débit ? `bulk-update-record` accepte-t-il **plusieurs**
    enregistrements par appel ? Le mot *bulk* le laisse penser, mais l'exemple n'en montre qu'un.
12. **Un environnement de test.** Existe-t-il un bac à sable ? Sinon, un store de test sur lequel
    faire le premier essai.
13. **Supprimer ou désactiver** une offre créée par erreur : l'API le permet-elle ?

## 4. Ce qu'on s'imposera quand on le construira

Rien de nouveau : ce sont les règles d'`AGENTS.md`, appliquées à un appel HTTP au lieu d'un clic.

- **Dry-run par défaut.** Le script écrit la liste des appels qu'il ferait, sans en envoyer aucun.
- **Fichier de validation obligatoire.** On n'appelle l'API qu'à partir d'un `approved.json`,
  jamais d'une mémoire ou d'un vieux lot.
- **Succès déterministe.** On se fie au code HTTP et au champ d'erreur de la réponse, puis à
  une **preuve relue** : la ligne disparue du feed, ou l'offre relue par l'API. Jamais une
  estimation du modèle.
- **Journal JSONL** de chaque appel : requête sans le jeton, réponse, preuve.
- **Arrêt au premier doute** : réponse illisible, 4xx/5xx, preuve absente. On s'arrête et on
  écrit un rapport d'erreur, on ne réessaie pas en boucle.
- **Pas de dépendance nouvelle.** `urllib` suffit.
