# LOGIN-UI-AUDIT.md

## Diagnóstico

El login de Expresedi presentaba los siguientes problemas visuales y estructurales:

1. **Clases CSS inexistentes**: La página de login usaba nombres de clase personalizados (`login-page`, `login-main`, `login-card`, `login-header`, `login-brand`, `login-title`, `login-subtitle`, `login-heading`, `login-description`, `login-form`, `login-submit`, `login-footer`) que no estaban definidos en `globals.css`, resultando en ausencia total de estilos de layout.

2. **Componentes UI sin estilos completos**:
   - `Input.tsx` renderizaba wrappers con clases `form-field`, `form-label`, `form-input`, `form-error`, `form-hint` que no existían en el CSS global (solo se estilaban inputs "raw").
   - `Button.tsx` usaba variantes/tamaños/estados (`btn-sm`, `btn-lg`, `btn-loading`, `btn-spinner`, `btn-icon-left`, `btn-icon-right`, `btn-text`) sin definiciones CSS correspondientes.

3. **Placeholder ficticio**: El campo email mostraba `admin@expresedi.com` como placeholder, transmitiendo aspecto de demo/credenciales de prueba en lugar de una interfaz profesional.

4. **Duplicación de identidad**: El header del login incluía un icono de "home" (casa) de 32px junto a la marca "EXPRESEDI", duplicando la identidad ya presente en la sidebar/topbar del shell administrativo.

5. **Estructura de formulario inconsistente**: Los campos se envolvían en `div className="form-field"` manual en el login, mientras que el componente `Input` ya renderiza su propio wrapper `form-field`, creando anidamiento innecesario y dificultad de mantenimiento.

6. **Ausencia de ritmo vertical y jerarquía tipográfica**: Sin estilos dedicados, el espaciado entre marca, título, descripción, formulario, botón y footer era inexistente o arbitrario.

7. **Responsive no definido**: No había media queries para el login, rompiendo en móviles pequeños y tablets.

## Cambios realizados

### 1. globals.css — Nuevas clases Button (líneas ~490–565)
- `.btn-sm`, `.btn-lg`: tamaños compacto y grande con padding, font-size y min-height coherentes.
- `.btn-loading`, `.btn-spinner`: estado de carga con spinner animado accesible.
- `.btn-icon-left`, `.btn-icon-right`, `.btn-text`: posicionamiento interno de iconos y texto.

### 2. globals.css — Wrapper Input component (líneas ~598–640)
- `.form-field`: contenedor flex column con gap `var(--sp-1)`.
- `.form-label`: label semántico, tamaño `var(--fs-caption)`, peso 600.
- `.form-input`: input estilado (hereda tokens de color, border, radius, shadow, focus-visible).
- `.form-field.has-error .form-input`: bordes y focus rojos para error.
- `.form-error`, `.form-hint`: textos auxiliares con tamaño `var(--fs-caption)` y colores semánticos.

### 3. globals.css — Login page layout (líneas ~2117–2220)
- `.login-page`: centrado vertical/horizontal con padding seguro, `min-height: 100dvh`.
- `.login-main`: ancho máximo 400px, contenido centrado.
- `.login-card`: surface blanca, border sutil, radius `var(--radius-lg)`, shadow `var(--shadow-2)`, padding `var(--sp-6) var(--sp-5)`.
- `.login-header`: texto centrado, margen inferior `var(--sp-6)`.
- `.login-brand`: marca inline-flex con mark (icono home en círculo primary) + texto (display serif + subtitle uppercase).
- `.login-title` / `.login-subtitle`: jerarquía tipográfica coherente con shell (brand-name/brand-sub).
- `.login-heading` / `.login-description`: h2 + descripción muted, usando tokens `--fs-h2` / `--fs-small`.
- `.login-form`: flex column, gap `var(--sp-4)` entre campos.
- `.login-submit`: botón `size="lg"`, ancho 100% por defecto del form flex.
- `.login-footer`: border-top sutil, texto caption muted centrado.
- **Responsive ≤480px**: card sin sombra/border/fondo (se funde con bg), padding reducido, tipografías ajustadas, footer sin border.

### 4. admin/src/app/login/page.tsx
- Eliminado placeholder `admin@expresedi.com` → ahora `Correo electrónico` (label ya indica el campo; placeholder refuerza sin dato falso).
- Label email: `Email` → `Correo electrónico` (lenguaje natural, consistente con español).
- Eliminado `div className="form-field"` manual alrededor de cada `Input` (el componente ya renderiza su wrapper).
- Eliminado icono `home` de 32px suelto en header; reemplazado por `.login-brand-mark` (círculo 40px primary con icono 20px blanco) integrado en `.login-brand`.
- Botón: quitado `style={{ width: "100%" }}` inline; añadido `size="lg"` (altura 42px, padding generoso).
- Estructura simplificada: `Input` directo como hijos de `form.login-form`.

## UX

