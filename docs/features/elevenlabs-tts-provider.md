# Feature: Añadir ElevenLabs como proveedor de TTS

> Prompt de implementación para Claude Code. Pegar en una sesión nueva.

---

Quiero implementar **ElevenLabs** como nuevo proveedor de text-to-speech en RPG Scribe,
**junto** al de OpenAI (no lo elimines: ambos deben seguir seleccionables vía config).
El objetivo es poder poner `provider = "elevenlabs"` en el `[tts]` del TOML.

Antes de escribir código, consulta la documentación ACTUAL del SDK `elevenlabs` de Python
(usa context7) porque su API cambia entre versiones — necesito el cliente async y el método
de `text_to_speech` correctos, no de memoria.

## Contrato crítico que NO puedes romper

El proveedor implementa `BaseTTSProvider` (`src/rpg_scribe/tts/base.py`):

```python
async def synthesize(self, text: str, voice: str, response_format: str = "mp3") -> bytes
def supported_voices(self) -> list[str]
@property
def name(self) -> str
```

**Requisito duro:** cuando `response_format == "pcm"`, `synthesize` DEBE devolver audio
**PCM crudo 24 kHz, mono, int16 little-endian, sin cabecera**. Ese buffer se pasa tal cual a
`pcm_24k_mono_to_48k_stereo()` en `src/rpg_scribe/tts/audio_utils.py` (hace
`np.frombuffer(..., dtype=np.int16)`). Si el formato no es exactamente ese, el audio de
Discord sale como ruido.

Mapeo de `response_format` → `output_format` de ElevenLabs:
- `"pcm"` → `pcm_24000` (raw 24 kHz mono int16 LE — encaja con el pipeline existente)
- `"mp3"` → `mp3_44100_128`

## Adaptación de modelos/voces (esto es lo que hay que ajustar a ElevenLabs)

- OpenAI usaba `model="tts-1"` y `voice="nova"`. ElevenLabs usa un **model_id** y un
  **voice_id** distintos. Como las partidas son en **español**, el modelo por defecto debe
  ser multilingüe: usa `eleven_multilingual_v2` como default de `model`.
- `voice` pasa a ser un **voice_id** de ElevenLabs. **Voice_id por defecto a usar:**
  `t9LRTh3y1ioN00e9wsNh`.
- `supported_voices()`: puede devolver una lista de voice_ids conocidos (constante de módulo,
  p.ej. `ELEVENLABS_VOICES`, que incluya al menos `t9LRTh3y1ioN00e9wsNh`), o consultar la API
  si hay API key. Elige la opción más simple y coméntalo.

## Pasos concretos

1. **Crea `src/rpg_scribe/tts/elevenlabs_provider.py`**
   - Clase `ElevenLabsTTSProvider(BaseTTSProvider)`, misma estructura que
     `OpenAITTSProvider` en `src/rpg_scribe/tts/openai_provider.py`.
   - `__init__(self, model: str = "eleven_multilingual_v2")`.
   - Init perezoso del cliente (`_get_client()`), con el patrón `try/except ImportError`
     que lanza un mensaje con `pip install elevenlabs`. El cliente lee `ELEVENLABS_API_KEY`
     del entorno (igual que el de OpenAI lee `OPENAI_API_KEY`).
   - `name` → `"elevenlabs"`.
   - `synthesize`: llama al método `text_to_speech` del SDK con el `output_format` mapeado.
     Ojo: el SDK de ElevenLabs suele devolver un **iterador/stream de bytes** — concaténalos
     en un único `bytes` antes de devolver.
   - Constante de módulo `ELEVENLABS_VOICES` con al menos el voice_id `t9LRTh3y1ioN00e9wsNh`.

2. **Regístralo en los DOS sitios de instanciación** (son los únicos):
   - `src/rpg_scribe/main.py` (~línea 312): añade `elif tts_config.provider == "elevenlabs":`
     que importe e instancie `ElevenLabsTTSProvider(model=tts_config.model)`.
   - `src/rpg_scribe/web/app.py` (~línea 149): mismo `elif`, asignando a
     `router.tts_provider`.

3. **Config**: `TTSConfig` en `src/rpg_scribe/core/models.py` (~línea 218). El loader
   (`src/rpg_scribe/config.py` ~línea 105) usa `hasattr`/`setattr`, así que cualquier campo
   nuevo se carga solo del TOML. NO cambies los defaults del dataclass (romperían
   `test_tts.py::TestTTSConfig::test_defaults`). En su lugar, añade un ejemplo comentado de
   sección `[tts]` para ElevenLabs en `config/default.toml` (junto al `[tts]` existente en
   las líneas ~60-65), mostrando:

   ```toml
   # provider = "elevenlabs"
   # model = "eleven_multilingual_v2"
   # voice = "t9LRTh3y1ioN00e9wsNh"
   ```

4. **Dependencia**: en `pyproject.toml` añade `elevenlabs` como extra opcional
   (p.ej. un grupo `tts = ["elevenlabs>=..."]` en `[project.optional-dependencies]`),
   coherente con el import perezoso.

5. **Variable de entorno `ELEVENLABS_API_KEY`**: documéntala en `CLAUDE.md` (tabla de
   variables), `README.md` y `.env.example` si existe.
   ⚠️ El fichero `.env` del repo tiene claves reales commiteadas. NO añadas la clave real ahí;
   avísame de este problema de seguridad y propón sacar `.env` del control de versiones
   (`.gitignore` + `.env.example`), pero no lo hagas sin mi confirmación.

6. **Docs**: actualiza `docs/tts-narration.md`, sección "Añadir un provider nuevo". De paso
   corrige que menciona solo `web/app.py`: hay que instanciar en `main.py` **y** `web/app.py`.

7. **Tests**: añade tests en `tests/test_tts.py` replicando `TestOpenAITTSProvider`
   (`name == "elevenlabs"`, `supported_voices()` no vacío, `synthesize` con
   `response_format="pcm"` produce el `output_format` correcto). Mockea inyectando un cliente
   falso en `provider._client`, igual que hace el test de OpenAI. Verifica que
   `tests/test_tts_synthesizer.py` sigue pasando.

## Verificación final

- `ruff check src/ tests/` y `ruff format src/ tests/` limpios.
- `pytest -k tts` en verde (ignora los fallos preexistentes documentados en CLAUDE.md).
- Confírmame explícitamente que el modo Discord recibe PCM 24 kHz mono int16 LE (revisa que
  el `output_format` es `pcm_24000` y que concatenas bien el stream de bytes).

**No hagas commit** — lo probaré yo antes.
