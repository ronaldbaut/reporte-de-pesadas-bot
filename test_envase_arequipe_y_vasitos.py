"""Pregunta nueva del envase de arequipe (11 de 22) y la 19/22 sin foto si no hubo vasitos."""
import asyncio
import unittest

from test_foto_material_envasado import Canal, Mensaje, Adjunto, main, TEXTO_FOTO, _indice


class TestEnvaseArequipe(unittest.TestCase):
    def setUp(self):
        self._grok = main.consultar_grok

        async def _no_grok(*a, **k):
            raise AssertionError("no debe consultar al modelo")

        main.consultar_grok = _no_grok
        main.conversation_state.clear()

    def tearDown(self):
        main.consultar_grok = self._grok
        main.conversation_state.clear()

    def _estado(self, canal, paso):
        st = main._crear_estado(7)
        st["paso"] = paso
        main.conversation_state[str(canal.id)] = st
        return st

    def test_va_justo_despues_del_arequipe_final(self):
        i = _indice("Se desocupó hoy algún envase de arequipe")
        self.assertEqual(i, _indice("arequipe terminó el día") + 1)
        self.assertEqual(i, 10)

    def test_arequipe_final_pregunta_envase(self):
        async def run():
            c = Canal(); st = self._estado(c, 9)
            await main.manejar_respuesta(Mensaje("2.5", c))
            self.assertIn("**Pregunta 11 de 22:**\n¿Se desocupó hoy algún envase de arequipe?", c.messages[-1])
        asyncio.run(run())

    def test_si_pide_peso_y_exige_numero(self):
        async def run():
            c = Canal(); st = self._estado(c, 10)
            await main.manejar_respuesta(Mensaje("SI", c))
            self.assertEqual(st["paso"], 10)
            self.assertEqual(c.messages[-1], "Escribe el peso del envase vacío")
            await main.manejar_respuesta(Mensaje("no sé", c))
            self.assertEqual(st["paso"], 10)
            self.assertIn("en número", c.messages[-1])
            await main.manejar_respuesta(Mensaje("1,35 kg", c))
            self.assertEqual(st["paso"], 11)
            self.assertIn("1,35 kg", st["answers"]["10"])
            self.assertEqual(st["answers"]["envase_arequipe"], {"desocupado": True, "peso_envase_vacio": "1,35"})
            self.assertIn("**Pregunta 12 de 22:**", c.messages[-1])
        asyncio.run(run())

    def test_si_con_acento_y_no_salta(self):
        async def run():
            c = Canal(); st = self._estado(c, 10)
            await main.manejar_respuesta(Mensaje("Sí", c))
            self.assertEqual(c.messages[-1], "Escribe el peso del envase vacío")
            c2 = Canal(43); st2 = self._estado(c2, 10)
            await main.manejar_respuesta(Mensaje("No", c2))
            self.assertEqual(st2["paso"], 11)
            self.assertEqual(st2["answers"]["envase_arequipe"]["desocupado"], False)
        asyncio.run(run())

    def test_respuesta_rara_repregunta(self):
        async def run():
            c = Canal(); st = self._estado(c, 10)
            await main.manejar_respuesta(Mensaje("quizás", c))
            self.assertEqual(st["paso"], 10)
            self.assertIn("Sí** o **No", c.messages[-1])
        asyncio.run(run())


class TestVasitosSinFoto(TestEnvaseArequipe):
    def test_no_se_hicieron_vasitos_avanza_sin_foto(self):
        async def run():
            for i, t in enumerate(("No", "no hay", "No se hicieron vasitos hoy", "no se hizo")):
                c = Canal(100 + i); st = self._estado(c, 18)
                await main.manejar_respuesta(Mensaje(t, c))
                self.assertEqual(st["paso"], 19, t)
                self.assertIsNone(st["answers"]["foto_material_envasado"])
        asyncio.run(run())

    def test_otra_respuesta_sigue_pidiendo_foto(self):
        async def run():
            c = Canal(); st = self._estado(c, 18)
            await main.manejar_respuesta(Mensaje("listo", c))
            self.assertEqual(st["paso"], 18)
            self.assertIn("Necesito **una foto**", c.messages[-1])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