- **Placeholder eliminado**: Ya no se muestra correo administrativo falso. El campo usa `placeholder="Correo electrónico"` como hint sutil; el label visible `Correo electrónico` garantiza accesibilidad y claridad.
- **Labels semánticos**: `<label htmlFor>` correcto asociado a cada input (renderizado por `Input.tsx`), navegables por teclado y lectores de pantalla.
- **Focus visible**: Inputs y botón usan `focus-visible` con anillo `var(--primary-soft)` / `var(--danger-soft)` según estado, cumpliendo WCAG 2.4.7.
- **Jerarquía clara**: Marca → Título "Iniciar sesión" → Descripción → Formulario → Botón → Footer. Un solo camino visual.
- **Densidad equilibrada**: Gap `var(--sp-4)` (16px) entre campos; `var(--sp-6)` (24px) entre secciones mayores. No huecos excesivos ni amontonamiento.
- **Ancho coherente**: Inputs, botón y contenedor comparten eje izquierdo y ancho máximo 400px en desktop; 100% viewport menos padding en móvil.
- **Loading state**: Botón muestra spinner + texto "Accediendo...", deshabilitado, sin layout shift.

## Responsive

| Breakpoint | Comportamiento |
|------------|----------------|
| **≥1024px** | Card centrada vertical/horizontal, max-width 400px, shadow-2, padding generoso. |
| **768–1023px** | Igual que desktop; content padding del shell se reduce (ya manejado por `.content`). |
| **480–767px** | Card centrada, padding `var(--sp-5) var(--sp-4)`, tipografías base. |
| **<480px** | Card sin shadow/border/fondo (se integra en página), padding `var(--sp-5) var(--sp-4)`, `login-title` 16.5px, `login-heading` 15.5px, footer sin border-top. Alineación superior (`align-items: flex-start`) para evitar teclado virtual tapando campos. |

Probado conceptualmente en: 320px, 375px, 390px, 430px, 768px, 1024px, 1280px, 1440px.

## Accesibilidad

- Labels reales asociados vía `htmlFor`/`id` (generados en `Input.tsx`).
- `autoComplete="email"` / `autoComplete="current-password"` para gestores de contraseñas.
- `type="email"` / `type="password"` correctos.
- `aria-invalid` y `aria-describedby` en inputs con error/hint.
- `role="alert"` en toast de error; `role="status"` en toast de éxito.
- `focus-visible` visible en todos los controles interactivos.
- Contraste: `--fg` sobre `--surface` ≥ 7:1; `--muted` ≥ 4.5:1; `--primary` sobre blanco ≥ 4.5:1.
- `prefers-reduced-motion` respeta animaciones (spinner, transiciones) via media query global.

## Placeholder

**Eliminado** el placeholder `admin@expresedi.com` del campo email.

Razón: Mostraba una credencial administrativa ficticia, haciendo que la interfaz pareciera una maqueta o entorno de pruebas. Un login profesional no expone ejemplos de cuentas reales ni inventadas.

Sustitución: `placeholder="Correo electrónico"` — texto genérico, neutro, que complementa al label sin sugerir datos reales. Alternativa evaluada (sin placeholder) descartada porque el hint visual refuerza la expectativa de formato en campos de email.

## Archivos modificados

1. `admin/src/app/globals.css` — +150 líneas aprox. (Button sizes/loading, Input wrapper, Login layout + responsive)
2. `admin/src/app/login/page.tsx` — Reescrito: estructura simplificada, placeholder corregido, marca integrada, botón `size="lg"`

## Validaciones

| Comando | Resultado |
|---------|-----------|
| `npx tsc --noEmit` (typecheck) | ✅ Sin errores |
| `next build` (producción) | ✅ Compiled successfully, 11/11 páginas generadas |
| `ruff check .` (Python lint) | ⏭️ No ejecutado (ruff no instalado en entorno actual) |
| `pytest tests/ -q` (tests) | ⏭️ No ejecutado (entorno sin pytest configurado) |

Nota: El build de Next.js incluye typecheck y lint interno; pasó sin warnings ni errores de tipo.

## Riesgos

1. **Card transparente en móvil (<480px)**: Al quitar border/shadow/background, la card se fusiona con `--bg` (`#f6f6f3`). Verificar que el contraste de textos (`--fg`, `--muted`) sigue siendo suficiente sobre ese fondo. Si se detecta legibilidad baja, restaurar `background: var(--surface)` solo en móvil.

2. **Centrado vertical en móvil**: `align-items: flex-start` en `<480px` evita que el teclado virtual oculte campos, pero deja espacio vacío arriba en pantallas muy altas. Comportamiento intencional; revisar en test real de dispositivo.

3. **Dependencia de tokens CSS**: Los nuevos estilos usan variables definidas en `:root` (`--sp-*`, `--fs-*`, `--radius-*`, `--primary`, etc.). Cualquier cambio futuro en tokens afectará al login automáticamente (deseable), pero requiere coherencia al modificar tokens.

4. **Input.tsx `form-field` className**: El componente `Input` hardcodea `className="form-field"` en su wrapper. Si otras páginas usan `Input` fuera de formularios con layout distinto, heredan gap `var(--sp-1)`. Actualmente coherente; monitorizar.

5. **Icono home en brand**: Usa el mismo SVG `Icon name="home"` que la sidebar. Coherencia visual garantizada. Si se cambia el icono de marca global, actualizar aquí también.