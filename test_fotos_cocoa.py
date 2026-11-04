"""En una transferencia de cocoa cambian las dos fotos; el resto no.

La cocoa se pide como envase vacío y luego envase con la recarga.
Leche, azúcar y los demás siguen con bulto nuevo y empaque vacío.
No hay cálculo de peso: la primera foto sigue guardándose en "nuevo"
y la segunda en "vacio".
"""
import asyncio
import contextlib
import io
import json
import os
import unittest

os.environ["PESADAS_NO_ARRANCAR"] = "1"
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("XAI_API_KEY", "test-key")

import main


def _paso_transferencia() -> int:
    return next(i for i, p in enumerate(main.PREGUNTAS) if p["tipo"] == "transferencia")


def _foto_clasica(producto: str, cual: str) -> str:
    if cual == "nuevo":
        cuerpo = (
            "Manda la foto del **bulto NUEVO en la báscula**, "
            "para ver cuánto pesa el contenido neto junto con el empaque."
        )
    else:
        cuerpo = "Ahora manda la foto del **empaque VACÍO** cuyo contenido neto se acabó."
    return f"📦 **Transferencia — {producto}**\n{cuerpo}"


FOTO_ENVASE_VACIO = (
    "Manda la foto del **envase vacío en la báscula**, "
    "donde se va a colocar la cocoa."
)
FOTO_CON_RECARGA = (
    "Ahora manda la foto del **envase con la recarga de cocoa** ya incluida."
)


class Canal:
    def __init__(self, cid=42):
        self.id = cid
        self.messages = []

    async def send(self, content):
        self.messages.append(content)


class Autor:
    def __init__(self, user_id=7):
        self.id = user_id


class Adjunto:
    def __init__(self, filename, content_type="image/jpeg"):
        self.filename = filename
        self.url = f"https://cdn.example/{filename}"
        self.content_type = content_type


