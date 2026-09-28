# 0004. Exposer les outils par MCP plutôt que d'appeler l'API depuis l'application

Statut : accepté, 2026-09-28.

## Contexte

Il faut donner à un modèle un accès contrôlé aux livres d'un client.

## Options

1. **Appel direct à l'API** depuis l'application, avec l'usage d'outils (tool use) : l'application
   pilote la boucle, choisit le modèle, garde les journaux.
2. **Serveur MCP** : les outils sont décrits une fois et utilisables depuis Claude Desktop, Claude
   Code ou tout client MCP, par l'équipe elle-même.

## Décision

Option 2 pour cette maquette. Les mêmes six outils servent à l'équipe dans Claude Desktop et à un
agent lancé en tâche de fond (`claude -p` avec `--mcp-config`, voir le README). Les tests pilotent
le serveur par un vrai client MCP, en mémoire et en sous-processus stdio, sans aucun modèle.

## Conséquences

- On change de modèle sans toucher au code : les deux essais du README utilisent deux modèles.
- Limite : transport stdio, donc un poste et un utilisateur, sans authentification. Pour une équipe,
  il faudrait le transport HTTP, une authentification et un journal des appels par utilisateur.
- Si la fiduciaire veut une boucle entièrement intégrée à son application (planification, reprise
  sur erreur, coût maîtrisé), l'option 1 redevient la bonne, et le module `books` se réutilise tel
  quel : le serveur MCP n'en est qu'une façade.
