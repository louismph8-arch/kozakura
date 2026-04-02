# 🌸 Kozakura Bot

Bot Discord de modération avancée avec IA pour serveur francophone.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.x-blue)
![Railway](https://img.shields.io/badge/Hosted-Railway-purple)

---

## ✨ Fonctionnalités

### 🔨 Modération
- Ban, kick, mute, unmute, warn, purge, clear
- Mass ban avec confirmation (`!massban`)
- Sanctions progressives avec historique complet
- Système de tribunal avec votes (`!tribunal`)

### 🎫 Tickets
- 4 catégories : Gestion Staff, Gestion Abus, C.O.D, Partenariat
- Claim, add/remove membres, fermeture avec raison
- Résumé IA automatique à la fermeture

### 🎖️ Rangs
- 6 niveaux : `***` Mirai → `I` Kage
- Rank up / Derank / Setrank automatique

### 🏆 XP & Niveaux
- XP texte + vocal fusionnés
- Level up dans le salon dédié
- Leaderboard, trophées, badges

### 🎉 Giveaways
- Durée flexible, conditions (messages min, être en vocal)
- Reroll, fin anticipée

### 🤖 Intelligence Artificielle (Groq / Llama 3)
- Réponses automatiques dans `🧠・ia`
- `!ai`, `!imagine`, `!traduis`, `!analyse`, `!resume`
- `!announce` génération d'annonces
- Modération IA contextuelle (`!moderia`)
- Réponses adaptées selon le profil (nouveau/vétéran)

### 🔒 Sécurité Avancée
- Anti-nuke (détection suppression masse)
- Anti-raid automatique
- Anti-spam vocal et messages
- Détection comptes suspects à l'arrivée
- Détection usurpation d'identité staff
- Honeypot (salon piège)
- Lockdown d'urgence (`!lockdown`)
- Freeze/Unfreeze membre
- Quarantaine
- Backup + restauration serveur
- `!whois` avec score de risque

### 📊 Stats & Rapports
- `!activite` fiche complète membre
- `!rapport` hebdomadaire automatique (lundi 9h)
- Logs séparés : `logs-bans`, `logs-messages`, `log-photos`, `log-vocs`

---

## 🚀 Installation

### Prérequis
- Python 3.11+
- Compte Railway
- Clé API Groq (gratuite)

### Variables d'environnement
```
TOKEN=ton_token_discord
DASHBOARD_SECRET=ta_clé_secrète
GROQ_API_KEY=ta_clé_groq
```

### Lancement local
```bash
pip install -r requirements.txt
python bot.py
```

---

## 📋 Commandes principales

| Catégorie | Commande | Description |
|-----------|----------|-------------|
| Modération | `!ban @membre [raison]` | Bannit un membre |
| Modération | `!mute @membre [min]` | Mute temporaire |
| Rangs | `!rankup @membre` | Monte d'un rang |
| Tickets | `!ticketpanel` | Crée le panel tickets |
| IA | `!ai [question]` | Pose une question |
| IA | `!traduis [langue] [texte]` | Traduction |
| Sécurité | `!lockdown` | Verrouille le serveur |
| Sécurité | `!freeze @membre` | Coupe les permissions |
| Fun | `!dog @membre` | Mode dog vocal |
| Fun | `!pic @membre` | Photo de profil |
| Stats | `!activite @membre` | Stats détaillées |

Tape `!help` pour la liste complète des commandes.

---

## ⚙️ Configuration

```
!setlog #salon          → Logs généraux
!setwelcome #salon      → Salon bienvenue
!setautorole @role      → Rôle automatique
!setticketcategory nom  → Catégorie tickets
!setantibotprotection   → Protection anti-bot
!sethoneypot            → Salon piège
!setminage [jours]      → Âge minimum comptes
```

---

## 🏗️ Architecture

```
KozakuraBot/
├── bot.py              # Bot principal (~5500 lignes)
├── requirements.txt    # Dépendances
├── Procfile            # Config Railway
├── .python-version     # Python 3.11
├── .gitignore
└── data/               # Données JSON (auto-créé)
    ├── sanctions.json
    ├── xp.json
    ├── tickets.json
    ├── trophees.json
    └── ...
```

---

## 📡 Dashboard Web

Interface web de gestion disponible via `dashboard.html`.

Connecte-toi avec l'URL Railway + ta clé `DASHBOARD_SECRET`.

Fonctionnalités : membres, sanctions, tickets, XP, trophées, giveaways, rôles, rangs, vocal en direct, logs temps réel, envoi de messages.

---

## 📜 Licence

Projet privé — Kozakura © 2026
