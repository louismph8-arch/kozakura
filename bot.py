"""
╔══════════════════════════════════════════════════════════════╗
║           🤖 BOT DISCORD — MODÉRATION COMPLÈTE              ║
║     + Système de tickets avancé avec 4 catégories           ║
╚══════════════════════════════════════════════════════════════╝
pip install discord.py
python bot.py
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, re, time, asyncio, aiohttp, random, sys
from datetime import datetime, timedelta
from collections import defaultdict

# ─── ANTHROPIC AI (Claude) ────────────────────────────────────────────────────
import anthropic as _anthropic

ANTHROPIC_API_KEY = (
    os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("CLAUDE_API_KEY")
    or os.getenv("ANTHROPIC_KEY")
    or ""
)
CLAUDE_MODEL = "claude-haiku-4-5"  # Mis à jour si nécessaire

# Historique des conversations par utilisateur {user_id: [messages]}
ai_conversations = {}
AI_MAX_HISTORY   = 10  # Messages max gardés en mémoire

# Salons où le bot répond automatiquement (contient ces mots dans le nom)
AI_AUTO_CHANNELS = ["ia", "ai", "bot", "kozakura", "discussion", "general", "général"]

# Salons où le bot ne répond JAMAIS automatiquement
AI_IGNORE_CHANNELS = ["sanction", "logs", "ticket", "tribunal", "rank"]

SYSTEM_PROMPT = """Tu es Kozakura, le bot intelligent d'un serveur Discord francophone.
Tu es serviable, sympathique et tu réponds en français.
Tu peux aider avec des questions générales, discuter, aider avec du code,
expliquer des concepts, et modérer intelligemment.
Tu connais les commandes du bot : !ban, !kick, !mute, !warn, !rank, !help, etc.
Réponds de manière concise (max 300 mots) et adaptée à Discord.
Si quelqu'un semble en conflit ou agressif, reste calme et professionnel.
Ne mentionne jamais que tu es une IA Anthropic/Claude — tu es Kozakura."""

async def call_claude(messages: list, member_ctx: dict = None) -> str:
    """Appelle l'API Claude (Anthropic) et retourne la réponse"""
    if not ANTHROPIC_API_KEY:
        return "❌ Clé API Anthropic non configurée."

    # Système adaptatif selon le profil du membre
    system = SYSTEM_PROMPT
    if member_ctx:
        days   = member_ctx.get("days", 0)
        level  = member_ctx.get("level", 0)
        sancs  = member_ctx.get("sanctions", 0)
        if days < 7:
            system += "\nCe membre est NOUVEAU sur le serveur (moins de 7 jours). Sois particulièrement accueillant, explique les fonctionnalités de base."
        elif days > VETERAN_DAYS and level > 10:
            system += "\nCe membre est un VÉTÉRAN actif du serveur. Tu peux être plus direct et utiliser un ton plus familier."
        if sancs > 3:
            system += "\nCe membre a eu des sanctions par le passé. Reste professionnel et neutre."

    try:
        client = _anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=system,
            messages=messages
        )
        return response.content[0].text.strip()
    except _anthropic.BadRequestError as e:
        msg = getattr(e, 'message', str(e))
        print(f"[Claude] BadRequest: {msg}")
        return f"❌ Requête invalide : {str(msg)[:150]}"
    except _anthropic.AuthenticationError:
        print("[Claude] Clé API invalide !")
        return "❌ Clé API Anthropic invalide — vérifie la variable ANTHROPIC_API_KEY dans Railway."
    except _anthropic.NotFoundError as e:
        # Modèle introuvable → fallback automatique
        print(f"[Claude] Modèle '{CLAUDE_MODEL}' introuvable, tentative avec claude-3-5-haiku-20241022")
        try:
            client2 = _anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            response2 = await client2.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                system=system,
                messages=messages
            )
            return response2.content[0].text.strip()
        except Exception as e2:
            return f"❌ Modèle IA indisponible : {str(e2)[:100]}"
    except _anthropic.RateLimitError:
        return "⏰ Limite de requêtes atteinte, réessaie dans un moment !"
    except _anthropic.APIConnectionError:
        return "❌ Impossible de contacter l'API Claude."
    except Exception as e:
        print(f"[Claude] Erreur inattendue : {e}")
        return f"❌ Erreur : {str(e)[:100]}"

async def detect_conflict(content: str) -> bool:
    """Détecte si un message est potentiellement conflictuel"""
    conflict_words = [
        "je vais te", "ta gueule", "ferme la", "nique", "bâtard",
        "connard", "salope", "fdp", "va te", "idiot", "stupide",
        "merde", "enculé", "insulte", "menace"
    ]
    low = content.lower()
    return any(w in low for w in conflict_words)


# ─── CONFIGURATION ────────────────────────────────────────────────────────────
TOKEN  = os.getenv("DISCORD_TOKEN", "")
PREFIX = "!"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─── PERSISTANCE JSON ─────────────────────────────────────────────────────────
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def load_json(name, default=None):
    if default is None:
        default = {}
    p = f"{DATA_DIR}/{name}"
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(name, data):
    with open(f"{DATA_DIR}/{name}", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

warnings_db    = load_json("warnings.json", {})
xp_db          = load_json("xp.json", {})
config_db      = load_json("config.json", {})
custom_cmds_db = load_json("custom_commands.json", {})
reminders_db   = load_json("reminders.json", {})
reaction_roles = load_json("reaction_roles.json", {})
tickets_db     = load_json("tickets.json", {})
nsfw_words_db  = load_json("nsfw_words.json", {"words": []})
user_prefs_db  = load_json("user_prefs.json", {})   # pseudo préféré IA
banned_db      = load_json("banned_members.json", {})  # historique bannis
autotrad_db    = load_json("autotrad.json", {})     # {guild_id: {channel_id: bool}}
titles_db      = load_json("titles.json", {})       # {guild_id: {user_id: title}}
watchlist_db   = load_json("watchlist.json", {})    # {guild_id: {user_id: {reason, by, date}}}
shadowban_db   = load_json("shadowban.json", {})    # {guild_id: {user_id: True}}
reports_db     = load_json("reports.json", {})      # {guild_id: [{reporter, target, reason, date}]}
giveaway_db    = load_json("giveaways.json", {})    # {guild_id: {message_id: {...}}}
starboard_db   = load_json("starboard.json", {})    # {guild_id: {message_id: starboard_msg_id}}
afk_db         = load_json("afk.json", {})          # {guild_id: {user_id: {reason, since}}}
birthdays_db   = load_json("birthdays.json", {})    # {guild_id: {user_id: "DD/MM"}}
tempbans_db    = load_json("tempbans.json", {})      # {guild_id: {user_id: {unban_at, reason}}}
streaks_db     = load_json("streaks.json", {})       # {guild_id: {user_id: {last_date, streak}}}
ticket_stats_db = load_json("ticket_stats.json", {}) # {guild_id: {user_id: {claims, closes, last_activity}}}

# ─── VARIABLES EN MÉMOIRE ─────────────────────────────────────────────────────
message_tracker  = defaultdict(list)
raid_tracker     = []
xp_cooldowns     = {}
BANNED_WORDS     = ["badword1", "badword2"]

# NSFW_WORDS : liste de base fusionnée avec la DB persistante
_NSFW_BASE = [
    "envoie des nudes", "envoie tes nudes", "envoie moi tes nudes",
    "montre tes seins", "montre ta bite", "montre ton cul",
    "t'as des nudes", "tu as des nudes", "tes nudes",
    "send nudes", "send pics", "nude stp", "nude svp",
    "photo intime", "photos intimes", "video intime",
    "suce moi", "lèche moi", "lache moi", "baise moi",
    "viens baiser", "on baise", "tu veux baiser",
    "je veux te baiser", "je vais te niquer",
    "tu veux sucer", "tu veux te faire",
    "cam privée", "cam privee", "cam sex", "snap privé",
    "echange photo", "échange photo", "echange snap",
    "montre toi nue", "montre toi nu",
    "t'es chaude", "t as chaud", "t'es bonne",
    "sextape", "sex tape",
]
# Fusionner base + mots ajoutés via !addnsfw (persistés en JSON)
NSFW_WORDS = list({*_NSFW_BASE, *nsfw_words_db.get("words", [])})

# Mots-clés NSFW pour la détection IA (réponse éducative plutôt que sanction)
NSFW_AI_PATTERNS = [
    "nudes", "nude", "photo intime", "content sexuel", "contenu sexuel",
    "envoie moi", "montre toi", "harcèlement", "harcelement",
]

# Salons "confidentiels" — alert si image envoyée
PRIVATE_CHANNEL_KEYWORDS = ["privé", "prive", "confidentiel", "staff", "admin", "direction", "secret"]

# ── Anti-copypasta multi-salons ───────────────────────────────────────────────
# {uid: [(content, channel_id, timestamp), ...]}
copypasta_tracker: dict = defaultdict(list)
COPYPASTA_WINDOW   = 30   # secondes
COPYPASTA_CHANNELS = 3    # salons différents
COPYPASTA_RATIO    = 0.80 # similarité minimum

# ── Liens raccourcis suspects (étendu) ───────────────────────────────────────
SHORT_LINKS = [
    "bit.ly", "tinyurl.com", "t.co", "ow.ly", "short.io",
    "rebrand.ly", "cutt.ly", "tiny.cc", "is.gd", "buff.ly",
    "adf.ly",
]
# linktr.ee autorisé si staff, bloqué sinon
SHORT_LINKS_STRICT = SHORT_LINKS + ["linktr.ee"]

# ── Mots-clés détresse psychologique ─────────────────────────────────────────
DISTRESS_WORDS = [
    "je veux mourir", "envie de mourir", "je vais mourir",
    "je suis déprimé", "je suis dépressive", "trop déprimé",
    "plus envie de rien", "plus envie de vivre",
    "personne m'aime", "personne ne m'aime", "tout le monde s'en fout de moi",
    "je vais me suicider", "je veux me suicider", "penser au suicide",
    "j'en peux plus", "j en peux plus", "j'en peux vraiment plus",
    "la vie vaut pas la peine", "à quoi ça sert de vivre",
    "personne ne me comprend", "je suis seul au monde",
    "je me sens inutile", "je veux disparaître",
]
SUSPICIOUS_LINKS = [
    "bit.ly", "free-nitro", "discord-gift", "steamcommunity.ru", "discordnitro", "nitro-gift", "free-steam",
    # IP grabbers / loggers
    "grabify.link", "iplogger.org", "iplogger.com", "ipgrab.me", "2no.co", "yip.su",
    "ps3cfw.com", "lovebird.guru", "blasze.tk", "api.grabify", "iplis.ru", "02ip.ru",
    "ezstat.ru", "network-ip.ru", "iptracker.org", "getiplocation.net", "whatstheirip.com",
    "trackip.net", "spylink.net", "href.li", "crabdance.com", "gyazo.link",
    # Phishing Discord / Steam
    "discordapp.io", "discord-app.io", "discordgift.site", "discord-nitro.site",
    "discord-nitro.gift", "discord-gifts.site", "discordnitro.com", "dsc.gg/free",
    "steamcommunity.pw", "steam-community.ru", "steampowered.gift", "steam-trade.ru",
    "csgo-skins.com", "csgo-trade.com",
    # Scam/malware courants
    "pornhub.gift", "free-robux.gg", "roblox.gift", "fortnite-vbucks.com",
    "nitro.gift", "nitro-discord.com", "discordapp.gift",
]
XP_PER_MSG       = 10
XP_COOLDOWN      = 60
LEVEL_ROLES      = {5: "Niveau 5", 10: "Niveau 10", 20: "Niveau 20", 50: "Niveau 50"}
STARBOARD_THRESHOLD = 3   # nombre de ⭐ pour apparaître dans le starboard
STREAK_BONUS_XP     = 20  # XP bonus par streak quotidien

# ══════════════════════════════════════════════════════════════════════════════
# 🔒 VARIABLES DE SÉCURITÉ AVANCÉE
# ══════════════════════════════════════════════════════════════════════════════

# Anti-nuke — tracker des actions destructives par membre
nuke_tracker     = defaultdict(list)  # {user_id: [timestamps]}
NUKE_THRESHOLD   = 3    # Actions en moins de 10s = nuke détecté
NUKE_WINDOW      = 10   # Secondes

# Anti-spam vocal
voice_spam_tracker = defaultdict(list)  # {user_id: [timestamps join/leave]}
VOICE_SPAM_THRESHOLD = 5  # Rejoindre/quitter 5x en 30s

# Anti-mention massive
mention_tracker  = defaultdict(list)  # {user_id: [timestamps]}
MENTION_THRESHOLD = 5   # Mentions en 10s

# Lockdown
lockdown_active  = {}   # {guild_id: True/False}
lockdown_backup  = {}   # {channel_id: overwrites sauvegardées}

# Cache invitations : {guild_id: {code: uses}}
invite_cache = {}

# Salons vocaux temporaires : {channel_id: owner_id}
temp_voice_channels = {}

# Comptes suspects — âge minimum en jours
ACCOUNT_MIN_AGE_DAYS  = 7    # Âge minimum compte en jours
VETERAN_DAYS          = 180  # Jours pour être considéré vétéran
MAX_SANCTIONS_DISPLAY = 10   # Sanctions affichées dans !infosanction
MAX_XP_LEADERBOARD   = 50   # Entrées dans le leaderboard

# Log sécurité dédié
SECURITY_LOG_NAMES = ["logs-securite", "logs-security", "log-securite", "security-logs", "logs-bans"]

async def log_security(guild, embed):
    """Envoie dans le salon de sécurité dédié"""
    for name in SECURITY_LOG_NAMES:
        ch = discord.utils.find(lambda c: name in c.name.lower(), guild.text_channels)
        if ch:
            await ch.send(embed=embed)
            return
    await log(guild, embed)

async def nuke_action(guild, member, action_type: str):
    """Enregistre une action potentiellement nuisible et alerte si seuil atteint"""
    # Rôles exemptés — pas de restriction automatique
    member_role_names = [r.name for r in member.roles]
    if any(r in member_role_names for r in NUKE_EXEMPT_ROLES):
        return

    now = time.time()
    uid = str(member.id)
    nuke_tracker[uid].append(now)
    nuke_tracker[uid] = [t for t in nuke_tracker[uid] if now - t < NUKE_WINDOW]

    if len(nuke_tracker[uid]) >= NUKE_THRESHOLD:
        # Retirer toutes les permissions immédiament
        try:
            # Retirer tous les rôles dangereux
            dangerous_perms = ["administrator", "manage_guild", "manage_channels",
                              "manage_roles", "manage_webhooks", "ban_members", "kick_members"]
            for role in member.roles:
                if role.name != "@everyone":
                    perms = role.permissions
                    if any(getattr(perms, p, False) for p in dangerous_perms):
                        try: await member.remove_roles(role, reason="🚨 Anti-nuke automatique")
                        except Exception: pass
        except Exception: pass

        e = discord.Embed(
            title="🚨 ANTI-NUKE DÉCLENCHÉ",
            description=f"**{member.mention}** a effectué **{len(nuke_tracker[uid])} actions destructives** en {NUKE_WINDOW}s !",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="Action détectée", value=action_type)
        e.add_field(name="Membre", value=f"{member} (`{member.id}`)")
        e.add_field(name="⚡ Action prise", value="Rôles dangereux retirés automatiquement")
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text="⚠️ Vérifiez le serveur immédiatement !")
        await log_security(guild, e)
        nuke_tracker[uid] = []  # Reset


# ─── NOMS DES RÔLES (à personnaliser selon ton serveur) ──────────────────────
ROLE_GESTION_STAFF     = "Gestion Staff"
ROLE_GESTION_STAFF_ID  = 1493629004824186980   # ID Discord du rôle Gestion Staff
ROLE_GESTION_ABUS      = "Gestion Abus"
ROLE_GESTION_ABUS_ID   = 1493629136269217912   # ID Discord du rôle Gestion Abus
ROLE_COD               = "kozakura C.O.D"      # Peut tout voir
ROLE_COD_ID            = 1478530602037674148   # ID Discord du rôle kozakura C.O.D
ROLE_PARTENARIAT       = "Partenariat"
ROLE_JUGE              = "Gestion Staff"       # Rôle requis pour le tribunal

# Rôles exemptés de l'anti-nuke et des sécurités automatiques
NUKE_EXEMPT_ROLES = ("kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer")

# Rôles protégés : seul le rôle "kozakura" peut les donner/retirer
PROTECTED_ROLES = ("Développer",)
ROLE_CROWN = "kozakura"  # Seul ce rôle peut toucher les rôles protégés

# Anti-ping : ces utilisateurs ne peuvent pas être mentionnés / leur pseudo écrit
ANTI_PING_USERS = {
    777495590049021972: ["louis", "louisl", "louismph8"],  # pseudo(s) à surveiller (minuscules)
}

# Protection vocale légère : toucher ces membres → mute 10min + 1 avertissement
VOC_WARN_USERS = {
    1467246069833269526,  # membre protégé niveau warn
}

# ─── UTILITAIRES ──────────────────────────────────────────────────────────────
def xp_for_level(lvl): return int(100 * (lvl ** 1.5))

def get_level(xp):
    lvl = 0
    while xp >= xp_for_level(lvl + 1): lvl += 1
    return lvl

def get_cfg(guild_id, key, default=None):
    return config_db.get(str(guild_id), {}).get(key, default)

def set_cfg(guild_id, key, value):
    gid = str(guild_id)
    config_db.setdefault(gid, {})[key] = value
    save_json("config.json", config_db)

async def log(guild, embed):
    """Log général (garde pour compatibilité)"""
    ch_id = get_cfg(guild.id, "log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if not ch:
            try: ch = await guild.fetch_channel(int(ch_id))
            except: return
        if ch: await ch.send(embed=embed)

async def log_to(guild, embed, channel_keywords):
    """Envoie dans le premier salon dont le nom contient un des keywords"""
    for kw in channel_keywords:
        ch = discord.utils.find(lambda c: kw in c.name.lower(), guild.text_channels)
        if ch:
            await ch.send(embed=embed)
            return
    # Fallback sur le log général
    await log(guild, embed)

async def log_ban(guild, embed):
    """Logs sanctions : logs-bans, logs-sanctions"""
    await log_to(guild, embed, ["logs-bans", "logs-ban", "log-ban", "log-bans", "sanction"])

async def log_message(guild, embed):
    """Logs messages : logs-messages, logs-message"""
    await log_to(guild, embed, ["logs-messages", "logs-message", "log-messages", "log-message"])

async def log_photo(guild, embed):
    """Logs photos/fichiers : log-photos, logs-photos"""
    await log_to(guild, embed, ["log-photos", "logs-photos", "log-photo", "logs-photo"])

async def log_vocal(guild, embed):
    """Logs vocaux : log-vocs, logs-vocs"""
    await log_to(guild, embed, ["log-vocs", "logs-vocs", "log-voc", "logs-voc", "log-vocal"])

async def dm(user, title, desc, color=discord.Color.red()):
    try:
        e = discord.Embed(title=title, description=desc, color=color,
            timestamp=datetime.utcnow())
        await user.send(embed=e)
    except Exception: pass

async def resolve_channel(ctx, arg: str):
    arg = arg.strip()
    if arg.startswith("<#") and arg.endswith(">"):
        cid = arg[2:-1]
        if cid.isdigit():
            ch = ctx.guild.get_channel(int(cid))
            if ch: return ch
            try: return await ctx.guild.fetch_channel(int(cid))
            except Exception: pass
    if arg.isdigit():
        ch = ctx.guild.get_channel(int(arg))
        if ch: return ch
        try: return await ctx.guild.fetch_channel(int(arg))
        except Exception: pass
    name = arg.lstrip("#").lower()
    return discord.utils.find(lambda c: c.name.lower() == name, ctx.guild.text_channels)

async def resolve_role(ctx, arg: str):
    arg = arg.strip()
    if arg.startswith("<@&") and arg.endswith(">"):
        rid = arg[3:-1]
        if rid.isdigit(): return ctx.guild.get_role(int(rid))
    if arg.isdigit(): return ctx.guild.get_role(int(arg))
    return discord.utils.find(lambda r: r.name.lower() == arg.lower(), ctx.guild.roles)

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅  {bot.user}  connecté !")
    if ANTHROPIC_API_KEY:
        print(f"🤖 Clé API Anthropic détectée (longueur : {len(ANTHROPIC_API_KEY)})")
    else:
        print("⚠️  ANTHROPIC_API_KEY introuvable — fonctions IA désactivées")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=f"le serveur | {PREFIX}help"))
    check_reminders.start()
    update_counters.start()
    rapport_hebdo.start()
    try:
        synced = await bot.tree.sync()
        print(f"⚡ {len(synced)} slash commands synchronisées")
    except Exception as e: print(e)

    # ── Enregistrement des Views persistantes (survie aux redémarrages) ────────
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
    print("✅ Views persistantes enregistrées (ticket panel + contrôles)")

    # ── Auto-restore du panel ticket si le message a été supprimé ─────────────
    for guild in bot.guilds:
        ch_id  = get_cfg(guild.id, "ticket_panel_channel")
        msg_id = get_cfg(guild.id, "ticket_panel_message")
        if not ch_id:
            continue
        ch = guild.get_channel(int(ch_id))
        if not ch:
            continue
        panel_exists = False
        if msg_id:
            try:
                await ch.fetch_message(int(msg_id))
                panel_exists = True  # Le message existe encore, rien à faire
            except Exception:
                panel_exists = False
        if not panel_exists:
            # Renvoyer automatiquement le panel
            try:
                e = _build_ticket_panel_embed(guild)
                new_msg = await ch.send(embed=e, view=TicketPanelView())
                set_cfg(guild.id, "ticket_panel_message", new_msg.id)
                print(f"♻️ Panel ticket renvoyé dans #{ch.name} ({guild.name})")
            except Exception as err:
                print(f"⚠️ Impossible de renvoyer le panel ticket : {err}")

    # Repopuler voice_join_times pour les membres déjà en vocal au redémarrage
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for m in vc.members:
                if not m.bot:
                    voice_join_times[str(m.id)] = time.time()

    # Charger le cache des invitations
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

@bot.event
async def on_member_join(member):
    guild = member.guild; now = time.time()

    # Vérification anti-bot en premier
    if member.bot:
        await check_antibot(member)
        return

    # ── Détection compte suspect ──────────────────────────────────────────────
    account_age_days = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    has_avatar = member.avatar is not None
    suspicious_flags = []

    if account_age_days < ACCOUNT_MIN_AGE_DAYS:
        suspicious_flags.append(f"⚠️ Compte créé il y a seulement **{account_age_days}j**")
    if not has_avatar:
        suspicious_flags.append("⚠️ **Pas d'avatar**")
    if account_age_days < 1:
        suspicious_flags.append("🚨 **Compte créé aujourd'hui**")

    if suspicious_flags:
        e_sus = discord.Embed(
            title="🔍 Compte Suspect Détecté",
            description=f"{member.mention} vient de rejoindre le serveur.",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        e_sus.set_thumbnail(url=member.display_avatar.url)
        e_sus.add_field(name="⚠️ Indicateurs suspects", value="\n".join(suspicious_flags), inline=False)
        e_sus.add_field(name="📅 Compte créé le", value=member.created_at.strftime('%d/%m/%Y'), inline=True)
        e_sus.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        e_sus.set_footer(text="Surveillez ce membre • Kozakura Security")
        await log_security(guild, e_sus)

    # ── Détection retour d'un banni (nouveau compte) ──────────────────────────
    import difflib as _dl
    gid_j = str(guild.id)
    banned_list = banned_db.get(gid_j, {})
    new_name = member.name.lower()
    new_disp = member.display_name.lower()
    new_avatar = str(member.avatar) if member.avatar else None

    best_match_uid  = None
    best_match_data = None
    best_ratio      = 0.0

    for banned_uid, bdata in banned_list.items():
        if str(member.id) == banned_uid:
            continue  # même compte, déjà géré par Discord
        b_name = bdata.get("name", "").lower()
        b_disp = bdata.get("display_name", "").lower()
        b_avatar = bdata.get("avatar")

        # Similarité nom + display_name
        r1 = _dl.SequenceMatcher(None, new_name, b_name).ratio()
        r2 = _dl.SequenceMatcher(None, new_disp, b_disp).ratio()
        r_avatar = 1.0 if (new_avatar and b_avatar and new_avatar == b_avatar) else 0.0
        combined = max(r1, r2, r_avatar)

        if combined > best_ratio:
            best_ratio = combined
            best_match_uid = banned_uid
            best_match_data = bdata

    if best_ratio >= 0.80 and best_match_data:
        gestion_role = discord.utils.get(guild.roles, name=ROLE_GESTION_STAFF)
        mention_staff = gestion_role.mention if gestion_role else "**@Gestion**"

        # Freeze automatique
        if member.id not in frozen_members:
            frozen_members[member.id] = {}
            for channel in guild.channels:
                try:
                    ow = channel.overwrites_for(member)
                    frozen_members[member.id][channel.id] = ow.pair()
                    await channel.set_permissions(member,
                        send_messages=False, read_messages=False,
                        connect=False, speak=False,
                        reason="🚨 Retour possible d'un banni — freeze auto")
                except Exception: pass

        e_ban_ret = discord.Embed(
            title="🚨 RETOUR DE BANNI POTENTIEL",
            description=(
                f"{member.mention} vient de rejoindre et ressemble à un membre banni.\n\n"
                f"**Freeze automatique appliqué.**"
            ),
            color=discord.Color.dark_red(), timestamp=datetime.utcnow()
        )
        e_ban_ret.add_field(name="👤 Nouveau membre",   value=f"{member} (`{member.id}`)", inline=True)
        e_ban_ret.add_field(name="🔨 Membre banni",     value=f"{best_match_data.get('name')} (`{best_match_uid}`)", inline=True)
        e_ban_ret.add_field(name="📊 Similarité",       value=f"**{best_ratio*100:.0f}%**", inline=True)
        e_ban_ret.add_field(name="📅 Banni le",         value=best_match_data.get('banned_at', '?')[:10], inline=True)
        e_ban_ret.set_thumbnail(url=member.display_avatar.url)
        e_ban_ret.set_footer(text="Kozakura Security • Vérification manuelle recommandée")
        await log_security(guild, e_ban_ret)
        sec_ch = discord.utils.find(
            lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels
        )
        if sec_ch:
            await sec_ch.send(content=f"🚨 {mention_staff} — Retour de banni potentiel, freeze appliqué !", embed=e_ban_ret)

    # Captcha humain désactivé

    raid_tracker.append(now)
    raid_tracker[:] = [t for t in raid_tracker if now - t < 10]
    if len(raid_tracker) >= get_cfg(guild.id, "raid_threshold", 10):
        try:
            await member.kick(reason="Anti-raid automatique")
        except Exception:
            pass
        # Lockdown automatique si pas déjà actif
        raid_count = len(raid_tracker)
        await trigger_lockdown(
            guild,
            raison=f"Raid détecté — {raid_count} joins en 10 secondes",
            triggered_by="🤖 Anti-Raid automatique"
        )
        e = discord.Embed(
            title="🚨 ANTI-RAID DÉCLENCHÉ",
            description=f"{member.mention} expulsé\n**{raid_count}** joins en 10 secondes",
            color=discord.Color.dark_red(), timestamp=datetime.utcnow()
        )
        e.add_field(name="🔒 Lockdown", value="Activé automatiquement")
        e.set_footer(text="Kozakura Security")
        await log_security(guild, e)
        return
    ar = get_cfg(guild.id, "auto_role")
    if ar:
        role = guild.get_role(int(ar))
        if role:
            try: await member.add_roles(role)
            except Exception: pass
    wc = get_cfg(guild.id, "welcome_channel")
    if wc:
        ch = guild.get_channel(int(wc))
        if not ch:
            try: ch = await guild.fetch_channel(int(wc))
            except: ch = None
        if ch:
            msg = get_cfg(guild.id, "welcome_message",
                "👋 Bienvenue sur **{server}**, {user} ! Tu es le membre n°{count}.")
            msg = msg.replace("{user}", member.mention).replace("{server}", guild.name)\
                     .replace("{count}", str(guild.member_count))
            e = discord.Embed(description=msg, color=discord.Color.green(),
                timestamp=datetime.utcnow())
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)
    # ── Détection de l'invitation utilisée ───────────────────────────────────────
    used_invite   = None
    used_inviter  = None
    try:
        current_invites = await guild.invites()
        cached = invite_cache.get(guild.id, {})
        for inv in current_invites:
            old_uses = cached.get(inv.code, 0)
            if inv.uses > old_uses:
                used_invite  = inv
                used_inviter = inv.inviter
                break
        # Mettre à jour le cache
        invite_cache[guild.id] = {inv.code: inv.uses for inv in current_invites}
    except Exception:
        pass

    # Log invite
    await _log_invite_join(guild, member, used_invite, used_inviter)

    e = discord.Embed(title="📥 Nouveau membre",
        description=f"{member.mention}\nCompte créé le {member.created_at.strftime('%d/%m/%Y')}",
        color=discord.Color.green(), timestamp=datetime.utcnow())
    e.set_thumbnail(url=member.display_avatar.url)
    await log(guild, e)

async def _log_invite_join(guild, member, invite, inviter):
    """Envoie un embed de log d'invitation dans le salon configuré ou auto-détecté."""
    ch = None
    ch_id = get_cfg(guild.id, "invite_log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if not ch:
            try: ch = await guild.fetch_channel(int(ch_id))
            except: ch = None
    # Auto-détection si pas configuré
    if not ch:
        INVITE_LOG_KEYWORDS = ["invitations", "invite-log", "log-invite", "logs-invite", "invite"]
        ch = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in INVITE_LOG_KEYWORDS),
            guild.text_channels
        )
    if not ch:
        return

    e = discord.Embed(
        title="📨 Invitation utilisée",
        color=0xFF89B4,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Nouveau membre", value=f"{member.mention}\n`{member.id}`", inline=True)

    if inviter:
        e.add_field(name="🔗 Invité par", value=f"{inviter.mention}\n`{inviter.id}`", inline=True)
        e.add_field(name="📎 Code", value=f"`discord.gg/{invite.code}`\n**{invite.uses}** utilisation(s)", inline=True)
    else:
        e.add_field(name="🔗 Invité par", value="*Inconnu*", inline=True)

    account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    e.add_field(name="📅 Compte créé", value=f"il y a **{account_age}j**", inline=True)
    e.add_field(name="👥 Membres total", value=str(guild.member_count), inline=True)
    e.set_footer(text="Kozakura • Invite Log")
    await ch.send(embed=e)

@bot.command(name="setinvitelog")
@commands.has_permissions(administrator=True)
async def setinvitelog(ctx, *, arg: str):
    """!setinvitelog #salon — Définit le salon de log des invitations"""
    channel = await resolve_channel(ctx, arg)
    if not channel:
        return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "invite_log_channel", channel.id)
    await ctx.send(f"✅ Log invitations → {channel.mention}")

@bot.event
async def on_member_remove(member):
    e = discord.Embed(title="📤 Membre parti", description=f"{member.mention} ({member.name})",
        color=discord.Color.orange(), timestamp=datetime.utcnow())
    await log(member.guild, e)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    guild = message.guild; author = message.author
    uid = str(author.id); gid = str(guild.id); now = time.time()

    # ── Anti-ping / anti-mention utilisateurs protégés ───────────────────────
    for protected_id, pseudos in ANTI_PING_USERS.items():
        if author.id == protected_id:
            break  # La personne protégée peut écrire son propre nom
        triggered = False
        # Vérifier mention directe (<@ID>)
        if any(u.id == protected_id for u in message.mentions):
            triggered = True
        # Vérifier pseudo écrit dans le message
        content_low = message.content.lower()
        if not triggered and any(p in content_low for p in pseudos):
            triggered = True
        if triggered:
            try:
                await message.delete()
            except Exception:
                pass
            protected_member = guild.get_member(protected_id)
            warn_txt = (
                f"⛔ {author.mention} Tu n'es pas autorisé(e) à mentionner ou écrire le nom de cette personne."
            )
            try:
                warn_msg = await message.channel.send(warn_txt, delete_after=6)
            except Exception:
                pass
            # Log sécurité
            e_ap = discord.Embed(
                title="🔕 Anti-Ping Déclenché",
                description=f"{author.mention} a tenté de mentionner une personne protégée.",
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
            e_ap.add_field(name="👤 Auteur",   value=f"{author} (`{author.id}`)", inline=True)
            e_ap.add_field(name="📌 Salon",    value=message.channel.mention, inline=True)
            e_ap.add_field(name="💬 Message",  value=message.content[:300] or "*(vide)*", inline=False)
            e_ap.set_footer(text="Kozakura Security • Anti-Ping")
            await log_security(guild, e_ap)
            return  # Ne pas traiter le reste du message

    # Log photos/fichiers envoyés
    if message.attachments:
        for att in message.attachments:
            if att.content_type and (att.content_type.startswith("image") or att.content_type.startswith("video")):
                e_photo = discord.Embed(
                    title="📸 Média Envoyé",
                    description=f"Par {author.mention} dans {message.channel.mention}",
                    color=discord.Color.blurple(), timestamp=datetime.utcnow()
                )
                e_photo.add_field(name="Fichier", value=att.filename)
                e_photo.set_image(url=att.proxy_url)
                e_photo.set_thumbnail(url=author.display_avatar.url)
                await log_photo(guild, e_photo)

    message_tracker[uid].append(now)
    message_tracker[uid] = [t for t in message_tracker[uid] if now - t < 5]
    if len(message_tracker[uid]) >= 5:
        await message.delete()
        if message.channel.slowmode_delay < 10:
            await message.channel.edit(slowmode_delay=10)
            e = discord.Embed(title="⏱️ Slowmode Activé",
                description=f"10s dans {message.channel.mention}",
                color=discord.Color.orange(), timestamp=datetime.utcnow())
            await log(guild, e)
        await message.channel.send(f"{author.mention} ⚠️ Stop au spam !", delete_after=5)
        return
    low = message.content.lower()
    for w in BANNED_WORDS:
        if w in low:
            await message.delete()
            e = discord.Embed(title="🚫 Message Supprimé", description=f"{author.mention} — insulte",
                color=discord.Color.red(), timestamp=datetime.utcnow())
            e.add_field(name="Contenu", value=f"||{message.content[:200]}||")
            e.set_thumbnail(url=author.display_avatar.url)
            await log_message(guild, e)
            # Alerte IA insulte au staff
            staff_ch = discord.utils.find(lambda c: "logs-bans" in c.name.lower() or "sanction" in c.name.lower(), guild.text_channels)
            if staff_ch:
                e2 = discord.Embed(title="🤖 IA — Insulte Détectée",
                    description=f"{author.mention} a utilisé un mot interdit dans {message.channel.mention}",
                    color=discord.Color.dark_red(), timestamp=datetime.utcnow())
                e2.add_field(name="Message", value=f"||{message.content[:200]}||")
                await staff_ch.send(embed=e2)
            await message.channel.send(f"{author.mention} ce mot est interdit.", delete_after=5)
            return

    # ── Détection NSFW / harcèlement sexuel ──────────────────────────────────
    for phrase in NSFW_WORDS:
        if phrase in low:
            try: await message.delete()
            except Exception: pass

            # ── Sanction progressive basée sur les warns ──────────────────
            gid = str(guild.id); uid = str(author.id)
            warnings_db.setdefault(gid, {}).setdefault(uid, []).append(
                {"reason": f"[Auto-mod NSFW] {phrase}", "by": "bot", "date": str(datetime.utcnow())}
            )
            save_json("warnings.json", warnings_db)
            warn_count = len(warnings_db[gid][uid])
            add_sanction(guild, author, "Warn", f"[Auto-mod NSFW] {phrase}", guild.me)

            action_taken = ""
            if warn_count == 1:
                action_taken = "⚠️ Avertissement #1 enregistré."
            elif warn_count == 2:
                until = datetime.utcnow() + timedelta(minutes=10)
                try: await author.timeout(until, reason="[Auto-mod NSFW] 2ème infraction")
                except Exception: pass
                action_taken = "🔇 Mute 10 min (2ème infraction)."
            elif warn_count == 3:
                until = datetime.utcnow() + timedelta(hours=1)
                try: await author.timeout(until, reason="[Auto-mod NSFW] 3ème infraction")
                except Exception: pass
                action_taken = "🔇 Mute 1h (3ème infraction)."
            elif warn_count == 4:
                try: await author.kick(reason="[Auto-mod NSFW] 4ème infraction")
                except Exception: pass
                action_taken = "👟 Kick automatique (4ème infraction)."
            else:
                try: await guild.ban(author, reason="[Auto-mod NSFW] 5ème+ infraction", delete_message_days=1)
                except Exception: pass
                action_taken = "🔨 Ban automatique (5ème+ infraction)."

            # ── Alerte staff ──────────────────────────────────────────────
            gestion_role = discord.utils.get(guild.roles, name=ROLE_GESTION_STAFF)
            mention_staff = gestion_role.mention if gestion_role else "**@Gestion**"

            e_nsfw = discord.Embed(
                title="🔞 CONTENU NSFW / HARCÈLEMENT DÉTECTÉ",
                description=(
                    f"{author.mention} a envoyé un message à caractère sexuel ou de harcèlement "
                    f"dans {message.channel.mention}.\n\n"
                    f"**Action automatique :** {action_taken}"
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
            e_nsfw.add_field(name="👤 Membre",      value=f"{author} (`{author.id}`)", inline=True)
            e_nsfw.add_field(name="📌 Salon",        value=message.channel.mention, inline=True)
            e_nsfw.add_field(name="⚠️ Warns total", value=f"**{warn_count}**", inline=True)
            e_nsfw.add_field(name="🔑 Déclencheur", value=f"`{phrase}`", inline=True)
            e_nsfw.add_field(name="💬 Contenu supprimé", value=f"||{message.content[:400]}||", inline=False)
            e_nsfw.set_thumbnail(url=author.display_avatar.url)
            e_nsfw.set_footer(text="Kozakura Auto-Mod • NSFW Protection")

            sec_ch = discord.utils.find(
                lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES),
                guild.text_channels
            )
            if sec_ch:
                await sec_ch.send(content=f"🚨 {mention_staff} — Contenu NSFW ({warn_count} warn) !", embed=e_nsfw)
            else:
                await log_security(guild, e_nsfw)

            await message.channel.send(
                f"{author.mention} ⛔ Message supprimé — contenu inapproprié. ({action_taken})",
                delete_after=8
            )
            return

    # ── Anti-screenshot dans salons confidentiels ─────────────────────────────
    if message.attachments:
        ch_name = message.channel.name.lower()
        if any(kw in ch_name for kw in PRIVATE_CHANNEL_KEYWORDS):
            for att in message.attachments:
                if att.content_type and att.content_type.startswith("image"):
                    gestion_role = discord.utils.get(guild.roles, name=ROLE_GESTION_STAFF)
                    mention_staff = gestion_role.mention if gestion_role else "**@Gestion**"
                    e_screen = discord.Embed(
                        title="📸 Image dans salon confidentiel",
                        description=f"{author.mention} a envoyé une image dans {message.channel.mention}.",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow()
                    )
                    e_screen.add_field(name="👤 Membre",  value=f"{author} (`{author.id}`)", inline=True)
                    e_screen.add_field(name="📌 Salon",   value=message.channel.mention, inline=True)
                    e_screen.add_field(name="📎 Fichier", value=att.filename, inline=True)
                    e_screen.set_image(url=att.proxy_url)
                    e_screen.set_footer(text="Kozakura Security • Anti-Screenshot")
                    await log_security(guild, e_screen)
                    sec_ch = discord.utils.find(
                        lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels
                    )
                    if sec_ch:
                        await sec_ch.send(content=f"📸 {mention_staff} — Image dans salon confidentiel !", embed=e_screen)
                    break

    # ── Anti-copypasta multi-salons ──────────────────────────────────────────
    if not has_sanction_role(author, ROLES_BAN) and message.content and len(message.content) > 10:
        import difflib
        now_cp = time.time()
        uid_cp = str(author.id)
        copypasta_tracker[uid_cp].append((message.content, message.channel.id, now_cp))
        # Garder seulement les 10 derniers dans la fenêtre
        copypasta_tracker[uid_cp] = [
            (c, ch, t) for c, ch, t in copypasta_tracker[uid_cp]
            if now_cp - t <= COPYPASTA_WINDOW
        ][-10:]

        recent = copypasta_tracker[uid_cp]
        if len(recent) >= COPYPASTA_CHANNELS:
            # Compter les channels uniques avec message similaire
            unique_channels_match = {}
            for c, ch, t in recent:
                ratio = difflib.SequenceMatcher(None, message.content.lower(), c.lower()).ratio()
                if ratio >= COPYPASTA_RATIO:
                    unique_channels_match[ch] = True
            if len(unique_channels_match) >= COPYPASTA_CHANNELS:
                # Supprimer tous les messages similaires récents
                for c, ch_id, t in recent:
                    try:
                        ch_obj = guild.get_channel(ch_id)
                        if ch_obj:
                            async for m in ch_obj.history(limit=20):
                                if m.author.id == author.id:
                                    ratio = difflib.SequenceMatcher(None, message.content.lower(), m.content.lower()).ratio()
                                    if ratio >= COPYPASTA_RATIO:
                                        try: await m.delete()
                                        except Exception: pass
                                        break
                    except Exception: pass
                copypasta_tracker[uid_cp] = []

                # Mute 30min
                until_cp = datetime.utcnow() + timedelta(minutes=30)
                try: await author.timeout(until_cp, reason="[Auto-mod] Copypasta multi-salons")
                except Exception: pass

                e_cp = discord.Embed(
                    title="📋 COPYPASTA MULTI-SALONS DÉTECTÉ",
                    description=f"{author.mention} a envoyé le même message dans **{len(unique_channels_match)} salons** en {COPYPASTA_WINDOW}s.",
                    color=discord.Color.dark_orange(), timestamp=datetime.utcnow()
                )
                e_cp.add_field(name="👤 Membre",  value=f"{author} (`{author.id}`)", inline=True)
                e_cp.add_field(name="⏱️ Fenêtre", value=f"{COPYPASTA_WINDOW}s", inline=True)
                e_cp.add_field(name="🔇 Action",  value="Mute 30 minutes", inline=True)
                e_cp.add_field(name="💬 Message", value=f"||{message.content[:300]}||", inline=False)
                e_cp.set_thumbnail(url=author.display_avatar.url)
                e_cp.set_footer(text="Kozakura Anti-Spam • Copypasta Protection")
                await log_security(guild, e_cp)
                await message.channel.send(
                    f"{author.mention} ⛔ Spam multi-salons détecté — mute 30 min.", delete_after=8
                )
                return

    # ── Anti-mentions massives ────────────────────────────────────────────────
    mention_count = len(message.mentions) + len(message.role_mentions)
    if mention_count >= MENTION_THRESHOLD and not has_sanction_role(author, ROLES_BAN + ROLES_MUTE):
        now_m = time.time()
        mention_tracker[uid].append(now_m)
        mention_tracker[uid] = [t for t in mention_tracker[uid] if now_m - t < 10]
        if len(mention_tracker[uid]) >= 2 or mention_count >= 8:
            try: await message.delete()
            except Exception: pass
            until_m = datetime.utcnow() + timedelta(minutes=30)
            try: await author.timeout(until_m, reason="[Auto-mod] Mentions massives")
            except Exception: pass
            e_men = discord.Embed(
                title="🔔 MENTIONS MASSIVES DÉTECTÉES",
                description=f"{author.mention} a mentionné **{mention_count} membres/rôles** d'un coup.",
                color=discord.Color.dark_red(), timestamp=datetime.utcnow()
            )
            e_men.add_field(name="👤 Membre", value=f"{author} (`{author.id}`)", inline=True)
            e_men.add_field(name="🔇 Action",  value="Mute 30 minutes", inline=True)
            e_men.set_thumbnail(url=author.display_avatar.url)
            await log_security(guild, e_men)
            await message.channel.send(
                f"{author.mention} ⛔ Mentions massives interdites — mute 30 min.", delete_after=8
            )
            return

    # ── Watchlist — surveillance renforcée ────────────────────────────────────
    if uid in watchlist_db.get(str(guild.id), {}):
        wdata = watchlist_db[str(guild.id)][uid]
        e_watch = discord.Embed(
            title="👁️ Membre Surveillé — Message",
            description=f"{author.mention} (watchlist) a envoyé un message dans {message.channel.mention}",
            color=discord.Color.gold(), timestamp=datetime.utcnow()
        )
        e_watch.add_field(name="💬 Message", value=message.content[:500] or "*(média)*", inline=False)
        e_watch.add_field(name="📋 Raison watchlist", value=wdata.get("reason", "?"), inline=False)
        e_watch.set_thumbnail(url=author.display_avatar.url)
        await log_security(guild, e_watch)

    # ── Shadowban — suppression silencieuse ───────────────────────────────────
    if uid in shadowban_db.get(str(guild.id), {}):
        try: await message.delete()
        except Exception: pass
        return

    # ── Détection IA contextuelle (mots dangereux en contexte) ───────────────
    if ANTHROPIC_API_KEY and len(message.content) > 20:
        CONTEXT_PATTERNS = [
            "je vais te", "je vais vous", "t'es mort", "tu es mort",
            "je te retrouve", "adresse", "tu vas voir", "je vais venir"
        ]
        if any(p in message.content.lower() for p in CONTEXT_PATTERNS):
            e_threat = discord.Embed(
                title="🤖 IA — Menace Potentielle Détectée",
                description=f"Message suspect de {author.mention} dans {message.channel.mention}",
                color=discord.Color.red(), timestamp=datetime.utcnow()
            )
            e_threat.add_field(name="Message", value=f"||{message.content[:300]}||")
            e_threat.add_field(name="Membre", value=f"{author} (`{author.id}`)")
            staff_role = discord.utils.get(guild.roles, name="Gestion")
            mention_txt = staff_role.mention if staff_role else ""
            await log_security(guild, e_threat)
            sec_ch = discord.utils.find(lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels)
            if sec_ch and mention_txt:
                await sec_ch.send(f"⚠️ {mention_txt} — Menace potentielle détectée !")

    # Salons où les liens sont autorisés
    LINK_ALLOWED_CHANNELS = [
        "partenariat",
        "condi-partenariat",
        "notre-fiche",
    ]
    channel_name_low = message.channel.name.lower()

    # Vérifier si c'est un salon autorisé (nom ou ticket)
    is_link_allowed = (
        any(allowed in channel_name_low for allowed in LINK_ALLOWED_CHANNELS)
        or str(message.channel.id) in tickets_db.get(str(guild.id), {})
        or has_sanction_role(author, ROLES_BAN)  # Staff autorisé partout
    )

    # Regex étendu : capture aussi discordapp.com/invite/ avec ou sans https://
    _url_pattern = re.compile(
        r'https?://\S+|discord\.gg/\S+|discord\.com/invite/\S+|discordapp\.com/invite/\S+',
        re.IGNORECASE
    )
    for url in _url_pattern.findall(message.content):
        url_low = url.lower()
        is_suspicious    = any(d in url_low for d in SUSPICIOUS_LINKS)
        is_short_link    = any(d in url_low for d in SHORT_LINKS_STRICT) and not has_sanction_role(author, ROLES_BAN)
        is_discord_invite = any(x in url_low for x in [
            "discord.gg/", "discord.com/invite/", "discordapp.com/invite/"
        ])
        if not is_suspicious and not is_short_link and not is_discord_invite:
            continue
        if not is_link_allowed:
            try: await message.delete()
            except Exception: pass

            if is_short_link and not is_suspicious and not is_discord_invite:
                # Warn progressif pour liens raccourcis
                gid_l = str(guild.id); uid_l = str(author.id)
                warnings_db.setdefault(gid_l, {}).setdefault(uid_l, []).append(
                    {"reason": f"[Auto-mod] Lien raccourci : {url[:80]}", "by": "bot", "date": str(datetime.utcnow())}
                )
                save_json("warnings.json", warnings_db)
                warn_c = len(warnings_db[gid_l][uid_l])
                e_short = discord.Embed(
                    title="🔗 Lien Raccourci Détecté",
                    description=f"{author.mention} a envoyé un lien raccourci interdit.",
                    color=discord.Color.orange(), timestamp=datetime.utcnow()
                )
                e_short.add_field(name="URL",    value=f"||{url[:200]}||", inline=False)
                e_short.add_field(name="Membre", value=f"{author} (`{author.id}`)", inline=True)
                e_short.add_field(name="Warns",  value=f"**{warn_c}**", inline=True)
                await log_security(guild, e_short)
                if warn_c >= 2:
                    until_s = datetime.utcnow() + timedelta(hours=1)
                    try: await author.timeout(until_s, reason="[Auto-mod] Lien raccourci — 2ème infraction")
                    except Exception: pass
                    await message.channel.send(f"{author.mention} ⛔ Lien raccourci interdit — mute 1h (2ème infraction).", delete_after=8)
                else:
                    await message.channel.send(f"{author.mention} ⚠️ Les liens raccourcis sont interdits ici. ({warn_c}/2 avant mute)", delete_after=6)
                return

            label = "Invitation Discord" if is_discord_invite else "Lien Suspect"
            e = discord.Embed(
                title=f"🔗 {label} Supprimé — Ban Auto",
                description=f"{author.mention} a envoyé une invitation/lien interdit.",
                color=discord.Color.dark_red(), timestamp=datetime.utcnow()
            )
            e.add_field(name="URL",    value=f"||{url[:200]}||", inline=False)
            e.add_field(name="Membre", value=f"{author} (`{author.id}`)", inline=True)
            e.add_field(name="Action", value="🔨 Ban automatique", inline=True)
            await log_security(guild, e)
            await message.channel.send(
                f"⛔ {author.mention} a été banni automatiquement pour publicité/invitation Discord.", delete_after=8
            )
            # Ban automatique si non-staff
            if not has_sanction_role(author, list(ROLES_BAN) + list(ROLES_MUTE)):
                try:
                    await guild.ban(author, reason=f"[Auto-mod] Invitation Discord interdite : {url[:100]}", delete_message_days=1)
                    await log_sanction(guild, author, "Ban", "[Auto-mod] Invitation/pub Discord", bot.user or author, extra="Ban automatique • Invitation Discord")
                except Exception: pass
            return

    # ── Détection détresse / idées suicidaires ────────────────────────────────
    msg_low_full = message.content.lower()
    if any(kw in msg_low_full for kw in DISTRESS_WORDS):
        # Alerte discrète staff (sans contenu exact)
        gestion_role = discord.utils.get(guild.roles, name=ROLE_GESTION_STAFF)
        mention_staff = gestion_role.mention if gestion_role else "**@Gestion**"
        e_distress = discord.Embed(
            title="💙 Alerte Bien-être Membre",
            description=(
                f"{author.mention} semble traverser une période difficile dans {message.channel.mention}.\n\n"
                f"🌸 **Aucune sanction n'a été appliquée.** Intervention humaine recommandée."
            ),
            color=discord.Color.blue(), timestamp=datetime.utcnow()
        )
        e_distress.add_field(name="👤 Membre", value=f"{author} (`{author.id}`)", inline=True)
        e_distress.add_field(name="📌 Salon",  value=message.channel.mention, inline=True)
        e_distress.set_thumbnail(url=author.display_avatar.url)
        e_distress.set_footer(text="Kozakura Bien-être • Confidentiel — ne pas diffuser")
        await log_security(guild, e_distress)
        sec_ch = discord.utils.find(
            lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels
        )
        if sec_ch:
            await sec_ch.send(content=f"💙 {mention_staff} — Alerte bien-être, intervention discrète recommandée.", embed=e_distress)
        # MP chaleureux via IA
        if ANTHROPIC_API_KEY:
            support_prompt = [{
                "role": "user",
                "content": (
                    f"Un membre du serveur Discord '{guild.name}' semble aller très mal. "
                    f"Écris un message de soutien TRÈS chaleureux, bienveillant et humain (max 120 mots). "
                    f"Rappelle-lui qu'il n'est pas seul, que des ressources existent (ex: numéro national prévention suicide 3114 en France). "
                    f"Ton style : doux, empathique, jamais condescendant. Pas d'emojis excessifs."
                )
            }]
            support_msg = await call_claude(support_prompt)
            try:
                e_dm = discord.Embed(
                    title=f"🌸 Kozakura te parle — {guild.name}",
                    description=support_msg,
                    color=discord.Color.blue(), timestamp=datetime.utcnow()
                )
                e_dm.set_footer(text="🌸 Tu n'es pas seul·e. Numéro national : 3114")
                await author.send(embed=e_dm)
            except Exception: pass

    # ── Traduction automatique ────────────────────────────────────────────────
    if (
        ANTHROPIC_API_KEY
        and len(message.content.split()) >= 5
        and not str(message.channel.id) in tickets_db.get(str(guild.id), {})
        and autotrad_db.get(str(guild.id), {}).get(str(message.channel.id), False)
    ):
        detect_prompt = [{
            "role": "user",
            "content": (
                f"Ce message est-il en français ? Réponds UNIQUEMENT par 'oui' ou par la langue détectée + traduction.\n"
                f"Format si non-français : 'LANGUE: [langue] | TRADUCTION: [traduction en français]'\n"
                f"Message : {message.content[:300]}"
            )
        }]
        try:
            trad_response = await call_claude(detect_prompt)
            if trad_response and not trad_response.lower().startswith("oui"):
                # Parser la réponse
                if "TRADUCTION:" in trad_response:
                    parts = trad_response.split("|")
                    lang_part = parts[0].replace("LANGUE:", "").strip() if len(parts) > 0 else "?"
                    trad_part = parts[1].replace("TRADUCTION:", "").strip() if len(parts) > 1 else trad_response
                    e_trad = discord.Embed(
                        description=f"🌐 **Traduction** ({lang_part} → français) : *{trad_part}*",
                        color=0x2B2D31
                    )
                    e_trad.set_footer(text="Kozakura Traduction automatique • !setautotrad off pour désactiver")
                    await message.reply(embed=e_trad, mention_author=False)
        except Exception: pass

    last = xp_cooldowns.get(uid, 0)
    if now - last > XP_COOLDOWN:
        xp_cooldowns[uid] = now
        xp_db.setdefault(gid, {})
        old_xp    = xp_db[gid].get(uid, 0)
        old_level = get_level(old_xp)

        # ── Streak quotidien ──────────────────────────────────────────────────
        today     = datetime.utcnow().strftime("%Y-%m-%d")
        s_data    = streaks_db.setdefault(gid, {}).setdefault(uid, {"last_date": "", "streak": 0})
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        streak_xp = 0
        if s_data["last_date"] == yesterday:
            s_data["streak"] += 1
            streak_xp = STREAK_BONUS_XP
        elif s_data["last_date"] != today:
            s_data["streak"] = 1
        s_data["last_date"] = today
        save_json("streaks.json", streaks_db)

        gained = XP_PER_MSG + streak_xp
        xp_db[gid][uid] = old_xp + gained
        new_level = get_level(xp_db[gid][uid])
        save_json("xp.json", xp_db)

        if new_level > old_level:
            SAKURA_PINK = 0xFF89B4
            next_xp  = xp_for_level(new_level + 1)
            e = discord.Embed(
                title="⭐  Level Up !",
                description=(
                    f"## {author.mention}\n"
                    f"Félicitations, tu passes au **niveau {new_level}** !\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=SAKURA_PINK,
                timestamp=datetime.utcnow()
            )
            e.set_thumbnail(url=author.display_avatar.url)
            e.add_field(name="🏅 Nouveau niveau", value=f"`{new_level}`",            inline=True)
            e.add_field(name="✨ XP total",        value=f"`{xp_db[gid][uid]}`",     inline=True)
            e.add_field(name="🎯 Prochain niveau", value=f"`{next_xp}` XP",          inline=True)
            if s_data["streak"] > 1:
                e.add_field(name="🔥 Streak", value=f"{s_data['streak']} jours consécutifs !", inline=False)
            e.set_footer(text=f"Kozakura XP  •  {guild.name}")
            level_ch = discord.utils.find(
                lambda c: "niveaux" in c.name.lower() or "niveau" in c.name.lower(),
                guild.text_channels)
            target = level_ch if level_ch else message.channel
            await target.send(embed=e)
            for req, rname in sorted(LEVEL_ROLES.items()):
                if new_level >= req:
                    role = discord.utils.get(guild.roles, name=rname)
                    if role and role not in author.roles:
                        try: await author.add_roles(role)
                        except Exception: pass
    if gid in custom_cmds_db:
        trigger = message.content.lower().strip()
        if trigger in custom_cmds_db[gid]:
            await message.channel.send(custom_cmds_db[gid][trigger])
            return

    # ── AFK — retour de l'auteur ──────────────────────────────────────────────
    if not message.content.startswith(PREFIX):
        afk_entry = afk_db.get(gid, {}).get(uid)
        if afk_entry:
            del afk_db[gid][uid]
            save_json("afk.json", afk_db)
            try:
                await message.reply(
                    f"✅ Bienvenue de retour {author.mention} ! Ton statut AFK a été retiré.",
                    delete_after=8, mention_author=False)
            except Exception: pass

    # ── AFK — mention d'un membre AFK ────────────────────────────────────────
    for mentioned in message.mentions:
        m_uid = str(mentioned.id)
        afk_entry = afk_db.get(gid, {}).get(m_uid)
        if afk_entry and m_uid != uid:
            since = afk_entry.get("since", "")
            reason = afk_entry.get("reason", "Pas de raison")
            try:
                await message.reply(
                    f"💤 **{mentioned.display_name}** est AFK depuis `{since[:16]}`\n**Raison :** {reason}",
                    delete_after=10, mention_author=False)
            except Exception: pass

    # ── IA — Réponse automatique ──────────────────────────────────────────────
    # Ne pas répondre si c'est une commande
    if message.content.startswith(PREFIX):
        await bot.process_commands(message)
        return

    await bot.process_commands(message)

    channel_low = message.channel.name.lower()

    # Vérifier si c'est un salon ignoré
    if any(ign in channel_low for ign in AI_IGNORE_CHANNELS):
        return

    if not ANTHROPIC_API_KEY:
        return

    # Conditions pour répondre :
    # 1. Le bot est mentionné
    # 2. Quelqu'un répond au bot
    # 3. C'est un salon IA spécifique (pas "général" pour éviter le spam)
    bot_mentioned = bot.user in message.mentions
    reply_to_bot  = (message.reference and message.reference.resolved and
                     hasattr(message.reference.resolved, 'author') and
                     message.reference.resolved.author == bot.user)
    auto_channel  = any(kw in channel_low for kw in ["ia", "ai", "kozakura-bot", "bot-kozakura"])

    should_respond = bot_mentioned or reply_to_bot or auto_channel

    if not should_respond:
        return

    # Anti-doublon : ignorer si le même message a déjà été traité (protection Railway)
    msg_key = f"{message.id}"
    if msg_key in ai_conversations.get("__processed__", set()):
        return
    if "__processed__" not in ai_conversations:
        ai_conversations["__processed__"] = set()
    ai_conversations["__processed__"].add(msg_key)
    # Nettoyer après 100 entrées
    if len(ai_conversations["__processed__"]) > 100:
        ai_conversations["__processed__"] = set(list(ai_conversations["__processed__"])[-50:])

    # Détecter conflit
    if await detect_conflict(message.content):
        staff_role = discord.utils.get(guild.roles, name="Gestion")
        alert_ch   = discord.utils.find(lambda c: "log" in c.name.lower() or "staff" in c.name.lower(), guild.text_channels)
        if alert_ch:
            e = discord.Embed(
                title="⚠️ Conflit Détecté par l'IA",
                description=f"Message potentiellement conflictuel de {author.mention} dans {message.channel.mention}",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            e.add_field(name="Message", value=f"||{message.content[:300]}||")
            e.add_field(name="Membre", value=f"{author} (`{author.id}`)")
            mention = staff_role.mention if staff_role else "@staff"
            await alert_ch.send(content=mention, embed=e)

    # Construire l'historique de conversation
    uid = str(author.id)
    if uid not in ai_conversations:
        ai_conversations[uid] = []

    # Nettoyer la mention du bot du message
    content_clean = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    if not content_clean:
        content_clean = "Bonjour !"

    # ── Mémoriser le pseudo préféré ──────────────────────────────────────────
    import re as _re
    _name_match = _re.search(
        r"(?:appelle[- ]moi|mon (?:prénom|pseudo|nom) (?:est|c'est)|je m'appelle)\s+([A-Za-zÀ-ÿ0-9_\-]{2,20})",
        content_clean, _re.IGNORECASE
    )
    if _name_match:
        preferred = _name_match.group(1).strip()
        user_prefs_db.setdefault(uid, {})["preferred_name"] = preferred
        save_json("user_prefs.json", user_prefs_db)

    # Utiliser le pseudo préféré s'il existe
    display_name = user_prefs_db.get(uid, {}).get("preferred_name", author.display_name)

    # ── Détection NSFW dans message IA — réponse éducative ──────────────────
    if any(p in content_clean.lower() for p in NSFW_AI_PATTERNS):
        nsfw_reply = (
            f"🌸 {author.mention}, je suis Kozakura et ce type de demande n'est pas approprié ici. "
            f"Ce serveur est un espace respectueux — tout contenu sexuel ou harcèlement est strictement interdit. "
            f"Merci de respecter les règles de la communauté. ⛩️"
        )
        await message.reply(nsfw_reply)
        return

    ai_conversations[uid].append({"role": "user", "content": f"{display_name}: {content_clean}"})

    # Garder seulement les N derniers messages
    if len(ai_conversations[uid]) > AI_MAX_HISTORY:
        ai_conversations[uid] = ai_conversations[uid][-AI_MAX_HISTORY:]

    # Indicateur de frappe
    async with message.channel.typing():
        # Contexte membre pour réponses personnalisées
        days  = (datetime.utcnow() - author.joined_at.replace(tzinfo=None)).days if author.joined_at else 0
        level = get_level(xp_db.get(gid, {}).get(uid, 0))
        sancs = len(sanctions_db.get(gid, {}).get(uid, []))
        member_ctx = {"days": days, "level": level, "sanctions": sancs}
        response = await call_claude(ai_conversations[uid], member_ctx=member_ctx)

    # Sauvegarder la réponse dans l'historique
    ai_conversations[uid].append({"role": "assistant", "content": response})

    # Envoyer la réponse
    if len(response) > 2000:
        # Découper si trop long
        for i in range(0, len(response), 1990):
            await message.reply(response[i:i+1990])
    else:
        await message.reply(response)

@bot.event
async def on_message_delete(message):
    if message.author.bot: return

    # Cherche qui a supprimé dans l'audit log
    deleter = None
    try:
        await asyncio.sleep(0.5)
        async for entry in message.guild.audit_logs(limit=5, action=discord.AuditLogAction.message_delete):
            if (entry.target.id == message.author.id
                    and (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 8):
                deleter = entry.user
                break
    except Exception:
        pass

    deleted_by = f"🗑️ Supprimé par **{deleter.mention}**" if deleter and deleter != message.author else "🗑️ Auto-supprimé par l'auteur"

    # Log photos/fichiers séparé
    if message.attachments:
        for att in message.attachments:
            e_photo = discord.Embed(
                title="🖼️  Fichier Supprimé",
                description=(
                    f"**Auteur :** {message.author.mention}\n"
                    f"**Salon :** {message.channel.mention}\n"
                    f"{deleted_by}"
                ),
                color=discord.Color.from_rgb(255, 149, 0),
                timestamp=datetime.utcnow()
            )
            e_photo.add_field(name="📎 Fichier", value=f"`{att.filename}`", inline=True)
            if att.content_type and att.content_type.startswith("image"):
                e_photo.set_image(url=att.proxy_url)
            e_photo.set_thumbnail(url=message.author.display_avatar.url)
            e_photo.set_footer(text=f"ID auteur : {message.author.id}")
            await log_photo(message.guild, e_photo)

    # Log message supprimé
    if message.content:
        e = discord.Embed(
            title="🗑️  Message Supprimé",
            description=(
                f"**Auteur :** {message.author.mention}\n"
                f"**Salon :** {message.channel.mention}\n"
                f"{deleted_by}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{message.content[:900]}"
            ),
            color=discord.Color.from_rgb(237, 66, 69),
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=message.author.display_avatar.url)
        e.set_footer(text=f"ID auteur : {message.author.id}  •  #{message.channel.name}")
        await log_message(message.guild, e)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content: return
    e = discord.Embed(
        title="✏️  Message Modifié",
        description=(
            f"**Auteur :** {before.author.mention}\n"
            f"**Salon :** {before.channel.mention}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="📝 Avant", value=before.content[:500] or "*(vide)*", inline=False)
    e.add_field(name="✅ Après", value=after.content[:500] or "*(vide)*", inline=False)
    e.add_field(name="🔗 Lien", value=f"[Aller au message]({after.jump_url})", inline=True)
    e.set_thumbnail(url=before.author.display_avatar.url)
    e.set_footer(text=f"ID : {before.author.id}  •  #{before.channel.name}")
    await log_message(before.guild, e)


# ─── HELPER SALON SANCTION ────────────────────────────────────────────────────
sanctions_db = load_json("sanctions.json", {})

async def log_sanction(guild, member, type_sanction, reason, moderator, extra=""):
    """Enregistre la sanction en DB et l'envoie dans le salon sanction"""
    gid = str(guild.id); uid = str(member.id)
    sanctions_db.setdefault(gid, {}).setdefault(uid, []).append({
        "type":      type_sanction,
        "reason":    reason,
        "by":        str(moderator.id),
        "by_name":   moderator.display_name,
        "date":      str(datetime.utcnow()),
        "extra":     extra
    })
    save_json("sanctions.json", sanctions_db)

    # Couleurs par type
    colors = {
        "Ban": discord.Color.dark_red(),
        "Kick": discord.Color.orange(),
        "Mute": discord.Color.greyple(),
        "Unmute": discord.Color.green(),
        "Warn": discord.Color.yellow(),
        "Unban": discord.Color.green(),
    }
    emojis = {
        "Ban": "🔨", "Kick": "👟", "Mute": "🔇",
        "Unmute": "🔊", "Warn": "⚠️", "Unban": "✅"
    }
    color = colors.get(type_sanction, discord.Color.red())
    emoji = emojis.get(type_sanction, "🔴")

    e = discord.Embed(
        title=f"{emoji} {type_sanction}",
        color=color,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre",     value=f"{member.mention}\n`{member} ({member.id})`", inline=True)
    e.add_field(name="🛡️ Modérateur", value=moderator.mention, inline=True)
    e.add_field(name="📋 Raison",     value=reason, inline=False)
    if extra:
        e.add_field(name="ℹ️ Info", value=extra, inline=False)
    total = len(sanctions_db[gid][uid])
    e.set_footer(text=f"Sanction #{total} • {guild.name}")

    # Logs sanctions → logs-bans uniquement
    await log_ban(guild, e)
    return e

# ─── RÔLES AUTORISÉS POUR LES SANCTIONS ──────────────────────────────────────
ROLES_BAN  = ("kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Inspecteur", "Chef Gestion", "[+] Kozakura gestion", "A. Kozakura")
ROLES_KICK = ("kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Inspecteur", "Chef Gestion", "[+] Kozakura gestion", "A. Kozakura")
ROLES_MUTE = ["kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Inspecteur", "Chef Gestion", "[+] Kozakura gestion", "A. Kozakura", "Gestion Staff", "Gestion Modérations", "Gestion Abus", "Gestion"]
ROLES_WARN = ["kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Inspecteur", "Chef Gestion", "[+] Kozakura gestion", "A. Kozakura", "Gestion Staff", "Gestion Modérations", "Gestion Abus", "Gestion"]

# Rôles autorisés pour le tribunal (Inspecteur + grades supérieurs)
ROLES_TRIBUNAL = ("kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Inspecteur", "Chef Gestion", "[+] Kozakura gestion")

# Rôles autorisés pour rankup/derank (Gestion Modérations inclus, avec restriction hiérarchique)
ROLES_RANKDERANK = ("kozakura", "kozakura C.O.D", "Co Propriétaire", "Développer", "Royal", "Chef Gestion", "[+] Kozakura gestion", "A. Kozakura", "Gestion Modérations")

# Mass ban : uniquement Développer et kozakura C.O.D
ROLES_MASSBAN = ("kozakura", "kozakura C.O.D", "Développer")

def has_sanction_role(member, roles_list):
    """Vérifie si le membre a l'un des rôles autorisés"""
    member_roles = [r.name for r in member.roles]
    return any(r in member_roles for r in roles_list)

def staff_only(roles=None):
    """Décorateur custom : vérifie que l'auteur a un rôle staff (ROLES_WARN par défaut)"""
    async def predicate(ctx):
        r = roles if roles is not None else ROLES_WARN
        if has_sanction_role(ctx.author, r):
            return True
        await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.", delete_after=5)
        return False
    return commands.check(predicate)

# ─── MODÉRATION ───────────────────────────────────────────────────────────────
@bot.command()
async def ban(ctx, member: discord.Member = None, *, reason="Aucune raison"):
    if member is None:
        return await ctx.send("❌ Mentionne un membre : `!ban @membre [raison]`", delete_after=5)
    if not has_sanction_role(ctx.author, ROLES_BAN):
        return await ctx.send("❌ Tu n'as pas la permission de bannir.", delete_after=5)
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send("❌ Je ne peux pas bannir ce membre (son rôle est supérieur ou égal au mien).", delete_after=5)
    if member == ctx.author:
        return await ctx.send("❌ Tu ne peux pas te bannir toi-même.", delete_after=5)
    await dm(member, "🔨 Tu as été banni",
        f"**Serveur :** {ctx.guild.name}\n**Raison :** {reason}\n\nSi tu penses que c'est une erreur, contacte un administrateur.",
        color=discord.Color.dark_red())
    try:
        await member.ban(reason=reason, delete_message_days=7)
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée. Vérifie que le bot a le droit `Bannir des membres`.", delete_after=8)
    except discord.HTTPException as ex:
        return await ctx.send(f"❌ Erreur Discord : `{ex}`", delete_after=8)
    e = await log_sanction(ctx.guild, member, "Ban", reason, ctx.author)
    await ctx.send(embed=e)

@bot.command()
async def unban(ctx, user_id: int, *, reason="Aucune raison"):
    if not has_sanction_role(ctx.author, ROLES_BAN):
        return await ctx.send("❌ Tu n'as pas la permission de débannir.", delete_after=5)
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=reason)
    e = discord.Embed(title="✅ Unban", color=discord.Color.green(), timestamp=datetime.utcnow())
    e.add_field(name="👤 Utilisateur", value=f"`{user} ({user.id})`")
    e.add_field(name="🛡️ Modérateur",  value=ctx.author.mention)
    e.add_field(name="📋 Raison",      value=reason, inline=False)
    await log(ctx.guild, e)
    await ctx.send(embed=e)

@bot.command()
async def kick(ctx, member: discord.Member = None, *, reason="Aucune raison"):
    if member is None:
        return await ctx.send("❌ Mentionne un membre : `!kick @membre [raison]`", delete_after=5)
    if not has_sanction_role(ctx.author, ROLES_KICK):
        return await ctx.send("❌ Tu n'as pas la permission d'expulser.", delete_after=5)
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send("❌ Je ne peux pas expulser ce membre (hiérarchie des rôles).", delete_after=5)
    dm_e = discord.Embed(
        title="👟  Tu as été expulsé",
        description=(
            f"**Serveur :** {ctx.guild.name}\n"
            f"**Raison :** {reason}\n\n"
            "Si tu penses que c'est une erreur, contacte un administrateur."
        ),
        color=discord.Color.from_rgb(255, 149, 0)
    )
    dm_e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    try:
        await member.send(embed=dm_e)
    except Exception: pass
    try:
        await member.kick(reason=reason)
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée.", delete_after=5)
    e = await log_sanction(ctx.guild, member, "Kick", reason, ctx.author)
    await ctx.send(embed=e)

@bot.command()
async def mute(ctx, member: discord.Member = None, duration: int = 10, *, reason="Aucune raison"):
    if member is None:
        return await ctx.send("❌ Mentionne un membre : `!mute @membre [minutes] [raison]`", delete_after=5)
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Tu n'as pas la permission de mute.", delete_after=5)
    until = discord.utils.utcnow() + timedelta(minutes=duration)
    try:
        await member.timeout(until, reason=reason)
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée.", delete_after=5)
    dm_e = discord.Embed(
        title="🔇  Tu as été mis en sourdine",
        description=(
            f"**Serveur :** {ctx.guild.name}\n"
            f"**Durée :** {duration} minute(s)\n"
            f"**Raison :** {reason}\n\n"
            f"Tu seras automatiquement démuté dans **{duration} min**."
        ),
        color=discord.Color.from_rgb(114, 118, 125)
    )
    dm_e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    try:
        await member.send(embed=dm_e)
    except Exception: pass
    e = await log_sanction(ctx.guild, member, "Mute", reason, ctx.author, extra=f"Durée : {duration} min")
    await ctx.send(embed=e)

@bot.command()
async def unmute(ctx, member: discord.Member):
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Tu n'as pas la permission de démute.", delete_after=5)
    await member.timeout(None)
    await dm(member, "🔊 Tu as été démuté",
        f"**Serveur :** {ctx.guild.name}\nTu peux à nouveau parler !",
        color=discord.Color.green())
    e = await log_sanction(ctx.guild, member, "Unmute", "Fin du mute", ctx.author)
    await ctx.send(embed=e)

@bot.command()
@staff_only()
async def purge(ctx, amount: int):
    deleted = await ctx.channel.purge(limit=amount + 1)
    count = len(deleted) - 1
    e = discord.Embed(description=f"🗑️ {count} messages supprimés par {ctx.author.mention}",
        color=discord.Color.red(), timestamp=datetime.utcnow())
    await log(ctx.guild, e)
    await ctx.send(f"✅ {count} messages supprimés.", delete_after=5)

@bot.command()
@staff_only()
async def clear(ctx, amount_or_member=None, amount: int = 10):
    """
    !clear [nombre]           — Supprime les X derniers messages
    !clear @membre [nombre]   — Supprime les X derniers messages d'un membre
    """
    target_member = None

    # Déterminer si le premier argument est un membre ou un nombre
    if amount_or_member is not None:
        # Essayer de convertir en membre
        try:
            target_member = await commands.MemberConverter().convert(ctx, str(amount_or_member))
        except commands.BadArgument:
            # C'est un nombre
            try:
                amount = int(amount_or_member)
                target_member = None
            except ValueError:
                return await ctx.send("❌ Usage : `!clear [nombre]` ou `!clear @membre [nombre]`")

    amount = min(max(amount, 1), 100)

    try:
        await ctx.message.delete()
    except Exception: pass

    if target_member:
        # Supprimer uniquement les messages du membre ciblé
        def is_target(msg):
            return msg.author == target_member

        deleted = await ctx.channel.purge(limit=300, check=is_target, after=discord.utils.utcnow() - timedelta(days=14))
        # Limiter au nombre demandé
        count = min(len(deleted), amount)
        if len(deleted) > amount:
            # On a supprimé trop, pas possible de "unsuppress" donc on informe juste
            pass

        e = discord.Embed(
            title="🧹 Clear Ciblé",
            description=f"{ctx.author.mention} a supprimé **{len(deleted)}** message(s) de {target_member.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=target_member.display_avatar.url)
        e.add_field(name="Membre ciblé", value=target_member.mention)
        e.add_field(name="Messages supprimés", value=str(len(deleted)))
        e.add_field(name="Salon", value=ctx.channel.mention)
    else:
        deleted = await ctx.channel.purge(limit=amount)
        e = discord.Embed(
            title="🧹 Clear",
            description=f"{ctx.author.mention} a supprimé **{len(deleted)}** message(s) dans {ctx.channel.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

    await log(ctx.guild, e)
    await ctx.send(embed=e, delete_after=5)


@bot.command()
@staff_only()
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    status = f"**{seconds}s**" if seconds > 0 else "**désactivé**"
    await ctx.send(f"⏱️ Slowmode {status} dans {ctx.channel.mention}")

# ─── AVERTISSEMENTS ───────────────────────────────────────────────────────────
@bot.command()
async def warn(ctx, member: discord.Member = None, *, reason="Aucune raison"):
    if member is None:
        return await ctx.send("❌ Mentionne un membre : `!warn @membre [raison]`", delete_after=5)
    if not has_sanction_role(ctx.author, ROLES_WARN):
        return await ctx.send("❌ Tu n'as pas la permission d'avertir.", delete_after=5)
    gid = str(ctx.guild.id); uid = str(member.id)
    warnings_db.setdefault(gid, {}).setdefault(uid, []).append(
        {"reason": reason, "by": str(ctx.author.id), "date": str(datetime.utcnow())})
    save_json("warnings.json", warnings_db)
    count = len(warnings_db[gid][uid])
    WARN_COLORS = {1: 0xFFD700, 2: 0xFF9500, 3: 0xFF4444}
    color = WARN_COLORS.get(count, 0xFF0000)
    dm_e = discord.Embed(
        title=f"⚠️  Avertissement n°{count}",
        description=(
            f"**Serveur :** {ctx.guild.name}\n"
            f"**Raison :** {reason}\n\n"
            f"{'⛔ Attention : tu accumules des avertissements, une sanction peut suivre.' if count >= 3 else ''}"
        ),
        color=color
    )
    dm_e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    try:
        await member.send(embed=dm_e)
    except Exception: pass
    e = await log_sanction(ctx.guild, member, "Warn", reason, ctx.author, extra=f"Avertissement n°{count}")
    await ctx.send(embed=e)
    if count >= 3:
        alert = discord.Embed(
            title="⛔  Avertissements multiples",
            description=f"{member.mention} cumule **{count} avertissements** — une sanction est recommandée.",
            color=0xFF0000, timestamp=datetime.utcnow()
        )
        alert.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=alert)

@bot.command()
async def warnings(ctx, member: discord.Member = None):
    member = member or ctx.author
    gid    = str(ctx.guild.id); uid = str(member.id)
    data   = warnings_db.get(gid, {}).get(uid, [])
    count  = len(data)
    WARN_COLORS = {0: 0x57F287, 1: 0xFFD700, 2: 0xFF9500}
    color  = WARN_COLORS.get(count, 0xFF4444)
    e = discord.Embed(
        title=f"⚠️  Avertissements — {member.display_name}",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Total :** `{count}` avertissement(s)\n"
            f"{'⛔ Sanction recommandée' if count >= 3 else '✅ Historique propre' if count == 0 else ''}"
        ),
        color=color,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_author(name=f"{member}", icon_url=member.display_avatar.url)
    if not data:
        e.add_field(name="📋 Historique", value="Aucun avertissement ✅", inline=False)
    else:
        for i, w in enumerate(data[-5:], 1):
            by = ctx.guild.get_member(int(w.get("by", 0)))
            by_str = by.display_name if by else "Inconnu"
            e.add_field(
                name=f"⚠️ Warn #{i}  •  {w['date'][:10]}",
                value=f"**Raison :** {w['reason'][:100]}\n**Par :** {by_str}",
                inline=False
            )
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
@staff_only()
async def clearwarns(ctx, member: discord.Member):
    gid = str(ctx.guild.id); uid = str(member.id)
    if gid in warnings_db: warnings_db[gid][uid] = []
    save_json("warnings.json", warnings_db)
    await ctx.send(f"✅ Warns de {member.mention} réinitialisés.")

# ─── INFOSANCTION ─────────────────────────────────────────────────────────────
@bot.command()
@staff_only()
async def infosanction(ctx, member: discord.Member):
    """!infosanction @membre — Affiche toutes les sanctions d'un membre"""
    gid  = str(ctx.guild.id)
    uid  = str(member.id)
    data = sanctions_db.get(gid, {}).get(uid, [])

    if not data:
        e = discord.Embed(
            title=f"📋 Sanctions de {member.display_name}",
            description="✅ Aucune sanction enregistrée.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=member.display_avatar.url)
        return await ctx.send(embed=e)

    # Compter par type
    counts = {}
    for s in data:
        t = s["type"]
        counts[t] = counts.get(t, 0) + 1

    summary = " | ".join(f"**{v}x {k}**" for k, v in counts.items())

    e = discord.Embed(
        title=f"📋 Sanctions de {member.display_name}",
        description=f"Total : **{len(data)} sanction(s)**\n{summary}",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre", value=f"{member.mention} (`{member.id}`)", inline=False)

    # Afficher les 10 dernières sanctions
    emojis_type = {
        "Ban": "🔨", "Kick": "👟", "Mute": "🔇",
        "Unmute": "🔊", "Warn": "⚠️", "Unban": "✅"
    }
    for i, s in enumerate(reversed(data[-10:]), 1):
        emoji = emojis_type.get(s["type"], "🔴")
        date  = s["date"][:10]
        extra = f"\n*{s['extra']}*" if s.get("extra") else ""
        e.add_field(
            name=f"{emoji} #{len(data) - i + 1} — {s['type']} ({date})",
            value=f"📋 {s['reason']}{extra}\n🛡️ Par : {s['by_name']}",
            inline=False
        )

    if len(data) > 10:
        e.set_footer(text=f"Affichage des 10 dernières sur {len(data)} sanctions • {ctx.guild.name}")
    else:
        e.set_footer(text=f"{ctx.guild.name}")

    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def clearsanctions(ctx, member: discord.Member):
    """!clearsanctions @membre — Efface toutes les sanctions d'un membre"""
    gid = str(ctx.guild.id); uid = str(member.id)
    if gid in sanctions_db: sanctions_db[gid][uid] = []
    save_json("sanctions.json", sanctions_db)
    await ctx.send(f"✅ Toutes les sanctions de {member.mention} ont été effacées.")

# ─── XP / NIVEAUX ─────────────────────────────────────────────────────────────
@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    gid = str(ctx.guild.id); uid = str(member.id)
    gid_data  = xp_db.get(gid, {})
    xp        = gid_data.get(uid, 0)
    lvl       = get_level(xp)
    next_xp   = xp_for_level(lvl + 1)
    prev_xp   = xp_for_level(lvl)
    progress  = (xp - prev_xp) / max(next_xp - prev_xp, 1)
    bar_fill  = int(progress * 14)
    bar       = "█" * bar_fill + "░" * (14 - bar_fill)
    sorted_lb = sorted(gid_data.items(), key=lambda x: x[1], reverse=True)
    rank_pos  = next((i + 1 for i, (u, _) in enumerate(sorted_lb) if u == uid), "?")

    SAKURA_PINK = 0xFF89B4
    e = discord.Embed(
        description=(
            f"## ⭐  Niveau {lvl}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"`{bar}` **{int(progress*100)}%**\n"
            f"**{xp}** XP  ›  prochain niveau à **{next_xp}** XP"
        ),
        color=SAKURA_PINK,
        timestamp=datetime.utcnow()
    )
    e.set_author(name=f"{member.display_name}  •  Rang #{rank_pos}", icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="🏅 Niveau",    value=f"`{lvl}`",          inline=True)
    e.add_field(name="✨ XP total",  value=f"`{xp}`",           inline=True)
    e.add_field(name="🏆 Classement", value=f"`#{rank_pos}`",   inline=True)
    e.set_footer(text=f"Kozakura XP  •  {ctx.guild.name}", icon_url=ctx.guild.me.display_avatar.url)
    await ctx.send(embed=e)

@bot.command()
async def leaderboard(ctx):
    gid  = str(ctx.guild.id)
    top  = sorted(xp_db.get(gid, {}).items(), key=lambda x: x[1], reverse=True)[:10]
    SAKURA_PINK = 0xFF89B4
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    e = discord.Embed(
        title="🏆  Classement XP — Kozakura",
        color=SAKURA_PINK,
        timestamp=datetime.utcnow()
    )
    if ctx.guild.icon:
        e.set_thumbnail(url=ctx.guild.icon.url)
    if not top:
        e.description = "Aucune donnée XP enregistrée."
    else:
        lines = []
        for i, (uid, xp) in enumerate(top):
            m   = ctx.guild.get_member(int(uid))
            lvl = get_level(xp)
            name = m.display_name if m else f"*{uid}*"
            lines.append(f"{medals[i]} **{name}** — Niv. `{lvl}`  •  `{xp}` XP")
        e.description = "\n".join(lines)
    e.set_footer(text=f"Kozakura XP  •  {ctx.guild.name}")
    await ctx.send(embed=e)

# ─── BIENVENUE MANUELLE ────────────────────────────────────────────────────────
# ── ID du salon de bienvenue fixe ─────────────────────────────────────────────
WELCOME_CHANNEL_ID = 1477427118391558195

async def send_welcome(guild: discord.Guild, member: discord.Member, give_xp: bool = True):
    """Envoie l'embed de bienvenue dans le salon WELCOME_CHANNEL_ID."""
    chat_ch = guild.get_channel(WELCOME_CHANNEL_ID)
    if not chat_ch:
        return

    if give_xp:
        gid = str(guild.id); uid = str(member.id)
        gid_data = xp_db.setdefault(gid, {})
        gid_data[uid] = gid_data.get(uid, 0) + 50
        save_json("xp.json", xp_db)

    e = discord.Embed(
        description=f"🌸  Bienvenue {member.mention} — tu es le **{guild.member_count}ème** membre !",
        color=0xFF89B4
    )
    if guild.banner:
        e.set_image(url=guild.banner.url)
    elif guild.icon:
        e.set_image(url=guild.icon.url)
    await chat_ch.send(embed=e)


@bot.listen("on_member_join")
async def auto_welcome(member: discord.Member):
    """Envoie automatiquement le message de bienvenue à chaque arrivée."""
    if member.bot:
        return
    await send_welcome(member.guild, member, give_xp=True)


@bot.command(name="bvn")
async def bvn(ctx, member: discord.Member = None):
    """!bvn [@membre] — Envoie un message de bienvenue dans le salon dédié"""
    member  = member or ctx.author
    guild   = ctx.guild
    chat_ch = guild.get_channel(WELCOME_CHANNEL_ID)

    await send_welcome(guild, member, give_xp=True)

    if chat_ch and ctx.channel.id != WELCOME_CHANNEL_ID:
        await ctx.send(
            f"🌸 Bienvenue sur le serveur {member.mention} ! Message envoyé dans {chat_ch.mention} ✿",
            delete_after=8
        )
    elif not chat_ch:
        await ctx.send("❌ Salon de bienvenue introuvable (ID: `1477427118391558195`).", delete_after=8)

# ─── SUGGESTIONS / SONDAGES ───────────────────────────────────────────────────
class SuggestionView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Approuver", emoji="✅", style=discord.ButtonStyle.green, custom_id="sug_approve")
    async def approve(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if not has_sanction_role(interaction.user, ROLES_MUTE):
            return await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)
        e = interaction.message.embeds[0]
        new_e = discord.Embed(
            title="✅  Suggestion Approuvée",
            description=e.description,
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        for field in e.fields:
            new_e.add_field(name=field.name, value=field.value, inline=field.inline)
        new_e.add_field(name="✅ Décision", value=f"Approuvée par {interaction.user.mention}", inline=False)
        new_e.set_footer(text=e.footer.text if e.footer else "")
        await interaction.message.edit(embed=new_e, view=None)
        await interaction.response.send_message("✅ Suggestion approuvée.", ephemeral=True)

    @discord.ui.button(label="Refuser", emoji="❌", style=discord.ButtonStyle.red, custom_id="sug_deny")
    async def deny(self, interaction: discord.Interaction, btn: discord.ui.Button):
        if not has_sanction_role(interaction.user, ROLES_MUTE):
            return await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)
        e = interaction.message.embeds[0]
        new_e = discord.Embed(
            title="❌  Suggestion Refusée",
            description=e.description,
            color=0xED4245,
            timestamp=datetime.utcnow()
        )
        for field in e.fields:
            new_e.add_field(name=field.name, value=field.value, inline=field.inline)
        new_e.add_field(name="❌ Décision", value=f"Refusée par {interaction.user.mention}", inline=False)
        new_e.set_footer(text=e.footer.text if e.footer else "")
        await interaction.message.edit(embed=new_e, view=None)
        await interaction.response.send_message("❌ Suggestion refusée.", ephemeral=True)


async def suggest(ctx, *, suggestion):
    ch_id = get_cfg(ctx.guild.id, "suggestion_channel")
    ch    = ctx.guild.get_channel(int(ch_id)) if ch_id else ctx.channel
    e = discord.Embed(
        title="💡  Nouvelle Suggestion",
        description=f"{suggestion}",
        color=0x5865F2,
        timestamp=datetime.utcnow()
    )
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    e.add_field(name="👤 Auteur", value=ctx.author.mention, inline=True)
    e.add_field(name="📅 Date",   value=datetime.utcnow().strftime("%d/%m/%Y"), inline=True)
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    msg = await ch.send(embed=e, view=SuggestionView())
    await msg.add_reaction("✅"); await msg.add_reaction("❌")
    if ch != ctx.channel:
        await ctx.send("✅ Suggestion envoyée !", delete_after=5)
    try: await ctx.message.delete()
    except Exception: pass

@bot.command()
async def poll(ctx, question, *options):
    if len(options) < 2:
        return await ctx.send("❌ Minimum 2 options. Ex: `!poll \"Question\" \"Option 1\" \"Option 2\"`")
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    opts   = options[:10]
    lines  = "\n".join(f"{emojis[i]}  {opt}" for i, opt in enumerate(opts))
    e = discord.Embed(
        title=f"📊  {question}",
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{lines}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Réagis avec le numéro de ton choix !"
        ),
        color=0x5865F2,
        timestamp=datetime.utcnow()
    )
    e.set_author(name=f"Sondage par {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}  •  {len(opts)} option(s)")
    msg = await ctx.send(embed=e)
    for i in range(len(opts)):
        await msg.add_reaction(emojis[i])
    try: await ctx.message.delete()
    except Exception: pass

# ─── RAPPELS ──────────────────────────────────────────────────────────────────
@bot.command()
async def remind(ctx, duration: int, unit: str, *, message):
    mult = {"s": 1, "min": 60, "h": 3600, "j": 86400}.get(unit.lower(), 60)
    reminders_db.setdefault(str(ctx.author.id), []).append({
        "channel": ctx.channel.id, "message": message,
        "fire_at": time.time() + duration * mult})
    save_json("reminders.json", reminders_db)
    await ctx.send(f"⏰ Rappel dans **{duration} {unit}** !", delete_after=10)

@tasks.loop(seconds=30)
async def check_reminders():
    now = time.time(); changed = False
    for uid, rems in list(reminders_db.items()):
        keep = []
        for r in rems:
            if now >= r["fire_at"]:
                changed = True
                ch = bot.get_channel(r["channel"])
                try:
                    user = await bot.fetch_user(int(uid))
                    if ch: await ch.send(f"⏰ {user.mention} Rappel : **{r['message']}**")
                except Exception: pass
            else: keep.append(r)
        reminders_db[uid] = keep
    if changed: save_json("reminders.json", reminders_db)

# ─── STATS ────────────────────────────────────────────────────────────────────
@bot.command()
async def stats(ctx):
    g       = ctx.guild
    bots    = sum(1 for m in g.members if m.bot)
    humans  = g.member_count - bots
    online  = sum(1 for m in g.members if m.status != discord.Status.offline and not m.bot)
    vocal   = sum(len(vc.members) for vc in g.voice_channels)
    boosts  = g.premium_subscription_count or 0
    tier    = g.premium_tier
    text_ch = len(g.text_channels)
    voice_ch= len(g.voice_channels)
    roles   = len(g.roles) - 1
    age     = (datetime.utcnow() - g.created_at.replace(tzinfo=None)).days
    e = discord.Embed(
        title=f"📊  Statistiques — {g.name}",
        description=f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=0xFF89B4,
        timestamp=datetime.utcnow()
    )
    if g.icon:   e.set_thumbnail(url=g.icon.url)
    if g.banner: e.set_image(url=g.banner.url)
    e.set_author(name=g.name, icon_url=g.icon.url if g.icon else discord.Embed.Empty)
    e.add_field(name="👥 Membres",    value=f"`{humans}`",         inline=True)
    e.add_field(name="🟢 En ligne",   value=f"`{online}`",         inline=True)
    e.add_field(name="🤖 Bots",       value=f"`{bots}`",           inline=True)
    e.add_field(name="🎙️ En vocal",   value=f"`{vocal}`",          inline=True)
    e.add_field(name="💬 Salons text",value=f"`{text_ch}`",        inline=True)
    e.add_field(name="🔊 Salons voix",value=f"`{voice_ch}`",       inline=True)
    e.add_field(name="🎭 Rôles",      value=f"`{roles}`",          inline=True)
    e.add_field(name="💎 Boosts",     value=f"`{boosts}` (Niv. {tier})", inline=True)
    e.add_field(name="📅 Âge",        value=f"`{age}` jours",      inline=True)
    inv = get_cfg(g.id, "invite_link")
    if inv: e.add_field(name="🔗 Invitation", value=inv, inline=False)
    e.set_footer(text=f"Kozakura  •  ID : {g.id}")
    await ctx.send(embed=e)

# ─── COMMANDES PERSONNALISÉES ─────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def addcmd(ctx, trigger, *, response):
    custom_cmds_db.setdefault(str(ctx.guild.id), {})[trigger.lower()] = response
    save_json("custom_commands.json", custom_cmds_db)
    await ctx.send(f"✅ Commande `{trigger}` ajoutée !")

@bot.command()
@commands.has_permissions(administrator=True)
async def delcmd(ctx, trigger):
    gid = str(ctx.guild.id)
    if gid in custom_cmds_db and trigger.lower() in custom_cmds_db[gid]:
        del custom_cmds_db[gid][trigger.lower()]
        save_json("custom_commands.json", custom_cmds_db)
        await ctx.send(f"✅ Commande `{trigger}` supprimée.")
    else: await ctx.send("❌ Introuvable.")

# ─── RÔLES RÉACTIONS ──────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def reactionrole(ctx, emoji: str, role: discord.Role, *, desc="Réagis pour obtenir ce rôle"):
    e = discord.Embed(title="🎭 Rôle par Réaction",
        description=f"{emoji} → {role.mention}\n{desc}", color=discord.Color.purple())
    msg = await ctx.send(embed=e); await msg.add_reaction(emoji)
    reaction_roles[str(msg.id)] = {"role_id": role.id, "emoji": emoji}
    save_json("reaction_roles.json", reaction_roles)

# ─── COMPTEURS ────────────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def setupcounters(ctx):
    g = ctx.guild
    cat = await g.create_category("📊 Statistiques")
    mc = await g.create_voice_channel(f"👥 Membres: {g.member_count}", category=cat)
    oc = await g.create_voice_channel("🟢 En ligne: 0", category=cat)
    vc = await g.create_voice_channel("🎙️ En vocal: 0", category=cat)
    set_cfg(g.id, "counter_members", mc.id)
    set_cfg(g.id, "counter_online", oc.id)
    set_cfg(g.id, "counter_voice", vc.id)
    await ctx.send("✅ Compteurs créés !")

@tasks.loop(minutes=5)
async def update_counters():
    for g in bot.guilds:
        try:
            mc_id = get_cfg(g.id, "counter_members")
            oc_id = get_cfg(g.id, "counter_online")
            vc_id = get_cfg(g.id, "counter_voice")
            # IDs des salons compteurs à exclure du compte vocal
            counter_ids = set(filter(None, [mc_id, oc_id, vc_id]))
            if mc_id:
                ch = g.get_channel(int(mc_id))
                if ch: await ch.edit(name=f"👥 Membres: {g.member_count}")
            if oc_id:
                online = sum(1 for m in g.members if m.status != discord.Status.offline and not m.bot)
                ch = g.get_channel(int(oc_id))
                if ch: await ch.edit(name=f"🟢 En ligne: {online}")
            if vc_id:
                # Exclure les salons compteurs du calcul
                vocal = sum(
                    len([m for m in vc.members if not m.bot])
                    for vc in g.voice_channels
                    if str(vc.id) not in counter_ids
                )
                ch = g.get_channel(int(vc_id))
                if ch: await ch.edit(name=f"🎙️ En vocal: {vocal}")
        except Exception: pass

async def refresh_vocal_counter(guild):
    """Met à jour instantanément le compteur vocal"""
    try:
        vc_id = get_cfg(guild.id, "counter_voice")
        mc_id = get_cfg(guild.id, "counter_members")
        oc_id = get_cfg(guild.id, "counter_online")
        if not vc_id: return
        counter_ids = set(filter(None, [str(mc_id), str(oc_id), str(vc_id)]))
        vocal = sum(
            len([m for m in vc.members if not m.bot])
            for vc in guild.voice_channels
            if str(vc.id) not in counter_ids
        )
        ch = guild.get_channel(int(vc_id))
        if ch: await ch.edit(name=f"🎙️ En vocal: {vocal}")
    except Exception: pass

# ─── CONFIGURATION ADMIN ──────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, *, arg: str):
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "log_channel", channel.id)
    await ctx.send(f"✅ Logs → {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, *, arg: str):
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "welcome_channel", channel.id)
    await ctx.send(f"✅ Bienvenue → {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcomemsg(ctx, *, message):
    set_cfg(ctx.guild.id, "welcome_message", message)
    await ctx.send("✅ Message mis à jour ! (`{user}` `{server}` `{count}` disponibles)")

@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, *, arg: str):
    role = await resolve_role(ctx, arg)
    if not role: return await ctx.send("❌ Rôle introuvable.")
    set_cfg(ctx.guild.id, "auto_role", role.id)
    await ctx.send(f"✅ Auto-rôle → {role.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setsuggestions(ctx, *, arg: str):
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "suggestion_channel", channel.id)
    await ctx.send(f"✅ Suggestions → {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setraidthreshold(ctx, number: int):
    set_cfg(ctx.guild.id, "raid_threshold", number)
    await ctx.send(f"✅ Seuil anti-raid : **{number}** joins/10s")

@bot.command()
@commands.has_permissions(administrator=True)
async def setinvite(ctx, link: str):
    set_cfg(ctx.guild.id, "invite_link", link)
    await ctx.send(f"✅ Lien d'invitation enregistré.")

@bot.command()
@commands.has_permissions(administrator=True)
async def addbanword(ctx, word: str):
    BANNED_WORDS.append(word.lower())
    await ctx.send(f"✅ Mot `{word}` ajouté à la liste noire.")

@bot.command()
@commands.has_permissions(administrator=True)
async def addnsfw(ctx, *, phrase: str):
    """!addnsfw [phrase] — Ajoute une phrase/mot à la liste NSFW (persisté)"""
    p = phrase.lower().strip()
    if p in NSFW_WORDS:
        return await ctx.send(f"⚠️ `{p}` est déjà dans la liste NSFW.")
    NSFW_WORDS.append(p)
    if p not in nsfw_words_db["words"]:
        nsfw_words_db["words"].append(p)
        save_json("nsfw_words.json", nsfw_words_db)
    e = discord.Embed(
        title="🔞 Liste NSFW mise à jour",
        description=f"Phrase ajoutée : `{p}`\nTotal : **{len(NSFW_WORDS)} entrées**",
        color=discord.Color.dark_red(), timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Par {ctx.author}")
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def removensfw(ctx, *, phrase: str):
    """!removensfw [phrase] — Retire une phrase/mot de la liste NSFW"""
    p = phrase.lower().strip()
    if p not in NSFW_WORDS:
        return await ctx.send(f"❌ `{p}` n'est pas dans la liste NSFW.")
    NSFW_WORDS.remove(p)
    if p in nsfw_words_db["words"]:
        nsfw_words_db["words"].remove(p)
        save_json("nsfw_words.json", nsfw_words_db)
    e = discord.Embed(
        title="🔞 Liste NSFW mise à jour",
        description=f"Phrase retirée : `{p}`\nTotal : **{len(NSFW_WORDS)} entrées**",
        color=discord.Color.orange(), timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Par {ctx.author}")
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def listnsfw(ctx):
    """!listnsfw — Affiche toutes les phrases NSFW surveillées"""
    if not NSFW_WORDS:
        return await ctx.send("ℹ️ La liste NSFW est vide.")
    lines = "\n".join(f"`{w}`" for w in sorted(NSFW_WORDS))
    e = discord.Embed(
        title=f"🔞 Liste NSFW ({len(NSFW_WORDS)} entrées)",
        description=lines[:2000],
        color=discord.Color.dark_red(), timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
@staff_only()
async def sanctions(ctx, member: discord.Member):
    """!sanctions @membre — Voir le niveau de sanction actuel (warns)"""
    gid = str(ctx.guild.id); uid = str(member.id)
    warns = warnings_db.get(gid, {}).get(uid, [])
    count = len(warns)
    # Niveau de risque
    if count == 0:   niveau, color = "✅ Aucune infraction", discord.Color.green()
    elif count == 1: niveau, color = "⚠️ Niveau 1 — Avertissement", discord.Color.yellow()
    elif count == 2: niveau, color = "🔇 Niveau 2 — Prochain : mute 10min", discord.Color.orange()
    elif count == 3: niveau, color = "🔇 Niveau 3 — Prochain : mute 1h", discord.Color.orange()
    elif count == 4: niveau, color = "👟 Niveau 4 — Prochain : kick", discord.Color.red()
    else:            niveau, color = "🔨 Niveau 5+ — Prochain : BAN", discord.Color.dark_red()

    progression = ["⚠️ Warn", "🔇 Mute 10min", "🔇 Mute 1h", "👟 Kick", "🔨 Ban"]
    e = discord.Embed(
        title=f"📊 Niveau de sanction — {member.display_name}",
        description=f"{niveau}\n\n**Historique progressif :**\n" +
                    "\n".join(f"{'✅' if i < count else '⬜'} {p}" for i, p in enumerate(progression)),
        color=color, timestamp=datetime.utcnow()
    )
    e.add_field(name="⚠️ Warns actifs", value=f"**{count}** infraction(s)", inline=True)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura Security • {ctx.guild.name}")
    if warns:
        last = warns[-1]
        e.add_field(name="📌 Dernière infraction", value=f"{last['reason'][:80]} — {last['date'][:10]}", inline=False)
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# 🎫 SYSTÈME DE TICKETS PREMIUM — KOZAKURA
# ══════════════════════════════════════════════════════════════════════════════

TICKET_TYPES = {
    "staff": {
        "label": "⚒️ Gestion Staff",
        "emoji": "⚒️",
        "color": discord.Color.from_rgb(88, 101, 242),
        "role":    ROLE_GESTION_STAFF,
        "role_id": ROLE_GESTION_STAFF_ID,
        "description": "Candidature staff, rank-up, récupération de rôles perdus.",
        "style": discord.ButtonStyle.blurple,
        "icon": "🛠️",
    },
    "abus": {
        "label": "🛡️ Gestion Abus",
        "emoji": "🛡️",
        "color": discord.Color.from_rgb(237, 66, 69),
        "role":    ROLE_GESTION_ABUS,
        "role_id": ROLE_GESTION_ABUS_ID,
        "description": "Signaler un abus, conflit ou contester une sanction.",
        "style": discord.ButtonStyle.red,
        "icon": "⚖️",
    },
    "cod": {
        "label": "👑 Direction",
        "emoji": "👑",
        "color": discord.Color.gold(),
        "role":  ROLE_COD,
        "role_id": ROLE_COD_ID,
        "description": "Contacter la direction. Décalages, fusions, sujets stratégiques.",
        "style": discord.ButtonStyle.grey,
        "icon": "🏯",
    },
    "partenariat": {
        "label": "🤝 Partenariat",
        "emoji": "🤝",
        "color": discord.Color.from_rgb(87, 242, 135),
        "role":  ROLE_COD,
        "role_id": ROLE_COD_ID,
        "description": "Proposer un partenariat avec le serveur Kozakura.",
        "style": discord.ButtonStyle.green,
        "icon": "🌸",
    },
}

TICKET_PRIORITY_COLORS = {
    "urgent": discord.Color.from_rgb(237, 66, 69),
    "haute":  discord.Color.from_rgb(255, 149, 0),
    "normale": discord.Color.from_rgb(88, 101, 242),
    "basse":  discord.Color.from_rgb(87, 242, 135),
}
TICKET_PRIORITY_EMOJI = {
    "urgent": "🔴", "haute": "🟠", "normale": "🔵", "basse": "🟢",
}

def _track_ticket_stat(gid: str, uid: str, stat: str):
    """Enregistre une action tickets (claims/closes) pour le système On Top."""
    now = int(time.time())
    entry = ticket_stats_db.setdefault(gid, {}).setdefault(uid, {"claims": 0, "closes": 0, "last_activity": now})
    entry[stat] = entry.get(stat, 0) + 1
    entry["last_activity"] = now
    save_json("ticket_stats.json", ticket_stats_db)

# ─── ON TOP : tâche de fond ────────────────────────────────────────────────────
ON_TOP_ROLE_NAME   = "On Top"
ON_TOP_WINDOW_DAYS = 7    # Période prise en compte (7 jours)
ON_TOP_MIN_ACTIONS = 3    # Minimum d'actions pour garder le rôle

@tasks.loop(hours=6)
async def check_on_top():
    """Donne le rôle 'On Top' au staff le plus actif sur les tickets — retire si inactif."""
    now = int(time.time())
    cutoff = now - (ON_TOP_WINDOW_DAYS * 86400)

    for guild in bot.guilds:
        gid = str(guild.id)
        on_top_role = discord.utils.get(guild.roles, name=ON_TOP_ROLE_NAME)
        if not on_top_role:
            continue

        stats = ticket_stats_db.get(gid, {})
        # Calculer le score de chaque membre (claims + closes) dans la fenêtre
        scores = {}
        for uid, data in stats.items():
            if data.get("last_activity", 0) >= cutoff:
                scores[uid] = data.get("claims", 0) + data.get("closes", 0)

        # Retirer le rôle à tous ceux qui l'ont mais ne méritent plus
        for member in on_top_role.members:
            uid = str(member.id)
            score = scores.get(uid, 0)
            if score < ON_TOP_MIN_ACTIONS:
                try:
                    await member.remove_roles(on_top_role, reason="🏆 On Top retiré — activité ticket insuffisante")
                except Exception:
                    pass

        if not scores:
            continue

        # Trouver le meilleur
        best_uid = max(scores, key=lambda u: scores[u])
        best_score = scores[best_uid]
        if best_score < ON_TOP_MIN_ACTIONS:
            continue

        best_member = guild.get_member(int(best_uid))
        if not best_member:
            continue

        # Donner le rôle si pas déjà attribué
        if on_top_role not in best_member.roles:
            try:
                await best_member.add_roles(on_top_role, reason=f"🏆 On Top — {best_score} actions tickets")
            except Exception:
                pass

@bot.listen("on_ready")
async def start_on_top_checker():
    if not check_on_top.is_running():
        check_on_top.start()

async def log_ticket(guild, embed):
    ch_id = get_cfg(guild.id, "ticket_log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if not ch:
            try: ch = await guild.fetch_channel(int(ch_id))
            except: return
        if ch: await ch.send(embed=embed)

def get_ticket_overwrites(guild, author, ticket_type: str):
    """
    Construit les permissions du salon selon le type de ticket.
    - Personne ne voit par défaut
    - L'auteur voit
    - Le rôle concerné voit
    - C.O.D voit TOUT
    - Partenariat : visible uniquement par C.O.D (pas de rôle Partenariat)
    """
    cod_role = guild.get_role(ROLE_COD_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        author: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_permissions=True),
    }

    # C.O.D voit tout
    if cod_role:
        overwrites[cod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

    # Ajouter le rôle spécifique (sauf partenariat qui est géré uniquement par C.O.D)
    if ticket_type != "partenariat":
        cfg = TICKET_TYPES[ticket_type]
        _rid = cfg.get("role_id")
        role = guild.get_role(_rid) if _rid else discord.utils.get(guild.roles, name=cfg["role"])
        if role and role != cod_role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

    return overwrites

# ─── CONFIG TICKETS ───────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def setticketcategory(ctx, *, arg: str):
    arg = arg.strip()
    cat = None
    if arg.isdigit(): cat = ctx.guild.get_channel(int(arg))
    if not cat:
        cat = discord.utils.find(
            lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == arg.lower(),
            ctx.guild.categories)
    if not cat: return await ctx.send("❌ Catégorie introuvable. Tape le nom exact.")
    set_cfg(ctx.guild.id, "ticket_category", cat.id)
    await ctx.send(f"✅ Catégorie tickets → **{cat.name}**")

@bot.command()
@commands.has_permissions(administrator=True)
async def setticketlog(ctx, *, arg: str):
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "ticket_log_channel", channel.id)
    await ctx.send(f"✅ Logs tickets → {channel.mention}")

def _build_ticket_panel_embed(guild):
    """Construit l'embed du panel ticket (réutilisable)"""
    e = discord.Embed(
        title="🌸  Kozakura — Support & Contact",
        description=(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**Bienvenue au support officiel de Kozakura.**\n"
            "Notre équipe est disponible **24h/24 · 7j/7** pour vous aider.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**⚒️  Gestion Staff**\n"
            "` ` Candidatures, rank-up, récupération de rôles.\n\n"
            "**🛡️  Gestion Abus**\n"
            "` ` Signaler un abus, conflit ou contester une sanction.\n\n"
            "**👑  Direction**\n"
            "` ` Décalages, fusions, sujets stratégiques — C.O.D uniquement.\n\n"
            "**🤝  Partenariat**\n"
            "` ` Proposer un partenariat avec Kozakura.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ *Les demandes hors-sujet ou abusives seront ignorées.*"
        ),
        color=discord.Color.from_rgb(255, 182, 193)
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.set_footer(text="Kozakura Support  •  Cliquez sur un bouton ci-dessous")
    return e

@bot.command()
@commands.has_permissions(administrator=True)
async def ticketpanel(ctx):
    """Envoie le panel de tickets avec les 4 boutons"""
    e = _build_ticket_panel_embed(ctx.guild)
    msg = await ctx.send(embed=e, view=TicketPanelView())
    # Mémoriser l'ID du message et du salon pour auto-restore au redémarrage
    set_cfg(ctx.guild.id, "ticket_panel_channel", ctx.channel.id)
    set_cfg(ctx.guild.id, "ticket_panel_message", msg.id)
    try: await ctx.message.delete()
    except Exception: pass

# ─── VIEW PRINCIPALE DU PANEL ─────────────────────────────────────────────────
class TicketPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Gestion Staff", emoji="⚒️", style=discord.ButtonStyle.blurple, custom_id="ticket_staff", row=0)
    async def btn_staff(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(TicketOpenModal("staff"))

    @discord.ui.button(label="Gestion Abus", emoji="🛡️", style=discord.ButtonStyle.red, custom_id="ticket_abus", row=0)
    async def btn_abus(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(TicketOpenModal("abus"))

    @discord.ui.button(label="Direction", emoji="👑", style=discord.ButtonStyle.grey, custom_id="ticket_cod", row=1)
    async def btn_cod(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(TicketOpenModal("cod"))

    @discord.ui.button(label="Partenariat", emoji="🤝", style=discord.ButtonStyle.green, custom_id="ticket_partenariat", row=1)
    async def btn_partenariat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(TicketOpenModal("partenariat"))

# ─── MODAL D'OUVERTURE DE TICKET ─────────────────────────────────────────────
class TicketOpenModal(discord.ui.Modal):
    subject = discord.ui.TextInput(
        label="Sujet",
        placeholder="Résumé en une ligne de ta demande...",
        style=discord.TextStyle.short,
        required=True, max_length=100)
    details = discord.ui.TextInput(
        label="Détails (optionnel)",
        placeholder="Décris ta situation en détail...",
        style=discord.TextStyle.paragraph,
        required=False, max_length=1000)

    def __init__(self, ticket_type: str):
        cfg = TICKET_TYPES[ticket_type]
        super().__init__(title=f"{cfg['emoji']} Ouvrir — {cfg['label']}")
        self.ticket_type = ticket_type

    async def on_submit(self, interaction: discord.Interaction):
        await open_ticket(interaction, self.ticket_type,
                          subject=self.subject.value,
                          details=self.details.value or "")

# ─── FONCTION D'OUVERTURE DE TICKET ──────────────────────────────────────────
async def open_ticket(interaction: discord.Interaction, ticket_type: str, subject: str = "", details: str = ""):
    guild  = interaction.guild
    author = interaction.user
    gid    = str(guild.id)
    cfg    = TICKET_TYPES[ticket_type]

    # Vérifie si l'utilisateur a déjà un ticket ouvert du même type
    if gid in tickets_db:
        for tid, tdata in tickets_db[gid].items():
            if (str(tdata.get("author_id")) == str(author.id)
                    and tdata.get("status") == "open"
                    and tdata.get("type") == ticket_type):
                ch = guild.get_channel(int(tid))
                if ch:
                    return await interaction.response.send_message(
                        f"❌ Tu as déjà un ticket **{cfg['emoji']} {ticket_type}** ouvert : {ch.mention}",
                        ephemeral=True)

    cat_id   = get_cfg(guild.id, "ticket_category") or 1493632554006347898
    category = guild.get_channel(int(cat_id)) if cat_id else None

    ticket_number = len(tickets_db.get(gid, {})) + 1
    safe_name     = author.name[:15].lower().replace(" ", "-")
    channel_name  = f"ticket-{ticket_type}-{safe_name}-{ticket_number}"

    overwrites = get_ticket_overwrites(guild, author, ticket_type)

    ticket_channel = await guild.create_text_channel(
        channel_name, category=category, overwrites=overwrites,
        topic=f"Ticket {ticket_type} de {author.name} | #{ticket_number}")

    tickets_db.setdefault(gid, {})[str(ticket_channel.id)] = {
        "author_id":   author.id,
        "author_name": author.name,
        "number":      ticket_number,
        "type":        ticket_type,
        "subject":     subject,
        "status":      "open",
        "claimed_by":  None,
        "opened_at":   str(datetime.utcnow()),
        "priority":    "normale",
    }
    save_json("tickets.json", tickets_db)

    # Mention du rôle concerné
    role_id      = cfg.get("role_id")
    role         = guild.get_role(role_id) if role_id else discord.utils.get(guild.roles, name=cfg["role"])
    role_mention = role.mention if role else f"@{cfg['role']}"

    # Embed de bienvenue
    e = discord.Embed(
        title=f"{cfg['emoji']}  Ticket #{ticket_number} — {cfg['label']}",
        color=cfg["color"],
        timestamp=datetime.utcnow()
    )
    e.add_field(name="👤 Membre", value=author.mention, inline=True)
    e.add_field(name="🏷️ Type",   value=cfg["label"],   inline=True)
    e.add_field(name="🔢 Numéro", value=f"#{ticket_number}", inline=True)
    if subject:
        e.add_field(name="📌 Sujet",    value=subject[:1024],  inline=False)
    if details:
        e.add_field(name="📝 Détails",  value=details[:1024],  inline=False)
    rules_staff = f"› Notre équipe {role_mention} te répond dès que possible."
    rules_part  = "› Ce ticket est réservé à **B#tch** (Direction)."
    e.add_field(
        name="📋 Règles du ticket",
        value=(
            "› Sois précis et respectueux.\n"
            "› Ne ping pas inutilement le staff.\n"
            "› Le ticket sera fermé si inactif.\n"
            f"{rules_part if ticket_type == 'partenariat' else rules_staff}"
        ),
        inline=False
    )
    e.set_thumbnail(url=author.display_avatar.url)
    e.set_footer(text=f"Kozakura Support  •  {author.name}", icon_url=author.display_avatar.url)

    await ticket_channel.send(
        content=f"{author.mention} {role_mention}",
        embed=e,
        view=TicketControlView()
    )

    await interaction.response.send_message(
        f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True)

    le = discord.Embed(
        title=f"🎫 Ticket Ouvert — {cfg['label']}",
        description=f"Par {author.mention} → {ticket_channel.mention}",
        color=cfg["color"], timestamp=datetime.utcnow())
    le.add_field(name="Ticket", value=f"#{ticket_number}")
    le.add_field(name="Type",   value=cfg["label"])
    le.add_field(name="Membre", value=f"{author} ({author.id})")
    if subject:
        le.add_field(name="Sujet", value=subject[:256], inline=False)
    await log_ticket(guild, le)

# ─── VIEW CONTRÔLES DU TICKET ─────────────────────────────────────────────────
TICKET_PRIORITY_LABEL = {
    "urgent":  "🔴 URGENT",
    "haute":   "🟠 Haute",
    "normale": "🔵 Normale",
    "basse":   "🟢 Basse",
}

class PrioritySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Priorité Urgente",  value="urgent",  emoji="🔴", description="Nécessite une attention immédiate"),
            discord.SelectOption(label="Priorité Haute",    value="haute",   emoji="🟠", description="À traiter rapidement"),
            discord.SelectOption(label="Priorité Normale",  value="normale", emoji="🔵", description="Flux standard"),
            discord.SelectOption(label="Priorité Basse",    value="basse",   emoji="🟢", description="Pas urgent"),
        ]
        super().__init__(placeholder="🏷️ Définir la priorité...", options=options,
                         custom_id="tc_priority", row=1, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        niveau = self.values[0]
        gid = str(interaction.guild_id); tid = str(interaction.channel_id)
        if gid not in tickets_db or tid not in tickets_db[gid]:
            return await interaction.response.send_message("❌ Pas un ticket.", ephemeral=True)
        tickets_db[gid][tid]["priority"] = niveau
        save_json("tickets.json", tickets_db)
        color = TICKET_PRIORITY_COLORS[niveau]
        label = TICKET_PRIORITY_LABEL[niveau]
        ch_name = interaction.channel.name
        for p in ("urgent-", "haute-", "normale-", "basse-"):
            if ch_name.startswith(p):
                ch_name = ch_name[len(p):]
                break
        try:
            await interaction.channel.edit(name=f"{niveau}-{ch_name}")
        except Exception:
            pass
        e = discord.Embed(
            title=f"{label}  •  Priorité mise à jour",
            description=f"Ce ticket est maintenant en priorité **{label}**.",
            color=color, timestamp=datetime.utcnow()
        )
        e.set_footer(text=f"Modifié par {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PrioritySelect())

    @discord.ui.button(label="Fermer", emoji="🔒", style=discord.ButtonStyle.red, custom_id="tc_close", row=0)
    async def close_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(CloseTicketModal())

    @discord.ui.button(label="Claim", emoji="✋", style=discord.ButtonStyle.green, custom_id="tc_claim", row=0)
    async def claim_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        gid = str(interaction.guild_id); tid = str(interaction.channel_id)
        data = tickets_db.get(gid, {}).get(tid)
        if not data: return await interaction.response.send_message("❌ Pas un ticket.", ephemeral=True)
        # Toggle: si déjà claim par soi-même → unclaim
        if data.get("claimed_by") and str(data["claimed_by"]) == str(interaction.user.id):
            tickets_db[gid][tid]["claimed_by"] = None
            save_json("tickets.json", tickets_db)
            e = discord.Embed(title="✋ Ticket Unclaim",
                description=f"{interaction.user.mention} a retiré sa prise en charge.",
                color=discord.Color.orange(), timestamp=datetime.utcnow())
            await interaction.response.send_message(embed=e)
        elif data.get("claimed_by"):
            claimer = interaction.guild.get_member(int(data["claimed_by"]))
            return await interaction.response.send_message(
                f"❌ Ce ticket est déjà claim par {claimer.mention if claimer else 'quelqu\'un'}.", ephemeral=True)
        else:
            tickets_db[gid][tid]["claimed_by"] = interaction.user.id
            save_json("tickets.json", tickets_db)
            # Tracker les stats pour le rôle On Top
            _track_ticket_stat(gid, str(interaction.user.id), "claims")
            e = discord.Embed(title="✋ Ticket Claim",
                description=f"{interaction.user.mention} a pris en charge ce ticket.",
                color=discord.Color.green(), timestamp=datetime.utcnow())
            await interaction.response.send_message(embed=e)
            le = discord.Embed(title="✋ Ticket Claim",
                description=f"Ticket #{data['number']} claim par {interaction.user.mention}",
                color=discord.Color.green(), timestamp=datetime.utcnow())
            await log_ticket(interaction.guild, le)

    @discord.ui.button(label="Infos", emoji="📋", style=discord.ButtonStyle.grey, custom_id="tc_info", row=0)
    async def info_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        gid = str(interaction.guild_id); tid = str(interaction.channel_id)
        data = tickets_db.get(gid, {}).get(tid)
        if not data: return await interaction.response.send_message("❌ Données introuvables.", ephemeral=True)
        claimer = "Non claim"
        if data.get("claimed_by"):
            m = interaction.guild.get_member(int(data["claimed_by"]))
            claimer = m.mention if m else "Inconnu"
        cfg = TICKET_TYPES.get(data.get("type", ""), {})
        priority = TICKET_PRIORITY_LABEL.get(data.get("priority", "normale"), "🔵 Normale")
        e = discord.Embed(
            title=f"📋  Ticket #{data['number']} — Infos",
            color=cfg.get("color", discord.Color.blurple()),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="👤 Auteur",    value=data["author_name"],  inline=True)
        e.add_field(name="🏷️ Type",      value=data.get("type","?").capitalize(), inline=True)
        e.add_field(name="🔢 Numéro",    value=f"#{data['number']}", inline=True)
        e.add_field(name="📊 Statut",    value="🟢 Ouvert" if data["status"] == "open" else "🔴 Fermé", inline=True)
        e.add_field(name="✋ Claim",     value=claimer, inline=True)
        e.add_field(name="🏷️ Priorité",  value=priority, inline=True)
        if data.get("subject"):
            e.add_field(name="📌 Sujet", value=data["subject"][:256], inline=False)
        e.add_field(name="⏰ Ouvert le", value=data["opened_at"][:16], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

# ─── MODAL FERMETURE ──────────────────────────────────────────────────────────
class CloseTicketModal(discord.ui.Modal, title="🔒 Fermer le ticket"):
    reason = discord.ui.TextInput(
        label="Raison de fermeture",
        placeholder="Ex: Problème résolu, demande traitée...",
        style=discord.TextStyle.short,
        required=False, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild; channel = interaction.channel
        gid = str(guild.id); tid = str(channel.id)
        data = tickets_db.get(gid, {}).get(tid)
        if not data:
            return await interaction.response.send_message("❌ Pas un ticket valide.", ephemeral=True)

        reason_text = self.reason.value or "Aucune raison spécifiée"
        author = guild.get_member(int(data["author_id"])) if data.get("author_id") else None
        cfg = TICKET_TYPES.get(data.get("type", ""), {})

        tickets_db[gid][tid]["status"]       = "closed"
        tickets_db[gid][tid]["closed_by"]    = str(interaction.user.id)
        tickets_db[gid][tid]["closed_at"]    = str(datetime.utcnow())
        tickets_db[gid][tid]["close_reason"] = reason_text
        save_json("tickets.json", tickets_db)
        # Tracker les stats pour le rôle On Top
        _track_ticket_stat(gid, str(interaction.user.id), "closes")

        e = discord.Embed(
            title="🔒  Ticket Fermé",
            description=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Fermé par** {interaction.user.mention}\n"
                f"**Raison :** {reason_text}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(237, 66, 69),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="🎫 Ticket", value=f"#{data['number']}", inline=True)
        e.add_field(name="🏷️ Type",   value=data.get("type","?").capitalize(), inline=True)
        e.add_field(name="👤 Auteur", value=data["author_name"], inline=True)
        e.set_footer(text="Suppression dans 10 secondes…")
        await interaction.response.send_message(embed=e)

        if author:
            dm_e = discord.Embed(
                title="🌸  Ton ticket a été fermé",
                description=(
                    f"**Serveur :** {guild.name}\n"
                    f"**Ticket :** #{data['number']} — {data.get('type','?').capitalize()}\n"
                    f"**Fermé par :** {interaction.user}\n"
                    f"**Raison :** {reason_text}\n\n"
                    "Merci d'avoir contacté le support Kozakura 💌"
                ),
                color=discord.Color.from_rgb(255, 182, 193),
                timestamp=datetime.utcnow()
            )
            dm_e.set_footer(text="Kozakura Support")
            try:
                await author.send(embed=dm_e)
            except Exception:
                pass

        le = discord.Embed(title="🔒 Ticket Fermé",
            description=f"Fermé par {interaction.user.mention}",
            color=discord.Color.red(), timestamp=datetime.utcnow())
        le.add_field(name="Ticket", value=f"#{data['number']}")
        le.add_field(name="Type",   value=data.get("type","?").capitalize())
        le.add_field(name="Auteur", value=data["author_name"])
        le.add_field(name="Raison", value=reason_text, inline=False)
        await log_ticket(guild, le)

        await asyncio.sleep(10)
        try:
            await _save_ticket_transcript(guild, channel, data)
            await ai_summarize_ticket(guild, channel, data)
            await channel.delete()
        except Exception: pass

@bot.command(name="setpriority")
@staff_only()
async def setpriority(ctx, niveau: str = None):
    """!setpriority [urgent/haute/normale/basse] — Définit la priorité du ticket"""
    gid = str(ctx.guild.id); tid = str(ctx.channel.id)
    if gid not in tickets_db or tid not in tickets_db[gid]:
        return await ctx.send("❌ Cette commande s'utilise dans un salon de ticket.", delete_after=5)
    if niveau not in TICKET_PRIORITY_COLORS:
        return await ctx.send(f"❌ Niveaux valides : `urgent` / `haute` / `normale` / `basse`", delete_after=5)
    tickets_db[gid][tid]["priority"] = niveau
    save_json("tickets.json", tickets_db)
    emoji = TICKET_PRIORITY_EMOJI[niveau]
    color = TICKET_PRIORITY_COLORS[niveau]
    e = discord.Embed(
        title=f"{emoji} Priorité mise à jour",
        description=f"Ce ticket est maintenant en priorité **{niveau.upper()}**",
        color=color, timestamp=datetime.utcnow()
    )
    await ctx.send(embed=e)
    await ctx.channel.edit(name=f"{niveau}-{ctx.channel.name.split('-', 1)[-1] if '-' in ctx.channel.name else ctx.channel.name}")

@bot.command(name="reopen")
@staff_only()
async def reopen_ticket(ctx):
    """!reopen — Rouvre un ticket fermé"""
    gid = str(ctx.guild.id); tid = str(ctx.channel.id)
    if gid not in tickets_db or tid not in tickets_db[gid]:
        return await ctx.send("❌ Cette commande s'utilise dans un salon de ticket.", delete_after=5)
    data = tickets_db[gid][tid]
    if data.get("status") == "open":
        return await ctx.send("❌ Ce ticket est déjà ouvert.", delete_after=5)
    tickets_db[gid][tid]["status"] = "open"
    tickets_db[gid][tid].pop("closed_by", None)
    tickets_db[gid][tid].pop("closed_at", None)
    tickets_db[gid][tid].pop("close_reason", None)
    save_json("tickets.json", tickets_db)
    e = discord.Embed(
        title="🔓 Ticket Rouvert",
        description=f"Ticket #{data['number']} rouvert par {ctx.author.mention}",
        color=discord.Color.green(), timestamp=datetime.utcnow()
    )
    await ctx.send(embed=e, view=TicketControlView())
    await log_ticket(ctx.guild, e)

@bot.command()
@staff_only()
async def claim(ctx):
    """!claim — Prend en charge le ticket actuel"""
    gid = str(ctx.guild.id); tid = str(ctx.channel.id)
    if gid not in tickets_db or tid not in tickets_db[gid]:
        return await ctx.send("❌ Cette commande s'utilise dans un salon de ticket.")

    data = tickets_db[gid][tid]
    if data.get("claimed_by"):
        claimer = ctx.guild.get_member(int(data["claimed_by"]))
        return await ctx.send(f"❌ Ce ticket est déjà claim par {claimer.mention if claimer else 'quelqu\'un'}.")

    tickets_db[gid][tid]["claimed_by"] = ctx.author.id
    save_json("tickets.json", tickets_db)

    e = discord.Embed(title="✋ Ticket Claim",
        description=f"{ctx.author.mention} a pris en charge ce ticket.",
        color=discord.Color.green(), timestamp=datetime.utcnow())
    await ctx.send(embed=e)

    le = discord.Embed(title="✋ Ticket Claim",
        description=f"Ticket #{data['number']} claim par {ctx.author.mention}",
        color=discord.Color.green(), timestamp=datetime.utcnow())
    await log_ticket(ctx.guild, le)

@bot.command(name="add")
@staff_only()
async def ticket_add(ctx, member: discord.Member):
    """!add @membre — Ajoute un membre au ticket actuel"""
    gid = str(ctx.guild.id); tid = str(ctx.channel.id)
    if gid not in tickets_db or tid not in tickets_db[gid]:
        return await ctx.send("❌ Cette commande s'utilise dans un salon de ticket.")

    await ctx.channel.set_permissions(member,
        read_messages=True, send_messages=True, attach_files=True)

    e = discord.Embed(title="➕ Membre Ajouté",
        description=f"{member.mention} a été ajouté au ticket par {ctx.author.mention}",
        color=discord.Color.green(), timestamp=datetime.utcnow())
    await ctx.send(embed=e)

    await dm(member, "🎫 Ajouté à un ticket",
        f"**Serveur :** {ctx.guild.name}\nTu as été ajouté au ticket par {ctx.author}.\nSalon : {ctx.channel.mention}",
        color=discord.Color.blurple())

    le = discord.Embed(title="➕ Membre Ajouté au Ticket",
        description=f"{member.mention} ajouté par {ctx.author.mention}",
        color=discord.Color.green(), timestamp=datetime.utcnow())
    le.add_field(name="Ticket", value=f"#{tickets_db[gid][tid]['number']}")
    await log_ticket(ctx.guild, le)

@bot.command(name="remove")
@staff_only()
async def ticket_remove(ctx, member: discord.Member):
    """!remove @membre — Retire un membre du ticket actuel"""
    gid = str(ctx.guild.id); tid = str(ctx.channel.id)
    if gid not in tickets_db or tid not in tickets_db[gid]:
        return await ctx.send("❌ Cette commande s'utilise dans un salon de ticket.")

    # Empêche de retirer l'auteur du ticket
    data = tickets_db[gid][tid]
    if member.id == int(data["author_id"]):
        return await ctx.send("❌ Tu ne peux pas retirer l'auteur du ticket.")

    await ctx.channel.set_permissions(member, overwrite=None)

    e = discord.Embed(title="➖ Membre Retiré",
        description=f"{member.mention} a été retiré du ticket par {ctx.author.mention}",
        color=discord.Color.orange(), timestamp=datetime.utcnow())
    await ctx.send(embed=e)

    await dm(member, "🎫 Retiré d'un ticket",
        f"**Serveur :** {ctx.guild.name}\nTu as été retiré du ticket par {ctx.author}.",
        color=discord.Color.orange())

    le = discord.Embed(title="➖ Membre Retiré du Ticket",
        description=f"{member.mention} retiré par {ctx.author.mention}",
        color=discord.Color.orange(), timestamp=datetime.utcnow())
    le.add_field(name="Ticket", value=f"#{data['number']}")
    await log_ticket(ctx.guild, le)

@bot.command(name="tickets")
@staff_only()
async def list_tickets(ctx):
    """!tickets — Liste tous les tickets ouverts"""
    gid = str(ctx.guild.id)
    data = tickets_db.get(gid, {})
    open_tickets = [(tid, t) for tid, t in data.items() if t.get("status") == "open"]

    e = discord.Embed(
        title=f"🎫  Tickets Ouverts — {len(open_tickets)} actif(s)",
        color=discord.Color.from_rgb(255, 182, 193),
        timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Kozakura Support  •  {ctx.guild.name}")

    if not open_tickets:
        e.description = "✅ Aucun ticket ouvert en ce moment."
    else:
        for tid, t in open_tickets[:15]:
            ch = ctx.guild.get_channel(int(tid))
            claim_val = "—"
            if t.get("claimed_by"):
                m = ctx.guild.get_member(int(t["claimed_by"]))
                claim_val = f"✋ {m.name if m else 'Inconnu'}"
            priority = TICKET_PRIORITY_LABEL.get(t.get("priority", "normale"), "🔵 Normale")
            subject_line = f"\n📌 {t['subject'][:60]}" if t.get("subject") else ""
            e.add_field(
                name=f"{TICKET_PRIORITY_EMOJI.get(t.get('priority','normale'),'🔵')} #{t['number']} · {t.get('type','?').upper()} — {t['author_name']}",
                value=f"{ch.mention if ch else '`Supprimé`'}  ·  {claim_val}{subject_line}",
                inline=False)
    await ctx.send(embed=e)

# ─── PANEL ADMIN ──────────────────────────────────────────────────────────────
class AdminPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=180)

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.blurple)
    async def btn_stats(self, i: discord.Interaction, _: discord.ui.Button):
        g = i.guild
        bots = sum(1 for m in g.members if m.bot)
        online = sum(1 for m in g.members if m.status != discord.Status.offline and not m.bot)
        vocal = sum(len(vc.members) for vc in g.voice_channels)
        e = discord.Embed(title="📊 Stats", color=discord.Color.blurple())
        e.add_field(name="👥 Membres", value=g.member_count - bots)
        e.add_field(name="🟢 En ligne", value=online)
        e.add_field(name="🎙️ Vocal", value=vocal)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="⚠️ Top Warns", style=discord.ButtonStyle.red)
    async def btn_warns(self, i: discord.Interaction, _: discord.ui.Button):
        gid = str(i.guild.id); data = warnings_db.get(gid, {})
        top = sorted(data.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        e = discord.Embed(title="⚠️ Top Avertissements", color=discord.Color.orange())
        for uid, ws in top:
            m = i.guild.get_member(int(uid))
            e.add_field(name=m.name if m else uid, value=f"{len(ws)} warn(s)", inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="🏆 Top XP", style=discord.ButtonStyle.green)
    async def btn_xp(self, i: discord.Interaction, _: discord.ui.Button):
        gid = str(i.guild.id)
        top = sorted(xp_db.get(gid, {}).items(), key=lambda x: x[1], reverse=True)[:5]
        e = discord.Embed(title="🏆 Top 5 XP", color=discord.Color.gold())
        for idx, (uid, xp) in enumerate(top, 1):
            m = i.guild.get_member(int(uid))
            e.add_field(name=f"#{idx} {m.name if m else uid}",
                value=f"Niv.{get_level(xp)} | {xp} XP", inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="🎫 Tickets", style=discord.ButtonStyle.grey)
    async def btn_tickets(self, i: discord.Interaction, _: discord.ui.Button):
        gid = str(i.guild.id); data = tickets_db.get(gid, {})
        open_t = [(tid, t) for tid, t in data.items() if t.get("status") == "open"]
        e = discord.Embed(title=f"🎫 Tickets Ouverts ({len(open_t)})", color=discord.Color.blurple())
        if not open_t: e.description = "Aucun ticket ouvert ✅"
        else:
            for tid, t in open_t[:10]:
                ch = i.guild.get_channel(int(tid))
                e.add_field(name=f"#{t['number']} [{t.get('type','?').upper()}] — {t['author_name']}",
                    value=ch.mention if ch else "Supprimé", inline=True)
        await i.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="⚙️ Config", style=discord.ButtonStyle.grey)
    async def btn_config(self, i: discord.Interaction, _: discord.ui.Button):
        gid = str(i.guild.id); cfg = config_db.get(gid, {})
        e = discord.Embed(title="⚙️ Config actuelle", color=discord.Color.greyple())
        for k, v in cfg.items():
            ch = i.guild.get_channel(int(v)) if isinstance(v, int) else None
            e.add_field(name=k, value=ch.mention if ch else str(v), inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def panel(ctx):
    e = discord.Embed(title="🛠️ Panel Admin", color=discord.Color.blurple(),
        description="Gère ton serveur facilement avec les boutons ci-dessous.")
    await ctx.send(embed=e, view=AdminPanel())

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────
@bot.tree.command(name="rank", description="Affiche ton niveau XP")
async def sl_rank(i: discord.Interaction, member: discord.Member = None):
    member = member or i.user
    xp = xp_db.get(str(i.guild_id), {}).get(str(member.id), 0); lvl = get_level(xp)
    e = discord.Embed(title=f"🏆 {member.name}", color=discord.Color.gold())
    e.add_field(name="Niveau", value=lvl); e.add_field(name="XP", value=f"{xp} / {xp_for_level(lvl+1)}")
    e.set_thumbnail(url=member.display_avatar.url)
    await i.response.send_message(embed=e)

@bot.tree.command(name="stats", description="Statistiques du serveur")
async def sl_stats(i: discord.Interaction):
    g = i.guild
    bots = sum(1 for m in g.members if m.bot)
    online = sum(1 for m in g.members if m.status != discord.Status.offline and not m.bot)
    vocal = sum(len(vc.members) for vc in g.voice_channels)
    e = discord.Embed(title=f"📊 {g.name}", color=discord.Color.blurple())
    e.add_field(name="👥 Membres", value=g.member_count - bots)
    e.add_field(name="🟢 En ligne", value=online)
    e.add_field(name="🎙️ En vocal", value=vocal)
    await i.response.send_message(embed=e)

@bot.tree.command(name="warn", description="Avertir un membre")
@app_commands.describe(member="Le membre", reason="La raison")
@app_commands.checks.has_permissions(kick_members=True)
async def sl_warn(i: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    gid = str(i.guild_id); uid = str(member.id)
    warnings_db.setdefault(gid, {}).setdefault(uid, []).append(
        {"reason": reason, "by": str(i.user.id), "date": str(datetime.utcnow())})
    save_json("warnings.json", warnings_db)
    count = len(warnings_db[gid][uid])
    e = discord.Embed(title="⚠️ Avertissement",
        description=f"{member.mention} averti ({count} total)", color=discord.Color.yellow())
    e.add_field(name="Raison", value=reason)
    await i.response.send_message(embed=e)
    await dm(member, f"⚠️ Avertissement ({count})",
        f"**Serveur :** {i.guild.name}\n**Raison :** {reason}")

@bot.tree.command(name="panel", description="Panel d'administration")
@app_commands.checks.has_permissions(administrator=True)
async def sl_panel(i: discord.Interaction):
    e = discord.Embed(title="🛠️ Panel Admin", color=discord.Color.blurple())
    await i.response.send_message(embed=e, view=AdminPanel(), ephemeral=True)

# ─── AIDE ─────────────────────────────────────────────────────────────────────
ROLES_HELP = ("B#tch", "Univers", "Queen", "Baby admin", "Développer",
              "[+] Kozakura gestion", "Gestion", "Support")

@bot.command()
async def help(ctx, categorie: str = None):
    """!help [catégorie] — Affiche l'aide complète ou d'une catégorie (staff uniquement)"""
    if not has_sanction_role(ctx.author, ROLES_HELP):
        return await ctx.message.delete() if ctx.guild else None

    categories = {
        "mod":        "🔨 Modération",
        "sanctions":  "📋 Sanctions",
        "roles":      "🎭 Rôles",
        "rank":       "🎖️ Rank/Derank",
        "tickets":    "🎫 Tickets",
        "tribunal":   "⚖️ Tribunal",
        "xp":         "🏆 XP / Niveaux",
        "trophees":   "🏅 Trophées",
        "communaute": "💬 Communauté",
        "texte":      "📝 Texte",
        "massban":    "💥 Mass Ban",
        "admin":      "⚙️ Admin",
        "slash":      "⚡ Slash",
        "ia":         "🤖 Intelligence Artificielle",
        "stats":      "📊 Stats & Rapports",
        "securite":   "🔒 Sécurité Avancée",
        "vocal":      "🎙️ Vocal Temporaire",
    }

    if categorie and categorie.lower() in categories:
        cat = categorie.lower()
        e = discord.Embed(color=discord.Color.blurple(), timestamp=datetime.utcnow())
        e.set_footer(text=f"!help pour revenir au menu • Préfixe : {PREFIX}")

        if cat == "mod":
            e.title = "🔨 Modération"
            e.add_field(name="!ban @membre [raison]",    value="Bannit un membre (MP envoyé avant)", inline=False)
            e.add_field(name="!unban [id] [raison]",     value="Débannit un utilisateur par ID", inline=False)
            e.add_field(name="!kick @membre [raison]",   value="Expulse un membre", inline=False)
            e.add_field(name="!mute @membre [min] [raison]", value="Mute un membre (défaut 10 min)", inline=False)
            e.add_field(name="!unmute @membre",          value="Démute un membre", inline=False)
            e.add_field(name="!warn @membre [raison]",   value="Avertit un membre", inline=False)
            e.add_field(name="!warnings [@membre]",      value="Voir les avertissements", inline=False)
            e.add_field(name="!clearwarns @membre",      value="Réinitialise les avertissements", inline=False)
            e.add_field(name="!purge [n]",               value="Supprime N messages (max 100)", inline=False)
            e.add_field(name="!clear [n] ou !clear @membre [n]", value="Supprime N messages ou ceux d'un membre", inline=False)
            e.add_field(name="!slowmode [secondes]",     value="Active/désactive le slowmode", inline=False)

        elif cat == "sanctions":
            e.title = "📋 Sanctions"
            e.add_field(name="!infosanction @membre",    value="Voir toutes les sanctions d'un membre (ban, kick, mute, warn)", inline=False)
            e.add_field(name="!clearsanctions @membre",  value="Efface l'historique de sanctions (admin)", inline=False)
            e.description = "Toutes les sanctions sont automatiquement envoyées dans le salon **sanction** et dans les logs."

        elif cat == "roles":
            e.title = "🎭 Rôles"
            e.add_field(name="!addrole @membre @role",   value="Donne un rôle à un membre", inline=False)
            e.add_field(name="!delrole @membre @role",   value="Retire un rôle à un membre", inline=False)
            e.add_field(name="!reactionrole [emoji] @role [desc]", value="Crée un rôle par réaction", inline=False)
            e.add_field(name="!setautorole @role",       value="Rôle donné automatiquement à l'arrivée", inline=False)

        elif cat == "rank":
            e.title = "🎖️ Rank / Derank"
            e.description = (
                "Hiérarchie : `*** Mirai` → `** Taiyō` → `* Hoshi` → `III Shin` → `II Tsuki` → `I Kage`\n"
                "Chaque rang attribue automatiquement le grade **et** le titre."
            )
            e.add_field(name="!rankup @membre [raison]",       value="Monte le membre d'un rang ⬆️", inline=False)
            e.add_field(name="!derank @membre [raison]",       value="Descend le membre d'un rang ⬇️", inline=False)
            e.add_field(name="!setrank @membre [1-6] [raison]",value="Définit directement un rang (1=***, 6=I)", inline=False)
            e.add_field(name="!removerank @membre [raison]",   value="Retire tous les rangs", inline=False)
            e.add_field(name="!ranglist",                      value="Affiche la hiérarchie des rangs", inline=False)

        elif cat == "tickets":
            e.title = "🎫 Tickets"
            e.description = "4 types : **Gestion** | **Support** | **B#tch** | **Partenariat**"
            e.add_field(name="!ticketpanel",                   value="Envoie le panel avec les 4 boutons", inline=False)
            e.add_field(name="!tickets",                       value="Liste tous les tickets ouverts", inline=False)
            e.add_field(name="!claim",                         value="Prendre en charge le ticket actuel ✋", inline=False)
            e.add_field(name="!add @membre",                   value="Ajouter un membre au ticket", inline=False)
            e.add_field(name="!remove @membre",                value="Retirer un membre du ticket", inline=False)
            e.add_field(name="!closeticket [raison]",          value="Fermer le ticket actuel", inline=False)
            e.add_field(name="!setpriority [urgent/haute/normale/basse]", value="Définir la priorité du ticket", inline=False)
            e.add_field(name="!reopen",                        value="Rouvrir un ticket fermé", inline=False)
            e.add_field(name="!setticketcategory [nom]",       value="Définit la catégorie des tickets (admin)", inline=False)
            e.add_field(name="!setticketlog #salon",           value="Définit le salon de logs tickets (admin)", inline=False)

        elif cat == "tribunal":
            e.title = "⚖️ Tribunal"
            e.description = f"Nécessite le rôle **{ROLE_JUGE}** pour voter et ouvrir.\n**{VOTES_NECESSAIRES} votes** nécessaires pour valider."
            e.add_field(name="!tribunal @membre [ban/kick/mute] [motif]", value="Ouvre un vote tribunal dans #tribunal", inline=False)
            e.add_field(name="Bouton Pour ✅",   value="Vote pour la sanction", inline=False)
            e.add_field(name="Bouton Contre ❌", value="Vote contre la sanction", inline=False)
            e.add_field(name="Bouton Bannir 🔨", value="Exécute la sanction si assez de votes Pour", inline=False)

        elif cat == "xp":
            e.title = "🏆 XP / Niveaux"
            e.description = f"Chaque message rapporte **{XP_PER_MSG} XP** (cooldown {XP_COOLDOWN}s). Les passages de niveau s'affichent dans **⭐・niveaux**."
            e.add_field(name="!rank [@membre]",    value="Affiche le niveau et XP d'un membre", inline=False)
            e.add_field(name="!leaderboard",       value="Top 10 XP du serveur", inline=False)

        elif cat == "trophees":
            e.title = "🏅 Trophées"
            e.description = "Badges automatiques selon les votes, le temps vocal et les boosts."
            e.add_field(name="!trophe [@membre]",           value="Affiche le trophée d'un membre", inline=False)
            e.add_field(name="!topvotes",                   value="Classement par votes", inline=False)
            e.add_field(name="!topvocal",                   value="Classement par temps vocal", inline=False)
            e.add_field(name="!addvote @membre [n]",        value="Ajoute des votes (admin)", inline=False)
            e.add_field(name="!removevote @membre [n]",     value="Retire des votes (admin)", inline=False)
            e.add_field(name="!settrophees #salon",         value="Définit le salon des trophées (admin)", inline=False)
            e.add_field(name="🎖️ Badges Votes",
                value="🌱 Débutant → 📊 10 → 🥉 50 → 🥈 100 → 🥇 200 → 🏆 500", inline=False)
            e.add_field(name="🎖️ Badges Vocal",
                value="🔈 10h → 🎤 50h → 📢 100h → 🔊 200h → 🎙️ 500h", inline=False)

        elif cat == "communaute":
            e.title = "💬 Communauté"
            e.add_field(name="!suggest [texte]",              value="Envoie une suggestion", inline=False)
            e.add_field(name="!poll [question] [opt1] [opt2]", value="Crée un sondage (max 10 options)", inline=False)
            e.add_field(name="!stats",                        value="Statistiques du serveur", inline=False)
            e.add_field(name="!remind [n] [s/min/h/j] [msg]", value="Crée un rappel", inline=False)
            e.add_field(name="!rank [@membre]",               value="Ton niveau XP", inline=False)
            e.add_field(name="!leaderboard",                  value="Top 10 XP", inline=False)
            e.add_field(name="!ranglist",                     value="Hiérarchie des rangs", inline=False)

        elif cat == "texte":
            e.title = "📝 Texte & Embeds"
            e.add_field(name='!text [contenu]',
                value="Envoie un message permanent.\nSauts de ligne avec Shift+Entrée.", inline=False)
            e.add_field(name='!embed "Titre" [couleur] [contenu]',
                value="Envoie un embed coloré permanent.\nCouleurs : `rouge` `vert` `bleu` `or` `violet` `orange` `gris`", inline=False)

        elif cat == "massban":
            e.title = "💥 Mass Ban"
            e.add_field(name="!massban @u1 @u2 @u3 [raison]", value="Prépare un mass ban (confirmation requise)", inline=False)
            e.add_field(name="!massbanconfirm",                value="Exécute le mass ban préparé", inline=False)
            e.add_field(name="!massbancancel",                 value="Annule le mass ban en attente", inline=False)

        elif cat == "admin":
            e.title = "⚙️ Administration"
            e.add_field(name="!panel",                  value="Panel admin interactif", inline=False)
            e.add_field(name="!setlog #salon",          value="Salon de logs général", inline=False)
            e.add_field(name="!setwelcome #salon",      value="Salon de bienvenue", inline=False)
            e.add_field(name="!setwelcomemsg [msg]",    value="Message de bienvenue ({user} {server} {count})", inline=False)
            e.add_field(name="!setautorole @role",      value="Rôle automatique à l'arrivée", inline=False)
            e.add_field(name="!setsuggestions #salon",  value="Salon des suggestions", inline=False)
            e.add_field(name="!setraidthreshold [n]",   value="Seuil anti-raid (joins/10s)", inline=False)
            e.add_field(name="!setinvite [lien]",       value="Lien d'invitation du serveur", inline=False)
            e.add_field(name="!setupcounters",          value="Crée les salons compteurs", inline=False)
            e.add_field(name="!addcmd [trigger] [réponse]", value="Ajoute une commande personnalisée", inline=False)
            e.add_field(name="!delcmd [trigger]",       value="Supprime une commande personnalisée", inline=False)
            e.add_field(name="!addbanword [mot]",       value="Ajoute un mot à la liste noire", inline=False)

        elif cat == "slash":
            e.title = "⚡ Slash Commands"
            e.add_field(name="/rank [@membre]", value="Niveau XP", inline=False)
            e.add_field(name="/stats",          value="Stats du serveur", inline=False)
            e.add_field(name="/warn @membre",   value="Avertir un membre", inline=False)
            e.add_field(name="/panel",          value="Panel admin (éphémère)", inline=False)

        elif cat == "ia":
            e.title = "🤖 Intelligence Artificielle"
            e.description = "Powered by **Claude (Anthropic)** — Mentionne le bot ou écris dans `🧠・ia`"
            e.add_field(name="@Kozakura [message]",       value="Parle directement au bot n'importe où", inline=False)
            e.add_field(name="!ai [question]",            value="Pose une question à l'IA", inline=False)
            e.add_field(name="!mood",                     value="Analyse l'ambiance des 50 derniers messages du salon 🌸", inline=False)
            e.add_field(name="!roast [@membre]",          value="Roast drôle et bienveillant basé sur les vraies stats 🔥", inline=False)
            e.add_field(name="!conseil",                  value="Conseil de vie profond avec style japonais 🌸", inline=False)
            e.add_field(name="!histoire",                 value="Histoire courte avec des membres aléatoires du serveur 📜", inline=False)
            e.add_field(name="!imagine [description]",    value="Génère une description visuelle détaillée", inline=False)
            e.add_field(name="!traduis [langue] [texte]", value="Traduit dans n'importe quelle langue", inline=False)
            e.add_field(name="!moderia @membre [raison]", value="L'IA analyse et propose une sanction (staff)", inline=False)
            e.add_field(name="!announce [sujet]",         value="Génère une annonce avec confirmation (admin)", inline=False)
            e.add_field(name="!resume [nb]",              value="Résume les X derniers messages du salon", inline=False)
            e.add_field(name="!analyse @membre",          value="Analyse le comportement d'un membre", inline=False)
            e.add_field(name="!clearmemory",              value="Efface ta mémoire de conversation avec l'IA", inline=False)
            e.add_field(name="🧠 Mémoire pseudo",
                value="Dis *\"appelle-moi [prénom]\"* — le bot s'en souvient pour toujours !", inline=False)
            e.add_field(name="🛡️ Réponse NSFW",
                value="L'IA répond fermement aux demandes inappropriées en rappelant les règles", inline=False)
            e.add_field(name="🎭 Réponses adaptatives",
                value="• **Nouveau** (<7j) → accueillant\n• **Vétéran** (>180j) → familier\n• **Sanctionné** → neutre", inline=False)

        elif cat == "stats":
            e.title = "📊 Stats & Rapports"
            e.add_field(name="!activite [@membre]",
                value="Fiche complète : XP, niveau, vocal, sanctions, ancienneté, rôles", inline=False)
            e.add_field(name="!rapport",
                value="Génère le rapport hebdomadaire maintenant (admin)", inline=False)
            e.add_field(name="📅 Rapport automatique",
                value="Envoyé chaque **lundi à 9h** dans le salon staff\nContient : top XP, top vocal, sanctions de la semaine", inline=False)

        elif cat == "securite":
            e.title = "🔒 Sécurité Avancée"
            e.description = "Système de sécurité multicouche — Kozakura Security"
            e.add_field(name="🚨 Anti-Nuke",
                value="Détection auto si quelqu'un supprime salons/rôles/ban en masse → rôles dangereux retirés", inline=False)
            e.add_field(name="👤 Comptes suspects",
                value="Alerte automatique si un compte < 7 jours ou sans avatar rejoint", inline=False)
            e.add_field(name="🔔 Anti-mentions",
                value="Mute 30min auto si spam @mentions ou @everyone", inline=False)
            e.add_field(name="🎙️ Anti-spam vocal",
                value="Mute 10min si rejoindre/quitter le vocal 5x en 30s", inline=False)
            e.add_field(name="⚠️ Usurpation identité",
                value="Alerte si un membre change de pseudo pour ressembler au staff", inline=False)
            e.add_field(name="🤖 Détection menaces IA",
                value="Analyse contextuelle des messages suspects", inline=False)
            e.add_field(name="🧊 !freeze @membre",         value="Coupe toutes les permissions sans bannir", inline=False)
            e.add_field(name="🔓 !unfreeze @membre",       value="Restaure les permissions", inline=False)
            e.add_field(name="🔍 !whois @membre",          value="Enquête complète + score de risque", inline=False)
            e.add_field(name="🍯 !sethoneypot [#salon]",   value="Salon piège — alerte si quelqu'un y écrit", inline=False)
            e.add_field(name="💾 !backup",                 value="Sauvegarde la structure du serveur", inline=False)
            e.add_field(name="♻️ !restorebackup",          value="Restaure les salons/rôles depuis le backup", inline=False)
            e.add_field(name="🔒 !lockdown [raison]",      value="Verrouille tous les salons d'urgence", inline=False)
            e.add_field(name="🔓 !unlockdown",             value="Lève le lockdown", inline=False)
            e.add_field(name="🔬 !quarantaine @membre",    value="Accès très limité sans bannir", inline=False)
            e.add_field(name="✅ !unquarantaine @membre",  value="Libère de la quarantaine", inline=False)
            e.add_field(name="📊 !securitystatus",         value="Vue d'ensemble de la sécurité", inline=False)
            e.add_field(name="⚙️ !setminage [jours]",     value="Âge minimum des comptes", inline=False)
            e.add_field(name="📋 !setsecuritylog #salon",  value="Salon de logs sécurité dédié", inline=False)

        elif cat == "securite":
            e.title = "🔒 Sécurité Avancée"
            e.description = "Système de sécurité multicouche — Kozakura Security"
            e.add_field(name="🚨 Anti-Nuke",           value="Détection auto bans/suppressions massifs → rôles retirés", inline=False)
            e.add_field(name="👤 Comptes suspects",     value="Alerte si compte < 7j ou sans avatar à l'arrivée", inline=False)
            e.add_field(name="🔁 Anti-copypasta",       value="Mute 30min si même message dans 3 salons en 30s (staff ignoré)", inline=False)
            e.add_field(name="🔨 Retour de banni",      value="Détecte les nouveaux comptes similaires aux bannis (80%+) → freeze auto + alerte", inline=False)
            e.add_field(name="🔗 Anti-liens raccourcis",value="Warn auto (bit.ly, tinyurl, t.co…) — 2ème infraction = mute 1h", inline=False)
            e.add_field(name="💙 Détection détresse",   value="MP bienveillant IA + alerte discrète staff si mots de détresse détectés", inline=False)
            e.add_field(name="🌐 Traduction auto",      value="`!setautotrad on/off [#salon]` — Traduit les messages étrangers (≥5 mots)", inline=False)
            e.add_field(name="🔞 Anti-NSFW / Harcèlement",
                value="Suppression auto + sanctions progressives (warn→mute→kick→ban)\n"
                      "`!addnsfw` `!removensfw` `!listnsfw` (admin)", inline=False)
            e.add_field(name="📸 Anti-Screenshot",      value="Alerte staff si image dans salon confidentiel/staff/privé", inline=False)
            e.add_field(name="📊 !sanctions @membre",   value="Niveau de sanction progressif d'un membre", inline=False)
            e.add_field(name="⚖️ Sanctions progressives", value="1→rien | 2→mute 10min | 3→mute 1h | 4→kick | 5→ban", inline=False)
            e.add_field(name="🔒 !lockdown [raison]",   value="Verrouille tous les salons immédiatement", inline=False)
            e.add_field(name="🔓 !unlockdown",          value="Lève le lockdown", inline=False)
            e.add_field(name="🧊 !freeze @membre",      value="Coupe toutes les permissions sans bannir", inline=False)

        elif cat in ("economie", "économie", "eco"):
            e.title = "🌸 Économie — Sakuras"
            e.description = "Gagne, dépense et échange des 🌸 Sakuras !"
            e.add_field(name="!daily",                    value="Récompense quotidienne (100-500 🌸, cooldown 24h)", inline=False)
            e.add_field(name="!work",                     value="Travailler toutes les 2h (50-200 🌸)", inline=False)
            e.add_field(name="!balance [@membre]",        value="Voir son solde de Sakuras", inline=False)
            e.add_field(name="!give @membre [montant]",   value="Donner des Sakuras à quelqu'un", inline=False)
            e.add_field(name="!topmoney",                 value="Classement des membres les plus riches", inline=False)
            e.add_field(name="!setbirthday [JJ/MM]",      value="Enregistrer son anniversaire (+500 🌸 le jour J)", inline=False)
            e.add_field(name="⚙️ Admin",
                value="`!addmoney @m [n]` — Ajouter des Sakuras\n`!removemoney @m [n]` — Retirer des Sakuras",
                inline=False)

        elif cat == "vocal":
            e.title = "🎙️ Vocal Temporaire"
            e.description = "Crée ton propre salon vocal, gère-le comme tu veux."
            e.add_field(name="🔧 Setup (admin)", value="`!settempcreate #salon` — Définit le salon 'Rejoindre pour créer'", inline=False)
            e.add_field(name="🔒 !vlock",         value="Verrouille ton vocal (personne ne peut rejoindre)", inline=False)
            e.add_field(name="🔓 !vunlock",        value="Déverrouille ton vocal", inline=False)
            e.add_field(name="✏️ !vrename [nom]",  value="Renomme ton vocal", inline=False)
            e.add_field(name="👥 !vlimit [0-99]",  value="Limite le nombre de membres (0 = illimité)", inline=False)
            e.add_field(name="👢 !vkick @membre",  value="Expulse un membre de ton vocal", inline=False)
            e.add_field(name="✅ !vinvite @membre", value="Autorise un membre à rejoindre un vocal verrouillé", inline=False)
            e.add_field(name="👑 !vtransfer @m",   value="Transfère la propriété du vocal à un autre membre", inline=False)
            e.add_field(name="📋 !vinfo",           value="Affiche les infos de ton vocal temporaire", inline=False)

        elif cat == "fun":
            e.title = "🎲 Commandes Fun"
            e.description = "Détends-toi avec les commandes fun de Kozakura 🌸"
            e.add_field(name="!8ball [question]",       value="La boule magique répond à ta question 🔮", inline=False)
            e.add_field(name="!coinflip",               value="Pile ou face animé 🪙", inline=False)
            e.add_field(name="!dé [faces]",             value="Lancer un dé (défaut 6 faces) 🎲", inline=False)
            e.add_field(name="!ship @u1 @u2",           value="Compatibilité amoureuse entre deux membres 💘", inline=False)
            e.add_field(name="!compliment [@membre]",   value="Envoyer un compliment stylé 🌸", inline=False)
            e.add_field(name="!insulte [@membre]",      value="Insulte légère et drôle 😤", inline=False)
            e.add_field(name="🔥 !unfreeze @membre", value="Restaure les permissions d'un membre gelé", inline=False)
            e.add_field(name="🍯 !sethoneypot [#salon]", value="Crée un salon piège — alerte + ban auto si quelqu'un écrit dedans", inline=False)
            e.add_field(name="🔍 !whois @membre", value="Enquête complète : historique, risques, sanctions, rôles", inline=False)
            e.add_field(name="💾 !backup", value="Sauvegarde la structure du serveur (rôles, salons)", inline=False)
            e.add_field(name="♻️ !restorebackup", value="Restaure les rôles manquants depuis le dernier backup", inline=False)
            e.add_field(name="🔒 !quarantine @membre", value="Met en quarantaine (accès limité)", inline=False)
            e.add_field(name="🕵️ Détection usurpation", value="Alerte auto si un membre change de pseudo pour ressembler au staff", inline=False)
            e.add_field(name="📊 !securitystatus", value="Vue d'ensemble de la sécurité du serveur", inline=False)
            e.add_field(name="⚙️ Config",
                value="`!setsecuritylog #salon` — Salon logs sécurité\n`!setminage [jours]` — Âge minimum comptes\n`!setantibotprotection on/off` — Anti-bot",
                inline=False)

        await ctx.send(embed=e)
        return

    # ── Menu principal ──────────────────────────────────────────────────────
    e = discord.Embed(
        title="📖 Aide — Kozakura Bot",
        description=(
            f"Préfixe : `{PREFIX}` | Slash : `/`\n"
            f"Tape `!help [catégorie]` pour les détails.\n\u200b"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    if ctx.guild.icon:
        e.set_thumbnail(url=ctx.guild.icon.url)

    e.add_field(name="🔨 `!help mod`",        value="Ban, kick, mute, warn, clear, purge...", inline=True)
    e.add_field(name="📋 `!help sanctions`",   value="Infosanction, historique", inline=True)
    e.add_field(name="🎭 `!help roles`",       value="Addrole, delrole, reactionrole", inline=True)
    e.add_field(name="🎖️ `!help rank`",        value="Rankup, derank, setrank, ranglist", inline=True)
    e.add_field(name="🎫 `!help tickets`",     value="Panel, claim, add, remove, close", inline=True)
    e.add_field(name="⚖️ `!help tribunal`",    value="Vote tribunal avec rôle juge", inline=True)
    e.add_field(name="🏆 `!help xp`",          value="Rank, leaderboard, niveaux", inline=True)
    e.add_field(name="🏅 `!help trophees`",    value="Trophées, votes, vocal, badges", inline=True)
    e.add_field(name="💬 `!help communaute`",  value="Suggest, poll, stats, remind", inline=True)
    e.add_field(name="📝 `!help texte`",       value="Text, embed permanent", inline=True)
    e.add_field(name="💥 `!help massban`",     value="Mass ban avec confirmation", inline=True)
    e.add_field(name="⚙️ `!help admin`",       value="Config, logs, compteurs...", inline=True)
    e.add_field(name="⚡ `!help slash`",       value="Slash commands disponibles", inline=True)
    e.add_field(name="🤖 `!help ia`",          value="IA, imagine, traduis, moderation IA...", inline=True)
    e.add_field(name="📊 `!help stats`",       value="Activité membre, rapport hebdo...", inline=True)
    e.add_field(name="🔒 `!help securite`",    value="Lockdown, freeze, honeypot, whois, backup...", inline=True)
    e.add_field(name="🌸 `!help economie`",    value="Sakuras, daily, work, balance, topmoney...", inline=True)
    e.add_field(name="🎲 `!help fun`",         value="8ball, coinflip, dé, ship, compliment...", inline=True)
    e.add_field(name="🎙️ `!help vocal`",       value="Vocaux temporaires, lock, rename, kick...", inline=True)

    e.set_footer(text=f"Kozakura Bot • {ctx.guild.name}")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 📁 SYSTÈME RANK / DERANK
# ══════════════════════════════════════════════════════════════════════════════

# Hiérarchie des rangs : (rôle grade, rôle titre) du plus haut au plus bas
# Modifie les noms ici s'ils sont différents dans ton serveur
RANGS = [
    ("***", "Mirai"),
    ("**",  "Taiyō"),
    ("*",   "Hoshi"),
    ("III", "Shin"),
    ("II",  "Tsuki"),
    ("I",   "Kage"),
]

def get_rang_actuel(member):
    """Retourne (index, grade_role, titre_role) du rang actuel du membre, ou None"""
    for i, (grade, titre) in enumerate(RANGS):
        grade_role = discord.utils.get(member.guild.roles, name=grade)
        titre_role = discord.utils.get(member.guild.roles, name=titre)
        if grade_role and grade_role in member.roles:
            return i, grade_role, titre_role
    return None

async def log_rankderank(guild, embed):
    """Envoie le log dans 📁・rank-derank"""
    ch = discord.utils.find(
        lambda c: "rank-derank" in c.name.lower(), guild.text_channels)
    if ch: await ch.send(embed=embed)

@bot.command(name="rankup")
async def rank_up(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    """!rankup @membre [raison] — Monte le membre d'un rang"""
    if not has_sanction_role(ctx.author, ROLES_RANKDERANK):
        return await ctx.send("❌ Tu n'as pas la permission de gérer les rangs.", delete_after=5)
    # Gestion Modérations : restriction hiérarchique (ne peut pas rank quelqu'un au-dessus ou égal)
    if has_sanction_role(ctx.author, ["Gestion Modérations"]) and not has_sanction_role(ctx.author, ROLES_BAN):
        if member.top_role >= ctx.author.top_role:
            return await ctx.send("❌ Tu ne peux pas modifier le rang d'un membre avec un rôle supérieur ou égal au tien.", delete_after=5)
    guild = ctx.guild
    rang  = get_rang_actuel(member)

    # Trouver le prochain rang
    if rang is None:
        # Pas de rang → donner le rang le plus bas (index 5 = I / Kage)
        next_idx = len(RANGS) - 1
    else:
        current_idx = rang[0]
        if current_idx == 0:
            return await ctx.send(f"❌ {member.mention} est déjà au rang maximum (***** / Mirai**).")
        next_idx = current_idx - 1

    new_grade_name, new_titre_name = RANGS[next_idx]
    new_grade = discord.utils.get(guild.roles, name=new_grade_name)
    new_titre = discord.utils.get(guild.roles, name=new_titre_name)

    if not new_grade or not new_titre:
        return await ctx.send(
            f"❌ Rôles introuvables : **{new_grade_name}** et/ou **{new_titre_name}**.\n"
            "Vérifie que les noms correspondent exactement aux rôles Discord.")

    # Retirer l'ancien rang si existant
    if rang:
        old_grade, old_titre = rang[1], rang[2]
        try:
            roles_to_remove = [r for r in [old_grade, old_titre] if r and r in member.roles]
            if roles_to_remove: await member.remove_roles(*roles_to_remove)
        except Exception: pass

    # Donner le nouveau rang
    try:
        roles_to_add = [r for r in [new_grade, new_titre] if r]
        await member.add_roles(*roles_to_add)
    except discord.Forbidden:
        return await ctx.send("❌ Je n'ai pas la permission de gérer ces rôles. Vérifie ma hiérarchie.")

    old_name = f"{RANGS[rang[0]][0]} / {RANGS[rang[0]][1]}" if rang else "Aucun"
    new_name  = f"{new_grade_name} / {new_titre_name}"

    e = discord.Embed(
        title="📈 Rank Up",
        description=f"{member.mention} a été **promu** par {ctx.author.mention}",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Ancien rang", value=old_name)
    e.add_field(name="Nouveau rang", value=f"✨ **{new_name}**")
    e.add_field(name="Raison", value=reason, inline=False)
    e.set_footer(text=f"Par {ctx.author.display_name}")

    await ctx.send(embed=e)
    await log_rankderank(guild, e)

    # MP au membre
    await dm(member, "📈 Tu as été promu !",
        f"**Serveur :** {guild.name}\n**Nouveau rang :** {new_name}\n**Raison :** {reason}",
        color=discord.Color.green())

@bot.command(name="derank")
async def derank_down(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    """!derank @membre [raison] — Rétrograde le membre d'un rang"""
    if not has_sanction_role(ctx.author, ROLES_RANKDERANK):
        return await ctx.send("❌ Tu n'as pas la permission de gérer les rangs.", delete_after=5)
    # Gestion Modérations : restriction hiérarchique
    if has_sanction_role(ctx.author, ["Gestion Modérations"]) and not has_sanction_role(ctx.author, ROLES_BAN):
        if member.top_role >= ctx.author.top_role:
            return await ctx.send("❌ Tu ne peux pas modifier le rang d'un membre avec un rôle supérieur ou égal au tien.", delete_after=5)
    guild = ctx.guild
    rang  = get_rang_actuel(member)

    if rang is None:
        return await ctx.send(f"❌ {member.mention} n'a aucun rang à retirer.")

    current_idx = rang[0]

    # Rang le plus bas → retirer complètement
    if current_idx == len(RANGS) - 1:
        old_grade, old_titre = rang[1], rang[2]
        try:
            roles_to_remove = [r for r in [old_grade, old_titre] if r and r in member.roles]
            if roles_to_remove: await member.remove_roles(*roles_to_remove)
        except discord.Forbidden:
            return await ctx.send("❌ Je n'ai pas la permission de gérer ces rôles.")

        old_name = f"{RANGS[current_idx][0]} / {RANGS[current_idx][1]}"
        e = discord.Embed(
            title="📉 Derank",
            description=f"{member.mention} a été **rétrogradé** par {ctx.author.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Ancien rang", value=old_name)
        e.add_field(name="Nouveau rang", value="❌ Aucun rang")
        e.add_field(name="Raison", value=reason, inline=False)
        e.set_footer(text=f"Par {ctx.author.display_name}")
        await ctx.send(embed=e)
        await log_rankderank(guild, e)
        await dm(member, "📉 Tu as été rétrogradé",
            f"**Serveur :** {guild.name}\n**Ancien rang :** {old_name}\n**Tu n'as plus de rang.**\n**Raison :** {reason}",
            color=discord.Color.red())
        return

    # Rang suivant (plus bas)
    next_idx = current_idx + 1
    new_grade_name, new_titre_name = RANGS[next_idx]
    new_grade = discord.utils.get(guild.roles, name=new_grade_name)
    new_titre = discord.utils.get(guild.roles, name=new_titre_name)

    if not new_grade or not new_titre:
        return await ctx.send(
            f"❌ Rôles introuvables : **{new_grade_name}** et/ou **{new_titre_name}**.\n"
            "Vérifie que les noms correspondent exactement aux rôles Discord.")

    # Retirer l'ancien rang
    old_grade, old_titre = rang[1], rang[2]
    try:
        roles_to_remove = [r for r in [old_grade, old_titre] if r and r in member.roles]
        if roles_to_remove: await member.remove_roles(*roles_to_remove)
    except Exception: pass

    # Donner le rang inférieur
    try:
        roles_to_add = [r for r in [new_grade, new_titre] if r]
        await member.add_roles(*roles_to_add)
    except discord.Forbidden:
        return await ctx.send("❌ Je n'ai pas la permission de gérer ces rôles.")

    old_name = f"{RANGS[current_idx][0]} / {RANGS[current_idx][1]}"
    new_name  = f"{new_grade_name} / {new_titre_name}"

    e = discord.Embed(
        title="📉 Derank",
        description=f"{member.mention} a été **rétrogradé** par {ctx.author.mention}",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Ancien rang", value=old_name)
    e.add_field(name="Nouveau rang", value=f"⬇️ **{new_name}**")
    e.add_field(name="Raison", value=reason, inline=False)
    e.set_footer(text=f"Par {ctx.author.display_name}")

    await ctx.send(embed=e)
    await log_rankderank(guild, e)

    await dm(member, "📉 Tu as été rétrogradé",
        f"**Serveur :** {guild.name}\n**Ancien rang :** {old_name}\n**Nouveau rang :** {new_name}\n**Raison :** {reason}",
        color=discord.Color.red())

@bot.command(name="setrank")
@staff_only(list(ROLES_RANKDERANK))
async def set_rank(ctx, member: discord.Member, rang_num: int, *, reason: str = "Aucune raison"):
    """!setrank @membre [1-6] [raison] — Définit directement le rang (1=***, 6=I)"""
    guild = ctx.guild
    if rang_num < 1 or rang_num > 6:
        return await ctx.send("❌ Le rang doit être entre **1** (***) et **6** (I).")

    idx = rang_num - 1
    new_grade_name, new_titre_name = RANGS[idx]
    new_grade = discord.utils.get(guild.roles, name=new_grade_name)
    new_titre = discord.utils.get(guild.roles, name=new_titre_name)

    if not new_grade or not new_titre:
        return await ctx.send(
            f"❌ Rôles introuvables : **{new_grade_name}** et/ou **{new_titre_name}**.")

    # Retirer tous les anciens rangs
    all_rang_roles = []
    for g, t in RANGS:
        gr = discord.utils.get(guild.roles, name=g)
        tr = discord.utils.get(guild.roles, name=t)
        if gr: all_rang_roles.append(gr)
        if tr: all_rang_roles.append(tr)
    try:
        to_remove = [r for r in all_rang_roles if r in member.roles]
        if to_remove: await member.remove_roles(*to_remove)
    except Exception: pass

    # Donner le nouveau rang
    try:
        await member.add_roles(*[r for r in [new_grade, new_titre] if r])
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée.")

    new_name = f"{new_grade_name} / {new_titre_name}"
    e = discord.Embed(
        title="🎖️ Rang Défini",
        description=f"{member.mention} a reçu le rang **{new_name}** par {ctx.author.mention}",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Rang attribué", value=f"**{new_name}**")
    e.add_field(name="Raison", value=reason, inline=False)
    e.set_footer(text=f"Par {ctx.author.display_name}")

    await ctx.send(embed=e)
    await log_rankderank(guild, e)
    await dm(member, "🎖️ Rang attribué",
        f"**Serveur :** {guild.name}\n**Rang :** {new_name}\n**Raison :** {reason}",
        color=discord.Color.blurple())

@bot.command(name="removerank")
@staff_only(list(ROLES_RANKDERANK))
async def remove_rank(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    """!removerank @membre — Retire tous les rangs du membre"""
    guild = ctx.guild
    rang  = get_rang_actuel(member)
    if not rang:
        return await ctx.send(f"❌ {member.mention} n'a aucun rang.")

    old_name = f"{RANGS[rang[0]][0]} / {RANGS[rang[0]][1]}"
    old_grade, old_titre = rang[1], rang[2]
    try:
        to_remove = [r for r in [old_grade, old_titre] if r and r in member.roles]
        if to_remove: await member.remove_roles(*to_remove)
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée.")

    e = discord.Embed(
        title="❌ Rang Retiré",
        description=f"{member.mention} a perdu son rang **{old_name}**",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Rang retiré", value=old_name)
    e.add_field(name="Raison", value=reason, inline=False)
    e.set_footer(text=f"Par {ctx.author.display_name}")

    await ctx.send(embed=e)
    await log_rankderank(guild, e)
    await dm(member, "❌ Ton rang a été retiré",
        f"**Serveur :** {guild.name}\n**Rang retiré :** {old_name}\n**Raison :** {reason}",
        color=discord.Color.dark_red())

@bot.command(name="ranglist")
async def rang_list(ctx):
    """!ranglist — Affiche la hiérarchie des rangs"""
    e = discord.Embed(title="🎖️ Hiérarchie des Rangs", color=discord.Color.gold(),
        timestamp=datetime.utcnow())
    medals = ["👑", "⭐", "🌟", "💫", "✨", "🔰"]
    parts = []
    for i, (grade, titre) in enumerate(RANGS):
        grade_role = discord.utils.get(ctx.guild.roles, name=grade)
        titre_role = discord.utils.get(ctx.guild.roles, name=titre)
        gm = grade_role.mention if grade_role else f"`{grade}`"
        tm = titre_role.mention if titre_role else f"`{titre}`"
        parts.append(f"{medals[i]} {gm} + {tm}")
    e.description = "\n".join(parts)
    e.set_footer(text="!rank pour monter | !derank pour descendre")
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# 🏆 SYSTÈME DE TROPHÉES
# ══════════════════════════════════════════════════════════════════════════════

trophees_db = load_json("trophees.json", {})

# ─── CONFIG TROPHÉES ──────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def settrophees(ctx, *, arg: str):
    """!settrophees #salon — Définit le salon des trophées"""
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "trophees_channel", channel.id)
    await ctx.send(f"✅ Salon trophées → {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def addvote(ctx, member: discord.Member, amount: int = 1):
    """!addvote @membre [nombre] — Ajoute des votes à un membre"""
    gid = str(ctx.guild.id); uid = str(member.id)
    trophees_db.setdefault(gid, {}).setdefault(uid, {"votes": 0, "voice_minutes": 0})
    trophees_db[gid][uid]["votes"] = trophees_db[gid][uid].get("votes", 0) + amount
    save_json("trophees.json", trophees_db)
    await ctx.send(f"✅ +{amount} vote(s) pour {member.mention} (total : **{trophees_db[gid][uid]['votes']}**)")

@bot.command()
@commands.has_permissions(administrator=True)
async def removevote(ctx, member: discord.Member, amount: int = 1):
    """!removevote @membre [nombre] — Retire des votes à un membre"""
    gid = str(ctx.guild.id); uid = str(member.id)
    trophees_db.setdefault(gid, {}).setdefault(uid, {"votes": 0, "voice_minutes": 0})
    trophees_db[gid][uid]["votes"] = max(0, trophees_db[gid][uid].get("votes", 0) - amount)
    save_json("trophees.json", trophees_db)
    await ctx.send(f"✅ -{amount} vote(s) pour {member.mention} (total : **{trophees_db[gid][uid]['votes']}**)")

# ─── TRACKING VOCAL ───────────────────────────────────────────────────────────
voice_join_times = {}  # {member_id: timestamp}
XP_PER_VOICE_MIN = 1   # XP par minute en vocal

# Rôles autorisés à utiliser move_members sur l'utilisateur protégé (seulement la couronne)
VOC_PROTECTED_ALLOWED_ROLES = ("kozakura", "kozakura C.O.D")

async def _sanction_voc_actor(guild, actor, victim, action_type: str):
    """Sanctionne quelqu'un qui a tenté une action vocale sur un utilisateur protégé."""
    # Vérifie que l'acteur n'est pas dans les rôles autorisés
    actor_member = guild.get_member(actor.id)
    if actor_member and has_sanction_role(actor_member, list(VOC_PROTECTED_ALLOWED_ROLES)):
        return  # Rôle autorisé, pas de sanction

    if actor_member:
        # Retrait de tous les rôles
        try:
            roles_to_strip = [r for r in actor_member.roles if r.name != "@everyone"]
            if roles_to_strip:
                await actor_member.remove_roles(*roles_to_strip, reason=f"🔒 Protection voc — {action_type}")
        except Exception:
            pass
        # Kick
        try:
            await actor_member.kick(reason=f"🔒 Protection voc — {action_type}")
        except Exception:
            pass

    e = discord.Embed(
        title="🚨 PROTECTION VOC — ACTION BLOQUÉE",
        description=f"⛔ Tentative de **{action_type}** sur un utilisateur protégé — **banni automatiquement**.",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🎯 Victime",           value=f"{victim.mention} (`{victim.id}`)", inline=True)
    e.add_field(name="⚠️ Responsable",       value=f"{actor.mention} (`{actor.id}`)", inline=True)
    e.add_field(name="⚡ Action tentée",     value=action_type.capitalize(), inline=False)
    e.add_field(name="✅ Sanctions",         value="Rôles retirés • Kick", inline=False)
    e.set_footer(text="Kozakura Security MAX • Protection vocale")
    await log_security(guild, e)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    uid = str(member.id)
    gid = str(member.guild.id)
    guild = member.guild

    # ── PROTECTION VOC utilisateur protégé ────────────────────────────────────
    if member.id in ANTI_PING_USERS:

        async def _find_voc_actor(audit_action, window=10):
            """Cherche l'auteur d'une action dans l'audit log avec retry."""
            for _ in range(3):   # 3 tentatives
                await asyncio.sleep(0.8)
                try:
                    now_dt = discord.utils.utcnow()
                    async for entry in guild.audit_logs(limit=10, action=audit_action):
                        age = (now_dt - entry.created_at).total_seconds()
                        if age > window:
                            break
                        if entry.user.id != guild.me.id and entry.user.id != member.id:
                            return entry.user
                except Exception:
                    pass
            return None

        # ── Déconnexion forcée ──────────────────────────────────────────────
        if before.channel is not None and after.channel is None:
            actor = await _find_voc_actor(discord.AuditLogAction.member_disconnect)
            if actor:
                await _sanction_voc_actor(guild, actor, member, "déconnexion forcée du vocal")
                return

        # ── Mute serveur forcé ──────────────────────────────────────────────
        if not before.mute and after.mute:
            actor = await _find_voc_actor(discord.AuditLogAction.member_update)
            if actor:
                try:
                    await member.edit(mute=False, reason="🔒 Protection voc — unmute automatique")
                except Exception:
                    pass
                await _sanction_voc_actor(guild, actor, member, "mute serveur forcé")
                return

        # ── Sourd serveur forcé ─────────────────────────────────────────────
        if not before.deaf and after.deaf:
            actor = await _find_voc_actor(discord.AuditLogAction.member_update)
            if actor:
                try:
                    await member.edit(deafen=False, reason="🔒 Protection voc — undeafen automatique")
                except Exception:
                    pass
                await _sanction_voc_actor(guild, actor, member, "sourd serveur forcé")
                return

    # ── PROTECTION VOC légère (mute + warn) ──────────────────────────────────
    if member.id in VOC_WARN_USERS:
        action_done = None
        if before.channel is not None and after.channel is None:
            action_done = "déconnexion forcée"
            audit_action = discord.AuditLogAction.member_disconnect
        elif not before.mute and after.mute:
            action_done = "mute serveur forcé"
            audit_action = discord.AuditLogAction.member_update
        elif not before.deaf and after.deaf:
            action_done = "sourd serveur forcé"
            audit_action = discord.AuditLogAction.member_update
        else:
            audit_action = None

        if action_done:
            actor = None
            for _ in range(3):
                await asyncio.sleep(0.8)
                try:
                    now_dt = discord.utils.utcnow()
                    async for entry in guild.audit_logs(limit=10, action=audit_action):
                        age = (now_dt - entry.created_at).total_seconds()
                        if age > 10:
                            break
                        if entry.user.id != guild.me.id and entry.user.id != member.id:
                            actor = entry.user
                            break
                except Exception:
                    pass
                if actor:
                    break

            if actor:
                actor_member = guild.get_member(actor.id)
                if actor_member and not has_sanction_role(actor_member, list(VOC_PROTECTED_ALLOWED_ROLES)):
                    # 1️⃣ Mute serveur 1 minute
                    try:
                        until = discord.utils.utcnow() + timedelta(minutes=1)
                        await actor_member.timeout(until, reason=f"🔒 Protection voc — {action_done}")
                    except Exception:
                        pass

                    # 2️⃣ Ajouter 1 avertissement en DB
                    await log_sanction(
                        guild, actor_member, "Warn",
                        f"Action non autorisée sur un membre protégé : {action_done}",
                        guild.me
                    )

                    # 3️⃣ Alerte
                    e = discord.Embed(
                        title="⚠️ Protection VOC — Mute + Avertissement",
                        description=f"{actor_member.mention} a tenté une action non autorisée sur un membre protégé.",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow()
                    )
                    e.add_field(name="🎯 Membre protégé", value=f"<@{member.id}>", inline=True)
                    e.add_field(name="⚠️ Responsable",    value=f"{actor_member.mention} (`{actor_member.id}`)", inline=True)
                    e.add_field(name="⚡ Action tentée",  value=action_done.capitalize(), inline=False)
                    e.add_field(name="✅ Sanctions",      value="🔇 Mute 1 minute\n📋 1 avertissement ajouté", inline=False)
                    e.set_footer(text="Kozakura Security • Protection VOC")
                    await log_security(guild, e)
                    return

    # ── Vocal temporaire (Join to Create) ────────────────────────────────────
    # Détection : salon configuré OU nom contenant des mots-clés
    CREATE_VOC_KEYWORDS = ["créer-un-vocal", "creer-un-vocal", "create-a-voice",
                           "join-to-create", "créer un vocal", "➕", "créer"]
    create_ch_id = get_cfg(guild.id, "temp_voice_create_channel")
    is_create_channel = (
        (create_ch_id and after.channel and str(after.channel.id) == str(create_ch_id))
        or (after.channel and any(kw in after.channel.name.lower() for kw in CREATE_VOC_KEYWORDS))
    )
    if is_create_channel and after.channel and after.channel.id not in temp_voice_channels:
        category = after.channel.category
        try:
            new_ch = await guild.create_voice_channel(
                name=f"🎙️ {member.display_name}",
                category=category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(connect=True, speak=True),
                    member: discord.PermissionOverwrite(
                        connect=True, speak=True, mute_members=True,
                        deafen_members=True, move_members=True, manage_channels=True
                    ),
                    guild.me: discord.PermissionOverwrite(
                        connect=True, manage_channels=True, move_members=True
                    ),
                },
                reason=f"Vocal temporaire créé par {member}"
            )
            temp_voice_channels[new_ch.id] = member.id
            await member.move_to(new_ch, reason="Vocal temporaire")
            # Envoyer le panel de gestion en DM
            try:
                panel = TempVocalPanel(guild.id, new_ch.id)
                e_dm = discord.Embed(
                    title="🎙️ Ton vocal temporaire est prêt !",
                    description=(
                        f"**Salon :** {new_ch.name}\n"
                        "Utilise les boutons ci-dessous pour gérer ton vocal."
                    ),
                    color=0xFF89B4
                )
                e_dm.set_footer(text="Ce panel reste actif tant que tu es dans le vocal.")
                await member.send(embed=e_dm, view=panel)
            except Exception:
                pass  # DMs désactivés
        except Exception:
            pass

    # Suppression du vocal temporaire quand il est vide
    if before.channel and before.channel.id in temp_voice_channels:
        if len(before.channel.members) == 0:
            try:
                await before.channel.delete(reason="Vocal temporaire vide")
                temp_voice_channels.pop(before.channel.id, None)
            except Exception:
                pass

    # ── Anti-spam vocal ───────────────────────────────────────────────────────
    if before.channel != after.channel:
        now_v = time.time()
        voice_spam_tracker[uid].append(now_v)
        voice_spam_tracker[uid] = [t for t in voice_spam_tracker[uid] if now_v - t < 30]
        if len(voice_spam_tracker[uid]) >= VOICE_SPAM_THRESHOLD:
            try:
                until = discord.utils.utcnow() + timedelta(minutes=10)
                await member.timeout(until, reason="🔒 Anti-spam vocal")
            except Exception: pass
            e = discord.Embed(
                title="🔇 Anti-Spam Vocal",
                description=f"{member.mention} mute 10min pour spam vocal ({len(voice_spam_tracker[uid])}x en 30s)",
                color=discord.Color.orange(), timestamp=datetime.utcnow()
            )
            await log_security(member.guild, e)
            voice_spam_tracker[uid] = []

    # Rejoint un salon vocal
    if before.channel is None and after.channel is not None:
        voice_join_times[uid] = time.time()
        await refresh_vocal_counter(member.guild)
        e = discord.Embed(
            description=(
                f"🎙️ **{member.display_name}** a rejoint **{after.channel.name}**"
            ),
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_footer(text=f"#{after.channel.name}  •  {member.guild.name}")
        await log_vocal(member.guild, e)

    # Quitte un salon vocal
    elif before.channel is not None and after.channel is None:
        if uid in voice_join_times:
            elapsed_seconds = time.time() - voice_join_times.pop(uid)
            elapsed_minutes = int(elapsed_seconds / 60)

            if elapsed_minutes > 0:
                # Trophées — temps vocal
                trophees_db.setdefault(gid, {}).setdefault(uid, {"votes": 0, "voice_minutes": 0})
                trophees_db[gid][uid]["voice_minutes"] = trophees_db[gid][uid].get("voice_minutes", 0) + elapsed_minutes
                save_json("trophees.json", trophees_db)

                # XP vocal fusionné avec XP texte (1 XP/min)
                xp_gained = elapsed_minutes * XP_PER_VOICE_MIN
                xp_db.setdefault(gid, {})
                old_xp    = xp_db[gid].get(uid, 0)
                old_level = get_level(old_xp)
                xp_db[gid][uid] = old_xp + xp_gained
                new_level = get_level(xp_db[gid][uid])
                save_json("xp.json", xp_db)

                # Level up ?
                if new_level > old_level:
                    guild    = member.guild
                    SAKURA_PINK = 0xFF89B4
                    next_xp  = xp_for_level(new_level + 1)
                    e = discord.Embed(
                        title="⭐  Level Up ! (Vocal)",
                        description=(
                            f"## {member.mention}\n"
                            f"Félicitations, tu passes au **niveau {new_level}** grâce au vocal ! 🎙️\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                        ),
                        color=SAKURA_PINK,
                        timestamp=datetime.utcnow()
                    )
                    e.set_thumbnail(url=member.display_avatar.url)
                    e.add_field(name="🏅 Niveau",      value=f"`{new_level}`",         inline=True)
                    e.add_field(name="🎙️ Session",     value=f"`{elapsed_minutes}` min",inline=True)
                    e.add_field(name="✨ XP gagné",    value=f"`+{xp_gained}` XP",     inline=True)
                    e.add_field(name="🎯 Prochain niveau", value=f"`{next_xp}` XP",    inline=True)
                    e.set_footer(text=f"Kozakura XP  •  {guild.name}")
                    level_ch = discord.utils.find(
                        lambda c: "niveaux" in c.name.lower() or "niveau" in c.name.lower(),
                        guild.text_channels)
                    if level_ch:
                        await level_ch.send(embed=e)

                    # Rôles de niveau
                    for req, rname in sorted(LEVEL_ROLES.items()):
                        if new_level >= req:
                            role = discord.utils.get(guild.roles, name=rname)
                            if role and role not in member.roles:
                                try: await member.add_roles(role)
                                except Exception: pass

        await refresh_vocal_counter(member.guild)

        # Calcul du temps
        elapsed_min = int((time.time() - voice_join_times.get(uid, time.time())) / 60) if uid in voice_join_times else 0
        elapsed_display = f"{elapsed_min} min" if elapsed_min > 0 else "< 1 min"

        # Vérifier si déconnexion forcée via audit log
        kicker = None
        try:
            await asyncio.sleep(0.8)
            now_dt = discord.utils.utcnow()
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_disconnect):
                age = (now_dt - entry.created_at).total_seconds()
                if age < 8 and entry.user.id != guild.me.id and entry.user.id != member.id:
                    kicker = entry.user
                    break
        except Exception:
            pass

        # Log vocal départ
        if kicker:
            e_voc = discord.Embed(
                description=(
                    f"👢 **{member.display_name}** a été **expulsé du vocal** par {kicker.mention}\n"
                    f"📌 Salon : **{before.channel.name}**  •  ⏱️ `{elapsed_display}`"
                ),
                color=0xFF0000,
                timestamp=datetime.utcnow()
            )
            e_voc.set_author(name=str(member), icon_url=member.display_avatar.url)
            e_voc.add_field(name="👮 Expulsé par", value=f"{kicker.mention}\n`{kicker.id}`", inline=True)
            e_voc.add_field(name="📌 Salon",        value=before.channel.name, inline=True)
        else:
            e_voc = discord.Embed(
                description=(
                    f"🔇 **{member.display_name}** a quitté **{before.channel.name}**\n"
                    f"⏱️ Temps passé : `{elapsed_display}`"
                ),
                color=0xED4245,
                timestamp=datetime.utcnow()
            )
            e_voc.set_author(name=str(member), icon_url=member.display_avatar.url)
        e_voc.set_footer(text=f"#{before.channel.name}  •  {member.guild.name}")
        await log_vocal(member.guild, e_voc)

    # Changement de salon vocal
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        e_voc = discord.Embed(
            title="🔀 Changement de vocal",
            description=f"{member.mention} : **{before.channel.name}** → **{after.channel.name}**",
            color=discord.Color.blurple(), timestamp=datetime.utcnow()
        )
        e_voc.set_thumbnail(url=member.display_avatar.url)
        await log_vocal(member.guild, e_voc)

        # ── Mode Dog : déplacer les followers ────────────────────────────────
        master_id = str(member.id)
        for follower_id, target_id in list(dog_followers.items()):
            if target_id == master_id:
                # Ce membre doit suivre
                follower = member.guild.get_member(int(follower_id))
                if follower and follower.voice and follower.voice.channel:
                    if follower.voice.channel != after.channel:
                        try:
                            await asyncio.sleep(0.5)
                            await follower.move_to(after.channel, reason="🐕 Mode Dog — suit son maître")
                        except Exception: pass

def get_trophee_badges(votes, voice_minutes, booster):
    """Retourne les badges trophées selon les stats"""
    badges = []

    # Badges votes
    if votes >= 500: badges.append("🏆 Légende des Votes")
    elif votes >= 200: badges.append("🥇 Expert Voteur")
    elif votes >= 100: badges.append("🥈 Voteur Assidu")
    elif votes >= 50:  badges.append("🥉 Bon Voteur")
    elif votes >= 10:  badges.append("📊 Débutant Voteur")

    # Badges vocal
    h = voice_minutes // 60
    if h >= 500:  badges.append("🎙️ Légende Vocal")
    elif h >= 200: badges.append("🔊 Maître du Vocal")
    elif h >= 100: badges.append("📢 Habitué du Vocal")
    elif h >= 50:  badges.append("🎤 Actif Vocal")
    elif h >= 10:  badges.append("🔈 Nouveau Vocal")

    # Badge boost
    if booster: badges.append("💎 Booster du Serveur")

    return badges if badges else ["🌱 Débutant"]

def _progress_bar(current, target, prev=0, width=12):
    total = max(target - prev, 1)
    filled = min(int((current - prev) / total * width), width)
    return "█" * filled + "░" * (width - filled)

@bot.command()
async def trophe(ctx, member: discord.Member = None):
    """!trophe [@membre] — Affiche le trophée d'un membre"""
    member = member or ctx.author
    guild  = ctx.guild
    gid    = str(guild.id)
    uid    = str(member.id)
    ch_id  = get_cfg(guild.id, "trophees_channel")

    data        = trophees_db.get(gid, {}).get(uid, {})
    votes       = data.get("votes", 0)
    voice_min   = data.get("voice_minutes", 0)
    voice_h     = voice_min // 60
    voice_m     = voice_min % 60
    booster     = member.premium_since is not None

    # XP
    xp_data = xp_db.get(gid, {})
    xp      = xp_data.get(uid, 0)
    lvl     = get_level(xp)

    # Classement vocal
    top_vocal = sorted(trophees_db.get(gid, {}).items(), key=lambda x: x[1].get("voice_minutes", 0), reverse=True)
    rank_vocal = next((i + 1 for i, (u, _) in enumerate(top_vocal) if u == uid), "?")

    badges = get_trophee_badges(votes, voice_min, booster)

    # Barres de progression
    VOTE_MILESTONES  = [10, 50, 100, 200, 500]
    VOICE_MILESTONES = [10, 50, 100, 200, 500]

    next_v  = next((n for n in VOTE_MILESTONES  if n > votes),   None)
    prev_v  = max((n for n in [0]+VOTE_MILESTONES  if n <= votes),   default=0)
    next_vh = next((n for n in VOICE_MILESTONES if n > voice_h),  None)
    prev_vh = max((n for n in [0]+VOICE_MILESTONES if n <= voice_h), default=0)

    bar_votes = _progress_bar(votes,   next_v  or votes+1,  prev_v)  if next_v  else "█" * 12
    bar_voice = _progress_bar(voice_h, next_vh or voice_h+1, prev_vh) if next_vh else "█" * 12

    GOLD = 0xFFD700
    e = discord.Embed(color=GOLD, timestamp=datetime.utcnow())
    e.set_author(name=f"🏆  Trophée de {member.display_name}", icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)

    e.add_field(
        name="🗳️ Votes",
        value=(
            f"**{votes}** vote(s)\n"
            f"`{bar_votes}` → **{next_v or '✅ MAX'}**"
        ),
        inline=True
    )
    e.add_field(
        name="🎙️ Temps vocal",
        value=(
            f"**{voice_h}h {voice_m}min**\n"
            f"`{bar_voice}` → **{next_vh or '✅ MAX'}h**"
        ),
        inline=True
    )
    e.add_field(
        name="⭐ Niveau XP",
        value=f"Niv. **{lvl}**  •  `{xp}` XP\n🎙️ Rang vocal : **#{rank_vocal}**",
        inline=True
    )
    e.add_field(
        name="🎖️ Badges",
        value="  ".join(badges) if badges else "🌱 Aucun badge encore",
        inline=False
    )
    if booster:
        e.add_field(name="💎 Booster", value="Merci de booster le serveur !", inline=False)

    e.set_footer(text=f"Kozakura  •  {guild.name}", icon_url=guild.me.display_avatar.url)

    if ch_id:
        trophee_ch = guild.get_channel(int(ch_id))
        if trophee_ch and trophee_ch != ctx.channel:
            await trophee_ch.send(embed=e)
            await ctx.send(f"✅ Trophée envoyé dans {trophee_ch.mention} !", delete_after=5)
            return
    await ctx.send(embed=e)

@bot.command()
async def topvotes(ctx):
    """!topvotes — Classement des membres par votes"""
    gid  = str(ctx.guild.id)
    data = trophees_db.get(gid, {})
    top  = sorted(data.items(), key=lambda x: x[1].get("votes", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    e = discord.Embed(
        title="🗳️  Top Votes — Kozakura",
        color=0xFFD700,
        timestamp=datetime.utcnow()
    )
    if ctx.guild.icon: e.set_thumbnail(url=ctx.guild.icon.url)
    if not top:
        e.description = "Aucun vote enregistré pour l'instant."
    else:
        lines = []
        for i, (uid, d) in enumerate(top):
            m     = ctx.guild.get_member(int(uid))
            votes = d.get("votes", 0)
            name  = m.display_name if m else f"*{uid}*"
            lines.append(f"{medals[i]} **{name}** — `{votes}` vote(s)")
        e.description = "\n".join(lines)
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def topvocal(ctx):
    """!topvocal — Classement des membres par temps vocal"""
    gid  = str(ctx.guild.id)
    data = trophees_db.get(gid, {})
    top  = sorted(data.items(), key=lambda x: x[1].get("voice_minutes", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    e = discord.Embed(
        title="🎙️  Top Vocal — Kozakura",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.utcnow()
    )
    if ctx.guild.icon: e.set_thumbnail(url=ctx.guild.icon.url)
    if not top:
        e.description = "Aucune donnée vocale enregistrée pour l'instant."
    else:
        lines = []
        for i, (uid, d) in enumerate(top):
            m  = ctx.guild.get_member(int(uid))
            vm = d.get("voice_minutes", 0)
            h  = vm // 60; mn = vm % 60
            name = m.display_name if m else f"*{uid}*"
            lines.append(f"{medals[i]} **{name}** — `{h}h {mn}min`")
        e.description = "\n".join(lines)
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    mid = str(payload.message_id)
    if mid in reaction_roles:
        guild  = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        role   = guild.get_role(reaction_roles[mid]["role_id"])
        if role and member:
            try: await member.add_roles(role)
            except Exception: pass

    # ── Starboard ─────────────────────────────────────────────────────────────
    if str(payload.emoji) == "⭐":
        guild  = bot.get_guild(payload.guild_id)
        if not guild: return
        gid    = str(guild.id)
        sb_ch_id = get_cfg(guild.id, "starboard_channel")
        if not sb_ch_id: return
        sb_ch = guild.get_channel(int(sb_ch_id))
        if not sb_ch: return
        try:
            ch      = guild.get_channel(payload.channel_id)
            message = await ch.fetch_message(payload.message_id)
        except Exception: return
        # Compter les ⭐
        star_count = 0
        for r in message.reactions:
            if str(r.emoji) == "⭐":
                star_count = r.count
                break
        if star_count < STARBOARD_THRESHOLD: return
        sb_key = str(payload.message_id)
        existing_id = starboard_db.get(gid, {}).get(sb_key)
        # Construire l'embed starboard
        e = discord.Embed(
            description=message.content[:2000] if message.content else "",
            color=0xFFD700,
            timestamp=message.created_at
        )
        e.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        e.add_field(name="📌 Source", value=f"[Aller au message]({message.jump_url})", inline=True)
        e.add_field(name="⭐ Étoiles", value=f"`{star_count}`", inline=True)
        if message.attachments:
            e.set_image(url=message.attachments[0].url)
        e.set_footer(text=f"#{ch.name}  •  {guild.name}")
        if existing_id:
            try:
                sb_msg = await sb_ch.fetch_message(int(existing_id))
                await sb_msg.edit(embed=e)
            except Exception: pass
        else:
            sb_msg = await sb_ch.send(embed=e)
            starboard_db.setdefault(gid, {})[sb_key] = str(sb_msg.id)
            save_json("starboard.json", starboard_db)

@bot.event
async def on_raw_reaction_remove(payload):
    mid = str(payload.message_id)
    if mid in reaction_roles:
        guild  = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        role   = guild.get_role(reaction_roles[mid]["role_id"])
        if role and member:
            try: await member.remove_roles(role)
            except Exception: pass

            try: await member.remove_roles(role)
            except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
# 🔒 SÉCURITÉ AVANCÉE — ANTI-NUKE & LOCKDOWN
# ══════════════════════════════════════════════════════════════════════════════

# ── Events Anti-Nuke ──────────────────────────────────────────────────────────
@bot.event
async def on_guild_channel_delete(channel):
    """Détecte la suppression massive de salons"""
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.user and not entry.user.bot:
            await nuke_action(guild, entry.user, f"Suppression salon : #{channel.name}")

@bot.event
async def on_guild_channel_create(channel):
    """Détecte la création massive de salons"""
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if entry.user and not entry.user.bot:
            await nuke_action(guild, entry.user, f"Création salon : #{channel.name}")

@bot.event
async def on_guild_role_delete(role):
    """Détecte la suppression massive de rôles + protection rôles protégés"""
    guild = role.guild

    # ── PROTECTION MAX : rôle protégé supprimé ───────────────────────────────
    if role.name in PROTECTED_ROLES:
        await asyncio.sleep(0.3)
        actor = None
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                actor = entry.user
                break
        except Exception:
            pass

        crown_role     = discord.utils.get(guild.roles, name=ROLE_CROWN)
        actor_is_crown = crown_role and actor and crown_role in actor.roles
        actor_is_bot   = actor and actor.id == guild.me.id

        if not actor_is_crown and not actor_is_bot and actor:
            actor_member = guild.get_member(actor.id)
            if actor_member:
                try:
                    roles_to_strip = [r for r in actor_member.roles if r.name != "@everyone"]
                    if roles_to_strip:
                        await actor_member.remove_roles(*roles_to_strip, reason="🔒 PROTECTION MAX — suppression rôle protégé")
                except Exception:
                    pass
                try:
                    until = datetime.utcnow() + timedelta(days=28)
                    await actor_member.timeout(until, reason="🔒 PROTECTION MAX — suppression rôle protégé")
                except Exception:
                    pass
                try:
                    await actor_member.kick(reason="🔒 PROTECTION MAX — suppression rôle protégé")
                except Exception:
                    pass

        e = discord.Embed(
            title="🚨 ALERTE MAX — RÔLE PROTÉGÉ SUPPRIMÉ",
            description=f"⛔ Le rôle protégé **{role.name}** a été **supprimé** ! Recréez-le immédiatement.",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="🎭 Rôle supprimé", value=f"**{role.name}**", inline=True)
        e.add_field(name="⚠️ Responsable",   value=actor.mention if actor else "Inconnu", inline=True)
        if actor and not actor_is_crown:
            e.add_field(name="⚡ Sanctions",  value="✅ Tous rôles retirés\n✅ Timeout 28j\n✅ Kick", inline=False)
        e.set_footer(text="Kozakura Security MAX • Action immédiate requise")
        await log_security(guild, e)
        return

    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        if entry.user and not entry.user.bot:
            await nuke_action(guild, entry.user, f"Suppression rôle : @{role.name}")


@bot.event
async def on_guild_role_update(before, after):
    """PROTECTION MAX — empêche toute modification des permissions d'un rôle protégé"""
    if before.name not in PROTECTED_ROLES:
        return
    guild = after.guild
    await asyncio.sleep(0.3)
    actor = None
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            actor = entry.user
            break
    except Exception:
        pass

    crown_role     = discord.utils.get(guild.roles, name=ROLE_CROWN)
    actor_is_crown = crown_role and actor and crown_role in actor.roles
    actor_is_bot   = actor and actor.id == guild.me.id

    if not actor_is_crown and not actor_is_bot:
        # Revert les permissions du rôle à l'état d'avant
        try:
            await after.edit(
                permissions=before.permissions,
                name=before.name,
                color=before.color,
                hoist=before.hoist,
                mentionable=before.mentionable,
                reason="🔒 PROTECTION MAX — modification rôle protégé annulée"
            )
        except Exception:
            pass

        if actor:
            actor_member = guild.get_member(actor.id)
            if actor_member:
                try:
                    roles_to_strip = [r for r in actor_member.roles if r.name != "@everyone"]
                    if roles_to_strip:
                        await actor_member.remove_roles(*roles_to_strip, reason="🔒 PROTECTION MAX")
                except Exception:
                    pass
                try:
                    until = datetime.utcnow() + timedelta(days=28)
                    await actor_member.timeout(until, reason="🔒 PROTECTION MAX — modification rôle protégé")
                except Exception:
                    pass
                try:
                    await actor_member.kick(reason="🔒 PROTECTION MAX — modification rôle protégé")
                except Exception:
                    pass

        e = discord.Embed(
            title="🚨 PROTECTION MAX — MODIFICATION RÔLE PROTÉGÉ",
            description=f"⛔ Tentative de modification du rôle **{before.name}** **annulée et sanctionnée**.",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="🎭 Rôle ciblé",    value=f"**{before.name}**", inline=True)
        e.add_field(name="⚠️ Responsable",   value=actor.mention if actor else "Inconnu", inline=True)
        e.add_field(name="⚡ Sanctions",      value="✅ Rôle rétabli\n✅ Tous rôles retirés\n✅ Timeout 28j\n✅ Kick", inline=False)
        e.set_footer(text="Kozakura Security MAX")
        await log_security(guild, e)

@bot.event
async def on_member_ban(guild, user):
    """Détecte les bans massifs + sauvegarde les bannis pour détection retour"""
    # Sauvegarder le banni
    gid = str(guild.id)
    banned_db.setdefault(gid, {})[str(user.id)] = {
        "name":         user.name,
        "display_name": user.display_name,
        "discriminator": user.discriminator,
        "avatar":       str(user.avatar) if user.avatar else None,
        "banned_at":    str(datetime.utcnow()),
    }
    save_json("banned_members.json", banned_db)

    # Anti-nuke : détecter ban massif
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.user and not entry.user.bot and entry.user != guild.owner:
            await nuke_action(guild, entry.user, f"Ban de {user}")

@bot.event
async def on_webhooks_update(channel):
    """Détecte la création de webhooks suspects"""
    guild = channel.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
        if entry.user and not entry.user.bot:
            e = discord.Embed(
                title="⚠️ Webhook Créé",
                description=f"Nouveau webhook dans {channel.mention} par {entry.user.mention}",
                color=discord.Color.orange(), timestamp=datetime.utcnow()
            )
            await log_security(guild, e)

# ── Events sécurité supplémentaires ──────────────────────────────────────────

@bot.event
async def on_guild_update(before, after):
    """Détecte les modifications suspectes du serveur (nuke)"""
    guild = after
    changes = []
    if before.name != after.name:
        changes.append(f"📛 Nom : `{before.name}` → `{after.name}`")
    if before.icon != after.icon:
        changes.append("🖼️ Icône modifiée")
    if before.vanity_url_code != after.vanity_url_code:
        changes.append(f"🔗 Vanity URL modifiée : `{before.vanity_url_code}` → `{after.vanity_url_code}`")
    if before.verification_level != after.verification_level:
        changes.append(f"🛡️ Niveau vérif : `{before.verification_level}` → `{after.verification_level}`")

    if not changes:
        return

    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
        if entry.user and not entry.user.bot:
            await nuke_action(guild, entry.user, f"Modification serveur : {', '.join(changes)}")
            e = discord.Embed(
                title="⚙️ Serveur Modifié",
                description=f"Modifications détectées par {entry.user.mention}",
                color=discord.Color.orange(), timestamp=datetime.utcnow()
            )
            for chg in changes:
                e.add_field(name="Changement", value=chg, inline=False)
            e.set_footer(text="Kozakura Security")
            await log_security(guild, e)

@bot.event
async def on_guild_role_create(role):
    """Détecte la création massive de rôles (nuke)"""
    guild = role.guild
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
        if entry.user and not entry.user.bot:
            await nuke_action(guild, entry.user, f"Création rôle : @{role.name}")

@bot.event
async def on_member_update(before, after):
    """Détecte attribution de permissions dangereuses + protection des rôles protégés + pseudo"""
    guild = after.guild

    # ── PROTECTION PSEUDO utilisateur protégé ─────────────────────────────────
    if after.id in ANTI_PING_USERS and before.nick != after.nick:
        await asyncio.sleep(0.3)
        actor = None
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                actor = entry.user
                break
        except Exception:
            pass

        actor_is_self = actor and actor.id == after.id
        actor_is_bot  = actor and actor.id == guild.me.id

        if not actor_is_self and not actor_is_bot and actor:
            # Rétablir l'ancien pseudo
            try:
                await after.edit(nick=before.nick, reason="🔒 Protection pseudo — annulation automatique")
            except Exception:
                pass

            # Sanctions
            actor_member = guild.get_member(actor.id)
            if actor_member:
                try:
                    roles_to_strip = [r for r in actor_member.roles if r.name != "@everyone"]
                    if roles_to_strip:
                        await actor_member.remove_roles(*roles_to_strip, reason="🔒 Protection pseudo")
                except Exception:
                    pass
                try:
                    until = datetime.utcnow() + timedelta(days=28)
                    await actor_member.timeout(until, reason="🔒 Protection pseudo — modification non autorisée")
                except Exception:
                    pass
                try:
                    await actor_member.kick(reason="🔒 Protection pseudo — modification non autorisée")
                except Exception:
                    pass

            e = discord.Embed(
                title="🚨 PROTECTION PSEUDO — ACTION BLOQUÉE",
                description="⛔ Tentative de modification du pseudo d'un utilisateur protégé — sanctionné automatiquement.",
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
            e.add_field(name="👤 Membre ciblé",     value=f"{after.mention} (`{after.id}`)", inline=True)
            e.add_field(name="⚠️ Responsable",      value=f"{actor.mention} (`{actor.id}`)", inline=True)
            e.add_field(name="📝 Ancien pseudo",    value=before.nick or "*(aucun)*", inline=True)
            e.add_field(name="❌ Nouveau pseudo",   value=after.nick or "*(aucun)*", inline=True)
            e.add_field(name="✅ Sanctions",        value="Pseudo rétabli • Rôles retirés • Timeout 28j • Kick", inline=False)
            e.set_footer(text="Kozakura Security MAX • Protection pseudo")
            await log_security(guild, e)
            return

    if before.roles == after.roles:
        return
    added_roles   = [r for r in after.roles if r not in before.roles]
    removed_roles = [r for r in before.roles if r not in after.roles]

    # ── PROTECTION MAXIMALE — Rôles protégés (ex: Développer) ──────────────────
    changed_protected = [r for r in added_roles + removed_roles if r.name in PROTECTED_ROLES]
    if changed_protected:
        await asyncio.sleep(0.3)
        actor = None
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                actor = entry.user
                break
        except Exception:
            pass

        crown_role   = discord.utils.get(guild.roles, name=ROLE_CROWN)
        actor_is_crown = crown_role and actor and crown_role in actor.roles
        actor_is_bot   = actor and actor.id == guild.me.id

        if not actor_is_crown and not actor_is_bot:
            # 1️⃣ Revert immédiat
            for role in changed_protected:
                try:
                    if role in added_roles:
                        await after.remove_roles(role, reason="🔒 PROTECTION MAX — annulation")
                    else:
                        await after.add_roles(role, reason="🔒 PROTECTION MAX — annulation")
                except Exception:
                    pass

            # 2️⃣ Retirer TOUS les rôles de l'acteur (sauf @everyone)
            if actor:
                actor_member = guild.get_member(actor.id)
                if actor_member:
                    try:
                        roles_to_strip = [r for r in actor_member.roles if r.name != "@everyone"]
                        if roles_to_strip:
                            await actor_member.remove_roles(*roles_to_strip, reason="🔒 PROTECTION MAX — tentative sur rôle protégé")
                    except Exception:
                        pass

                    # 3️⃣ Timeout 28 jours (maximum Discord)
                    try:
                        until = datetime.utcnow() + timedelta(days=28)
                        await actor_member.timeout(until, reason="🔒 PROTECTION MAX — tentative sur rôle protégé")
                    except Exception:
                        pass

                    # 4️⃣ Kick
                    try:
                        await actor_member.kick(reason="🔒 PROTECTION MAX — tentative de modification d'un rôle protégé")
                    except Exception:
                        pass

            # 5️⃣ Alerte sécurité maximale
            e = discord.Embed(
                title="🚨 PROTECTION MAXIMALE — RÔLE PROTÉGÉ",
                description=(
                    f"⛔ **Tentative non autorisée détectée et neutralisée.**\n"
                    f"Seul le rôle **{ROLE_CROWN}** peut modifier les rôles protégés."
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
            e.add_field(name="🎭 Rôle(s) visé(s)",    value=", ".join(f"**{r.name}**" for r in changed_protected), inline=False)
            e.add_field(name="👤 Membre ciblé",         value=f"{after.mention} (`{after.id}`)", inline=True)
            e.add_field(name="⚠️ Responsable",          value=actor.mention if actor else "Inconnu", inline=True)
            e.add_field(name="⚡ Sanctions appliquées", value="✅ Revert\n✅ Tous rôles retirés\n✅ Timeout 28j\n✅ Kick", inline=False)
            e.set_thumbnail(url=actor.display_avatar.url if actor else guild.me.display_avatar.url)
            e.set_footer(text="Kozakura Security MAX • Protection automatique")
            await log_security(guild, e)
            return

    dangerous_perms = ["administrator", "manage_guild", "manage_channels",
                       "manage_roles", "manage_webhooks", "ban_members", "kick_members"]
    for role in added_roles:
        if any(getattr(role.permissions, p, False) for p in dangerous_perms):
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                moderator = entry.user
                break
            else:
                moderator = None
            e = discord.Embed(
                title="⚠️ Rôle Dangereux Attribué",
                description=f"{after.mention} a reçu le rôle **{role.name}** (permissions élevées)",
                color=discord.Color.orange(), timestamp=datetime.utcnow()
            )
            e.add_field(name="👤 Membre", value=f"{after} (`{after.id}`)", inline=True)
            e.add_field(name="🎭 Rôle", value=f"@{role.name}", inline=True)
            if moderator:
                e.add_field(name="🛡️ Attribué par", value=f"{moderator.mention}", inline=True)
            e.add_field(name="⚙️ Permissions", value=", ".join(p for p in dangerous_perms if getattr(role.permissions, p, False)), inline=False)
            e.set_thumbnail(url=after.display_avatar.url)
            e.set_footer(text="Kozakura Security • Vérifiez si intentionnel")
            await log_security(guild, e)
            break

@bot.event
async def on_invite_create(invite):
    """Log les invitations créées + mise à jour du cache"""
    guild = invite.guild
    # Mise à jour du cache
    invite_cache.setdefault(guild.id, {})[invite.code] = invite.uses
    e = discord.Embed(
        title="🔗 Invitation Créée",
        description=f"Nouvelle invitation par {invite.inviter.mention if invite.inviter else '?'}",
        color=discord.Color.blurple(), timestamp=datetime.utcnow()
    )
    e.add_field(name="📎 Code", value=f"`discord.gg/{invite.code}`", inline=True)
    e.add_field(name="♾️ Utilisations max", value=str(invite.max_uses) if invite.max_uses else "Illimité", inline=True)
    e.add_field(name="⏳ Expire dans", value=str(timedelta(seconds=invite.max_age)) if invite.max_age else "Jamais", inline=True)
    e.add_field(name="📌 Salon", value=invite.channel.mention if invite.channel else "?", inline=True)
    e.set_footer(text="Kozakura Security • Invite Tracker")
    await log_security(guild, e)

@bot.event
async def on_invite_delete(invite):
    """Log les invitations supprimées + mise à jour du cache"""
    if not invite.guild:
        return
    # Retirer du cache
    invite_cache.get(invite.guild.id, {}).pop(invite.code, None)
    e = discord.Embed(
        title="🔗 Invitation Supprimée",
        description=f"Code : `discord.gg/{invite.code}`",
        color=discord.Color.red(), timestamp=datetime.utcnow()
    )
    e.add_field(name="📌 Salon", value=invite.channel.mention if invite.channel else "?", inline=True)
    e.set_footer(text="Kozakura Security")
    await log_security(invite.guild, e)

# ── Helper lockdown (appelable sans ctx) ─────────────────────────────────────
async def trigger_lockdown(guild, raison: str = "Mesure de sécurité d'urgence", triggered_by: str = "Anti-Raid automatique"):
    """Verrouille tous les salons texte — peut être appelé sans contexte de commande."""
    gid = str(guild.id)
    if lockdown_active.get(gid):
        return  # Déjà en lockdown
    lockdown_active[gid] = True
    locked = 0
    for channel in guild.text_channels:
        try:
            overwrite = channel.overwrites_for(guild.default_role)
            lockdown_backup[channel.id] = overwrite.pair()
            overwrite.send_messages = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite,
                reason=f"🔒 Lockdown auto : {raison}")
            locked += 1
        except Exception:
            pass
    e = discord.Embed(
        title="🔒 SERVEUR EN LOCKDOWN",
        description=f"**{locked}** salon(s) verrouillé(s)\n**Raison :** {raison}",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🛡️ Déclenché par", value=triggered_by)
    e.add_field(name="🔓 Pour lever", value="`!unlockdown`")
    e.set_footer(text="Kozakura Security")
    await log_security(guild, e)
    # Ping staff dans le salon de sécurité
    staff_role = discord.utils.get(guild.roles, name="Gestion")
    sec_ch = discord.utils.find(
        lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels
    )
    if sec_ch and staff_role:
        await sec_ch.send(f"🚨 {staff_role.mention} — **LOCKDOWN AUTOMATIQUE** : {raison}", embed=e)
    elif sec_ch:
        await sec_ch.send(f"🚨 **LOCKDOWN AUTOMATIQUE** : {raison}", embed=e)

# ── Commandes Lockdown ────────────────────────────────────────────────────────
@bot.command(name="lockdown")
@commands.has_permissions(administrator=True)
async def lockdown(ctx, *, raison: str = "Mesure de sécurité d'urgence"):
    """!lockdown [raison] — Verrouille tous les salons texte immédiatement"""
    guild = ctx.guild
    gid   = str(guild.id)

    if lockdown_active.get(gid):
        return await ctx.send("⚠️ Le serveur est déjà en lockdown. Utilise `!unlockdown` pour lever.")

    lockdown_active[gid] = True
    msg = await ctx.send("🔒 Lockdown en cours...")
    locked = 0

    for channel in guild.text_channels:
        try:
            # Sauvegarder les permissions actuelles de @everyone
            overwrite = channel.overwrites_for(guild.default_role)
            lockdown_backup[channel.id] = overwrite.pair()
            # Bloquer l'envoi de messages
            overwrite.send_messages = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite,
                reason=f"🔒 Lockdown : {raison}")
            locked += 1
        except Exception: pass

    e = discord.Embed(
        title="🔒 SERVEUR EN LOCKDOWN",
        description=f"**{locked}** salon(s) verrouillé(s)\n**Raison :** {raison}",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🛡️ Déclenché par", value=ctx.author.mention)
    e.add_field(name="🔓 Pour lever", value="`!unlockdown`")
    e.set_footer(text="Kozakura Security")

    await msg.edit(content="", embed=e)
    await log_security(guild, e)

    # Annoncer dans le salon actuel
    staff_role = discord.utils.get(guild.roles, name="Gestion")
    if staff_role:
        await ctx.send(f"🚨 {staff_role.mention} — Serveur en lockdown !")

@bot.command(name="unlockdown")
@commands.has_permissions(administrator=True)
async def unlockdown(ctx):
    """!unlockdown — Lève le lockdown et restaure les permissions"""
    guild = ctx.guild
    gid   = str(guild.id)

    if not lockdown_active.get(gid):
        return await ctx.send("❌ Le serveur n'est pas en lockdown.")

    lockdown_active[gid] = False
    msg = await ctx.send("🔓 Levée du lockdown en cours...")
    unlocked = 0

    for channel in guild.text_channels:
        try:
            overwrite = channel.overwrites_for(guild.default_role)
            # Restaurer les permissions sauvegardées ou remettre à None
            if channel.id in lockdown_backup:
                allow, deny = lockdown_backup[channel.id]
                overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
                del lockdown_backup[channel.id]
            else:
                overwrite.send_messages = None
            await channel.set_permissions(guild.default_role, overwrite=overwrite,
                reason="🔓 Lockdown levé")
            unlocked += 1
        except Exception: pass

    e = discord.Embed(
        title="🔓 LOCKDOWN LEVÉ",
        description=f"**{unlocked}** salon(s) déverrouillé(s)",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🛡️ Levé par", value=ctx.author.mention)
    e.set_footer(text="Kozakura Security")

    await msg.edit(content="", embed=e)
    await log_security(guild, e)

@bot.command(name="securitystatus")
@staff_only()
async def security_status(ctx):
    """!securitystatus — Affiche le statut de sécurité du serveur"""
    guild = ctx.guild
    gid   = str(guild.id)

    # Compter les membres suspects
    suspects = []
    for m in guild.members:
        if m.bot: continue
        age = (datetime.utcnow() - m.created_at.replace(tzinfo=None)).days
        if age < ACCOUNT_MIN_AGE_DAYS or not m.avatar:
            suspects.append(m)

    # Membres mutés
    muted = [m for m in guild.members if m.is_timed_out()]

    e = discord.Embed(
        title="🔒 Statut de Sécurité — Kozakura",
        color=discord.Color.green() if not lockdown_active.get(gid) else discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🔒 Lockdown", value="🟢 Inactif" if not lockdown_active.get(gid) else "🔴 ACTIF", inline=True)
    e.add_field(name="🛡️ Anti-bot", value="✅ Actif" if get_cfg(guild.id, "antibot_active") else "❌ Inactif", inline=True)
    e.add_field(name="👥 Membres totaux", value=str(guild.member_count), inline=True)
    e.add_field(name="🔍 Comptes suspects", value=f"**{len(suspects)}** membre(s)\n(<{ACCOUNT_MIN_AGE_DAYS}j ou sans avatar)", inline=True)
    e.add_field(name="🔇 Membres mutés", value=str(len(muted)), inline=True)
    e.add_field(name="💎 Boosts", value=str(guild.premium_subscription_count), inline=True)

    if suspects[:5]:
        e.add_field(name="⚠️ Top suspects",
            value="\n".join(f"• {m.mention} — {(datetime.utcnow()-m.created_at.replace(tzinfo=None)).days}j" for m in suspects[:5]),
            inline=False)

    e.set_footer(text="Kozakura Security System")
    await ctx.send(embed=e)

@bot.command(name="setsecuritylog")
@commands.has_permissions(administrator=True)
async def set_security_log(ctx, *, arg: str):
    """!setsecuritylog #salon — Définit le salon de logs sécurité"""
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "security_log", channel.id)
    await ctx.send(f"✅ Logs sécurité → {channel.mention}")

@bot.command(name="setminage")
@commands.has_permissions(administrator=True)
async def set_min_age(ctx, jours: int):
    """!setminage [jours] — Définit l'âge minimum d'un compte pour rejoindre"""
    global ACCOUNT_MIN_AGE_DAYS
    ACCOUNT_MIN_AGE_DAYS = max(0, jours)
    await ctx.send(f"✅ Âge minimum des comptes : **{ACCOUNT_MIN_AGE_DAYS} jours**")

# ── Shadowban ────────────────────────────────────────────────────────────────

@bot.command(name="shadowban")
@commands.has_permissions(administrator=True)
async def shadowban(ctx, member: discord.Member, *, raison: str = "Aucune raison"):
    """!shadowban @membre [raison] — Supprime silencieusement tous ses messages sans qu'il le sache"""
    gid = str(ctx.guild.id); uid = str(member.id)
    shadowban_db.setdefault(gid, {})[uid] = {"reason": raison, "by": str(ctx.author.id), "date": str(datetime.utcnow())}
    save_json("shadowban.json", shadowban_db)
    e = discord.Embed(
        title="👻 Shadowban Appliqué",
        description=f"{member.mention} est maintenant shadowban — ses messages seront supprimés silencieusement.",
        color=discord.Color.dark_gray(), timestamp=datetime.utcnow()
    )
    e.add_field(name="📋 Raison", value=raison)
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    e.set_footer(text="Kozakura Security • Shadowban (invisible pour le membre)")
    await ctx.send(embed=e)
    await log_security(ctx.guild, e)

@bot.command(name="unshadowban")
@commands.has_permissions(administrator=True)
async def unshadowban(ctx, member: discord.Member):
    """!unshadowban @membre — Lève le shadowban"""
    gid = str(ctx.guild.id); uid = str(member.id)
    if uid not in shadowban_db.get(gid, {}):
        return await ctx.send(f"❌ {member.mention} n'est pas shadowban.")
    shadowban_db[gid].pop(uid)
    save_json("shadowban.json", shadowban_db)
    await ctx.send(f"✅ Shadowban levé pour {member.mention}.")

# ── Watchlist ─────────────────────────────────────────────────────────────────

@bot.command(name="watchlist")
async def watchlist_add(ctx, member: discord.Member, *, raison: str = "Surveillance"):
    """!watchlist @membre [raison] — Surveille un membre (alerte staff à chaque message)"""
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Permission insuffisante.", delete_after=5)
    gid = str(ctx.guild.id); uid = str(member.id)
    watchlist_db.setdefault(gid, {})[uid] = {
        "reason": raison, "by": str(ctx.author.id), "by_name": ctx.author.display_name,
        "date": str(datetime.utcnow())
    }
    save_json("watchlist.json", watchlist_db)
    e = discord.Embed(
        title="👁️ Membre Ajouté à la Watchlist",
        description=f"{member.mention} est maintenant sous surveillance.",
        color=discord.Color.gold(), timestamp=datetime.utcnow()
    )
    e.add_field(name="📋 Raison", value=raison)
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    e.set_footer(text="Kozakura Security • Watchlist")
    await ctx.send(embed=e)
    await log_security(ctx.guild, e)

@bot.command(name="unwatch")
async def watchlist_remove(ctx, member: discord.Member):
    """!unwatch @membre — Retire un membre de la watchlist"""
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Permission insuffisante.", delete_after=5)
    gid = str(ctx.guild.id); uid = str(member.id)
    if uid not in watchlist_db.get(gid, {}):
        return await ctx.send(f"❌ {member.mention} n'est pas en watchlist.")
    watchlist_db[gid].pop(uid)
    save_json("watchlist.json", watchlist_db)
    await ctx.send(f"✅ {member.mention} retiré de la watchlist.")

@bot.command(name="watchers")
async def watchlist_view(ctx):
    """!watchers — Liste tous les membres sous surveillance"""
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Permission insuffisante.", delete_after=5)
    gid = str(ctx.guild.id)
    data = watchlist_db.get(gid, {})
    if not data:
        return await ctx.send("✅ Aucun membre en watchlist.")
    e = discord.Embed(title="👁️ Watchlist", color=discord.Color.gold(), timestamp=datetime.utcnow())
    for uid, wdata in list(data.items())[:15]:
        member = ctx.guild.get_member(int(uid))
        name = member.mention if member else f"`{uid}`"
        e.add_field(name=name, value=f"📋 {wdata.get('reason','?')}\n🛡️ {wdata.get('by_name','?')} — {wdata.get('date','?')[:10]}", inline=False)
    e.set_footer(text=f"{len(data)} membre(s) surveillé(s)")
    await ctx.send(embed=e)

# ── Report ────────────────────────────────────────────────────────────────────

@bot.command(name="report")
async def report(ctx, member: discord.Member, *, raison: str):
    """!report @membre [raison] — Signaler un membre au staff"""
    if member == ctx.author:
        return await ctx.send("❌ Tu ne peux pas te signaler toi-même.", delete_after=5)
    gid = str(ctx.guild.id)
    reports_db.setdefault(gid, []).append({
        "reporter": str(ctx.author.id), "reporter_name": ctx.author.display_name,
        "target":   str(member.id),     "target_name":   member.display_name,
        "reason":   raison,             "date":          str(datetime.utcnow()),
        "channel":  str(ctx.channel.id)
    })
    save_json("reports.json", reports_db)

    gestion_role = discord.utils.get(ctx.guild.roles, name=ROLE_GESTION_STAFF)
    mention_staff = gestion_role.mention if gestion_role else "**@Gestion**"

    e = discord.Embed(
        title="🚨 Signalement Membre",
        description=f"**{ctx.author.display_name}** a signalé **{member.display_name}**",
        color=discord.Color.red(), timestamp=datetime.utcnow()
    )
    e.add_field(name="👤 Signalé", value=f"{member.mention} (`{member.id}`)", inline=True)
    e.add_field(name="📢 Signaleur", value=ctx.author.mention, inline=True)
    e.add_field(name="📋 Raison", value=raison, inline=False)
    e.add_field(name="📌 Salon", value=ctx.channel.mention, inline=True)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text="Kozakura • Système de signalement")

    sec_ch = discord.utils.find(
        lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), ctx.guild.text_channels
    )
    if sec_ch:
        await sec_ch.send(content=f"🚨 {mention_staff} — Nouveau signalement !", embed=e)
    else:
        await log_security(ctx.guild, e)

    try: await ctx.message.delete()
    except Exception: pass
    await ctx.send(f"✅ Ton signalement a été transmis au staff. Merci.", delete_after=8)

@bot.command(name="reports")
@staff_only()
async def view_reports(ctx, member: discord.Member = None):
    """!reports [@membre] — Liste les signalements"""
    gid = str(ctx.guild.id)
    data = reports_db.get(gid, [])
    if member:
        data = [r for r in data if r["target"] == str(member.id)]
    if not data:
        return await ctx.send("✅ Aucun signalement.")
    e = discord.Embed(
        title=f"📋 Signalements{' de '+member.display_name if member else ''}",
        color=discord.Color.red(), timestamp=datetime.utcnow()
    )
    for r in data[-10:]:
        e.add_field(
            name=f"🚨 {r['target_name']} — {r['date'][:10]}",
            value=f"📋 {r['reason']}\n📢 Par : {r['reporter_name']}",
            inline=False
        )
    e.set_footer(text=f"{len(data)} signalement(s)")
    await ctx.send(embed=e)

# ── Forceban ─────────────────────────────────────────────────────────────────

@bot.command(name="forceban")
async def forceban(ctx, user_id: int, *, reason: str = "Aucune raison"):
    """!forceban [id] [raison] — Bannit un utilisateur par ID même s'il n'est pas sur le serveur"""
    if not has_sanction_role(ctx.author, ROLES_BAN):
        return await ctx.send("❌ Permission insuffisante.", delete_after=5)
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.ban(user, reason=reason, delete_message_days=1)
        e = discord.Embed(
            title="🔨 Forceban",
            description=f"**{user}** (`{user_id}`) banni par ID.",
            color=discord.Color.dark_red(), timestamp=datetime.utcnow()
        )
        e.add_field(name="📋 Raison", value=reason)
        e.add_field(name="🛡️ Par", value=ctx.author.mention)
        await ctx.send(embed=e)
        await log_security(ctx.guild, e)
    except Exception as ex:
        await ctx.send(f"❌ Erreur : `{ex}`")

# ── Setantispam ───────────────────────────────────────────────────────────────

@bot.command(name="setantispam")
@commands.has_permissions(administrator=True)
async def set_antispam(ctx, messages: int = None, secondes: int = None):
    """!setantispam [messages] [secondes] — Configure le seuil anti-spam (ex: !setantispam 5 5)"""
    global message_tracker
    if messages is None or secondes is None:
        return await ctx.send(
            f"⚙️ Config actuelle : **5 messages** en **5 secondes**\n"
            f"Usage : `!setantispam [nb_messages] [fenêtre_secondes]`"
        )
    set_cfg(ctx.guild.id, "antispam_msgs", max(3, min(messages, 20)))
    set_cfg(ctx.guild.id, "antispam_secs", max(2, min(secondes, 60)))
    await ctx.send(f"✅ Anti-spam : **{messages} messages** en **{secondes}s** → mute auto.")

# ── Freeze / Unfreeze ─────────────────────────────────────────────────────────
frozen_members = {}  # {member_id: {channel_id: overwrite_pair}}

@bot.command(name="freeze")
@commands.has_permissions(administrator=True)
async def freeze(ctx, member: discord.Member, *, raison: str = "Gel préventif"):
    """!freeze @membre [raison] — Coupe toutes les permissions sans bannir"""
    if member.id in frozen_members:
        return await ctx.send(f"❌ {member.mention} est déjà gelé.")

    frozen_members[member.id] = {}
    count = 0
    for channel in ctx.guild.channels:
        try:
            ow = channel.overwrites_for(member)
            frozen_members[member.id][channel.id] = ow.pair()
            await channel.set_permissions(member,
                send_messages=False, read_messages=False,
                connect=False, speak=False,
                reason=f"🧊 Freeze : {raison}")
            count += 1
        except Exception: pass

    # Déconnecter du vocal si présent
    if member.voice:
        try: await member.move_to(None)
        except Exception: pass

    e = discord.Embed(
        title="🧊 Membre Gelé",
        description=f"{member.mention} a été **gelé** — accès coupé partout.",
        color=discord.Color.blue(), timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📋 Raison", value=raison)
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    e.add_field(name="🔓 Pour libérer", value=f"`!unfreeze @{member.name}`")
    e.set_footer(text="Kozakura Security")
    await ctx.send(embed=e)
    await log_security(ctx.guild, e)
    await dm(member, "🧊 Tu as été gelé",
        f"**Serveur :** {ctx.guild.name}\n**Raison :** {raison}\nContacte le staff pour plus d'infos.")

@bot.command(name="unfreeze")
@commands.has_permissions(administrator=True)
async def unfreeze(ctx, member: discord.Member):
    """!unfreeze @membre — Restaure les permissions d'un membre gelé"""
    if member.id not in frozen_members:
        return await ctx.send(f"❌ {member.mention} n'est pas gelé.")

    backups = frozen_members.pop(member.id)
    count = 0
    for channel in ctx.guild.channels:
        try:
            if channel.id in backups:
                allow, deny = backups[channel.id]
                ow = discord.PermissionOverwrite.from_pair(allow, deny)
                if allow.value == 0 and deny.value == 0:
                    await channel.set_permissions(member, overwrite=None)
                else:
                    await channel.set_permissions(member, overwrite=ow)
            else:
                await channel.set_permissions(member, overwrite=None)
            count += 1
        except Exception: pass

    e = discord.Embed(
        title="🔥 Membre Libéré",
        description=f"{member.mention} a été **dégelé** — permissions restaurées.",
        color=discord.Color.green(), timestamp=datetime.utcnow()
    )
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    await ctx.send(embed=e)
    await log_security(ctx.guild, e)
    await dm(member, "🔥 Tu as été libéré",
        f"**Serveur :** {ctx.guild.name}\nTon accès a été restauré.", color=discord.Color.green())

# ── Honeypot ──────────────────────────────────────────────────────────────────
honeypot_channels = set()  # {channel_id}

@bot.command(name="sethoneypot")
@commands.has_permissions(administrator=True)
async def set_honeypot(ctx, *, arg: str = None):
    """!sethoneypot [#salon] — Crée ou définit un salon piège invisible"""
    if arg:
        channel = await resolve_channel(ctx, arg)
    else:
        # Créer un nouveau salon piège
        try:
            channel = await ctx.guild.create_text_channel(
                "〔🍯〕honeypot",
                reason="Salon piège honeypot",
                overwrites={
                    ctx.guild.default_role: discord.PermissionOverwrite(
                        read_messages=True, send_messages=True
                    ),
                    ctx.guild.me: discord.PermissionOverwrite(
                        read_messages=True, send_messages=True, manage_channels=True
                    )
                }
            )
            await ctx.send(f"✅ Salon honeypot créé : {channel.mention}\n⚠️ Rends-le **invisible** pour les humains (retire la permission `Voir le salon` pour @everyone et staff) mais laisse-le visible pour les bots/raiders.")
        except Exception as ex:
            return await ctx.send(f"❌ Erreur : {ex}")

    honeypot_channels.add(channel.id)
    await ctx.send(f"✅ Salon honeypot → {channel.mention}\nTout message dans ce salon déclenchera une alerte ! 🍯")

@bot.listen("on_message")
async def honeypot_listener(message):
    """Alerte si quelqu'un écrit dans le salon honeypot"""
    if message.author.bot or not message.guild: return
    if message.channel.id not in honeypot_channels: return

    member = message.author
    guild  = message.guild

    e = discord.Embed(
        title="🍯 HONEYPOT DÉCLENCHÉ !",
        description=f"**{member.mention}** a écrit dans le salon piège !",
        color=discord.Color.red(), timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Message", value=f"||{message.content[:300]}||")
    e.add_field(name="Membre", value=f"{member} (`{member.id}`)")
    e.add_field(name="Compte créé", value=member.created_at.strftime('%d/%m/%Y'))

    staff_role = discord.utils.get(guild.roles, name="Gestion")
    mention    = staff_role.mention if staff_role else ""
    await log_security(guild, e)

    sec_ch = discord.utils.find(lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels)
    if sec_ch:
        await sec_ch.send(f"🚨 {mention} **HONEYPOT DÉCLENCHÉ** — {member.mention}", embed=e)

    # Auto-ban si compte < 7 jours
    age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    if age < 7:
        try:
            await member.ban(reason="🍯 Honeypot — compte suspect", delete_message_days=7)
            await sec_ch.send(f"✅ {member} banni automatiquement (compte {age}j)")
        except Exception: pass

# ── Whois ─────────────────────────────────────────────────────────────────────
@bot.command(name="whois")
@staff_only()
async def whois(ctx, member: discord.Member):
    """!whois @membre — Enquête complète sur un membre"""
    gid = str(ctx.guild.id)
    uid = str(member.id)

    # Données collectées
    sanctions  = sanctions_db.get(gid, {}).get(uid, [])
    warnings   = warnings_db.get(gid, {}).get(uid, [])
    xp         = xp_db.get(gid, {}).get(uid, 0)
    trophees   = trophees_db.get(gid, {}).get(uid, {})
    msgs       = message_count_db.get(gid, {}).get(uid, 0)

    account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    server_age  = (datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0

    # Flags de risque
    risk_flags = []
    if account_age < 7:     risk_flags.append("🚨 Compte < 7 jours")
    if account_age < 30:    risk_flags.append("⚠️ Compte < 30 jours")
    if not member.avatar:   risk_flags.append("⚠️ Pas d'avatar")
    if len(sanctions) >= 5: risk_flags.append("🔴 5+ sanctions")
    if len(warnings) >= 3:  risk_flags.append("🟠 3+ avertissements")
    if member.id in frozen_members: risk_flags.append("🧊 Actuellement gelé")
    if member.is_timed_out(): risk_flags.append("🔇 Actuellement muté")

    risk_level = "🟢 Faible" if not risk_flags else ("🟠 Moyen" if len(risk_flags) < 3 else "🔴 Élevé")

    e = discord.Embed(
        title=f"🔍 Whois — {member.display_name}",
        color=discord.Color.green() if not risk_flags else (discord.Color.orange() if len(risk_flags) < 3 else discord.Color.red()),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)

    e.add_field(name="👤 Identité",
        value=f"**Pseudo :** {member.name}\n**Surnom :** {member.nick or 'Aucun'}\n**ID :** `{member.id}`",
        inline=False)
    e.add_field(name="📅 Dates",
        value=f"**Compte créé :** {member.created_at.strftime('%d/%m/%Y')} ({account_age}j)\n**A rejoint :** {member.joined_at.strftime('%d/%m/%Y') if member.joined_at else '?'} ({server_age}j)",
        inline=False)
    e.add_field(name="📊 Activité",
        value=f"**Messages :** ~{msgs}\n**XP :** {xp} (Niv.{get_level(xp)})\n**Vocal :** {trophees.get('voice_minutes',0)//60}h",
        inline=True)
    e.add_field(name="⚖️ Historique",
        value=f"**Sanctions :** {len(sanctions)}\n**Warns :** {len(warnings)}\n**Votes :** {trophees.get('votes',0)}",
        inline=True)
    e.add_field(name=f"🎯 Niveau de risque : {risk_level}",
        value="\n".join(risk_flags) if risk_flags else "✅ Aucun indicateur suspect",
        inline=False)

    # Rôles
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    if roles:
        e.add_field(name=f"🎭 Rôles ({len(roles)})", value=" ".join(roles[-8:]), inline=False)

    e.set_footer(text=f"Kozakura Security • {ctx.guild.name}")
    await ctx.send(embed=e)

# ── Backup & Restauration ─────────────────────────────────────────────────────
server_backup = {}  # {guild_id: backup_data}

@bot.command(name="backup")
@commands.has_permissions(administrator=True)
async def backup_server(ctx):
    """!backup — Sauvegarde la structure du serveur (salons, rôles, catégories)"""
    guild = ctx.guild
    msg   = await ctx.send("⏳ Backup en cours...")

    backup_data = {
        "name":       guild.name,
        "date":       str(datetime.utcnow()),
        "roles":      [],
        "categories": [],
        "channels":   []
    }

    # Sauvegarder les rôles
    for role in guild.roles:
        if role.name == "@everyone": continue
        backup_data["roles"].append({
            "name":        role.name,
            "color":       str(role.color),
            "permissions": role.permissions.value,
            "mentionable": role.mentionable,
            "hoist":       role.hoist,
            "position":    role.position
        })

    # Sauvegarder les catégories
    for cat in guild.categories:
        backup_data["categories"].append({
            "id":   cat.id,
            "name": cat.name,
            "position": cat.position
        })

    # Sauvegarder les salons
    for channel in guild.channels:
        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            ch_data = {
                "name":     channel.name,
                "type":     "text" if isinstance(channel, discord.TextChannel) else "voice",
                "category": channel.category.name if channel.category else None,
                "position": channel.position,
                "topic":    getattr(channel, "topic", None)
            }
            backup_data["channels"].append(ch_data)

    server_backup[str(guild.id)] = backup_data
    save_json("backup.json", server_backup)

    e = discord.Embed(
        title="✅ Backup Effectué",
        description=f"Sauvegarde de **{guild.name}** réussie !",
        color=discord.Color.green(), timestamp=datetime.utcnow()
    )
    e.add_field(name="🎭 Rôles", value=str(len(backup_data["roles"])))
    e.add_field(name="📁 Catégories", value=str(len(backup_data["categories"])))
    e.add_field(name="💬 Salons", value=str(len(backup_data["channels"])))
    e.add_field(name="📅 Date", value=backup_data["date"][:16])
    e.set_footer(text="Utilise !restorebackup pour restaurer")
    await msg.edit(content="", embed=e)
    await log_security(guild, e)

@bot.command(name="restorebackup")
@commands.has_permissions(administrator=True)
async def restore_backup(ctx):
    """!restorebackup — Restaure les rôles et catégories depuis le dernier backup"""
    gid    = str(ctx.guild.id)
    backup = server_backup.get(gid)
    if not backup:
        # Essayer de charger depuis le fichier
        loaded = load_json("backup.json", {})
        backup = loaded.get(gid)
    if not backup:
        return await ctx.send("❌ Aucun backup trouvé. Fais `!backup` d'abord.")

    msg = await ctx.send("⏳ Restauration en cours... (seulement les rôles manquants)")
    restored_roles = 0

    for role_data in backup["roles"]:
        existing = discord.utils.get(ctx.guild.roles, name=role_data["name"])
        if not existing:
            try:
                color_val = role_data.get("color", "#000000")
                color = discord.Color(int(color_val.replace("#",""), 16)) if color_val != "#000000" else discord.Color.default()
                await ctx.guild.create_role(
                    name=role_data["name"],
                    color=color,
                    permissions=discord.Permissions(role_data["permissions"]),
                    mentionable=role_data.get("mentionable", False),
                    hoist=role_data.get("hoist", False),
                    reason="♻️ Restauration backup"
                )
                restored_roles += 1
            except Exception: pass

    e = discord.Embed(
        title="♻️ Restauration Terminée",
        color=discord.Color.green(), timestamp=datetime.utcnow()
    )
    e.add_field(name="🎭 Rôles recréés", value=str(restored_roles))
    e.add_field(name="📅 Backup du", value=backup["date"][:16])
    e.set_footer(text="Les salons ne sont pas recréés automatiquement pour éviter les doublons")
    await msg.edit(content="", embed=e)

# ── Quarantaine automatique ───────────────────────────────────────────────────
@bot.command(name="quarantine")
@commands.has_permissions(administrator=True)
async def quarantine_cmd(ctx, member: discord.Member, *, raison: str = "Compte suspect"):
    """!quarantine @membre — Met un membre en quarantaine (accès limité)"""
    qr_role_id = get_cfg(ctx.guild.id, "quarantine_role")
    if not qr_role_id:
        return await ctx.send("❌ Aucun rôle quarantaine configuré. Utilise `!setquarantinerole @role`")

    qr_role = ctx.guild.get_role(int(qr_role_id))
    if not qr_role:
        return await ctx.send("❌ Rôle quarantaine introuvable.")

    try:
        # Retirer tous les rôles sauf @everyone
        roles_to_remove = [r for r in member.roles if r != ctx.guild.default_role and r != qr_role]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f"🔒 Quarantaine : {raison}")
        await member.add_roles(qr_role, reason=f"🔒 Quarantaine : {raison}")
    except discord.Forbidden:
        return await ctx.send("❌ Permission insuffisante.")

    e = discord.Embed(
        title="🔒 Membre en Quarantaine",
        description=f"{member.mention} a été mis en quarantaine.",
        color=discord.Color.orange(), timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📋 Raison", value=raison)
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    e.set_footer(text="Kozakura Security")
    await ctx.send(embed=e)
    await log_security(ctx.guild, e)
    await dm(member, "🔒 Tu as été mis en quarantaine",
        f"**Serveur :** {ctx.guild.name}\n**Raison :** {raison}\nContacte le staff pour plus d'infos.",
        color=discord.Color.orange())

# ── Détection usurpation d'identité staff ─────────────────────────────────────
STAFF_ROLES_DETECT = ["B#tch", "Univers", "Queen", "Baby admin", "Développer",
                      "[+] Kozakura gestion", "Gestion", "Support"]

@bot.listen("on_member_update")
async def detect_impersonation(before, after):
    """Détecte si un membre change de pseudo pour ressembler au staff"""
    if before.display_name == after.display_name: return
    guild = after.guild

    # Récupérer les noms du staff
    staff_names = []
    for role_name in STAFF_ROLES_DETECT:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            for m in role.members:
                staff_names.append(m.display_name.lower())

    new_name = after.display_name.lower()

    for staff_name in staff_names:
        # Vérifier similarité (même nom ou très proche)
        if (new_name == staff_name or
            new_name in staff_name or
            staff_name in new_name or
            (len(staff_name) > 4 and staff_name[:4] in new_name)):

            # Vérifier que ce n'est pas le membre lui-même
            is_staff = any(r.name in STAFF_ROLES_DETECT for r in after.roles)
            if is_staff: continue

            e = discord.Embed(
                title="⚠️ Usurpation d'Identité Détectée",
                description=f"{after.mention} a changé son pseudo pour ressembler à un membre staff !",
                color=discord.Color.red(), timestamp=datetime.utcnow()
            )
            e.set_thumbnail(url=after.display_avatar.url)
            e.add_field(name="Avant", value=before.display_name)
            e.add_field(name="Après", value=after.display_name)
            e.add_field(name="Ressemble à", value=staff_name)
            e.set_footer(text="Kozakura Security • Action manuelle requise")

            staff_role = discord.utils.get(guild.roles, name="Gestion")
            await log_security(guild, e)
            sec_ch = discord.utils.find(lambda c: any(n in c.name.lower() for n in SECURITY_LOG_NAMES), guild.text_channels)
            if sec_ch:
                mention = staff_role.mention if staff_role else ""
                await sec_ch.send(f"🚨 {mention} **Usurpation d'identité !**", embed=e)
            break

# ══════════════════════════════════════════════════════════════════════════════
# 🎉 SYSTÈME DE GIVEAWAY
# ══════════════════════════════════════════════════════════════════════════════

giveaways_db = {}  # {message_id: {...}}
GIVEAWAY_EMOJI = "🎉"

def parse_duration(duration_str):
    """Convertit '10s', '5min', '2h', '1j' en secondes"""
    duration_str = duration_str.lower().strip()
    units = {"s": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "j": 86400, "d": 86400}
    for unit, mult in sorted(units.items(), key=lambda x: -len(x[0])):
        if duration_str.endswith(unit):
            try:
                return int(duration_str[:-len(unit)]) * mult
            except Exception: pass
    try:
        return int(duration_str)
    except Exception:
        return None

def format_duration(seconds):
    """Formate les secondes en texte lisible"""
    if seconds >= 86400:
        return f"{seconds // 86400}j {(seconds % 86400) // 3600}h"
    elif seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}min"
    elif seconds >= 60:
        return f"{seconds // 60}min {seconds % 60}s"
    else:
        return f"{seconds}s"

async def end_giveaway(message_id, channel_id, guild_id):
    """Termine un giveaway et tire le/les gagnant(s) avec vérification des conditions"""
    await asyncio.sleep(0)

    if message_id not in giveaways_db:
        return

    data    = giveaways_db[message_id]
    guild   = bot.get_guild(guild_id)
    channel = bot.get_channel(channel_id)
    if not guild or not channel:
        return

    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        return

    # Conditions requises
    min_messages = data.get("min_messages", 0)
    require_vocal = data.get("require_vocal", False)

    # Récupérer les participants (réaction 🎉)
    raw_participants = []
    for reaction in msg.reactions:
        if str(reaction.emoji) == GIVEAWAY_EMOJI:
            async for user in reaction.users():
                if not user.bot:
                    raw_participants.append(user)
            break

    # Filtrer selon les conditions
    import random
    valid_participants = []
    disqualified = []

    gid = str(guild.id)
    for user in raw_participants:
        member = guild.get_member(user.id)
        if not member:
            disqualified.append((user, "plus membre du serveur"))
            continue

        uid = str(user.id)

        # Condition messages minimum
        if min_messages > 0:
            user_msgs = xp_db.get(gid, {}).get(uid, 0)
            # On estime les messages via XP (1 msg = XP_PER_MSG XP)
            estimated_msgs = user_msgs // XP_PER_MSG
            if estimated_msgs < min_messages:
                disqualified.append((user, f"messages insuffisants ({estimated_msgs}/{min_messages})"))
                continue

        # Condition vocal actif
        if require_vocal:
            in_voice = any(
                member in vc.members
                for vc in guild.voice_channels
            )
            if not in_voice:
                disqualified.append((user, "pas en vocal"))
                continue

        valid_participants.append(user)

    winners_count = data.get("winners", 1)
    prize         = data["prize"]
    host          = guild.get_member(data["host_id"])

    e = discord.Embed(
        title=f"🎉 GIVEAWAY TERMINÉ — {prize}",
        color=discord.Color.dark_grey(),
        timestamp=datetime.utcnow()
    )

    winners = []
    if not valid_participants:
        e.description = "😔 Aucun participant valide — pas de gagnant."
        e.color = discord.Color.dark_red()
        winners_mentions = "Aucun"
    else:
        count   = min(winners_count, len(valid_participants))
        winners = random.sample(valid_participants, count)
        winners_mentions = " ".join(w.mention for w in winners)
        e.description = f"🏆 **Gagnant(s) :** {winners_mentions}\n\n🎁 **Prix :** {prize}"
        e.color = discord.Color.gold()

    if host:
        e.add_field(name="👑 Organisé par", value=host.mention)
    e.add_field(name="👥 Participants valides", value=f"{len(valid_participants)}/{len(raw_participants)}")

    # Afficher les conditions
    conds = []
    if min_messages > 0: conds.append(f"📝 Min. {min_messages} messages")
    if require_vocal:     conds.append("🎙️ Être en vocal")
    if conds:
        e.add_field(name="📋 Conditions", value="\n".join(conds), inline=False)

    if disqualified:
        e.add_field(
            name=f"❌ Disqualifiés ({len(disqualified)})",
            value="\n".join(f"• {u.mention} — {r}" for u, r in disqualified[:5]) +
                  (f"\n*...et {len(disqualified)-5} autres*" if len(disqualified) > 5 else ""),
            inline=False
        )

    e.set_footer(text="Giveaway terminé")
    await msg.edit(embed=e)

    if valid_participants:
        host_str = host.mention if host else "l'organisateur"
        await channel.send(
            f"🎉 Félicitations {winners_mentions} ! Tu as gagné **{prize}** !\n"
            f"Contacte {host_str} pour récupérer ton prix."
        )

    giveaways_db[message_id]["ended"]       = True
    giveaways_db[message_id]["winners_ids"] = [w.id for w in winners]


@bot.command()
async def giveaway(ctx, duration: str, winners: str, *, prize: str):
    """
    !giveaway [durée] [nb]w [prix]
    Options conditions (à ajouter à la fin du prix) :
      --msgs [n]    → Minimum N messages requis
      --vocal       → Être en vocal au moment du tirage

    Exemples :
      !giveaway 24h 1w Nitro Classic
      !giveaway 30min 2w PSN 20€ --msgs 50
      !giveaway 2h 1w Nitro --vocal
      !giveaway 7j 1w Abonnement --msgs 100 --vocal
    """
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ Tu n'as pas la permission de créer un giveaway.", delete_after=5)

    seconds = parse_duration(duration)
    if not seconds or seconds <= 0:
        return await ctx.send("❌ Durée invalide. Exemples : `10s`, `30min`, `2h`, `7j`")

    winners_str = winners.lower().replace("w", "").replace("x", "").strip()
    try:
        winners_count = max(1, int(winners_str))
    except Exception:
        return await ctx.send("❌ Nombre de gagnants invalide. Exemples : `1w`, `2w`")

    # Parser les conditions dans le prix
    min_messages  = 0
    require_vocal = False
    prize_clean   = prize

    import re as _re
    msgs_match = _re.search(r'--msgs?\s+(\d+)', prize)
    if msgs_match:
        min_messages = int(msgs_match.group(1))
        prize_clean  = prize_clean.replace(msgs_match.group(0), "").strip()

    if "--vocal" in prize_clean.lower():
        require_vocal = True
        prize_clean   = _re.sub(r'--vocal', '', prize_clean, flags=_re.IGNORECASE).strip()

    end_time = datetime.utcnow() + timedelta(seconds=seconds)

    # Construire la description avec conditions
    conds_lines = []
    if min_messages > 0: conds_lines.append(f"📝 Minimum **{min_messages} messages** sur le serveur")
    if require_vocal:    conds_lines.append(f"🎙️ Être **en vocal** au moment du tirage")
    conds_text = ("\n\n**📋 Conditions :**\n" + "\n".join(conds_lines)) if conds_lines else ""

    e = discord.Embed(
        title=f"🎉 GIVEAWAY — {prize_clean}",
        description=(
            f"Réagis avec {GIVEAWAY_EMOJI} pour participer !{conds_text}\n\n"
            f"🎁 **Prix :** {prize_clean}\n"
            f"🏆 **Gagnants :** {winners_count}\n"
            f"⏰ **Fin dans :** {format_duration(seconds)}\n"
            f"📅 **Se termine le :** <t:{int(end_time.timestamp())}:F>"
        ),
        color=discord.Color.blurple(),
        timestamp=end_time
    )
    e.set_footer(text=f"Organisé par {ctx.author.display_name} • Se termine le")
    if ctx.guild.icon:
        e.set_thumbnail(url=ctx.guild.icon.url)

    try: await ctx.message.delete()
    except Exception: pass

    msg = await ctx.send(embed=e)
    await msg.add_reaction(GIVEAWAY_EMOJI)

    giveaways_db[msg.id] = {
        "prize":         prize_clean,
        "winners":       winners_count,
        "host_id":       ctx.author.id,
        "channel_id":    ctx.channel.id,
        "guild_id":      ctx.guild.id,
        "end_time":      end_time.timestamp(),
        "ended":         False,
        "min_messages":  min_messages,
        "require_vocal": require_vocal
    }

    asyncio.create_task(_giveaway_timer(msg.id, ctx.channel.id, ctx.guild.id, seconds))

async def _giveaway_timer(message_id, channel_id, guild_id, seconds):
    await asyncio.sleep(seconds)
    await end_giveaway(message_id, channel_id, guild_id)

@bot.command()
async def greroll(ctx, message_id: int = None):
    """!greroll [message_id] — Nouveau tirage"""
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ Tu n'as pas la permission.", delete_after=5)

    if message_id is None:
        for mid, data in reversed(list(giveaways_db.items())):
            if data.get("ended") and data["channel_id"] == ctx.channel.id:
                message_id = mid
                break

    if message_id not in giveaways_db:
        return await ctx.send("❌ Giveaway introuvable.")

    data    = giveaways_db[message_id]
    channel = bot.get_channel(data["channel_id"])
    guild   = bot.get_guild(data["guild_id"])

    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        return await ctx.send("❌ Message introuvable.")

    import random
    min_messages  = data.get("min_messages", 0)
    require_vocal = data.get("require_vocal", False)
    gid = str(guild.id)

    valid = []
    for reaction in msg.reactions:
        if str(reaction.emoji) == GIVEAWAY_EMOJI:
            async for user in reaction.users():
                if user.bot: continue
                member = guild.get_member(user.id)
                if not member: continue
                uid = str(user.id)
                if min_messages > 0:
                    if (xp_db.get(gid, {}).get(uid, 0) // XP_PER_MSG) < min_messages:
                        continue
                if require_vocal:
                    if not any(member in vc.members for vc in guild.voice_channels):
                        continue
                valid.append(user)
            break

    if not valid:
        return await ctx.send("😔 Aucun participant valide pour reroll.")

    winner = random.choice(valid)
    await ctx.send(f"🎉 Nouveau gagnant : {winner.mention} ! Félicitations pour **{data['prize']}** !")

@bot.command()
async def gend(ctx, message_id: int):
    """!gend [message_id] — Termine un giveaway immédiatement"""
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.manage_guild:
        return await ctx.send("❌ Tu n'as pas la permission.", delete_after=5)
    if message_id not in giveaways_db:
        return await ctx.send("❌ Giveaway introuvable.")
    data = giveaways_db[message_id]
    await end_giveaway(message_id, data["channel_id"], data["guild_id"])
    await ctx.send("✅ Giveaway terminé.", delete_after=5)

@bot.command()
async def glist(ctx):
    """!glist — Liste les giveaways actifs"""
    actifs = [(mid, d) for mid, d in giveaways_db.items()
              if not d.get("ended") and d["guild_id"] == ctx.guild.id]
    e = discord.Embed(title="🎉 Giveaways Actifs", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    if not actifs:
        e.description = "Aucun giveaway en cours."
    else:
        for mid, d in actifs:
            ch        = bot.get_channel(d["channel_id"])
            remaining = max(0, int(d["end_time"] - datetime.utcnow().timestamp()))
            conds = []
            if d.get("min_messages"): conds.append(f"📝 {d['min_messages']} msgs min")
            if d.get("require_vocal"): conds.append("🎙️ Vocal requis")
            e.add_field(
                name=f"🎁 {d['prize']}",
                value=(
                    f"Salon : {ch.mention if ch else 'inconnu'}\n"
                    f"Gagnants : {d['winners']}\n"
                    f"Temps restant : {format_duration(remaining)}\n"
                    + (f"Conditions : {' • '.join(conds)}\n" if conds else "") +
                    f"ID : `{mid}`"
                ),
                inline=False
            )
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🛡️ PROTECTION ANTI-BOT
# ══════════════════════════════════════════════════════════════════════════════

# Charger la whitelist depuis le fichier
_wl_data = load_json("bot_whitelist.json", [])
BOT_WHITELIST = list(_wl_data) if isinstance(_wl_data, list) else []

# Tracker anti-raid bots
bot_raid_tracker = []

# L'event on_member_join gère déjà les bots — on y ajoute la logique anti-bot
# via une fonction séparée appelée depuis on_member_join

async def check_antibot(member):
    """Vérifie et kick les bots non autorisés"""
    if not member.bot:
        return
    guild = member.guild

    # Protection active ?
    if not get_cfg(guild.id, "antibot_active", False):
        return

    # Bot dans la whitelist ?
    if member.id in BOT_WHITELIST:
        return

    # Anti-raid bots : plusieurs bots en peu de temps
    now = time.time()
    bot_raid_tracker.append(now)
    bot_raid_tracker[:] = [t for t in bot_raid_tracker if now - t < 30]

    try:
        await member.kick(reason="🛡️ Anti-bot : bot non autorisé")
    except Exception:
        pass  # Ignoré intentionnellement

    e = discord.Embed(
        title="🛡️ Bot Non Autorisé Kické",
        description=f"**{member.name}** (`{member.id}`) a été expulsé automatiquement.",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="ID Bot",   value=f"`{member.id}`")
    e.add_field(name="Nom",      value=member.name)
    e.add_field(name="Whitelist", value=f"Non autorisé\nUtilise `!addbotwhitelist {member.id}` pour l'autoriser")
    e.set_thumbnail(url=member.display_avatar.url)

    # Alerte + lockdown si raid de bots
    if len(bot_raid_tracker) >= 3:
        e.add_field(name="⚠️ ALERTE RAID BOTS",
            value=f"**{len(bot_raid_tracker)} bots** ont tenté de rejoindre en 30 secondes !",
            inline=False)
        e.color = discord.Color.dark_red()
        await trigger_lockdown(
            guild,
            raison=f"Raid de bots — {len(bot_raid_tracker)} bots en 30 secondes",
            triggered_by="🤖 Anti-Bot automatique"
        )

    await log(guild, e)

    # Notif dans le salon de logs
    log_ch_id = get_cfg(guild.id, "log_channel")
    if log_ch_id:
        ch = guild.get_channel(int(log_ch_id))
        if ch:
            await ch.send(
                f"🚨 **Bot non autorisé expulsé :** `{member.name}` (`{member.id}`)\n"
                f"Pour l'autoriser : `!addbotwhitelist {member.id}`"
            )

@bot.command()
@commands.has_permissions(administrator=True)
async def setantibotprotection(ctx, state: str = "on"):
    """!setantibotprotection [on/off] — Active/désactive la protection anti-bot"""
    active = state.lower() in ["on", "oui", "1", "true"]
    set_cfg(ctx.guild.id, "antibot_active", active)
    status = "✅ activée" if active else "❌ désactivée"
    await ctx.send(f"🛡️ Protection anti-bot **{status}**.\n"
        "Les bots non whitelistés seront automatiquement expulsés à leur arrivée.")

@bot.command()
@commands.has_permissions(administrator=True)
async def addbotwhitelist(ctx, bot_id: int):
    """!addbotwhitelist [id] — Ajoute un bot à la whitelist"""
    if bot_id not in BOT_WHITELIST:
        BOT_WHITELIST.append(bot_id)
        save_json("bot_whitelist.json", BOT_WHITELIST)
    try:
        u = await bot.fetch_user(bot_id)
        name = u.name
    except Exception:
        name = str(bot_id)
    await ctx.send(f"✅ **{name}** (`{bot_id}`) autorisé.")

@bot.command()
@commands.has_permissions(administrator=True)
async def removebotwhitelist(ctx, bot_id: int):
    """!removebotwhitelist [id] — Retire un bot de la whitelist"""
    if bot_id in BOT_WHITELIST:
        BOT_WHITELIST.remove(bot_id)
        save_json("bot_whitelist.json", BOT_WHITELIST)
    await ctx.send(f"✅ Bot `{bot_id}` retiré de la whitelist.")

@bot.command()
@commands.has_permissions(administrator=True)
async def botwhitelist(ctx):
    """!botwhitelist — Affiche tous les bots autorisés"""
    e = discord.Embed(
        title="🤖 Bots Autorisés",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    active = get_cfg(ctx.guild.id, "antibot_active", False)
    e.description = f"Protection anti-bot : {'✅ Active' if active else '❌ Inactive'}\n\n"
    if not BOT_WHITELIST:
        e.description += "Aucun bot en whitelist."
    else:
        lines = []
        for bid in BOT_WHITELIST:
            try:
                u = await bot.fetch_user(bid)
                lines.append(f"• **{u.name}** (`{bid}`)")
            except Exception:
                lines.append(f"• `{bid}`")
        e.description += "\n".join(lines)
    e.set_footer(text="!addbotwhitelist [id] pour ajouter | !setantibotprotection on/off")
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# 🔨 MASSBAN
# ══════════════════════════════════════════════════════════════════════════════

massban_queue = {}  # {guild_id: {"members": [...], "reason": str, "by": int}}

@bot.command()
async def massban(ctx, members: commands.Greedy[discord.Member], *, reason: str = "Mass ban"):
    """
    !massban @user1 @user2 @user3 [raison]
    Prépare un mass ban — à confirmer avec !massbanconfirm
    Réservé aux rôles Développer et kozakura C.O.D uniquement.
    """
    if not has_sanction_role(ctx.author, ROLES_MASSBAN):
        return await ctx.send("❌ Seuls les **kozakura C.O.D** et **Développer** peuvent utiliser le mass ban.", delete_after=5)

    if not members:
        return await ctx.send(
            "❌ Mentionne au moins un membre.\n"
            "Usage : `!massban @user1 @user2 raison`")

    gid = str(ctx.guild.id)
    massban_queue[gid] = {
        "members": [m.id for m in members],
        "reason":  reason,
        "by":      ctx.author.id
    }

    e = discord.Embed(
        title="⚠️ Mass Ban Préparé",
        description=f"**{len(members)} membre(s)** vont être bannis.\nConfirme avec `!massbanconfirm` ou annule avec `!massbancancel`",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="📋 Raison", value=reason, inline=False)
    e.add_field(
        name="👥 Membres ciblés",
        value="\n".join(f"• {m.mention} (`{m.id}`)" for m in members[:20]) +
              (f"\n*...et {len(members)-20} autres*" if len(members) > 20 else ""),
        inline=False
    )
    e.add_field(name="🛡️ Préparé par", value=ctx.author.mention)
    e.set_footer(text="⚠️ Cette action est irréversible — utilise !massbanconfirm pour confirmer")
    await ctx.send(embed=e)

@bot.command()
async def massbanconfirm(ctx):
    """!massbanconfirm — Exécute le mass ban préparé"""
    if not has_sanction_role(ctx.author, ROLES_MASSBAN):
        return await ctx.send("❌ Seuls les **kozakura C.O.D** et **Développer** peuvent confirmer le mass ban.", delete_after=5)

    gid = str(ctx.guild.id)
    if gid not in massban_queue:
        return await ctx.send("❌ Aucun mass ban en attente. Utilise d'abord `!massban @user1 @user2 raison`.")

    data    = massban_queue[gid]
    reason  = data["reason"]
    ids     = data["members"]
    prep_by = ctx.guild.get_member(data["by"])

    # Vérif que c'est bien le même modérateur (ou un admin)
    if ctx.author.id != data["by"] and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Seul le modérateur qui a préparé le mass ban peut le confirmer.")

    msg = await ctx.send(f"⏳ Mass ban en cours... **0/{len(ids)}** bannis")

    success, failed = [], []
    for i, uid in enumerate(ids):
        try:
            member = ctx.guild.get_member(uid)
            if member:
                await dm(member, "🔨 Tu as été banni",
                    f"**Serveur :** {ctx.guild.name}\n**Raison :** {reason}",
                    color=discord.Color.dark_red())
                await member.ban(reason=f"[MassBan] {reason}", delete_message_days=7)
            else:
                user = await bot.fetch_user(uid)
                await ctx.guild.ban(user, reason=f"[MassBan] {reason}")
            success.append(uid)
        except Exception as ex:
            failed.append(uid)

        # Mise à jour progress tous les 3 bans
        if (i + 1) % 3 == 0:
            try:
                await msg.edit(content=f"⏳ Mass ban en cours... **{i+1}/{len(ids)}** bannis")
            except Exception: pass
        await asyncio.sleep(0.5)  # Évite le rate limit

    del massban_queue[gid]

    e = discord.Embed(
        title="🔨 Mass Ban Exécuté",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="✅ Bannis",   value=str(len(success)))
    e.add_field(name="❌ Échoués", value=str(len(failed)))
    e.add_field(name="📋 Raison",  value=reason, inline=False)
    e.add_field(name="🛡️ Par",     value=ctx.author.mention)
    if failed:
        fail_mentions = ", ".join(f"`{i}`" for i in failed[:10])
        e.add_field(name="⚠️ IDs échoués", value=fail_mentions, inline=False)
    e.set_footer(text=ctx.guild.name)

    await msg.edit(content="", embed=e)

    # Log dans sanction
    await log(ctx.guild, e)

@bot.command()
async def massbancancel(ctx):
    """!massbancancel — Annule le mass ban en attente"""
    gid = str(ctx.guild.id)
    if gid not in massban_queue:
        return await ctx.send("❌ Aucun mass ban en attente.")
    del massban_queue[gid]
    await ctx.send("✅ Mass ban annulé.")


# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="addrole")
@staff_only()
async def addrole(ctx, member: discord.Member, *, arg: str):
    """!addrole @membre @role — Donne un rôle à un membre"""
    role = await resolve_role(ctx, arg)
    if not role:
        return await ctx.send("❌ Rôle introuvable. Utilise `!addrole @membre @role` ou le nom exact.")

    # Rôles protégés : uniquement la couronne peut les attribuer
    if role.name in PROTECTED_ROLES and not has_sanction_role(ctx.author, [ROLE_CROWN]):
        return await ctx.send(f"👑 Seul le rôle **{ROLE_CROWN}** peut attribuer le rôle **{role.name}**.", delete_after=8)

    if role in member.roles:
        return await ctx.send(f"❌ {member.mention} possède déjà le rôle {role.mention}.")

    try:
        await member.add_roles(role, reason=f"Ajouté par {ctx.author}")
    except discord.Forbidden:
        return await ctx.send("❌ Je n'ai pas la permission d'attribuer ce rôle. Vérifie ma hiérarchie.")

    e = discord.Embed(
        title="✅ Rôle Ajouté",
        description=f"{role.mention} a été donné à {member.mention}",
        color=role.color if role.color.value else discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Membre",     value=f"{member} (`{member.id}`)")
    e.add_field(name="Rôle",       value=role.mention)
    e.add_field(name="Par",        value=ctx.author.mention)
    e.set_footer(text=ctx.guild.name)
    await ctx.send(embed=e)
    await log(ctx.guild, e)

@bot.command(name="delrole")
@staff_only()
async def delrole(ctx, member: discord.Member, *, arg: str):
    """!delrole @membre @role — Retire un rôle à un membre"""
    role = await resolve_role(ctx, arg)
    if not role:
        return await ctx.send("❌ Rôle introuvable. Utilise `!delrole @membre @role` ou le nom exact.")

    # Rôles protégés : uniquement la couronne peut les retirer
    if role.name in PROTECTED_ROLES and not has_sanction_role(ctx.author, [ROLE_CROWN]):
        return await ctx.send(f"👑 Seul le rôle **{ROLE_CROWN}** peut retirer le rôle **{role.name}**.", delete_after=8)

    if role not in member.roles:
        return await ctx.send(f"❌ {member.mention} n'a pas le rôle {role.mention}.")

    try:
        await member.remove_roles(role, reason=f"Retiré par {ctx.author}")
    except discord.Forbidden:
        return await ctx.send("❌ Je n'ai pas la permission de retirer ce rôle. Vérifie ma hiérarchie.")

    e = discord.Embed(
        title="🗑️ Rôle Retiré",
        description=f"{role.mention} a été retiré de {member.mention}",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Membre", value=f"{member} (`{member.id}`)")
    e.add_field(name="Rôle",   value=role.mention)
    e.add_field(name="Par",    value=ctx.author.mention)
    e.set_footer(text=ctx.guild.name)
    await ctx.send(embed=e)
    await log(ctx.guild, e)

@bot.command(name="mv")
async def mv(ctx, member: discord.Member, *, channel_arg: str = None):
    """
    !mv @membre [salon vocal]  — Déplace un membre dans un salon vocal
    !mv @membre                — Déplace le membre dans ton salon vocal actuel
    """
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.move_members:
        return await ctx.send("❌ Tu n'as pas la permission de déplacer des membres.", delete_after=5)

    # Vérifier que le membre est en vocal
    if not member.voice or not member.voice.channel:
        return await ctx.send(f"❌ {member.mention} n'est pas dans un salon vocal.")

    # Trouver le salon cible
    if channel_arg:
        # Chercher par nom ou ID
        target_channel = discord.utils.find(
            lambda c: channel_arg.lower() in c.name.lower() or str(c.id) == channel_arg.strip("<#>"),
            ctx.guild.voice_channels
        )
        if not target_channel:
            # Lister les salons disponibles
            salons = "\n".join(f"• `{c.name}`" for c in ctx.guild.voice_channels)
            return await ctx.send(f"❌ Salon vocal introuvable.\n**Salons disponibles :**\n{salons}")
    else:
        # Déplacer dans le vocal de l'auteur
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Précise un salon vocal ou rejoins-en un toi-même.\nUsage : `!mv @membre nom-du-salon`")
        target_channel = ctx.author.voice.channel

    from_channel = member.voice.channel

    # Même salon ?
    if from_channel == target_channel:
        return await ctx.send(f"❌ {member.mention} est déjà dans **{target_channel.name}**.")

    try:
        await member.move_to(target_channel, reason=f"Déplacé par {ctx.author}")
    except discord.Forbidden:
        return await ctx.send("❌ Je n'ai pas la permission de déplacer ce membre.")

    e = discord.Embed(
        title="🔀 Membre Déplacé",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre",   value=member.mention)
    e.add_field(name="📤 Depuis",   value=f"🔊 {from_channel.name}")
    e.add_field(name="📥 Vers",     value=f"🔊 {target_channel.name}")
    e.add_field(name="🛡️ Par",      value=ctx.author.mention)
    e.set_footer(text=ctx.guild.name)
    await ctx.send(embed=e, delete_after=10)
    await log(ctx.guild, e)


# Tracker pour le mode dog {follower_id: target_id}
dog_followers = {}

@bot.command(name="dog")
async def dog(ctx, member: discord.Member):
    """!dog @membre — Force le membre à suivre tes déplacements vocaux + emoji 🐕"""
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.move_members:
        return await ctx.send("❌ Tu n'as pas la permission.", delete_after=5)

    if not member.voice or not member.voice.channel:
        return await ctx.send(f"❌ {member.mention} n'est pas en vocal.")

    # Activer le mode dog
    dog_followers[str(member.id)] = str(ctx.author.id)

    # Ajouter 🐕 au pseudo si pas déjà présent
    old_nick = member.display_name
    if "🐕" not in old_nick:
        try:
            await member.edit(nick=f"🐕 {old_nick[:30]}", reason=f"Dog par {ctx.author}")
        except discord.Forbidden:
            pass  # Pas de permission pour changer le pseudo

    # Déplacer immédiatement dans le salon de l'auteur si en vocal
    if ctx.author.voice and ctx.author.voice.channel:
        try:
            await member.move_to(ctx.author.voice.channel, reason=f"Dog par {ctx.author}")
        except Exception: pass

    e = discord.Embed(
        title="🐕 Mode Dog Activé !",
        description=f"{member.mention} va maintenant **suivre** {ctx.author.mention} en vocal.",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🐾 Comportement", value="Se déplace automatiquement dans chaque salon vocal de son maître")
    e.add_field(name="🔓 Pour libérer", value=f"`!undog @{member.name}`")
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e, delete_after=30)

@bot.command(name="undog")
async def undog(ctx, member: discord.Member):
    """!undog @membre — Libère un membre du mode dog"""
    if not has_sanction_role(ctx.author, ROLES_BAN) and not ctx.author.guild_permissions.move_members:
        return await ctx.send("❌ Tu n'as pas la permission.", delete_after=5)

    uid = str(member.id)
    if uid in dog_followers:
        del dog_followers[uid]

    # Retirer le 🐕 du pseudo
    if "🐕" in member.display_name:
        try:
            new_nick = member.display_name.replace("🐕 ", "").replace("🐕", "").strip()
            await member.edit(nick=new_nick or None, reason=f"Undog par {ctx.author}")
        except discord.Forbidden:
            pass

    e = discord.Embed(
        title="🔓 Mode Dog Désactivé",
        description=f"{member.mention} est libre ! Le mode dog a été retiré.",
        color=discord.Color.green(), timestamp=datetime.utcnow()
    )
    await ctx.send(embed=e, delete_after=15)


@bot.command(name="unmuteall")
async def unmute_all(ctx):
    """!unmuteall — Démute tous les membres actuellement mutes (timeout)"""
    if not has_sanction_role(ctx.author, ROLES_MUTE):
        return await ctx.send("❌ Tu n'as pas la permission.", delete_after=5)

    count = 0
    failed = 0
    msg = await ctx.send("⏳ Démute en cours...")

    for member in ctx.guild.members:
        if member.is_timed_out():
            try:
                await member.timeout(None, reason=f"Unmute global par {ctx.author}")
                count += 1
            except Exception:
                failed += 1

    e = discord.Embed(
        title="🔊 Unmute Global",
        description=f"**{count}** membre(s) démutés" + (f"\n❌ {failed} échec(s)" if failed else ""),
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    await msg.edit(content="", embed=e)

@bot.command(name="pic")
async def pic(ctx, member: discord.Member = None):
    """!pic [@membre] — Affiche la photo de profil d'un membre"""
    member = member or ctx.author
    e = discord.Embed(
        title=f"🖼️ Photo de profil — {member.display_name}",
        color=member.color if member.color.value else discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    # Avatar serveur si disponible
    guild_avatar = member.guild_avatar
    if guild_avatar:
        e.set_image(url=guild_avatar.url)
        e.add_field(name="Avatar du serveur", value=f"[Télécharger]({guild_avatar.url})")
    else:
        e.set_image(url=member.display_avatar.url)
        e.add_field(name="Avatar global", value=f"[Télécharger]({member.display_avatar.url})")
    e.set_footer(text=f"ID : {member.id}")
    await ctx.send(embed=e)

@bot.command(name="banner")
async def banner(ctx, member: discord.Member = None):
    """!banner [@membre] — Affiche la bannière de profil d'un membre"""
    member = member or ctx.author
    try:
        # Fetch complet pour avoir la bannière
        user = await bot.fetch_user(member.id)
        if not user.banner:
            return await ctx.send(f"❌ {member.mention} n'a pas de bannière de profil.")
        e = discord.Embed(
            title=f"🎨 Bannière — {member.display_name}",
            color=member.color if member.color.value else discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        e.set_image(url=user.banner.url)
        e.add_field(name="Télécharger", value=f"[Cliquer ici]({user.banner.url})")
        e.set_footer(text=f"ID : {member.id}")
        await ctx.send(embed=e)
    except Exception:
        await ctx.send(f"❌ Impossible de récupérer la bannière de {member.mention}.")

   # Rôle qui peut faire !tribunal
VOTES_NECESSAIRES = 4            # Votes nécessaires pour valider une décision

tribunal_votes = {}  # {message_id: {"pour": [], "contre": [], "data": {...}}}

class TribunalView(discord.ui.View):
    def __init__(self, accused_id, moderator_id, motif, vote_type):
        super().__init__(timeout=None)
        self.accused_id   = accused_id
        self.moderator_id = moderator_id
        self.motif        = motif
        self.vote_type    = vote_type  # "ban", "kick", "mute"

    async def update_embed(self, interaction, data):
        guild = interaction.guild
        accused = guild.get_member(self.accused_id)

        pour_list   = data["pour"]
        contre_list = data["contre"]

        # Formater les votes
        def fmt_votes(lst):
            lines = ""
            for uid in lst:
                m = guild.get_member(uid)
                lines += f"Vote x{lst.index(uid)+1} @{m.display_name if m else uid}\nJuge :\n"
            return lines if lines else "*(aucun vote)*"

        emojis_type = {"ban": "🔨", "kick": "👟", "mute": "🔇"}
        titles_type = {"ban": "VOTE BANNISSEMENT", "kick": "VOTE EXPULSION", "mute": "VOTE MUTE"}
        colors_type = {"ban": discord.Color.dark_red(), "kick": discord.Color.orange(), "mute": discord.Color.greyple()}

        emoji = emojis_type.get(self.vote_type, "⚖️")
        title = titles_type.get(self.vote_type, "VOTE TRIBUNAL")
        color = colors_type.get(self.vote_type, discord.Color.blurple())

        mod = guild.get_member(self.moderator_id)

        e = discord.Embed(title=f"⚖️ — {title}", color=color)
        e.add_field(name="",
            value=(
                f"✖️ - Modérateur > {mod.mention if mod else 'Inconnu'}\n"
                f"🔵 - Membre > {accused.mention if accused else f'`{self.accused_id}`'}\n"
                f"✅ - Motif > {self.motif}"
            ), inline=False)

        e.add_field(name=f"Votes Pour 👍",   value=fmt_votes(pour_list),   inline=True)
        e.add_field(name=f"Votes Contre 👎", value=fmt_votes(contre_list), inline=True)

        e.set_image(url="https://i.imgur.com/tribunal_hammer.jpg")  # image optionnelle
        e.set_footer(text=f"{VOTES_NECESSAIRES} votes pour l'un des deux côtés sont nécessaires.")

        return e

    @discord.ui.button(label="Pour", style=discord.ButtonStyle.green, custom_id="trib_pour")
    async def vote_pour(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._vote(interaction, "pour")

    @discord.ui.button(label="Contre", style=discord.ButtonStyle.grey, custom_id="trib_contre")
    async def vote_contre(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._vote(interaction, "contre")

    @discord.ui.button(label="Bannir", style=discord.ButtonStyle.red, custom_id="trib_bannir")
    async def vote_bannir(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Seulement si assez de votes Pour
        mid  = str(interaction.message.id)
        data = tribunal_votes.get(mid, {"pour": [], "contre": []})
        if len(data["pour"]) < VOTES_NECESSAIRES:
            return await interaction.response.send_message(
                f"❌ Il faut **{VOTES_NECESSAIRES} votes Pour** avant d'exécuter la sanction.", ephemeral=True)

        # Vérif permission juge
        juge_role = discord.utils.get(interaction.guild.roles, name=ROLE_JUGE)
        if juge_role and juge_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Tu n'as pas le rôle **Gestion**.", ephemeral=True)

        guild   = interaction.guild
        accused = guild.get_member(self.accused_id)
        if not accused:
            return await interaction.response.send_message("❌ Membre introuvable.", ephemeral=True)

        try:
            if self.vote_type == "ban":
                await dm(accused, "🔨 Tu as été banni par le tribunal",
                    f"**Serveur :** {guild.name}\n**Motif :** {self.motif}",
                    color=discord.Color.dark_red())
                await accused.ban(reason=f"[Tribunal] {self.motif}")
                action = "banni"
            elif self.vote_type == "kick":
                await dm(accused, "👟 Tu as été expulsé par le tribunal",
                    f"**Serveur :** {guild.name}\n**Motif :** {self.motif}",
                    color=discord.Color.orange())
                await accused.kick(reason=f"[Tribunal] {self.motif}")
                action = "expulsé"
            elif self.vote_type == "mute":
                until = discord.utils.utcnow() + timedelta(hours=24)
                await accused.timeout(until, reason=f"[Tribunal] {self.motif}")
                action = "muté (24h)"
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Permission insuffisante.", ephemeral=True)

        # Désactiver les boutons
        for child in self.children:
            child.disabled = True

        e = discord.Embed(
            title=f"⚖️ Tribunal — Verdict Rendu",
            description=f"{accused.mention if accused else self.accused_id} a été **{action}** par décision du tribunal.\n**Motif :** {self.motif}",
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        e.add_field(name="Votes Pour",   value=str(len(data["pour"])))
        e.add_field(name="Votes Contre", value=str(len(data["contre"])))
        e.add_field(name="Exécuté par",  value=interaction.user.mention)
        e.set_footer(text=guild.name)

        await interaction.message.edit(embed=e, view=self)
        await interaction.response.send_message(f"✅ {accused.mention} a été **{action}**.", ephemeral=True)

        # Log sanction
        await log_sanction(guild, accused, self.vote_type.capitalize(),
            f"[Tribunal] {self.motif}", interaction.user)

    async def _vote(self, interaction: discord.Interaction, side: str):
        # Vérif rôle juge
        juge_role = discord.utils.get(interaction.guild.roles, name=ROLE_JUGE)
        if juge_role and juge_role not in interaction.user.roles:
            return await interaction.response.send_message(
                f"❌ Seuls les membres avec le rôle **{ROLE_JUGE}** peuvent voter.", ephemeral=True)

        mid  = str(interaction.message.id)
        tribunal_votes.setdefault(mid, {"pour": [], "contre": [], "data": {}})
        data = tribunal_votes[mid]

        uid = interaction.user.id

        # Retirer vote opposé si existant
        other = "contre" if side == "pour" else "pour"
        if uid in data[other]:
            data[other].remove(uid)

        # Toggle vote
        if uid in data[side]:
            data[side].remove(uid)
            await interaction.response.send_message(f"↩️ Ton vote **{side}** a été retiré.", ephemeral=True)
        else:
            data[side].append(uid)
            await interaction.response.send_message(f"✅ Vote **{side}** enregistré !", ephemeral=True)

        # Mettre à jour l'embed
        new_embed = await self.update_embed(interaction, data)
        await interaction.message.edit(embed=new_embed)

@bot.command(name="tribunal")
async def tribunal(ctx, accused: discord.Member, vote_type: str = "ban", *, motif: str = "Aucun motif"):
    """
    !tribunal @membre [ban/kick/mute] [motif]
    Nécessite le rôle 'Gestion'
    """
    # Vérif rôle juge (Inspecteur + grades supérieurs)
    if not has_sanction_role(ctx.author, ROLES_TRIBUNAL):
        return await ctx.send("❌ Seuls les **Inspecteur**, **Chef Gestion** et grades supérieurs peuvent ouvrir un tribunal.")

    # Vérif type de vote
    vote_type = vote_type.lower()
    if vote_type not in ["ban", "kick", "mute"]:
        return await ctx.send("❌ Type invalide. Utilise `ban`, `kick` ou `mute`.")

    # Vérif salon tribunal
    tribunal_ch = discord.utils.find(
        lambda c: "tribunal" in c.name.lower(), ctx.guild.text_channels)
    target_ch = tribunal_ch or ctx.channel

    emojis_type = {"ban": "🔨", "kick": "👟", "mute": "🔇"}
    titles_type = {"ban": "VOTE BANNISSEMENT", "kick": "VOTE EXPULSION", "mute": "VOTE MUTE"}
    colors_type = {"ban": discord.Color.dark_red(), "kick": discord.Color.orange(), "mute": discord.Color.greyple()}

    e = discord.Embed(
        title=f"⚖️ — {titles_type[vote_type]}",
        color=colors_type[vote_type],
        timestamp=datetime.utcnow()
    )
    e.add_field(name="",
        value=(
            f"✖️ - Modérateur > {ctx.author.mention}\n"
            f"🔵 - Membre > {accused.mention}\n"
            f"✅ - Motif > {motif}"
        ), inline=False)
    e.add_field(name="Votes Pour 👍",   value="*(aucun vote)*", inline=True)
    e.add_field(name="Votes Contre 👎", value="*(aucun vote)*", inline=True)
    e.set_footer(text=f"{VOTES_NECESSAIRES} votes pour l'un des deux côtés sont nécessaires.")
    e.set_thumbnail(url=accused.display_avatar.url)

    view = TribunalView(accused.id, ctx.author.id, motif, vote_type)
    msg  = await target_ch.send(embed=e, view=view)

    # Enregistrer le vote
    tribunal_votes[str(msg.id)] = {"pour": [], "contre": [], "data": {}}

    if target_ch != ctx.channel:
        await ctx.send(f"⚖️ Vote tribunal ouvert dans {target_ch.mention} !", delete_after=5)
    try:
        await ctx.message.delete()
    except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="text")
@commands.has_permissions(administrator=True)
async def send_text(ctx, *, contenu: str):
    """
    !text [contenu] — Envoie un message personnalisé permanent dans ce salon.

    Formatage disponible :
      **gras**   __souligné__   *italique*   ~~barré~~
      `code`     > citation
      Saut de ligne : écrire \\n dans la commande

    Exemples :
      !text Bienvenue sur le serveur !
      !text **Règlement**\\n> 1. Soyez respectueux\\n> 2. Pas de spam
    """

    # Remplace les \n littéraux et | par de vrais sauts de ligne
    contenu = contenu.replace("\\n", "\n").replace(r"\n", "\n").replace(" | ", "\n").replace("|", "\n")

    # Supprimer le message de commande pour ne laisser que le résultat
    try:
        await ctx.message.delete()
    except Exception:
        pass  # Ignoré intentionnellement

    await ctx.send(contenu)

@bot.command(name="embed")
@commands.has_permissions(administrator=True)
async def send_embed(ctx, titre: str, couleur: str = "bleu", *, contenu: str):
    """
    !embed "Titre" [couleur] [contenu] — Envoie un embed personnalisé permanent.

    Couleurs : rouge, vert, bleu, or, violet, orange, gris
    Saut de ligne : \\n

    Exemple :
      !embed "📜 Règlement" rouge Règle 1 : Sois respectueux\\nRègle 2 : Pas de spam
    """

    couleurs = {
        "rouge":  discord.Color.red(),
        "vert":   discord.Color.green(),
        "bleu":   discord.Color.blurple(),
        "or":     discord.Color.gold(),
        "violet": discord.Color.purple(),
        "orange": discord.Color.orange(),
        "gris":   discord.Color.greyple(),
        "noir":   discord.Color.dark_gray(),
        "blanc":  discord.Color.light_gray(),
    }

    color = couleurs.get(couleur.lower(), discord.Color.blurple())
    contenu = contenu.replace("\\n", "\n")

    e = discord.Embed(title=titre, description=contenu, color=color)
    if ctx.guild.icon:
        e.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url)

    try:
        await ctx.message.delete()
    except Exception:
        pass  # Ignoré intentionnellement

    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# 🤖 COMMANDES IA
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="ai")
async def ai_command(ctx, *, question: str):
    """!ai [question] — Pose une question à l'IA Kozakura"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée (clé ANTHROPIC_API_KEY manquante).")

    async with ctx.typing():
        messages = [{"role": "user", "content": f"{ctx.author.display_name}: {question}"}]
        response = await call_claude(messages)

    e = discord.Embed(
        description=response,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    e.set_author(name=f"🤖 Kozakura AI — réponse à {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    e.set_footer(text="Powered by Claude (Anthropic)")
    await ctx.reply(embed=e)

@bot.command(name="announce")
@commands.has_permissions(administrator=True)
async def ai_announce(ctx, *, sujet: str):
    """!announce [sujet] — Génère une annonce stylée avec l'IA"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    async with ctx.typing():
        messages = [{
            "role": "user",
            "content": f"Génère une annonce Discord professionnelle et engageante pour un serveur Discord sur ce sujet : {sujet}. "
                      f"Utilise des emojis Discord, du **gras**, et structure bien l'annonce. Maximum 400 mots. "
                      f"Le serveur s'appelle Kozakura."
        }]
        response = await call_claude(messages)

    e = discord.Embed(
        title="📢 Annonce",
        description=response,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    if ctx.guild.icon:
        e.set_thumbnail(url=ctx.guild.icon.url)
    e.set_footer(text=f"Annonce générée par {ctx.author.display_name}")

    # Demander confirmation
    confirm_msg = await ctx.send(
        "Voici l'annonce générée. Réagis avec ✅ pour l'envoyer dans ce salon, ❌ pour annuler.",
        embed=e
    )
    await confirm_msg.add_reaction("✅")
    await confirm_msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30.0, check=check)
        if str(reaction.emoji) == "✅":
            await ctx.send(embed=e)
            await confirm_msg.delete()
            await ctx.message.delete()
        else:
            await confirm_msg.delete()
            await ctx.send("❌ Annonce annulée.", delete_after=5)
    except asyncio.TimeoutError:
        await confirm_msg.delete()

@bot.command(name="resume")
@staff_only()
async def ai_resume(ctx, nb_messages: int = 20):
    """!resume [nb] — Résume les derniers messages du salon avec l'IA"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    nb_messages = min(nb_messages, 50)

    async with ctx.typing():
        messages_history = []
        async for msg in ctx.channel.history(limit=nb_messages + 1):
            if msg.id != ctx.message.id and not msg.author.bot:
                messages_history.append(f"{msg.author.display_name}: {msg.content[:200]}")

        messages_history.reverse()
        conversation = "\n".join(messages_history)

        if not conversation:
            return await ctx.send("❌ Pas assez de messages à résumer.")

        prompt = [{
            "role": "user",
            "content": f"Résume cette conversation Discord en français de manière concise et claire. "
                      f"Identifie les sujets principaux, les points importants et l'ambiance générale :\n\n{conversation}"
        }]
        response = await call_claude(prompt)

    e = discord.Embed(
        title=f"📝 Résumé des {nb_messages} derniers messages",
        description=response,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Résumé par Kozakura AI • {ctx.channel.name}")
    await ctx.reply(embed=e)

@bot.command(name="analyse")
@staff_only()
async def ai_analyse(ctx, member: discord.Member):
    """!analyse @membre — Analyse le comportement d'un membre avec l'IA"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    gid = str(ctx.guild.id)
    uid = str(member.id)

    # Récupérer les données du membre
    sanctions = sanctions_db.get(gid, {}).get(uid, [])
    warnings  = warnings_db.get(gid, {}).get(uid, [])
    xp        = xp_db.get(gid, {}).get(uid, 0)
    level     = get_level(xp)
    trophees  = trophees_db.get(gid, {}).get(uid, {})

    async with ctx.typing():
        data_str = (
            f"Membre : {member.display_name}\n"
            f"Niveau XP : {level} ({xp} XP)\n"
            f"Sanctions totales : {len(sanctions)}\n"
            f"Avertissements : {len(warnings)}\n"
            f"Votes trophée : {trophees.get('votes', 0)}\n"
            f"Temps vocal : {trophees.get('voice_minutes', 0) // 60}h\n"
            f"Types sanctions : {', '.join(set(s['type'] for s in sanctions)) if sanctions else 'aucune'}\n"
            f"Dernière sanction : {sanctions[-1]['date'][:10] if sanctions else 'jamais'}"
        )

        prompt = [{
            "role": "user",
            "content": f"Analyse ce profil de membre Discord et donne une évaluation de son comportement, "
                      f"ses points positifs, ses points négatifs, et une recommandation pour le staff. "
                      f"Sois objectif et professionnel :\n\n{data_str}"
        }]
        response = await call_claude(prompt)

    e = discord.Embed(
        title=f"🔍 Analyse IA — {member.display_name}",
        description=response,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📊 Stats rapides",
                value=f"Niv. {level} | {len(sanctions)} sanctions | {len(warnings)} warns",
                inline=False)
    e.set_footer(text="Analyse générée par Kozakura AI")
    await ctx.reply(embed=e)

@bot.command(name="clearmemory")
async def ai_clear_memory(ctx):
    """!clearmemory — Efface la mémoire de conversation avec l'IA"""
    uid = str(ctx.author.id)
    if uid in ai_conversations:
        del ai_conversations[uid]
    await ctx.send("🧠 Mémoire de conversation effacée ! Je repars de zéro.", delete_after=10)

@bot.command(name="setaichannel")
@commands.has_permissions(administrator=True)
async def set_ai_channel(ctx, *, arg: str):
    """!setaichannel #salon — Définit le salon IA principal"""
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "ai_channel", channel.id)
    await ctx.send(f"✅ Salon IA → {channel.mention}\nLe bot répondra automatiquement dans ce salon.")

@bot.command(name="setautotrad")
@commands.has_permissions(administrator=True)
async def setautotrad(ctx, state: str, channel: discord.TextChannel = None):
    """!setautotrad on/off [#salon] — Active/désactive la traduction automatique"""
    ch = channel or ctx.channel
    gid = str(ctx.guild.id); cid = str(ch.id)
    state = state.lower().strip()
    if state not in ("on", "off"):
        return await ctx.send("❌ Utilise `!setautotrad on` ou `!setautotrad off`.", delete_after=5)
    enabled = (state == "on")
    autotrad_db.setdefault(gid, {})[cid] = enabled
    save_json("autotrad.json", autotrad_db)
    status = "✅ activée" if enabled else "❌ désactivée"
    e = discord.Embed(
        title="🌐 Traduction automatique",
        description=f"Traduction auto {status} dans {ch.mention}.",
        color=KOZA_PINK if enabled else discord.Color.dark_grey(),
        timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command(name="mood")
async def mood(ctx):
    """!mood — L'IA analyse l'ambiance générale des 50 derniers messages"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ Clé API Anthropic non configurée.")
    async with ctx.typing():
        messages_raw = []
        async for msg in ctx.channel.history(limit=50):
            if not msg.author.bot and msg.content:
                messages_raw.append(f"{msg.author.display_name}: {msg.content[:100]}")
        if not messages_raw:
            return await ctx.send("❌ Pas assez de messages à analyser.")
        messages_raw.reverse()
        sample = "\n".join(messages_raw[-30:])
        prompt = [{"role": "user", "content":
            f"Analyse l'ambiance générale de cette conversation Discord (serveur: {ctx.guild.name}). "
            f"Décris en 3-4 phrases l'humeur, le ton, et l'énergie du salon. "
            f"Utilise des emojis japonais/anime. Sois créatif et expressif.\n\n---\n{sample}"}]
        response = await call_claude(prompt)
    e = discord.Embed(
        title="🌸 Analyse d'Ambiance — Kozakura IA",
        description=response,
        color=KOZA_PINK, timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Kozakura IA • {ctx.guild.name} • 50 derniers messages")
    await ctx.send(embed=e)

@bot.command(name="roast")
async def roast(ctx, member: discord.Member = None):
    """!roast @membre — L'IA génère un roast drôle et bienveillant basé sur les stats"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ Clé API Anthropic non configurée.")
    member = member or ctx.author
    gid = str(ctx.guild.id); uid = str(member.id)
    xp   = xp_db.get(gid, {}).get(uid, 0)
    lvl  = get_level(xp)
    warns = len(warnings_db.get(gid, {}).get(uid, []))
    joined_days = (datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0
    roles_count = len([r for r in member.roles if r.name != "@everyone"])
    bal = get_balance(gid, uid)
    async with ctx.typing():
        prompt = [{"role": "user", "content":
            f"Génère un roast DRÔLE, BIENVEILLANT et CRÉATIF de {member.display_name} "
            f"en utilisant CES VRAIES STATS : "
            f"Niveau XP: {lvl}, XP total: {xp}, "
            f"Membre depuis: {joined_days} jours, "
            f"Avertissements: {warns}, "
            f"Sakuras: {bal} 🌸, "
            f"Nombre de rôles: {roles_count}. "
            f"Style anime/japonais, max 150 mots, avec emojis. "
            f"C'est pour rire, reste gentil et créatif !"}]
        response = await call_claude(prompt)
    e = discord.Embed(
        title=f"🔥 Roast de {member.display_name}",
        description=response,
        color=KOZA_DARK, timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura IA • {ctx.guild.name} • C'est pour rire !")
    await ctx.send(embed=e)

@bot.command(name="conseil")
async def conseil(ctx):
    """!conseil — L'IA donne un conseil de vie profond"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ Clé API Anthropic non configurée.")
    async with ctx.typing():
        prompt = [{"role": "user", "content":
            "Donne un conseil de vie profond, inspirant et original. "
            "Style poétique avec des métaphores japonaises/anime (cerisiers, samouraïs, katana, etc.). "
            "Max 100 mots. Termine par un emoji japonais."}]
        response = await call_claude(prompt)
    e = discord.Embed(
        title="🌸 Conseil de Kozakura",
        description=f"*{response}*",
        color=KOZA_PINK, timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Kozakura IA • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command(name="histoire")
async def histoire(ctx):
    """!histoire — L'IA génère une courte histoire avec des membres du serveur"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ Clé API Anthropic non configurée.")
    import random
    # Prendre 3-5 membres aléatoires du serveur (non-bots)
    members_sample = random.sample(
        [m for m in ctx.guild.members if not m.bot],
        min(4, len([m for m in ctx.guild.members if not m.bot]))
    )
    names = ", ".join(m.display_name for m in members_sample)
    async with ctx.typing():
        prompt = [{"role": "user", "content":
            f"Écris une COURTE histoire originale et drôle (max 200 mots) "
            f"dans un univers anime/japonais (ninjas, samouraïs, magie, Japon féodal...) "
            f"en incluant CES vrais membres du serveur '{ctx.guild.name}' : {names}. "
            f"L'histoire doit être positive, créative et amusante. Utilise des emojis."}]
        response = await call_claude(prompt)
    e = discord.Embed(
        title="📜 Histoire de Kozakura",
        description=response,
        color=KOZA_PINK, timestamp=datetime.utcnow()
    )
    e.add_field(name="🎭 Héros de l'histoire", value=", ".join(m.mention for m in members_sample), inline=False)
    e.set_footer(text=f"Kozakura IA • {ctx.guild.name}")
    await ctx.send(embed=e)

# ─── TRANSCRIPT TICKET ───────────────────────────────────────────────────────
async def _save_ticket_transcript(guild, channel, ticket_data):
    """Génère un transcript texte du ticket et l'envoie dans les logs"""
    try:
        import io
        lines = [
            f"═══════════════════════════════════════════════════",
            f"  TRANSCRIPT — Ticket #{ticket_data.get('number', '?')}",
            f"  Serveur   : {guild.name}",
            f"  Type      : {ticket_data.get('type', '?').capitalize()}",
            f"  Auteur    : {ticket_data.get('author_name', '?')}",
            f"  Ouvert le : {ticket_data.get('opened_at', '?')[:16]}",
            f"  Fermé le  : {ticket_data.get('closed_at', '?')[:16]}",
            f"  Raison    : {ticket_data.get('close_reason', '?')}",
            f"═══════════════════════════════════════════════════",
            "",
        ]
        msgs = []
        async for msg in channel.history(limit=500, oldest_first=True):
            ts = msg.created_at.strftime("%d/%m/%Y %H:%M")
            content = msg.content or "[média/embed]"
            msgs.append(f"[{ts}] {msg.author.display_name}: {content}")
        lines.extend(msgs)
        content_str = "\n".join(lines)

        log_ch_id = get_cfg(guild.id, "ticket_log_channel")
        if log_ch_id:
            log_ch = guild.get_channel(int(log_ch_id))
            if log_ch:
                buf = io.BytesIO(content_str.encode("utf-8"))
                fname = f"transcript-ticket-{ticket_data.get('number','?')}.txt"
                e = discord.Embed(
                    title=f"📄 Transcript — Ticket #{ticket_data.get('number','?')}",
                    description=(
                        f"**Type :** {ticket_data.get('type','?').capitalize()}\n"
                        f"**Auteur :** {ticket_data.get('author_name','?')}\n"
                        f"**Messages :** {len(msgs)}"
                    ),
                    color=discord.Color.blurple(), timestamp=datetime.utcnow()
                )
                e.set_footer(text="Kozakura • Transcript automatique")
                await log_ch.send(embed=e, file=discord.File(buf, filename=fname))
    except Exception:
        pass

# ─── RÉSUMÉ AUTOMATIQUE À LA FERMETURE DES TICKETS ───────────────────────────
async def ai_summarize_ticket(guild, channel, ticket_data):
    """Résume automatiquement un ticket à sa fermeture"""
    if not ANTHROPIC_API_KEY:
        return

    try:
        messages_history = []
        async for msg in channel.history(limit=100):
            if not msg.author.bot:
                messages_history.append(f"{msg.author.display_name}: {msg.content[:200]}")

        messages_history.reverse()
        conversation = "\n".join(messages_history[:50])

        if not conversation:
            return

        prompt = [{
            "role": "user",
            "content": f"Résume ce ticket de support Discord en 3-4 lignes max. "
                      f"Indique : le problème signalé, comment il a été résolu (si applicable), "
                      f"et le ton général de l'échange. Sois concis :\n\n{conversation}"
        }]

        summary = await call_claude(prompt)

        # Envoyer le résumé dans les logs tickets
        log_ch_id = get_cfg(guild.id, "ticket_log_channel")
        if log_ch_id:
            log_ch = guild.get_channel(int(log_ch_id))
            if log_ch:
                e = discord.Embed(
                    title=f"🤖 Résumé IA — Ticket #{ticket_data.get('number', '?')}",
                    description=summary,
                    color=discord.Color.blurple(),
                    timestamp=datetime.utcnow()
                )
                e.add_field(name="Type", value=ticket_data.get('type', '?').capitalize())
                e.add_field(name="Auteur", value=ticket_data.get('author_name', '?'))
                e.set_footer(text="Résumé automatique par Kozakura AI")
                await log_ch.send(embed=e)
    except Exception:
        pass  # Ignoré intentionnellement

# ══════════════════════════════════════════════════════════════════════════════
# 📊 STATS & RAPPORTS
# ══════════════════════════════════════════════════════════════════════════════

# Tracker de messages par membre {guild_id: {user_id: count}}
message_count_db = load_json("message_counts.json", {})

@bot.command(name="activite")
@staff_only()
async def activite(ctx, member: discord.Member = None):
    """!activite [@membre] — Stats détaillées d'un membre"""
    member = member or ctx.author
    gid = str(ctx.guild.id)
    uid = str(member.id)

    xp        = xp_db.get(gid, {}).get(uid, 0)
    level     = get_level(xp)
    sanctions = sanctions_db.get(gid, {}).get(uid, [])
    warnings  = warnings_db.get(gid, {}).get(uid, [])
    trophees  = trophees_db.get(gid, {}).get(uid, {})
    msgs      = message_count_db.get(gid, {}).get(uid, 0)
    voice_min = trophees.get("voice_minutes", 0)
    votes     = trophees.get("votes", 0)

    # Compter sanctions par type
    sanc_counts = {}
    for s in sanctions:
        sanc_counts[s["type"]] = sanc_counts.get(s["type"], 0) + 1

    # Statut vocal actuel
    in_voice = member.voice.channel.name if member.voice else "Non"

    # Ancienneté
    joined = member.joined_at
    days_on_server = (datetime.utcnow() - joined.replace(tzinfo=None)).days if joined else 0

    e = discord.Embed(
        title=f"📊 Activité de {member.display_name}",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)

    e.add_field(
        name="🏆 XP & Niveaux",
        value=f"Niveau **{level}** • {xp} XP\nMessages estimés : ~{msgs}",
        inline=True
    )
    e.add_field(
        name="🎙️ Vocal",
        value=f"Temps total : **{voice_min // 60}h {voice_min % 60}min**\nEn vocal : {in_voice}",
        inline=True
    )
    e.add_field(
        name="📅 Ancienneté",
        value=f"Membre depuis **{days_on_server} jours**\n({joined.strftime('%d/%m/%Y') if joined else '?'})",
        inline=True
    )
    e.add_field(
        name="⚖️ Sanctions",
        value="\n".join(f"• {k} : {v}" for k,v in sanc_counts.items()) or "✅ Aucune sanction",
        inline=True
    )
    e.add_field(
        name="⚠️ Avertissements",
        value=f"**{len(warnings)}** warn(s)",
        inline=True
    )
    e.add_field(
        name="🏅 Trophées",
        value=f"⭐ {votes} votes\n🎙️ {voice_min // 60}h vocal",
        inline=True
    )

    # Rôles importants
    roles = [r.mention for r in member.roles if r.name != "@everyone"][-5:]
    if roles:
        e.add_field(name="🎭 Rôles", value=" ".join(roles), inline=False)

    e.set_footer(text=f"Kozakura Stats • {ctx.guild.name}")
    await ctx.send(embed=e)

# ── Rapport hebdomadaire automatique ─────────────────────────────────────────
@tasks.loop(hours=1)
async def rapport_hebdo():
    """Envoie un rapport hebdomadaire chaque lundi à 9h UTC"""
    now = datetime.utcnow()
    if now.weekday() != 0 or now.hour != 9:  # Lundi = 0, 9h UTC
        return

    for guild in bot.guilds:
        gid = str(guild.id)
        staff_ch = discord.utils.find(
            lambda c: "staff" in c.name.lower() or "logs-bans" in c.name.lower(),
            guild.text_channels
        )
        if not staff_ch:
            continue

        # Stats de la semaine
        sanctions_week = []
        for uid, sancs in sanctions_db.get(gid, {}).items():
            for s in sancs:
                try:
                    date = datetime.fromisoformat(s["date"][:19])
                    if (now - date).days <= 7:
                        sanctions_week.append(s)
                except Exception: pass

        # Top XP
        top_xp = sorted(xp_db.get(gid, {}).items(), key=lambda x: -x[1])[:3]

        # Membres actifs en vocal cette semaine
        top_vocal = sorted(
            trophees_db.get(gid, {}).items(),
            key=lambda x: x[1].get("voice_minutes", 0), reverse=True
        )[:3]

        e = discord.Embed(
            title=f"📊 Rapport Hebdomadaire — {guild.name}",
            description=f"Semaine du **{(now - timedelta(days=7)).strftime('%d/%m')}** au **{now.strftime('%d/%m/%Y')}**",
            color=discord.Color.gold(),
            timestamp=now
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        # Sanctions semaine
        sanc_types = {}
        for s in sanctions_week:
            sanc_types[s["type"]] = sanc_types.get(s["type"], 0) + 1
        sanc_txt = "\n".join(f"• {k} : {v}" for k,v in sanc_types.items()) or "✅ Aucune"
        e.add_field(name=f"⚖️ Sanctions ({len(sanctions_week)})", value=sanc_txt, inline=True)

        # Top XP
        xp_lines = []
        for uid, xp in top_xp:
            m = guild.get_member(int(uid))
            xp_lines.append(f"• {m.display_name if m else uid} — Niv.{get_level(xp)}")
        e.add_field(name="🏆 Top XP", value="\n".join(xp_lines) or "Aucun", inline=True)

        # Top vocal
        voc_lines = []
        for uid, d in top_vocal:
            m = guild.get_member(int(uid))
            h = d.get("voice_minutes", 0) // 60
            voc_lines.append(f"• {m.display_name if m else uid} — {h}h")
        e.add_field(name="🎙️ Top Vocal", value="\n".join(voc_lines) or "Aucun", inline=True)

        # Stats générales
        e.add_field(
            name="📈 Stats Serveur",
            value=(
                f"👥 Membres : {guild.member_count}\n"
                f"💎 Boosts : {guild.premium_subscription_count}\n"
                f"🎫 Tickets ouverts : {sum(1 for t in tickets_db.get(gid,{}).values() if t.get('status')=='open')}"
            ),
            inline=False
        )
        e.set_footer(text="Rapport généré automatiquement chaque lundi • Kozakura")
        await staff_ch.send(embed=e)

# ── Commande rapport manuel ───────────────────────────────────────────────────
@bot.command(name="rapport")
@commands.has_permissions(administrator=True)
async def rapport_manuel(ctx):
    """!rapport — Génère le rapport hebdomadaire maintenant"""
    gid = str(ctx.guild.id)
    now = datetime.utcnow()

    sanctions_week = []
    for uid, sancs in sanctions_db.get(gid, {}).items():
        for s in sancs:
            try:
                date = datetime.fromisoformat(s["date"][:19])
                if (now - date).days <= 7:
                    sanctions_week.append(s)
            except Exception: pass

    top_xp    = sorted(xp_db.get(gid, {}).items(), key=lambda x: -x[1])[:5]
    top_vocal = sorted(trophees_db.get(gid, {}).items(), key=lambda x: x[1].get("voice_minutes",0), reverse=True)[:5]

    e = discord.Embed(
        title=f"📊 Rapport — {ctx.guild.name}",
        description=f"Généré le **{now.strftime('%d/%m/%Y à %H:%M')}**",
        color=discord.Color.gold(), timestamp=now
    )
    if ctx.guild.icon: e.set_thumbnail(url=ctx.guild.icon.url)

    sanc_types = {}
    for s in sanctions_week:
        sanc_types[s["type"]] = sanc_types.get(s["type"], 0) + 1
    e.add_field(name=f"⚖️ Sanctions 7j ({len(sanctions_week)})",
        value="\n".join(f"• {k} : {v}" for k,v in sanc_types.items()) or "✅ Aucune", inline=True)

    xp_lines = []
    for uid, xp in top_xp:
        m = ctx.guild.get_member(int(uid))
        xp_lines.append(f"• {m.display_name if m else uid} — Niv.{get_level(xp)} ({xp} XP)")
    e.add_field(name="🏆 Top XP", value="\n".join(xp_lines) or "Aucun", inline=False)

    voc_lines = []
    for uid, d in top_vocal:
        m = ctx.guild.get_member(int(uid))
        h = d.get("voice_minutes", 0) // 60
        mn = d.get("voice_minutes", 0) % 60
        voc_lines.append(f"• {m.display_name if m else uid} — {h}h {mn}min")
    e.add_field(name="🎙️ Top Vocal", value="\n".join(voc_lines) or "Aucun", inline=False)

    e.add_field(name="📈 Stats Serveur",
        value=(f"👥 {ctx.guild.member_count} membres • 💎 {ctx.guild.premium_subscription_count} boosts\n"
               f"🎫 Tickets ouverts : {sum(1 for t in tickets_db.get(gid,{}).values() if t.get('status')=='open')}"),
        inline=False)
    e.set_footer(text="Rapport Kozakura")
    await ctx.send(embed=e)

# ── Tracker messages ──────────────────────────────────────────────────────────
# (incrémenté dans on_message via bot.listen)
@bot.listen("on_message")
async def track_message_count(message):
    if message.author.bot or not message.guild: return
    gid = str(message.guild.id)
    uid = str(message.author.id)
    message_count_db.setdefault(gid, {})
    message_count_db[gid][uid] = message_count_db[gid].get(uid, 0) + 1
    if message_count_db[gid][uid] % 50 == 0:  # Sauvegarder tous les 50 msgs
        save_json("message_counts.json", message_count_db)

# ══════════════════════════════════════════════════════════════════════════════
# 🤖 NOUVELLES COMMANDES IA
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="imagine")
async def ai_imagine(ctx, *, description: str):
    """!imagine [description] — Génère une description d'image détaillée avec l'IA"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    async with ctx.typing():
        prompt = [{
            "role": "user",
            "content": (
                f"Génère une description d'image très détaillée et visuelle pour : {description}\n\n"
                f"Décris : les couleurs, l'ambiance, les éléments visuels, le style artistique, "
                f"la composition, l'éclairage. Sois créatif et précis. Format : paragraphe descriptif "
                f"suivi de mots-clés style 'prompt' séparés par des virgules."
            )
        }]
        response = await call_claude(prompt)

    e = discord.Embed(
        title=f"🎨 Imagine — {description[:50]}",
        description=response,
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Demandé par {ctx.author.display_name} • Kozakura AI")
    await ctx.reply(embed=e)

@bot.command(name="traduis")
async def ai_traduis(ctx, langue: str = "anglais", *, texte: str):
    """
    !traduis [langue] [texte] — Traduit un texte
    Exemples : !traduis anglais Bonjour tout le monde
               !traduis espagnol Comment ça va ?
    """
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    async with ctx.typing():
        prompt = [{
            "role": "user",
            "content": f"Traduis ce texte en {langue}. Réponds UNIQUEMENT avec la traduction, sans explications :\n\n{texte}"
        }]
        response = await call_claude(prompt)

    e = discord.Embed(color=discord.Color.blue(), timestamp=datetime.utcnow())
    e.add_field(name="📝 Original", value=texte[:500], inline=False)
    e.add_field(name=f"🌍 Traduction ({langue})", value=response[:500], inline=False)
    e.set_footer(text=f"Traduit par Kozakura AI • {ctx.author.display_name}")
    await ctx.reply(embed=e)

@bot.command(name="moderia")
@staff_only()
async def ai_moderation(ctx, member: discord.Member, *, raison: str = None):
    """!moderia @membre [raison] — L'IA analyse et propose une sanction"""
    if not ANTHROPIC_API_KEY:
        return await ctx.send("❌ L'IA n'est pas configurée.")

    gid = str(ctx.guild.id)
    uid = str(member.id)
    sanctions = sanctions_db.get(gid, {}).get(uid, [])
    warnings  = warnings_db.get(gid, {}).get(uid, [])
    xp        = xp_db.get(gid, {}).get(uid, 0)
    days      = (datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0

    async with ctx.typing():
        prompt = [{
            "role": "user",
            "content": (
                f"Tu es un modérateur Discord expert. Analyse ce profil et propose une sanction appropriée.\n\n"
                f"Membre : {member.display_name}\n"
                f"Ancienneté : {days} jours\n"
                f"Niveau XP : {get_level(xp)}\n"
                f"Sanctions passées : {len(sanctions)} ({', '.join(set(s['type'] for s in sanctions)) if sanctions else 'aucune'})\n"
                f"Avertissements : {len(warnings)}\n"
                f"Raison actuelle : {raison or 'non précisée'}\n\n"
                f"Propose : la sanction recommandée (warn/mute/kick/ban), la durée si applicable, "
                f"et une justification courte. Sois juste et proportionnel."
            )
        }]
        response = await call_claude(prompt)

    e = discord.Embed(
        title=f"🤖 Analyse IA — {member.display_name}",
        description=response,
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📋 Contexte", value=f"**{len(sanctions)}** sanctions • **{len(warnings)}** warns • {days}j ancienneté")
    e.set_footer(text="⚠️ Suggestion IA — décision finale au staff")
    await ctx.reply(embed=e)

    e.add_field(name="📋 Contexte", value=f"**{len(sanctions)}** sanctions • **{len(warnings)}** warns • {days}j ancienneté")
    e.set_footer(text="⚠️ Suggestion IA — décision finale au staff")
    await ctx.reply(embed=e)

# ─── LANCEMENT ────────────────────────────────────────────────────────────────
import asyncio
import sys

import uuid
from flask import Flask, request, jsonify
from threading import Thread

# ── CORS helper ───────────────────────────────────────────────────────────────
DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "")  # ex: https://mon-dashboard.railway.app

def add_cors(response):
    origin = request.headers.get("Origin", "")
    if DASHBOARD_ORIGIN:
        # Autoriser uniquement l'origine configurée
        if origin == DASHBOARD_ORIGIN:
            response.headers["Access-Control-Allow-Origin"] = origin
    else:
        # Fallback si non configuré (à éviter en production)
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response

# ══════════════════════════════════════════════════════════════════════════════
# 🌐 API DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

API_SECRET = os.getenv("DASHBOARD_SECRET", "")
app_flask  = Flask(__name__)

# ── Rate limiting anti brute-force (en mémoire) ───────────────────────────────
_auth_attempts: dict = {}   # {ip: [timestamps]}
AUTH_MAX_ATTEMPTS = 10      # tentatives max
AUTH_WINDOW       = 60      # secondes

def _get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

def _check_rate_limit_auth():
    ip  = _get_ip()
    now = time.time()
    attempts = _auth_attempts.setdefault(ip, [])
    # Purge les anciennes tentatives
    _auth_attempts[ip] = [t for t in attempts if now - t < AUTH_WINDOW]
    if len(_auth_attempts[ip]) >= AUTH_MAX_ATTEMPTS:
        return False
    _auth_attempts[ip].append(now)
    return True

@app_flask.after_request
def after_request(response):
    return add_cors(response)

@app_flask.route("/api/<path:path>", methods=["OPTIONS"])
@app_flask.route("/api", methods=["OPTIONS"])
def handle_options(*args, **kwargs):
    from flask import Response
    return add_cors(Response())

def check_auth():
    return request.headers.get("X-API-Key") == API_SECRET and bool(API_SECRET)

def api_error(msg, code=403):
    return jsonify({"error": msg}), code

def safe_int(val, default=None):
    """Conversion int sécurisée — retourne default si val n'est pas un entier valide."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

def member_to_dict(m):
    return {
        "id":           str(m.id),
        "name":         m.name,
        "display_name": m.display_name,
        "avatar":       str(m.display_avatar.url),
        "roles":        [r.name for r in m.roles if r.name != "@everyone"],
        "joined_at":    str(m.joined_at),
        "bot":          m.bot
    }

# ── Auth ─────────────────────────────────────────────────────────────────────
@app_flask.route("/api/auth", methods=["POST"])
def api_auth():
    if not _check_rate_limit_auth():
        return api_error("Trop de tentatives, réessaie dans 1 minute", 429)
    key = request.json.get("key") if request.json else None
    if key and key == API_SECRET and bool(API_SECRET):
        return jsonify({"status": "ok", "token": API_SECRET})
    return api_error("Clé invalide", 401)

# ── Stats générales ───────────────────────────────────────────────────────────
@app_flask.route("/api/stats")
def api_stats():
    if not check_auth(): return api_error("Non autorisé")
    guilds = []
    for guild in bot.guilds:
        gid = str(guild.id)
        guilds.append({
            "id":          str(guild.id),
            "name":        guild.name,
            "icon":        str(guild.icon.url) if guild.icon else None,
            "members":     guild.member_count,
            "online":      sum(1 for m in guild.members if m.status != discord.Status.offline) if hasattr(list(guild.members)[0], 'status') else 0,
            "boosts":      guild.premium_subscription_count,
            "tickets":     len(tickets_db.get(gid, {})),
            "sanctions":   sum(len(v) for v in sanctions_db.get(gid, {}).values()),
            "giveaways":   sum(1 for g in giveaways_db.values() if not g.get("ended") and str(g["guild_id"]) == gid)
        })
    return jsonify({"guilds": guilds, "ping": round(bot.latency * 1000)})

# ── Membres ───────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/members")
def api_members(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    members = [member_to_dict(m) for m in guild.members if not m.bot]
    return jsonify({"members": members, "total": len(members)})

@app_flask.route("/api/<guild_id>/members/<member_id>")
def api_member(guild_id, member_id):
    if not check_auth(): return api_error("Non autorisé")
    guild  = bot.get_guild(safe_int(guild_id))
    member = guild.get_member(safe_int(member_id)) if guild else None
    if not member: return api_error("Membre introuvable", 404)
    gid = str(guild.id)
    uid = str(member.id)
    data = member_to_dict(member)
    data["xp"]         = xp_db.get(gid, {}).get(uid, 0)
    data["level"]      = get_level(data["xp"])
    data["sanctions"]  = sanctions_db.get(gid, {}).get(uid, [])
    data["trophees"]   = trophees_db.get(gid, {}).get(uid, {})
    data["voice_ch"]   = member.voice.channel.name if member.voice else None
    return jsonify(data)

# ── Actions membres ───────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/action", methods=["POST"])
def api_action(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data      = request.json or {}
    action    = data.get("action")
    member_id = data.get("member_id")
    reason    = data.get("reason", "Action depuis le dashboard")

    guild  = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    member = guild.get_member(safe_int(member_id)) if member_id else None

    async def do_action():
        if action == "ban" and member:
            await member.ban(reason=reason, delete_message_days=7)
        elif action == "kick" and member:
            await member.kick(reason=reason)
        elif action == "mute" and member:
            duration = data.get("duration", 10)
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=reason)
        elif action == "unmute" and member:
            await member.timeout(None)
        elif action == "warn" and member:
            await log_sanction(guild, member, "Warn", reason, guild.me)

    asyncio.run_coroutine_threadsafe(do_action(), bot.loop)
    return jsonify({"status": "ok", "action": action})

# ── Sanctions ─────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/sanctions")
def api_sanctions(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid   = str(guild.id)
    result = []
    for uid, sanctions in sanctions_db.get(gid, {}).items():
        member = guild.get_member(int(uid))
        result.append({
            "member_id":   uid,
            "member_name": member.display_name if member else f"ID:{uid}",
            "avatar":      str(member.display_avatar.url) if member else None,
            "sanctions":   sanctions
        })
    return jsonify({"sanctions": result})

# ── Tickets ───────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/tickets")
def api_tickets(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid   = str(guild.id)
    status_filter = request.args.get("status", "open")
    result = []
    for ch_id, tdata in tickets_db.get(gid, {}).items():
        if status_filter != "all" and tdata.get("status", "open") != status_filter:
            continue
        ch = guild.get_channel(int(ch_id))
        author_id = tdata.get("author_id") or tdata.get("opener_id", 0)
        opener = guild.get_member(int(author_id)) if author_id else None
        claimer_id = tdata.get("claimed_by")
        claimer = guild.get_member(int(claimer_id)) if claimer_id else None
        result.append({
            "channel_id":    ch_id,
            "channel_name":  ch.name if ch else f"ticket-{ch_id}",
            "type":          tdata.get("type", "inconnu"),
            "opener":        opener.display_name if opener else tdata.get("author_name", "inconnu"),
            "opener_id":     str(author_id),
            "claimed_by":    claimer.display_name if claimer else "",
            "opened_at":     tdata.get("opened_at", ""),
            "closed_at":     tdata.get("closed_at", ""),
            "close_reason":  tdata.get("close_reason", ""),
            "priority":      tdata.get("priority", "normale"),
            "status":        tdata.get("status", "open"),
            "number":        tdata.get("number", "?"),
        })
    result.sort(key=lambda x: x.get("opened_at", ""), reverse=True)
    return jsonify({"tickets": result})

@app_flask.route("/api/<guild_id>/tickets/<channel_id>/close", methods=["POST"])
def api_close_ticket(guild_id, channel_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid = str(guild.id)

    async def do_close():
        ch = guild.get_channel(safe_int(channel_id))
        if ch:
            data = tickets_db.get(gid, {}).get(channel_id, {})
            tickets_db.setdefault(gid, {})[channel_id] = {
                **data,
                "status": "closed",
                "closed_by": "dashboard",
                "closed_at": str(datetime.utcnow()),
                "close_reason": "Fermé depuis le dashboard",
            }
            save_json("tickets.json", tickets_db)
            await _save_ticket_transcript(guild, ch, tickets_db[gid][channel_id])
            await ch.delete(reason="Fermé depuis le dashboard")

    asyncio.run_coroutine_threadsafe(do_close(), bot.loop)
    return jsonify({"status": "ok"})

# ── Sécurité : Shadowban ───────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/security/shadowbans")
def api_shadowbans(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid = str(guild.id)
    result = []
    for uid, data in shadowban_db.get(gid, {}).items():
        member = guild.get_member(int(uid))
        result.append({
            "member_id":   uid,
            "member_name": member.display_name if member else f"ID:{uid}",
            "avatar":      str(member.display_avatar.url) if member else None,
            "reason":      data.get("reason", "?"),
            "by":          data.get("by", "?"),
            "date":        data.get("date", "?")[:16],
        })
    return jsonify({"shadowbans": result})

@app_flask.route("/api/<guild_id>/security/shadowbans/<member_id>", methods=["DELETE"])
def api_unshadowban(guild_id, member_id):
    if not check_auth(): return api_error("Non autorisé")
    gid = str(guild_id)
    if member_id in shadowban_db.get(gid, {}):
        shadowban_db[gid].pop(member_id)
        save_json("shadowban.json", shadowban_db)
    return jsonify({"status": "ok"})

# ── Sécurité : Watchlist ──────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/security/watchlist")
def api_watchlist(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid = str(guild.id)
    result = []
    for uid, data in watchlist_db.get(gid, {}).items():
        member = guild.get_member(int(uid))
        result.append({
            "member_id":   uid,
            "member_name": member.display_name if member else f"ID:{uid}",
            "avatar":      str(member.display_avatar.url) if member else None,
            "reason":      data.get("reason", "?"),
            "by_name":     data.get("by_name", "?"),
            "date":        data.get("date", "?")[:16],
        })
    return jsonify({"watchlist": result})

@app_flask.route("/api/<guild_id>/security/watchlist/<member_id>", methods=["DELETE"])
def api_unwatch(guild_id, member_id):
    if not check_auth(): return api_error("Non autorisé")
    gid = str(guild_id)
    if member_id in watchlist_db.get(gid, {}):
        watchlist_db[gid].pop(member_id)
        save_json("watchlist.json", watchlist_db)
    return jsonify({"status": "ok"})

# ── Sécurité : Signalements ───────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/security/reports")
def api_reports(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    gid = str(guild_id)
    data = reports_db.get(gid, [])
    return jsonify({"reports": data[-50:]})

# ── XP / Niveaux ──────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/xp")
def api_xp(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid   = str(guild.id)
    result = []
    for uid, xp in sorted(xp_db.get(gid, {}).items(), key=lambda x: -x[1]):
        member = guild.get_member(int(uid))
        result.append({
            "member_id":   uid,
            "member_name": member.display_name if member else f"ID:{uid}",
            "avatar":      str(member.display_avatar.url) if member else None,
            "xp":          xp,
            "level":       get_level(xp)
        })
    return jsonify({"leaderboard": result})

@app_flask.route("/api/<guild_id>/xp/<member_id>", methods=["POST"])
def api_set_xp(guild_id, member_id):
    if not check_auth(): return api_error("Non autorisé")
    xp_val = request.json.get("xp", 0) if request.json else 0
    gid = str(guild_id)
    xp_db.setdefault(gid, {})[str(member_id)] = int(xp_val)
    save_json("xp.json", xp_db)
    return jsonify({"status": "ok", "xp": xp_val})

# ── Giveaways ─────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/giveaways")
def api_giveaways(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    result = [
        {**{k: str(v) if k in ["host_id","channel_id","guild_id"] else v for k,v in g.items()}, "id": str(mid)}
        for mid, g in giveaways_db.items()
        if str(g["guild_id"]) == str(guild_id)
    ]
    return jsonify({"giveaways": result})

@app_flask.route("/api/<guild_id>/giveaways/create", methods=["POST"])
def api_create_giveaway(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data    = request.json or {}
    guild   = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    ch_id   = data.get("channel_id")
    channel = guild.get_channel(int(ch_id)) if ch_id else None
    if not channel: return api_error("Salon introuvable", 404)

    async def do_create():
        seconds  = int(data.get("duration_seconds", 3600))
        winners  = int(data.get("winners", 1))
        prize    = data.get("prize", "Prix")
        end_time = datetime.utcnow() + timedelta(seconds=seconds)
        e = discord.Embed(
            title=f"🎉 GIVEAWAY — {prize}",
            description=(
                f"Réagis avec 🎉 pour participer !\n\n"
                f"🎁 **Prix :** {prize}\n"
                f"🏆 **Gagnants :** {winners}\n"
                f"⏰ **Fin dans :** {format_duration(seconds)}"
            ),
            color=discord.Color.blurple(), timestamp=end_time
        )
        e.set_footer(text="Créé depuis le Dashboard")
        msg = await channel.send(embed=e)
        await msg.add_reaction("🎉")
        giveaways_db[msg.id] = {
            "prize": prize, "winners": winners,
            "host_id": guild.me.id, "channel_id": channel.id,
            "guild_id": guild.id, "end_time": end_time.timestamp(),
            "ended": False
        }
        asyncio.create_task(_giveaway_timer(msg.id, channel.id, guild.id, seconds))

    asyncio.run_coroutine_threadsafe(do_create(), bot.loop)
    return jsonify({"status": "ok"})

# ── Trophées & Rangs ──────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/trophees")
def api_trophees(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    gid   = str(guild.id)
    result = []
    for uid, tdata in trophees_db.get(gid, {}).items():
        member = guild.get_member(int(uid))
        result.append({
            "member_id":     uid,
            "member_name":   member.display_name if member else f"ID:{uid}",
            "avatar":        str(member.display_avatar.url) if member else None,
            "votes":         tdata.get("votes", 0),
            "voice_minutes": tdata.get("voice_minutes", 0),
            "voice_hours":   round(tdata.get("voice_minutes", 0) / 60, 1)
        })
    return jsonify({"trophees": sorted(result, key=lambda x: -x["votes"])})

# ── Config ────────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/config")
def api_config(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    cfg = config_db.get(str(guild_id), {})
    return jsonify({"config": cfg})

@app_flask.route("/api/<guild_id>/config", methods=["POST"])
def api_set_config(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data = request.json or {}
    gid  = str(guild_id)
    config_db.setdefault(gid, {}).update(data)
    save_json("config.json", config_db)
    return jsonify({"status": "ok"})

# ── Salons vocaux en direct ───────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/voice")
def api_voice(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    channels = []
    for vc in guild.voice_channels:
        members = []
        for m in vc.members:
            members.append({
                "id":     str(m.id),
                "name":   m.display_name,
                "avatar": str(m.display_avatar.url),
                "muted":  m.voice.self_mute if m.voice else False,
                "deafened": m.voice.self_deaf if m.voice else False
            })
        channels.append({
            "id":      str(vc.id),
            "name":    vc.name,
            "members": members,
            "limit":   vc.user_limit
        })
    return jsonify({"channels": channels})

@app_flask.route("/api/<guild_id>/voice/move", methods=["POST"])
def api_voice_move(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data      = request.json or {}
    member_id = data.get("member_id")
    channel_id = data.get("channel_id")
    guild  = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    member  = guild.get_member(safe_int(member_id))
    channel = guild.get_channel(safe_int(channel_id))
    if not member or not channel: return api_error("Membre ou salon introuvable", 404)
    async def do_move():
        await member.move_to(channel, reason="Déplacé depuis le dashboard")
    asyncio.run_coroutine_threadsafe(do_move(), bot.loop)
    return jsonify({"status": "ok"})

@app_flask.route("/api/<guild_id>/voice/disconnect", methods=["POST"])
def api_voice_disconnect(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    member_id = (request.json or {}).get("member_id")
    guild  = bot.get_guild(safe_int(guild_id))
    member = guild.get_member(safe_int(member_id)) if guild else None
    if not member: return api_error("Membre introuvable", 404)
    async def do_dc():
        await member.move_to(None, reason="Déconnecté depuis le dashboard")
    asyncio.run_coroutine_threadsafe(do_dc(), bot.loop)
    return jsonify({"status": "ok"})

# ── Envoyer un message dans un salon ─────────────────────────────────────────
@app_flask.route("/api/<guild_id>/send", methods=["POST"])
def api_send_message(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data       = request.json or {}
    channel_id = data.get("channel_id")
    content    = data.get("content", "")
    guild      = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    channel = guild.get_channel(safe_int(channel_id)) if channel_id else None
    if not channel: return api_error("Salon introuvable", 404)
    async def do_send():
        if data.get("embed"):
            e = discord.Embed(
                title=data.get("embed_title", ""),
                description=content,
                color=discord.Color.from_str(data.get("color", "#FF2D78"))
            )
            await channel.send(embed=e)
        else:
            await channel.send(content)
    asyncio.run_coroutine_threadsafe(do_send(), bot.loop)
    return jsonify({"status": "ok"})

# ── Liste des salons texte ────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/channels")
def api_channels(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    return jsonify({"channels": channels})

# ── Rôles ─────────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/roles")
def api_roles(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    roles = [{"id": str(r.id), "name": r.name, "color": str(r.color), "members": len(r.members)}
             for r in guild.roles if r.name != "@everyone"]
    return jsonify({"roles": sorted(roles, key=lambda x: -x["members"])})

@app_flask.route("/api/<guild_id>/roles/<role_id>/give", methods=["POST"])
def api_give_role(guild_id, role_id):
    if not check_auth(): return api_error("Non autorisé")
    member_id = (request.json or {}).get("member_id")
    guild  = bot.get_guild(safe_int(guild_id))
    member = guild.get_member(safe_int(member_id)) if guild else None
    role   = guild.get_role(safe_int(role_id)) if guild else None
    if not member or not role: return api_error("Introuvable", 404)
    async def do_give():
        await member.add_roles(role, reason="Ajouté depuis le dashboard")
    asyncio.run_coroutine_threadsafe(do_give(), bot.loop)
    return jsonify({"status": "ok"})

@app_flask.route("/api/<guild_id>/roles/<role_id>/remove", methods=["POST"])
def api_remove_role(guild_id, role_id):
    if not check_auth(): return api_error("Non autorisé")
    member_id = (request.json or {}).get("member_id")
    guild  = bot.get_guild(safe_int(guild_id))
    member = guild.get_member(safe_int(member_id)) if guild else None
    role   = guild.get_role(safe_int(role_id)) if guild else None
    if not member or not role: return api_error("Introuvable", 404)
    async def do_remove():
        await member.remove_roles(role, reason="Retiré depuis le dashboard")
    asyncio.run_coroutine_threadsafe(do_remove(), bot.loop)
    return jsonify({"status": "ok"})

    return jsonify({"status": "ok"})

@app_flask.route("/api/<guild_id>/roles/<role_id>/delete", methods=["POST"])
def api_delete_role(guild_id, role_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    role  = guild.get_role(safe_int(role_id)) if guild else None
    if not role: return api_error("Rôle introuvable", 404)
    async def do_delete():
        await role.delete(reason="Supprimé depuis le dashboard")
    asyncio.run_coroutine_threadsafe(do_delete(), bot.loop)
    return jsonify({"status": "ok"})

# ── Logs en temps réel ────────────────────────────────────────────────────────
dashboard_logs = []  # Liste des derniers logs

@bot.listen("on_message_delete")
async def dashboard_log_delete(message):
    if message.author.bot: return
    dashboard_logs.append({"type":"delete","time":str(datetime.utcnow()),"content":f"Message supprimé de {message.author.display_name}: {message.content[:100]}","color":"red"})
    if len(dashboard_logs) > 200: dashboard_logs.pop(0)

@bot.listen("on_member_join")
async def dashboard_log_join(member):
    dashboard_logs.append({"type":"join","time":str(datetime.utcnow()),"content":f"{member.display_name} a rejoint le serveur","color":"green"})
    if len(dashboard_logs) > 200: dashboard_logs.pop(0)

@bot.listen("on_member_remove")
async def dashboard_log_leave(member):
    dashboard_logs.append({"type":"leave","time":str(datetime.utcnow()),"content":f"{member.display_name} a quitté le serveur","color":"yellow"})
    if len(dashboard_logs) > 200: dashboard_logs.pop(0)

@app_flask.route("/api/<guild_id>/logs")
def api_logs(guild_id):
    """Retourne les logs temps réel"""
    if not check_auth(): return api_error("Non autorisé")
    return jsonify({"logs": list(reversed(dashboard_logs[-50:]))})

# ── Rangs ─────────────────────────────────────────────────────────────────────
@app_flask.route("/api/<guild_id>/ranks")
def api_ranks(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    guild = bot.get_guild(safe_int(guild_id))
    if not guild: return api_error("Serveur introuvable", 404)
    RANK_ROLES_LIST = [
        ("***", "Mirai"), ("**", "Taiyō"), ("*", "Hoshi"),
        ("III", "Shin"), ("II", "Tsuki"), ("I", "Kage")
    ]
    result = []
    for grade, titre in RANK_ROLES_LIST:
        role_grade = discord.utils.get(guild.roles, name=grade)
        members_with_rank = [member_to_dict(m) for m in guild.members if role_grade and role_grade in m.roles]
        result.append({"grade": grade, "titre": titre, "members": members_with_rank})
    return jsonify({"ranks": result})

@app_flask.route("/api/<guild_id>/ranks/set", methods=["POST"])
def api_set_rank(guild_id):
    if not check_auth(): return api_error("Non autorisé")
    data      = request.json or {}
    member_id = data.get("member_id")
    rank_idx  = data.get("rank_index", 0)  # 0=***, 5=I
    guild     = bot.get_guild(safe_int(guild_id))
    member    = guild.get_member(safe_int(member_id)) if guild else None
    if not member: return api_error("Membre introuvable", 404)
    RANK_ROLES_PAIRS = [("***","Mirai"),("**","Taiyō"),("*","Hoshi"),("III","Shin"),("II","Tsuki"),("I","Kage")]
    async def do_rank():
        # Retirer tous les anciens rangs
        for g, t in RANK_ROLES_PAIRS:
            rg = discord.utils.get(guild.roles, name=g)
            rt = discord.utils.get(guild.roles, name=t)
            if rg and rg in member.roles: await member.remove_roles(rg)
            if rt and rt in member.roles: await member.remove_roles(rt)
        # Donner le nouveau rang
        g, t = RANK_ROLES_PAIRS[rank_idx]
        rg = discord.utils.get(guild.roles, name=g)
        rt = discord.utils.get(guild.roles, name=t)
        if rg: await member.add_roles(rg)
        if rt: await member.add_roles(rt)
    asyncio.run_coroutine_threadsafe(do_rank(), bot.loop)
    return jsonify({"status": "ok"})


# ── Lancement Flask dans un thread ────────────────────────────────────────────
def run_flask():
    port = int(os.getenv("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

async def main():
    # Lancer l'API Flask dans un thread séparé
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    async with bot:
        await bot.start(TOKEN)

# ══════════════════════════════════════════════════════════════════════════════
# 🌸 SYSTÈME D'ÉCONOMIE — SAKURA
# ══════════════════════════════════════════════════════════════════════════════

economy_db   = load_json("economy.json", {})
birthday_db  = load_json("birthdays.json", {})
weekly_xp_db = load_json("weekly_xp.json", {})

KOZA_PINK  = 0xFF2D78
KOZA_DARK  = 0x080810

def get_balance(guild_id: str, user_id: str) -> int:
    return economy_db.get(guild_id, {}).get(user_id, 0)

def add_balance(guild_id: str, user_id: str, amount: int):
    economy_db.setdefault(guild_id, {})[user_id] = get_balance(guild_id, user_id) + amount
    save_json("economy.json", economy_db)

def set_balance(guild_id: str, user_id: str, amount: int):
    economy_db.setdefault(guild_id, {})[user_id] = max(0, amount)
    save_json("economy.json", economy_db)

def koza_embed(title: str, description: str = "", color: int = KOZA_PINK) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color,
                         timestamp=datetime.utcnow())

@bot.command()
async def daily(ctx):
    """!daily — Récompense quotidienne (100-500 🌸, cooldown 24h)"""
    import random
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    key = f"daily_{uid}_{gid}"
    last = config_db.get(key, 0)
    now  = time.time()
    remaining = 86400 - (now - last)
    if remaining > 0:
        h, m = divmod(int(remaining), 3600); m //= 60
        e = koza_embed("🌸 Daily indisponible",
            f"{ctx.author.mention}, ton daily sera disponible dans **{h}h {m}min** ⏳", KOZA_DARK)
        e.set_footer(text=f"Kozakura • {ctx.guild.name}")
        return await ctx.send(embed=e)
    gain = random.randint(100, 500)
    add_balance(gid, uid, gain)
    config_db[key] = now
    save_json("config.json", config_db)
    e = koza_embed("🌸 Daily récupéré !",
        f"{ctx.author.mention} a reçu **{gain} 🌸 Sakuras** !\n\n"
        f"💰 Solde : **{get_balance(gid, uid):,} 🌸**")
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

WORK_MESSAGES = [
    "Tu as livré des ramens à domicile 🍜",
    "Tu as gardé des chats de ninja 🐱‍👤",
    "Tu as réparé le katana d'un samouraï 🗡️",
    "Tu as vendu des fleurs de cerisier au marché 🌸",
    "Tu as joué de la flûte dans la rue ⛩️",
    "Tu as trié des étoiles de shuriken rouillées ⭐",
    "Tu as servi du thé dans un ryokan 🍵",
    "Tu as nettoyé un temple la nuit 🏮",
    "Tu as dompté un renard kitsune 🦊",
    "Tu as préparé des onigiri pour le staff 🍙",
    "Tu as couru après un tanuki voleur 🦝",
    "Tu as traduit des parchemins anciens 📜",
]

@bot.command()
async def work(ctx):
    """!work — Travailler toutes les 2h (50-200 🌸)"""
    import random
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    key = f"work_{uid}_{gid}"
    last = config_db.get(key, 0)
    now  = time.time()
    remaining = 7200 - (now - last)
    if remaining > 0:
        m, s = divmod(int(remaining), 60); m, h = m % 60, m // 60
        suffix = f"**{h}h {m}min**" if h else f"**{m}min {s}s**"
        e = koza_embed("⏳ Tu es encore fatigué·e",
            f"{ctx.author.mention}, repose-toi encore {suffix} avant de retravailler !", KOZA_DARK)
        e.set_footer(text=f"Kozakura • {ctx.guild.name}")
        return await ctx.send(embed=e)
    gain = random.randint(50, 200)
    msg  = random.choice(WORK_MESSAGES)
    add_balance(gid, uid, gain)
    config_db[key] = now
    save_json("config.json", config_db)
    e = koza_embed("💼 Travail accompli !",
        f"✨ *{msg}*\n\n"
        f"{ctx.author.mention} a gagné **{gain} 🌸 Sakuras** !\n"
        f"💰 Solde : **{get_balance(gid, uid):,} 🌸**")
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def balance(ctx, member: discord.Member = None):
    """!balance [@membre] — Voir son solde"""
    member = member or ctx.author
    gid = str(ctx.guild.id); uid = str(member.id)
    bal = get_balance(gid, uid)
    # Rang richesse
    sorted_eco = sorted(economy_db.get(gid, {}).items(), key=lambda x: x[1], reverse=True)
    rank_pos = next((i + 1 for i, (u, _) in enumerate(sorted_eco) if u == uid), len(sorted_eco))
    e = koza_embed("💰 Portefeuille Sakura 🌸",
        f"**{member.display_name}** possède :")
    e.add_field(name="🌸 Sakuras", value=f"**{bal:,}** 🌸", inline=True)
    e.add_field(name="🏆 Rang richesse", value=f"**#{rank_pos}** / {len(sorted_eco)}", inline=True)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    """!give @membre [montant] — Donner des sakuras"""
    if amount <= 0:
        return await ctx.send("❌ Le montant doit être positif.", delete_after=5)
    gid = str(ctx.guild.id)
    uid_from = str(ctx.author.id); uid_to = str(member.id)
    if get_balance(gid, uid_from) < amount:
        e = koza_embed("❌ Fonds insuffisants",
            f"Tu n'as que **{get_balance(gid, uid_from):,} 🌸** — il t'en faut **{amount:,}**.", KOZA_DARK)
        e.set_footer(text=f"Kozakura • {ctx.guild.name}")
        return await ctx.send(embed=e)
    add_balance(gid, uid_from, -amount)
    add_balance(gid, uid_to,    amount)
    e = koza_embed("🌸 Transfert effectué !",
        f"{ctx.author.mention} a offert **{amount:,} 🌸** à {member.mention} 💝\n\n"
        f"💰 Ton nouveau solde : **{get_balance(gid, uid_from):,} 🌸**")
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def topmoney(ctx):
    """!topmoney — Classement des plus riches"""
    gid = str(ctx.guild.id)
    top = sorted(economy_db.get(gid, {}).items(), key=lambda x: x[1], reverse=True)[:10]
    if not top:
        return await ctx.send("Aucune donnée économique pour ce serveur.")
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = []
    for i, (uid, bal) in enumerate(top):
        m = ctx.guild.get_member(int(uid))
        name = m.display_name if m else f"ID:{uid}"
        lines.append(f"{medals[i]} **{name}** — {bal:,} 🌸")
    e = koza_embed("🌸 Classement des plus riches", "\n".join(lines))
    if ctx.guild.icon:
        e.set_thumbnail(url=ctx.guild.icon.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def addmoney(ctx, member: discord.Member, amount: int):
    """!addmoney @membre [montant] — Admin : ajouter des sakuras"""
    gid = str(ctx.guild.id); uid = str(member.id)
    add_balance(gid, uid, amount)
    e = koza_embed("✅ Sakuras ajoutés",
        f"**+{amount:,} 🌸** ajoutés à {member.mention}\n"
        f"Nouveau solde : **{get_balance(gid, uid):,} 🌸**")
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
@commands.has_permissions(administrator=True)
async def removemoney(ctx, member: discord.Member, amount: int):
    """!removemoney @membre [montant] — Admin : retirer des sakuras"""
    gid = str(ctx.guild.id); uid = str(member.id)
    bal = get_balance(gid, uid)
    set_balance(gid, uid, bal - amount)
    e = koza_embed("✅ Sakuras retirés",
        f"**-{amount:,} 🌸** retirés à {member.mention}\n"
        f"Nouveau solde : **{get_balance(gid, uid):,} 🌸**", KOZA_DARK)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🎂 ANNIVERSAIRES
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def setbirthday(ctx, date: str):
    """!setbirthday [JJ/MM] — Enregistrer son anniversaire"""
    try:
        parts = date.split("/")
        if len(parts) != 2: raise ValueError
        day, month = int(parts[0]), int(parts[1])
        if not (1 <= day <= 31 and 1 <= month <= 12): raise ValueError
        datetime(2000, month, day)  # valide la date
    except (ValueError, IndexError):
        return await ctx.send("❌ Format invalide. Utilise `!setbirthday JJ/MM` (ex: `!setbirthday 14/03`)", delete_after=8)
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    birthday_db.setdefault(gid, {})[uid] = f"{day:02d}/{month:02d}"
    save_json("birthdays.json", birthday_db)
    e = koza_embed("🎂 Anniversaire enregistré !",
        f"🎉 {ctx.author.mention}, ton anniversaire est le **{day:02d}/{month:02d}** 🌸\n"
        f"Tu recevras **500 🌸 Sakuras** ce jour-là !")
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

async def announce_birthdays():
    """Annonce les anniversaires du jour dans tous les serveurs"""
    import random
    today = datetime.utcnow()
    date_str = f"{today.day:02d}/{today.month:02d}"
    confettis = ["🎊", "🎉", "🌸", "✨", "🎋", "💮", "🎀", "🏮"]
    for guild in bot.guilds:
        gid = str(guild.id)
        members_today = [uid for uid, d in birthday_db.get(gid, {}).items() if d == date_str]
        if not members_today:
            continue
        ch = discord.utils.find(
            lambda c: "général" in c.name.lower() or "general" in c.name.lower(),
            guild.text_channels
        )
        if not ch:
            continue
        for uid in members_today:
            member = guild.get_member(int(uid))
            if not member:
                continue
            add_balance(gid, uid, 500)
            banner = " ".join(random.choices(confettis, k=8))
            e = discord.Embed(
                title=f"🎂 Joyeux Anniversaire, {member.display_name} ! 🎂",
                description=(
                    f"{banner}\n\n"
                    f"✨ Toute l'équipe de **{guild.name}** te souhaite un merveilleux anniversaire {member.mention} ! 🌸\n\n"
                    f"🎁 Cadeau spécial : **+500 🌸 Sakuras** offerts !\n\n"
                    f"{banner}"
                ),
                color=KOZA_PINK,
                timestamp=datetime.utcnow()
            )
            e.set_thumbnail(url=member.display_avatar.url)
            if guild.icon:
                e.set_image(url=guild.icon.url)
            e.set_footer(text=f"Kozakura • {guild.name}")
            await ch.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🏆 CLASSEMENT HEBDOMADAIRE XP
# ══════════════════════════════════════════════════════════════════════════════

TOP_ROLE_NAMES = ["🥇 Top 1", "🥈 Top 2", "🥉 Top 3"]

async def weekly_reset():
    """Reset hebdo : annonce top 3, attribue rôles temporaires, remet à zéro"""
    for guild in bot.guilds:
        gid = str(guild.id)
        week_data = weekly_xp_db.get(gid, {})
        if not week_data:
            continue
        top3 = sorted(week_data.items(), key=lambda x: x[1], reverse=True)[:3]

        # Retirer les anciens rôles top
        for rname in TOP_ROLE_NAMES:
            role = discord.utils.get(guild.roles, name=rname)
            if role:
                for m in list(role.members):
                    try: await m.remove_roles(role, reason="Reset hebdo XP")
                    except Exception: pass

        # Attribuer les nouveaux rôles + embed annonce
        ch = discord.utils.find(
            lambda c: "niveau" in c.name.lower() or "level" in c.name.lower() or "xp" in c.name.lower(),
            guild.text_channels
        )
        podium_lines = []
        for i, (uid, xp) in enumerate(top3):
            member = guild.get_member(int(uid))
            if not member: continue
            rname = TOP_ROLE_NAMES[i]
            role  = discord.utils.get(guild.roles, name=rname)
            if role:
                try: await member.add_roles(role, reason="Top hebdo XP")
                except Exception: pass
            medals = ["🥇", "🥈", "🥉"]
            podium_lines.append(f"{medals[i]} {member.mention} — **{xp:,} XP**")

        if ch and podium_lines:
            e = discord.Embed(
                title="🏆 Classement Hebdomadaire — Résultats !",
                description=(
                    "✨ La semaine est terminée ! Voici le top 3 XP 🌸\n\n"
                    + "\n".join(podium_lines) +
                    "\n\n🎖️ Les rôles **Top 1 / 2 / 3** ont été attribués pour cette semaine !"
                ),
                color=KOZA_PINK,
                timestamp=datetime.utcnow()
            )
            if guild.icon:
                e.set_thumbnail(url=guild.icon.url)
            e.set_footer(text=f"Kozakura • {guild.name}")
            await ch.send(embed=e)

        # Reset
        weekly_xp_db[gid] = {}
    save_json("weekly_xp.json", weekly_xp_db)


# ── Tâche planifiée : anniversaires 8h UTC + reset hebdo lundi ───────────────
@tasks.loop(minutes=1)
async def daily_tasks():
    now = datetime.utcnow()
    # Anniversaires à 8h00 UTC
    if now.hour == 8 and now.minute == 0:
        await announce_birthdays()
    # Reset hebdo lundi à 8h05 UTC
    if now.weekday() == 0 and now.hour == 8 and now.minute == 5:
        await weekly_reset()

# Démarrer la tâche dans on_ready (ajout via bot.listen)
@bot.listen("on_ready")
async def start_daily_tasks():
    if not daily_tasks.is_running():
        daily_tasks.start()

# Accumuler XP hebdomadaire à chaque message XP gagné
@bot.listen("on_message")
async def track_weekly_xp(message):
    if message.author.bot or not message.guild: return
    gid = str(message.guild.id); uid = str(message.author.id)
    weekly_xp_db.setdefault(gid, {})
    weekly_xp_db[gid][uid] = weekly_xp_db[gid].get(uid, 0) + XP_PER_MSG


# ══════════════════════════════════════════════════════════════════════════════
# 🎲 COMMANDES FUN
# ══════════════════════════════════════════════════════════════════════════════

EIGHTBALL_RESPONSES = [
    ("🟢", "Absolument, c'est certain ! ✨"),
    ("🟢", "Les esprits du cerisier disent OUI 🌸"),
    ("🟢", "Sans aucun doute, va-y ! ⛩️"),
    ("🟢", "Les étoiles s'alignent en ta faveur 🌙"),
    ("🟢", "Le karma est de ton côté 🎋"),
    ("🟡", "Peut-être... les fleurs ne sont pas encore écloses 🌸"),
    ("🟡", "Le vent souffle dans les deux sens 🍃"),
    ("🟡", "Le tanuki ne se prononce pas 🦝"),
    ("🟡", "Interroge à nouveau sous la lune 🌙"),
    ("🟡", "La réponse est floue comme la brume du mont Fuji 🗻"),
    ("🔴", "Les esprits murmurent NON ⛩️"),
    ("🔴", "Le samouraï secoue la tête 🗡️"),
    ("🔴", "Les sakuras tombent — mauvais présage 🌸"),
    ("🔴", "Absolument pas, change de plan ! 💮"),
    ("🔴", "Le destin en a décidé autrement 🌑"),
    ("🟡", "Reviens me voir après avoir médité 🧘"),
    ("🟢", "Fonce, le dragon approuve 🐉"),
    ("🔴", "Même le kitsune rit de cette idée 🦊"),
    ("🟢", "Le temple a parlé : c'est un oui ! 🏮"),
    ("🔴", "Aucune chance, même avec un sortilège 🌀"),
]

@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    """!8ball [question] — La boule magique répond"""
    import random
    color_icon, response = random.choice(EIGHTBALL_RESPONSES)
    e = koza_embed(f"🔮 Boule Magique Kozakura",
        f"**Question :** {question}\n\n"
        f"{color_icon} **Réponse :** {response}")
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def coinflip(ctx):
    """!coinflip — Pile ou face"""
    import random
    result = random.choice([("🌸 Face", "La fleur de cerisier est visible !"), ("⚔️ Pile", "La lame du samouraï est en haut !")])
    e = koza_embed("🪙 Pile ou Face", f"La pièce tourne... et c'est...\n\n# {result[0]}\n*{result[1]}*")
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command(name="dé")
async def de(ctx, faces: int = 6):
    """!dé [faces] — Lancer un dé"""
    import random
    if faces < 2 or faces > 1000:
        return await ctx.send("❌ Le dé doit avoir entre 2 et 1000 faces.", delete_after=5)
    result = random.randint(1, faces)
    e = koza_embed(f"🎲 Dé à {faces} faces",
        f"{ctx.author.mention} lance le dé...\n\n"
        f"✨ Résultat : **{result}** / {faces}")
    e.set_thumbnail(url=ctx.author.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def ship(ctx, user1: discord.Member, user2: discord.Member):
    """!ship @u1 @u2 — Compatibilité amoureuse"""
    import random, hashlib
    seed = int(hashlib.md5(f"{min(user1.id, user2.id)}{max(user1.id, user2.id)}".encode()).hexdigest(), 16)
    rng  = random.Random(seed)
    score = rng.randint(0, 100)
    bar_fill = score // 10
    bar = "💗" * bar_fill + "🖤" * (10 - bar_fill)
    if score >= 90:   verdict = "💞 Âmes sœurs — c'est le destin ! ⛩️"
    elif score >= 70: verdict = "💕 Très bonne compatibilité 🌸"
    elif score >= 50: verdict = "💛 Amitié possible, qui sait ? 🎋"
    elif score >= 30: verdict = "🌀 Ça va être compliqué..."
    else:             verdict = "💔 Les esprits déconseillent fortement 🗡️"
    e = koza_embed("💘 Kozakura Ship !")
    e.add_field(name="💑 Le couple", value=f"{user1.mention} ❤️ {user2.mention}", inline=False)
    e.add_field(name="📊 Compatibilité", value=f"{bar} **{score}%**", inline=False)
    e.add_field(name="✨ Verdict", value=verdict, inline=False)
    e.set_thumbnail(url=user1.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

COMPLIMENTS = [
    "est une lumière dans ce serveur 🌸",
    "a le sourire le plus radieux de tout le Japon ✨",
    "est aussi précieux·se qu'une fleur de cerisier rare 🌸",
    "illumine chaque conversation comme la lune 🌙",
    "est la raison pour laquelle ce serveur est génial 💮",
    "a le charisme d'un shogun et la douceur d'un pétale 🌸",
    "est absolument irremplaçable dans cette communauté ⛩️",
    "mérite tous les sakuras du monde 🌸✨",
    "est une âme rare, comme un cerisier en hiver 🎋",
    "rayonne comme un feu de temple dans la nuit 🏮",
]

INSULTES = [
    "a probablement oublié de manger ses ramens ce matin 🍜",
    "confond encore les baguettes avec des stylos 🥢",
    "a un chat kitsune plus intelligent que lui/elle 🦊",
    "ferait peur même aux fantômes de Kyoto 👻",
    "arrive toujours en retard comme un samouraï sans monture 🗡️",
    "a le sens de l'orientation d'un tanuki ivre 🦝",
    "mérite un award du membre le plus étrange du serveur 🏆",
    "a des mèmes aussi vieux que le mont Fuji 🗻",
    "dort probablement en plein milieu d'une conversation 😴",
    "parle de tout mais ne sait rien, comme l'oracle du village 🏮",
]

@bot.command()
async def compliment(ctx, member: discord.Member = None):
    """!compliment [@membre] — Envoyer un compliment stylé"""
    import random
    member = member or ctx.author
    msg = random.choice(COMPLIMENTS)
    e = koza_embed("🌸 Compliment Kozakura",
        f"✨ {member.mention} {msg}")
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command()
async def insulte(ctx, member: discord.Member = None):
    """!insulte [@membre] — Insulte légère et drôle"""
    import random
    member = member or ctx.author
    msg = random.choice(INSULTES)
    e = koza_embed("😤 Kozakura dit...",
        f"🗡️ {member.mention} {msg}", KOZA_DARK)
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura • {ctx.guild.name} • (c'est pour rire !)")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🃏 CARTE DE PROFIL
# ══════════════════════════════════════════════════════════════════════════════

def _current_season() -> str:
    m = datetime.utcnow().month
    if m in (12, 1, 2):  return "❄️ Hiver"
    if m in (3, 4, 5):   return "🌸 Printemps"
    if m in (6, 7, 8):   return "☀️ Été"
    return "🍂 Automne"

def _season_color() -> int:
    m = datetime.utcnow().month
    if m in (12, 1, 2):  return 0xA8D8EA   # bleu glacé
    if m in (3, 4, 5):   return 0xFF89B4   # rose sakura
    if m in (6, 7, 8):   return 0xFFD700   # doré été
    return 0xD2691E                         # ocre automne

def _get_kozakura_rank(member: discord.Member) -> str:
    """Retourne le rang Kozakura actuel du membre en cherchant ses rôles."""
    for grade, titre in RANGS:
        if discord.utils.get(member.roles, name=grade) or discord.utils.get(member.roles, name=titre):
            return f"**{grade}** — *{titre}*"
    return "*Aucun rang Kozakura*"

@bot.command(name="carte")
async def carte(ctx, member: discord.Member = None):
    """!carte [@membre] — Carte de profil complète Kozakura"""
    member = member or ctx.author
    guild  = ctx.guild
    gid    = str(guild.id); uid = str(member.id)

    # ── XP / Niveau ──────────────────────────────────────────────────────────
    xp       = xp_db.get(gid, {}).get(uid, 0)
    lvl      = get_level(xp)
    next_xp  = xp_for_level(lvl + 1)
    prev_xp  = xp_for_level(lvl)
    progress = (xp - prev_xp) / max(next_xp - prev_xp, 1)
    bar_len  = 16
    filled   = int(progress * bar_len)
    bar      = "█" * filled + "░" * (bar_len - filled)
    pct      = int(progress * 100)

    # ── Rang leaderboard ─────────────────────────────────────────────────────
    sorted_lb = sorted(xp_db.get(gid, {}).items(), key=lambda x: x[1], reverse=True)
    rank_pos  = next((i + 1 for i, (u, _) in enumerate(sorted_lb) if u == uid), "?")

    # ── Trophées / vocal / badges ─────────────────────────────────────────────
    tdata       = trophees_db.get(gid, {}).get(uid, {})
    votes       = tdata.get("votes", 0)
    voice_min   = tdata.get("voice_minutes", 0)
    booster     = member.premium_since is not None
    badges      = get_trophee_badges(votes, voice_min, booster)
    voice_h     = voice_min // 60
    voice_m     = voice_min % 60

    # ── Sakuras ──────────────────────────────────────────────────────────────
    bal = get_balance(gid, uid)

    # ── Ancienneté ───────────────────────────────────────────────────────────
    joined_days = (datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0

    # ── Statut Discord ────────────────────────────────────────────────────────
    status_map = {
        discord.Status.online:    "🟢 En ligne",
        discord.Status.idle:      "🌙 Absent",
        discord.Status.dnd:       "🔴 Ne pas déranger",
        discord.Status.offline:   "⚫ Hors ligne",
    }
    statut = status_map.get(member.status, "⚫ Hors ligne")
    in_voice = member.voice and member.voice.channel
    if in_voice:
        statut += f" 🎙️ *{member.voice.channel.name}*"

    # ── Rang Kozakura ────────────────────────────────────────────────────────
    koza_rank = _get_kozakura_rank(member)

    # ── Titre personnalisé ────────────────────────────────────────────────────
    custom_title = titles_db.get(gid, {}).get(uid)

    # ── Embed ─────────────────────────────────────────────────────────────────
    season       = _current_season()
    season_color = _season_color()
    now_str      = datetime.utcnow().strftime("%d/%m/%Y")

    e = discord.Embed(
        title=f"{'✦ ' + custom_title + ' ✦' if custom_title else '🃏 Carte de Profil'}",
        description=(
            f"## {member.display_name}\n"
            f"*{member.name}* • {statut}\n\n"
            f"**✦ Rang Kozakura :** {koza_rank}\n"
            f"**✦ Classement XP :** `#{rank_pos}` / {len(sorted_lb)}"
        ),
        color=season_color,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)

    # XP
    e.add_field(
        name=f"⭐ Niveau {lvl}",
        value=f"`{bar}` {pct}%\n`{xp:,}` / `{next_xp:,}` XP",
        inline=False
    )

    # Stats rapides
    e.add_field(name="🌸 Sakuras",       value=f"`{bal:,}` 🌸", inline=True)
    e.add_field(name="🎙️ Temps vocal",   value=f"`{voice_h}h {voice_m:02d}m`", inline=True)
    e.add_field(name="🏅 Votes trophée", value=f"`{votes}`", inline=True)

    # Badges
    e.add_field(
        name=f"🎖️ Badges `({len(badges)})`",
        value=" · ".join(badges[:6]) or "*Aucun badge*",
        inline=False
    )

    # Ancienneté
    joined_str = member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?"
    e.add_field(name="📅 Membre depuis",  value=f"`{joined_str}` ({joined_days}j)", inline=True)
    account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    e.add_field(name="🗓️ Compte créé",   value=f"il y a `{account_age}` jours", inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)

    e.set_footer(
        text=f"Kozakura • {guild.name} • {season} • {now_str}",
        icon_url=guild.me.display_avatar.url
    )
    await ctx.send(embed=e)

@bot.command(name="settitle")
async def settitle(ctx, *, title: str = ""):
    """!settitle [titre] — Définir son titre personnalisé (vide = supprimer)"""
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    if title:
        if len(title) > 40:
            return await ctx.send("❌ Titre trop long (max 40 caractères).", delete_after=5)
        titles_db.setdefault(gid, {})[uid] = title
        save_json("titles.json", titles_db)
        e = koza_embed("✦ Titre défini", f"Ton titre est maintenant : **{title}**\nIl s'affichera sur ta `!carte` !")
    else:
        titles_db.setdefault(gid, {}).pop(uid, None)
        save_json("titles.json", titles_db)
        e = koza_embed("✦ Titre supprimé", "Ton titre personnalisé a été retiré.")
    e.set_footer(text=f"Kozakura • {ctx.guild.name}")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🌤️ MÉTÉO
# ══════════════════════════════════════════════════════════════════════════════

WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")

WEATHER_EMOJIS = {
    "clear sky":           "☀️", "few clouds": "🌤️", "scattered clouds": "⛅",
    "broken clouds":       "☁️", "overcast clouds": "☁️",
    "light rain":          "🌦️", "moderate rain": "🌧️", "heavy intensity rain": "🌧️",
    "shower rain":         "🌧️", "thunderstorm": "⛈️",
    "snow":                "❄️", "light snow": "🌨️", "mist": "🌫️",
    "fog":                 "🌫️", "haze": "🌫️", "drizzle": "🌦️",
}

def _weather_emoji(description: str) -> str:
    desc = description.lower()
    for k, v in WEATHER_EMOJIS.items():
        if k in desc:
            return v
    return "🌡️"

def _temp_color(temp_c: float) -> int:
    if temp_c <= 0:   return 0xA8D8EA  # glacé
    if temp_c <= 10:  return 0x6EB5FF  # froid
    if temp_c <= 20:  return 0x90EE90  # frais
    if temp_c <= 28:  return 0xFFD700  # chaud
    return 0xFF4500                     # très chaud

@bot.command(name="meteo")
async def meteo(ctx, *, ville: str):
    """!meteo [ville] — Météo en temps réel via OpenWeatherMap"""
    if not WEATHER_API_KEY:
        return await ctx.send("❌ Clé API météo non configurée (`WEATHER_API_KEY`).", delete_after=8)
    url = (
        f"http://api.openweathermap.org/data/2.5/weather"
        f"?q={ville}&appid={WEATHER_API_KEY}&units=metric&lang=fr"
    )
    async with ctx.typing():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
                        return await ctx.send(f"❌ Ville **{ville}** introuvable.", delete_after=8)
                    if resp.status != 200:
                        return await ctx.send(f"❌ Erreur API météo ({resp.status}).", delete_after=8)
                    data = await resp.json()
        except Exception as ex:
            return await ctx.send(f"❌ Erreur de connexion : {str(ex)[:80]}", delete_after=8)

    temp      = data["main"]["temp"]
    feels     = data["main"]["feels_like"]
    humidity  = data["main"]["humidity"]
    wind      = data["wind"]["speed"]
    desc      = data["weather"][0]["description"].capitalize()
    city_name = data["name"]
    country   = data["sys"]["country"]
    emoji     = _weather_emoji(data["weather"][0]["description"])
    sunrise   = datetime.utcfromtimestamp(data["sys"]["sunrise"]).strftime("%H:%M")
    sunset    = datetime.utcfromtimestamp(data["sys"]["sunset"]).strftime("%H:%M")

    e = discord.Embed(
        title=f"{emoji} Météo — {city_name}, {country}",
        description=f"*{desc}*",
        color=_temp_color(temp),
        timestamp=datetime.utcnow()
    )
    e.add_field(name="🌡️ Température",  value=f"**{temp:.1f}°C**", inline=True)
    e.add_field(name="🤔 Ressenti",      value=f"**{feels:.1f}°C**", inline=True)
    e.add_field(name="💧 Humidité",      value=f"**{humidity}%**", inline=True)
    e.add_field(name="💨 Vent",          value=f"**{wind} m/s**", inline=True)
    e.add_field(name="🌅 Lever",         value=f"**{sunrise} UTC**", inline=True)
    e.add_field(name="🌇 Coucher",       value=f"**{sunset} UTC**", inline=True)
    e.set_footer(text=f"Météo pour {city_name} • Kozakura • OpenWeatherMap")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🌅 MESSAGES BONJOUR / BONNE NUIT AUTOMATIQUES
# ══════════════════════════════════════════════════════════════════════════════

BONJOUR_MSGS = [
    "おはようございます ✨ Une nouvelle journée commence sous les cerisiers… Que le soleil guide tes pas aujourd'hui 🌸",
    "🌅 Le soleil se lève sur le sanctuaire de Kozakura ! Prêt·e pour cette nouvelle aventure ? ⛩️",
    "🎋 *Le vent du matin souffle doucement…* Bonjour à toi, guerrier·ère de l'aube ! 🗡️",
    "🌸 Une nouvelle journée s'ouvre comme un pétale de cerisier. Sois béni·e en ce jour ! 💮",
    "おはよう 🌄 Le temple s'éveille… Les esprits souhaitent une excellente journée à toute la communauté !",
    "☀️ Que cette journée soit aussi lumineuse que les lanternes du temple ! Bonjour Kozakura~ 🏮",
    "🌿 *Le kitsune s'étire au soleil levant…* Bonne journée à tous les membres de ce sanctuaire ! 🦊",
    "✨ Le ciel du Japon se colore d'or ce matin ! C'est un signe de bonne fortune ~ 🎑",
    "🌸 Debout, samurai·e ! Une nouvelle journée t'attend, pleine de possibilités et de Sakuras ! 💰",
    "⛩️ Le sanctuaire s'illumine… Que les esprits protecteurs veillent sur toi aujourd'hui ! 🕊️",
]

BONNE_NUIT_MSGS = [
    "🌙 La nuit tombe sur le sanctuaire de Kozakura… おやすみなさい, repose-toi bien ! ✨",
    "🌸 *Les pétales de cerisier dansent dans la nuit étoilée…* Douce nuit à tous ! 💫",
    "⛩️ Le temple s'endort… Que les rêves t'emportent dans un Japon féodal magique 🗡️",
    "🌙 おやすみ~ Le kitsune veille sur le serveur cette nuit. Bonne nuit, guerrier·ère ! 🦊",
    "🎋 *Le bambou se balance sous la lune…* Il est l'heure de recharger tes forces ! 💤",
    "🌑 La lune de Kozakura brille pour toi ce soir. Dors bien et reviens demain plus fort·e ! 🌟",
    "✨ Les lanternes s'éteignent une à une… Bonne nuit à toute la communauté 🏮",
    "💮 *Sous les étoiles du temple, le calme règne…* Repose-toi, demain est un nouveau départ ! 🌸",
    "🌙 La garde de nuit est assurée par Kozakura~ おやすみなさい à tous ! ⚔️",
    "🎑 *La lune se reflète dans le lac du sanctuaire…* Que tes rêves soient aussi beaux que ce paysage ! 🌊",
]

async def _send_bonjour_bonne_nuit(is_morning: bool):
    import random
    msgs   = BONJOUR_MSGS if is_morning else BONNE_NUIT_MSGS
    title  = "🌅 Bonjour Kozakura !" if is_morning else "🌙 Bonne nuit Kozakura !"
    color  = _season_color()
    season = _current_season()

    for guild in bot.guilds:
        ch = discord.utils.find(
            lambda c: "général" in c.name.lower() or "general" in c.name.lower() or "chat" in c.name.lower(),
            guild.text_channels
        )
        if not ch:
            continue

        online_count = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)

        e = discord.Embed(
            title=title,
            description=random.choice(msgs),
            color=color,
            timestamp=datetime.utcnow()
        )
        e.add_field(name="👥 Membres en ligne", value=f"**{online_count}** membres actifs 🌸", inline=True)
        e.add_field(name="🗓️ Saison", value=season, inline=True)
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.set_footer(text=f"Kozakura • {guild.name}", icon_url=guild.me.display_avatar.url)
        try:
            await ch.send(embed=e)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 🔄 STATUT ROTATIF DU BOT
# ══════════════════════════════════════════════════════════════════════════════

_STATUTS = [
    (discord.ActivityType.watching,   "🌸 Protège Kozakura"),
    (discord.ActivityType.watching,   "⛩️ Surveille le serveur"),
    (discord.ActivityType.playing,    "🗡️ En garde"),
    (discord.ActivityType.watching,   "🌙 Veille sur vous"),
    (discord.ActivityType.listening,  "✨ Powered by Claude"),
    (discord.ActivityType.playing,    "🎋 Mode zen activé"),
    (discord.ActivityType.watching,   "🌸 Les fleurs de cerisier tomber"),
    (discord.ActivityType.listening,  "🏮 Les prières du temple"),
    (discord.ActivityType.playing,    "🦊 Avec le kitsune"),
    (discord.ActivityType.watching,   "💮 Les Sakuras s'envoler"),
    (discord.ActivityType.competing,  "⚔️ Le tournoi des samouraïs"),
    (discord.ActivityType.listening,  "🎋 Le vent dans le bambou"),
    (discord.ActivityType.watching,   "🌕 La lune se lever"),
    (discord.ActivityType.playing,    "🐉 Avec le dragon"),
    (discord.ActivityType.watching,   "🎑 Le festival de la lune"),
    (discord.ActivityType.listening,  "🌊 Les vagues de l'océan"),
    (discord.ActivityType.playing,    "🎴 aux cartes hanafuda"),
    (discord.ActivityType.watching,   "💰 Les Sakuras de tout le monde"),
    (discord.ActivityType.competing,  "🌸 Le classement XP"),
    (discord.ActivityType.listening,  "🗡️ Les secrets du serveur"),
    (discord.ActivityType.watching,   "⭐ Chaque nouveau niveau"),
    (discord.ActivityType.playing,    "🏯 Dans le château Kozakura"),
]

_statut_index = 0

@tasks.loop(hours=1)
async def rotate_status():
    global _statut_index
    atype, name = _STATUTS[_statut_index % len(_STATUTS)]
    _statut_index += 1
    await bot.change_presence(activity=discord.Activity(type=atype, name=name))

@bot.listen("on_ready")
async def start_rotate_status():
    if not rotate_status.is_running():
        rotate_status.start()


# ── Intégrer bonjour/bonne nuit dans daily_tasks ─────────────────────────────
# (patch de la tâche existante via un listener séparé)
@tasks.loop(minutes=1)
async def greetings_task():
    now = datetime.utcnow()
    if now.hour == 8 and now.minute == 0:
        await _send_bonjour_bonne_nuit(is_morning=True)
    if now.hour == 23 and now.minute == 0:
        await _send_bonjour_bonne_nuit(is_morning=False)

@bot.listen("on_ready")
async def start_greetings():
    if not greetings_task.is_running():
        greetings_task.start()


# ══════════════════════════════════════════════════════════════════════════════
# 💤 AFK
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def afk(ctx, *, reason="Pas de raison"):
    """!afk [raison] — Passe en mode AFK"""
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    afk_db.setdefault(gid, {})[uid] = {"reason": reason, "since": str(datetime.utcnow())}
    save_json("afk.json", afk_db)
    e = discord.Embed(
        description=f"💤 **{ctx.author.display_name}** est maintenant AFK\n**Raison :** {reason}",
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.utcnow()
    )
    e.set_footer(text="Tu seras retiré de l'AFK dès ton prochain message.")
    await ctx.send(embed=e)

# ══════════════════════════════════════════════════════════════════════════════
# 🎁 GIVEAWAY
# ══════════════════════════════════════════════════════════════════════════════

class GiveawayView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Participer", emoji="🎉", style=discord.ButtonStyle.green, custom_id="gw_enter")
    async def enter(self, interaction: discord.Interaction, _: discord.ui.Button):
        gid = str(interaction.guild_id); mid = str(interaction.message.id)
        gw  = giveaway_db.get(gid, {}).get(mid)
        if not gw:
            return await interaction.response.send_message("❌ Giveaway introuvable.", ephemeral=True)
        if gw.get("ended"):
            return await interaction.response.send_message("❌ Ce giveaway est terminé.", ephemeral=True)
        uid = str(interaction.user.id)
        participants = gw.setdefault("participants", [])
        if uid in participants:
            participants.remove(uid)
            save_json("giveaways.json", giveaway_db)
            return await interaction.response.send_message("✅ Tu t'es retiré du giveaway.", ephemeral=True)
        participants.append(uid)
        save_json("giveaways.json", giveaway_db)
        await interaction.response.send_message(
            f"🎉 Tu participes ! **{len(participants)}** participant(s) au total.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# ⭐ STARBOARD CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def setstarboard(ctx, *, arg: str):
    """!setstarboard #salon — Définit le salon starboard"""
    channel = await resolve_channel(ctx, arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "starboard_channel", channel.id)
    await ctx.send(f"✅ Starboard → {channel.mention}  (seuil : **{STARBOARD_THRESHOLD}** ⭐)")


@bot.command()
@commands.has_permissions(administrator=True)
async def setstarboardthreshold(ctx, n: int):
    """!setstarboardthreshold [n] — Nombre de ⭐ requis pour le starboard"""
    global STARBOARD_THRESHOLD
    STARBOARD_THRESHOLD = max(1, n)
    await ctx.send(f"✅ Seuil starboard → **{STARBOARD_THRESHOLD}** ⭐")


# ══════════════════════════════════════════════════════════════════════════════
# 📅 ANNIVERSAIRES
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def birthday(ctx, date: str = None):
    """!birthday [JJ/MM] — Enregistre ton anniversaire (ou affiche la liste)"""
    gid = str(ctx.guild.id); uid = str(ctx.author.id)
    if date is None:
        # Afficher les prochains anniversaires
        data = birthdays_db.get(gid, {})
        if not data:
            return await ctx.send("Aucun anniversaire enregistré.", delete_after=5)
        today = datetime.utcnow()
        entries = []
        for u, d in data.items():
            try:
                day, month = map(int, d.split("/"))
                bday = datetime(today.year, month, day)
                if bday < today.replace(hour=0, minute=0, second=0, microsecond=0):
                    bday = datetime(today.year + 1, month, day)
                entries.append((bday, u, d))
            except Exception: continue
        entries.sort()
        e = discord.Embed(title="🎂  Prochains Anniversaires", color=0xFF89B4, timestamp=datetime.utcnow())
        if ctx.guild.icon: e.set_thumbnail(url=ctx.guild.icon.url)
        lines = []
        for bday, u, d in entries[:10]:
            m = ctx.guild.get_member(int(u))
            name = m.display_name if m else f"*{u}*"
            lines.append(f"🎂 **{name}** — `{d}` (<t:{int(bday.timestamp())}:R>)")
        e.description = "\n".join(lines) if lines else "Aucun anniversaire."
        return await ctx.send(embed=e)
    # Enregistrer
    import re as _re
    if not _re.match(r"^\d{2}/\d{2}$", date):
        return await ctx.send("❌ Format : `!birthday 25/12`", delete_after=5)
    try:
        day, month = map(int, date.split("/"))
        datetime(2000, month, day)  # Valider la date
    except ValueError:
        return await ctx.send("❌ Date invalide.", delete_after=5)
    birthdays_db.setdefault(gid, {})[uid] = date
    save_json("birthdays.json", birthdays_db)
    await ctx.send(f"🎂 Anniversaire enregistré : **{date}** !", delete_after=8)


@bot.command(name="setbirthdaychannel")
@commands.has_permissions(administrator=True)
async def setbirthdaychannel(ctx, channel_arg: str):
    """!setbirthdaychannel #salon — Salon des annonces d'anniversaires"""
    channel = await resolve_channel(ctx, channel_arg)
    if not channel: return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "birthday_channel", channel.id)
    await ctx.send(f"✅ Annonces anniversaires → {channel.mention}")


@tasks.loop(minutes=1)
async def check_birthdays():
    now = datetime.utcnow()
    if now.hour != 8 or now.minute != 0: return
    today_str = now.strftime("%d/%m")
    for guild in bot.guilds:
        gid     = str(guild.id)
        ch_id   = get_cfg(guild.id, "birthday_channel")
        if not ch_id: continue
        ch = guild.get_channel(int(ch_id))
        if not ch: continue
        for uid, date in birthdays_db.get(gid, {}).items():
            if date == today_str:
                member = guild.get_member(int(uid))
                if not member: continue
                e = discord.Embed(
                    title="🎂  Joyeux Anniversaire !",
                    description=(
                        f"## 🎉 {member.mention}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Toute l'équipe Kozakura te souhaite un **joyeux anniversaire** ! 🌸🎊"
                    ),
                    color=0xFF89B4,
                    timestamp=datetime.utcnow()
                )
                e.set_thumbnail(url=member.display_avatar.url)
                e.set_footer(text="Kozakura  •  Bon anniversaire !")
                await ch.send(content=member.mention, embed=e)


@bot.listen("on_ready")
async def start_birthday_checker():
    if not check_birthdays.is_running():
        check_birthdays.start()


# ══════════════════════════════════════════════════════════════════════════════
# 🔨 BAN TEMPORAIRE
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def tempban(ctx, member: discord.Member = None, duration: str = "1h", *, reason="Aucune raison"):
    """!tempban @membre [durée: 30m/2h/1j] [raison] — Ban temporaire"""
    if member is None:
        return await ctx.send("❌ Usage : `!tempban @membre [durée] [raison]`", delete_after=5)
    if not has_sanction_role(ctx.author, ROLES_BAN):
        return await ctx.send("❌ Tu n'as pas la permission de bannir.", delete_after=5)
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send("❌ Je ne peux pas bannir ce membre (hiérarchie des rôles).", delete_after=5)
    units = {"s": 1, "m": 60, "h": 3600, "j": 86400}
    unit  = duration[-1].lower()
    try:
        secs = int(duration[:-1]) * units.get(unit, 3600)
    except ValueError:
        return await ctx.send("❌ Format de durée invalide. Ex: `30m`, `2h`, `1j`", delete_after=5)
    unban_at = (datetime.utcnow() + timedelta(seconds=secs)).isoformat()
    gid = str(ctx.guild.id); uid = str(member.id)
    await dm(member, "🔨 Tu as été banni temporairement",
        f"**Serveur :** {ctx.guild.name}\n**Durée :** {duration}\n**Raison :** {reason}\n\nTu seras automatiquement débanni.",
        color=discord.Color.dark_red())
    try:
        await member.ban(reason=f"[TempBan {duration}] {reason}", delete_message_days=1)
    except discord.Forbidden:
        return await ctx.send("❌ Permission refusée.", delete_after=5)
    tempbans_db.setdefault(gid, {})[uid] = {"unban_at": unban_at, "reason": reason, "by": str(ctx.author.id)}
    save_json("tempbans.json", tempbans_db)
    e = discord.Embed(
        title="🔨  Ban Temporaire",
        description=(
            f"**Membre :** {member.mention} (`{member.id}`)\n"
            f"**Durée :** {duration}\n"
            f"**Raison :** {reason}\n"
            f"**Débanni le :** <t:{int((datetime.utcnow() + timedelta(seconds=secs)).timestamp())}:F>"
        ),
        color=discord.Color.dark_red(), timestamp=datetime.utcnow()
    )
    e.set_footer(text=f"Par {ctx.author}  •  {ctx.guild.name}")
    await ctx.send(embed=e)
    e_log = await log_sanction(ctx.guild, member, "TempBan", reason, ctx.author, extra=f"Durée : {duration}")
    _ = e_log  # already sent inside log_sanction


@tasks.loop(minutes=1)
async def check_tempbans():
    now = datetime.utcnow()
    for gid, bans in list(tempbans_db.items()):
        guild = discord.utils.get(bot.guilds, id=int(gid))
        if not guild: continue
        for uid, data in list(bans.items()):
            unban_at = datetime.fromisoformat(data["unban_at"])
            if now >= unban_at:
                try:
                    user = await bot.fetch_user(int(uid))
                    await guild.unban(user, reason="[TempBan] Durée expirée")
                    try:
                        dm_e = discord.Embed(
                            title="✅ Tu as été débanni",
                            description=f"**Serveur :** {guild.name}\nTon ban temporaire a expiré.",
                            color=discord.Color.green())
                        await user.send(embed=dm_e)
                    except Exception: pass
                except Exception: pass
                del tempbans_db[gid][uid]
                save_json("tempbans.json", tempbans_db)


@bot.listen("on_ready")
async def start_tempban_checker():
    if not check_tempbans.is_running():
        check_tempbans.start()


# ══════════════════════════════════════════════════════════════════════════════
# 👋 MESSAGE DE DÉPART
# ══════════════════════════════════════════════════════════════════════════════

@bot.listen("on_member_remove")
async def send_leave_message(member: discord.Member):
    if member.bot: return
    guild  = member.guild
    ch_id  = get_cfg(guild.id, "welcome_channel")
    if not ch_id: return
    ch = guild.get_channel(int(ch_id))
    if not ch: return
    SAKURA_PINK = 0xFF89B4
    e = discord.Embed(
        description=(
            f"## 👋  Au revoir, {member.mention}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**{member.display_name}** a quitté le serveur.\n"
            f"Il reste **{guild.member_count}** membres."
        ),
        color=SAKURA_PINK,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Kozakura  •  {guild.name}", icon_url=guild.me.display_avatar.url)
    await ch.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🔥 STREAK
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def streak(ctx, member: discord.Member = None):
    """!streak [@membre] — Affiche le streak quotidien"""
    member = member or ctx.author
    gid = str(ctx.guild.id); uid = str(member.id)
    s_data     = streaks_db.get(gid, {}).get(uid, {})
    streak_val = s_data.get("streak", 0)
    last       = s_data.get("last_date") or "Jamais"
    bonus      = STREAK_BONUS_XP if streak_val > 0 else 0
    e = discord.Embed(
        description=(
            f"## 🔥  Streak de {member.display_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**{streak_val}** jour(s) consécutifs\n"
            f"Bonus XP actif : `+{bonus}` XP par message"
        ),
        color=0xFF6B35,
        timestamp=datetime.utcnow()
    )
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📅 Dernier message", value=last[:10] if last != "Jamais" else "Jamais", inline=True)
    e.add_field(name="🎯 Bonus XP",        value=f"`+{bonus}` XP",                            inline=True)
    e.set_footer(text=f"Kozakura XP  •  {ctx.guild.name}")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 👤 USERINFO
# ══════════════════════════════════════════════════════════════════════════════

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    """!userinfo [@membre] — Fiche complète et belle d'un membre"""
    member = member or ctx.author
    gid = str(ctx.guild.id); uid = str(member.id)
    xp      = xp_db.get(gid, {}).get(uid, 0)
    lvl     = get_level(xp)
    warns   = len(warnings_db.get(gid, {}).get(uid, []))
    gdata   = xp_db.get(gid, {})
    sorted_lb = sorted(gdata.items(), key=lambda x: x[1], reverse=True)
    rank_pos  = next((i + 1 for i, (u, _) in enumerate(sorted_lb) if u == uid), "?")
    streak_val = streaks_db.get(gid, {}).get(uid, {}).get("streak", 0)
    roles   = [r.mention for r in member.roles if r.name != "@everyone"]
    created = member.created_at.strftime("%d/%m/%Y")
    joined  = member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?"
    account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    SAKURA_PINK = 0xFF89B4
    e = discord.Embed(
        description=(
            f"## {member.mention}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=SAKURA_PINK if not member.color.value else member.color,
        timestamp=datetime.utcnow()
    )
    e.set_author(name=f"{member}  •  {member.id}", icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="📅 Compte créé",   value=f"{created}\n(il y a `{account_age}` jours)", inline=True)
    e.add_field(name="📥 Rejoint le",    value=joined,                                         inline=True)
    e.add_field(name="🤖 Bot",           value="Oui" if member.bot else "Non",                 inline=True)
    e.add_field(name="⭐ Niveau XP",     value=f"Niv. `{lvl}`  •  `{xp}` XP",                 inline=True)
    e.add_field(name="🏆 Classement",    value=f"#{rank_pos}",                                 inline=True)
    e.add_field(name="🔥 Streak",        value=f"`{streak_val}` jours",                        inline=True)
    e.add_field(name="⚠️ Avertissements", value=f"`{warns}`",                                  inline=True)
    e.add_field(name="💎 Booster",       value="Oui 💎" if member.premium_since else "Non",    inline=True)
    e.add_field(name=f"🎭 Rôles `({len(roles)})`",
        value=", ".join(roles[:6]) + ("…" if len(roles) > 6 else "") if roles else "*aucun*",
        inline=False)
    e.set_footer(text=f"Kozakura  •  {ctx.guild.name}")
    await ctx.send(embed=e)


# ══════════════════════════════════════════════════════════════════════════════
# 🎙️ VOCAL TEMPORAIRE — PANEL UI
# ══════════════════════════════════════════════════════════════════════════════

class TempVocalRenameModal(discord.ui.Modal, title="✏️ Renommer ton vocal"):
    name = discord.ui.TextInput(
        label="Nouveau nom du vocal",
        placeholder="Ex: Soirée gaming, Détente, Zone privée...",
        min_length=1, max_length=50,
        style=discord.TextStyle.short
    )

    def __init__(self, guild_id, channel_id):
        super().__init__()
        self.guild_id   = guild_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = bot.get_guild(self.guild_id)
        ch    = guild.get_channel(self.channel_id) if guild else None
        if not ch:
            return await interaction.response.send_message("❌ Vocal introuvable.", ephemeral=True)
        if temp_voice_channels.get(ch.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Tu n'es pas le propriétaire.", ephemeral=True)
        await ch.edit(name=self.name.value)
        await interaction.response.send_message(f"✅ Vocal renommé en **{self.name.value}**.", ephemeral=True)

class TempVocalLimitModal(discord.ui.Modal, title="👥 Limite de membres"):
    limit = discord.ui.TextInput(
        label="Limite (0 = illimité, max 99)",
        placeholder="Ex: 5",
        min_length=1, max_length=2,
        style=discord.TextStyle.short
    )

    def __init__(self, guild_id, channel_id):
        super().__init__()
        self.guild_id   = guild_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = bot.get_guild(self.guild_id)
        ch    = guild.get_channel(self.channel_id) if guild else None
        if not ch:
            return await interaction.response.send_message("❌ Vocal introuvable.", ephemeral=True)
        if temp_voice_channels.get(ch.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Tu n'es pas le propriétaire.", ephemeral=True)
        try:
            val = max(0, min(99, int(self.limit.value)))
        except ValueError:
            return await interaction.response.send_message("❌ Entre un nombre entre 0 et 99.", ephemeral=True)
        await ch.edit(user_limit=val)
        label = f"**{val}** membres max" if val > 0 else "**Illimité**"
        await interaction.response.send_message(f"✅ Limite définie : {label}.", ephemeral=True)

class TempVocalPanel(discord.ui.View):
    def __init__(self, guild_id, channel_id):
        super().__init__(timeout=None)
        self.guild_id   = guild_id
        self.channel_id = channel_id

    def _get_ch(self):
        guild = bot.get_guild(self.guild_id)
        return guild.get_channel(self.channel_id) if guild else None

    @discord.ui.button(label="✏️ Renommer", style=discord.ButtonStyle.blurple)
    async def rename_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(TempVocalRenameModal(self.guild_id, self.channel_id))

    @discord.ui.button(label="🔒 Verrouiller", style=discord.ButtonStyle.grey)
    async def lock_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        ch = self._get_ch()
        if not ch:
            return await interaction.response.send_message("❌ Vocal introuvable.", ephemeral=True)
        if temp_voice_channels.get(ch.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Tu n'es pas le propriétaire.", ephemeral=True)
        locked = ch.overwrites_for(interaction.guild.default_role).connect is False
        if locked:
            await ch.set_permissions(interaction.guild.default_role, connect=True)
            btn.label = "🔒 Verrouiller"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("🔓 Vocal déverrouillé.", ephemeral=True)
        else:
            await ch.set_permissions(interaction.guild.default_role, connect=False)
            btn.label = "🔓 Déverrouiller"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("🔒 Vocal verrouillé.", ephemeral=True)

    @discord.ui.button(label="👥 Limite", style=discord.ButtonStyle.grey)
    async def limit_btn(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(TempVocalLimitModal(self.guild_id, self.channel_id))

    @discord.ui.button(label="❌ Fermer", style=discord.ButtonStyle.red)
    async def close_btn(self, interaction: discord.Interaction, _):
        ch = self._get_ch()
        if not ch:
            return await interaction.response.send_message("❌ Vocal déjà supprimé.", ephemeral=True)
        if temp_voice_channels.get(ch.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Tu n'es pas le propriétaire.", ephemeral=True)
        temp_voice_channels.pop(ch.id, None)
        await ch.delete(reason="Fermé par le propriétaire")
        await interaction.response.send_message("✅ Vocal fermé.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# 🎙️ VOCAL TEMPORAIRE — GESTION
# ══════════════════════════════════════════════════════════════════════════════

def _get_temp_channel(ctx):
    """Retourne le salon temp de l'auteur s'il en est le propriétaire."""
    if ctx.author.voice and ctx.author.voice.channel:
        ch = ctx.author.voice.channel
        if temp_voice_channels.get(ch.id) == ctx.author.id:
            return ch
    return None

@bot.command(name="settempcreate")
@commands.has_permissions(administrator=True)
async def settempcreate(ctx, *, arg: str):
    """!settempcreate #salon — Définit le salon 'Rejoindre pour créer un vocal'"""
    channel = await resolve_channel(ctx, arg)
    if not channel:
        return await ctx.send("❌ Salon introuvable.")
    set_cfg(ctx.guild.id, "temp_voice_create_channel", channel.id)
    await ctx.send(
        f"✅ Salon configuré : **{channel.name}**\n"
        f"Quand quelqu'un le rejoint, un vocal temporaire lui est créé automatiquement."
    )

@bot.command(name="vlock")
async def vlock(ctx):
    """!vlock — Verrouille ton vocal (personne ne peut rejoindre)"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    await ch.set_permissions(ctx.guild.default_role, connect=False)
    e = discord.Embed(description=f"🔒 **{ch.name}** — Vocal verrouillé.", color=discord.Color.red())
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vunlock")
async def vunlock(ctx):
    """!vunlock — Déverrouille ton vocal"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    await ch.set_permissions(ctx.guild.default_role, connect=True)
    e = discord.Embed(description=f"🔓 **{ch.name}** — Vocal déverrouillé.", color=discord.Color.green())
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vrename")
async def vrename(ctx, *, name: str):
    """!vrename [nom] — Renomme ton vocal"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    await ch.edit(name=name[:100])
    e = discord.Embed(description=f"✏️ Vocal renommé en **{name[:100]}**.", color=0xFF89B4)
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vlimit")
async def vlimit(ctx, limit: int):
    """!vlimit [0-99] — Définit la limite d'utilisateurs (0 = illimité)"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    limit = max(0, min(99, limit))
    await ch.edit(user_limit=limit)
    val = f"**{limit}** utilisateurs" if limit > 0 else "Illimité"
    e = discord.Embed(description=f"👥 Limite définie : {val}.", color=0xFF89B4)
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vkick")
async def vkick(ctx, target: discord.Member):
    """!vkick @membre — Expulse un membre de ton vocal"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    if target not in ch.members:
        return await ctx.send("❌ Ce membre n'est pas dans ton vocal.", delete_after=5)
    await target.move_to(None, reason=f"Expulsé du vocal par {ctx.author}")
    e = discord.Embed(description=f"👢 **{target.display_name}** a été expulsé du vocal.", color=discord.Color.orange())
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vinvite")
async def vinvite(ctx, target: discord.Member):
    """!vinvite @membre — Autorise un membre à rejoindre ton vocal verrouillé"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    await ch.set_permissions(target, connect=True)
    e = discord.Embed(description=f"✅ **{target.display_name}** peut rejoindre ton vocal.", color=discord.Color.green())
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vtransfer")
async def vtransfer(ctx, target: discord.Member):
    """!vtransfer @membre — Transfère la propriété de ton vocal"""
    ch = _get_temp_channel(ctx)
    if not ch:
        return await ctx.send("❌ Tu dois être dans ton propre vocal temporaire.", delete_after=5)
    if target not in ch.members:
        return await ctx.send("❌ Ce membre doit être dans le vocal.", delete_after=5)
    temp_voice_channels[ch.id] = target.id
    await ch.set_permissions(ctx.author, overwrite=None)
    await ch.set_permissions(target, connect=True, speak=True, mute_members=True,
        deafen_members=True, move_members=True, manage_channels=True)
    e = discord.Embed(
        description=f"👑 Propriété transférée à **{target.display_name}**.",
        color=0xFF89B4
    )
    await ctx.send(embed=e, delete_after=10)

@bot.command(name="vinfo")
async def vinfo(ctx):
    """!vinfo — Infos sur ton vocal temporaire"""
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ Tu n'es pas en vocal.", delete_after=5)
    ch = ctx.author.voice.channel
    owner_id = temp_voice_channels.get(ch.id)
    if not owner_id:
        return await ctx.send("❌ Ce n'est pas un vocal temporaire.", delete_after=5)
    owner = ctx.guild.get_member(owner_id)
    e = discord.Embed(title=f"🎙️ {ch.name}", color=0xFF89B4, timestamp=datetime.utcnow())
    e.add_field(name="👑 Propriétaire", value=owner.mention if owner else f"`{owner_id}`", inline=True)
    e.add_field(name="👥 Membres",      value=str(len(ch.members)), inline=True)
    e.add_field(name="🔢 Limite",       value=str(ch.user_limit) if ch.user_limit else "Illimité", inline=True)
    locked = ctx.guild.default_role in ch.overwrites and ch.overwrites[ctx.guild.default_role].connect is False
    e.add_field(name="🔒 Statut", value="Verrouillé" if locked else "Ouvert", inline=True)
    e.set_footer(text="Kozakura • Vocal temporaire")
    await ctx.send(embed=e)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass