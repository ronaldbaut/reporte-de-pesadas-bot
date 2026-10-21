import discord
from discord.ext import commands
import os
import traceback
import unicodedata
from openai import OpenAI
import json
import re
from typing import Optional

print(">>> Iniciando bot de reporte de pesadas...")

# ================== CONFIGURACIÓN ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("❌ ERROR: Falta la variable de entorno DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
)

# Estado por canal:
# {
#   "user_id": int,
#   "paso": int,
#   "answers": { "0": "...", ... },
#   "buffer": str,
#   "fotos_tx": None | { productos, idx, paso_foto, capturas },
# }
conversation_state = {}

EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".bmp"}
PRODUCTOS_TRANSFER_CONOCIDOS = [
    "crema de leche",
    "estabilizante",
    "arequipe",
    "glucosa",
    "azúcar",
    "azucar",
    "leche",
    "suero",
    "cacao",
    "conos",
    "cono",
]

# Los conos se reportan, pero no hay foto que pedir ni que exigir.
# El emparejamiento (cono/conos, mayúsculas, acentos) vive en _es_producto_conos.
REGLA_CONOS_SIN_FOTO = (
    "Los conos (singular o plural: cono/conos; mayúsculas y acentos no importan) "
    "NO requieren foto. No pidas la foto de los conos y no dejes el reporte "
    "bloqueado ni incompleto por no tenerla. "
    "Cualquier otro producto de la transferencia sigue exigiendo sus fotos igual que siempre."
)

# ================== PREGUNTAS + REGLAS ==================
# tipo:
#   cantidad      → número / peso (puede ir con unidades, potes, multilínea)
#   adicionales   → lista producto + cantidad
#   transferencia → no / sí + productos y cantidades (recargas de bultos)
#   si_no         → sí/no
#   stock_bajo    → productos cerca de acabarse (acepta "no hay" = 0)
#   abierta       → texto libre; "no"/"ninguna" OK
#   foto          → una imagen adjunta obligatoria; sin ella no avanza ni cierra
#
# La foto del material de envasado es un paso fijo (siempre una, siempre
# obligatoria). Por eso es pregunta numerada y entra en el total: queda
# como la 18, justo después del sí/no de las tapitas (la 17). No va pegada
# a la 17 ni a la cola de fotos de la transferencia: esa cola es variable
# y los conos siguen sin foto.
TEXTO_FOTO_MATERIAL_ENVASADO = (
    "📸 Envía una foto de cómo dejaste organizado el material para envasado, "
    "donde se vean claramente los nombres de las tapitas."
)

