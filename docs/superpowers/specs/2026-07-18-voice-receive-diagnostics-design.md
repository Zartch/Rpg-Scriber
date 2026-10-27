# Diagnostico del pipeline de recepcion de voz

**Fecha:** 2026-07-18
**Estado:** aprobado para planificacion

## Objetivo

Identificar en el siguiente incidente el punto exacto donde se degrada la
recepcion de voz de Discord: entrada de paquetes, descifrado DAVE, decodificacion
Opus, callback PCM o emision de chunks. La instrumentacion no cambia la logica,
los umbrales ni los eventos de recuperacion existentes.

## Contexto y evidencia

El parche de close-word elimino un bloqueo downstream del `EventBus`, pero los
incidentes de audio silencioso son distintos. El listener aplica actualmente un
parche a `PacketDecoder._decode_packet`: cualquier excepcion de `dave.decrypt()`
se ignora y el paquete se sustituye por silencio Opus. Una racha persistente de
fallos puede, por tanto, mantener la conexion aparentemente activa mientras los
chunks contienen silencio.

Los logs actuales no permiten confirmar esta hipotesis porque suprimen el tipo y
la frecuencia de los fallos. Tambien existen recuperaciones durante pausas sin
chunks nuevos; se documentaran mediante las nuevas metricas, pero no se cambiara
su comportamiento en este trabajo.

## Diseno

### Estado por conexion

Cada `DiscordListener` creara un acumulador de diagnostico asociado a su
`VoiceRecvClient`. El estado se reiniciara en cada conexion y tendra un
identificador de generacion para separar claramente periodos anteriores y
posteriores a una reconexion.

El acumulador sera seguro para acceso desde los hilos internos de `voice_recv` y
desde el event loop. No almacenara payloads, texto transcrito ni audio adicional.

### Fronteras observadas

Se registraran contadores acumulados y del intervalo para:

- Invocaciones al decoder con paquete y gaps sin paquete.
- Estado DAVE: sesion presente, protocolo, `ready` y cambios de estado.
- Descifrados DAVE correctos, fallidos y mayor racha consecutiva de fallos.
- Tipos de excepcion de descifrado, agregados por nombre de clase.
- Decodificaciones Opus correctas, fallidas y generacion de silencio por FEC.
- Callbacks PCM, bytes recibidos, usuarios activos y RMS agregado.
- Chunks emitidos, bytes, duracion y tiempo empleado en publicarlos.
- Tiempo desde el ultimo paquete, descifrado correcto, callback PCM y chunk.

### Logs

El listener emitira un resumen estructurado cada 10 segundos mientras este
conectado. Cada linea incluira sesion, generacion, estado DAVE, tasas y edades de
las ultimas actividades. Esto permitira distinguir:

- No llegan paquetes: problema de transporte o `AudioReader`.
- Llegan paquetes y falla DAVE: renegociacion o estado criptografico.
- DAVE funciona y falla Opus: payload o decoder corrupto.
- Opus funciona pero no hay callback: router/sink detenido.
- Hay PCM con RMS casi nulo: audio sustituido por silencio o stream degradado.
- Hay chunks y el publish tarda: back-pressure downstream.

Los fallos DAVE generaran warnings limitados: uno al comenzar una racha
significativa y recordatorios espaciados, sin una linea por paquete. El warning
incluira el tipo de excepcion y el estado DAVE, nunca el payload. Los cambios de
estado DAVE se registraran una sola vez por transicion.

### Integracion

El parche global del decoder buscara el acumulador asociado al `VoiceClient` y
actualizara las metricas antes y despues de DAVE y Opus. El callback de
`BasicSink` registrara PCM antes de convertirlo a mono. `_emit_chunk` registrara
la salida y su latencia. `_periodic_flush` sera responsable del resumen periodico.

Si no existe acumulador, el decoder conservara exactamente el comportamiento
actual. La instrumentacion nunca iniciara ni impedira una recuperacion.

## Pruebas

Las pruebas se escribiran antes de la implementacion y cubriran:

- Conteo de exitos y reinicio de la racha tras un descifrado correcto.
- Conteo, clasificacion y racha de excepciones DAVE.
- Deteccion de cambios de estado DAVE sin duplicar transiciones.
- Calculo de resumen, tasas, edades y RMS sin dividir por cero.
- Limitacion de warnings durante fallos consecutivos.
- Registro de callbacks PCM y chunks emitidos.
- Conservacion de las pruebas existentes de listener, transcriber y recovery.

## Fuera de alcance

- Cambiar condiciones, umbrales, cooldowns o eventos de recuperacion.
- Reconectar directamente desde el decoder o desde el diagnostico.
- Cambiar el filtro de audio o el transcriptor.
- Guardar paquetes DAVE, RTP o nuevas copias de audio.
