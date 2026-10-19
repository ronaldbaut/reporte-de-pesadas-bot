"""Los conos se reportan, pero no piden foto ni frenan el reporte.

El resto de transferencias sigue exigiendo las dos fotos de siempre.
"""
import asyncio
import contextlib
import io
import os
import unittest

os.environ["PESADAS_NO_ARRANCAR"] = "1"
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("XAI_API_KEY", "test-key")

import main


def _paso_transferencia() -> int:
    return next(i for i, p in enumerate(main.PREGUNTAS) if p["tipo"] == "transferencia")


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


class TestConosSinFoto(unittest.TestCase):
    def setUp(self):
        self._create = main.client.chat.completions.create
        main.conversation_state.clear()

    def tearDown(self):
        main.client.chat.completions.create = self._create
        main.extraer_productos_transferencia = self._extraer_original()
        main.consultar_grok = self._grok_original()
        main.conversation_state.clear()

    def _extraer_original(self):
        return getattr(self, "_extraer_real", main.extraer_productos_transferencia)

    def _grok_original(self):
        return getattr(self, "_grok_real", main.consultar_grok)

    def _usar_extractor_local(self):
        if not hasattr(self, "_extraer_real"):
            self._extraer_real = main.extraer_productos_transferencia

        async def _local(texto):
            return main._productos_locales(texto)

        main.extraer_productos_transferencia = _local

    def _estado(self, canal):
        state = main._crear_estado(7)
        state["paso"] = _paso_transferencia()
        main.conversation_state[str(canal.id)] = state
        return state

    def test_reconoce_cono_singular_plural_mayusculas_y_acentos(self):
        variantes = [
            "cono",
            "conos",
            "CONO",
            "CONOS",
            "Cono",
            "Conos",
            "cóno",
            "cónos",
            "conó",
            "CÓNOS",
            "  Conos  ",
            "caja de conos",
            "Caja de Conos",
            "cono de helado",
            "cono\u0301s",
        ]
        for nombre in variantes:
            self.assertTrue(main._es_producto_conos(nombre), nombre)

    def test_otros_productos_no_son_conos(self):
        for nombre in [
            "leche",
            "azúcar",
            "azucar",
            "cacao",
            "estabilizante",
            "arequipe",
            "glucosa",
            "suero",
            "crema de leche",
            "el producto transferido",
            "",
            "conocer",
            "icono",
            "coño",
            "conocidos",
        ]:
            self.assertFalse(main._es_producto_conos(nombre), nombre)

    def test_detector_local_de_conos_en_el_texto(self):
        self.assertEqual(main._productos_locales("1 caja de conos"), ["Conos"])
        self.assertEqual(main._productos_locales("transferí un CONO"), ["Conos"])
        self.assertEqual(main._productos_locales("2 CÓNOS"), ["Conos"])
        self.assertEqual(main._productos_locales("se pasó 1 cóno"), ["Conos"])
        self.assertEqual(main._productos_locales("cono\u0301s 3"), ["Conos"])
        mezcla = main._productos_locales("Leche 10 y cónos 1 caja")
        self.assertEqual(mezcla, ["Leche", "Conos"])
        self.assertNotIn("Conos", main._productos_locales("no hubo"))
        self.assertNotIn("Conos", main._productos_locales("conocer el icono"))

    def test_azucar_y_crema_siguen_igual(self):
        self.assertEqual(main._productos_locales("azúcar 2 bultos"), ["Azúcar"])
        self.assertEqual(main._productos_locales("azucar 2"), ["Azúcar"])
        self.assertEqual(main._productos_locales("crema de leche 2"), ["Crema de Leche"])
        ambos = main._productos_locales("leche 2 y crema de leche 1")
        self.assertEqual(ambos, ["Crema de Leche", "Leche"])

    def test_solo_conos_no_abren_cola_de_fotos(self):
        self.assertIsNone(main._estado_fotos_si_aplica(["Conos"]))
        self.assertIsNone(main._estado_fotos_si_aplica(["cono", "CONOS", "caja de conos"]))
        self.assertIsNone(main._estado_fotos_si_aplica([]))

    def test_leche_sigue_pidiendo_foto(self):
        estado = main._estado_fotos_si_aplica(["Leche"])
        self.assertEqual(
            estado,
            {"productos": ["Leche"], "idx": 0, "paso_foto": "nuevo", "capturas": {}},
        )

    def test_mezcla_quita_conos_y_conserva_el_orden(self):
        estado = main._estado_fotos_si_aplica(["Azúcar", "Conos", "Leche", "cóno"])
        self.assertEqual(estado["productos"], ["Azúcar", "Leche"])

    def test_instrucciones_al_modelo(self):
        item = next(p for p in main.PREGUNTAS if p["tipo"] == "transferencia")
        self.assertIn(main.REGLA_CONOS_SIN_FOTO, item["reglas"])
        prompt = main._system_prompt_validador()
        self.assertIn(main.REGLA_CONOS_SIN_FOTO, prompt)
        self.assertIn("Pedir foto de conos", prompt)
        self.assertIn("Listas producto+cantidad", prompt)
        import inspect

        self.assertIn("no pidas foto", inspect.getsource(main.extraer_productos_transferencia))

    def test_rechazo_por_foto_de_conos(self):
        self.assertTrue(
            main._rechazo_pide_foto_de_conos(
                "Mándame la foto de los conos",
                "transferí 1 caja de conos",
            )
        )
        self.assertTrue(
            main._rechazo_pide_foto_de_conos(
                "Falta la imagen",
                "se pasaron los cónos",
            )
        )
        self.assertFalse(
            main._rechazo_pide_foto_de_conos(
                "Mándame la foto de la leche",
                "leche 25",
            )
        )
        self.assertFalse(
            main._rechazo_pide_foto_de_conos(
                "Falta la cantidad",
                "transferí conos",
            )
        )

    def test_margaret_reporta_conos_y_el_reporte_sigue(self):
        textos = [
            "1 caja de conos",
            "transferí los CONOS",
            "se pasó un cóno",
            "2 CÓNOS del almacén",
            "cono\u0301s: 1 caja",
        ]
        for texto in textos:
            with self.subTest(texto=texto):
                asyncio.run(self._assert_conos_no_bloquean(texto))

    async def _assert_conos_no_bloquean(self, texto):
        self._usar_extractor_local()
        if not hasattr(self, "_grok_real"):
            self._grok_real = main.consultar_grok

        async def _grok_valido(*args, **kwargs):
            return {"respuesta_valida": True, "mensaje": None}

        main.consultar_grok = _grok_valido
        canal = Canal()
        state = self._estado(canal)
        paso = state["paso"]
        await main.manejar_respuesta(Mensaje(texto, canal))

        self.assertIsNone(state["fotos_tx"])
        self.assertNotIn("fotos_transferencia", state["answers"])
        self.assertEqual(state["paso"], paso + 1)
        self.assertIn(texto, state["answers"][str(paso)])
        junto = "\n".join(canal.messages).lower()
        self.assertNotIn("báscula", junto)
        self.assertNotIn("necesito **una foto**", junto)
        self.assertIn("no necesitan foto", junto)
        self.assertIn("adicionales", junto)

    def test_transferencia_de_leche_sigue_pidiendo_las_dos_fotos(self):
        asyncio.run(self._assert_leche_pide_fotos())

    async def _assert_leche_pide_fotos(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("Leche 25.25", canal))

        self.assertEqual(state["fotos_tx"]["productos"], ["Leche"])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")
        self.assertNotIn("no hace falta foto", canal.messages[0])
        self.assertNotIn("no necesitan foto", "\n".join(canal.messages))
        self.assertEqual(
            canal.messages[0],
            "Hubo transferencia de inventario (se acabó el bulto en uso y se abrió uno nuevo).\n"
            "Productos: **Leche**.\n"
            "Por cada uno necesito 2 fotos: el **bulto nuevo en la báscula** "
            "(contenido neto + empaque) y el **empaque vacío** que se acabó.",
        )
        self.assertEqual(canal.messages[1], main._texto_pedir_foto("Leche", "nuevo"))

        await main.manejar_respuesta(Mensaje("ya va", canal))
        self.assertIn("Necesito **una foto**", canal.messages[-1])
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertIsNone(state["fotos_tx"]["capturas"].get("Leche", {}).get("nuevo") if state["fotos_tx"]["capturas"] else None)

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("bulto-nuevo.jpg")]))
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Leche", "vacio"))
        self.assertEqual(state["fotos_tx"]["capturas"]["Leche"]["nuevo"]["filename"], "bulto-nuevo.jpg")

        await main.manejar_respuesta(Mensaje("", canal, [Adjunto("empaque-vacio.jpg")]))
        self.assertIsNone(state["fotos_tx"])
        self.assertEqual(
            state["answers"]["fotos_transferencia"]["Leche"]["vacio"]["filename"],
            "empaque-vacio.jpg",
        )
        self.assertIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertIn("adicionales", canal.messages[-1])

    def test_mezcla_pide_foto_de_lo_demas_y_no_de_conos(self):
        asyncio.run(self._assert_mezcla())

    async def _assert_mezcla(self):
        self._usar_extractor_local()
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(
            Mensaje("Azúcar 1 bulto, leche 25, 1 caja de conos", canal)
        )
        self.assertEqual(state["fotos_tx"]["productos"], ["Azúcar", "Leche"])
        junto = "\n".join(canal.messages)
        self.assertIn("Los conos quedan anotados y no hace falta foto de ellos.", junto)
        self.assertIn("Productos: **Azúcar, Leche**.", junto)
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Azúcar", "nuevo"))
        self.assertNotIn("Transferencia — Conos", junto)

    def test_conos_en_la_cola_no_exigen_imagen(self):
        asyncio.run(self._assert_cola_con_conos())

    async def _assert_cola_con_conos(self):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": ["Conos", "Leche"],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(Mensaje("sigo", canal))
        self.assertNotIn("Necesito **una foto**", "\n".join(canal.messages))
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Leche", "nuevo"))
        self.assertEqual(state["fotos_tx"]["productos"][state["fotos_tx"]["idx"]], "Leche")

    def test_si_el_modelo_pide_la_foto_de_conos_no_bloquea(self):
        asyncio.run(self._assert_rechazo_del_modelo())

    async def _assert_rechazo_del_modelo(self):
        self._usar_extractor_local()
        if not hasattr(self, "_grok_real"):
            self._grok_real = main.consultar_grok

        async def _pide_foto(*args, **kwargs):
            return {
                "respuesta_valida": False,
                "mensaje": "Mándame la foto de los conos en la báscula.",
            }

        main.consultar_grok = _pide_foto
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("transferí los conos", canal))
        self.assertIsNone(state["fotos_tx"])
        self.assertNotIn("báscula", "\n".join(canal.messages).lower())
        self.assertIn("no necesitan foto", "\n".join(canal.messages))
        self.assertEqual(state["paso"], _paso_transferencia() + 1)

    def test_si_falta_cantidad_pide_cantidad_sin_foto(self):
        asyncio.run(self._assert_pide_cantidad())

    async def _assert_pide_cantidad(self):
        if not hasattr(self, "_grok_real"):
            self._grok_real = main.consultar_grok

        async def _pide_ambas(*args, **kwargs):
            return {
                "respuesta_valida": False,
                "mensaje": "Falta la cantidad y la foto de los conos.",
            }

        main.consultar_grok = _pide_ambas
        canal = Canal()
        state = self._estado(canal)
        paso = state["paso"]
        await main.manejar_respuesta(Mensaje("transferí conos", canal))
        self.assertEqual(state["paso"], paso)
        self.assertIsNone(state["fotos_tx"])
        self.assertEqual(
            canal.messages[-1],
            "Indica la cantidad de cada producto. Los conos no necesitan foto.",
        )
        self.assertNotIn("báscula", canal.messages[-1].lower())

    def test_foto_de_otro_producto_sigue_siendo_rechazo_del_modelo(self):
        asyncio.run(self._assert_foto_leche())

    async def _assert_foto_leche(self):
        if not hasattr(self, "_grok_real"):
            self._grok_real = main.consultar_grok

        async def _pide_leche(*args, **kwargs):
            return {
                "respuesta_valida": False,
                "mensaje": "Mándame la foto de la leche.",
            }

        main.consultar_grok = _pide_leche
        canal = Canal()
        state = self._estado(canal)
        paso = state["paso"]
        await main.manejar_respuesta(Mensaje("leche", canal))
        self.assertEqual(state["paso"], paso)
        self.assertIsNone(state["fotos_tx"])
        self.assertEqual(canal.messages[-1], "Mándame la foto de la leche.")

    def test_no_hubo_transferencia_no_pide_foto(self):
        asyncio.run(self._assert_no())

    async def _assert_no(self):
        canal = Canal()
        state = self._estado(canal)
        await main.manejar_respuesta(Mensaje("No", canal))
        self.assertIsNone(state["fotos_tx"])
        self.assertNotIn("foto", "\n".join(canal.messages).lower())
        self.assertIn("adicionales", canal.messages[-1])

    def test_extractor_sin_api_reconoce_conos(self):
        def _boom(**kwargs):
            raise RuntimeError("sin red en test")

        main.client.chat.completions.create = _boom
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            productos = asyncio.run(
                self._extraer_original()("Margaret pasó 1 caja de cónos")
            )
        self.assertEqual(productos, ["Conos"])


if __name__ == "__main__":
    unittest.main()