PREGUNTAS = [
    {
        "texto": "¿Con cuánta leche comenzó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Válido: número de cantidad/peso (9.30, 14.40, 4,30). "
            "Unidades opcionales (kg, bultos). "
            "Inválido: solo punto o sin número."
        ),
    },
    {
        "texto": "¿Con cuánta leche terminó el día?",
        "tipo": "cantidad",
        "reglas": "Igual que leche inicial. Número de cierre válido.",
    },
    {
        "texto": "¿Con cuánto azúcar comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto azúcar terminó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto suero comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto suero terminó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso. Válido.",
    },
    {
        "texto": "¿Con cuánto cacao comenzó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Válido si hay un número de cantidad (3.217, 2.197, 4.104). "
            "Puede traer 'pote', decimales con punto o coma, y líneas extra "
            "como 2N 2C 2G (conteos de potes/líneas). "
            "CRÍTICO: '3.217 pote' + '2N 2C 2G' YA tiene la cantidad → válido. "
            "NO digas 'no me dijiste con cuánto comenzó' si hay un número claro. "
            "Foto + número también válido."
        ),
    },
    {
        "texto": "¿Con cuánto cacao terminó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Igual que cacao inicial. Número + notas/pote/líneas extra OK. "
            "No rechaces multilínea si el número está."
        ),
    },
    {
        "texto": "¿Con cuánto arequipe comenzó el día?",
        "tipo": "cantidad",
        "reglas": "Número de cantidad/peso (kg o potes). Válido.",
    },
    {
        "texto": "¿Con cuánto arequipe terminó el día?",
        "tipo": "cantidad",
        "reglas": (
            "Número válido, incluido 0 o 0.00 si el pote en uso quedó vacío. "
            "Si aclara potes nuevos aparte, mejor, pero no es obligatorio."
        ),
    },
    {
        "texto": (
            "¿Hubo transferencia del almacén de bultos al almacén de pesadas hoy? "
            "Si sí, indica qué productos se transfirieron (por ejemplo leche, azúcar, cacao, "
            "estabilizante, conos) y en qué cantidades. Si no hubo, responde **No**."
        ),
        "tipo": "transferencia",
        "reglas": (
            "Válido 'No' / 'No hubo' / 'Ninguna' si no hubo transferencia. "
            "Si sí hubo: lista producto + cantidad (ej. 'Leche 25.25, azúcar 1 bulto, "
            "cacao 1 bulto, estabilizante 0,8515, 1 caja de conos'). "
            "Eso es lo que antes se olvidaba reportar como 'recargas de bultos'. "
            "NO exijas un solo número total. El desglose ES la respuesta correcta. "
            "Si dice 'sí' sin productos, pide qué y cuánto. "
            "NO pidas las fotos aquí: el bot las pide después, producto por producto, "
            "excepto los conos. "
            + REGLA_CONOS_SIN_FOTO
        ),
    },
    {
        "texto": (
            "¿Qué adicionales se dejaron hoy? Indica producto y cantidad "
            "(ej. leche, azúcar, glucosa, crema de leche). Si no hubo, responde **No** o **0**."
        ),
        "tipo": "adicionales",
        "reglas": (
            "Válido: lista con producto y cantidad "
            "('270 azúcar café, 1300 leche, 63 azúcar bianchi, 18 glucosa'). "
            "Válido: 'No', 'Ninguno', '0'. "
            "CRÍTICO: NO digas 'responde con el número o la cantidad' rechazando el desglose. "
            "El desglose ES lo que se necesita. "
            "NO fuerces un único número total (ej. '4') que borre el detalle."
        ),
    },
    {
        "texto": "¿Las bandejas quedaron marcadas correctamente?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. Puede matizar.",
    },
    {
        "texto": "¿Recogiste los vasitos y las tapas del día anterior?",
        "tipo": "si_no",
        "reglas": "Sí/No válido.",
    },
    {
        "texto": "¿Anotaste en el cuaderno los vasos entregados hoy?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. 'Lo dejé en el cuaderno, no había internet' ES válido.",
    },
    {
        "texto": "¿Dejaste las tapitas para los vasitos de helado que se van a producir hoy?",
        "tipo": "si_no",
        "reglas": "Sí/No válido.",
    },
    {
        "texto": "¿Las tapitas están correctamente ordenadas por líneas y sabores?",
        "tipo": "si_no",
        "reglas": "Sí/No válido. Puede reportar un error (ej. tapas de coco en chocooreo).",
    },
    {
        "texto": TEXTO_FOTO_MATERIAL_ENVASADO,
        "tipo": "foto",
        "clave": "foto_material_envasado",
        "reglas": (
            "Obligatoria. Solo vale con una imagen adjunta. "
            "Sin esa foto el reporte no avanza ni queda completo. "
            "Un texto solo, aunque diga que sí, no basta. "
            "No tiene relación con la foto de transferencia ni con la excepción de conos."
        ),
    },
    {
        "texto": (
            "¿Qué productos están cerca de acabarse? Indica el producto y la cantidad "
            "aproximada que queda (si no hay, pon 0 o 'no hay')."
        ),
        "tipo": "stock_bajo",
        "reglas": (
            "Válido: lista producto + cantidad o 'no hay' / 0. "
            "'Bandejas de un litro no hay' ES válido (= 0). "
            "'Bianchi quedan 4' ES válido. "
            "Si pide una planilla o algo operativo sin listar stock, pide al menos un producto "
            "o que diga 'ninguno cerca de acabarse'. "
            "NO rechaces 'no hay' por no traer un número explícito."
        ),
    },
    {
        "texto": "¿Hubo alguna incidencia, problema o área de mejora hoy?",
        "tipo": "abierta",
        "reglas": "'No' / 'Ninguna' ES válido. Descripción de incidencia también.",
    },
    {
        "texto": (
            "¿Comentarios finales del día? "
            "(Puedes incluir pesadas que quedan, cacao por línea, recargas que faltaron anotar, etc.)"
        ),
        "tipo": "abierta",
        "reglas": (
            "'No' / 'Ninguno' ES válido. "
            "Listas tipo 'Dejó pesadas: 5N 2S…' o recargas ES válido y útil."
        ),
    },
]


# ================== HELPERS ==================
def _vacio_o_basura(texto: str, tiene_adjuntos: bool) -> bool:
    t = (texto or "").strip()
    if tiene_adjuntos and not t:
        return False
    if not t:
        return True
    return t.lower() in {".", "..", "...", "ok", "vale", "listo", "k", "ya", "-", "—"}


