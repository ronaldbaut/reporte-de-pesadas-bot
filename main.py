import discord
from discord.ext import commands
import os
from openai import OpenAI
import json

print(">>> Iniciando bot de reporte de pesadas...")

# ================== CONFIGURACIÓN ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cliente de xAI (Grok)
client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1"
)

# ================== ESTADO DE CONVERSACIÓN ==================
conversation_state = {}

# ================== LISTA DE PREGUNTAS ==================
PREGUNTAS = [
    "¿Cuántos kilos de azúcar se usaron?",
    "¿Cuántos kilos de leche en polvo se usaron?",
    "¿Cuántos kilos de grasa se usaron?",
    "¿Cuántos kilos de estabilizante se usaron?",
    "¿Cuántos kilos de saborizantes se usaron?",
    "¿Cuántos kilos de colorantes se usaron?",
    "¿Cuántos kilos de cacao se usaron?",
    "¿Cuántos kilos de vainilla se usaron?",
    "¿Cuántos kilos de otros ingredientes se usaron?",
    "¿Cuántos kilos de base de helado se prepararon?",
    "¿Cuántos kilos de mezcla final se obtuvieron?",
    "¿Cuántos kilos de merma hubo?",
    "¿Cuántos kilos de producto terminado se obtuvieron?",
    "¿Cuántos kilos de producto se enviaron a congelación?",
    "¿Cuántos kilos de producto se enviaron a empaque?",
    "¿Cuántos kilos de producto se enviaron a venta?",
    "¿Observaciones adicionales del proceso de pesadas?"
]

# ================== COMANDO SLASH ==================
@bot.tree.command(name="reporte-pesadas", description="Inicia el Reporte de Pesadas")
async def reporte_pesadas_slash(interaction: discord.Interaction):
    channel = interaction.channel
    conversation_state[str(channel.id)] = {
        "pregunta_actual": 0,
        "respuestas": []
    }
    
    await interaction.response.send_message(
        f"**Reporte de Pesadas iniciado.**\n\n"
        f"**Pregunta 1 de {len(PREGUNTAS)}:**\n"
        f"{PREGUNTAS[0]}\n\n"
        f"_Escribe **cancelar** o **cancelar reporte** en cualquier momento para detenerlo._"
    )

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados")
    except Exception as e:
        print(f"❌ Error al sincronizar: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    content = message.content.strip().lower()
    channel_id = str(message.channel.id)

    # Cancelar reporte
    if "cancelar" in content:
        if channel_id in conversation_state:
            del conversation_state[channel_id]
            await message.channel.send("✅ Reporte de Pesadas cancelado.")
        return

    # Iniciar por texto
    if content in ["reporte de pesadas", "iniciar reporte de pesadas"]:
        conversation_state[channel_id] = {
            "pregunta_actual": 0,
            "respuestas": []
        }
        await message.channel.send(
            f"**Reporte de Pesadas iniciado.**\n\n"
            f"**Pregunta 1 de {len(PREGUNTAS)}:**\n"
            f"{PREGUNTAS[0]}\n\n"
            f"_Escribe **cancelar** o **cancelar reporte** en cualquier momento para detenerlo._"
        )
        return

    # Responder pregunta
    if channel_id in conversation_state:
        await manejar_respuesta(message)

# ================== MANEJO DE RESPUESTAS ==================
async def manejar_respuesta(message):
    channel_id = str(message.channel.id)
    state = conversation_state[channel_id]
    
    # Guardar respuesta
    state["respuestas"].append(message.content)
    
    # Enviar check
    await message.channel.send("✅")
    
    # Avanzar a siguiente pregunta
    state["pregunta_actual"] += 1
    
    if state["pregunta_actual"] < len(PREGUNTAS):
        # Hay más preguntas
        pregunta_num = state["pregunta_actual"] + 1
        await message.channel.send(
            f"**Pregunta {pregunta_num} de {len(PREGUNTAS)}:**\n"
            f"{PREGUNTAS[state['pregunta_actual']]}"
        )
    else:
        # Reporte completado
        await message.channel.send(
            "✅ **Reporte de Pesadas completado.**\n\n"
            "Todas las respuestas han sido registradas. ¡Gracias!"
        )
        del conversation_state[channel_id]

# ================== INICIO ==================
bot.run(DISCORD_TOKEN)