class Mensaje:
    def __init__(self, content, canal, attachments=None):
        self.content = content
        self.channel = canal
        self.attachments = list(attachments or [])
        self.author = Autor()
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class _Choice:
    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class TestFotosCocoa(unittest.TestCase):
    def setUp(self):
        self._create = main.client.chat.completions.create
        main.conversation_state.clear()

    def _estado(self, canal):
        state = main._crear_estado(7)
        state["paso"] = _paso_transferencia()
        main.conversation_state[str(canal.id)] = state
        return state

    def _usar_extractor_local(self):
        if not hasattr(self, "_extraer_real"):
            self._extraer_real = main.extraer_productos_transferencia

        async def _local(texto):
            return main._productos_locales(texto)

        main.extraer_productos_transferencia = _local

    def tearDown(self):
        main.client.chat.completions.create = self._create
        if hasattr(self, "_extraer_real"):
            main.extraer_productos_transferencia = self._extraer_real
        main.conversation_state.clear()

    def test_reconoce_cocoa_y_cacao_sin_mayusculas_ni_acentos(self):
        variantes = [
            "cocoa",
            "COCOA",
            "Cocoa",
            "CoCoA",
            "cócoa",
            "CÓCOA",
            "co\u0301coa",
            "  Cocoa  ",
            "cocoa en polvo",
            "polvo de cocoa",
            "Cocoa-mix",
            "cacao",
            "CACAO",
            "Cacao",
            "cácao",
            "Cácao",
            "ca\u0301cao",
            "polvo de cacao",
            "Cacao en polvo",
        ]
        for nombre in variantes:
            self.assertTrue(main._es_producto_cocoa(nombre), nombre)

    def test_otros_productos_no_son_cocoa(self):
        for nombre in [
            "",
            "leche",
            "azúcar",
            "Azucar",
            "conos",
            "cono",
            "coco",
            "Coco",
            "chocolate",
            "suero",
            "arequipe",
            "estabilizante",
            "glucosa",
            "crema de leche",
            "el producto transferido",
        ]:
            self.assertFalse(main._es_producto_cocoa(nombre), nombre)

    def test_los_demas_productos_conservan_el_texto_de_siempre(self):
        for producto in [
            "Leche",
            "Azúcar",
            "Suero",
            "Arequipe",
            "Estabilizante",
            "Glucosa",
            "Crema de Leche",
            "Coco",
            "el producto transferido",
        ]:
            self.assertEqual(
                main._texto_pedir_foto(producto, "nuevo"),
                _foto_clasica(producto, "nuevo"),
            )
            self.assertEqual(
                main._texto_pedir_foto(producto, "vacio"),
                _foto_clasica(producto, "vacio"),
            )
            self.assertEqual(
                main._texto_falta_foto_transferencia(producto),
                "Necesito **una foto** (imagen adjunta). "
                "Tómala y súbela aquí: primero el bulto nuevo en la báscula, "
                "después el empaque vacío.",
            )
        self.assertEqual(
            main._texto_resumen_fotos_transferencia(["Leche", "Azúcar"]),
            "Por cada uno necesito 2 fotos: el **bulto nuevo en la báscula** "
            "(contenido neto + empaque) y el **empaque vacío** que se acabó.",
        )

    def test_textos_de_cocoa_piden_envase_vacio_y_luego_la_recarga(self):
        for producto in ["Cacao", "Cocoa", "COCOA", "cocoa en polvo", "polvo de cacao"]:
            nuevo = main._texto_pedir_foto(producto, "nuevo")
            vacio = main._texto_pedir_foto(producto, "vacio")
            self.assertIn(f"Transferencia — {producto}", nuevo)
            self.assertIn(FOTO_ENVASE_VACIO, nuevo)
            self.assertNotIn("bulto NUEVO", nuevo)
            self.assertIn(FOTO_CON_RECARGA, vacio)
            self.assertNotIn("empaque VACÍO", vacio)
            self.assertNotIn("contenido neto se acabó", vacio)

    def test_detector_local_unifica_cocoa_y_cacao(self):
        self.assertEqual(main._productos_locales("1 bulto de COCOA"), ["Cacao"])
        self.assertEqual(main._productos_locales("cócoa 2 kg"), ["Cacao"])
        self.assertEqual(main._productos_locales("co\u0301coa"), ["Cacao"])
        self.assertEqual(main._productos_locales("cácao 1"), ["Cacao"])
        self.assertEqual(main._productos_locales("cacao y cocoa"), ["Cacao"])
        self.assertEqual(main._productos_locales("cocoa en polvo 3"), ["Cacao"])
        self.assertEqual(
            main._productos_locales("leche 10 y cocoa 1"),
            ["Leche", "Cacao"],
        )
        self.assertNotIn("Cacao", main._productos_locales("coco 2 y leche 1"))
        self.assertEqual(main._productos_locales("coco 2 y leche 1"), ["Leche"])

    def test_grok_no_duplica_cocoa_y_cacao_y_conserva_un_nombre_largo(self):
        def _ok(**kwargs):
            return _Resp(json.dumps({"productos": ["Cocoa", "Cacao", "Leche"]}))

        main.client.chat.completions.create = _ok
        productos = asyncio.run(main.extraer_productos_transferencia("cocoa y leche"))
        self.assertEqual(productos, ["Cacao", "Leche"])

        def _largo(**kwargs):
            return _Resp(json.dumps({"productos": ["cocoa en polvo"]}))

        main.client.chat.completions.create = _largo
        productos = asyncio.run(main.extraer_productos_transferencia("cocoa en polvo"))
        self.assertEqual(productos, ["Cocoa En Polvo"])
        self.assertTrue(main._es_producto_cocoa(productos[0]))

    def test_si_la_api_falla_el_respaldo_reconoce_cocoa(self):
        def _boom(**kwargs):
            raise RuntimeError("sin red en test")

        main.client.chat.completions.create = _boom
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            productos = asyncio.run(
                main.extraer_productos_transferencia("pasaron COCOA y cácao")
            )
        self.assertEqual(productos, ["Cacao"])

    def test_transferencia_de_cacao_pide_las_dos_fotos_nuevas(self):
        asyncio.run(self._assert_cacao())

    async def _assert_cacao(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("cacao 1 bulto", canal))

        self.assertEqual(state["fotos_tx"]["productos"], ["Cacao"])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")
        self.assertIn("envase vacío en la báscula", canal.messages[0])
        self.assertIn("recarga de cocoa", canal.messages[0])
        self.assertNotIn("bulto nuevo en la báscula", canal.messages[0])
        self.assertNotIn("empaque vacío", canal.messages[0])
        self.assertEqual(canal.messages[1], main._texto_pedir_foto("Cacao", "nuevo"))
        self.assertIn(FOTO_ENVASE_VACIO, canal.messages[1])

        await main.manejar_respuesta(Mensaje("ya va", canal))
        self.assertEqual(
            canal.messages[-1],
            main._texto_falta_foto_transferencia("Cacao"),
        )
        self.assertNotIn("bulto nuevo", canal.messages[-1])
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("envase-vacio.jpg")]))
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Cacao", "vacio"))
        self.assertIn(FOTO_CON_RECARGA, canal.messages[-1])
        self.assertEqual(
            state["fotos_tx"]["capturas"]["Cacao"]["nuevo"]["filename"],
            "envase-vacio.jpg",
        )
        self.assertIsNone(state["fotos_tx"]["capturas"]["Cacao"]["vacio"])

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("con-recarga.jpg")]))
        self.assertIsNone(state["fotos_tx"])
        guardadas = state["answers"]["fotos_transferencia"]["Cacao"]
        self.assertEqual(guardadas["nuevo"]["filename"], "envase-vacio.jpg")
        self.assertEqual(guardadas["vacio"]["filename"], "con-recarga.jpg")
        self.assertEqual(set(guardadas["nuevo"]), {"filename", "url", "content_type"})
        self.assertNotIn("peso", guardadas["nuevo"])
        self.assertNotIn("peso", guardadas["vacio"])
        self.assertIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertIn("adicionales", canal.messages[-1])

    def test_dos_fotos_juntas_siguen_en_nuevo_y_vacio_sin_calcular_peso(self):
        asyncio.run(self._assert_dos_juntas())

    async def _assert_dos_juntas(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("COCOA 1", canal))
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [Adjunto("envase-vacio.jpg"), Adjunto("con-recarga.jpg")],
            )
        )
        self.assertNotIn(main._texto_pedir_foto("Cacao", "vacio"), canal.messages)
        guardadas = state["answers"]["fotos_transferencia"]["Cacao"]
        self.assertEqual(guardadas["nuevo"]["filename"], "envase-vacio.jpg")
        self.assertEqual(guardadas["vacio"]["filename"], "con-recarga.jpg")
        self.assertIsNone(state["fotos_tx"])

    def test_mezcla_cambia_solo_la_cocoa(self):
        asyncio.run(self._assert_mezcla())

    async def _assert_mezcla(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("leche 10, cocoa 1", canal))
        self.assertEqual(state["fotos_tx"]["productos"], ["Leche", "Cacao"])
        self.assertIn("En la cocoa:", canal.messages[0])
        self.assertIn("bulto nuevo en la báscula", canal.messages[0])
        self.assertEqual(canal.messages[-1], _foto_clasica("Leche", "nuevo"))

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("leche-nuevo.jpg")]))
        self.assertEqual(canal.messages[-1], _foto_clasica("Leche", "vacio"))
        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("leche-vacio.jpg")]))
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Cacao", "nuevo"))
        self.assertIn(FOTO_ENVASE_VACIO, canal.messages[-1])

        await main.manejar_respuesta(Mensaje("sin foto", canal))
        self.assertIn("recarga de cocoa", canal.messages[-1])
        self.assertNotIn("bulto nuevo", canal.messages[-1])

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("envase.jpg")]))
        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("recarga.jpg")]))
        fotos = state["answers"]["fotos_transferencia"]
        self.assertEqual(fotos["Leche"]["nuevo"]["filename"], "leche-nuevo.jpg")
        self.assertEqual(fotos["Leche"]["vacio"]["filename"], "leche-vacio.jpg")
        self.assertEqual(fotos["Cacao"]["nuevo"]["filename"], "envase.jpg")
        self.assertEqual(fotos["Cacao"]["vacio"]["filename"], "recarga.jpg")

    def test_nombre_largo_que_contiene_cocoa_usa_los_textos_nuevos(self):
        asyncio.run(self._assert_nombre_largo())

    async def _assert_nombre_largo(self):
        original = main.extraer_productos_transferencia

        async def _largo(texto):
            return ["Cocoa en polvo"]

        main.extraer_productos_transferencia = _largo
        try:
            canal = Canal()
            state = self._estado(canal)
            await main.manejar_respuesta(Mensaje("cocoa en polvo 1", canal))
            self.assertEqual(state["fotos_tx"]["productos"], ["Cocoa en polvo"])
            self.assertIn(FOTO_ENVASE_VACIO, canal.messages[-1])
            self.assertIn("Transferencia — Cocoa en polvo", canal.messages[-1])
        finally:
            main.extraer_productos_transferencia = original

    def test_conos_y_cocoa_piden_foto_solo_de_la_cocoa(self):
        asyncio.run(self._assert_conos_y_cocoa())

    async def _assert_conos_y_cocoa(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("cocoa 1 y 1 caja de conos", canal))
        self.assertEqual(state["fotos_tx"]["productos"], ["Cacao"])
        junto = "\n".join(canal.messages)
        self.assertIn("Los conos quedan anotados y no hace falta foto de ellos.", junto)
        self.assertIn(FOTO_ENVASE_VACIO, junto)
        self.assertNotIn("Transferencia — Conos", junto)


if __name__ == "__main__":
    unittest.main()