def _parece_cancelar(content_lower: str) -> bool:
    patrones = [
        r"^cancelar(\s+reporte)?$",
        r"^cancel(\s+report)?$",
        r"^cancela(r)?$",
        r"^canelar(\s+reporte)?$",
        r"^reporte\s+cancelado$",
        r"^detener(\s+reporte)?$",
    ]
    return any(re.match(p, content_lower) for p in patrones)


def _parece_inicio(content_lower: str) -> bool:
    return content_lower in {
        "reporte de pesadas",
        "iniciar reporte de pesadas",
        "inicio reporte de pesadas",
        "/inicio reporte de pesadas",
        "/ inicio reporte de pesadas",
    }


def _tiene_numero(texto: str) -> bool:
    if not texto:
        return False
    # Busca digitos con decimal opcional (punto o coma)
    patron = r"\d+(?:[.,]\d+)?"
    return re.search(patron, texto) is not None


def _es_no_hubo_vasitos(texto: str) -> bool:
    """True si responde que hoy no se hicieron vasitos / no hay / no (sin foto)."""
    t = re.sub(r"[^a-z\s]", " ", _sin_acentos((texto or "").lower()))
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) > 80:
        return False
    return re.match(r"^(no|nop|nada|ninguno|ninguna)\b", t) is not None or "no se hic" in t or "no hubo" in t or "no hay" in t


def _es_si_no_corto(texto: str) -> Optional[bool]:
    t = re.sub(r"[¡!?.]", "", (texto or "").strip().lower())
    if t in {"si", "sí", "yes", "s", "1", "correcto"}:
        return True
    if t in {"no", "n", "0", "nop", "ninguno", "ninguna", "nada"}:
        return False
    if re.match(r"^(si|sí)\b", t) and len(t) <= 60:
        return True
    if re.match(r"^no\b", t) and len(t) <= 60:
        return False
    return None


def _mensaje_inicio(user: discord.abc.User) -> str:
    n = len(PREGUNTAS)
    return (
        f"**Reporte de Pesadas iniciado** por {user.mention}\n\n"
        f"**Pregunta 1 de {n}:**\n"
        f"{PREGUNTAS[0]['texto']}\n\n"
        f"_Solo {user.display_name} puede responder este reporte._\n"
        f"_Escribe **cancelar** o **cancelar reporte** para detenerlo._"
    )


def _crear_estado(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "paso": 0,
        "answers": {},
        "buffer": "",
        "fotos_tx": None,
    }


def _es_respuesta_no_transferencia(texto: str) -> bool:
    """True solo si NO hubo recarga de bultos. Si hay productos, no es un 'no'."""
    if _productos_locales(texto):
        return False
    t = re.sub(r"[¡!?.]", "", (texto or "").strip().lower())
    if t in {
        "no",
        "n",
        "0",
        "nop",
        "ninguno",
        "ninguna",
        "nada",
        "no hubo",
        "no hubo nada",
        "sin transferencia",
    }:
        return True
    return bool(re.match(r"^(no hubo|no,?\s*ningun[oa]|sin transfer)\b", t))


def _adjuntos_imagen(message: discord.Message) -> list:
    imgs = []
    for a in message.attachments or []:
        nombre = (a.filename or "").lower()
        ctype = (a.content_type or "").lower()
        if ctype.startswith("image/") or any(nombre.endswith(ext) for ext in EXT_IMAGEN):
            imgs.append(a)
    return imgs


def _info_adjunto(adj) -> dict:
    return {
        "filename": adj.filename,
        "url": str(adj.url),
        "content_type": adj.content_type,
    }


# á/é/í/ó/ú/ü, no la eñe: «coño» no es un cono.
_TABLA_ACENTOS = str.maketrans(
    "áéíóúüÁÉÍÓÚÜàèìòùÀÈÌÒÙ",
    "aeiouuAEIOUUaeiouAEIOU",
)


def _sin_acentos(texto: str) -> str:
    t = unicodedata.normalize("NFC", texto or "")
    return t.translate(_TABLA_ACENTOS)


def _es_producto_conos(nombre: str) -> bool:
    """True para cono/conos, sin importar mayúsculas ni acentos.

    Cubre el nombre suelto ("Conos", "CÓNO") y frases ("caja de conos").
    Esos productos se anotan en el reporte y no piden foto.
    """
    n = _sin_acentos(nombre).lower()
    return re.search(r"\bconos?\b", n) is not None


def _productos_que_requieren_foto(productos: list) -> list:
    """Quita los conos. El resto conserva el orden y sigue pidiendo foto."""
    return [p for p in productos if p and not _es_producto_conos(str(p))]


