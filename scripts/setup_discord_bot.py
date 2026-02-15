#!/usr/bin/env python3
"""Helper script to set up a Discord bot for RPG Scribe.

This script guides the user through the process of configuring
the Discord bot token and required permissions.
"""

from __future__ import annotations

import sys


REQUIRED_PERMISSIONS = [
    ("Read Messages / View Channels", "Para ver canales de texto"),
    ("Send Messages", "Para publicar resumenes"),
    ("Embed Links", "Para enviar embeds con formato"),
    ("Connect", "Para unirse a canales de voz"),
    ("Speak", "No necesario, pero requerido por Discord para voz"),
    ("Use Voice Activity", "Para escuchar audio de los jugadores"),
]

REQUIRED_INTENTS = [
    ("Message Content", "Para comandos de texto (opcional con slash commands)"),
    ("Voice States", "Para detectar quien esta en el canal de voz"),
    ("Guild Members", "Para mapear IDs de Discord a nombres"),
]

BOT_PERMISSIONS_INT = 3148800  # Connect + Speak + View + Send + Embed + VAD


def main() -> None:
    print("=" * 60)
    print("  RPG Scribe — Discord Bot Setup")
    print("=" * 60)
    print()
    print("Este script te guia para configurar el bot de Discord.")
    print()

    # Step 1: Create application
    print("PASO 1: Crear la aplicacion de Discord")
    print("-" * 40)
    print("1. Ve a https://discord.com/developers/applications")
    print("2. Haz clic en 'New Application'")
    print("3. Nombra la app 'RPG Scribe' (o como prefieras)")
    print("4. Acepta los terminos")
    print()
    input("Pulsa Enter cuando hayas creado la aplicacion...")
    print()

    # Step 2: Bot token
    print("PASO 2: Obtener el token del bot")
    print("-" * 40)
    print("1. En el menu lateral, haz clic en 'Bot'")
    print("2. Haz clic en 'Reset Token' o 'Add Bot'")
    print("3. Copia el token (NO lo compartas con nadie)")
    print()
    token = input("Pega el token aqui (se guardara en .env): ").strip()

    if not token:
        print("Error: El token no puede estar vacio.")
        sys.exit(1)

    # Step 3: Privileged intents
    print()
    print("PASO 3: Activar Privileged Gateway Intents")
    print("-" * 40)
    print("En la seccion 'Bot' del portal de desarrolladores:")
    print()
    for intent, reason in REQUIRED_INTENTS:
        print(f"  [x] {intent} — {reason}")
    print()
    print("Activa estos intents y guarda los cambios.")
    input("Pulsa Enter cuando hayas activado los intents...")
    print()

    # Step 4: Invite URL
    print("PASO 4: Invitar el bot a tu servidor")
    print("-" * 40)
    print("1. Ve a 'OAuth2' > 'URL Generator'")
    print("2. Selecciona los scopes: bot, applications.commands")
    print("3. Selecciona estos permisos:")
    print()
    for perm, reason in REQUIRED_PERMISSIONS:
        print(f"  [x] {perm} — {reason}")
    print()
    print("O usa esta URL directa (reemplaza CLIENT_ID):")
    print()
    print(
        f"  https://discord.com/oauth2/authorize"
        f"?client_id=TU_CLIENT_ID"
        f"&permissions={BOT_PERMISSIONS_INT}"
        f"&scope=bot+applications.commands"
    )
    print()
    input("Pulsa Enter cuando hayas invitado el bot...")
    print()

    # Step 5: Write .env file
    print("PASO 5: Guardar configuracion")
    print("-" * 40)

    channel_id = input(
        "ID del canal de texto para resumenes (opcional, Enter para omitir): "
    ).strip()

    env_lines = [
        f"DISCORD_BOT_TOKEN={token}",
        "# OPENAI_API_KEY=sk-...",
        "# ANTHROPIC_API_KEY=sk-ant-...",
    ]
    if channel_id:
        env_lines.append(f"DISCORD_SUMMARY_CHANNEL_ID={channel_id}")

    env_content = "\n".join(env_lines) + "\n"

    try:
        with open(".env", "w") as f:
            f.write(env_content)
        print()
        print("Archivo .env creado con exito!")
    except OSError as exc:
        print(f"Error al escribir .env: {exc}")
        print("Crea el archivo manualmente con:")
        print()
        print(env_content)

    print()
    print("=" * 60)
    print("  Configuracion completada!")
    print("=" * 60)
    print()
    print("Para ejecutar RPG Scribe:")
    print("  rpg-scribe --campaign config/campaigns/mi-campana.toml")
    print()
    print("O con python:")
    print("  python -m rpg_scribe --campaign config/campaigns/mi-campana.toml")


if __name__ == "__main__":
    main()
