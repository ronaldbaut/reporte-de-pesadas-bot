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

    # Cancelación flexible
    if any(palabra in content for palabra in ["cancelar", "canelar", "cancel", "cancela", "cancelar reporte", "canelar reporte"]):
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

# ================== FUNCIÓN QUE CONSULTA A GROK ==================
async def consultar_grok(pregunta: str, respuesta_usuario: str) -> dict:
    system_prompt = """
Eres un supervisor estricto de reportes de pesadas en una fábrica de helados.

Responde ÚNICAMENTE con un JSON válido:

{
  "respuesta_valida": true o false,
  "mensaje": null o "texto"
}

Reglas:
- Si la respuesta es muy corta, vacía, irrelevante o no responde claramente la pregunta → respuesta_valida = false
- Cuando sea inválida, el campo "mensaje" debe decir de forma clara, simple y contundente qué falta.
  Ejemplos:
  - "Te falta decirme la cantidad en kilos."
  - "No me dijiste cuántos kilos se usaron."
  - "Responde con un número de kilos."
- Sé directo y corto.
- Si la respuesta es válida, pon "mensaje": null
"""

    user_content = f"""
Pregunta actual:
{pregunta}

Respuesta del trabajador:
"{respuesta_usuario}"
"""

    try:
        response = client.chat.completions.create(
            model="grok-4-1-fast",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error al consultar Grok: {e}")
        return {
            "respuesta_valida": True,
            "mensaje": None
        }

# ================== MANEJO DE RESPUESTAS ==================
async def manejar_respuesta(message):
    channel_id = str(message.channel.id)
    state = conversation_state[channel_id]
    
    pregunta_actual = PREGUNTAS[state["pregunta_actual"]]
    
    # Reacción en vez de mensaje ✅
    try:
        await message.add_reaction("✅")
    except:
        pass

    # Consultamos a Grok
    decision = await consultar_grok(pregunta_actual, message.content)

    # Si la respuesta no es válida → regaño y no avanzamos
    if not decision.get("respuesta_valida", True):
        mensaje = decision.get("mensaje") or "Tu respuesta está incompleta. Responde correctamente lo que se te preguntó."
        await message.channel.send(mensaje)
        return

    # ===== Respuesta válida → guardamos y avanzamos =====
    state["respuestas"].append(message.content)
    state["pregunta_actual"] += 1
    
    if state["pregunta_actual"] < len(PREGUNTAS):
        pregunta_num = state["pregunta_actual"] + 1
        await message.channel.send(
            f"**Pregunta {pregunta_num} de {len(PREGUNTAS)}:**\n"
            f"{PREGUNTAS[state['pregunta_actual']]}"
        )
    else:
        await message.channel.send(
            "✅ **Reporte de Pesadas completado.**\n\n"
            "Todas las respuestas han sido registradas. ¡Gracias!"
        )
        del conversation_state[channel_id]

# ================== INICIO ==================
bot.run(DISCORD_TOKEN)