def _rechazo_pide_foto_de_conos(mensaje: str, texto: str) -> bool:
    """True si el validador rechazó la respuesta pidiendo foto y el texto trae conos.

    Esa petición no puede frenar el reporte: la cantidad, si falta, se pide aparte.
    """
    msg = _sin_acentos(mensaje or "").lower()
    if not re.search(r"\bfotos?\b|\bimagen(?:es)?\b", msg):
        return False
    return any(_es_producto_conos(p) for p in _productos_locales(texto))


def _estado_fotos_si_aplica(productos: list) -> Optional[dict]:
    """Estado de la cola de fotos, o None si no hay nada que fotografiar.

    None (solo conos, o lista vacía) no bloquea el reporte ni lo deja incompleto.
    """
    con_foto = _productos_que_requieren_foto(productos)
    if not con_foto:
        return None
    return {
        "productos": con_foto,
        "idx": 0,
        "paso_foto": "nuevo",
        "capturas": {},
    }


def _titulo_producto(nombre: str) -> str:
    t = (nombre or "").strip()
    if not t:
        return "Producto"
    bajos = {"de", "del", "la", "el", "y"}
    partes = []
    for i, w in enumerate(t.split()):
        wl = w.lower()
        if i > 0 and wl in bajos:
            partes.append(wl)
        else:
            partes.append(wl.capitalize() if wl != "azúcar" else "Azúcar")
    return " ".join(partes)


def _productos_locales(texto: str) -> list:
    t = _sin_acentos(texto).lower()
    encontrados = []
    for p in PRODUCTOS_TRANSFER_CONOCIDOS:
        p_norm = _sin_acentos(p).lower()
        if p_norm == "leche":
            hay = re.search(r"(?<!crema de )\bleche\b", t)
        else:
            hay = re.search(rf"\b{re.escape(p_norm)}\b", t)
        if not hay:
            continue
        if p in {"azucar", "azúcar"}:
            nombre = "Azúcar"
        elif p in {"cono", "conos"}:
            nombre = "Conos"
        else:
            nombre = _titulo_producto(p)
        if nombre not in encontrados:
            encontrados.append(nombre)
    return encontrados


def _texto_pedir_foto(producto: str, cual: str) -> str:
    if cual == "nuevo":
        return (
            f"📦 **Transferencia — {producto}**\n"
            "Manda la foto del **bulto NUEVO en la báscula**, "
            "para ver cuánto pesa el contenido neto junto con el empaque."
        )
    return (
        f"📦 **Transferencia — {producto}**\n"
        "Ahora manda la foto del **empaque VACÍO** cuyo contenido neto se acabó."
    )


async def iniciar_reporte(channel, user: discord.abc.User) -> bool:
    """Inicia por texto. True si arrancó, False si ya había uno."""
    channel_id = str(channel.id)
    if channel_id in conversation_state:
        dueño = conversation_state[channel_id]["user_id"]
        await channel.send(
            f"Ya hay un reporte de pesadas en curso (iniciado por <@{dueño}>). "
            f"Termínenlo o escriban **cancelar reporte**."
        )
        return False

    conversation_state[channel_id] = _crear_estado(user.id)
    await channel.send(_mensaje_inicio(user))
    return True


# ================== SLASH ==================
# Discord exige responder la interacción en < 3 segundos.
# Si el bot está caído o tarda, el usuario ve: "La aplicación no respondió".
@bot.tree.command(name="reporte-pesadas", description="Inicia el Reporte de Pesadas")
async def reporte_pesadas_slash(interaction: discord.Interaction):
    try:
        channel_id = str(interaction.channel.id) if interaction.channel else None
        if not channel_id:
            await interaction.response.send_message(
                "❌ No pude identificar el canal. Usa el comando dentro de #pesadas.",
                ephemeral=True,
            )
            return

        if channel_id in conversation_state:
            dueño = conversation_state[channel_id]["user_id"]
            await interaction.response.send_message(
                f"Ya hay un reporte en curso (iniciado por <@{dueño}>).\n"
                f"Escribe **cancelar reporte** para reiniciar.",
                ephemeral=True,
            )
            return

        # Estado + respuesta pública inmediata (cumple el deadline de Discord)
        conversation_state[channel_id] = _crear_estado(interaction.user.id)
        await interaction.response.send_message(_mensaje_inicio(interaction.user))
        print(f"[PESADAS] slash OK user={interaction.user.id} channel={channel_id}")

    except discord.errors.NotFound:
        print("[PESADAS] slash NotFound: interacción expirada (>3s)")
        return
    except discord.errors.InteractionResponded:
        try:
            await interaction.followup.send(
                "El reporte ya se estaba iniciando…", ephemeral=True
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[PESADAS] Error en slash: {e}")
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⚠️ Error al iniciar el reporte: `{type(e).__name__}`. "
                    f"Prueba escribir: **inicio reporte de pesadas**",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Error: `{type(e).__name__}`. "
                    f"Prueba: **inicio reporte de pesadas**",
                    ephemeral=True,
                )
        except Exception:
            pass


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user} (id={bot.user.id})")
    print(f"   Guilds: {[g.name for g in bot.guilds]}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados: {[c.name for c in synced]}")
    except Exception as e:
        print(f"❌ Error al sincronizar slash: {e}")
        traceback.print_exc()


