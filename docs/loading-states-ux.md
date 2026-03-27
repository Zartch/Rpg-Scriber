# Loading States & UX Patterns

Toda operación async en el Web UI usa feedback visual consistente:

## Helpers

- **Button operations**: `withLoading(btn, asyncFn, { loadingText })` — spinner inline + texto + disabled
  - Muestra spinner CSS giratorio junto al texto de carga
  - Deshabilita automáticamente el botón y restaura el estado original al terminar
  - Casos especiales (Export, Extract entities) manejan feedback temporal de éxito en el `.then()`
- **Panel loads**: `withPanelLoading(container, asyncFn)` — overlay semi-transparente con spinner centrado
  - Para cargas de datos grandes (campaign info, session history, browse campaigns)
  - Overlay con `background: rgba(15,17,23,0.7)` y spinner blanco centrado
- **Skeleton screens**: `showSkeleton(container, lineCount)` — placeholder shimmer para listas
  - Para cargas iniciales donde se conoce la forma del contenido
  - Líneas animadas con gradiente `var(--border)` → `#3a3d4a` → `var(--border)`
  - `campaign-summaries.html` usa skeleton HTML directo (sin helpers JS)
- **Background refresh**: `setRefreshing(container, bool)` — opacity reducida sin bloquear
  - Para polling/refresh de contenido existente (session list cada 30s)
  - `opacity: 0.5; filter: blur(1px); pointer-events: none`

## CSS Classes

- `.spinner-inline`, `.loading-overlay`, `.skeleton-line`, `.skeleton-block`, `.content-refreshing`

## Animaciones

- `@keyframes spin` (rotación spinner 0.6s)
- `@keyframes shimmer` (gradiente skeleton 1.5s)

## Guía de uso

Al añadir nuevas operaciones async, usar estos helpers en vez de `btn.disabled/textContent` manual. 47 operaciones catalogadas, 26 son button operations, 21 son panel/background loads.