@bot.event
async def on_error(event_method, *args, **kwargs):
    print(f"❌ on_error en {event_method}")
    traceback.print_exc()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    print(f"❌ Error en app command: {error}")
    traceback.print_exc()
    try:
        msg = "⚠️ Falló el comando. Escribe en el canal: **inicio reporte de pesadas**"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content_lower = (message.content or "").strip().lower()
    channel_id = str(message.channel.id)
    state = conversation_state.get(channel_id)

    if state and _parece_cancelar(content_lower):
        es_dueño = message.author.id == state["user_id"]
        if es_dueño or content_lower in {
            "cancelar reporte",
            "reporte cancelado",
            "canelar reporte",
        }:
            del conversation_state[channel_id]
            await message.channel.send("✅ Reporte de Pesadas cancelado.")
        return

    if _parece_inicio(content_lower):
        await iniciar_reporte(message.channel, message.author)
        return

    if not state:
        return

    # Solo el dueño avanza (evita que Tania/Martha “cierren” la pregunta del cacao)
    if message.author.id != state["user_id"]:
        return

    await manejar_respuesta(message)


# ================== GROK ==================
def _system_prompt_validador() -> str:
    return (
        """
Eres validador del Reporte de Pesadas de una fábrica de helados.
Responde ÚNICAMENTE JSON:
{
  "respuesta_valida": true o false,
  "mensaje": null o "texto corto pidiendo SOLO lo que falta"
}

Principios:
1. Sé RAZONABLE. Evalúa si la INFORMACIÓN está, no si la frase es perfecta.
2. Números con punto o coma (3.217 / 3,217) son válidos.
3. Multilínea con número + notas (pote, 2N 2C 2G) es VÁLIDA si el número está.
4. Listas producto+cantidad son la respuesta CORRECTA en adicionales y transferencias.
5. "No" / "No hubo" / "Ninguno" / "0" son válidos cuando la pregunta lo permite.
6. "No hay" en stock bajo = cantidad 0 → válido.
7. Sí/No cortos válidos en checklists.
8. BUFFER + respuesta nueva se evalúan juntos.
9. Español informal y typos OK.
10. Nunca digas solo "Responde completo..." sin decir qué falta.
11. Nunca digas "no me dijiste la cantidad" si hay un dígito claro en el texto.
12. Punto "." solo → inválido.
13. """
        + REGLA_CONOS_SIN_FOTO
        + """

Errores REALES que debes evitar:
- Rechazar "3.217 pote / 2N 2C 2G" pidiendo de nuevo el cacao.
- Rechazar desglose de adicionales pidiendo "un número".
- Rechazar "Bandejas de un litro no hay".
- Tragar mensajes de otras personas (eso lo filtra el código; tú solo validas el texto dado).
- Pedir foto de conos, o tratar la respuesta como incompleta porque no hay foto de conos.
"""
    )


async def consultar_grok(
    pregunta_item: dict,
    respuesta_nueva: str,
    buffer: str,
    tiene_adjuntos: bool,
) -> dict:
    system_prompt = _system_prompt_validador()

    user_content = f"""
Pregunta:
{pregunta_item["texto"]}

Tipo: {pregunta_item.get("tipo")}
Reglas de esta pregunta:
{pregunta_item.get("reglas", "")}

Tiene_adjuntos: {tiene_adjuntos}

BUFFER (intentos previos misma pregunta):
\"\"\"{buffer or "(vacío)"}\"\"\"

Respuesta NUEVA:
\"\"\"{respuesta_nueva}\"\"\"
"""

    try:
        response = client.chat.completions.create(
            model="grok-4-1-fast",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return {
            "respuesta_valida": bool(data.get("respuesta_valida", False)),
            "mensaje": data.get("mensaje"),
        }
    except Exception as e:
        print(f"Error al consultar Grok: {e}")
        traceback.print_exc()
        if _vacio_o_basura(respuesta_nueva, tiene_adjuntos):
            return {
                "respuesta_valida": False,
                "mensaje": "Escribe la respuesta con datos (no uses solo un punto).",
            }
        return {"respuesta_valida": True, "mensaje": None}


async def extraer_productos_transferencia(texto: str) -> list:
    """Nombres de productos recargados. Grok primero; lista conocida de respaldo."""
    locales = _productos_locales(texto)
    system_prompt = """
Eres extractor. El trabajador reportó una transferencia del almacén de bultos
al almacén de pesadas (se acabó el bulto en uso y se abrió uno nuevo).
Responde ÚNICAMENTE JSON:
{ "productos": ["Leche", "Azúcar"] }

Reglas:
- Lista cada producto distinto que se transfirió/recargó.
- Nombres cortos: Leche, Azúcar, Suero, Cacao, Arequipe, Estabilizante, Conos, Glucosa.
- Cono, conos, CONOS o cónos son el mismo producto: usa "Conos". Inclúyelos si aparecen; no pidas foto.
- Si dijo que NO hubo transferencia, productos = [].
- No inventes productos que no estén en el texto.
- Sin duplicados.
"""
    try:
        response = client.chat.completions.create(
            model="grok-4-1-fast",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Respuesta:\n\"\"\"{texto}\"\"\""},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        crudos = data.get("productos") or []
        limpios = []
        for p in crudos:
            n = _titulo_producto(str(p))
            if n and n not in limpios and n.lower() not in {"no", "ninguno", "nada"}:
                limpios.append(n)
        if limpios:
            return limpios
    except Exception as e:
        print(f"Error al extraer productos de transferencia: {e}")
        traceback.print_exc()
    return locales


async def _iniciar_fotos_transferencia(message: discord.Message, state: dict, texto: str):
    productos = await extraer_productos_transferencia(texto)
    if not productos:
        productos = ["el producto transferido"]
    # Los conos se quedan en la respuesta ya guardada. No entran a la cola
    # de fotos: ni se piden, ni bloquean, ni dejan el reporte incompleto.
    habia_conos = any(_es_producto_conos(str(p)) for p in productos)
    fotos = _estado_fotos_si_aplica(productos)
    if fotos is None:
        if habia_conos:
            await message.channel.send(
                "Anotado. Los conos no necesitan foto; seguimos con el reporte."
            )
        await _avanzar_pregunta(message, state)
        return
    state["fotos_tx"] = fotos
    productos_foto = fotos["productos"]
    lista = ", ".join(productos_foto)
    aviso_conos = (
        "Los conos quedan anotados y no hace falta foto de ellos.\n"
        if habia_conos
        else ""
    )
    await message.channel.send(
        "Hubo transferencia de inventario (se acabó el bulto en uso y se abrió uno nuevo).\n"
        f"Productos: **{lista}**.\n"
        f"{aviso_conos}"
        "Por cada uno necesito 2 fotos: el **bulto nuevo en la báscula** "
        "(contenido neto + empaque) y el **empaque vacío** que se acabó."
    )
    await message.channel.send(_texto_pedir_foto(productos_foto[0], "nuevo"))


async def _avanzar_pregunta(message: discord.Message, state: dict):
    channel_id = str(message.channel.id)
    state["paso"] += 1
    if state["paso"] < len(PREGUNTAS):
        n = state["paso"] + 1
        total = len(PREGUNTAS)
        await message.channel.send(
            f"**Pregunta {n} de {total}:**\n"
            f"{PREGUNTAS[state['paso']]['texto']}"
        )
        return
    await message.channel.send(
        "✅ **Reporte de Pesadas completado.**\n\n"
        "Todas las respuestas han sido registradas. ¡Gracias!\n"
        f"_Respondido por <@{state['user_id']}>._"
    )
    print(
        f"[PESADAS OK] channel={channel_id} "
        f"answers={json.dumps(state['answers'], ensure_ascii=False)}"
    )
    del conversation_state[channel_id]


async def _siguiente_foto_o_seguir(message: discord.Message, state: dict):
    ft = state.get("fotos_tx") or {}
    ft["idx"] = int(ft.get("idx") or 0) + 1
    ft["paso_foto"] = "nuevo"
    productos = ft.get("productos") or []
    while ft["idx"] < len(productos) and _es_producto_conos(str(productos[ft["idx"]])):
        ft["idx"] += 1
    if ft["idx"] < len(productos):
        await message.channel.send(_texto_pedir_foto(productos[ft["idx"]], "nuevo"))
        return
    capturas = ft.get("capturas") or {}
    if capturas:
        state["answers"]["fotos_transferencia"] = capturas
        await message.channel.send("Listo, ya tengo las fotos de la transferencia.")
    state["fotos_tx"] = None
    await _avanzar_pregunta(message, state)


async def manejar_fotos_transferencia(message: discord.Message, state: dict):
    ft = state.get("fotos_tx")
    if not ft:
        return

    productos = ft.get("productos") or ["el producto transferido"]
    idx = int(ft.get("idx") or 0)
    if 0 <= idx < len(productos) and _es_producto_conos(str(productos[idx])):
        await _siguiente_foto_o_seguir(message, state)
        return

    imgs = _adjuntos_imagen(message)
    if not imgs and item.get("clave") == "foto_material_envasado" and _es_no_hubo_vasitos(texto):
        state["answers"][str(state["paso"])] = (texto or "").strip() + " [sin foto: no se hicieron vasitos]"
        state["answers"][item["clave"]] = None
        state["buffer"] = ""
        try:
            await message.add_reaction("✅")
        except Exception:
            pass
        await _avanzar_pregunta(message, state)
        return
    if not imgs:
        await message.channel.send(
            "Necesito **una foto** (imagen adjunta). "
            "Tómala y súbela aquí: primero el bulto nuevo en la báscula, "
            "después el empaque vacío."
        )
        return

    productos = ft.get("productos") or ["el producto transferido"]
    idx = int(ft.get("idx") or 0)
    if idx < 0 or idx >= len(productos):
        state["fotos_tx"] = None
        await _avanzar_pregunta(message, state)
        return

    producto = productos[idx]
    paso_foto = ft.get("paso_foto") or "nuevo"
    capturas = ft.setdefault("capturas", {})
    slot = capturas.setdefault(producto, {"nuevo": None, "vacio": None})

    try:
        await message.add_reaction("✅")
    except Exception:
        pass

    if paso_foto == "nuevo":
        slot["nuevo"] = _info_adjunto(imgs[0])
        if len(imgs) >= 2:
            slot["vacio"] = _info_adjunto(imgs[1])
            await _siguiente_foto_o_seguir(message, state)
            return
        ft["paso_foto"] = "vacio"
        await message.channel.send(_texto_pedir_foto(producto, "vacio"))
        return

    slot["vacio"] = _info_adjunto(imgs[0])
    await _siguiente_foto_o_seguir(message, state)


# ================== MANEJO ==================
async def _manejar_foto_obligatoria(
    message: discord.Message, state: dict, item: dict, texto: str
):
    """Cierra el paso solo con una imagen. Sin ella el reporte sigue abierto."""
    imgs = _adjuntos_imagen(message)
    if not imgs:
        await message.channel.send(
            "Necesito **una foto** (imagen adjunta).\n" + item["texto"]
        )
        return

    try:
        await message.add_reaction("✅")
    except Exception:
        pass

    info = _info_adjunto(imgs[0])
    nota = (texto or "").strip()
    rotulo = f"[foto: {info['filename']}]"
    state["answers"][str(state["paso"])] = (
        f"{nota}\n{rotulo}".strip() if nota else rotulo
    )
    state["answers"][item.get("clave") or "foto"] = info
    state["buffer"] = ""
    await _avanzar_pregunta(message, state)


async def manejar_respuesta(message: discord.Message):
    channel_id = str(message.channel.id)
    state = conversation_state.get(channel_id)
    if not state:
        return

    if state.get("fotos_tx"):
        await manejar_fotos_transferencia(message, state)
        return

    paso = state["paso"]
    if paso < 0 or paso >= len(PREGUNTAS):
        del conversation_state[channel_id]
        return

    item = PREGUNTAS[paso]
    texto = (message.content or "").strip()
    tiene_adjuntos = bool(message.attachments)
    tipo = item.get("tipo")

    # Antes de los atajos de sí/no y de "ok"/"listo": una foto con esa
    # palabra igual cuenta, y un "Sí" sin imagen no cierra el reporte.
    if tipo == "foto":
        await _manejar_foto_obligatoria(message, state, item, texto)
        return

    if _vacio_o_basura(texto, tiene_adjuntos):
        await message.channel.send(
            "Escribe la respuesta con datos (no uses solo un punto). "
            "Si es una cantidad, pon el número (ej. 3.217). "
            "Si no aplica, di **No** o **No hubo**."
        )
        return

    # Atajos locales: menos tokens y menos rechazos absurdos
    sn = _es_si_no_corto(texto)

    if tipo == "si_no" and sn is not None:
        await _aceptar_y_avanzar(message, state, texto)
        return

    if tipo in {"abierta", "adicionales"} and sn is False:
        await _aceptar_y_avanzar(message, state, texto)
        return

    if tipo == "transferencia" and _es_respuesta_no_transferencia(texto):
        final = ((state.get("buffer") or "") + "\n" + texto).strip()
        await _aceptar_y_avanzar(message, state, final)
        return

    if tipo == "cantidad" and _tiene_numero(texto):
        # Número presente → aceptar (evita el bug del cacao 3.217 pote)
        await _aceptar_y_avanzar(message, state, texto)
        return

    if tipo == "cantidad" and tiene_adjuntos and not texto:
        await message.channel.send(
            "Recibí la foto. Escribe también la **cantidad en número** "
            "(ej. 3,217) para poder registrar el dato."
        )
        return

    if tipo == "stock_bajo":
        if re.search(
            r"\bno\s+hay\b|\bninguno\b|\bnada\b|\b0\b", texto.lower()
        ) or _tiene_numero(texto):
            if len(texto) >= 3:
                await _aceptar_y_avanzar(message, state, texto)
                return

    if tipo in {"adicionales", "transferencia"}:
        if _tiene_numero(texto) or (tipo == "adicionales" and sn is False):
            final = ((state.get("buffer") or "") + "\n" + texto).strip()
            await _aceptar_y_avanzar(message, state, final)
            return
        if sn is True:
            state["buffer"] = ((state.get("buffer") or "") + "\n" + texto).strip()
            await message.channel.send(
                "Ok, hubo movimiento. Indica **qué productos** y **en qué cantidades**."
            )
            return

    # Resto → Grok (con buffer)
    buffer_prev = state.get("buffer") or ""
    respuesta_para_ia = texto
    if tiene_adjuntos:
        nombres = ", ".join(a.filename for a in message.attachments)
        respuesta_para_ia = f"{texto}\n[Adjuntos: {nombres}]".strip()

    decision = await consultar_grok(item, respuesta_para_ia, buffer_prev, tiene_adjuntos)

    if not decision.get("respuesta_valida", False):
        state["buffer"] = (buffer_prev + "\n" + texto).strip() if buffer_prev else texto
        if tipo == "transferencia" and _rechazo_pide_foto_de_conos(
            decision.get("mensaje") or "", state["buffer"]
        ):
            msg_norm = _sin_acentos(decision.get("mensaje") or "").lower()
            pide_cantidad = re.search(
                r"\bcantidad\b|\bnumero\b|\bcuanto\b|\bcuantas\b|\bcuantos\b",
                msg_norm,
            )
            if _tiene_numero(state["buffer"]) or not pide_cantidad:
                await _aceptar_y_avanzar(message, state, state["buffer"])
                return
            await message.channel.send(
                "Indica la cantidad de cada producto. Los conos no necesitan foto."
            )
            return
        msg = decision.get("mensaje") or "Falta un dato. Completa solo lo que falta."
        if msg.strip().lower() in {
            "responde completo lo que se te preguntó.",
            "responde con el número o la cantidad.",
            "te falta decirme la cantidad.",
            "no me dijiste con cuánto comenzó.",
            "no me dijiste con cuánto comenzó / terminó.",
            "no me dijiste con cuánto cacao comenzó el día.",
        }:
            if _tiene_numero(state["buffer"]):
                await _aceptar_y_avanzar(message, state, state["buffer"])
                return
            msg = "Necesito la cantidad en número (puedes agregar notas en la misma respuesta)."
        await message.channel.send(msg)
        return

    final = (buffer_prev + "\n" + texto).strip() if buffer_prev else texto
    await _aceptar_y_avanzar(message, state, final)


async def _aceptar_y_avanzar(message: discord.Message, state: dict, texto_final: str):
    paso = state["paso"]

    try:
        await message.add_reaction("✅")
    except Exception:
        pass

    state["answers"][str(paso)] = texto_final
    state["buffer"] = ""

    item = PREGUNTAS[paso] if 0 <= paso < len(PREGUNTAS) else {}
    if item.get("tipo") == "transferencia" and not _es_respuesta_no_transferencia(texto_final):
        await _iniciar_fotos_transferencia(message, state, texto_final)
        return

    await _avanzar_pregunta(message, state)


# ================== INICIO ==================
# Railway arranca este archivo (python main.py). Los tests ponen
# PESADAS_NO_ARRANCAR=1 para importar la lógica sin conectar a Discord.
if os.getenv("PESADAS_NO_ARRANCAR") != "1":
    bot.run(DISCORD_TOKEN)
